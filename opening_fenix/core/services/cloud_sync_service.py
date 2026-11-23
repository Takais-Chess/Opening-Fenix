import os
import io
import re
import json
import time
import shutil
import socket
import hashlib
import sqlite3
import zipfile
import tempfile
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple, Callable

from opening_fenix.core.utils import (
    get_default_user_dir,
    get_custom_data_dir,
    get_configured_custom_data_dir,
    get_local_workspace_dir,
    get_user_dir,
    is_cloud_sync_configured,
    is_cloud_dir_offline,
)
from opening_fenix.core.logger import logger

SYNC_MANIFEST_FILENAME = "sync_manifest.json"
ACTIVE_SESSION_FILENAME = "active_session.json"
LOCAL_SYNC_STATE_FILENAME = "local_sync_state.json"
SHARED_SETTINGS_FILENAME = "shared_settings.json"
USER_DICTIONARY_FILENAME = "user_dictionary.txt"
ENGINE_CACHE_SNAPSHOT_FILENAME = "engine_eval_cache.fenixsync.zip"
CLOUD_SYNC_SUBDIR = "cloud_sync"

# Global re-entrant lock protecting sync operations within the process
_SYNC_LOCK = threading.RLock()

# Default heartbeat cadence & stale lock timeout (modern clients)
HEARTBEAT_INTERVAL_SECONDS = 60
MODERN_SESSION_MAX_AGE_SECONDS = 10 * 60
LEGACY_SESSION_MAX_AGE_SECONDS = 6 * 3600

# Portable config.json keys safe to synchronize across PC & Laptop
# (Excludes machine-specific paths like engine_path, custom_data_dir, window geometry, lichess_token, auto_login_profile)
PORTABLE_CONFIG_KEYS = (
    "ui_language",
    "theme",
    "board_theme",
    "piece_set",
    "highlight_color",
    "master_volume",
    "sound_enabled",
    "animation_speed",
    "auto_delay",
    "creator_active_tabs",
    "spellcheck_enabled",
    "lichess_delay",
    "auto_check_updates",
    "show_coordinates",
    "show_legal_moves",
    "lockout_enabled",
    "lockout_use_token",
    "lockout_usernames",
)

# Files that should never be packaged into repertoire/profile sync snapshots
_IGNORED_SUFFIXES = (
    ".db-wal",
    ".db-shm",
    ".db-journal",
    "-wal",
    "-shm",
    "-journal",
    ".empty",
    ".malformed",
    ".tmp",
)

# Patterns matching Google Drive / OneDrive / Dropbox conflict copies
_CONFLICT_FILE_PATTERNS = (
    re.compile(r"\(\d+\)\.(json|zip)$", re.IGNORECASE),
    re.compile(r"conflicted copy", re.IGNORECASE),
    re.compile(r"conflict", re.IGNORECASE),
    re.compile(r"^sync_manifest-.+\.json$", re.IGNORECASE),
)


def _is_ignored_repo_file(filename: str) -> bool:
    low = filename.lower()
    if low.endswith(_IGNORED_SUFFIXES):
        return True
    if ".corrupted" in low or ".malformed" in low or ".tmp." in low:
        return True
    if low == "dump.sql":
        return True
    return False


def get_device_name() -> str:
    try:
        return socket.gethostname() or "Unknown-PC"
    except Exception:
        return "Unknown-PC"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def format_relative_time(iso_str: Optional[str]) -> str:
    """Formats an ISO timestamp into a user-friendly relative time string (localized)."""
    if not iso_str:
        return ""
    try:
        from opening_fenix.core.translation import tr_ui
    except Exception:
        def tr_ui(key, default, **kwargs):
            return default.format(**kwargs) if kwargs else default

    try:
        dt = datetime.fromisoformat(str(iso_str))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt
        total_sec = int(delta.total_seconds())
        if total_sec < 0:
            total_sec = 0
        if total_sec < 60:
            return tr_ui("cloud_sync.rel_just_now", "Gerade eben")
        if total_sec < 3600:
            mins = total_sec // 60
            return tr_ui("cloud_sync.rel_minutes_ago", "Vor {n} Min.", n=mins)
        if total_sec < 86400:
            hrs = total_sec // 3600
            return tr_ui("cloud_sync.rel_hours_ago", "Vor {n} Std.", n=hrs)
        days = delta.days
        if days == 1:
            return tr_ui("cloud_sync.rel_yesterday", "Gestern")
        return tr_ui("cloud_sync.rel_days_ago", "Vor {n} Tagen", n=days)
    except Exception:
        return str(iso_str)


def _unique_tmp_path(target_path: str) -> str:
    return f"{target_path}.tmp.{os.getpid()}.{threading.get_ident()}"


def _safe_replace(src_path: str, dst_path: str, retries: int = 5, delay: float = 0.08) -> None:
    """Atomically replaces dst_path with src_path with short Windows file-lock retries."""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            os.replace(src_path, dst_path)
            return
        except PermissionError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
        except OSError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    if last_err is not None:
        raise last_err


def _safe_extract_zip(zip_path: str, dst_dir: str) -> Tuple[bool, str]:
    """
    Validates zip integrity (CRC check via testzip) and guards against Zip Slip
    path traversal before extracting into dst_dir.
    """
    dst_abs = os.path.abspath(dst_dir)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                return False, f"Corrupted zip entry: {bad_member}"
            for member in zf.namelist():
                member_target = os.path.abspath(os.path.join(dst_abs, member))
                if not (member_target == dst_abs or member_target.startswith(dst_abs + os.sep)):
                    return False, f"Unsafe zip entry path: {member}"
            zf.extractall(dst_abs)
        return True, ""
    except zipfile.BadZipFile as e:
        return False, f"Invalid or incomplete zip archive: {e}"
    except Exception as e:
        return False, str(e)


def verify_sqlite_db(db_path: str) -> bool:
    """
    Strictly verifies that a SQLite database file is physically intact:
    1. Exists and is at least 100 bytes with valid SQLite 3 magic header.
    2. If no -wal sidecar exists, file size on disk must be >= in-header page count * page size
       (detects Google Drive truncation before SQLite even opens a query).
    3. Passes PRAGMA quick_check == 'ok' and can read sqlite_master.
    """
    if not db_path or not os.path.exists(db_path):
        return False
    try:
        with open(db_path, "rb") as f:
            hdr = f.read(100)
        if len(hdr) < 100 or hdr[:16] != b"SQLite format 3\x00":
            return False

        conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=10.0)
        try:
            rows = conn.execute("PRAGMA quick_check;").fetchall()
            res = "\n".join(str(r[0]) for r in rows if r and r[0] is not None)
            if res != "ok":
                logger.warning(f"SQLite quick_check failed for {db_path}: {res}")
                return False
            conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()
        finally:
            conn.close()

        # Re-read header and file size after SQLite's read lock / quick_check to avoid
        # TOCTOU races with concurrent writers/migrations appending pages.
        with open(db_path, "rb") as f:
            hdr = f.read(100)
            size = os.fstat(f.fileno()).st_size
        page_size = int.from_bytes(hdr[16:18], "big")
        if page_size == 1:
            page_size = 65536
        in_hdr_pages = int.from_bytes(hdr[28:32], "big")
        wal_exists = os.path.exists(db_path + "-wal") and os.path.getsize(db_path + "-wal") > 0
        journal_exists = os.path.exists(db_path + "-journal") and os.path.getsize(db_path + "-journal") > 0
        if page_size >= 512 and in_hdr_pages > 0 and not wal_exists and not journal_exists:
            expected_size = in_hdr_pages * page_size
            if size < expected_size:
                logger.warning(
                    f"SQLite file truncated: {db_path} has {size} bytes "
                    f"({size / page_size:.1f} pages), header expects {in_hdr_pages} pages ({expected_size} bytes)."
                )
                return False
        return True
    except Exception as e:
        logger.warning(f"SQLite verification failed for {db_path}: {e}")
        return False


def create_verified_db_snapshot(src_db_path: str, dst_db_path: str) -> bool:
    """
    Creates an atomic, self-contained (journal_mode=DELETE) snapshot of src_db_path
    at dst_db_path using SQLite's online backup API, and verifies its integrity.
    Returns True if and only if dst_db_path is a valid, verified SQLite database.
    """
    if not os.path.exists(src_db_path):
        return False

    # Pre-check source before attempting online backup
    if not verify_sqlite_db(src_db_path):
        return False

    os.makedirs(os.path.dirname(os.path.abspath(dst_db_path)), exist_ok=True)
    if os.path.exists(dst_db_path):
        try:
            os.remove(dst_db_path)
        except Exception:
            pass

    src_conn = None
    dst_conn = None
    try:
        src_uri = f"file:{os.path.abspath(src_db_path)}?mode=ro"
        src_conn = sqlite3.connect(src_uri, uri=True, timeout=15.0)
        dst_conn = sqlite3.connect(dst_db_path, timeout=15.0)
        src_conn.backup(dst_conn)
        dst_conn.close()
        dst_conn = None
        src_conn.close()
        src_conn = None

        # Normalize snapshot header to journal_mode=DELETE (write/read version 1/1)
        # so the archived DB never expects a -wal sidecar when extracted on another device.
        norm_conn = sqlite3.connect(dst_db_path, timeout=10.0)
        try:
            norm_conn.execute("PRAGMA journal_mode=DELETE;")
            norm_conn.commit()
        finally:
            norm_conn.close()

        for sidecar in (dst_db_path + "-wal", dst_db_path + "-shm", dst_db_path + "-journal"):
            if os.path.exists(sidecar):
                try:
                    os.remove(sidecar)
                except Exception:
                    pass

        return verify_sqlite_db(dst_db_path)
    except Exception as e:
        logger.warning(f"Failed to create verified DB snapshot from {src_db_path}: {e}")
        if os.path.exists(dst_db_path):
            try:
                os.remove(dst_db_path)
            except Exception:
                pass
        return False
    finally:
        for c in (dst_conn, src_conn):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = _unique_tmp_path(path)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    _safe_replace(tmp_path, path)


def _read_json_safe(path: str, default: Optional[dict] = None) -> dict:
    if not path or not os.path.exists(path):
        return dict(default) if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(f"Could not read JSON file {path}: {e}")
    return dict(default) if default is not None else {}


