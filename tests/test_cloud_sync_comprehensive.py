import os
import json
import time
import shutil
import sqlite3
from datetime import datetime, timedelta
import pytest

from opening_fenix.core.utils import (
    get_default_user_dir,
    get_custom_data_dir,
    get_configured_custom_data_dir,
    get_local_workspace_dir,
    set_custom_data_dir,
    get_user_dir,
    is_cloud_sync_configured,
    is_cloud_dir_offline,
    request_app_restart,
    is_app_restart_requested,
    ensure_user_data_seeded,
)
from opening_fenix.core.services.cloud_sync_service import (
    CloudSyncService,
    verify_sqlite_db,
    format_relative_time,
)


def _create_repo_db(db_path: str, comment_text: str = "V1") -> None:
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


def _create_profile_db(db_path: str, training_rows=None, settings_rows=None) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS training_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repertoire_name TEXT NOT NULL,
            fen TEXT NOT NULL,
            move_uci TEXT NOT NULL,
            box INTEGER DEFAULT 0,
            next_due TEXT,
            streak INTEGER DEFAULT 0,
            last_review TEXT,
            UNIQUE(repertoire_name, fen, move_uci)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_repertoire_settings (
            repertoire_name TEXT PRIMARY KEY,
            active_level INTEGER DEFAULT 1,
            comment_language TEXT DEFAULT 'auto',
            rating REAL DEFAULT 800.0,
            last_rating_update TEXT,
            last_new_count INTEGER DEFAULT 0,
            last_due_count INTEGER DEFAULT 0,
            last_dist_json TEXT,
            stats_updated_at TEXT
        )
        """
    )
    for row in (training_rows or []):
        c.execute(
            "INSERT OR REPLACE INTO training_data (repertoire_name, fen, move_uci, box, next_due, streak, last_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    for srow in (settings_rows or []):
        c.execute(
            "INSERT OR REPLACE INTO user_repertoire_settings "
            "(repertoire_name, active_level, comment_language, rating, last_rating_update, last_new_count, last_due_count, last_dist_json, stats_updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            srow,
        )
    conn.commit()
    conn.close()


def _switch_device(monkeypatch, default_dir: str, device_name: str):
    monkeypatch.setattr("opening_fenix.core.utils.get_default_user_dir", lambda: default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_default_user_dir", lambda: default_dir)
    monkeypatch.setattr("opening_fenix.core.services.cloud_sync_service.get_device_name", lambda: device_name)
    # Invalidate utils cache when switching mock device
    import opening_fenix.core.utils as u
    u._CUSTOM_DATA_DIR_CACHE["key"] = None
    u._CUSTOM_DATA_DIR_CACHE["value"] = None
    u._CUSTOM_DATA_DIR_CACHE["configured_value"] = None


def test_offline_cloud_drive_keeps_local_workspace(temp_dir, monkeypatch):
    """When cloud drive unmounts / goes offline, app must stay in local_workspace instead of jumping to default_dir."""
    cloud_dir = os.path.join(temp_dir, "GDrive_Fenix")
    pc_default = os.path.join(temp_dir, "PC_AppData")
    _switch_device(monkeypatch, pc_default, "DESKTOP-PC")

    set_custom_data_dir(cloud_dir)
    expected_ws = os.path.abspath(os.path.join(pc_default, "local_workspace"))
    assert get_user_dir() == expected_ws
    assert is_cloud_sync_configured() is True
    assert is_cloud_dir_offline() is False
    assert CloudSyncService.is_enabled() is True

    # Simulate cloud drive unmounting / offline
    shutil.rmtree(cloud_dir)
    assert is_cloud_sync_configured() is True
    assert is_cloud_dir_offline() is True
    assert get_configured_custom_data_dir() == os.path.abspath(cloud_dir)
    assert get_custom_data_dir() is None
    assert CloudSyncService.is_enabled() is False
    # CRITICAL: must stay in local_workspace, never silently revert to pc_default!
    assert get_user_dir() == expected_ws

    st = CloudSyncService.get_sync_status()
    assert st["configured"] is True
    assert st["offline"] is True
    assert st["enabled"] is False
    assert st["local_dir"] == expected_ws

    # Reconnect drive -> back online
    os.makedirs(cloud_dir, exist_ok=True)
    assert is_cloud_dir_offline() is False
    assert CloudSyncService.is_enabled() is True


def test_manifest_ahead_of_zip_hash_race_blocked(temp_dir, monkeypatch):
    """
    Simulates Google Drive syncing sync_manifest.json faster than the large .fenixsync.zip:
    Laptop must detect the db_sha256 mismatch, refuse the stale zip, and NOT advance local_sync_state.
    """
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    laptop_default = os.path.join(temp_dir, "Laptop")

    # 1. PC pushes V1
    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)
    repo_db = os.path.join(get_user_dir(), "repertoires", "Sicilian", "Sicilian.db")
    _create_repo_db(repo_db, "V1")
    res = CloudSyncService.sync_now(direction="push")
    assert "Sicilian" in res["pushed_repertoires"]

    # 2. Laptop pulls V1
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    set_custom_data_dir(cloud_dir)
    res_l1 = CloudSyncService.sync_now(direction="both")
    assert "Sicilian" in res_l1["pulled_repertoires"]

    # 3. Simulate manifest updated to V2 while zip on disk is still V1!
    manifest = CloudSyncService.load_manifest(cloud_dir)
    manifest["repertoires"]["Sicilian"]["sha256"] = "fake_v2_composite_sha"
    manifest["repertoires"]["Sicilian"]["db_sha256"] = "fake_v2_db_sha"
    manifest["repertoires"]["Sicilian"]["zip_sha256"] = "fake_v2_zip_sha"
    CloudSyncService.save_manifest(manifest, cloud_dir)

    res_l2 = CloudSyncService.sync_now(direction="both")
    assert "Sicilian" not in res_l2["pulled_repertoires"]
    assert "repertoire:Sicilian" in res_l2["pending_downloads"]
    # Ensure local_sync_state did NOT falsely mark fake_v2_composite_sha as synced
    l_state = CloudSyncService.load_local_state()
    assert l_state["repertoires"]["Sicilian"]["synced_snapshot_sha256"] != "fake_v2_composite_sha"


def test_skip_unchanged_zip_rewrite_on_mtime_touch(temp_dir, monkeypatch):
    """Touching DB mtime without changing content must NOT rewrite the cloud zip or mark manifest dirty."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)

    repo_db = os.path.join(get_user_dir(), "repertoires", "Caro", "Caro.db")
    _create_repo_db(repo_db, "Unchanged")
    res1 = CloudSyncService.sync_now(direction="push")
    assert "Caro" in res1["pushed_repertoires"]

    zip_path = os.path.join(cloud_dir, "cloud_sync", "repertoires", "Caro.fenixsync.zip")
    orig_zip_mtime = os.stat(zip_path).st_mtime_ns
    orig_manifest_updated = CloudSyncService.load_manifest(cloud_dir)["updated_at"]

    # Touch local DB mtime (simulates read-only open / WAL checkpoint without logical change)
    time.sleep(0.05)
    os.utime(repo_db, None)

    res2 = CloudSyncService.sync_now(direction="push")
    assert "Caro" not in res2["pushed_repertoires"]
    assert os.stat(zip_path).st_mtime_ns == orig_zip_mtime
    assert CloudSyncService.load_manifest(cloud_dir)["updated_at"] == orig_manifest_updated


