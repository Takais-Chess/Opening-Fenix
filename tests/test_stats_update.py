import pytest
import datetime
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from unittest.mock import patch
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.core.db.models import TrainingData, Position

@pytest.fixture
def test_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

@pytest.fixture
def window(test_app, mock_user_dir, sample_repertoire):
    """Creates a MainWindow connected to our sample repertoire."""
    win = MainWindow(profile_name="TestUser")
    win.change_repertoire(sample_repertoire)
    return win

def test_stats_update_on_repertoire_switch(window, sample_repertoire):
    """Test that the big donut chart updates when switching repertoires."""
    # Create a dummy repertoire to switch to
    dummy_repo = "DummyRepo"
    b = window.repertoire_manager
    b.set_active_repertoire(dummy_repo)
    # Add one move to the dummy repo so stats aren't completely empty if it expects data
    b.repo_session.add(Position(fen="dummy"))
    b.repo_session.commit()
    
    # Track calls to update_stats
    updates = []
    original_update = window.progress_bar.update_stats
    def mock_update(*args, **kwargs):
        updates.append(args)
        original_update(*args, **kwargs)
    window.progress_bar.update_stats = mock_update

    # Switch back to the sample repertoire
    window.change_repertoire(sample_repertoire)
    
    # Process pending Qt events (since we use a QTimer for debounce)
    QApplication.processEvents()
    
    assert len(updates) > 0, "Big donut chart was not updated after switching repertoires"

def test_stats_update_after_training_move(window, sample_repertoire):
    """Test that the big donut chart updates immediately after a training move."""
    # Force new mode to ensure we have something to train
    window.training_mode = 'new'
    window.load_next_challenge()
    
    if window.current_move_obj is None:
        new, due, dist = window.training_manager.get_stats()
        print(f"DEBUG: stats were new={new}, due={due}, dist={dist}")
        # Try once more with fresh cache
        window.training_manager.on_repertoire_changed()
        window.load_next_challenge()
        
    assert window.current_move_obj is not None, "No training move available in sample repertoire"
    
    window.skip_all_animations()
    
    # Setup the mock to track updates
    with patch.object(window, 'update_stats_display') as mock_update:
        # Simulate a correct move
        window.button_state = 'waiting_for_move'
        target_move = window.current_move_obj.uci
        
        window.check_user_move(chess.Move.from_uci(target_move))
        
        # We must process events to let the timer fire. Use QTest.qWait to spin the event loop properly.
        QTest.qWait(200)

        assert mock_update.called, "Big donut chart was not updated after executing a training move"
