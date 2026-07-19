import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QDialog
from opening_fenix.gui.window_manager import WindowManager

@pytest.fixture
def window_manager():
    return WindowManager()

def test_start_application(window_manager):
    # Mock run_loop to avoid infinite loop
    with patch.object(window_manager, 'run_loop') as mock_loop:
        window_manager.start_application("TestProfile")
        assert window_manager.current_profile == "TestProfile"
        assert mock_loop.called

def test_show_login_success(qtbot, window_manager):
    with patch("opening_fenix.gui.window_manager.LoginDialog") as mock_dialog_class:
        mock_dialog = MagicMock()
        mock_dialog_class.return_value = mock_dialog
        mock_dialog.exec.return_value = QDialog.DialogCode.Accepted
        mock_dialog.selected_profile = "MyProfile"
        mock_dialog.open_creator_requested = False
        
        result = window_manager.show_login()
        
        assert result is True
        assert window_manager.current_profile == "MyProfile"

def test_show_login_cancel(qtbot, window_manager):
    with patch("opening_fenix.gui.window_manager.LoginDialog") as mock_dialog_class:
        mock_dialog = MagicMock()
        mock_dialog_class.return_value = mock_dialog
        mock_dialog.exec.return_value = QDialog.DialogCode.Rejected
        mock_dialog.open_creator_requested = False
        
        result = window_manager.show_login()
        
        assert result is False
        assert window_manager.current_profile is None

def test_show_login_creator_request(qtbot, window_manager):
    with patch("opening_fenix.gui.window_manager.LoginDialog") as mock_dialog_class, \
         patch.object(window_manager, "show_creator") as mock_show_creator:
        
        mock_dialog = MagicMock()
        mock_dialog_class.return_value = mock_dialog
        mock_dialog.open_creator_requested = True
        
        result = window_manager.show_login()
        
        assert result is False
        assert mock_show_creator.called

@patch("opening_fenix.gui.window_manager.MainWindow")
@patch("PyQt6.QtWidgets.QApplication.instance")
def test_show_main_window(mock_app_instance, mock_main_window_class, window_manager):
    window_manager.current_profile = "Test"
    mock_main_window = MagicMock()
    mock_main_window_class.return_value = mock_main_window
    
    mock_app = MagicMock()
    mock_app_instance.return_value = mock_app
    
    window_manager.show_main_window()
    
    assert mock_main_window.showMaximized.called
    assert mock_app.exec.called

@patch("opening_fenix.gui.window_manager.CreatorWindow")
@patch("PyQt6.QtWidgets.QApplication.instance")
def test_show_creator(mock_app_instance, mock_creator_class, window_manager):
    mock_creator = MagicMock()
    mock_creator_class.return_value = mock_creator
    
    mock_app = MagicMock()
    mock_app_instance.return_value = mock_app
    
    window_manager.show_creator()
    
    assert mock_creator.showMaximized.called
    assert mock_app.exec.called

def test_run_loop_switching(window_manager):
    # We want to test the 'switch_requested' logic
    # Setup: 
    # 1. First iteration: show_main_window finds switch_requested=True
    # 2. Second iteration: show_login returns False (cancel) to break loop
    
    window_manager.current_profile = "User1"
    
    with patch.object(window_manager, "show_main_window") as mock_show_main, \
         patch.object(window_manager, "show_login") as mock_show_login:
        
        def mock_main_side_effect():
            # Simulate switch request
            window_manager.main_window = MagicMock()
            window_manager.main_window.switch_requested = True
            
        mock_show_main.side_effect = mock_main_side_effect
        mock_show_login.return_value = False # Break loop on login
        
        window_manager.run_loop()
        
        assert mock_show_main.called
        assert mock_show_login.called
        assert window_manager.current_profile is None

def test_run_loop_switching_clears_auto_login(window_manager, mock_user_dir, monkeypatch):
    """Test that switching profile clears the auto_login_profile setting inside config.json."""
    monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: mock_user_dir)
    
    # 1. Setup config.json with auto_login_profile
    import json
    import os
    config_path = os.path.join(mock_user_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"auto_login_profile": "User1"}, f)
        
    window_manager.current_profile = "User1"
    
    with patch.object(window_manager, "show_main_window") as mock_show_main, \
         patch.object(window_manager, "show_login") as mock_show_login:
        
        def mock_main_side_effect():
            window_manager.main_window = MagicMock()
            window_manager.main_window.switch_requested = True
            
        mock_show_main.side_effect = mock_main_side_effect
        mock_show_login.return_value = False # Break loop on login
        
        window_manager.run_loop()
        
        # Verify it was set to None in config.json
        with open(config_path, "r") as f:
            config = json.load(f)
        assert config.get("auto_login_profile") is None

@patch("opening_fenix.gui.window_manager.LoginDialog")
@patch("PyQt6.QtCore.QEventLoop")
def test_run_loop_auto_login_shows_loading_overlay(mock_event_loop_class, mock_login_dialog_class, window_manager):
    """Test that the loading overlay is shown and a QEventLoop is started during auto-login."""
    window_manager.current_profile = "Felix"
    
    mock_dialog = MagicMock()
    mock_login_dialog_class.return_value = mock_dialog
    
    mock_loop = MagicMock()
    mock_event_loop_class.return_value = mock_loop
    
    with patch.object(window_manager, "show_main_window") as mock_show_main, \
         patch.object(window_manager, "show_login") as mock_show_login:
        
        # Break loop on second iteration to avoid infinite loop
        def mock_main_side_effect():
            window_manager.current_profile = None
            
        mock_show_main.side_effect = mock_main_side_effect
        
        window_manager.run_loop()
        
        assert mock_login_dialog_class.called
        assert mock_dialog.show.called
        assert mock_dialog.show_loading_state.called
        mock_dialog.show_loading_state.assert_called_with("Felix")
        assert mock_loop.exec.called
