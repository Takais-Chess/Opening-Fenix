from unittest.mock import MagicMock, patch
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6 import sip

from opening_fenix.gui.main_window import MainWindow
from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    win = MainWindow("TestUser")
    yield win
    win.close()
    if not sip.isdeleted(win):
        win.deleteLater()
    qapp.processEvents()


def test_storage_restart_button_and_prompt(main_window, qapp):
    with patch.object(UnifiedSettingsDialog, "restart_application") as mock_restart:
        dlg = UnifiedSettingsDialog(main_window)
        assert hasattr(dlg, "btn_restart_storage")
        assert dlg.btn_restart_storage.isVisible() is False

        # Simulate clicking "Later"
        with patch.object(QMessageBox, "exec", return_value=0), \
             patch.object(QMessageBox, "clickedButton", return_value=None):
            dlg._prompt_storage_restart("C:/Temp/NewStorage")
            assert dlg.btn_restart_storage.isHidden() is False
            mock_restart.assert_not_called()

        # Simulate clicking the inline "Restart Application" button
        dlg.btn_restart_storage.click()
        mock_restart.assert_called_once()

        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()
