import sys
from unittest.mock import MagicMock
import pytest
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget, QTreeWidget

import opening_fenix.creator.creator_window

@pytest.fixture(scope="session")
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app

def test_creator_arrow_navigation(qapp, monkeypatch):
    """Test that arrow keys are correctly handled and filtered in CreatorWindow.
    
    In the real app, pressing Up/Down redirects focus to the tree widget.
    In headless Qt testing, setFocus() on invisible widgets is a no-op and
    hasFocus() always returns False. We mock setFocus() to verify the intent
    without relying on Qt's headless focus state.
    """
    # Mock heavy backend components
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorBackend", MagicMock())
    monkeypatch.setattr("opening_fenix.core.engine.EngineThread", MagicMock())
    # Block dialogs from firing via QTimer
    monkeypatch.setattr(
        "opening_fenix.creator.creator_window.CreatorWindow.new_repertoire_dialog",
        lambda self: None
    )
    monkeypatch.setattr(
        "opening_fenix.creator.creator_window.CreatorWindow.load_repertoire_dialog",
        lambda self: None
    )
    
    from opening_fenix.creator.creator_window import CreatorWindow
    window = CreatorWindow()
    
    # We need a real QTreeWidget; replace after creation so internal refs still work.
    real_tree = QTreeWidget()
    window.tree_widget = real_tree
    
    # Case 1: Press Down when focus is NOT on the tree.
    # eventFilter should call setFocus() on the tree widget and return True.
    # We replace setFocus with a MagicMock to observe the call — patching Qt C++
    # methods with wraps= crashes, so we use a plain mock that replaces the slot.
    event_down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    
    real_tree.setFocus = MagicMock()
    handled = window.eventFilter(window, event_down)
    assert handled is True
    real_tree.setFocus.assert_called()  # focus was directed to the tree

    # Case 2: Press Down when obj IS the tree_widget.
    # Should return False to avoid recursion.
    handled_recursive = window.eventFilter(window.tree_widget, event_down)
    assert handled_recursive is False

    window.close()
    real_tree.deleteLater()

def test_creator_horizontal_navigation(qapp, monkeypatch):
    """Test Left/Right arrow navigation."""
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorBackend", MagicMock())
    monkeypatch.setattr("opening_fenix.core.engine.EngineThread", MagicMock())
    monkeypatch.setattr(
        "opening_fenix.creator.creator_window.CreatorWindow.new_repertoire_dialog",
        lambda self: None
    )
    from opening_fenix.creator.creator_window import CreatorWindow
    window = CreatorWindow()
    
    window.go_back = MagicMock()
    window.go_forward = MagicMock()
    
    event_left = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    event_right = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    
    assert window.eventFilter(window, event_left) is True
    window.go_back.assert_called_once()
    
    assert window.eventFilter(window, event_right) is True
    window.go_forward.assert_called_once()
    window.close()

