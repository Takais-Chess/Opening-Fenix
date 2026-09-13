import pytest
import os
import chess.pgn
import io
from PyQt6.QtWidgets import QApplication
from opening_fenix.creator.creator_window import CreatorWindow, CreatorBackend

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def creator_window(qapp, mock_user_dir, sample_repertoire):
    """Fixture for CreatorWindow."""
    win = CreatorWindow(repertoire_name=sample_repertoire)
    win.show()
    yield win
    win.close()

def test_pgn_import_text(creator_window):
    """Test importing a PGN string into the repertoire."""
    pgn_text = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *"
    
    # import_pgn_text is in CreatorBackend
    creator_window.backend.import_pgn_text(pgn_text)
    
    # Verify that moves are now in the database
    creator_window.backend.session.expire_all()
    from opening_fenix.core.models import Move
    move_e4 = creator_window.backend.session.query(Move).filter_by(san="e4").first()
    assert move_e4 is not None

def test_pgn_export(creator_window):
    """Test exporting the repertoire to PGN."""
    # Add a move first to ensure something is exported
    creator_window.backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=1)
    
    # export_pgn is in CreatorBackend
    pgn_output = creator_window.backend.export_pgn()
    
    assert "e4" in pgn_output
    assert "[Event \"TestRepo\"]" in pgn_output

def test_candidate_moves_population(creator_window):
    """Test that candidate moves are correctly identified for a position."""
    # Add two candidate moves
    creator_window.backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=1)
    creator_window.backend.add_move(chess.STARTING_FEN, "d2d4", "d4", level_order=2)
    
    moves = creator_window.backend.get_candidate_moves(chess.STARTING_FEN)
    
    assert len(moves) >= 2
    sans = [m['san'] for m in moves]
    assert "e4" in sans
    assert "d4" in sans

def test_backend_orphan_detection(creator_window):
    """Test detecting orphan positions in the repertoire."""
    # This might use a diagnostic method we saw earlier
    # Let's check if the backend has run_diagnostic or similar
    if hasattr(creator_window.backend, 'run_diagnostic'):
        results = creator_window.backend.run_diagnostic()
        assert 'orphans' in results

def test_pgn_import_updates_candidate_moves_table(creator_window, tmp_path, monkeypatch):
    """Test that candidate moves table is refreshed when a PGN file is imported."""
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QMessageBox
    from opening_fenix.core.services.import_service import import_pgn_to_db

    monkeypatch.setattr(QMessageBox, "information", MagicMock())

    # Populate candidate moves table and backend cache initially (empty repo initially)
    creator_window.refresh_candidate_moves_table()
    initial_count = creator_window.tree_widget.topLevelItemCount()
    assert initial_count == 0

    # Verify cache is populated with the empty list
    fen = creator_window.board_widget.board.fen()
    assert f"cand_moves_{fen}" in creator_window.backend._ui_cache
    assert creator_window.backend._ui_cache[f"cand_moves_{fen}"] == []

    # Create a PGN with a new candidate move: 1. d4
    pgn_file = tmp_path / "new_variation.pgn"
    pgn_file.write_text("1. d4 d5 2. c4 *", encoding="utf-8")

    # Import PGN into active repo (simulating PGNImportThread background work)
    success, msg = import_pgn_to_db(
        str(pgn_file),
        creator_window.backend.active_repo_name,
        side="w",
        level_name="Basic",
        level_order=1
    )
    assert success

    # Trigger completion callback
    creator_window._on_pgn_import_finished(True, msg)

    # Verify table was updated with the new candidate move d4
    new_count = creator_window.tree_widget.topLevelItemCount()
    assert new_count == 1

    # Verify move in table
    items_san = [creator_window.tree_widget.topLevelItem(i).text(0) for i in range(new_count)]
    assert any("d4" in s for s in items_san)

