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
    profile_name = "TestUser"
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

def test_animation_speed_propagation(main_window):
    """Test that changing animation speed updates the setting."""
    dialog = SettingsDialog(main_window)
    
    target_speed = 500
    dialog.spin_anim.setValue(target_speed)
    
    assert main_window.training_manager.get_setting("anim_speed") == target_speed

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

def test_repertoire_visibility_toggle(main_window, qapp, monkeypatch):
    """Test toggling repertoire visibility."""
    # Mock get_all_repertoires
    monkeypatch.setattr(main_window.repertoire_manager, "get_all_repertoires", lambda: ["TestRepo"])
    
    dialog = SettingsDialog(main_window)
    # Switch to Repo page
    dialog.sidebar.setCurrentRow(2)
    
    # Trigger selection if not already set (e.g. if it's the only item, signal might not fire)
    if dialog.selected_repo != "TestRepo":
        dialog.on_repo_selected("TestRepo")
    
    # Initially visible
    assert dialog.chk_visible.isChecked() is True
    
    # Toggle off
    dialog.chk_visible.setChecked(False)
    dialog.toggle_visibility()
    
    assert main_window.training_manager.is_repo_visible("TestRepo") is False

def test_reset_progress_dialog(main_window, monkeypatch, qapp):
    """Test triggering the reset progress dialog."""
    # Mock get_all_repertoires
    monkeypatch.setattr(main_window.repertoire_manager, "get_all_repertoires", lambda: ["TestRepo"])
    
    dialog = SettingsDialog(main_window)
    dialog.sidebar.setCurrentRow(2)
    
    if dialog.selected_repo != "TestRepo":
        dialog.on_repo_selected("TestRepo")
    
    # Mock QMessageBox.question to return Yes
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    # Mock information box
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    
    # Trigger reset
    dialog.reset_repo_progress()
    
    # Verify
    assert dialog.selected_repo == "TestRepo"
