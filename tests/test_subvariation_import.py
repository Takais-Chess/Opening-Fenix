import os
import shutil
import pytest
import chess
from opening_fenix.core.services.course_import_service import (
    CourseImportPlan,
    execute_course_import,
    CATEGORY_LEVEL_1,
    CATEGORY_LEVEL_2
)
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.utils import get_repertoire_db_path, get_user_dir, parse_comment

PGN_PATH = r"C:\Users\Felix\Downloads\13.pgn"

@pytest.mark.skipif(not os.path.exists(PGN_PATH), reason="13.pgn not found in Downloads")
def test_import_13_pgn_subvariations_as_comments():
    repo_name = "Test_KID_13_Subvar_Enabled"
    db_path = get_repertoire_db_path(repo_name)
    repo_dir = os.path.dirname(db_path)

    # Clean up before test
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir, ignore_errors=True)

    try:
        plan = CourseImportPlan(
            repo_name=repo_name,
            side="b",
            chapter_targets={},
            pgn_paths=[PGN_PATH],
            target_lang="en",
            archive_original_pgns=False,
            subvariations_as_comments=True
        )

        result = execute_course_import(plan)
        assert result.success, f"Import failed: {result.message}"

        db = DatabaseManager(db_path)
        session = db.get_session()

        # 1. Verify that only mainline moves exist in Move table (18 plies)
        all_moves = session.query(Move).all()
        assert len(all_moves) == 18, f"Expected exactly 18 mainline moves, but found {len(all_moves)}"

        # 2. Check that sidelines (6... e5, 8. d5, 8... Nc5) were NOT created as Moves
        board = chess.Board()
        for mv in ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6", "Nf3", "O-O", "Be2"]:
            board.push_san(mv)
        fen_be2 = " ".join(board.fen().split(" ")[:4])
        pos_be2 = session.query(Position).filter_by(fen=fen_be2).first()
        assert pos_be2 is not None

        moves_from_be2 = session.query(Move).filter_by(from_position_id=pos_be2.id).all()
        assert len(moves_from_be2) == 1, f"Expected only 1 move (Nbd7) from Be2, found {[m.san for m in moves_from_be2]}"
        assert moves_from_be2[0].san == "Nbd7"

        # 3. Verify comments on position after 6... Nbd7
        board.push_san("Nbd7")
        fen_nbd7 = " ".join(board.fen().split(" ")[:4])
        pos_nbd7 = session.query(Position).filter_by(fen=fen_nbd7).first()
        assert pos_nbd7 is not None
        assert pos_nbd7.comment is not None

        c_text = parse_comment(pos_nbd7.comment, lang="en")
        assert "My pet line. I'll cover the mainline Classical" in c_text
        assert "6... e5" in c_text
        assert "The 6... Nbd7 variation is less about remembering long lines of theory" in c_text
        assert "dull Exchange Variation" in c_text

        # 4. Verify comments on position after 8. Be3
        for mv in ["O-O", "e5", "Be3"]:
            board.push_san(mv)
        fen_be3 = " ".join(board.fen().split(" ")[:4])
        pos_be3 = session.query(Position).filter_by(fen=fen_be3).first()
        assert pos_be3 is not None
        assert pos_be3.comment is not None

        c_text_be3 = parse_comment(pos_be3.comment, lang="en")
        assert "White's overwhelmingly most popular choice" in c_text_be3
        assert "With the knight on c6 8. d5 is an automatic reaction" in c_text_be3
        assert "8... Nc5" in c_text_be3

        session.close()
    finally:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)

@pytest.mark.skipif(not os.path.exists(PGN_PATH), reason="13.pgn not found in Downloads")
def test_import_13_pgn_subvariations_as_moves_when_disabled():
    repo_name = "Test_KID_13_Subvar_Disabled"
    db_path = get_repertoire_db_path(repo_name)
    repo_dir = os.path.dirname(db_path)

    # Clean up before test
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir, ignore_errors=True)

    try:
        plan = CourseImportPlan(
            repo_name=repo_name,
            side="b",
            chapter_targets={},
            pgn_paths=[PGN_PATH],
            target_lang="en",
            archive_original_pgns=False,
            subvariations_as_comments=False
        )

        result = execute_course_import(plan)
        assert result.success, f"Import failed: {result.message}"

        db = DatabaseManager(db_path)
        session = db.get_session()

        # When disabled, all subvariations become playable database moves (> 18 moves)
        all_moves = session.query(Move).all()
        assert len(all_moves) > 18, f"Expected more than 18 moves when subvariations are imported as moves, got {len(all_moves)}"

        # Verify that move 6... e5 exists from position after 6. Be2
        board = chess.Board()
        for mv in ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6", "Nf3", "O-O", "Be2"]:
            board.push_san(mv)
        fen_be2 = " ".join(board.fen().split(" ")[:4])
        pos_be2 = session.query(Position).filter_by(fen=fen_be2).first()
        assert pos_be2 is not None

        moves_from_be2 = session.query(Move).filter_by(from_position_id=pos_be2.id).all()
        # Should contain both Nbd7 and e5
        sans_from_be2 = [m.san for m in moves_from_be2]
        assert "Nbd7" in sans_from_be2
        assert "e5" in sans_from_be2

        session.close()
    finally:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)

