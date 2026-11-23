import os
import json
import shutil
import sqlite3
import tempfile
import pytest
from PyQt6.QtWidgets import QApplication
from opening_fenix.core.utils import (
    get_default_user_dir, get_custom_data_dir, get_local_workspace_dir,
    set_custom_data_dir, get_user_dir, migrate_user_data, ensure_user_data_seeded
)
from opening_fenix.core.services.cloud_sync_service import (
    CloudSyncService, verify_sqlite_db, create_verified_db_snapshot
)
from opening_fenix.core.services.backup_service import create_repertoire_backup, list_repertoire_backups


def _create_valid_sqlite_db(db_path: str, comment_text: str = "Initial comment") -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS positions (id TEXT PRIMARY KEY, fen TEXT, comment TEXT, level INT, priority REAL)")
    c.execute("INSERT OR REPLACE INTO metadata VALUES ('name', 'TestRepo')")
    c.execute(
        "INSERT OR REPLACE INTO positions (id, fen, comment, level, priority) VALUES (?, ?, ?, 1, 1.0)",
        ("pos1", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", json.dumps({"en": comment_text})),
    )
    conn.commit()
    conn.close()


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

    expected_local_ws = os.path.join(default_mock, 'local_workspace')
    assert get_custom_data_dir() == os.path.abspath(custom_target)
    # Active SQLite working directory must be the isolated local_workspace, never the raw cloud dir
    assert get_local_workspace_dir() == os.path.abspath(expected_local_ws)
    assert get_user_dir() == os.path.abspath(expected_local_ws)
    assert os.path.exists(os.path.join(custom_target, 'repertoires'))
    assert os.path.exists(os.path.join(custom_target, 'profiles'))
    assert os.path.exists(os.path.join(custom_target, 'backups'))
    assert os.path.exists(os.path.join(custom_target, 'cloud_sync'))
    assert os.path.exists(os.path.join(expected_local_ws, 'repertoires'))
    assert os.path.exists(os.path.join(expected_local_ws, 'profiles'))

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


def test_ensure_user_data_seeded_seeds_missing_into_custom_dir(temp_dir, monkeypatch):
    custom_dir = os.path.join(temp_dir, 'custom_dir')
    os.makedirs(os.path.join(custom_dir, 'repertoires', 'MyRepertoire'), exist_ok=True)
    with open(os.path.join(custom_dir, 'repertoires', 'MyRepertoire', 'MyRepertoire.db'), 'w') as f:
        f.write('data')

    monkeypatch.setattr('opening_fenix.core.utils.get_user_dir', lambda: custom_dir)
    monkeypatch.setattr('opening_fenix.core.utils.get_custom_data_dir', lambda: custom_dir)

    ensure_user_data_seeded()

    # Verify existing repertoire was not overwritten
    with open(os.path.join(custom_dir, 'repertoires', 'MyRepertoire', 'MyRepertoire.db'), 'r') as f:
        assert f.read() == 'data'

    # Verify bundled repertoires are also seeded even when custom_dir has repertoires
    rep_list = os.listdir(os.path.join(custom_dir, 'repertoires'))
    assert 'MyRepertoire' in rep_list


def test_cloud_sync_stepover_and_pc_laptop_roundtrip(temp_dir, monkeypatch):
    """
    Tests:
    1. Automatic stepover migration from a legacy Google Drive folder containing raw SQLite DBs.
    2. Pulling the migrated snapshots onto a second device (Laptop).
    3. Editing a repertoire on Laptop, pushing to Cloud, and pulling the update on PC.
    """
    cloud_dir = os.path.join(temp_dir, "GoogleDrive_OpeningFenix")
    pc_default_dir = os.path.join(temp_dir, "PC_AppData")
    laptop_default_dir = os.path.join(temp_dir, "Laptop_AppData")

    # Seed legacy raw repertoire & profile inside cloud_dir (pre-stepover state)
    legacy_repo_db = os.path.join(cloud_dir, "repertoires", "1.e4 giri", "1.e4 giri.db")
    _create_valid_sqlite_db(legacy_repo_db, comment_text="PC V1 comment")
    with open(os.path.join(cloud_dir, "repertoires", "1.e4 giri", "README.md"), "w", encoding="utf-8") as f:
        f.write("# 1.e4 Giri")

    legacy_prof_db = os.path.join(cloud_dir, "profiles", "Felix.db")
    _create_valid_sqlite_db(legacy_prof_db, comment_text="Profile V1")

    # 1. PC launches with cloud_dir configured -> automatic stepover migration
    monkeypatch.setattr("opening_fenix.core.utils.get_default_user_dir", lambda: pc_default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_default_user_dir", lambda: pc_default_dir)
    set_custom_data_dir(cloud_dir)

    res_pc1 = CloudSyncService.sync_now(direction="both")
    assert "1.e4 giri" in res_pc1["migrated_repertoires"]
    assert "Felix" in res_pc1["migrated_profiles"]

    pc_local_repo_db = os.path.join(get_user_dir(), "repertoires", "1.e4 giri", "1.e4 giri.db")
    assert os.path.exists(pc_local_repo_db)
    assert verify_sqlite_db(pc_local_repo_db)
    assert os.path.exists(os.path.join(cloud_dir, "cloud_sync", "repertoires", "1.e4 giri.fenixsync.zip"))
    assert os.path.exists(os.path.join(cloud_dir, "cloud_sync", "profiles", "Felix.fenixsync.zip"))

    # 2. Laptop connects to the same cloud_dir -> pulls snapshot into Laptop's local_workspace
    monkeypatch.setattr("opening_fenix.core.utils.get_default_user_dir", lambda: laptop_default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_default_user_dir", lambda: laptop_default_dir)
    set_custom_data_dir(cloud_dir)

    res_laptop_pull = CloudSyncService.sync_now(direction="both")
    assert "1.e4 giri" in res_laptop_pull["pulled_repertoires"]
    assert "Felix" in res_laptop_pull["pulled_profiles"]

    laptop_local_repo_db = os.path.join(get_user_dir(), "repertoires", "1.e4 giri", "1.e4 giri.db")
    assert os.path.exists(laptop_local_repo_db)

    # 3. Laptop updates repertoire comment and pushes to cloud
    conn = sqlite3.connect(laptop_local_repo_db)
    conn.execute("UPDATE positions SET comment = ? WHERE id = 'pos1'", (json.dumps({"en": "Laptop V2 comment"}),))
    conn.commit()
    conn.close()

    res_laptop_push = CloudSyncService.sync_now(direction="push")
    assert "1.e4 giri" in res_laptop_push["pushed_repertoires"]

    # 4. PC launches and pulls the updated snapshot from Laptop
    monkeypatch.setattr("opening_fenix.core.utils.get_default_user_dir", lambda: pc_default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_default_user_dir", lambda: pc_default_dir)

    res_pc_pull = CloudSyncService.sync_now(direction="both")
    assert "1.e4 giri" in res_pc_pull["pulled_repertoires"]

    conn = sqlite3.connect(pc_local_repo_db)
    comment_val = conn.execute("SELECT comment FROM positions WHERE id = 'pos1'").fetchone()[0]
    conn.close()
    assert "Laptop V2 comment" in comment_val


def test_corrupted_db_rejected_by_verify_backup_and_cloud_sync(temp_dir, monkeypatch):
    """
    Ensures a truncated/corrupted SQLite file (e.g. missing pages from interrupted cloud sync)
    is caught by verify_sqlite_db and NEVER overwrites healthy backups or cloud snapshots.
    """
    cloud_dir = os.path.join(temp_dir, "cloud_dir")
    pc_default_dir = os.path.join(temp_dir, "pc_appdata")
    monkeypatch.setattr("opening_fenix.core.utils.get_default_user_dir", lambda: pc_default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_default_user_dir", lambda: pc_default_dir)
    set_custom_data_dir(cloud_dir)

    repo_name = "1.e4 giri"
    local_repo_db = os.path.join(get_user_dir(), "repertoires", repo_name, f"{repo_name}.db")
    _create_valid_sqlite_db(local_repo_db, comment_text="Healthy State")

    # Create a larger DB so it has multiple pages, then sync and backup healthy state
    conn = sqlite3.connect(local_repo_db)
    for i in range(200):
        conn.execute(
            "INSERT INTO positions (id, fen, comment, level, priority) VALUES (?, ?, ?, 1, 1.0)",
            (f"p_{i}", f"fen_{i}", "x" * 400),
        )
    conn.commit()
    conn.close()

    assert verify_sqlite_db(local_repo_db) is True
    bk1 = create_repertoire_backup(repo_name, trigger_type="manual")
    assert bk1 is not None and os.path.exists(bk1)

    sync1 = CloudSyncService.sync_now(direction="push")
    assert repo_name in sync1["pushed_repertoires"]
    healthy_manifest = CloudSyncService.load_manifest(cloud_dir)
    healthy_sha = healthy_manifest["repertoires"][repo_name]["sha256"]

    # Now simulate truncation/corruption of local_repo_db (chop off last 2 pages while header still expects full page count)
    full_size = os.path.getsize(local_repo_db)
    with open(local_repo_db, "r+b") as f:
        f.truncate(full_size - 8192)

    assert verify_sqlite_db(local_repo_db) is False

    # 1. Backup service must refuse to create a backup of the malformed DB
    bk_corrupt = create_repertoire_backup(repo_name, trigger_type="manual")
    assert bk_corrupt is None
    assert len(list_repertoire_backups(repo_name)) == 1

    # 2. CloudSyncService push must refuse to overwrite the healthy cloud snapshot
    sync_corrupt = CloudSyncService.sync_now(direction="push")
    assert repo_name not in sync_corrupt["pushed_repertoires"]
    assert len(sync_corrupt["errors"]) >= 1
    after_manifest = CloudSyncService.load_manifest(cloud_dir)
    assert after_manifest["repertoires"][repo_name]["sha256"] == healthy_sha


def test_cross_device_session_lock(temp_dir, monkeypatch):
    cloud_dir = os.path.join(temp_dir, "cloud_dir")
    pc_default_dir = os.path.join(temp_dir, "pc_appdata")
    monkeypatch.setattr("opening_fenix.core.utils.get_default_user_dir", lambda: pc_default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_default_user_dir", lambda: pc_default_dir)
    set_custom_data_dir(cloud_dir)

    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_device_name", lambda: "DESKTOP-PC")
    CloudSyncService.acquire_session_lock(cloud_dir)

    # Same device -> no conflict
    assert CloudSyncService.check_other_active_session(cloud_dir) is None

    # Different device -> sees active session on DESKTOP-PC
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_device_name", lambda: "LAPTOP-PC")
    other = CloudSyncService.check_other_active_session(cloud_dir)
    assert other is not None
    assert other["device_name"] == "DESKTOP-PC"

    # Release from DESKTOP-PC
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_device_name", lambda: "DESKTOP-PC")
    CloudSyncService.release_session_lock(cloud_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_device_name", lambda: "LAPTOP-PC")
    assert CloudSyncService.check_other_active_session(cloud_dir) is None