def test_profile_deletion_and_asset_cleanup_propagation(temp_dir, monkeypatch):
    """Deleting a profile or a repertoire sub-asset on PC must propagate cleanly to Laptop without resurrection."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    laptop_default = os.path.join(temp_dir, "Laptop")

    # 1. PC creates repo with 2 PGN assets + profile
    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)
    pc_repo_dir = os.path.join(get_user_dir(), "repertoires", "French")
    _create_repo_db(os.path.join(pc_repo_dir, "French.db"), "French V1")
    with open(os.path.join(pc_repo_dir, "keep.pgn"), "w", encoding="utf-8") as f:
        f.write("1. e4 e6")
    with open(os.path.join(pc_repo_dir, "obsolete.pgn"), "w", encoding="utf-8") as f:
        f.write("1. d4 d5")
    pc_prof_db = os.path.join(get_user_dir(), "profiles", "OldUser.db")
    _create_profile_db(pc_prof_db)
    CloudSyncService.sync_now(direction="push")

    # 2. Laptop pulls both
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    set_custom_data_dir(cloud_dir)
    CloudSyncService.sync_now(direction="both")
    laptop_repo_dir = os.path.join(get_user_dir(), "repertoires", "French")
    laptop_prof_db = os.path.join(get_user_dir(), "profiles", "OldUser.db")
    assert os.path.exists(os.path.join(laptop_repo_dir, "obsolete.pgn"))
    assert os.path.exists(laptop_prof_db)

    # 3. PC deletes obsolete.pgn AND deletes OldUser profile
    _switch_device(monkeypatch, pc_default, "PC")
    os.remove(os.path.join(pc_repo_dir, "obsolete.pgn"))
    os.remove(pc_prof_db)
    res_pc_del = CloudSyncService.sync_now(direction="push")
    assert "OldUser" in res_pc_del["deleted_cloud_profiles"]
    assert "French" in res_pc_del["pushed_repertoires"]

    # 4. Laptop pulls -> obsolete.pgn and OldUser.db are both removed!
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    res_lap_pull = CloudSyncService.sync_now(direction="both")
    assert "OldUser" in res_lap_pull["deleted_local_profiles"]
    assert not os.path.exists(laptop_prof_db)
    assert not os.path.exists(os.path.join(laptop_repo_dir, "obsolete.pgn"))
    assert os.path.exists(os.path.join(laptop_repo_dir, "keep.pgn"))

    # 5. Next PC sync must NOT resurrect OldUser!
    _switch_device(monkeypatch, pc_default, "PC")
    CloudSyncService.sync_now(direction="both")
    assert not os.path.exists(pc_prof_db)


def test_profile_conflict_lossless_smart_merge(temp_dir, monkeypatch):
    """Offline training on BOTH PC and Laptop must merge losslessly instead of wiping either device's progress."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    laptop_default = os.path.join(temp_dir, "Laptop")

    # 1. PC seeds initial profile with Move Shared (older timestamp)
    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)
    pc_prof_db = os.path.join(get_user_dir(), "profiles", "Felix.db")
    _create_profile_db(
        pc_prof_db,
        training_rows=[("1.e4", "fen_shared", "e2e4", 1, "2026-11-24 10:00:00", 1, "2026-11-20 10:00:00")],
        settings_rows=[("1.e4", 1, "auto", 1200.0, "2026-11-20 10:00:00", 5, 2, "{}", "2026-11-20 10:00:00")],
    )
    CloudSyncService.sync_now(direction="push")

    # 2. Laptop pulls initial profile
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    set_custom_data_dir(cloud_dir)
    CloudSyncService.sync_now(direction="both")
    laptop_prof_db = os.path.join(get_user_dir(), "profiles", "Felix.db")

    # 3. PC trains Move A + updates Shared to 11:00 and pushes
    _switch_device(monkeypatch, pc_default, "PC")
    conn = sqlite3.connect(pc_prof_db)
    conn.execute(
        "INSERT INTO training_data (repertoire_name, fen, move_uci, box, next_due, streak, last_review) "
        "VALUES ('1.e4', 'fen_pc', 'g1f3', 2, '2026-11-25 10:00:00', 2, '2026-11-23 11:00:00')"
    )
    conn.execute(
        "UPDATE training_data SET box=2, streak=2, last_review='2026-11-23 11:00:00' WHERE fen='fen_shared'"
    )
    conn.commit()
    conn.close()
    CloudSyncService.sync_now(direction="push")

    # 4. Meanwhile Laptop OFFLINE trains Move B + updates Shared even newer (12:30)
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    conn = sqlite3.connect(laptop_prof_db)
    conn.execute(
        "INSERT INTO training_data (repertoire_name, fen, move_uci, box, next_due, streak, last_review) "
        "VALUES ('1.e4', 'fen_laptop', 'f1b5', 3, '2026-11-26 10:00:00', 3, '2026-11-23 12:30:00')"
    )
    conn.execute(
        "UPDATE training_data SET box=4, streak=4, last_review='2026-11-23 12:30:00' WHERE fen='fen_shared'"
    )
    conn.commit()
    conn.close()

    # 5. Laptop syncs -> must backup, smart-merge, and push merged DB back to cloud!
    res_merge = CloudSyncService.sync_now(direction="both")
    assert "Felix" in res_merge["merged_profiles"]
    assert "Felix" in res_merge["pushed_profiles"]

    # Verify all 3 moves exist on Laptop and Shared kept Laptop's newer box=4
    conn = sqlite3.connect(laptop_prof_db)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT fen, box, last_review FROM training_data").fetchall()}
    conn.close()
    assert "fen_pc" in rows
    assert "fen_laptop" in rows
    assert rows["fen_shared"][0] == 4

    # Verify conflict backup was created
    prof_bk_dir = os.path.join(cloud_dir, "backups", "_profiles", "Felix")
    assert os.path.isdir(prof_bk_dir)
    assert any(f.endswith(".zip") for f in os.listdir(prof_bk_dir))

    # 6. PC pulls merged profile and now has fen_laptop too!
    _switch_device(monkeypatch, pc_default, "PC")
    CloudSyncService.sync_now(direction="both")
    conn = sqlite3.connect(pc_prof_db)
    pc_fens = {r[0] for r in conn.execute("SELECT fen FROM training_data").fetchall()}
    conn.close()
    assert {"fen_shared", "fen_pc", "fen_laptop"}.issubset(pc_fens)


