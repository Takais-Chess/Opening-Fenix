import os
import pytest
from PyQt6.QtWidgets import QApplication, QPushButton, QDialog
from PyQt6.QtCore import Qt, QTimer
from PyQt6 import sip

from opening_fenix.gui.main_window import MainWindow
from opening_fenix.creator.creator_window import CreatorWindow
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog
from opening_fenix.gui.dialogs.login_dialog import LoginDialog

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

from opening_fenix.core.db.models import UserRepertoireSettings

@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    """Fixture for MainWindow."""
    profile_name = "TestUser"
    
    # 1. Ensure the sample repertoire is marked as visible in the user's settings
    from opening_fenix.core.training import TrainingManager
    from opening_fenix.core.repertoire import RepertoireManager
    rm = RepertoireManager(profile_name=profile_name)
    tm = TrainingManager(profile_name=profile_name, repertoire_manager=rm)
    tm.set_repo_visibility(sample_repertoire, True)
    tm.close()
    rm.close()
    
    # 2. Open MainWindow
    win = MainWindow(profile_name)
    win.show()
    yield win
    
    # 3. Cleanup
    win.close()
    if not sip.isdeleted(win):
        win.deleteLater()
    qapp.processEvents()

def test_trainer_to_creator_launch(main_window, qapp):
    """Test that clicking the creator button in MainWindow launches CreatorWindow."""
    # Ensure active repertoire is set
    assert main_window.repertoire_manager.active_repertoire_name == "TestRepo"
    
    # Find the creator button (pencil icon)
    btn_creator = main_window.btn_creator
    assert btn_creator is not None
    
    # Trigger the click/action
    btn_creator.click()
    
    # Process events to let UI update
    qapp.processEvents()
    
    # Check if creator_window is created and visible
    assert main_window.creator_window is not None
    assert isinstance(main_window.creator_window, CreatorWindow)
    assert main_window.creator_window.isVisible()
    
    # Cleanup
    main_window.creator_window.close()
    qapp.processEvents()

def test_trainer_settings_launch(main_window, monkeypatch):
    """Test that clicking the settings button opens the SettingsDialog."""
    # Mock exec_ to avoid blocking the test
    executed = False
    def mock_exec(self):
        nonlocal executed
        executed = True
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SettingsDialog, "exec", mock_exec)
    
    main_window.btn_settings.click()
    assert executed is True

def test_trainer_profile_switch(main_window):
    """Test that clicking the profile name sets switch_requested and closes window."""
    assert main_window.switch_requested is False
    
    main_window.btn_switch_profile.click()
    
    assert main_window.switch_requested is True
    # The window should be closed or scheduled for closing
    assert not main_window.isVisible()

def test_login_to_creator_launch(qapp, mock_user_dir):
    """Test that Repertoire Creator button in LoginDialog sets the correct flag."""
    login = LoginDialog()
    
    # Find the creator button
    target_btn = None
    for btn in login.findChildren(QPushButton):
        if "REPERTOIRE CREATOR" in btn.text().upper():
            target_btn = btn
            break
                
    assert target_btn is not None, "Creator button not found in LoginDialog"
    
    target_btn.click()
    assert login.open_creator_requested is True