def _compute_repo_local_fingerprint(repo_dir: str, repo_name: str) -> str:
    """
    Fast O(1) metadata fingerprint (mtime_ns + size) for all relevant files in a local
    repertoire directory to skip unchanged repertoires without reading megabytes of data.
    """
    parts: List[str] = []
    if not os.path.exists(repo_dir):
        return ""
    for root, dirs, files in os.walk(repo_dir):
        dirs.sort()
        for fname in sorted(files):
            low = fname.lower()
            if low.endswith(("-shm", ".tmp")) or ".corrupted" in low or ".malformed" in low or ".tmp." in low:
                continue
            full_p = os.path.join(root, fname)
            rel_p = os.path.relpath(full_p, repo_dir).replace("\\", "/")
            try:
                st = os.stat(full_p)
                parts.append(f"{rel_p}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                pass
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_profile_local_fingerprint(profiles_dir: str, profile_name: str) -> str:
    parts: List[str] = []
    for suffix in (f"{profile_name}.db", f"{profile_name}.db-wal", f"{profile_name}_settings.json"):
        fp = os.path.join(profiles_dir, suffix)
        if os.path.exists(fp):
            try:
                st = os.stat(fp)
                parts.append(f"{suffix}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                pass
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _parse_dt_comparable(val: Any) -> Tuple[int, str]:
    """Returns a comparable tuple (has_value, normalized_iso) for SQLite datetime values."""
    if val is None:
        return (0, "")
    s = str(val).strip()
    if not s:
        return (0, "")
    return (1, s)


def _merge_profile_dbs(
    local_db_path: str,
    cloud_db_path: str,
    merged_db_path: str,
) -> Tuple[bool, Dict[str, int]]:
    """
    Losslessly merges two conflicting SQLite User Profile databases (local offline training
    + cloud training) into merged_db_path:
    - `training_data`: keyed by (repertoire_name, fen, move_uci); keeps row with newer
      last_review (or non-NULL last_review, or higher box/streak tie-break).
    - `user_repertoire_settings`: keyed by repertoire_name; keeps row with newer
      last_rating_update / stats_updated_at.
    Returns (success, merge_stats).
    """
    stats = {"training_rows_kept_local": 0, "training_rows_added_local": 0, "settings_kept_local": 0}
    if not verify_sqlite_db(cloud_db_path) or not verify_sqlite_db(local_db_path):
        return False, stats

    if not create_verified_db_snapshot(cloud_db_path, merged_db_path):
        return False, stats

    local_conn = None
    merged_conn = None
    try:
        local_conn = sqlite3.connect(f"file:{os.path.abspath(local_db_path)}?mode=ro", uri=True, timeout=15.0)
        local_conn.row_factory = sqlite3.Row
        merged_conn = sqlite3.connect(merged_db_path, timeout=15.0)
        merged_conn.row_factory = sqlite3.Row

        local_tables = {r[0] for r in local_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        merged_tables = {r[0] for r in merged_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        # 1. Merge training_data
        if "training_data" in local_tables and "training_data" in merged_tables:
            existing_map: Dict[Tuple[str, str, str], dict] = {}
            for row in merged_conn.execute(
                "SELECT id, repertoire_name, fen, move_uci, box, next_due, streak, last_review FROM training_data"
            ):
                key = (row["repertoire_name"], row["fen"], row["move_uci"])
                existing_map[key] = dict(row)

            for lrow in local_conn.execute(
                "SELECT repertoire_name, fen, move_uci, box, next_due, streak, last_review FROM training_data"
            ):
                key = (lrow["repertoire_name"], lrow["fen"], lrow["move_uci"])
                crow = existing_map.get(key)
                if crow is None:
                    merged_conn.execute(
                        "INSERT INTO training_data (repertoire_name, fen, move_uci, box, next_due, streak, last_review) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            lrow["repertoire_name"],
                            lrow["fen"],
                            lrow["move_uci"],
                            lrow["box"],
                            lrow["next_due"],
                            lrow["streak"],
                            lrow["last_review"],
                        ),
                    )
                    stats["training_rows_added_local"] += 1
                else:
                    l_ts = _parse_dt_comparable(lrow["last_review"])
                    c_ts = _parse_dt_comparable(crow["last_review"])
                    prefer_local = False
                    if l_ts > c_ts:
                        prefer_local = True
                    elif l_ts == c_ts:
                        if (lrow["box"] or 0, lrow["streak"] or 0) > (crow["box"] or 0, crow["streak"] or 0):
                            prefer_local = True
                    if prefer_local:
                        merged_conn.execute(
                            "UPDATE training_data SET box=?, next_due=?, streak=?, last_review=? WHERE id=?",
                            (lrow["box"], lrow["next_due"], lrow["streak"], lrow["last_review"], crow["id"]),
                        )
                        stats["training_rows_kept_local"] += 1

        # 2. Merge user_repertoire_settings
        if "user_repertoire_settings" in local_tables and "user_repertoire_settings" in merged_tables:
            m_cols = [r[1] for r in merged_conn.execute("PRAGMA table_info(user_repertoire_settings)").fetchall()]
            l_cols = [r[1] for r in local_conn.execute("PRAGMA table_info(user_repertoire_settings)").fetchall()]
            common_cols = [c for c in m_cols if c in l_cols]
            if "repertoire_name" in common_cols:
                cols_sql = ", ".join(common_cols)
                cloud_settings = {}
                for row in merged_conn.execute(f"SELECT {cols_sql} FROM user_repertoire_settings"):
                    cloud_settings[row["repertoire_name"]] = dict(row)

                for lrow in local_conn.execute(f"SELECT {cols_sql} FROM user_repertoire_settings"):
                    ld = dict(lrow)
                    rname = ld["repertoire_name"]
                    cd = cloud_settings.get(rname)
                    if cd is None:
                        placeholders = ", ".join(["?"] * len(common_cols))
                        merged_conn.execute(
                            f"INSERT INTO user_repertoire_settings ({cols_sql}) VALUES ({placeholders})",
                            [ld[c] for c in common_cols],
                        )
                        stats["settings_kept_local"] += 1
                    else:
                        l_key = max(
                            _parse_dt_comparable(ld.get("last_rating_update")),
                            _parse_dt_comparable(ld.get("stats_updated_at")),
                        )
                        c_key = max(
                            _parse_dt_comparable(cd.get("last_rating_update")),
                            _parse_dt_comparable(cd.get("stats_updated_at")),
                        )
                        if l_key > c_key:
                            upd_cols = [c for c in common_cols if c != "repertoire_name"]
                            set_clause = ", ".join(f"{c}=?" for c in upd_cols)
                            merged_conn.execute(
                                f"UPDATE user_repertoire_settings SET {set_clause} WHERE repertoire_name=?",
                                [ld[c] for c in upd_cols] + [rname],
                            )
                            stats["settings_kept_local"] += 1

        merged_conn.commit()
        merged_conn.execute("PRAGMA journal_mode=DELETE;")
        merged_conn.commit()
        merged_conn.close()
        merged_conn = None
        local_conn.close()
        local_conn = None
        return verify_sqlite_db(merged_db_path), stats
    except Exception as e:
        logger.warning(f"CloudSync: Profile DB smart merge failed: {e}")
        return False, stats
    finally:
        for c in (merged_conn, local_conn):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass


def _merge_engine_cache_dbs(local_db_path: str, cloud_db_path: str, merged_db_path: str) -> bool:
    """Merges two engine_eval_cache.db files, keeping the higher depth entry per FEN."""
    if not verify_sqlite_db(cloud_db_path) or not verify_sqlite_db(local_db_path):
        return False
    if not create_verified_db_snapshot(cloud_db_path, merged_db_path):
        return False
    local_conn = None
    merged_conn = None
    try:
        local_conn = sqlite3.connect(f"file:{os.path.abspath(local_db_path)}?mode=ro", uri=True, timeout=15.0)
        merged_conn = sqlite3.connect(merged_db_path, timeout=15.0)
        l_tables = {r[0] for r in local_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        m_tables = {r[0] for r in merged_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "engine_evals" in l_tables and "engine_evals" in m_tables:
            m_cols = [r[1] for r in merged_conn.execute("PRAGMA table_info(engine_evals)").fetchall()]
            l_cols = [r[1] for r in local_conn.execute("PRAGMA table_info(engine_evals)").fetchall()]
            common_cols = [c for c in m_cols if c in l_cols]
            if "fen" in common_cols and "depth" in common_cols:
                cols_sql = ", ".join(common_cols)
                fen_idx = common_cols.index("fen")
                depth_idx = common_cols.index("depth")
                existing_depths = dict(merged_conn.execute("SELECT fen, depth FROM engine_evals").fetchall())
                to_upsert = []
                for row in local_conn.execute(f"SELECT {cols_sql} FROM engine_evals"):
                    fen = row[fen_idx]
                    depth = row[depth_idx] or 0
                    if fen not in existing_depths or depth > (existing_depths[fen] or 0):
                        to_upsert.append(row)
                if to_upsert:
                    placeholders = ", ".join(["?"] * len(common_cols))
                    merged_conn.executemany(
                        f"INSERT OR REPLACE INTO engine_evals ({cols_sql}) VALUES ({placeholders})",
                        to_upsert,
                    )
        merged_conn.commit()
        merged_conn.execute("PRAGMA journal_mode=DELETE;")
        merged_conn.commit()
        merged_conn.close()
        merged_conn = None
        local_conn.close()
        local_conn = None
        return verify_sqlite_db(merged_db_path)
    except Exception as e:
        logger.warning(f"CloudSync: Engine cache merge failed: {e}")
        return False
    finally:
        for c in (merged_conn, local_conn):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass


class CloudSyncService:
    """
    Manages safe PC <-> Laptop synchronization via a cloud folder (Google Drive, OneDrive, etc.).

    Architecture:
    - Live SQLite databases (.db, .db-wal, .db-shm) NEVER run inside the cloud folder.
      They run exclusively in `get_local_workspace_dir()` (%APPDATA%/Opening Fenix/local_workspace),
      even when the cloud drive is temporarily offline/unmounted.
    - The cloud folder (`get_custom_data_dir()`) stores:
      * `cloud_sync/sync_manifest.json`
      * `cloud_sync/repertoires/<repo_name>.fenixsync.zip` (atomic, quick_check + SHA256-verified snapshots)
      * `cloud_sync/profiles/<profile_name>.fenixsync.zip` (atomic, quick_check + SHA256-verified snapshots)
      * `cloud_sync/shared_settings.json` (portable UI/training preferences)
      * `cloud_sync/user_dictionary.txt` (union-merged custom spellcheck words)
      * `cloud_sync/engine_eval_cache.fenixsync.zip` (opt-in Stockfish eval cache)
      * `cloud_sync/active_session.json` (cross-device lock & 60s heartbeat)
      * `backups/<repo_name>/backup_*.zip` and `backups/_profiles/<profile>/backup_*.zip`
    """

    @staticmethod
    def is_configured() -> bool:
        """True if a cloud folder is configured in master config.json (even if currently offline)."""
        return is_cloud_sync_configured()

    @staticmethod
    def is_offline() -> bool:
        """True if cloud sync is configured, but the cloud folder is currently unreachable/unmounted."""
        return is_cloud_dir_offline()

    @staticmethod
    def get_configured_cloud_dir() -> Optional[str]:
        if not CloudSyncService.is_configured():
            return None
        return get_configured_custom_data_dir()

    @staticmethod
    def is_enabled() -> bool:
        """True if cloud sync is configured AND the cloud folder currently exists/is online."""
        cloud_dir = get_custom_data_dir()
        default_dir = get_default_user_dir()
        if not cloud_dir or not os.path.exists(cloud_dir):
            return False
        return os.path.normcase(os.path.abspath(cloud_dir)) != os.path.normcase(os.path.abspath(default_dir))

    @staticmethod
    def get_cloud_dir() -> Optional[str]:
        if not CloudSyncService.is_enabled():
            return None
        return get_custom_data_dir()

    @staticmethod
    def get_cloud_sync_root(cloud_dir: Optional[str] = None) -> Optional[str]:
        c_dir = cloud_dir or CloudSyncService.get_cloud_dir()
        if not c_dir or not os.path.exists(c_dir):
            return None
        root = os.path.join(c_dir, CLOUD_SYNC_SUBDIR)
        os.makedirs(os.path.join(root, "repertoires"), exist_ok=True)
        os.makedirs(os.path.join(root, "profiles"), exist_ok=True)
        return root

    @staticmethod
    def get_manifest_path(cloud_dir: Optional[str] = None) -> Optional[str]:
        sync_root = CloudSyncService.get_cloud_sync_root(cloud_dir)
        if not sync_root:
            return None
        return os.path.join(sync_root, SYNC_MANIFEST_FILENAME)

    @staticmethod
    def get_local_state_path(local_dir: Optional[str] = None) -> str:
        l_dir = local_dir or get_local_workspace_dir()
        os.makedirs(l_dir, exist_ok=True)
        return os.path.join(l_dir, LOCAL_SYNC_STATE_FILENAME)

    # ─── Cloud Sync Options & Selective Sync ────────────────────────────────

    @staticmethod
    def get_sync_options() -> Dict[str, Any]:
        """Reads user cloud sync preferences from master config.json."""
        defaults = {
            "sync_portable_settings": True,
            "sync_user_dictionary": True,
            "sync_engine_cache": False,
            "excluded_repertoires": [],
        }
        master_cfg_path = os.path.join(get_default_user_dir(), "config.json")
        cfg = _read_json_safe(master_cfg_path)
        opts = cfg.get("cloud_sync_options", {})
        if not isinstance(opts, dict):
            opts = {}
        merged = dict(defaults)
        merged.update(opts)
        if not isinstance(merged.get("excluded_repertoires"), list):
            merged["excluded_repertoires"] = []
        return merged

    @staticmethod
    def set_sync_options(**kwargs) -> Dict[str, Any]:
        """Updates one or more cloud sync options in master config.json."""
        default_dir = get_default_user_dir()
        os.makedirs(default_dir, exist_ok=True)
        master_cfg_path = os.path.join(default_dir, "config.json")
        cfg = _read_json_safe(master_cfg_path)
        opts = CloudSyncService.get_sync_options()
        for k, v in kwargs.items():
            if k in ("sync_portable_settings", "sync_user_dictionary", "sync_engine_cache"):
                opts[k] = bool(v)
            elif k == "excluded_repertoires" and isinstance(v, (list, set, tuple)):
                opts[k] = sorted(set(str(x) for x in v if x))
        cfg["cloud_sync_options"] = opts
        _atomic_write_json(master_cfg_path, cfg)
        return opts

    @staticmethod
    def get_excluded_repertoires() -> List[str]:
        return list(CloudSyncService.get_sync_options().get("excluded_repertoires", []))

    @staticmethod
    def set_repertoire_excluded(repo_name: str, excluded: bool) -> List[str]:
        excl = set(CloudSyncService.get_excluded_repertoires())
        if excluded:
            excl.add(repo_name)
        else:
            excl.discard(repo_name)
        opts = CloudSyncService.set_sync_options(excluded_repertoires=sorted(excl))
        return opts["excluded_repertoires"]

    # ─── Cloud Provider Auto-Detection ──────────────────────────────────────

    @staticmethod
    def detect_cloud_folders() -> List[Dict[str, Any]]:
        """
        Detects installed cloud storage folders (Google Drive, OneDrive, Dropbox, iCloud, Nextcloud)
        and checks whether an Opening Fenix sync folder already exists inside them.
        """
        home = os.path.expanduser("~")
        candidates: List[Tuple[str, str, str]] = []

        # Google Drive (Windows Drive for Desktop & legacy folder)
        for drive_letter in ("G", "H", "I", "F", "E", "D"):
            for sub in ("My Drive", "Meine Ablage"):
                p = f"{drive_letter}:\\{sub}"
                if os.path.isdir(p):
                    candidates.append(("Google Drive", "🟢", p))
        for gd_sub in ("Google Drive", "Google Drive\\My Drive", "Google Drive\\Meine Ablage"):
            p = os.path.join(home, gd_sub)
            if os.path.isdir(p):
                candidates.append(("Google Drive", "🟢", p))

        # OneDrive
        for env_key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            env_val = os.environ.get(env_key)
            if env_val and os.path.isdir(env_val):
                candidates.append(("OneDrive", "🔵", env_val))
        od_home = os.path.join(home, "OneDrive")
        if os.path.isdir(od_home):
            candidates.append(("OneDrive", "🔵", od_home))

        # Dropbox / iCloud / Nextcloud
        for label, icon, folder_name in (
            ("Dropbox", "📦", "Dropbox"),
            ("iCloud Drive", "☁️", "iCloudDrive"),
            ("Nextcloud", "🌐", "Nextcloud"),
        ):
            p = os.path.join(home, folder_name)
            if os.path.isdir(p):
                candidates.append((label, icon, p))

        seen_roots = set()
        results: List[Dict[str, Any]] = []
        for provider, icon, root_path in candidates:
            norm = os.path.normcase(os.path.abspath(root_path))
            if norm in seen_roots:
                continue
            seen_roots.add(norm)

            # Check if an existing Opening Fenix folder exists here
            suggested = os.path.join(root_path, "Opening Fenix")
            has_existing_sync = False
            existing_repo_count = 0
            existing_prof_count = 0
            for candidate_name in ("Opening Fenix", "Opening-Fenix", "OpeningFenix"):
                cpath = os.path.join(root_path, candidate_name)
                mpath = os.path.join(cpath, CLOUD_SYNC_SUBDIR, SYNC_MANIFEST_FILENAME)
                if os.path.isfile(mpath):
                    suggested = cpath
                    has_existing_sync = True
                    mdata = _read_json_safe(mpath)
                    existing_repo_count = len(mdata.get("repertoires", {}))
                    existing_prof_count = len(mdata.get("profiles", {}))
                    break
                elif os.path.isdir(os.path.join(cpath, "repertoires")):
                    suggested = cpath
                    has_existing_sync = True
                    break

            results.append({
                "provider": provider,
                "icon": icon,
                "root_path": os.path.abspath(root_path),
                "suggested_path": os.path.abspath(suggested),
                "has_existing_sync": has_existing_sync,
                "repertoire_count": existing_repo_count,
                "profile_count": existing_prof_count,
            })

        # Prioritize folders that already contain an Opening Fenix sync setup
        results.sort(key=lambda item: (not item["has_existing_sync"], item["provider"]))
        return results

    # ─── Cloud Provider Conflict Copy Detection ─────────────────────────────

    @staticmethod
    def detect_provider_conflict_files(cloud_dir: Optional[str] = None) -> List[str]:
        """Scans cloud_sync/ for Google Drive / OneDrive / Dropbox conflict duplicate files."""
        c_dir = cloud_dir or CloudSyncService.get_cloud_dir()
        if not c_dir or not os.path.exists(c_dir):
            return []
        sync_root = os.path.join(c_dir, CLOUD_SYNC_SUBDIR)
        if not os.path.isdir(sync_root):
            return []
        found: List[str] = []
        for root, _, files in os.walk(sync_root):
            for fname in sorted(files):
                if ".tmp." in fname.lower():
                    continue
                if any(pat.search(fname) for pat in _CONFLICT_FILE_PATTERNS):
                    rel = os.path.relpath(os.path.join(root, fname), sync_root).replace("\\", "/")
                    found.append(rel)
        return found

    # ─── Manifest & Local State I/O ─────────────────────────────────────────

    @staticmethod
    def load_manifest(cloud_dir: Optional[str] = None) -> dict:
        m_path = CloudSyncService.get_manifest_path(cloud_dir)
        default_manifest = {
            "schema_version": 2,
            "updated_at": None,
            "updated_by_device": None,
            "repertoires": {},
            "profiles": {},
            "deleted_repertoires": {},
            "deleted_profiles": {},
            "shared_settings": {},
            "user_dictionary": {},
            "engine_cache": {},
        }
        data = _read_json_safe(m_path, default_manifest)
        for k, v in default_manifest.items():
            if k not in data:
                data[k] = dict(v) if isinstance(v, dict) else v
        return data

    @staticmethod
    def save_manifest(manifest: dict, cloud_dir: Optional[str] = None) -> None:
        m_path = CloudSyncService.get_manifest_path(cloud_dir)
        if not m_path:
            return
        manifest["schema_version"] = max(int(manifest.get("schema_version") or 1), 2)
        manifest["updated_at"] = _now_iso()
        manifest["updated_by_device"] = get_device_name()
        _atomic_write_json(m_path, manifest)

    @staticmethod
    def load_local_state(local_dir: Optional[str] = None, cloud_dir: Optional[str] = None) -> dict:
        s_path = CloudSyncService.get_local_state_path(local_dir)
        c_dir = cloud_dir or CloudSyncService.get_configured_cloud_dir()
        default_state = {
            "cloud_dir": c_dir,
            "last_sync_at": None,
            "last_sync_device": None,
            "legacy_migration_done": False,
            "repertoires": {},
            "profiles": {},
            "known_deleted_repertoires": [],
            "shared_settings_sha256": None,
            "shared_settings_local_fp": None,
            "user_dictionary_sha256": None,
            "engine_cache_sha256": None,
            "engine_cache_local_fp": None,
        }
        data = _read_json_safe(s_path, default_state)
        # If the user switched to a different cloud directory, reset per-item sync state
        if (
            c_dir
            and data.get("cloud_dir")
            and os.path.normcase(os.path.abspath(str(data.get("cloud_dir"))))
            != os.path.normcase(os.path.abspath(c_dir))
        ):
            data = dict(default_state)
        if c_dir:
            data["cloud_dir"] = c_dir
        for k, v in default_state.items():
            if k not in data:
                data[k] = list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)
        return data

    @staticmethod
    def save_local_state(state: dict, local_dir: Optional[str] = None) -> None:
        s_path = CloudSyncService.get_local_state_path(local_dir)
        _atomic_write_json(s_path, state)

    # ─── Session Lock (PC <-> Laptop Concurrent Access Protection) ──────────

    @staticmethod
    def get_active_session_path(cloud_dir: Optional[str] = None) -> Optional[str]:
        sync_root = CloudSyncService.get_cloud_sync_root(cloud_dir)
        if not sync_root:
            return None
        return os.path.join(sync_root, ACTIVE_SESSION_FILENAME)

    @staticmethod
    def check_other_active_session(
        cloud_dir: Optional[str] = None,
        max_age_seconds: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Checks if another device currently holds an active session lock in the cloud folder.
        Modern clients write `heartbeat_interval_sec` and refresh every 60s, so their stale
        timeout is 10 minutes instead of 6 hours. Older lock files fall back to 6 hours.
        """
        lock_path = CloudSyncService.get_active_session_path(cloud_dir)
        if not lock_path or not os.path.exists(lock_path):
            return None
        data = _read_json_safe(lock_path)
        if not data:
            return None
        other_device = data.get("device_name")
        my_device = get_device_name()
        if not other_device or other_device == my_device:
            return None

        effective_max_age = max_age_seconds
        if effective_max_age is None:
            if data.get("heartbeat_interval_sec"):
                effective_max_age = MODERN_SESSION_MAX_AGE_SECONDS
            else:
                effective_max_age = LEGACY_SESSION_MAX_AGE_SECONDS

        hb_str = data.get("heartbeat_at") or data.get("started_at")
        if hb_str:
            try:
                hb_dt = datetime.fromisoformat(hb_str)
                age = (datetime.now() - hb_dt).total_seconds()
                if age > effective_max_age:
                    return None
            except Exception:
                pass
        return data

    @staticmethod
    def acquire_session_lock(cloud_dir: Optional[str] = None) -> None:
        lock_path = CloudSyncService.get_active_session_path(cloud_dir)
        if not lock_path:
            return
        now = _now_iso()
        data = {
            "device_name": get_device_name(),
            "pid": os.getpid(),
            "started_at": now,
            "heartbeat_at": now,
            "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SECONDS,
        }
        try:
            _atomic_write_json(lock_path, data)
        except Exception as e:
            logger.debug(f"Could not write cloud session lock: {e}")

    @staticmethod
    def update_session_heartbeat(cloud_dir: Optional[str] = None) -> None:
        lock_path = CloudSyncService.get_active_session_path(cloud_dir)
        if not lock_path:
            return
        try:
            existing = _read_json_safe(lock_path)
            now = _now_iso()
            my_dev = get_device_name()
            data = {
                "device_name": my_dev,
                "pid": os.getpid(),
                "started_at": existing.get("started_at", now) if existing.get("device_name") == my_dev else now,
                "heartbeat_at": now,
                "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SECONDS,
            }
            _atomic_write_json(lock_path, data)
        except Exception as e:
            logger.debug(f"Could not update cloud session heartbeat: {e}")

    @staticmethod
    def release_session_lock(cloud_dir: Optional[str] = None) -> None:
        lock_path = CloudSyncService.get_active_session_path(cloud_dir)
        if not lock_path or not os.path.exists(lock_path):
            return
        try:
            data = _read_json_safe(lock_path)
            if not data or data.get("device_name") == get_device_name():
                os.remove(lock_path)
        except Exception as e:
            logger.debug(f"Could not remove cloud session lock: {e}")

    # ─── Profile Backup Helper ──────────────────────────────────────────────

    @staticmethod
    def create_profile_backup(
        profile_name: str,
        trigger_type: str = "sync_conflict",
        local_profiles_dir: Optional[str] = None,
    ) -> Optional[str]:
        """Creates a verified backup zip of a user profile DB + settings JSON."""
        l_profs_dir = local_profiles_dir or os.path.join(get_local_workspace_dir(), "profiles")
        src_db = os.path.join(l_profs_dir, f"{profile_name}.db")
        if not os.path.exists(src_db) or not verify_sqlite_db(src_db):
            return None

        try:
            from opening_fenix.core.services.backup_service import get_backups_base_dir
            backups_base = get_backups_base_dir()
        except Exception:
            backups_base = os.path.join(CloudSyncService.get_cloud_dir() or get_local_workspace_dir(), "backups")

        prof_bk_dir = os.path.join(backups_base, "_profiles", profile_name)
        os.makedirs(prof_bk_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bk_zip_path = os.path.join(prof_bk_dir, f"backup_{ts}_{trigger_type}.zip")

        tmp_dir = tempfile.mkdtemp(prefix="fenix_prof_bk_")
        try:
            clean_db = os.path.join(tmp_dir, f"{profile_name}.db")
            if not create_verified_db_snapshot(src_db, clean_db):
                return None
            tmp_zip = _unique_tmp_path(bk_zip_path)
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(clean_db, f"{profile_name}.db")
                settings_p = os.path.join(l_profs_dir, f"{profile_name}_settings.json")
                if os.path.isfile(settings_p):
                    zf.write(settings_p, f"{profile_name}_settings.json")
            _safe_replace(tmp_zip, bk_zip_path)
            return bk_zip_path
        except Exception as e:
            logger.warning(f"CloudSync: Failed to create profile backup for '{profile_name}': {e}")
            return None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ─── Snapshot Packaging & Extraction Helpers ────────────────────────────

    @staticmethod
    def _recover_db_from_backups(cloud_dir: str, repo_name: str, dst_db_path: str) -> bool:
        """
        Attempts to auto-heal a malformed repertoire DB during legacy stepover migration
        by searching cloud_dir/backups/<repo_name>/backup_*.zip from newest to oldest.
        """
        backup_repo_dir = os.path.join(cloud_dir, "backups", repo_name)
        if not os.path.exists(backup_repo_dir):
            return False
        zips = sorted(
            [f for f in os.listdir(backup_repo_dir) if f.lower().endswith(".zip")],
            reverse=True,
        )
        for zname in zips:
            zpath = os.path.join(backup_repo_dir, zname)
            tmp_dir = tempfile.mkdtemp(prefix="fenix_heal_")
            try:
                ok, _ = _safe_extract_zip(zpath, tmp_dir)
                if not ok:
                    continue
                db_members = [f for f in os.listdir(tmp_dir) if f.endswith(".db")]
                if not db_members:
                    continue
                extracted_db = os.path.join(tmp_dir, db_members[0])
                if create_verified_db_snapshot(extracted_db, dst_db_path):
                    logger.info(f"Auto-healed malformed DB for '{repo_name}' from backup '{zname}'.")
                    return True
            except Exception as e:
                logger.debug(f"Backup candidate {zname} failed during auto-heal: {e}")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    @staticmethod
    def _package_repertoire_to_cloud(
        local_repo_dir: str,
        repo_name: str,
        cloud_sync_root: str,
        existing_sha: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Verifies the local repertoire DB, computes deterministic composite SHA256,
        and if changed (or snapshot missing), packages the clean DB + repertoire assets into an
        atomic .fenixsync.zip in cloud_sync/repertoires/.
        Returns:
          - None if local DB is missing or fails integrity verification.
          - {"unchanged": True, "sha256": ...} if content hash matches existing_sha and zip exists.
          - Full manifest entry dict if a new snapshot was written.
        """
        local_db_path = os.path.join(local_repo_dir, f"{repo_name}.db")
        if not os.path.exists(local_db_path):
            return None

        tmp_dir = tempfile.mkdtemp(prefix="fenix_pkg_repo_")
        try:
            clean_db_path = os.path.join(tmp_dir, f"{repo_name}.db")
            if not create_verified_db_snapshot(local_db_path, clean_db_path):
                logger.error(
                    f"CloudSync: Refusing to push repertoire '{repo_name}' because local DB failed integrity check."
                )
                return None

            content_hasher = hashlib.sha256()
            db_sha256 = _sha256_file(clean_db_path)
            content_hasher.update(f"DB:{db_sha256}".encode("utf-8"))

            asset_files: List[Tuple[str, str]] = []
            for root, dirs, files in os.walk(local_repo_dir):
                dirs.sort()
                for fname in sorted(files):
                    if _is_ignored_repo_file(fname):
                        continue
                    if fname.lower().endswith(".db") and root == local_repo_dir:
                        continue
                    full_p = os.path.join(root, fname)
                    if not os.path.isfile(full_p):
                        continue
                    rel_p = os.path.relpath(full_p, local_repo_dir).replace("\\", "/")
                    asset_files.append((full_p, rel_p))
                    content_hasher.update(f"ASSET:{rel_p}:{_sha256_file(full_p)}".encode("utf-8"))

            composite_sha256 = content_hasher.hexdigest()

            rel_zip_path = f"repertoires/{repo_name}.fenixsync.zip"
            final_zip_path = os.path.join(cloud_sync_root, "repertoires", f"{repo_name}.fenixsync.zip")

            # Skip rewriting zip & manifest if content is byte-for-byte identical to cloud
            if existing_sha and existing_sha == composite_sha256 and os.path.exists(final_zip_path):
                return {"unchanged": True, "sha256": composite_sha256, "db_sha256": db_sha256}

            os.makedirs(os.path.dirname(final_zip_path), exist_ok=True)
            tmp_zip_path = _unique_tmp_path(final_zip_path)

            with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(clean_db_path, f"{repo_name}.db")
                for full_p, rel_p in asset_files:
                    zf.write(full_p, rel_p)

            zip_sha256 = _sha256_file(tmp_zip_path)
            _safe_replace(tmp_zip_path, final_zip_path)
            return {
                "sha256": composite_sha256,
                "db_sha256": db_sha256,
                "zip_sha256": zip_sha256,
                "updated_at": _now_iso(),
                "updated_by": get_device_name(),
                "snapshot_file": rel_zip_path,
                "size_bytes": os.path.getsize(final_zip_path),
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _extract_repertoire_from_cloud(
        cloud_sync_root: str,
        repo_name: str,
        manifest_entry: dict,
        local_repo_dir: str,
    ) -> Tuple[bool, str]:
        """
        Extracts a repertoire .fenixsync.zip from cloud_sync into a temp folder,
        verifies zip CRC, verifies SQLite integrity + expected db_sha256 (catching
        Google Drive/OneDrive manifest-ahead-of-zip races), removes stale deleted
        local assets, and atomically updates local_repo_dir.
        Returns (success, error_reason).
        """
        rel_zip = manifest_entry.get("snapshot_file") or f"repertoires/{repo_name}.fenixsync.zip"
        zip_path = os.path.join(cloud_sync_root, rel_zip.replace("/", os.sep))
        if not os.path.exists(zip_path):
            logger.warning(f"CloudSync: Snapshot zip not found at {zip_path}")
            return False, "snapshot_missing"

        # Fast pre-check on zip hash if available
        expected_zip_sha = manifest_entry.get("zip_sha256")
        if expected_zip_sha:
            try:
                actual_zip_sha = _sha256_file(zip_path)
                if actual_zip_sha != expected_zip_sha:
                    logger.warning(
                        f"CloudSync: Snapshot zip for '{repo_name}' does not match manifest hash "
                        f"(cloud client may still be downloading)."
                    )
                    return False, "pending_cloud_download"
            except Exception as e:
                return False, f"read_error:{e}"

        tmp_dir = tempfile.mkdtemp(prefix="fenix_pull_repo_")
        try:
            ok, err = _safe_extract_zip(zip_path, tmp_dir)
            if not ok:
                logger.error(f"CloudSync: Invalid snapshot archive for '{repo_name}': {err}")
                return False, f"bad_archive:{err}"

            extracted_db = os.path.join(tmp_dir, f"{repo_name}.db")
            if not os.path.exists(extracted_db):
                dbs = [f for f in os.listdir(tmp_dir) if f.lower().endswith(".db")]
                if dbs:
                    os.replace(os.path.join(tmp_dir, dbs[0]), extracted_db)

            if not verify_sqlite_db(extracted_db):
                logger.error(f"CloudSync: Extracted snapshot DB for '{repo_name}' failed integrity verification!")
                return False, "db_integrity_failed"

            # Verify extracted DB matches manifest db_sha256 (prevents manifest-ahead-of-zip race)
            expected_db_sha = manifest_entry.get("db_sha256")
            if expected_db_sha:
                actual_db_sha = _sha256_file(extracted_db)
                if actual_db_sha != expected_db_sha:
                    logger.warning(
                        f"CloudSync: Extracted DB hash mismatch for '{repo_name}' "
                        f"(expected {expected_db_sha[:12]}, got {actual_db_sha[:12]}). "
                        f"Cloud sync client likely hasn't finished downloading the updated snapshot yet."
                    )
                    return False, "pending_cloud_download"

            # Invalidate SQLAlchemy cache for this DB path before replacing
            local_db_path = os.path.join(local_repo_dir, f"{repo_name}.db")
            try:
                from opening_fenix.core.db.database import DatabaseManager
                DatabaseManager.invalidate_verified_key(local_db_path)
            except Exception:
                pass

            os.makedirs(local_repo_dir, exist_ok=True)
            for sidecar in (local_db_path + "-wal", local_db_path + "-shm", local_db_path + "-journal"):
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar)
                    except Exception:
                        pass

            # Collect relative paths present in the new snapshot
            snapshot_rel_files = set()
            for root, _, files in os.walk(tmp_dir):
                for fname in files:
                    full_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(full_p, tmp_dir).replace("\\", "/")
                    snapshot_rel_files.add(os.path.normcase(rel_p))

            # Copy/replace snapshot files into local_repo_dir
            for root, _, files in os.walk(tmp_dir):
                rel_root = os.path.relpath(root, tmp_dir)
                target_root = local_repo_dir if rel_root == "." else os.path.join(local_repo_dir, rel_root)
                os.makedirs(target_root, exist_ok=True)
                for fname in files:
                    src_f = os.path.join(root, fname)
                    dst_f = os.path.join(target_root, fname)
                    tmp_dst = _unique_tmp_path(dst_f)
                    shutil.copy2(src_f, tmp_dst)
                    try:
                        _safe_replace(tmp_dst, dst_f)
                    except PermissionError:
                        try:
                            if os.path.exists(tmp_dst):
                                os.remove(tmp_dst)
                        except Exception:
                            pass
                        logger.warning(f"CloudSync: File locked while updating '{dst_f}'.")
                        return False, "file_locked"

            # Remove stale local asset files that were deleted on the other device
            for root, dirs, files in os.walk(local_repo_dir, topdown=False):
                for fname in files:
                    if _is_ignored_repo_file(fname):
                        continue
                    full_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(full_p, local_repo_dir).replace("\\", "/")
                    if os.path.normcase(rel_p) not in snapshot_rel_files:
                        try:
                            os.remove(full_p)
                        except Exception:
                            pass
                if root != local_repo_dir:
                    try:
                        if not os.listdir(root):
                            os.rmdir(root)
                    except Exception:
                        pass

            return True, ""
        except Exception as e:
            logger.error(f"CloudSync: Failed to extract repertoire '{repo_name}' from cloud: {e}")
            return False, str(e)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _package_profile_to_cloud(
        local_profiles_dir: str,
        profile_name: str,
        cloud_sync_root: str,
        existing_sha: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        local_db_path = os.path.join(local_profiles_dir, f"{profile_name}.db")
        if not os.path.exists(local_db_path):
            return None

        tmp_dir = tempfile.mkdtemp(prefix="fenix_pkg_prof_")
        try:
            clean_db_path = os.path.join(tmp_dir, f"{profile_name}.db")
            if not create_verified_db_snapshot(local_db_path, clean_db_path):
                logger.error(
                    f"CloudSync: Refusing to push profile '{profile_name}' because local DB failed integrity check."
                )
                return None

            content_hasher = hashlib.sha256()
            db_sha256 = _sha256_file(clean_db_path)
            content_hasher.update(f"DB:{db_sha256}".encode("utf-8"))

            settings_name = f"{profile_name}_settings.json"
            settings_path = os.path.join(local_profiles_dir, settings_name)
            has_settings = os.path.exists(settings_path) and os.path.isfile(settings_path)
            if has_settings:
                content_hasher.update(f"SETTINGS:{_sha256_file(settings_path)}".encode("utf-8"))

            composite_sha256 = content_hasher.hexdigest()
            rel_zip_path = f"profiles/{profile_name}.fenixsync.zip"
            final_zip_path = os.path.join(cloud_sync_root, "profiles", f"{profile_name}.fenixsync.zip")

            if existing_sha and existing_sha == composite_sha256 and os.path.exists(final_zip_path):
                return {"unchanged": True, "sha256": composite_sha256, "db_sha256": db_sha256}

            os.makedirs(os.path.dirname(final_zip_path), exist_ok=True)
            tmp_zip_path = _unique_tmp_path(final_zip_path)

            with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(clean_db_path, f"{profile_name}.db")
                if has_settings:
                    zf.write(settings_path, settings_name)

            zip_sha256 = _sha256_file(tmp_zip_path)
            _safe_replace(tmp_zip_path, final_zip_path)
            return {
                "sha256": composite_sha256,
                "db_sha256": db_sha256,
                "zip_sha256": zip_sha256,
                "updated_at": _now_iso(),
                "updated_by": get_device_name(),
                "snapshot_file": rel_zip_path,
                "size_bytes": os.path.getsize(final_zip_path),
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _extract_profile_from_cloud(
        cloud_sync_root: str,
        profile_name: str,
        manifest_entry: dict,
        local_profiles_dir: str,
        merge_with_local: bool = False,
    ) -> Tuple[bool, str, bool]:
        """
        Extracts a profile snapshot from cloud_sync, verifies integrity + db_sha256,
        and optionally performs a lossless SQLite merge with the local profile DB.
        Returns (success, error_reason, was_merged).
        """
        rel_zip = manifest_entry.get("snapshot_file") or f"profiles/{profile_name}.fenixsync.zip"
        zip_path = os.path.join(cloud_sync_root, rel_zip.replace("/", os.sep))
        if not os.path.exists(zip_path):
            logger.warning(f"CloudSync: Profile snapshot zip not found at {zip_path}")
            return False, "snapshot_missing", False

        expected_zip_sha = manifest_entry.get("zip_sha256")
        if expected_zip_sha:
            try:
                if _sha256_file(zip_path) != expected_zip_sha:
                    return False, "pending_cloud_download", False
            except Exception as e:
                return False, f"read_error:{e}", False

        tmp_dir = tempfile.mkdtemp(prefix="fenix_pull_prof_")
        try:
            ok, err = _safe_extract_zip(zip_path, tmp_dir)
            if not ok:
                logger.error(f"CloudSync: Invalid profile archive for '{profile_name}': {err}")
                return False, f"bad_archive:{err}", False

            extracted_db = os.path.join(tmp_dir, f"{profile_name}.db")
            if not verify_sqlite_db(extracted_db):
                logger.error(f"CloudSync: Extracted profile DB '{profile_name}' failed integrity verification!")
                return False, "db_integrity_failed", False

            expected_db_sha = manifest_entry.get("db_sha256")
            if expected_db_sha:
                actual_db_sha = _sha256_file(extracted_db)
                if actual_db_sha != expected_db_sha:
                    logger.warning(
                        f"CloudSync: Extracted profile DB hash mismatch for '{profile_name}' "
                        f"(cloud client may still be downloading)."
                    )
                    return False, "pending_cloud_download", False

            local_db_path = os.path.join(local_profiles_dir, f"{profile_name}.db")
            was_merged = False
            if merge_with_local and os.path.exists(local_db_path) and verify_sqlite_db(local_db_path):
                merged_db = os.path.join(tmp_dir, f"{profile_name}_merged.db")
                merged_ok, merge_stats = _merge_profile_dbs(local_db_path, extracted_db, merged_db)
                if merged_ok:
                    os.replace(merged_db, extracted_db)
                    was_merged = True
                    logger.info(f"CloudSync: Smart-merged profile '{profile_name}' ({merge_stats}).")
                # Also shallow-merge settings JSON so local keys aren't lost
                ext_settings_p = os.path.join(tmp_dir, f"{profile_name}_settings.json")
                loc_settings_p = os.path.join(local_profiles_dir, f"{profile_name}_settings.json")
                if os.path.isfile(ext_settings_p) and os.path.isfile(loc_settings_p):
                    try:
                        c_set = _read_json_safe(ext_settings_p)
                        l_set = _read_json_safe(loc_settings_p)
                        merged_set = dict(l_set)
                        merged_set.update(c_set)
                        _atomic_write_json(ext_settings_p, merged_set)
                    except Exception:
                        pass

            try:
                from opening_fenix.core.db.database import DatabaseManager
                DatabaseManager.invalidate_verified_key(local_db_path)
            except Exception:
                pass

            os.makedirs(local_profiles_dir, exist_ok=True)
            for sidecar in (local_db_path + "-wal", local_db_path + "-shm", local_db_path + "-journal"):
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar)
                    except Exception:
                        pass

            for fname in os.listdir(tmp_dir):
                src_f = os.path.join(tmp_dir, fname)
                if os.path.isfile(src_f):
                    dst_f = os.path.join(local_profiles_dir, fname)
                    tmp_dst = _unique_tmp_path(dst_f)
                    shutil.copy2(src_f, tmp_dst)
                    try:
                        _safe_replace(tmp_dst, dst_f)
                    except PermissionError:
                        try:
                            if os.path.exists(tmp_dst):
                                os.remove(tmp_dst)
                        except Exception:
                            pass
                        return False, "file_locked", False

            return True, "", was_merged
        except Exception as e:
            logger.error(f"CloudSync: Failed to extract profile '{profile_name}' from cloud: {e}")
            return False, str(e), False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ─── Portable Settings, User Dictionary & Optional Engine Cache Sync ────

    @staticmethod
    def _sync_portable_settings(
        cloud_sync_root: str,
        local_dir: str,
        manifest: dict,
        local_state: dict,
        direction: str,
        summary: dict,
    ) -> bool:
        """Syncs portable UI/training settings from config.json without overwriting machine-local keys."""
        manifest_dirty = False
        local_cfg_path = os.path.join(local_dir, "config.json")
        cloud_cfg_path = os.path.join(cloud_sync_root, SHARED_SETTINGS_FILENAME)

        local_cfg = _read_json_safe(local_cfg_path)
        local_portable = {k: local_cfg[k] for k in PORTABLE_CONFIG_KEYS if k in local_cfg}
        local_blob = json.dumps(local_portable, sort_keys=True, ensure_ascii=False).encode("utf-8")
        local_sha = hashlib.sha256(local_blob).hexdigest()

        m_entry = manifest.get("shared_settings") or {}
        cloud_sha = m_entry.get("sha256")
        last_synced_sha = local_state.get("shared_settings_sha256")

        # Pull if cloud changed
        if direction in ("both", "pull") and cloud_sha and os.path.isfile(cloud_cfg_path):
            if last_synced_sha != cloud_sha:
                cloud_portable = _read_json_safe(cloud_cfg_path)
                if cloud_portable:
                    changed_any = False
                    for k in PORTABLE_CONFIG_KEYS:
                        if k in cloud_portable and local_cfg.get(k) != cloud_portable[k]:
                            local_cfg[k] = cloud_portable[k]
                            changed_any = True
                    if changed_any or not os.path.exists(local_cfg_path):
                        _atomic_write_json(local_cfg_path, local_cfg)
                        summary["synced_extras"].append("settings:pulled")
                    local_portable = {k: local_cfg[k] for k in PORTABLE_CONFIG_KEYS if k in local_cfg}
                    local_sha = hashlib.sha256(
                        json.dumps(local_portable, sort_keys=True, ensure_ascii=False).encode("utf-8")
                    ).hexdigest()
                    local_state["shared_settings_sha256"] = cloud_sha
                    local_state["shared_settings_local_fp"] = local_sha

        # Push if local portable settings changed
        if direction in ("both", "push") and local_portable:
            if local_sha != cloud_sha or not os.path.isfile(cloud_cfg_path):
                _atomic_write_json(cloud_cfg_path, local_portable)
                manifest["shared_settings"] = {
                    "sha256": local_sha,
                    "updated_at": _now_iso(),
                    "updated_by": get_device_name(),
                }
                local_state["shared_settings_sha256"] = local_sha
                local_state["shared_settings_local_fp"] = local_sha
                summary["synced_extras"].append("settings:pushed")
                manifest_dirty = True

        return manifest_dirty

    @staticmethod
    def _sync_user_dictionary(
        cloud_sync_root: str,
        local_dir: str,
        manifest: dict,
        local_state: dict,
        direction: str,
        summary: dict,
    ) -> bool:
        """Lossless union-merge sync for custom spellcheck words (user_dictionary.txt)."""
        manifest_dirty = False
        local_dict_path = os.path.join(local_dir, USER_DICTIONARY_FILENAME)
        cloud_dict_path = os.path.join(cloud_sync_root, USER_DICTIONARY_FILENAME)

        def _read_words(p: str) -> set:
            words = set()
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f:
                            w = line.strip().lower()
                            if w and not w.startswith("#"):
                                words.add(w)
                except Exception:
                    pass
            return words

        def _write_words(p: str, words: set) -> None:
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            tmp_p = _unique_tmp_path(p)
            with open(tmp_p, "w", encoding="utf-8") as f:
                f.write("# Opening Fenix User Dictionary\n")
                for w in sorted(words):
                    f.write(f"{w}\n")
                f.flush()
                os.fsync(f.fileno())
            _safe_replace(tmp_p, p)

        local_words = _read_words(local_dict_path)
        cloud_words = _read_words(cloud_dict_path)
        if not local_words and not cloud_words:
            return False

        union_words = local_words | cloud_words
        union_sha = hashlib.sha256("\n".join(sorted(union_words)).encode("utf-8")).hexdigest()

        if direction in ("both", "pull") and union_words != local_words:
            _write_words(local_dict_path, union_words)
            summary["synced_extras"].append("dictionary:pulled")

        if direction in ("both", "push") and (union_words != cloud_words or not os.path.isfile(cloud_dict_path)):
            _write_words(cloud_dict_path, union_words)
            manifest["user_dictionary"] = {
                "sha256": union_sha,
                "word_count": len(union_words),
                "updated_at": _now_iso(),
                "updated_by": get_device_name(),
            }
            summary["synced_extras"].append("dictionary:pushed")
            manifest_dirty = True

        local_state["user_dictionary_sha256"] = union_sha
        return manifest_dirty

    @staticmethod
    def _sync_engine_cache(
        cloud_sync_root: str,
        local_dir: str,
        manifest: dict,
        local_state: dict,
        direction: str,
        summary: dict,
    ) -> bool:
        """Opt-in sync for global Stockfish evaluation cache (cache/engine_eval_cache.db)."""
        manifest_dirty = False
        local_cache_db = os.path.join(local_dir, "cache", "engine_eval_cache.db")
        cloud_zip_path = os.path.join(cloud_sync_root, ENGINE_CACHE_SNAPSHOT_FILENAME)
        m_entry = manifest.get("engine_cache") or {}
        cloud_sha = m_entry.get("sha256")

        # Pull / merge from cloud if cloud has newer cache
        if direction in ("both", "pull") and cloud_sha and os.path.isfile(cloud_zip_path):
            if local_state.get("engine_cache_sha256") != cloud_sha or not os.path.exists(local_cache_db):
                tmp_dir = tempfile.mkdtemp(prefix="fenix_ecache_pull_")
                try:
                    ok, _ = _safe_extract_zip(cloud_zip_path, tmp_dir)
                    ext_db = os.path.join(tmp_dir, "engine_eval_cache.db")
                    if ok and verify_sqlite_db(ext_db):
                        if not m_entry.get("db_sha256") or _sha256_file(ext_db) == m_entry.get("db_sha256"):
                            os.makedirs(os.path.dirname(local_cache_db), exist_ok=True)
                            if os.path.exists(local_cache_db) and verify_sqlite_db(local_cache_db):
                                merged_db = os.path.join(tmp_dir, "merged_cache.db")
                                if _merge_engine_cache_dbs(local_cache_db, ext_db, merged_db):
                                    ext_db = merged_db
                            tmp_dst = _unique_tmp_path(local_cache_db)
                            shutil.copy2(ext_db, tmp_dst)
                            try:
                                _safe_replace(tmp_dst, local_cache_db)
                                local_state["engine_cache_sha256"] = cloud_sha
                                summary["synced_extras"].append("engine_cache:pulled")
                            except PermissionError:
                                if os.path.exists(tmp_dst):
                                    os.remove(tmp_dst)
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        # Push local cache if present and changed
        if direction in ("both", "push") and os.path.exists(local_cache_db):
            try:
                st = os.stat(local_cache_db)
                cur_fp = f"{st.st_size}:{st.st_mtime_ns}"
            except OSError:
                cur_fp = ""
            if cur_fp and (
                local_state.get("engine_cache_local_fp") != cur_fp
                or not os.path.isfile(cloud_zip_path)
                or local_state.get("engine_cache_sha256") != cloud_sha
            ):
                tmp_dir = tempfile.mkdtemp(prefix="fenix_ecache_push_")
                try:
                    clean_db = os.path.join(tmp_dir, "engine_eval_cache.db")
                    if create_verified_db_snapshot(local_cache_db, clean_db):
                        db_sha = _sha256_file(clean_db)
                        if db_sha != cloud_sha or not os.path.isfile(cloud_zip_path):
                            tmp_zip = _unique_tmp_path(cloud_zip_path)
                            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                                zf.write(clean_db, "engine_eval_cache.db")
                            _safe_replace(tmp_zip, cloud_zip_path)
                            manifest["engine_cache"] = {
                                "sha256": db_sha,
                                "db_sha256": db_sha,
                                "size_bytes": os.path.getsize(cloud_zip_path),
                                "updated_at": _now_iso(),
                                "updated_by": get_device_name(),
                            }
                            summary["synced_extras"].append("engine_cache:pushed")
                            manifest_dirty = True
                        local_state["engine_cache_sha256"] = db_sha
                        local_state["engine_cache_local_fp"] = cur_fp
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        return manifest_dirty

    # ─── Automatic Stepover / Legacy Migration ──────────────────────────────

    @staticmethod
    def _migrate_legacy_cloud_data_if_needed(
        cloud_dir: str,
        local_dir: str,
        manifest: dict,
        local_state: dict,
    ) -> Tuple[List[str], List[str]]:
        """
        Seamless stepover from legacy raw-files-in-cloud-folder setup:
        1. Copies config.json from cloud_dir to local_dir if missing locally.
        2. Any repertoire in cloud_dir/repertoires/<name> not yet tracked in sync_manifest.json
           (and not deleted) is verified (or auto-healed from backups/), copied to local_dir,
           and packaged into cloud_sync/repertoires/<name>.fenixsync.zip.
        3. Any profile in cloud_dir/profiles/<name>.db not yet tracked in sync_manifest.json
           is verified, copied to local_dir, and packaged into cloud_sync/profiles/<name>.fenixsync.zip.
        """
        migrated_repos: List[str] = []
        migrated_profs: List[str] = []
        cloud_sync_root = CloudSyncService.get_cloud_sync_root(cloud_dir)
        if not cloud_sync_root:
            return migrated_repos, migrated_profs

        # 1. Seed config.json from cloud_dir if local_workspace doesn't have one yet
        cloud_cfg = os.path.join(cloud_dir, "config.json")
        local_cfg = os.path.join(local_dir, "config.json")
        if os.path.exists(cloud_cfg) and not os.path.exists(local_cfg):
            try:
                os.makedirs(local_dir, exist_ok=True)
                shutil.copy2(cloud_cfg, local_cfg)
            except Exception as e:
                logger.warning(f"CloudSync stepover: Could not copy config.json: {e}")

        # 2. Import legacy repertoires from cloud_dir/repertoires
        cloud_repos_dir = os.path.join(cloud_dir, "repertoires")
        local_repos_dir = os.path.join(local_dir, "repertoires")
        os.makedirs(local_repos_dir, exist_ok=True)

        if os.path.exists(cloud_repos_dir) and os.path.isdir(cloud_repos_dir):
            for repo_name in sorted(os.listdir(cloud_repos_dir)):
                c_repo_path = os.path.join(cloud_repos_dir, repo_name)
                if not os.path.isdir(c_repo_path):
                    continue
                if repo_name in manifest.get("repertoires", {}) or repo_name in manifest.get("deleted_repertoires", {}):
                    continue

                c_db_path = os.path.join(c_repo_path, f"{repo_name}.db")
                if not os.path.exists(c_db_path):
                    continue

                l_repo_path = os.path.join(local_repos_dir, repo_name)
                l_db_path = os.path.join(l_repo_path, f"{repo_name}.db")
                os.makedirs(l_repo_path, exist_ok=True)

                db_ok = False
                if os.path.exists(l_db_path) and verify_sqlite_db(l_db_path):
                    db_ok = True
                elif create_verified_db_snapshot(c_db_path, l_db_path):
                    db_ok = True
                elif CloudSyncService._recover_db_from_backups(cloud_dir, repo_name, l_db_path):
                    db_ok = True

                if not db_ok:
                    logger.warning(
                        f"CloudSync stepover: Skipping legacy repertoire '{repo_name}' because DB is malformed and no healthy backup was found."
                    )
                    continue

                for root, _, files in os.walk(c_repo_path):
                    rel_root = os.path.relpath(root, c_repo_path)
                    target_root = l_repo_path if rel_root == "." else os.path.join(l_repo_path, rel_root)
                    os.makedirs(target_root, exist_ok=True)
                    for fname in files:
                        if _is_ignored_repo_file(fname):
                            continue
                        if fname.lower().endswith(".db") and rel_root == ".":
                            continue
                        src_f = os.path.join(root, fname)
                        dst_f = os.path.join(target_root, fname)
                        if not os.path.exists(dst_f):
                            try:
                                shutil.copy2(src_f, dst_f)
                            except Exception:
                                pass

                entry = CloudSyncService._package_repertoire_to_cloud(l_repo_path, repo_name, cloud_sync_root)
                if entry and not entry.get("unchanged"):
                    manifest.setdefault("repertoires", {})[repo_name] = entry
                    local_state.setdefault("repertoires", {})[repo_name] = {
                        "synced_snapshot_sha256": entry["sha256"],
                        "local_fingerprint": _compute_repo_local_fingerprint(l_repo_path, repo_name),
                        "synced_at": entry["updated_at"],
                    }
                    migrated_repos.append(repo_name)

        # 3. Import legacy profiles from cloud_dir/profiles
        cloud_profs_dir = os.path.join(cloud_dir, "profiles")
        local_profs_dir = os.path.join(local_dir, "profiles")
        os.makedirs(local_profs_dir, exist_ok=True)

        if os.path.exists(cloud_profs_dir) and os.path.isdir(cloud_profs_dir):
            for fname in sorted(os.listdir(cloud_profs_dir)):
                if not fname.lower().endswith(".db"):
                    continue
                prof_name = os.path.splitext(fname)[0]
                if prof_name in manifest.get("profiles", {}) or prof_name in manifest.get("deleted_profiles", {}):
                    continue

                c_db_path = os.path.join(cloud_profs_dir, fname)
                l_db_path = os.path.join(local_profs_dir, fname)

                db_ok = False
                if os.path.exists(l_db_path) and verify_sqlite_db(l_db_path):
                    db_ok = True
                elif create_verified_db_snapshot(c_db_path, l_db_path):
                    db_ok = True

                if not db_ok:
                    logger.warning(f"CloudSync stepover: Skipping legacy profile '{prof_name}' (malformed DB).")
                    continue

                c_settings = os.path.join(cloud_profs_dir, f"{prof_name}_settings.json")
                l_settings = os.path.join(local_profs_dir, f"{prof_name}_settings.json")
                if os.path.exists(c_settings) and not os.path.exists(l_settings):
                    try:
                        shutil.copy2(c_settings, l_settings)
                    except Exception:
                        pass

                entry = CloudSyncService._package_profile_to_cloud(local_profs_dir, prof_name, cloud_sync_root)
                if entry and not entry.get("unchanged"):
                    manifest.setdefault("profiles", {})[prof_name] = entry
                    local_state.setdefault("profiles", {})[prof_name] = {
                        "synced_snapshot_sha256": entry["sha256"],
                        "local_fingerprint": _compute_profile_local_fingerprint(local_profs_dir, prof_name),
                        "synced_at": entry["updated_at"],
                    }
                    migrated_profs.append(prof_name)

        local_state["legacy_migration_done"] = True
        return migrated_repos, migrated_profs

    # ─── Main Bidirectional Sync Entry Point ────────────────────────────────

    @staticmethod
    def sync_now(
        direction: str = "both",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronizes the local workspace with the cloud sync folder.
        Thread-safe (guarded by _SYNC_LOCK).
        direction: "both" (default), "pull" (cloud -> local), or "push" (local -> cloud).
        """
        with _SYNC_LOCK:
            configured = CloudSyncService.is_configured()
            offline = CloudSyncService.is_offline()
            enabled = CloudSyncService.is_enabled()
            cloud_dir = CloudSyncService.get_cloud_dir()
            local_dir = get_local_workspace_dir()

            summary: Dict[str, Any] = {
                "configured": configured,
                "offline": offline,
                "enabled": enabled,
                "cloud_dir": cloud_dir or CloudSyncService.get_configured_cloud_dir(),
                "local_dir": local_dir,
                "pulled_repertoires": [],
                "pushed_repertoires": [],
                "deleted_local_repertoires": [],
                "deleted_cloud_repertoires": [],
                "pulled_profiles": [],
                "pushed_profiles": [],
                "merged_profiles": [],
                "deleted_local_profiles": [],
                "deleted_cloud_profiles": [],
                "migrated_repertoires": [],
                "migrated_profiles": [],
                "conflicts_backed_up": [],
                "conflicts": [],
                "pending_downloads": [],
                "provider_conflict_files": [],
                "synced_extras": [],
                "errors": [],
                "last_sync_at": None,
                "last_sync_device": None,
            }

            if not enabled or not cloud_dir:
                return summary

            cloud_sync_root = CloudSyncService.get_cloud_sync_root(cloud_dir)
            if not cloud_sync_root:
                return summary

            def _report(msg: str, cur: int, tot: int):
                if progress_callback:
                    try:
                        progress_callback(msg, cur, tot)
                    except Exception:
                        pass

            os.makedirs(os.path.join(local_dir, "repertoires"), exist_ok=True)
            os.makedirs(os.path.join(local_dir, "profiles"), exist_ok=True)
            os.makedirs(os.path.join(cloud_dir, "backups"), exist_ok=True)

            manifest = CloudSyncService.load_manifest(cloud_dir)
            local_state = CloudSyncService.load_local_state(local_dir, cloud_dir)
            sync_opts = CloudSyncService.get_sync_options()
            excluded_repos = set(sync_opts.get("excluded_repertoires", []))
            manifest_dirty = False

            # Check for cloud provider conflict copies (Google Drive / OneDrive)
            summary["provider_conflict_files"] = CloudSyncService.detect_provider_conflict_files(cloud_dir)

            # 0. One-time automatic stepover from legacy raw folders in Google Drive
            _report("Checking cloud folder...", 0, 100)
            mig_repos, mig_profs = CloudSyncService._migrate_legacy_cloud_data_if_needed(
                cloud_dir, local_dir, manifest, local_state
            )
            if mig_repos or mig_profs:
                summary["migrated_repertoires"].extend(mig_repos)
                summary["migrated_profiles"].extend(mig_profs)
                manifest_dirty = True

            local_repos_dir = os.path.join(local_dir, "repertoires")
            local_profs_dir = os.path.join(local_dir, "profiles")

            # Compute rough total work items for progress reporting
            total_steps = (
                len(manifest.get("repertoires", {}))
                + len(manifest.get("profiles", {}))
                + (len(os.listdir(local_repos_dir)) if os.path.isdir(local_repos_dir) else 0)
                + (len(os.listdir(local_profs_dir)) if os.path.isdir(local_profs_dir) else 0)
                + 3
            )
            step_idx = 0

            # 1. PULL phase (Cloud -> Local)
            if direction in ("both", "pull"):
                # 1a. Propagate repertoire deletions from cloud -> local
                for del_repo in list(manifest.get("deleted_repertoires", {}).keys()):
                    if del_repo in excluded_repos:
                        continue
                    l_repo_path = os.path.join(local_repos_dir, del_repo)
                    if del_repo in local_state.get("repertoires", {}):
                        if os.path.exists(l_repo_path):
                            cur_fp = _compute_repo_local_fingerprint(l_repo_path, del_repo)
                            prev_fp = local_state["repertoires"][del_repo].get("local_fingerprint")
                            if cur_fp == prev_fp:
                                shutil.rmtree(l_repo_path, ignore_errors=True)
                                summary["deleted_local_repertoires"].append(del_repo)
                        local_state["repertoires"].pop(del_repo, None)

                # 1b. Propagate profile deletions from cloud -> local
                for del_prof in list(manifest.get("deleted_profiles", {}).keys()):
                    l_db_path = os.path.join(local_profs_dir, f"{del_prof}.db")
                    l_set_path = os.path.join(local_profs_dir, f"{del_prof}_settings.json")
                    if del_prof in local_state.get("profiles", {}):
                        if os.path.exists(l_db_path):
                            cur_fp = _compute_profile_local_fingerprint(local_profs_dir, del_prof)
                            prev_fp = local_state["profiles"][del_prof].get("local_fingerprint")
                            if cur_fp == prev_fp:
                                for p_rm in (
                                    l_db_path,
                                    l_db_path + "-wal",
                                    l_db_path + "-shm",
                                    l_db_path + "-journal",
                                    l_set_path,
                                ):
                                    if os.path.exists(p_rm):
                                        try:
                                            os.remove(p_rm)
                                        except Exception:
                                            pass
                                summary["deleted_local_profiles"].append(del_prof)
                        local_state["profiles"].pop(del_prof, None)

                # 1c. Pull updated/new repertoires
                for repo_name, entry in list(manifest.get("repertoires", {}).items()):
                    step_idx += 1
                    if repo_name in excluded_repos:
                        continue
                    cloud_sha = entry.get("sha256")
                    if not cloud_sha:
                        continue
                    l_repo_path = os.path.join(local_repos_dir, repo_name)
                    l_db_path = os.path.join(l_repo_path, f"{repo_name}.db")
                    l_info = local_state.get("repertoires", {}).get(repo_name)

                    local_exists_and_valid = os.path.exists(l_db_path) and verify_sqlite_db(l_db_path)
                    cloud_changed = (l_info is None) or (l_info.get("synced_snapshot_sha256") != cloud_sha)

                    if not local_exists_and_valid or cloud_changed:
                        _report(f"Pulling repertoire: {repo_name}", step_idx, max(total_steps, step_idx))
                        is_conflict = False
                        conflict_backup_path = None
                        if local_exists_and_valid and l_info is not None:
                            cur_fp = _compute_repo_local_fingerprint(l_repo_path, repo_name)
                            if cur_fp != l_info.get("local_fingerprint"):
                                is_conflict = True
                                try:
                                    from opening_fenix.core.services.backup_service import create_repertoire_backup
                                    conflict_backup_path = create_repertoire_backup(
                                        repo_name, trigger_type="sync_conflict"
                                    )
                                    summary["conflicts_backed_up"].append(repo_name)
                                except Exception as bk_e:
                                    logger.warning(f"CloudSync: Could not create conflict backup for '{repo_name}': {bk_e}")

                        ok, reason = CloudSyncService._extract_repertoire_from_cloud(
                            cloud_sync_root, repo_name, entry, l_repo_path
                        )
                        if ok:
                            local_state.setdefault("repertoires", {})[repo_name] = {
                                "synced_snapshot_sha256": cloud_sha,
                                "local_fingerprint": _compute_repo_local_fingerprint(l_repo_path, repo_name),
                                "synced_at": _now_iso(),
                            }
                            summary["pulled_repertoires"].append(repo_name)
                            if is_conflict:
                                summary["conflicts"].append({
                                    "kind": "repertoire",
                                    "name": repo_name,
                                    "backup_path": conflict_backup_path,
                                    "cloud_updated_by": entry.get("updated_by"),
                                    "cloud_updated_at": entry.get("updated_at"),
                                    "resolution": "cloud_won_backup_created",
                                })
                        elif reason == "pending_cloud_download":
                            summary["pending_downloads"].append(f"repertoire:{repo_name}")
                            summary["errors"].append(
                                f"Cloud snapshot for repertoire '{repo_name}' is still downloading; skipped for safety."
                            )
                        elif reason == "file_locked":
                            summary["errors"].append(
                                f"Repertoire '{repo_name}' is currently open in this session; restart or close it to apply the cloud update."
                            )
                        else:
                            summary["errors"].append(f"Failed to pull repertoire '{repo_name}' ({reason})")

                # 1d. Pull updated/new profiles (with backup + lossless SQLite merge on conflict!)
                for prof_name, entry in list(manifest.get("profiles", {}).items()):
                    step_idx += 1
                    cloud_sha = entry.get("sha256")
                    if not cloud_sha:
                        continue
                    l_db_path = os.path.join(local_profs_dir, f"{prof_name}.db")
                    l_info = local_state.get("profiles", {}).get(prof_name)

                    local_exists_and_valid = os.path.exists(l_db_path) and verify_sqlite_db(l_db_path)
                    cloud_changed = (l_info is None) or (l_info.get("synced_snapshot_sha256") != cloud_sha)

                    if not local_exists_and_valid or cloud_changed:
                        _report(f"Pulling profile: {prof_name}", step_idx, max(total_steps, step_idx))
                        is_prof_conflict = False
                        prof_bk_path = None
                        if local_exists_and_valid and l_info is not None:
                            cur_fp = _compute_profile_local_fingerprint(local_profs_dir, prof_name)
                            if cur_fp != l_info.get("local_fingerprint"):
                                is_prof_conflict = True
                                prof_bk_path = CloudSyncService.create_profile_backup(
                                    prof_name, trigger_type="sync_conflict", local_profiles_dir=local_profs_dir
                                )
                        elif local_exists_and_valid and l_info is None:
                            # Both devices already had a profile with the same name -> smart merge!
                            is_prof_conflict = True
                            prof_bk_path = CloudSyncService.create_profile_backup(
                                prof_name, trigger_type="sync_conflict", local_profiles_dir=local_profs_dir
                            )

                        ok, reason, was_merged = CloudSyncService._extract_profile_from_cloud(
                            cloud_sync_root,
                            prof_name,
                            entry,
                            local_profs_dir,
                            merge_with_local=is_prof_conflict,
                        )
                        if ok:
                            if was_merged:
                                # Keep local_fingerprint invalidated so push phase uploads the merged DB
                                local_state.setdefault("profiles", {})[prof_name] = {
                                    "synced_snapshot_sha256": cloud_sha,
                                    "local_fingerprint": "",
                                    "synced_at": _now_iso(),
                                }
                                summary["merged_profiles"].append(prof_name)
                                summary["conflicts"].append({
                                    "kind": "profile",
                                    "name": prof_name,
                                    "backup_path": prof_bk_path,
                                    "cloud_updated_by": entry.get("updated_by"),
                                    "cloud_updated_at": entry.get("updated_at"),
                                    "resolution": "auto_merged",
                                })
                            else:
                                local_state.setdefault("profiles", {})[prof_name] = {
                                    "synced_snapshot_sha256": cloud_sha,
                                    "local_fingerprint": _compute_profile_local_fingerprint(local_profs_dir, prof_name),
                                    "synced_at": _now_iso(),
                                }
                            summary["pulled_profiles"].append(prof_name)
                        elif reason == "pending_cloud_download":
                            summary["pending_downloads"].append(f"profile:{prof_name}")
                            summary["errors"].append(
                                f"Cloud snapshot for profile '{prof_name}' is still downloading; skipped for safety."
                            )
                        elif reason == "file_locked":
                            summary["errors"].append(
                                f"Profile '{prof_name}' is currently open; restart to apply the cloud update."
                            )
                        else:
                            summary["errors"].append(f"Failed to pull profile '{prof_name}' ({reason})")

            # 2. PUSH phase (Local -> Cloud)
            if direction in ("both", "push"):
                # 2a. Detect local repertoire deletions
                for tracked_repo in list(local_state.get("repertoires", {}).keys()):
                    if tracked_repo in excluded_repos:
                        continue
                    l_repo_path = os.path.join(local_repos_dir, tracked_repo)
                    l_db_path = os.path.join(l_repo_path, f"{tracked_repo}.db")
                    if not os.path.exists(l_db_path):
                        local_state["repertoires"].pop(tracked_repo, None)
                        if tracked_repo in manifest.get("repertoires", {}):
                            manifest["repertoires"].pop(tracked_repo, None)
                            manifest.setdefault("deleted_repertoires", {})[tracked_repo] = {
                                "deleted_at": _now_iso(),
                                "deleted_by": get_device_name(),
                            }
                            snap_zip = os.path.join(cloud_sync_root, "repertoires", f"{tracked_repo}.fenixsync.zip")
                            if os.path.exists(snap_zip):
                                try:
                                    os.remove(snap_zip)
                                except Exception:
                                    pass
                            summary["deleted_cloud_repertoires"].append(tracked_repo)
                            manifest_dirty = True

                # 2b. Detect local profile deletions
                for tracked_prof in list(local_state.get("profiles", {}).keys()):
                    l_db_path = os.path.join(local_profs_dir, f"{tracked_prof}.db")
                    if not os.path.exists(l_db_path):
                        local_state["profiles"].pop(tracked_prof, None)
                        if tracked_prof in manifest.get("profiles", {}):
                            manifest["profiles"].pop(tracked_prof, None)
                            manifest.setdefault("deleted_profiles", {})[tracked_prof] = {
                                "deleted_at": _now_iso(),
                                "deleted_by": get_device_name(),
                            }
                            snap_zip = os.path.join(cloud_sync_root, "profiles", f"{tracked_prof}.fenixsync.zip")
                            if os.path.exists(snap_zip):
                                try:
                                    os.remove(snap_zip)
                                except Exception:
                                    pass
                            summary["deleted_cloud_profiles"].append(tracked_prof)
                            manifest_dirty = True

                # 2c. Push modified or new local repertoires
                if os.path.exists(local_repos_dir):
                    for repo_name in sorted(os.listdir(local_repos_dir)):
                        step_idx += 1
                        if repo_name in excluded_repos:
                            continue
                        l_repo_path = os.path.join(local_repos_dir, repo_name)
                        l_db_path = os.path.join(l_repo_path, f"{repo_name}.db")
                        if not os.path.isdir(l_repo_path) or not os.path.exists(l_db_path):
                            continue

                        cur_fp = _compute_repo_local_fingerprint(l_repo_path, repo_name)
                        l_info = local_state.get("repertoires", {}).get(repo_name)
                        m_entry = manifest.get("repertoires", {}).get(repo_name)
                        snap_zip = os.path.join(cloud_sync_root, "repertoires", f"{repo_name}.fenixsync.zip")

                        if (
                            l_info is not None
                            and m_entry is not None
                            and os.path.exists(snap_zip)
                            and l_info.get("local_fingerprint") == cur_fp
                            and l_info.get("synced_snapshot_sha256") == m_entry.get("sha256")
                        ):
                            continue

                        # Skip pushing if we skipped pulling due to pending cloud download
                        if f"repertoire:{repo_name}" in summary["pending_downloads"]:
                            continue

                        _report(f"Checking/pushing repertoire: {repo_name}", step_idx, max(total_steps, step_idx))
                        existing_sha = m_entry.get("sha256") if m_entry else None
                        new_entry = CloudSyncService._package_repertoire_to_cloud(
                            l_repo_path, repo_name, cloud_sync_root, existing_sha=existing_sha
                        )
                        if new_entry is None:
                            summary["errors"].append(f"Integrity check failed for local repertoire '{repo_name}'")
                            continue

                        if new_entry.get("unchanged"):
                            # Content didn't actually change (only mtime/WAL touched); refresh fingerprint only!
                            local_state.setdefault("repertoires", {})[repo_name] = {
                                "synced_snapshot_sha256": new_entry["sha256"],
                                "local_fingerprint": _compute_repo_local_fingerprint(l_repo_path, repo_name),
                                "synced_at": (l_info or {}).get("synced_at") or _now_iso(),
                            }
                            continue

                        manifest.setdefault("repertoires", {})[repo_name] = new_entry
                        manifest.get("deleted_repertoires", {}).pop(repo_name, None)
                        local_state.setdefault("repertoires", {})[repo_name] = {
                            "synced_snapshot_sha256": new_entry["sha256"],
                            "local_fingerprint": _compute_repo_local_fingerprint(l_repo_path, repo_name),
                            "synced_at": new_entry["updated_at"],
                        }
                        if m_entry is None or m_entry.get("sha256") != new_entry["sha256"]:
                            summary["pushed_repertoires"].append(repo_name)
                        manifest_dirty = True

                # 2d. Push modified or new local profiles
                if os.path.exists(local_profs_dir):
                    for fname in sorted(os.listdir(local_profs_dir)):
                        if not fname.lower().endswith(".db"):
                            continue
                        step_idx += 1
                        prof_name = os.path.splitext(fname)[0]
                        cur_fp = _compute_profile_local_fingerprint(local_profs_dir, prof_name)
                        l_info = local_state.get("profiles", {}).get(prof_name)
                        m_entry = manifest.get("profiles", {}).get(prof_name)
                        snap_zip = os.path.join(cloud_sync_root, "profiles", f"{prof_name}.fenixsync.zip")

                        if (
                            l_info is not None
                            and m_entry is not None
                            and os.path.exists(snap_zip)
                            and l_info.get("local_fingerprint") == cur_fp
                            and l_info.get("synced_snapshot_sha256") == m_entry.get("sha256")
                        ):
                            continue

                        if f"profile:{prof_name}" in summary["pending_downloads"]:
                            continue

                        _report(f"Checking/pushing profile: {prof_name}", step_idx, max(total_steps, step_idx))
                        existing_sha = m_entry.get("sha256") if m_entry else None
                        new_entry = CloudSyncService._package_profile_to_cloud(
                            local_profs_dir, prof_name, cloud_sync_root, existing_sha=existing_sha
                        )
                        if new_entry is None:
                            summary["errors"].append(f"Integrity check failed for local profile '{prof_name}'")
                            continue

                        if new_entry.get("unchanged"):
                            local_state.setdefault("profiles", {})[prof_name] = {
                                "synced_snapshot_sha256": new_entry["sha256"],
                                "local_fingerprint": _compute_profile_local_fingerprint(local_profs_dir, prof_name),
                                "synced_at": (l_info or {}).get("synced_at") or _now_iso(),
                            }
                            continue

                        manifest.setdefault("profiles", {})[prof_name] = new_entry
                        manifest.get("deleted_profiles", {}).pop(prof_name, None)
                        local_state.setdefault("profiles", {})[prof_name] = {
                            "synced_snapshot_sha256": new_entry["sha256"],
                            "local_fingerprint": _compute_profile_local_fingerprint(local_profs_dir, prof_name),
                            "synced_at": new_entry["updated_at"],
                        }
                        if m_entry is None or m_entry.get("sha256") != new_entry["sha256"]:
                            summary["pushed_profiles"].append(prof_name)
                        manifest_dirty = True

            # 3. Sync extra portable data (settings, custom dictionary, opt-in engine cache)
            _report("Syncing preferences & extras...", total_steps - 1, max(total_steps, 1))
            if sync_opts.get("sync_portable_settings", True):
                try:
                    if CloudSyncService._sync_portable_settings(
                        cloud_sync_root, local_dir, manifest, local_state, direction, summary
                    ):
                        manifest_dirty = True
                except Exception as e:
                    logger.warning(f"CloudSync: Portable settings sync warning: {e}")

            if sync_opts.get("sync_user_dictionary", True):
                try:
                    if CloudSyncService._sync_user_dictionary(
                        cloud_sync_root, local_dir, manifest, local_state, direction, summary
                    ):
                        manifest_dirty = True
                except Exception as e:
                    logger.warning(f"CloudSync: User dictionary sync warning: {e}")

            if sync_opts.get("sync_engine_cache", False):
                try:
                    if CloudSyncService._sync_engine_cache(
                        cloud_sync_root, local_dir, manifest, local_state, direction, summary
                    ):
                        manifest_dirty = True
                except Exception as e:
                    logger.warning(f"CloudSync: Engine cache sync warning: {e}")

            # Cache deleted_repertoires locally so offline ensure_user_data_seeded() never resurrects them
            local_state["known_deleted_repertoires"] = sorted(
                set(manifest.get("deleted_repertoires", {}).keys())
            )

            if manifest_dirty or not os.path.exists(CloudSyncService.get_manifest_path(cloud_dir) or ""):
                CloudSyncService.save_manifest(manifest, cloud_dir)

            now_str = _now_iso()
            local_state["last_sync_at"] = now_str
            local_state["last_sync_device"] = manifest.get("updated_by_device") or get_device_name()
            CloudSyncService.save_local_state(local_state, local_dir)

            summary["last_sync_at"] = local_state["last_sync_at"]
            summary["last_sync_device"] = local_state["last_sync_device"]
            _report("Synchronization complete.", max(total_steps, 1), max(total_steps, 1))
            return summary

    # ─── Single-Item Force Actions & Conflict Backup Restore ────────────────

    @staticmethod
    def force_push_item(kind: str, name: str) -> Tuple[bool, str]:
        """Forces uploading a specific repertoire or profile from local to cloud."""
        with _SYNC_LOCK:
            cloud_dir = CloudSyncService.get_cloud_dir()
            if not cloud_dir:
                return False, "Cloud sync is not available or offline."
            cloud_sync_root = CloudSyncService.get_cloud_sync_root(cloud_dir)
            local_dir = get_local_workspace_dir()
            manifest = CloudSyncService.load_manifest(cloud_dir)
            local_state = CloudSyncService.load_local_state(local_dir, cloud_dir)

            if kind == "repertoire":
                l_repo_path = os.path.join(local_dir, "repertoires", name)
                entry = CloudSyncService._package_repertoire_to_cloud(
                    l_repo_path, name, cloud_sync_root, existing_sha=None
                )
                if not entry:
                    return False, f"Local repertoire '{name}' failed integrity check or does not exist."
                manifest.setdefault("repertoires", {})[name] = entry
                manifest.get("deleted_repertoires", {}).pop(name, None)
                local_state.setdefault("repertoires", {})[name] = {
                    "synced_snapshot_sha256": entry["sha256"],
                    "local_fingerprint": _compute_repo_local_fingerprint(l_repo_path, name),
                    "synced_at": entry["updated_at"],
                }
            elif kind == "profile":
                l_profs_dir = os.path.join(local_dir, "profiles")
                entry = CloudSyncService._package_profile_to_cloud(
                    l_profs_dir, name, cloud_sync_root, existing_sha=None
                )
                if not entry:
                    return False, f"Local profile '{name}' failed integrity check or does not exist."
                manifest.setdefault("profiles", {})[name] = entry
                manifest.get("deleted_profiles", {}).pop(name, None)
                local_state.setdefault("profiles", {})[name] = {
                    "synced_snapshot_sha256": entry["sha256"],
                    "local_fingerprint": _compute_profile_local_fingerprint(l_profs_dir, name),
                    "synced_at": entry["updated_at"],
                }
            else:
                return False, f"Unknown item kind: {kind}"

            CloudSyncService.save_manifest(manifest, cloud_dir)
            local_state["last_sync_at"] = _now_iso()
            local_state["last_sync_device"] = get_device_name()
            CloudSyncService.save_local_state(local_state, local_dir)
            return True, "ok"

    @staticmethod
    def force_pull_item(kind: str, name: str) -> Tuple[bool, str]:
        """Forces downloading a specific repertoire or profile from cloud to local (backing up local first)."""
        with _SYNC_LOCK:
            cloud_dir = CloudSyncService.get_cloud_dir()
            if not cloud_dir:
                return False, "Cloud sync is not available or offline."
            cloud_sync_root = CloudSyncService.get_cloud_sync_root(cloud_dir)
            local_dir = get_local_workspace_dir()
            manifest = CloudSyncService.load_manifest(cloud_dir)
            local_state = CloudSyncService.load_local_state(local_dir, cloud_dir)

            if kind == "repertoire":
                entry = manifest.get("repertoires", {}).get(name)
                if not entry:
                    return False, f"Repertoire '{name}' not found in cloud manifest."
                l_repo_path = os.path.join(local_dir, "repertoires", name)
                if os.path.exists(os.path.join(l_repo_path, f"{name}.db")):
                    try:
                        from opening_fenix.core.services.backup_service import create_repertoire_backup
                        create_repertoire_backup(name, trigger_type="pre_force_pull")
                    except Exception:
                        pass
                ok, reason = CloudSyncService._extract_repertoire_from_cloud(
                    cloud_sync_root, name, entry, l_repo_path
                )
                if not ok:
                    return False, reason
                local_state.setdefault("repertoires", {})[name] = {
                    "synced_snapshot_sha256": entry["sha256"],
                    "local_fingerprint": _compute_repo_local_fingerprint(l_repo_path, name),
                    "synced_at": _now_iso(),
                }
            elif kind == "profile":
                entry = manifest.get("profiles", {}).get(name)
                if not entry:
                    return False, f"Profile '{name}' not found in cloud manifest."
                l_profs_dir = os.path.join(local_dir, "profiles")
                CloudSyncService.create_profile_backup(name, trigger_type="pre_force_pull", local_profiles_dir=l_profs_dir)
                ok, reason, _ = CloudSyncService._extract_profile_from_cloud(
                    cloud_sync_root, name, entry, l_profs_dir, merge_with_local=False
                )
                if not ok:
                    return False, reason
                local_state.setdefault("profiles", {})[name] = {
                    "synced_snapshot_sha256": entry["sha256"],
                    "local_fingerprint": _compute_profile_local_fingerprint(l_profs_dir, name),
                    "synced_at": _now_iso(),
                }
            else:
                return False, f"Unknown item kind: {kind}"

            local_state["last_sync_at"] = _now_iso()
            CloudSyncService.save_local_state(local_state, local_dir)
            return True, "ok"

    @staticmethod
    def restore_repertoire_conflict_backup(repo_name: str, backup_zip_path: str) -> Tuple[bool, str]:
        """Restores a local sync_conflict backup zip and pushes it to the cloud as the winning version."""
        if not backup_zip_path or not os.path.isfile(backup_zip_path):
            return False, "Conflict backup file not found."
        try:
            from opening_fenix.core.services.backup_service import restore_repertoire_from_backup
            ok = restore_repertoire_from_backup(repo_name, backup_zip_path)
            if not ok:
                return False, f"Failed to restore backup for '{repo_name}'."
            if CloudSyncService.is_enabled():
                return CloudSyncService.force_push_item("repertoire", repo_name)
            return True, "Restored locally (cloud offline)."
        except Exception as e:
            return False, str(e)

    # ─── Status & Detailed Inspector APIs ───────────────────────────────────

    @staticmethod
    def get_sync_status() -> Dict[str, Any]:
        """Returns current cloud sync configuration and status for UI banners & status pills."""
        configured = CloudSyncService.is_configured()
        offline = CloudSyncService.is_offline()
        enabled = CloudSyncService.is_enabled()
        cloud_dir = CloudSyncService.get_cloud_dir()
        configured_dir = CloudSyncService.get_configured_cloud_dir()
        local_dir = get_local_workspace_dir()

        if not configured:
            return {
                "configured": False,
                "offline": False,
                "enabled": False,
                "cloud_dir": None,
                "local_dir": get_default_user_dir(),
                "last_sync_at": None,
                "last_sync_device": None,
                "other_active_session": None,
                "repertoire_count": 0,
                "profile_count": 0,
                "provider_conflict_files": [],
            }

        local_state = CloudSyncService.load_local_state(local_dir, configured_dir)
        if offline or not enabled or not cloud_dir:
            return {
                "configured": True,
                "offline": True,
                "enabled": False,
                "cloud_dir": configured_dir,
                "local_dir": local_dir,
                "last_sync_at": local_state.get("last_sync_at"),
                "last_sync_device": local_state.get("last_sync_device"),
                "other_active_session": None,
                "repertoire_count": len(local_state.get("repertoires", {})),
                "profile_count": len(local_state.get("profiles", {})),
                "provider_conflict_files": [],
            }

        manifest = CloudSyncService.load_manifest(cloud_dir)
        other_session = CloudSyncService.check_other_active_session(cloud_dir)
        conflict_files = CloudSyncService.detect_provider_conflict_files(cloud_dir)
        return {
            "configured": True,
            "offline": False,
            "enabled": True,
            "cloud_dir": cloud_dir,
            "local_dir": local_dir,
            "last_sync_at": local_state.get("last_sync_at") or manifest.get("updated_at"),
            "last_sync_device": manifest.get("updated_by_device") or local_state.get("last_sync_device"),
            "other_active_session": other_session,
            "repertoire_count": len(manifest.get("repertoires", {})),
            "profile_count": len(manifest.get("profiles", {})),
            "provider_conflict_files": conflict_files,
        }

    @staticmethod
    def get_detailed_items_status() -> List[Dict[str, Any]]:
        """
        Returns per-item sync diagnostics for all repertoires and profiles
        (for the Settings Sync Inspector table).
        """
        items: List[Dict[str, Any]] = []
        configured = CloudSyncService.is_configured()
        offline = CloudSyncService.is_offline()
        cloud_dir = CloudSyncService.get_cloud_dir()
        local_dir = get_local_workspace_dir()
        excluded_repos = set(CloudSyncService.get_excluded_repertoires())

        local_state = CloudSyncService.load_local_state(local_dir, cloud_dir or CloudSyncService.get_configured_cloud_dir())
        manifest = CloudSyncService.load_manifest(cloud_dir) if (cloud_dir and not offline) else {"repertoires": {}, "profiles": {}}

        local_repos_dir = os.path.join(local_dir, "repertoires")
        local_profs_dir = os.path.join(local_dir, "profiles")

        local_repos = set()
        if os.path.isdir(local_repos_dir):
            for name in os.listdir(local_repos_dir):
                if os.path.isfile(os.path.join(local_repos_dir, name, f"{name}.db")):
                    local_repos.add(name)

        cloud_repos = set((manifest.get("repertoires") or {}).keys())
        for name in sorted(local_repos | cloud_repos):
            l_exists = name in local_repos
            c_entry = (manifest.get("repertoires") or {}).get(name)
            c_exists = c_entry is not None
            l_info = (local_state.get("repertoires") or {}).get(name)
            is_excl = name in excluded_repos

            size_bytes = 0
            if c_entry and c_entry.get("size_bytes"):
                size_bytes = int(c_entry["size_bytes"])
            elif l_exists:
                try:
                    size_bytes = os.path.getsize(os.path.join(local_repos_dir, name, f"{name}.db"))
                except OSError:
                    pass

            if is_excl:
                state = "excluded"
            elif not configured:
                state = "local_only"
            elif offline:
                state = "offline"
            elif l_exists and not c_exists:
                state = "local_only"
            elif c_exists and not l_exists:
                state = "cloud_only"
            else:
                cur_fp = _compute_repo_local_fingerprint(os.path.join(local_repos_dir, name), name)
                local_changed = (l_info is None) or (l_info.get("local_fingerprint") != cur_fp)
                cloud_changed = (l_info is None) or (l_info.get("synced_snapshot_sha256") != c_entry.get("sha256"))
                if local_changed and cloud_changed:
                    state = "conflict"
                elif cloud_changed:
                    state = "cloud_newer"
                elif local_changed:
                    state = "local_changes"
                else:
                    state = "synced"

            items.append({
                "kind": "repertoire",
                "name": name,
                "state": state,
                "local_exists": l_exists,
                "cloud_exists": c_exists,
                "excluded": is_excl,
                "size_bytes": size_bytes,
                "updated_at": (c_entry or {}).get("updated_at") or (l_info or {}).get("synced_at"),
                "updated_by": (c_entry or {}).get("updated_by") or "",
            })

        local_profs = set()
        if os.path.isdir(local_profs_dir):
            for fname in os.listdir(local_profs_dir):
                if fname.lower().endswith(".db"):
                    local_profs.add(os.path.splitext(fname)[0])

        cloud_profs = set((manifest.get("profiles") or {}).keys())
        for name in sorted(local_profs | cloud_profs):
            l_exists = name in local_profs
            c_entry = (manifest.get("profiles") or {}).get(name)
            c_exists = c_entry is not None
            l_info = (local_state.get("profiles") or {}).get(name)

            size_bytes = 0
            if c_entry and c_entry.get("size_bytes"):
                size_bytes = int(c_entry["size_bytes"])
            elif l_exists:
                try:
                    size_bytes = os.path.getsize(os.path.join(local_profs_dir, f"{name}.db"))
                except OSError:
                    pass

            if not configured:
                state = "local_only"
            elif offline:
                state = "offline"
            elif l_exists and not c_exists:
                state = "local_only"
            elif c_exists and not l_exists:
                state = "cloud_only"
            else:
                cur_fp = _compute_profile_local_fingerprint(local_profs_dir, name)
                local_changed = (l_info is None) or (l_info.get("local_fingerprint") != cur_fp)
                cloud_changed = (l_info is None) or (l_info.get("synced_snapshot_sha256") != c_entry.get("sha256"))
                if local_changed and cloud_changed:
                    state = "conflict"
                elif cloud_changed:
                    state = "cloud_newer"
                elif local_changed:
                    state = "local_changes"
                else:
                    state = "synced"

            items.append({
                "kind": "profile",
                "name": name,
                "state": state,
                "local_exists": l_exists,
                "cloud_exists": c_exists,
                "excluded": False,
                "size_bytes": size_bytes,
                "updated_at": (c_entry or {}).get("updated_at") or (l_info or {}).get("synced_at"),
                "updated_by": (c_entry or {}).get("updated_by") or "",
            })

        return items
