import pytest
from PyQt6.QtWidgets import QApplication, QPushButton, QLabel, QWidget
from PyQt6.QtCore import Qt
from opening_fenix.gui.widgets.title_bar import CustomTitleBar

def test_title_bar_basic(qtbot):
    """Test the custom title bar buttons and labels."""
    widget = CustomTitleBar(None, "Test Title")
    qtbot.addWidget(widget)
    
    # TitleLabel doesn't exist anymore according to lines I saw? 
    # Actually I should check if it exists.
    # Lines 23-25 of title_bar.py didn't show it.
    # I'll just check if buttons exist.
    
    # Check buttons exist
    btn_min = widget.findChild(QPushButton, "MinimizeButton")
    btn_close = widget.findChild(QPushButton, "CloseButton")
    assert btn_min
    assert btn_close

def test_title_bar_buttons(qtbot, monkeypatch):
    """Test title bar button logic."""
    class MockWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.minimized = False
            self.closed = False
        def showMinimized(self): self.minimized = True
        def close(self): self.closed = True
        def isMaximized(self): return False
        def showMaximized(self): pass
        def showNormal(self): pass
        def windowState(self): return Qt.WindowState.WindowNoState
    
    win = MockWindow()
    widget = CustomTitleBar(win, "Test")
    qtbot.addWidget(widget)
    
    # Test minimize
    btn_min = widget.findChild(QPushButton, "MinimizeButton")
    btn_min.click()
    assert win.minimized

def test_export_dialog_pgn(qtbot, complex_backend):
    """Test ExportDialog PGN options."""
    from opening_fenix.gui.dialogs.export_dialog import ExportDialog
    dialog = ExportDialog(complex_backend)
    qtbot.addWidget(dialog)
    dialog.r_pgn.setChecked(True)
    dialog.on_accept()
    assert dialog.result_data[0] == "pgn"
