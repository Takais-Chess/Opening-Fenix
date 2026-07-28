import os
import io
import json
import sqlite3
import hashlib
import zipfile
import shutil
from datetime import datetime, timedelta, timezone

from opening_fenix.core.data_tools import get_user_dir, get_base_path
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir, get_repertoire_comment_stats, get_multilingual_comment_dict
from opening_fenix.core.logger import logger


def get_backups_base_dir() -> str:
    """Returns the absolute path to the main backups directory."""
    b_dir = os.path.join(get_user_dir(), "backups")
    os.makedirs(b_dir, exist_ok=True)
    return b_dir


def get_repertoire_backup_dir(repo_name: str) -> str:
    """Returns the backup directory for a specific repertoire."""
    r_dir = os.path.join(get_backups_base_dir(), repo_name)
    os.makedirs(r_dir, exist_ok=True)
    return r_dir


def is_resource_pgn_file(file_name: str, repo_name: str = "", is_root: bool = False) -> bool:
    """
    Returns True if a PGN file is a resource asset (Model Games, Typical Motives, Typical Ideas, Tactics, etc.)
    and False if it is a dynamically generated repertoire export file (e.g. <RepoName> L1.pgn).
    """
    fname_lower = file_name.lower()
    if not fname_lower.endswith(".pgn"):
        return False

    # PGNs in subdirectories are always resource PGNs
    if not is_root:
        return True

    # Recognized resource file names in root directory
    resource_keywords = ["model games", "typical motives", "typical ideas", "tactics", "ideas"]
    for kw in resource_keywords:
        if kw in fname_lower:
            return True

    # Generated export check: if it matches/starts with repo_name, skip it
    if repo_name:
        safe_repo = repo_name.lower().replace("_", " ").strip()
        if fname_lower.startswith(safe_repo) or f"{safe_repo}.pgn" in fname_lower:
            return False

    # Default: keep other custom PGN resources
    return True


def compute_repertoire_checksum(repo_name: str) -> str:
    """
    Computes a composite SHA256 hash of the positions data and PGN files
    in the repertoire directory to detect logical repertoire content changes.
    """
    repo_dir = get_repertoire_dir(repo_name)
    db_path = get_repertoire_db_path(repo_name)
    
    hasher = hashlib.sha256()
    
    # 1. Hash positions table logically
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
            if c.fetchone():
                c.execute("SELECT id, comment, level, priority FROM positions ORDER BY id")
                for row in c.fetchall():
                    hasher.update(str(row).encode("utf-8"))
            conn.close()
        except Exception:
            try:
                with open(db_path, "rb") as f:
                    data = f.read()
                    if len(data) > 30:
                        data = data[:24] + b"\x00\x00\x00\x00" + data[28:]
                    hasher.update(data)
            except Exception:
                pass
            
    # 2. Hash all resource PGN files & cover images
    if os.path.exists(repo_dir):
        for root, dirs, files in os.walk(repo_dir):
            is_root = (root == repo_dir)
            for file in sorted(files):
                if is_resource_pgn_file(file, repo_name, is_root) or file.lower().startswith("cover."):
                    fp = os.path.join(root, file)
                    try:
                        hasher.update(file.encode("utf-8"))
                        with open(fp, "rb") as f:
                            for chunk in iter(lambda: f.read(65536), b""):
                                hasher.update(chunk)
                    except Exception:
                        pass

    return hasher.hexdigest()


