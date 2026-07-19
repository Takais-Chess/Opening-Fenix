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

def test_login_language_toggle(qapp, mock_user_dir, monkeypatch):
    """Test that clicking the language switcher buttons changes the active translation language."""
    monkeypatch.setattr("opening_fenix.gui.dialogs.login_dialog.get_user_dir", lambda: mock_user_dir)
    
    login = LoginDialog()
    
    # German should be default or loaded from config
    assert login.btn_lang_de.isCheckable()
    assert login.btn_lang_en.isCheckable()
    
    # 1. Switch to English
    login.btn_lang_en.click()
    from opening_fenix.core.translation import translator
    assert translator.current_lang == "en"
    assert login.btn_lang_en.isChecked()
    assert not login.btn_lang_de.isChecked()
    
    # Verify some UI texts got updated to English
    assert login.title_label.text() == "OPENING FENIX"
    assert login.subtitle_label.text() == "Who is training today?"
    
    # 2. Switch back to German
    login.btn_lang_de.click()
    assert translator.current_lang == "de"
    assert login.btn_lang_de.isChecked()
    assert not login.btn_lang_en.isChecked()
    assert login.subtitle_label.text() == "Wer trainiert heute?"

def test_login_auto_login_selection(qapp, mock_user_dir, monkeypatch):
    """Test that checking the auto-login checkbox saves the selection to config.json."""
    monkeypatch.setattr("opening_fenix.gui.dialogs.login_dialog.get_user_dir", lambda: mock_user_dir)
    
    profile_name = "AutoLoginUser"
    profile_path = os.path.join(mock_user_dir, "profiles", f"{profile_name}.db")
    with open(profile_path, "w") as f:
        f.write("") # Dummy database file
        
    login = LoginDialog()
    login.load_profiles()
    
    # Check the checkbox
    login.chk_auto_login.setChecked(True)
    
    # Find and click the button for "AutoLoginUser"
    buttons = login.findChildren(ProfileGridButton)
    target_btn = None
    for btn in buttons:
        if btn.text() == profile_name:
            target_btn = btn
            break
            
    assert target_btn is not None
    target_btn.click()
    
    # Verify auto_login_profile was written to config.json
    import json
    config_path = os.path.join(mock_user_dir, "config.json")
    assert os.path.exists(config_path)
    with open(config_path, "r") as f:
        config = json.load(f)
    assert config.get("auto_login_profile") == profile_name
    
    # Now verify that when auto-login is NOT checked, it clears it
    login2 = LoginDialog()
    login2.load_profiles()
    login2.chk_auto_login.setChecked(False)
    
    buttons2 = login2.findChildren(ProfileGridButton)
    target_btn2 = None
    for btn in buttons2:
        if btn.text() == profile_name:
            target_btn2 = btn
            break
            
    assert target_btn2 is not None
    target_btn2.click()
    
    with open(config_path, "r") as f:
        config2 = json.load(f)
    assert config2.get("auto_login_profile") is None
