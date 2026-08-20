import pytest
import os
import json
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QDialog, QMessageBox
from PyQt6.QtCore import Qt

from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
from opening_fenix.core.services.update_service import DownloaderWorker, get_config_dict, save_config_dict

@pytest.fixture
def sample_release_info():
    return {
        "version": "1.2.0",
        "tag_name": "v1.2.0",
        "title": "Opening Fenix v1.2.0 Release",
        "body": "## What's New\n- Faster Priority Calculation\n- New dark theme",
        "download_url": "https://github.com/Takais-Chess/Opening-Fenix/releases/download/v1.2.0/OpeningFenix_Setup.exe",
        "html_url": "https://github.com/Takais-Chess/Opening-Fenix/releases/tag/v1.2.0"
    }

def test_update_dialog_init(qtbot, sample_release_info):
    dialog = UpdateDialog(sample_release_info)
    qtbot.addWidget(dialog)
    dialog.show()
    
    assert "1.2.0" in dialog.windowTitle() or "Update" in dialog.windowTitle()
    assert dialog.txt_notes.toPlainText() == sample_release_info["body"]
    assert not dialog.btn_download.isHidden()
    assert not dialog.btn_snooze.isHidden()
    assert dialog.progress_container.isHidden()

def test_update_dialog_snooze_selection(qtbot, sample_release_info, tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.services.update_service.get_user_dir", lambda: str(tmp_path))
    
    dialog = UpdateDialog(sample_release_info)
    qtbot.addWidget(dialog)
    
    # Test snooze 1 week
    dialog.apply_snooze("1_week")
    cfg = get_config_dict()
    assert cfg.get("update_snooze_until") is not None

    # Test ignore version
    dialog.apply_snooze("ignore")
    cfg = get_config_dict()
    assert "1.2.0" in cfg.get("ignored_versions", []) or "v1.2.0" in cfg.get("ignored_versions", [])

def test_update_dialog_download_progress_and_finish(qtbot, sample_release_info):
    dialog = UpdateDialog(sample_release_info)
    qtbot.addWidget(dialog)
    
    # Simulate download start
    dialog.progress_container.show()
    dialog.on_download_progress(50, 100)
    assert dialog.progress_bar.value() == 50
    
    # Simulate download finished
    dialog.on_download_finished("C:/fake/path/setup.exe")
    assert dialog.downloaded_installer_path == "C:/fake/path/setup.exe"
    assert "installieren" in dialog.btn_download.text().lower()

def test_update_dialog_download_error(qtbot, sample_release_info, monkeypatch):
    dialog = UpdateDialog(sample_release_info)
    qtbot.addWidget(dialog)
    
    dialog.on_download_error("Connection timed out")
    assert dialog.btn_download.isEnabled()
    assert "Browser" in dialog.btn_download.text()

def test_downloader_worker_run(tmp_path, monkeypatch):
    worker = DownloaderWorker("https://example.com/fake.exe", "test_setup.exe")
    
    # Mock urllib context manager response
    mock_resp = MagicMock()
    mock_resp.headers = {'Content-Length': '100'}
    mock_resp.read.side_effect = [b"X" * 50, b"Y" * 50, b""]
    
    progress_updates = []
    worker.progress.connect(lambda cur, tot: progress_updates.append((cur, tot)))
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        worker.run()
        
    assert len(progress_updates) > 0
    assert progress_updates[-1] == (100, 100)
