import os
import pytest
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QDialog

from opening_fenix.gui.dialogs.engine_setup_dialog import (
    EngineActionDialog, EngineDownloadProgressDialog, prompt_engine_if_missing
)


def test_engine_action_dialog_actions(qapp):
    dlg = EngineActionDialog()
    assert dlg.selected_action == EngineActionDialog.ACTION_CANCEL

    dlg._on_download_clicked()
    assert dlg.selected_action == EngineActionDialog.ACTION_DOWNLOAD

    dlg._on_browse_clicked()
    assert dlg.selected_action == EngineActionDialog.ACTION_BROWSE


def test_prompt_engine_if_missing_already_valid(tmp_path, qapp):
    mock_exe = tmp_path / "valid_engine.exe"
    mock_exe.write_bytes(b"MZmock")

    cfg = {"engine_path": str(mock_exe)}
    with patch("opening_fenix.gui.dialogs.engine_setup_dialog.EngineActionDialog") as mock_dlg:
        res = prompt_engine_if_missing(None, config_dict=cfg)
        assert res == str(mock_exe)
        mock_dlg.assert_not_called()


def test_prompt_engine_if_missing_user_cancels(qapp):
    cfg = {"engine_path": ""}
    with patch("opening_fenix.gui.dialogs.engine_setup_dialog.EngineActionDialog.exec", 
               return_value=QDialog.DialogCode.Rejected):
        res = prompt_engine_if_missing(None, config_dict=cfg)
        assert res is None


def test_prompt_engine_if_missing_user_browses(tmp_path, qapp):
    mock_exe = tmp_path / "custom_stockfish.exe"
    mock_exe.write_bytes(b"MZmock")

    cfg = {"engine_path": ""}

    def mock_action_exec(self):
        self.selected_action = EngineActionDialog.ACTION_BROWSE
        return QDialog.DialogCode.Accepted

    with patch.object(EngineActionDialog, "exec", mock_action_exec), \
         patch("opening_fenix.gui.dialogs.engine_setup_dialog.QFileDialog.getOpenFileName", 
               return_value=(str(mock_exe), "Exe")), \
         patch("opening_fenix.gui.dialogs.engine_setup_dialog.save_config_dict") as mock_save:

        res = prompt_engine_if_missing(None, config_dict=cfg)
        assert res == str(mock_exe)
        assert cfg["engine_path"] == str(mock_exe)
        mock_save.assert_called_once()


def test_prompt_engine_if_missing_user_downloads(tmp_path, qapp):
    mock_exe = tmp_path / "downloaded_stockfish.exe"
    mock_exe.write_bytes(b"MZmock")

    cfg = {"engine_path": ""}

    def mock_action_exec(self):
        self.selected_action = EngineActionDialog.ACTION_DOWNLOAD
        return QDialog.DialogCode.Accepted

    def mock_dl_exec(self):
        self.engine_path = str(mock_exe)
        return QDialog.DialogCode.Accepted

    with patch.object(EngineActionDialog, "exec", mock_action_exec), \
         patch.object(EngineDownloadProgressDialog, "start_download"), \
         patch.object(EngineDownloadProgressDialog, "exec", mock_dl_exec), \
         patch("opening_fenix.gui.dialogs.engine_setup_dialog.save_config_dict") as mock_save:

        res = prompt_engine_if_missing(None, config_dict=cfg)
        assert res == str(mock_exe)
        assert cfg["engine_path"] == str(mock_exe)
        mock_save.assert_called_once()


def test_engine_download_progress_dialog_ui(tmp_path, qapp):
    mock_exe = tmp_path / "mock_sf.exe"
    mock_exe.write_bytes(b"MZmock")

    with patch.object(EngineDownloadProgressDialog, "start_download"):
        dlg = EngineDownloadProgressDialog()
        assert dlg.progress_bar.value() == 0

        # Simulate progress
        dlg._on_progress(50, 100)
        assert dlg.progress_bar.value() == 50

        # Simulate status
        dlg._on_status("Extracting...")
        assert dlg.lbl_status.text() == "Extracting..."

        # Simulate finished
        dlg._on_finished(str(mock_exe))
        assert dlg.engine_path == str(mock_exe)
        assert dlg.progress_bar.value() == 100

        # Simulate error
        dlg._on_error("Network Timeout")
        assert dlg.error_message == "Network Timeout"