def get_repertoire_detail_stats(db_path: str, repo_dir: str, zip_path: str = None, repo_name: str = "") -> dict:
    """
    Scans a repertoire DB and directory (or backup .zip) to generate rich backup metadata:
    - EN and DE comment counts
    - List of levels with move counts per level
    - Extra PGN resources (typical ideas, model games, tactics, etc. with filenames)
    """
    en_cnt = 0
    de_cnt = 0
    levels_info = []
    total_moves = 0
    pgn_resources = {}

    temp_db_path = None
    target_db = db_path

    try:
        # If inspecting a backup zip file directly
        if zip_path and os.path.exists(zip_path):
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    # Extract DB to temp file
                    db_members = [m for m in zf.namelist() if m.endswith('.db') and '/' not in m and '\\' not in m]
                    if db_members:
                        import tempfile
                        fd, temp_db_path = tempfile.mkstemp(suffix=".db")
                        os.close(fd)
                        with open(temp_db_path, "wb") as f_out:
                            f_out.write(zf.read(db_members[0]))
                        target_db = temp_db_path

                    # Collect PGN file names from zip
                    category_titles = {
                        "typical_ideas": "Typical Ideas",
                        "typical_motives": "Typical Motives",
                        "model_games": "Model Games",
                        "tactics": "Tactics"
                    }
                    for member in sorted(zf.namelist()):
                        if member.lower().endswith(".pgn"):
                            parts = member.replace("\\", "/").split("/")
                            is_root = (len(parts) == 1)
                            fname = parts[-1]
                            if is_resource_pgn_file(fname, repo_name, is_root):
                                if not is_root:
                                    raw_cat = parts[0]
                                    title = category_titles.get(raw_cat.lower(), raw_cat.replace("_", " ").title())
                                else:
                                    fname_no_ext = os.path.splitext(fname)[0]
                                    title = category_titles.get(fname_no_ext.lower(), fname_no_ext.title())
                                if title not in pgn_resources:
                                    pgn_resources[title] = []
                                pgn_resources[title].append(fname)
            except Exception as e:
                logger.warning(f"Could not inspect zip contents for {zip_path}: {e}")

        # Query database for comments and levels
        if target_db and os.path.exists(target_db):
            try:
                conn = sqlite3.connect(target_db)
                c = conn.cursor()

                # 1. EN and DE comments
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
                if c.fetchone():
                    c.execute("SELECT comment FROM positions WHERE comment IS NOT NULL AND comment != ''")
                    for (raw_c,) in c.fetchall():
                        c_dict = get_multilingual_comment_dict(raw_c)
                        if "en" in c_dict and c_dict["en"]:
                            en_cnt += 1
                        if "de" in c_dict and c_dict["de"]:
                            de_cnt += 1

                # 2. Levels and moves per level
                level_names = {}
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repertoire_levels'")
                if c.fetchone():
                    c.execute('SELECT "order", name FROM repertoire_levels ORDER BY "order"')
                    for order, name in c.fetchall():
                        level_names[order] = name or f"Level {order}"

                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repertoire_moves'")
                if c.fetchone():
                    c.execute("SELECT level, COUNT(*) FROM repertoire_moves GROUP BY level ORDER BY level")
                    for lvl, cnt in c.fetchall():
                        lvl_name = level_names.get(lvl, f"Level {lvl}")
                        levels_info.append({"level": lvl, "name": lvl_name, "moves": cnt})
                        total_moves += cnt
                else:
                    c.execute("SELECT level, COUNT(*) FROM positions GROUP BY level ORDER BY level")
                    for lvl, cnt in c.fetchall():
                        if lvl is not None:
                            lvl_name = level_names.get(lvl, f"Level {lvl}")
                            levels_info.append({"level": lvl, "name": lvl_name, "moves": cnt})
                            total_moves += cnt

                conn.close()
            except Exception as e:
                logger.warning(f"Could not compute DB detail stats for target_db: {e}")

        # If not reading zip and repo_dir exists, scan directory for resource PGNs
        if not zip_path and os.path.exists(repo_dir):
            try:
                category_titles = {
                    "typical_ideas": "Typical Ideas",
                    "typical_motives": "Typical Motives",
                    "model_games": "Model Games",
                    "tactics": "Tactics"
                }
                for root, dirs, files in os.walk(repo_dir):
                    is_root = (root == repo_dir)
                    for file in sorted(files):
                        if is_resource_pgn_file(file, repo_name, is_root):
                            if is_root:
                                fname_no_ext = os.path.splitext(file)[0]
                                title = category_titles.get(fname_no_ext.lower(), fname_no_ext.title())
                            else:
                                sub_name = os.path.basename(root)
                                title = category_titles.get(sub_name.lower(), sub_name.replace("_", " ").title())
                            if title not in pgn_resources:
                                pgn_resources[title] = []
                            pgn_resources[title].append(file)
            except Exception as e:
                logger.warning(f"Could not count PGN resources: {e}")

    finally:
        if temp_db_path and os.path.exists(temp_db_path):
            try: os.remove(temp_db_path)
            except: pass

    return {
        "en_comments": en_cnt,
        "de_comments": de_cnt,
        "levels_info": levels_info,
        "total_moves": total_moves,
        "pgn_resources": pgn_resources
    }