def test_repertoire_conflict_backup_and_restore(temp_dir, monkeypatch):
    """Dual offline repertoire edit must record conflict metadata, save backup, and support 1-click local restore."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    laptop_default = os.path.join(temp_dir, "Laptop")

    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)
    pc_db = os.path.join(get_user_dir(), "repertoires", "Grunfeld", "Grunfeld.db")
    _create_repo_db(pc_db, "Base")
    CloudSyncService.sync_now(direction="push")

    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    set_custom_data_dir(cloud_dir)
    CloudSyncService.sync_now(direction="both")
    laptop_db = os.path.join(get_user_dir(), "repertoires", "Grunfeld", "Grunfeld.db")

    # PC edits and pushes
    _switch_device(monkeypatch, pc_default, "PC")
    _create_repo_db(pc_db, "PC Edit")
    CloudSyncService.sync_now(direction="push")

    # Laptop edits offline and syncs
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    _create_repo_db(laptop_db, "Laptop Offline Edit")
    res = CloudSyncService.sync_now(direction="both")
    assert "Grunfeld" in res["conflicts_backed_up"]
    repo_conflicts = [c for c in res["conflicts"] if c["kind"] == "repertoire" and c["name"] == "Grunfeld"]
    assert len(repo_conflicts) == 1
    bk_path = repo_conflicts[0]["backup_path"]
    assert bk_path and os.path.isfile(bk_path)

    # Restore Laptop's local backup and push it to cloud
    ok, _ = CloudSyncService.restore_repertoire_conflict_backup("Grunfeld", bk_path)
    assert ok is True
    conn = sqlite3.connect(laptop_db)
    val = conn.execute("SELECT comment FROM positions WHERE id='pos1'").fetchone()[0]
    conn.close()
    assert "Laptop Offline Edit" in val


def test_portable_settings_dictionary_and_engine_cache_sync(temp_dir, monkeypatch):
    """Portable settings & user_dictionary merge cleanly across devices; engine_path stays local; opt-in engine cache merges max depth."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    laptop_default = os.path.join(temp_dir, "Laptop")

    # 1. PC configures settings, dictionary, and enables engine cache sync
    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)
    CloudSyncService.set_sync_options(sync_portable_settings=True, sync_user_dictionary=True, sync_engine_cache=True)

    pc_ws = get_user_dir()
    with open(os.path.join(pc_ws, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"theme": "Blau", "master_volume": 75, "engine_path": "C:/PC/stockfish.exe", "lichess_token": "SECRET_PC"}, f)
    with open(os.path.join(pc_ws, "user_dictionary.txt"), "w", encoding="utf-8") as f:
        f.write("zugzwang\nfianchetto\n")

    pc_cache = os.path.join(pc_ws, "cache", "engine_eval_cache.db")
    os.makedirs(os.path.dirname(pc_cache), exist_ok=True)
    conn = sqlite3.connect(pc_cache)
    conn.execute("CREATE TABLE engine_evals (fen TEXT PRIMARY KEY, depth INT, best_move TEXT)")
    conn.execute("INSERT INTO engine_evals VALUES ('fen1', 24, 'e2e4')")
    conn.commit()
    conn.close()

    CloudSyncService.sync_now(direction="push")

    # 2. Laptop has its own engine_path, its own dictionary word, and a deeper eval for fen1 + a new fen2
    _switch_device(monkeypatch, laptop_default, "LAPTOP")
    set_custom_data_dir(cloud_dir)
    CloudSyncService.set_sync_options(sync_portable_settings=True, sync_user_dictionary=True, sync_engine_cache=True)
    lap_ws = get_user_dir()
    with open(os.path.join(lap_ws, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"theme": "Braun", "engine_path": "D:/Laptop/stockfish.exe"}, f)
    with open(os.path.join(lap_ws, "user_dictionary.txt"), "w", encoding="utf-8") as f:
        f.write("zwischenzug\n")

    lap_cache = os.path.join(lap_ws, "cache", "engine_eval_cache.db")
    os.makedirs(os.path.dirname(lap_cache), exist_ok=True)
    conn = sqlite3.connect(lap_cache)
    conn.execute("CREATE TABLE engine_evals (fen TEXT PRIMARY KEY, depth INT, best_move TEXT)")
    conn.execute("INSERT INTO engine_evals VALUES ('fen1', 28, 'd2d4')")
    conn.execute("INSERT INTO engine_evals VALUES ('fen2', 20, 'c2c4')")
    conn.commit()
    conn.close()

    CloudSyncService.sync_now(direction="both")

    # Verify portable settings pulled while engine_path stayed Laptop's local path and lichess_token was NOT leaked
    with open(os.path.join(lap_ws, "config.json"), "r", encoding="utf-8") as f:
        lap_cfg = json.load(f)
    assert lap_cfg["theme"] == "Blau"
    assert lap_cfg["master_volume"] == 75
    assert lap_cfg["engine_path"] == "D:/Laptop/stockfish.exe"
    assert "lichess_token" not in lap_cfg

    # Verify dictionary union merge
    with open(os.path.join(lap_ws, "user_dictionary.txt"), "r", encoding="utf-8") as f:
        words = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    assert words == {"fianchetto", "zugzwang", "zwischenzug"}

    # Verify engine cache merge kept depth 28 for fen1 AND fen2
    conn = sqlite3.connect(lap_cache)
    evals = dict(conn.execute("SELECT fen, depth FROM engine_evals").fetchall())
    conn.close()
    assert evals["fen1"] == 28
    assert evals["fen2"] == 20


