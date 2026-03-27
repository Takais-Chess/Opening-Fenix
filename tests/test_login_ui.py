import os
import pytest
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtCore import Qt
from opening_fenix.gui.dialogs.login_dialog import LoginDialog, ProfileGridButton

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_login_profile_selection(qapp, mock_user_dir, monkeypatch):
    """Test that clicking a profile button correctly selects the profile."""
    # Ensure LoginDialog uses the mocked user dir
    monkeypatch.setattr("opening_fenix.gui.dialogs.login_dialog.get_user_dir", lambda: mock_user_dir)
    
    # 1. Create a dummy profile
    profile_name = "TestUser"
    profile_path = os.path.join(mock_user_dir, "profiles", f"{profile_name}.db")
    with open(profile_path, "w") as f:
        f.write("") # Just a dummy file to be detected 
        
    # 2. Open the LoginDialog
    login = LoginDialog()
    login.load_profiles()
    
    # 3. Find the button for "TestUser"
    buttons = login.findChildren(ProfileGridButton)
    target_btn = None
    for btn in buttons:
        if btn.text() == profile_name:
            target_btn = btn
            break
            
    assert target_btn is not None, f"Profile button for '{profile_name}' not found"
    
    # 4. Simulate a click on the button
    target_btn.click()
    
    # 5. Check if the profile was selected
    assert login.selected_profile == profile_name
    
def test_request_creator_flag(qapp, mock_user_dir):
    """Test that clicking the 'Repertoire Creator' button sets the correct flag."""
    login = LoginDialog()
    
    # Find the creator button. It's a QPushButton, not ProfileGridButton.
    target_btn = None
    for btn in login.findChildren(QPushButton):
        if "REPERTOIRE CREATOR" in btn.text():
            target_btn = btn
            break
                
    assert target_btn is not None, "Creator button not found"
    
    target_btn.click()
    assert login.open_creator_requested is True
