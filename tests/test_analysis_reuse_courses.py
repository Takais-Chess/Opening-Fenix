import os
import json
import pytest
from unittest.mock import MagicMock, patch

from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.services.analysis_sync_service import (
    normalize_fen,
    sync_analysis_data_from_other_repertoires
)
from opening_fenix.core.services.analysis_service import run_db_analysis


def test_normalize_fen():
    full_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    norm = normalize_fen(full_fen)
    assert norm == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    assert normalize_fen("") == ""
    assert normalize_fen(None) == ""


def test_sync_analysis_data_basic(mock_user_dir, sample_repertoire):
    """
    Test copying analysis from course A (sample_repertoire) into course B.
    """
    # 1. Put depth 20 analysis into sample_repertoire
    db_path_a = get_repertoire_db_path(sample_repertoire)
    db_a = DatabaseManager(db_path_a)
    session_a = db_a.get_session()
    pos_a = session_a.query(Position).filter(Position.fen.like("% w %")).first()
    pos_a.analysis_depth = 20
    pos_a.good_moves = json.dumps(["e2e4", "d2d4"])
    pos_a.engine_eval = 25
    session_a.commit()
    fen_to_copy = pos_a.fen
    session_a.close()
    db_a.close()

    # 2. Create second repertoire "Course_B"
    db_path_b = get_repertoire_db_path("Course_B")
    db_b = DatabaseManager(db_path_b)
    session_b = db_b.get_session()
    
    # Add identical position but without analysis
    pos_b = Position(fen=fen_to_copy, analysis_depth=None, good_moves=None)
    session_b.add(pos_b)
    session_b.commit()
    pos_b_id = pos_b.id

    # 3. Run sync targeting depth 18 (Course A has depth 20 >= 18)
    with patch("opening_fenix.core.services.repertoire_service.RepertoireService.get_all_repertoires", return_value=[sample_repertoire, "Course_B"]):
        copied = sync_analysis_data_from_other_repertoires(
            target_session=session_b,
            current_repo_name="Course_B",
            target_depth=18,
            player_color="w"
        )
        assert copied == 1

        updated_pos = session_b.query(Position).get(pos_b_id)
        assert updated_pos.analysis_depth == 20  # Adopted the higher depth 20!
        assert json.loads(updated_pos.good_moves) == ["d2d4", "e2e4"] or json.loads(updated_pos.good_moves) == ["e2e4", "d2d4"]
        assert updated_pos.engine_eval == 25

    session_b.close()
    db_b.close()


def test_sync_analysis_selects_highest_depth(mock_user_dir, sample_repertoire):
    """
    When multiple courses have analysis for the same FEN at or above target_depth,
    the sync chooses the one with the highest depth (e.g. depth 25 over depth 20).
    """
    target_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"

    # Course A: depth 20
    db_a = DatabaseManager(get_repertoire_db_path("Course_A"))
    s_a = db_a.get_session()
    s_a.add(Position(fen=target_fen, analysis_depth=20, good_moves=json.dumps(["e2e4"]), engine_eval=15))
    s_a.commit()
    s_a.close()
    db_a.close()

    # Course B: depth 25
    db_b = DatabaseManager(get_repertoire_db_path("Course_B"))
    s_b = db_b.get_session()
    s_b.add(Position(fen=target_fen, analysis_depth=25, good_moves=json.dumps(["d2d4", "e2e4"]), engine_eval=30))
    s_b.commit()
    s_b.close()
    db_b.close()

    # Target Course C: target depth 18
    db_c = DatabaseManager(get_repertoire_db_path("Course_C"))
    s_c = db_c.get_session()
    pos_c = Position(fen=target_fen, analysis_depth=None, good_moves=None)
    s_c.add(pos_c)
    s_c.commit()
    pos_c_id = pos_c.id

    with patch("opening_fenix.core.services.repertoire_service.RepertoireService.get_all_repertoires", return_value=["Course_A", "Course_B", "Course_C"]):
        copied = sync_analysis_data_from_other_repertoires(
            target_session=s_c,
            current_repo_name="Course_C",
            target_depth=18,
            player_color="w"
        )
        assert copied == 1

        updated_pos = s_c.query(Position).get(pos_c_id)
        assert updated_pos.analysis_depth == 25  # Picked depth 25 over 20
        assert "d2d4" in json.loads(updated_pos.good_moves)
        assert updated_pos.engine_eval == 30

    s_c.close()
    db_c.close()


