import os
import json
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QWidget

from opening_fenix.core.utils import get_last_active_profile_name
from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
from opening_fenix.gui.dialogs.repo_settings_dialog import RepoSettingsDialog
from opening_fenix.creator.creator_window import CreatorWindow


def test_get_last_active_profile_name_from_last_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    
    # Setup config.json
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"last_profile": "Alice"}), encoding="utf-8")
    
    # Setup profile file
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "Alice.db").write_text("", encoding="utf-8")
    
    assert get_last_active_profile_name() == "Alice"


def test_get_last_active_profile_name_from_profile_last_used(tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "profile_last_used": {
            "OldUser": "2026-01-01T10:00:00",
            "RecentUser": "2026-09-08T12:00:00"
        }
    }), encoding="utf-8")
    
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "OldUser.db").write_text("", encoding="utf-8")
    (profiles_dir / "RecentUser.db").write_text("", encoding="utf-8")
    
    assert get_last_active_profile_name() == "RecentUser"


def test_get_last_active_profile_name_from_filesystem_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "Bob_settings.json").write_text("{}", encoding="utf-8")
    
    assert get_last_active_profile_name() == "Bob"


def test_get_last_active_profile_name_default_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    assert get_last_active_profile_name() == "Default"


def test_unified_settings_resolves_last_active_profile_in_creator_mode(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.gui.dialogs.unified_settings_dialog.get_user_dir", lambda: str(tmp_path))
    
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"last_profile": "MasterPlayer"}), encoding="utf-8")
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "MasterPlayer.db").write_text("", encoding="utf-8")
    (profiles_dir / "MasterPlayer_settings.json").write_text(json.dumps({
        "interval_preset": "relaxed",
        "max_new_cards_per_day": 25
    }), encoding="utf-8")

    # Open RepoSettingsDialog with a dummy parent (simulating Creator launched standalone)
    parent = QWidget()
    dlg = RepoSettingsDialog(parent=parent)
    qtbot.addWidget(dlg)

    # 1. Check resolved profile name
    assert dlg.profile_name == "MasterPlayer"

    # 2. Check sidebar header contains profile name and not Default
    header_text = dlg.sec_trainer.text(0)
    assert "MasterPlayer" in header_text
    assert "Default" not in header_text

    # 3. Check that initial settings load from MasterPlayer_settings.json
    assert dlg.get_setting("interval_preset") == "relaxed"
    assert dlg.get_setting("max_new_cards_per_day") == 25

    # 4. Modify a trainer setting and check that it writes to MasterPlayer_settings.json
    dlg.set_setting("max_new_cards_per_day", 50)
    
    saved_profile_settings = json.loads((profiles_dir / "MasterPlayer_settings.json").read_text(encoding="utf-8"))
    assert saved_profile_settings["max_new_cards_per_day"] == 50


def test_creator_window_passes_profile_name_to_dialog(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.gui.dialogs.unified_settings_dialog.get_user_dir", lambda: str(tmp_path))

    # Mock TrainingManager attached to CreatorWindow
    mock_tm = MagicMock()
    mock_tm.profile_name = "Grandmaster"
    mock_tm.get_setting.side_effect = lambda k, d=None: {"auto_delay": 150}.get(k, d)

    class FakeCreatorWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.training_manager = mock_tm
            self.profile_name = "Grandmaster"
            self.backend = None

    creator_win = FakeCreatorWindow()
    qtbot.addWidget(creator_win)

    dlg = RepoSettingsDialog(parent=creator_win)
    qtbot.addWidget(dlg)

    assert dlg.profile_name == "Grandmaster"
    assert "Grandmaster" in dlg.sec_trainer.text(0)

    # Setting change should be delegated to training_manager
    dlg.set_setting("auto_delay", 300)
    mock_tm.set_setting.assert_called_with("auto_delay", 300)

