import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog
from opening_fenix.gui.widgets.board_widget import THEMES

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    """Fixture for MainWindow with visible repertoire."""
    profile_name = "test"
    from opening_fenix.core.training import TrainingManager
    from opening_fenix.core.repertoire import RepertoireManager
    rm = RepertoireManager(profile_name=profile_name)
    tm = TrainingManager(profile_name=profile_name, repertoire_manager=rm)
    tm.set_repo_visibility(sample_repertoire, True)
    tm.close()
    rm.close()
    
    win = MainWindow(profile_name)
    win.show()
    yield win
    win.close()

def test_theme_propagation(main_window):
    """Test that changing the theme in SettingsDialog updates the board."""
    dialog = SettingsDialog(main_window)
    
    # Target theme
    target_theme = "Grün (Lichess)"
    dialog.combo_theme.setCurrentText(target_theme)
    
    # Verify MainWindow and BoardWidget updated
    assert main_window.training_manager.get_setting("theme") == target_theme
    assert main_window.board_widget.light_color.name() == THEMES[target_theme][0].name()
    dialog.close()

def test_animation_speed_propagation(main_window):
    """Test that changing animation speed updates the setting."""
    dialog = SettingsDialog(main_window)
    
    target_speed = 500
    dialog.spin_anim.setValue(target_speed)
    
    assert main_window.training_manager.get_setting("anim_speed") == target_speed
    dialog.close()

def test_volume_propagation(main_window, monkeypatch):
    """Test that changing volume updates the main window."""
    # Mock set_master_volume to verify it's called
    volume_set = -1
    def mock_set_volume(val):
        nonlocal volume_set
        volume_set = val
        
    monkeypatch.setattr(main_window, "set_master_volume", mock_set_volume)
    
    dialog = SettingsDialog(main_window)
    dialog.volume_slider.setValue(75)
    
    assert volume_set == 75
    assert main_window.training_manager.get_setting("master_volume") == 75
    dialog.close()

def test_repertoire_visibility_toggle(main_window, qapp, monkeypatch):
    """Test toggling repertoire visibility."""
    # Mock refresh_repertoire_buttons (legacy) or tabs_widget.refresh_tabs
    monkeypatch.setattr(main_window, "refresh_repertoire_buttons", lambda: None, raising=False)
    
    dialog = SettingsDialog(main_window)
    # Switch to Repo page
    dialog.sidebar.setCurrentRow(2)
    
    # Find the card for TestRepo
    target_card = None
    for i in range(dialog.card_layout.count()):
        item = dialog.card_layout.itemAt(i)
        if item.widget() and hasattr(item.widget(), "repo_name") and item.widget().repo_name == "TestRepo":
            target_card = item.widget()
            break
    
    assert target_card is not None
    assert target_card.is_active is True
    
    # Toggle off
    target_card.toggle_active()
    
    assert main_window.training_manager.is_repo_visible("TestRepo") is False
    dialog.close()

def test_reset_progress_dialog(main_window, monkeypatch, qapp):
    """Test triggering the reset progress dialog."""
    dialog = SettingsDialog(main_window)
    dialog.sidebar.setCurrentRow(2)
    
    # Mock QMessageBox.warning to return Yes (for reset confirmation)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    # Mock information box
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    
    # Select repo
    dialog.on_repo_selected("TestRepo")
    
    # Trigger reset
    dialog.reset_repo_progress()
    
    # Verify
    assert dialog.selected_repo == "TestRepo"
    dialog.close()


def test_auto_continue_toggle_invalidates_preload(main_window):
    """Test that toggling auto-continue invalidates any preloaded challenges."""
    main_window.repertoire_manager.set_active_repertoire("TestRepo")
    
    main_window.btn_auto_continue.setChecked(True)
    main_window.toggle_auto_continue_btn()
    assert main_window.training_manager.get_setting("stop_at_variation_end") is False
    
    class MockMove:
        def __init__(self, move_id):
            self.id = move_id
            
    mock_move = MockMove(42)
    main_window._preloaded_challenge = {
        'type': 'auto_continue',
        'next_move': MockMove(100),
        'path': [],
        'source_move_id': 42
    }
    
    main_window.btn_auto_continue.setChecked(False)
    main_window.toggle_auto_continue_btn()
    
    assert main_window.training_manager.get_setting("stop_at_variation_end") is True
    assert main_window._preloaded_challenge is None


def test_load_next_challenge_reverifies_auto_continue(main_window):
    """Test that load_next_challenge dynamically re-verifies stop_at_variation_end setting even for preloaded challenges."""
    main_window.repertoire_manager.set_active_repertoire("TestRepo")
    
    class MockMove:
        def __init__(self, move_id):
            self.id = move_id
            
    mock_move = MockMove(42)
    
    main_window.training_manager.set_setting("stop_at_variation_end", True)
    main_window._preloaded_challenge = {
        'type': 'auto_continue',
        'next_move': MockMove(100),
        'path': [],
        'source_move_id': 42
    }
    
    main_window.update_notation_display = lambda reveal_move: setattr(main_window, "_called_update_notation", True)
    main_window.set_button_state = lambda state: setattr(main_window, "_called_set_button", state)
    
    main_window.load_next_challenge(last_success=True, last_move=mock_move)
    
    assert getattr(main_window, "_called_update_notation", False) is True
    assert getattr(main_window, "_called_set_button", "") == 'start'
    assert main_window.current_move_obj is None


def test_preload_next_challenge_excludes_current_move(main_window):
    """Test that preload_next_challenge excludes the current move from being preloaded."""
    main_window.repertoire_manager.set_active_repertoire("TestRepo")
    main_window.training_mode = 'due'
    
    class MockMove:
        def __init__(self, move_id):
            self.id = move_id
            self.to_position_id = 1
            
    mock_move = MockMove(42)
    main_window.current_move_obj = mock_move
    
    main_window.training_manager.set_setting("stop_at_variation_end", False)
    
    original_get_next_move = main_window.training_manager.get_next_move
    called_with_exclude = None
    
    def mock_get_next_move(mode='due', last_move_obj=None, last_was_success=False, only_continuation=False, variation_filter=None, exclude_move_ids=None):
        nonlocal called_with_exclude
        if not only_continuation:
            called_with_exclude = exclude_move_ids
        return original_get_next_move(mode, last_move_obj, last_was_success, only_continuation, variation_filter, exclude_move_ids)
        
    main_window.training_manager.get_next_move = mock_get_next_move
    
    main_window.preload_next_challenge()
    
    assert called_with_exclude == {42}


