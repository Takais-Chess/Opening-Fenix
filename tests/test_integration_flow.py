import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QDialog
from opening_fenix.gui.window_manager import WindowManager

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_window_manager_login_success(qapp, monkeypatch):
    """Verifies that a successful login leads to the main window."""
    manager = WindowManager()
    
    # Mock LoginDialog
    mock_login = MagicMock()
    mock_login.exec.return_value = QDialog.DialogCode.Accepted
    mock_login.selected_profile = "TestProfile"
    # Essential: Ensure this is explicitly False, otherwise a MagicMock() is truthy
    mock_login.open_creator_requested = False 
    monkeypatch.setattr("opening_fenix.gui.window_manager.LoginDialog", lambda: mock_login)
    
    # Mock MainWindow
    mock_main = MagicMock()
    mock_main.switch_requested = False
    monkeypatch.setattr("opening_fenix.gui.window_manager.MainWindow", lambda profile: mock_main)
    
    # Mock QApplication.exec to return immediately
    monkeypatch.setattr("PyQt6.QtWidgets.QApplication.exec", lambda self: 0)

    # Use a side effect to break the while True loop in run_loop after one iteration
    # Since run_loop is a simple loop, we can just call show_login and show_main_window directly
    # OR we can mock run_loop to test the transition logic.
    
    # Test show_login
    assert manager.show_login() is True
    assert manager.current_profile == "TestProfile"
    
    # Test show_main_window
    manager.show_main_window()
    assert manager.main_window == mock_main
    mock_main.showMaximized.assert_called_once()

def test_window_manager_login_to_creator(qapp, monkeypatch):
    """Verifies that requesting the creator in the login dialog opens the creator window."""
    manager = WindowManager()
    
    mock_login = MagicMock()
    mock_login.open_creator_requested = True
    monkeypatch.setattr("opening_fenix.gui.window_manager.LoginDialog", lambda: mock_login)
    
    mock_creator = MagicMock()
    monkeypatch.setattr("opening_fenix.gui.window_manager.CreatorWindow", lambda: mock_creator)
    monkeypatch.setattr("PyQt6.QtWidgets.QApplication.exec", lambda self: 0)

    # Calling show_login should trigger show_creator
    with patch.object(manager, 'show_creator') as mock_show_creator:
        result = manager.show_login()
        assert result is False
        mock_show_creator.assert_called_once()