def create_repertoire_backup(repo_name: str, trigger_type: str = "auto") -> str | None:
    """
    Creates a timestamped .zip backup of the repertoire database and PGN resources.
    Returns the backup zip path if created, or None if skipped (deduplicated / unchanged).
    """
    if not repo_name:
        return None

    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        logger.warning(f"Cannot backup repertoire '{repo_name}': DB file does not exist at {db_path}")
        return None

    repo_dir = get_repertoire_dir(repo_name)
    backup_dir = get_repertoire_backup_dir(repo_name)
    
    current_checksum = compute_repertoire_checksum(repo_name)
    
    # Check latest backup manifest for deduplication
    existing_backups = list_repertoire_backups(repo_name)
    if existing_backups:
        latest = existing_backups[0]
        logger.info(f"DEDUP CHECK: latest_checksum='{latest.get('checksum')}' vs current_checksum='{current_checksum}'")
        if latest.get("checksum") == current_checksum and trigger_type == "auto":
            logger.info(f"Backup skipped for '{repo_name}': contents unchanged since last backup ({latest['filename']})")
            return None

    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S_%f")[:23].replace(".", "-")
    zip_name = f"backup_{repo_name}_{timestamp_str}.zip"
    zip_path = os.path.join(backup_dir, zip_name)

    # Gather detailed repertoire statistics & metadata
    details = get_repertoire_detail_stats(db_path, repo_dir, repo_name=repo_name)

    manifest_data = {
        "repertoire_name": repo_name,
        "created_at": now.isoformat(),
        "checksum": compute_repertoire_checksum(repo_name),
        "trigger_type": trigger_type,
        "en_comments": details["en_comments"],
        "de_comments": details["de_comments"],
        "levels_info": details["levels_info"],
        "total_moves": details["total_moves"],
        "pgn_resources": details["pgn_resources"]
    }

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Add DB file
            zf.write(db_path, os.path.basename(db_path))
            
            # 2. Add resource PGN files (Model Games, Typical Motives, Tactics, etc.) & cover images
            if os.path.exists(repo_dir):
                for root, dirs, files in os.walk(repo_dir):
                    is_root = (root == repo_dir)
                    for file in files:
                        if file.endswith(".db"):
                            continue  # Already added at root
                        if file.lower().endswith(".pgn"):
                            if not is_resource_pgn_file(file, repo_name, is_root):
                                continue
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, repo_dir)
                        zf.write(full_p, rel_p)
                        
            # 3. Add manifest.json
            manifest_json = json.dumps(manifest_data, indent=2, ensure_ascii=False)
            zf.writestr("manifest.json", manifest_json)
            
        logger.info(f"Successfully created repertoire backup: {zip_path} (trigger: {trigger_type})")
        
        # Run retention pruning after backup creation
        prune_repertoire_backups(repo_name)
        return zip_path

    except Exception as e:
        logger.error(f"Failed to create backup for '{repo_name}': {e}", exc_info=True)
        if os.path.exists(zip_path):
            try: os.remove(zip_path)
            except: pass
        return None


def list_repertoire_backups(repo_name: str) -> list[dict]:
    """
    Returns a sorted list of all backup snapshots for a repertoire (newest first).
    Each dict contains: path, filename, created_at (datetime), checksum, size_bytes, comment_stats, trigger_type, details.
    """
    backup_dir = get_repertoire_backup_dir(repo_name)
    if not os.path.exists(backup_dir):
        return []

    items = []
    for fname in os.listdir(backup_dir):
        if fname.endswith(".zip") and fname.startswith("backup_"):
            fpath = os.path.join(backup_dir, fname)
            try:
                size_bytes = os.path.getsize(fpath)
                mtime = os.path.getmtime(fpath)
                dt = datetime.fromtimestamp(mtime)
                checksum = ""
                trigger = "auto"
                en_cnt = 0
                de_cnt = 0
                total_moves = 0
                levels_info = []
                pgn_resources = {}

                # Read manifest from zip if valid
                try:
                    with zipfile.ZipFile(fpath, "r") as zf:
                        if "manifest.json" in zf.namelist():
                            data = json.loads(zf.read("manifest.json").decode("utf-8"))
                            checksum = data.get("checksum", "")
                            trigger = data.get("trigger_type", "auto")
                            en_cnt = data.get("en_comments", 0)
                            de_cnt = data.get("de_comments", 0)
                            total_moves = data.get("total_moves", 0)
                            levels_info = data.get("levels_info", [])
                            pgn_resources = data.get("pgn_resources", {})
                            if "created_at" in data:
                                dt = datetime.fromisoformat(data["created_at"])
                except Exception:
                    pass

                # If levels_info missing/empty, inspect zip directly for accurate levels & PGN details
                if not levels_info and not en_cnt and not de_cnt:
                    db_path = get_repertoire_db_path(repo_name)
                    repo_dir = get_repertoire_dir(repo_name)
                    fallback_details = get_repertoire_detail_stats(db_path, repo_dir, zip_path=fpath)
                    en_cnt = fallback_details["en_comments"]
                    de_cnt = fallback_details["de_comments"]
                    levels_info = fallback_details["levels_info"]
                    total_moves = fallback_details["total_moves"]
                    pgn_resources = fallback_details["pgn_resources"]

                comment_stats = f"{en_cnt:,} EN ({de_cnt:,} DE)" if (en_cnt or de_cnt) else "Keine Kommentare"
                items.append({
                    "path": fpath,
                    "filename": fname,
                    "created_at": dt,
                    "checksum": checksum,
                    "size_bytes": size_bytes,
                    "comment_stats": comment_stats,
                    "en_comments": en_cnt,
                    "de_comments": de_cnt,
                    "total_moves": total_moves,
                    "levels_info": levels_info,
                    "pgn_resources": pgn_resources,
                    "trigger_type": trigger
                })
            except Exception as e:
                logger.warning(f"Could not parse backup file {fname}: {e}")

    # Sort descending by created_at (newest first)
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


