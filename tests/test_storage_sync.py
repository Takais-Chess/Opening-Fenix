import os
import json
import shutil
import tempfile
import pytest
from PyQt6.QtWidgets import QApplication
from opening_fenix.core.utils import (
    get_default_user_dir, get_custom_data_dir, set_custom_data_dir, 
    get_user_dir, migrate_user_data
)

def test_default_user_dir():
    default_dir = get_default_user_dir()
    assert default_dir is not None
    assert os.path.exists(default_dir)
    assert os.path.isdir(default_dir)

def test_custom_data_dir_workflow(temp_dir, monkeypatch):
    default_mock = os.path.join(temp_dir, 'default_user_dir')
    os.makedirs(default_mock, exist_ok=True)
    monkeypatch.setattr('opening_fenix.core.utils.get_default_user_dir', lambda: default_mock)

    assert get_custom_data_dir() is None
    assert get_user_dir() == default_mock

    custom_target = os.path.join(temp_dir, 'cloud_storage', 'Opening Fenix Data')
    set_custom_data_dir(custom_target)

    assert get_custom_data_dir() == os.path.abspath(custom_target)
    assert get_user_dir() == os.path.abspath(custom_target)
    assert os.path.exists(os.path.join(custom_target, 'repertoires'))
    assert os.path.exists(os.path.join(custom_target, 'profiles'))
    assert os.path.exists(os.path.join(custom_target, 'backups'))

    set_custom_data_dir(None)
    assert get_custom_data_dir() is None
    assert get_user_dir() == default_mock

def test_migrate_user_data(temp_dir):
    source_dir = os.path.join(temp_dir, 'source_dir')
    os.makedirs(os.path.join(source_dir, 'repertoires', 'Caro-Kann'), exist_ok=True)
    os.makedirs(os.path.join(source_dir, 'profiles'), exist_ok=True)
    os.makedirs(os.path.join(source_dir, 'backups'), exist_ok=True)

    with open(os.path.join(source_dir, 'repertoires', 'Caro-Kann', 'Caro-Kann.db'), 'w') as f:
        f.write('repertoire data')
    with open(os.path.join(source_dir, 'profiles', 'Felix.db'), 'w') as f:
        f.write('profile data')
    with open(os.path.join(source_dir, 'config.json'), 'w') as f:
        json.dump({'ui_language': 'de'}, f)

    target_dir = os.path.join(temp_dir, 'target_cloud_dir')

    summary = migrate_user_data(source_dir, target_dir)
    assert summary['repertoires'] >= 1
    assert summary['profiles'] >= 1

    assert os.path.exists(os.path.join(target_dir, 'repertoires', 'Caro-Kann', 'Caro-Kann.db'))
    with open(os.path.join(target_dir, 'repertoires', 'Caro-Kann', 'Caro-Kann.db'), 'r') as f:
        assert f.read() == 'repertoire data'

    assert os.path.exists(os.path.join(target_dir, 'profiles', 'Felix.db'))
    with open(os.path.join(target_dir, 'profiles', 'Felix.db'), 'r') as f:
        assert f.read() == 'profile data'

    assert os.path.exists(os.path.join(target_dir, 'config.json'))

def test_migrate_same_dir(temp_dir):
    source_dir = os.path.join(temp_dir, 'same_dir')
    os.makedirs(source_dir, exist_ok=True)
    summary = migrate_user_data(source_dir, source_dir)
    assert summary == {'repertoires': 0, 'profiles': 0, 'backups': 0}
