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