def test_selective_sync_inspector_and_provider_conflict_detection(temp_dir, monkeypatch):
    """Excluded repertoires are skipped; inspector reports accurate states; provider conflict copies are detected."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    _switch_device(monkeypatch, pc_default, "PC")
    set_custom_data_dir(cloud_dir)

    _create_repo_db(os.path.join(get_user_dir(), "repertoires", "MainRepo", "MainRepo.db"), "Main")
    _create_repo_db(os.path.join(get_user_dir(), "repertoires", "HugeDraft", "HugeDraft.db"), "Draft")
    CloudSyncService.set_repertoire_excluded("HugeDraft", True)

    res = CloudSyncService.sync_now(direction="push")
    assert "MainRepo" in res["pushed_repertoires"]
    assert "HugeDraft" not in res["pushed_repertoires"]

    # Place a fake Google Drive conflict duplicate in cloud_sync/
    with open(os.path.join(cloud_dir, "cloud_sync", "sync_manifest (1).json"), "w", encoding="utf-8") as f:
        f.write("{}")

    conflicts = CloudSyncService.detect_provider_conflict_files(cloud_dir)
    assert "sync_manifest (1).json" in conflicts

    items = {i["name"]: i for i in CloudSyncService.get_detailed_items_status()}
    assert items["MainRepo"]["state"] == "synced"
    assert items["HugeDraft"]["state"] == "excluded"


def test_modern_session_lock_timeout_and_deleted_seeding_guard(temp_dir, monkeypatch):
    """Modern lock with heartbeat_interval_sec expires after 10 min; ensure_user_data_seeded skips deleted cloud repos."""
    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    _switch_device(monkeypatch, pc_default, "DESKTOP-A")
    set_custom_data_dir(cloud_dir)

    lock_path = CloudSyncService.get_active_session_path(cloud_dir)
    old_ts = (datetime.now() - timedelta(minutes=15)).isoformat(timespec="seconds")

    # Modern lock older than 10 min -> expired!
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"device_name": "DESKTOP-B", "heartbeat_at": old_ts, "heartbeat_interval_sec": 60}, f)
    assert CloudSyncService.check_other_active_session(cloud_dir) is None

    # Legacy lock (no heartbeat_interval_sec) at 15 min -> still active (6h fallback)
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"device_name": "DESKTOP-B", "heartbeat_at": old_ts}, f)
    assert CloudSyncService.check_other_active_session(cloud_dir) is not None

    # Verify ensure_user_data_seeded does not resurrect deleted_repertoires
    manifest = CloudSyncService.load_manifest(cloud_dir)
    manifest["deleted_repertoires"]["DeletedCourse"] = {"deleted_at": old_ts, "deleted_by": "DESKTOP-B"}
    CloudSyncService.save_manifest(manifest, cloud_dir)

    fake_bundle = os.path.join(temp_dir, "bundle")
    os.makedirs(os.path.join(fake_bundle, "repertoires", "DeletedCourse"), exist_ok=True)
    with open(os.path.join(fake_bundle, "repertoires", "DeletedCourse", "DeletedCourse.db"), "w") as f:
        f.write("bundled")
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", os.path.join(fake_bundle, "app.exe"))
    monkeypatch.setattr("opening_fenix.core.utils.is_public_version", lambda: False)
    monkeypatch.setattr("opening_fenix.core.utils.is_example_repertoire", lambda name: False)

    ensure_user_data_seeded()
    assert not os.path.exists(os.path.join(get_user_dir(), "repertoires", "DeletedCourse"))


def test_cloud_sync_ui_widgets_and_deferred_restart(qapp, temp_dir, monkeypatch):
    """Smoke-tests CloudSyncStatusPill, CloudSyncConflictDialog, CloudFolderSetupDialog, and deferred restart flag."""
    from opening_fenix.gui.widgets.cloud_sync_widgets import (
        CloudSyncStatusPill,
        CloudSyncConflictDialog,
        CloudFolderSetupDialog,
    )

    cloud_dir = os.path.join(temp_dir, "Cloud")
    pc_default = os.path.join(temp_dir, "PC")
    _switch_device(monkeypatch, pc_default, "PC")

    pill = CloudSyncStatusPill()
    assert pill.isVisible() is False

    set_custom_data_dir(cloud_dir)
    pill.apply_status({"configured": True, "state": "synced", "cloud_dir": cloud_dir, "last_sync_rel": "Just now"})
    assert "Sync" in pill.text()
    assert not pill.icon().isNull()

    pill.apply_status({"configured": True, "state": "offline", "cloud_dir": cloud_dir})
    assert "Offline" in pill.text()
    assert not pill.icon().isNull()

    dlg_conflict = CloudSyncConflictDialog(
        conflicts=[{"kind": "repertoire", "name": "Sicilian", "cloud_updated_by": "LAPTOP", "cloud_updated_at": "2026-11-23T18:00:00"}],
        merged_profiles=["Felix"],
        provider_conflict_files=["sync_manifest (1).json"],
    )
    assert dlg_conflict is not None
    dlg_conflict.close()

    dlg_setup = CloudFolderSetupDialog()
    assert dlg_setup is not None
    dlg_setup.close()

    request_app_restart(False)
    assert is_app_restart_requested() is False
    request_app_restart(True)
    assert is_app_restart_requested() is True
    request_app_restart(False)

    assert format_relative_time(datetime.now().isoformat(timespec="seconds")) != ""
