import os
import shutil
import pytest
import chess
from unittest.mock import patch, MagicMock
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.threads import PGNImportThread
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.utils import get_repertoire_db_path, parse_comment

SAMPLE_PGN_WITH_SIDELINES = """[Event "Test PGN with Subvariations"]
[Site "?"]
[Date "2026.01.01"]
[Round "?"]
[White "Player1"]
[Black "Player2"]
[Result "*"]

1. e4 {King's Pawn} ( 1. d4 {Queen's Pawn} 1... d5 ) 1... e5 {Open Game} ( 1... c5 {Sicilian Defense} 2. Nf3 ) 2. Nf3 Nc6 3. Bb5 a6 *
"""

@pytest.fixture
def pgn_file_with_sidelines(tmp_path):
    p = tmp_path / "sample_with_sidelines.pgn"
    p.write_text(SAMPLE_PGN_WITH_SIDELINES, encoding="utf-8")
    return str(p)

def test_import_pgn_to_db_subvariations_as_comments(mock_user_dir, pgn_file_with_sidelines):
    repo_name = "Test_PGN_Subvar_Enabled"
    db_path = get_repertoire_db_path(repo_name)
    repo_dir = os.path.dirname(db_path)

    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir, ignore_errors=True)

    try:
        success, msg = import_pgn_to_db(
            pgn_path=pgn_file_with_sidelines,
            repo_name=repo_name,
            side="w",
            level_name="Level 1",
            level_order=1,
            target_lang="en",
            subvariations_as_comments=True
        )
        assert success is True, f"Import failed: {msg}"

        db = DatabaseManager(db_path)
        session = db.get_session()

        # 1. Mainline has 6 plies: e4, e5, Nf3, Nc6, Bb5, a6
        all_moves = session.query(Move).all()
        assert len(all_moves) == 6, f"Expected exactly 6 mainline moves, found {len(all_moves)}: {[m.san for m in all_moves]}"
        sans = {m.san for m in all_moves}
        assert sans == {"e4", "e5", "Nf3", "Nc6", "Bb5", "a6"}

        # 2. Check that sidelines (1. d4, 1... c5) were NOT created as database moves
        assert "d4" not in sans
        assert "c5" not in sans

        # 3. Check position comments after 1. e4
        board = chess.Board()
        board.push_san("e4")
        fen_e4 = " ".join(board.fen().split(" ")[:4])
        pos_e4 = session.query(Position).filter_by(fen=fen_e4).first()
        assert pos_e4 is not None
        c_e4 = parse_comment(pos_e4.comment, lang="en")
        assert "King's Pawn" in c_e4
        assert "1. d4" in c_e4
        assert "Queen's Pawn" in c_e4

        # 4. Check position comments after 1... e5
        board.push_san("e5")
        fen_e5 = " ".join(board.fen().split(" ")[:4])
        pos_e5 = session.query(Position).filter_by(fen=fen_e5).first()
        assert pos_e5 is not None
        c_e5 = parse_comment(pos_e5.comment, lang="en")
        assert "Open Game" in c_e5
        assert "1... c5" in c_e5
        assert "Sicilian Defense" in c_e5

        session.close()
        db.close()
    finally:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)

def test_import_pgn_to_db_subvariations_as_moves(mock_user_dir, pgn_file_with_sidelines):
    repo_name = "Test_PGN_Subvar_Disabled"
    db_path = get_repertoire_db_path(repo_name)
    repo_dir = os.path.dirname(db_path)

    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir, ignore_errors=True)

    try:
        success, msg = import_pgn_to_db(
            pgn_path=pgn_file_with_sidelines,
            repo_name=repo_name,
            side="w",
            level_name="Level 1",
            level_order=1,
            target_lang="en",
            subvariations_as_comments=False
        )
        assert success is True, f"Import failed: {msg}"

        db = DatabaseManager(db_path)
        session = db.get_session()

        # Both mainline moves and subvariations must exist in Move table
        all_moves = session.query(Move).all()
        sans = {m.san for m in all_moves}
        assert "d4" in sans
        assert "c5" in sans
        assert len(all_moves) > 6

        session.close()
        db.close()
    finally:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)

def test_pgn_import_thread_forwards_subvariations_flag(qtbot):
    with patch("opening_fenix.core.threads.import_pgn_to_db") as mock_import:
        mock_import.return_value = (True, "OK")

        thread = PGNImportThread(
            pgn_path="dummy.pgn",
            repo_name="dummy_repo",
            side="w",
            level_name="Level 1",
            level_order=1,
            target_lang="en",
            subvariations_as_comments=True
        )
        thread.start()
        thread.wait(3000)

        mock_import.assert_called_once()
        _, kwargs = mock_import.call_args
        assert kwargs.get("subvariations_as_comments") is True

def test_creator_window_pgn_dialog_checkbox(qtbot, creator_window, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    pgn_path = tmp_path / "test.pgn"
    pgn_path.write_text("1. e4 e5 *")

    dialog_captured = []

    def intercept_exec(self):
        if hasattr(self, "chk_subvariations"):
            dialog_captured.append(self)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", intercept_exec)
    creator_window._start_pgn_import(str(pgn_path))

    assert len(dialog_captured) == 1
    dlg = dialog_captured[0]
    assert hasattr(dlg, "chk_subvariations")
    assert dlg.chk_subvariations.isChecked() is True

    # Test toggling
    dlg.chk_subvariations.setChecked(False)
    assert dlg.chk_subvariations.isChecked() is False
    dlg.chk_subvariations.setChecked(True)
    assert dlg.chk_subvariations.isChecked() is True