def prune_repertoire_backups(repo_name: str):
    """
    Applies the multi-tiered retention pruning schedule:
    - 1 Day ago: Keep exact daily snapshots for the last 7 days.
    - 1 Week ago: Keep 1 milestone snapshot for ~7 days ago.
    - 1 Month ago: Keep 1 milestone snapshot for ~30 days ago.
    - 1 Year ago: Keep 1 milestone snapshot for ~365 days ago.
    - Yearly: Keep 1 snapshot for each year thereafter.
    Unmatched intermediate daily backups older than 7 days are safely deleted.
    """
    backups = list_repertoire_backups(repo_name)
    if len(backups) <= 7:
        return  # Keep all if 7 or fewer

    now = datetime.now()
    to_keep = set()

    weekly_buckets = {}
    monthly_buckets = {}
    yearly_buckets = {}

    for b in backups:
        dt = b["created_at"]
        age_days = (now - dt).days

        if age_days <= 7:
            to_keep.add(b["path"])
        elif age_days <= 30:
            w_key = (dt.year, dt.isocalendar()[1])
            if w_key not in weekly_buckets:
                weekly_buckets[w_key] = b["path"]
        elif age_days <= 365:
            m_key = (dt.year, dt.month)
            if m_key not in monthly_buckets:
                monthly_buckets[m_key] = b["path"]
        else:
            y_key = dt.year
            if y_key not in yearly_buckets:
                yearly_buckets[y_key] = b["path"]

    for path in weekly_buckets.values():
        to_keep.add(path)
    for path in monthly_buckets.values():
        to_keep.add(path)
    for path in yearly_buckets.values():
        to_keep.add(path)

    for b in backups:
        if b["path"] not in to_keep:
            try:
                os.remove(b["path"])
                logger.info(f"Pruned outdated backup snapshot: {b['filename']}")
            except Exception as e:
                logger.warning(f"Could not prune backup {b['filename']}: {e}")


def restore_repertoire_from_backup(repo_name: str, backup_zip_path: str) -> bool:
    """
    Restores a repertoire database and all PGN resources from a backup .zip file.
    Creates a pre-restore safety snapshot first!
    """
    if not os.path.exists(backup_zip_path):
        logger.error(f"Cannot restore: Backup file {backup_zip_path} does not exist.")
        return False

    repo_dir = get_repertoire_dir(repo_name)
    db_path = get_repertoire_db_path(repo_name)

    # 1. Pre-restore safety snapshot
    try:
        create_repertoire_backup(repo_name, trigger_type="pre_restore_safety")
    except Exception as e:
        logger.warning(f"Pre-restore safety backup failed: {e}")

    try:
        # 2. Extract zip to repertoire directory
        with zipfile.ZipFile(backup_zip_path, "r") as zf:
            for member in zf.namelist():
                if member == "manifest.json":
                    continue
                
                if member.endswith(".db") and "/" not in member and "\\" not in member:
                    target_db = db_path
                    with open(target_db, "wb") as f_out:
                        f_out.write(zf.read(member))
                else:
                    out_path = os.path.join(repo_dir, member)
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    if not member.endswith("/"):
                        with open(out_path, "wb") as f_out:
                            f_out.write(zf.read(member))

        logger.info(f"Successfully restored repertoire '{repo_name}' from {backup_zip_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to restore repertoire '{repo_name}' from {backup_zip_path}: {e}", exc_info=True)
        return False
