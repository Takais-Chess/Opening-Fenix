import pytest
from unittest.mock import MagicMock
from PyQt6 import sip
from PyQt6.QtCore import QUrl
import sys
sys.modules["sip"] = sip # Add compatibility for code doing 'import sip'


def test_open_creator_reconnects_on_none_session(monkeypatch):
    """
    Test that open_creator_at_current_position triggers load_repertoire
    if the backend session is None, even if the repertoire name is the same.
    """
    # 1. Setup Mocks
    mock_repo_manager = MagicMock()
    mock_repo_manager.active_repertoire_name = "TestRepo"
    mock_repo_manager.is_active_test = False
    
    mock_training_manager = MagicMock()
    
    # Mock CreatorWindow instance
    mock_creator = MagicMock()
    mock_creator.backend.active_repo_name = "TestRepo"
    mock_creator.is_test = False
    mock_creator.backend.session = None # SIMULATE CLOSED SESSION
    mock_creator.isMinimized.return_value = False
    
    # Mock sip.isdeleted to return False for our mock
    monkeypatch.setattr(sip, "isdeleted", lambda x: False)
    
    # Mock CreatorWindow class (for the 'else' branch, though we'll test the 'if' branch)
    monkeypatch.setattr("opening_fenix.gui.main_window.CreatorWindow", MagicMock())
    
    # 2. Initialize MainWindow (minimally)
    from opening_fenix.gui.main_window import MainWindow
    # We use __new__ to avoid full __init__ which starts UI/Threads
    main_window = MainWindow.__new__(MainWindow)
    main_window.repertoire_manager = mock_repo_manager
    main_window.training_manager = mock_training_manager
    main_window.creator_window = mock_creator
    main_window.board_widget = MagicMock()
    main_window.board_widget.board.fen.return_value = "startfen"
    
    # 3. Execute
    main_window.open_creator_at_current_position("targetfen")
    
    # 4. Verify
    # Because session was None, load_repertoire SHOULD have been called
    mock_creator.load_repertoire.assert_called_with("TestRepo", mock_training_manager, False)
    mock_creator.set_board_to_fen.assert_called_with("targetfen")

def test_open_creator_skips_reload_if_session_active(monkeypatch):
    """
    Test that open_creator_at_current_position does NOT trigger load_repertoire
    if the session is already healthy and repertoire matches.
    """
    # 1. Setup Mocks
    mock_repo_manager = MagicMock()
    mock_repo_manager.active_repertoire_name = "TestRepo"
    mock_repo_manager.is_active_test = False
    
    mock_training_manager = MagicMock()
    
    mock_creator = MagicMock()
    mock_creator.backend.active_repo_name = "TestRepo"
    mock_creator.is_test = False
    mock_creator.backend.session = MagicMock() # SESSION IS ACTIVE
    mock_creator.isMinimized.return_value = False
    
    monkeypatch.setattr(sip, "isdeleted", lambda x: False)
    
    from opening_fenix.gui.main_window import MainWindow
    main_window = MainWindow.__new__(MainWindow)
    main_window.repertoire_manager = mock_repo_manager
    main_window.training_manager = mock_training_manager
    main_window.creator_window = mock_creator
    main_window.board_widget = MagicMock()
    
    # 2. Execute
    main_window.open_creator_at_current_position("targetfen")
    
    # 3. Verify
    # load_repertoire should NOT be called
    mock_creator.load_repertoire.assert_not_called()
    mock_creator.set_board_to_fen.assert_called_with("targetfen")

def test_show_debug_info_handles_none_session(monkeypatch):
    """
    Test that CreatorWindow.show_debug_position_info doesn't crash if session is None.
    """
    # Mock QApplication for QMessageBox
    monkeypatch.setattr("opening_fenix.creator.creator_window.QMessageBox.warning", MagicMock())
    
    from opening_fenix.creator.creator_window import CreatorWindow
    # Minimize init
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorBackend", MagicMock())
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.init_ui", lambda x: None)
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.init_engine", lambda x: None)
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.init_icons", lambda x: None)
    
    window = CreatorWindow.__new__(CreatorWindow)
    window.backend = MagicMock()
    window.backend.session = None # SESSION IS NONE
    window.board_widget = MagicMock()
    window.board_widget.board.fen.return_value = "fen"
    
    # This should not raise AttributeError
    window.show_debug_position_info()
    
    from opening_fenix.creator.creator_window import QMessageBox
    QMessageBox.warning.assert_called()