def test_sync_analysis_ignores_insufficient_depth(mock_user_dir):
    """
    If another course has analysis below target_depth (e.g. depth 14 when target is 18),
    it is NOT copied.
    """
    target_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"

    # Course A: depth 14 (< 18)
    db_a = DatabaseManager(get_repertoire_db_path("Course_A"))
    s_a = db_a.get_session()
    s_a.add(Position(fen=target_fen, analysis_depth=14, good_moves=json.dumps(["e2e4"])))
    s_a.commit()
    s_a.close()
    db_a.close()

    # Target Course B: target depth 18
    db_b = DatabaseManager(get_repertoire_db_path("Course_B"))
    s_b = db_b.get_session()
    pos_b = Position(fen=target_fen, analysis_depth=None, good_moves=None)
    s_b.add(pos_b)
    s_b.commit()

    with patch("opening_fenix.core.services.repertoire_service.RepertoireService.get_all_repertoires", return_value=["Course_A", "Course_B"]):
        copied = sync_analysis_data_from_other_repertoires(
            target_session=s_b,
            current_repo_name="Course_B",
            target_depth=18,
            player_color="w"
        )
        assert copied == 0
        assert pos_b.analysis_depth is None
        assert pos_b.good_moves is None

    s_b.close()
    db_b.close()


def test_sync_preserves_target_repertoire_move(mock_user_dir):
    """
    When copying good_moves from another course, the active repertoire move
    in the target course must be preserved in good_moves.
    """
    target_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"

    # Course A: analyzed with good_moves = ["e2e4"]
    db_a = DatabaseManager(get_repertoire_db_path("Course_A"))
    s_a = db_a.get_session()
    s_a.add(Position(fen=target_fen, analysis_depth=20, good_moves=json.dumps(["e2e4"])))
    s_a.commit()
    s_a.close()
    db_a.close()

    # Course B: has repertoire move "c2c4" (English opening)
    db_b = DatabaseManager(get_repertoire_db_path("Course_B"))
    s_b = db_b.get_session()
    pos_b = Position(fen=target_fen, analysis_depth=None, good_moves=None)
    to_pos_b = Position(fen="rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq -", analysis_depth=None)
    s_b.add_all([pos_b, to_pos_b])
    s_b.flush()

    move_b = Move(from_position_id=pos_b.id, to_position_id=to_pos_b.id, uci="c2c4", san="c4")
    s_b.add(move_b)
    s_b.flush()
    rep_move_b = RepertoireMove(move_id=move_b.id, is_active=True)
    s_b.add(rep_move_b)
    s_b.commit()
    pos_b_id = pos_b.id

    with patch("opening_fenix.core.services.repertoire_service.RepertoireService.get_all_repertoires", return_value=["Course_A", "Course_B"]):
        copied = sync_analysis_data_from_other_repertoires(
            target_session=s_b,
            current_repo_name="Course_B",
            target_depth=18,
            player_color="w"
        )
        assert copied == 1

        updated_pos = s_b.query(Position).get(pos_b_id)
        moves = json.loads(updated_pos.good_moves)
        assert "e2e4" in moves
        assert "c2c4" in moves  # Repertoire move retained!

    s_b.close()
    db_b.close()


@patch("chess.engine.SimpleEngine.popen_uci")
def test_run_db_analysis_bypasses_engine_when_courses_satisfy_all(mock_popen, mock_user_dir, sample_repertoire):
    """
    If all positions in target course are satisfied by other courses,
    run_db_analysis should return success without ever spawning Stockfish.
    """
    # 1. Populate sample_repertoire with depth 20 analysis
    db_path_a = get_repertoire_db_path(sample_repertoire)
    db_a = DatabaseManager(db_path_a)
    s_a = db_a.get_session()
    for p in s_a.query(Position).all():
        p.analysis_depth = 20
        p.good_moves = json.dumps(["e2e4"])
    s_a.commit()
    s_a.close()
    db_a.close()

    # 2. Target course with same positions but depth None
    db_path_b = get_repertoire_db_path("Target_Course")
    db_b = DatabaseManager(db_path_b)
    s_b = db_b.get_session()
    s_b.add(Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -", analysis_depth=None))
    s_b.commit()
    s_b.close()
    db_b.close()

    with patch("opening_fenix.core.services.repertoire_service.RepertoireService.get_all_repertoires", return_value=[sample_repertoire, "Target_Course"]):
        with patch("opening_fenix.core.services.analysis_service.get_meta", return_value="w"):
            success, msg = run_db_analysis(
                "Target_Course",
                "dummy_engine",
                depth=18,
                threads=1,
                reuse_other_courses=True
            )

            assert success is True
            assert "übernommen" in msg
            # Engine was NEVER spawned because cross-course sync satisfied all positions
            mock_popen.assert_not_called()
