import pytest
import os
import json
import datetime

from opening_fenix.core.services.update_service import (
    parse_version, is_newer_version, should_check_for_updates,
    is_version_ignored, set_snooze_period, get_config_dict, save_config_dict
)

def test_parse_version():
    assert parse_version("v1.0.0") == (1, 0, 0)
    assert parse_version("2.3.1") == (2, 3, 1)
    assert parse_version("v2.2.0-beta") == (2, 2, 0)
    assert parse_version("") == (0, 0, 0)
    assert parse_version(None) == (0, 0, 0)

def test_is_newer_version():
    assert is_newer_version("v1.1.0", "1.0.0") is True
    assert is_newer_version("v2.0.0", "1.9.9") is True
    assert is_newer_version("1.0.1", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("v0.9.0", "1.0.0") is False

def test_snooze_and_ignore_logic(tmp_path, monkeypatch):
    # Mock user_dir to tmp_path
    monkeypatch.setattr("opening_fenix.core.services.update_service.get_user_dir", lambda: str(tmp_path))

    # Initial state
    assert should_check_for_updates(manual=False) is True
    assert is_version_ignored("v1.5.0") is False

    # Test ignore
    set_snooze_period("ignore", "v1.5.0")
    assert is_version_ignored("v1.5.0") is True
    assert is_version_ignored("1.5.0") is True
    assert is_version_ignored("v1.6.0") is False

    # Test snooze 1 week
    set_snooze_period("1_week", "v1.6.0")
    assert should_check_for_updates(manual=False) is False
    assert should_check_for_updates(manual=True) is True

    # Test reset next start
    set_snooze_period("next_start", "v1.6.0")
    assert should_check_for_updates(manual=False) is True

    # Test auto check disabled
    cfg = get_config_dict()
    cfg["auto_check_updates"] = False
    save_config_dict(cfg)
    assert should_check_for_updates(manual=False) is False
    assert should_check_for_updates(manual=True) is True
