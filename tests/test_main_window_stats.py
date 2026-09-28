import pytest
import os
import json
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QTimer
from opening_fenix.gui.main_window import MainWindow

@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire, monkeypatch):
    """Fixture for MainWindow with sample repertoire and necessary mocks."""
    # Mock sounds to avoid ALSA/DirectShow errors in CI
    monkeypatch.setattr("opening_fenix.gui.main_window.MainWindow.play_sound", lambda *args: None)
    
    # Mock config
    config_path = os.path.join(mock_user_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"lichess_token": "mock_token", "theme": "dark"}, f)
    
    win = MainWindow(profile_name="TestProfile")
    win.repertoire_manager.set_active_repertoire(sample_repertoire)
    win.show()
    yield win
    win.close()

def test_elo_display_updates(main_window, qapp):
    """Test that the Elo display updates correctly."""
    # Set a mock Elo
    main_window.training_manager.get_current_elo = MagicMock(return_value=1234)
    
    # Trigger update
    main_window._do_update_stats_display()
    qapp.processEvents()
    
    # Check label
    assert "1234" in main_window.lbl_elo.text()

def test_stats_update_debounce(main_window, qapp):
    """Test that stats updates are debounced via timer."""
    # Start timer
    main_window.update_stats_display()
    assert main_window.stats_update_timer.isActive()
    
    # Wait for timer (manually trigger for speed)
    main_window.stats_update_timer.stop()
    main_window._do_update_stats_display()
    
    assert main_window.progress_bar is not None

def test_repo_tab_loading(main_window, qapp, sample_repertoire):
    """Test that repository tabs are loaded and updated."""
    # Mock return of visible repos to ensure buttons are created
    with patch.object(main_window.training_manager, 'get_visible_repos', return_value=[sample_repertoire]):
        main_window.refresh_repertoire_buttons()
        qapp.processEvents()
        
        # Check that we have buttons in the group
        assert len(main_window.repo_button_group.buttons()) > 0

def test_smart_button_states(main_window):
    """Test the smart action button text transitions."""
    main_window.set_button_state('start')
    assert "STARTEN" in main_window.btn_smart.text()
    
    main_window.set_button_state('waiting_for_move')
    assert "ZUG" in main_window.btn_smart.text()
    
    main_window.set_button_state('correct')
    assert "KORREKT" in main_window.btn_smart.text()

def test_repertoire_tabs_sorting_order(main_window, qapp):
    """Test that repertoire tabs sort by due moves descending, then Elo descending, then name ascending."""
    repos = ["Repo_D", "Repo_B", "Repo_E", "Repo_A", "Repo_C"]
    stats_mock = {
        "Repo_A": (0, 10, {}),
        "Repo_B": (0, 0, {}),
        "Repo_C": (0, 0, {}),
        "Repo_D": (0, 0, {}),
        "Repo_E": (0, 0, {}),
    }
    ratings_mock = {
        "Repo_A": 900.0,
        "Repo_B": 1400.0,
        "Repo_C": 1100.0,
        "Repo_D": 800.0,
        "Repo_E": 800.0,
    }
    with patch.object(main_window.training_manager, 'get_visible_repos', return_value=repos), \
         patch.object(main_window.training_manager, 'get_stats_for_repertoire', side_effect=lambda r: stats_mock[r]), \
         patch.object(main_window.training_manager, 'get_ratings_for_all_repertoires', return_value=ratings_mock):
        
        main_window.sorted_repo_names = None
        main_window.refresh_repertoire_buttons()
        qapp.processEvents()

        # Expected order:
        # 1. Repo_A (10 due moves)
        # 2. Repo_B (0 due, 1400 Elo)
        # 3. Repo_C (0 due, 1100 Elo)
        # 4. Repo_D (0 due, 800 Elo)
        # 5. Repo_E (0 due, 800 Elo)
        assert main_window.sorted_repo_names == ["Repo_A", "Repo_B", "Repo_C", "Repo_D", "Repo_E"]

