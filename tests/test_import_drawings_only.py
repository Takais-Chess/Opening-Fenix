import json
import os
from unittest.mock import MagicMock, patch

import chess
import pytest

from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Move, Position, RepertoireLevel, RepertoireMove
from opening_fenix.core.services.import_service import import_pgn_drawings_only, import_pgn_to_db
from opening_fenix.core.threads import PGNImportThread
from opening_fenix.core.utils import get_repertoire_db_path, parse_chessbase_annotations


def _setup_base_repertoire(tmp_path, repo_name: str):
    base_pgn = tmp_path / "base.pgn"
    base_pgn.write_text(
        '[Event "Base"]\n[Result "*"]\n\n1. e4 {Existing DE comment} e5 {[%csl Rd4] Existing} *\n',
        encoding="utf-8",
    )
    ok, _ = import_pgn_to_db(str(base_pgn), repo_name, "w", "Level 1", 1, target_lang="de")
    assert ok is True
    return get_repertoire_db_path(repo_name)


def test_import_drawings_only_merges_and_ignores_moves_levels_and_text(mock_user_dir, tmp_path):
    repo_name = "DrawingsOnlyRepo"
    db_path = _setup_base_repertoire(tmp_path, repo_name)

    # Add a multilingual comment to the position after 1. e4
    db = DatabaseManager(db_path)
    session = db.get_session()
    board_e4 = chess.Board()
    board_e4.push_san("e4")
    fen_e4 = " ".join(board_e4.fen().split(" ")[:4])
    pos_e4 = session.query(Position).filter_by(fen=fen_e4).first()
    pos_e4.comment = json.dumps({"de": "[%cal Ye2e4] Deutsch", "en": "[%cal Ye2e4] English"})
    session.commit()

    initial_pos_count = session.query(Position).count()
    initial_move_count = session.query(Move).count()
    initial_rm_count = session.query(RepertoireMove).count()
    initial_level_count = session.query(RepertoireLevel).count()
    session.close()
    db.close()

    # PGN has:
    # - root drawing [%csl Ge4]
    # - 1. e4 with [%cal Ge2e4] [%csl Bf4] and ignored text
    # - 1... e5 with [%cal Gg1f3] and ignored text (should merge with existing [%csl Rd4])
    # - 2. Nf3 Nc6 (NOT in repertoire -> must NOT be added!)
    draw_pgn = tmp_path / "drawings.pgn"
    draw_pgn.write_text(
        '[Event "Drawings"]\n[Result "*"]\n\n'
        '{[%csl Ge4] Ignored root text} '
        '1. e4 {[%cal Ge2e4] [%csl Bf4] Ignored e4 text} '
        'e5 {[%cal Gg1f3] Ignored e5 text} '
        '2. Nf3 {[%cal Gf3e5] New move text} Nc6 {[%csl Rc6]} *\n',
        encoding="utf-8",
    )

    progress_values = []
    success, msg = import_pgn_drawings_only(str(draw_pgn), repo_name, progress_callback=progress_values.append)
    assert success is True
    assert "3" in msg  # root, after 1. e4, after 1... e5

    db = DatabaseManager(db_path)
    session = db.get_session()
    try:
        # No new positions, moves, repertoire moves, or levels
        assert session.query(Position).count() == initial_pos_count
        assert session.query(Move).count() == initial_move_count
        assert session.query(RepertoireMove).count() == initial_rm_count
        assert session.query(RepertoireLevel).count() == initial_level_count

        # Root position got [%csl Ge4] without root text
        start_fen = " ".join(chess.Board().fen().split(" ")[:4])
        pos_root = session.query(Position).filter_by(fen=start_fen).first()
        parsed_root = parse_chessbase_annotations(pos_root.comment)
        assert (chess.E4, "green") in parsed_root["highlights"]
        assert parsed_root["clean_text"] == ""

        # Position after 1. e4 kept multilingual text and merged [%csl Bf4] + updated [%cal Ge2e4]
        pos_e4 = session.query(Position).filter_by(fen=fen_e4).first()
        comment_dict = json.loads(pos_e4.comment)
        assert "Deutsch" in comment_dict["de"]
        assert "English" in comment_dict["en"]
        assert "Ignored e4 text" not in pos_e4.comment
        parsed_de = parse_chessbase_annotations(comment_dict["de"])
        assert (chess.F4, "blue") in parsed_de["highlights"]
        assert (chess.E2, chess.E4, "green") in parsed_de["arrows"]

        # Position after 1... e5 kept existing text + [%csl Rd4] and added [%cal Gg1f3]
        board_e5 = chess.Board()
        board_e5.push_san("e4")
        board_e5.push_san("e5")
        fen_e5 = " ".join(board_e5.fen().split(" ")[:4])
        pos_e5 = session.query(Position).filter_by(fen=fen_e5).first()
        parsed_e5 = parse_chessbase_annotations(pos_e5.comment)
        assert parsed_e5["clean_text"] == "Existing"
        assert (chess.D4, "red") in parsed_e5["highlights"]
        assert (chess.G1, chess.F3, "green") in parsed_e5["arrows"]
    finally:
        session.close()
        db.close()


def test_import_drawings_only_missing_repo(mock_user_dir, tmp_path):
    pgn = tmp_path / "empty.pgn"
    pgn.write_text("1. e4 {[%cal Ge2e4]} *\n", encoding="utf-8")
    success, _ = import_pgn_drawings_only(str(pgn), "DoesNotExist")
    assert success is False


def test_import_drawings_only_no_drawings_in_pgn(mock_user_dir, tmp_path):
    repo_name = "NoDrawingsRepo"
    _setup_base_repertoire(tmp_path, repo_name)
    pgn = tmp_path / "nodraw.pgn"
    pgn.write_text("1. e4 {Just text} e5 *\n", encoding="utf-8")
    success, _ = import_pgn_drawings_only(str(pgn), repo_name)
    assert success is False


def test_pgn_import_thread_drawings_only_dispatch():
    with patch("opening_fenix.core.threads.import_pgn_drawings_only", return_value=(True, "ok")) as mock_draw, \
         patch("opening_fenix.core.threads.import_pgn_to_db") as mock_full:
        thread = PGNImportThread("test.pgn", "Repo", "w", "", 1, drawings_only=True)
        results = []
        thread.finished_signal.connect(lambda s, m: results.append((s, m)))
        thread.run()

        mock_draw.assert_called_once()
        mock_full.assert_not_called()
        assert results == [(True, "ok")]
