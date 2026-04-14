import os
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget, QGridLayout
from PyQt6.QtCore import Qt
from opening_fenix.gui.dialogs.repo_settings_dialog import RepoSettingsDialog, DiagnosticDialog, MaintenanceRepoWidget
from opening_fenix.creator.creator_window import CreatorBackend

class MockMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.config = {"theme": "Blau (Turnier)", "master_volume": 80}

def test_diagnostic_dialog_init(qtbot, complex_backend, monkeypatch):
    """Test DiagnosticDialog with mock issues."""
    mock_issues = {'schema': ['new_column'], 'gaps': 5, 'duplicates': 2, 'orphans': 10}
    monkeypatch.setattr(complex_backend, "run_diagnostic", lambda: mock_issues)
    dialog = DiagnosticDialog(complex_backend)
    qtbot.addWidget(dialog)
    # The scan runs in a timer, wait for it
    qtbot.waitUntil(lambda: "identified" in dialog.lbl_info.text(), timeout=2000)
    assert dialog.btn_repair.isEnabled()

def test_maintenance_widget(qtbot):
    """Test the custom maintenance row widget."""
    widget = MaintenanceRepoWidget("TestRepo", "high")
    qtbot.addWidget(widget)
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert not widget.is_checked()

def test_settings_navigation(qapp, complex_backend):
    """Test sidebar navigation in RepoSettingsDialog."""
    win = MockMainWindow()
    dialog = RepoSettingsDialog(win, complex_backend)
    dialog.sidebar.setCurrentRow(1)
    assert dialog.pages.currentIndex() == 1
    dialog.sidebar.setCurrentRow(4)
    assert dialog.pages.currentIndex() == 4
