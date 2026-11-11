import os
import shutil
from typing import Optional, Tuple, Set, Any
from sqlalchemy import or_
from sqlalchemy.orm import Session
from opening_fenix.core.db.models import Metadata, Position, Move
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_user_dir, get_repertoire_dir, get_repertoire_db_path

def get_meta(session: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieves a metadata value from the database."""
    m = session.query(Metadata).filter_by(key=key).first()
    return m.value if m else default

def set_meta(session: Session, key: str, value: Any) -> None:
    """Sets or updates a metadata value in the database.
    
    If value is None, the key is deleted from metadata (rather than storing
    the string 'None', which would be truthy and mislead downstream callers).
    """
    m = session.query(Metadata).filter_by(key=key).first()
    if value is None:
        if m:
            session.delete(m)
    elif m:
        m.value = str(value)
    else:
        session.add(Metadata(key=key, value=str(value)))

def delete_repertoire_db(repo_name: str) -> Tuple[bool, str]:
    """
    Deletes the directory and database file for a given repertoire.
    Also removes all learning data and settings for this repertoire across all user profiles.
    
    Args:
        repo_name: The name of the repertoire to delete.
        
    Returns:
        A tuple (success, message).
    """
    try:
        from opening_fenix.core.utils import release_repertoire_locks
        from opening_fenix.core.services.profile_service import delete_repertoire_from_profiles_globally
        from opening_fenix.core.logger import logger
        
        release_repertoire_locks(repo_name, checkpoint_wal=False)

        # Collect any existing directories (regular and/or test)
        dirs_to_delete = []
        regular_dir = get_repertoire_dir(repo_name, is_test=False)
        test_dir = get_repertoire_dir(repo_name, is_test=True)
        if regular_dir and os.path.exists(regular_dir) and os.path.isdir(regular_dir):
            dirs_to_delete.append(regular_dir)
        if test_dir and os.path.exists(test_dir) and os.path.isdir(test_dir) and test_dir not in dirs_to_delete:
            dirs_to_delete.append(test_dir)

        if not dirs_to_delete:
            # Repertoire directory not found on disk, but still self-heal profiles
            delete_repertoire_from_profiles_globally(repo_name)
            return False, "Repertoire-Verzeichnis nicht gefunden."

        def remove_readonly(func, path, _):
            import stat
            try:
                os.chmod(path, stat.S_IWRITE)
            except Exception:
                pass
            try:
                func(path)
            except Exception:
                pass

        import time
        import gc
        import stat
        last_err = None

        for repo_dir in dirs_to_delete:
            deleted = False
            for attempt in range(10):
                try:
                    if os.path.exists(repo_dir):
                        # Ensure all files and subdirectories are writable
                        for root, dirs, files in os.walk(repo_dir):
                            for d in dirs:
                                try: os.chmod(os.path.join(root, d), stat.S_IWRITE)
                                except Exception: pass
                            for f in files:
                                try: os.chmod(os.path.join(root, f), stat.S_IWRITE)
                                except Exception: pass
                        try: os.chmod(repo_dir, stat.S_IWRITE)
                        except Exception: pass

                        shutil.rmtree(repo_dir, onerror=remove_readonly)

                    if not os.path.exists(repo_dir):
                        deleted = True
                        break
                except Exception as e:
                    last_err = e
                    release_repertoire_locks(repo_name, checkpoint_wal=False)
                    gc.collect()
                    time.sleep(0.25 * (attempt + 1))

            if not deleted and os.path.exists(repo_dir):
                logger.error(f"delete_repertoire_db failed for '{repo_name}': {last_err}")
                return False, f"Fehler beim Löschen: {last_err}"

        # Clean up learning progress and settings for this repertoire across all user profiles
        delete_repertoire_from_profiles_globally(repo_name)

        logger.info(f"Repertoire '{repo_name}' was successfully deleted from disk.")
        return True, f"Repertoire '{repo_name}' wurde gelöscht."
    except Exception as e:
        from opening_fenix.core.logger import logger
        logger.error(f"delete_repertoire_db exception for '{repo_name}': {e}")
        return False, f"Fehler beim Löschen: {e}"

def _get_all_repertoire_db_paths():
    repo_base = os.path.join(get_user_dir(), "repertoires")
    if not os.path.exists(repo_base):
        return []
        
    paths = []
    # Normal repertoires
    for f in os.listdir(repo_base):
        if f != "test" and os.path.isdir(os.path.join(repo_base, f)):
            db_path = get_repertoire_db_path(f, is_test=False)
            if os.path.exists(db_path):
                paths.append((f, db_path))
                
    # Test repertoires
    test_base = os.path.join(repo_base, "test")
    if os.path.exists(test_base):
        for f in os.listdir(test_base):
            if os.path.isdir(os.path.join(test_base, f)):
                db_path = get_repertoire_db_path(f, is_test=True)
                if os.path.exists(db_path):
                    paths.append((f, db_path))
                    
    return paths

def check_all_databases_integrity() -> str:
    """
    Checks all repertoire databases for missing variation caches.
    Returns a formatted string containing the results.
    """
    db_paths = _get_all_repertoire_db_paths()
    if not db_paths:
        return "Keine Repertoires gefunden."

    results = []
    for repo_name, db_path in db_paths:
        try:
            db = DatabaseManager(db_path)
            session = db.get_session()
            
            missing_cache = session.query(Position).filter(
                or_(
                    (Position.variation_1 != None) & (Position.variation_1 != ""),
                    (Position.variation_2 != None) & (Position.variation_2 != ""),
                    (Position.variation_3 != None) & (Position.variation_3 != "")
                ),
                Position.cached_v1 == None
            ).first()
            
            if missing_cache:
                results.append(f"❌ {repo_name}: Cache unvollständig.")
            else:
                results.append(f"✅ {repo_name}: OK.")
            
            session.close()
            db.close()
        except Exception as e:
            results.append(f"⚠️ {repo_name}: Fehler bei Prüfung ({e})")

    return "\n".join(results)

def repair_all_databases_cache() -> str:
    """
    Repairs missing variation caches in all repertoire databases.
    Returns a formatted string containing the results.
    """
    db_paths = _get_all_repertoire_db_paths()
    if not db_paths:
        return "Keine Repertoires gefunden."

    results = []
    for repo_name, db_path in db_paths:
        try:
            db = DatabaseManager(db_path)
            session = db.get_session()
            
            start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
            start_pos = session.query(Position).filter_by(fen=start_fen).first()
            
            if start_pos:
                print(f"Repariere {repo_name}...")
                _update_cached_names_recursive_standalone(session, start_pos)
                session.commit()
                results.append(f"✅ {repo_name}: Repariert.")
            else:
                results.append(f"⚠️ {repo_name}: Startposition nicht gefunden.")
            
            session.close()
            db.close()
        except Exception as e:
            results.append(f"❌ {repo_name}: Fehler bei Reparatur ({e})")

    return "\n".join(results)

def rebuild_cached_names_fast(session: Session, start_pos: Optional[Position] = None) -> int:
    """
    High-performance in-memory recalculation and bulk update of downstream
    cached variation names (cached_v1, cached_v2, cached_v3).
    Replaces slow recursive N+1 database queries with an in-memory graph traversal.
    Returns the number of positions whose cached variation names were updated.
    """
    from collections import defaultdict, deque
    from opening_fenix.core.db.database import commit_with_retry

    pos_records = session.query(
        Position.id, Position.variation_1, Position.variation_2, Position.variation_3,
        Position.cached_v1, Position.cached_v2, Position.cached_v3, Position.fen
    ).all()
    if not pos_records:
        return 0

    pos_dict = {
        row.id: {
            'v1': row.variation_1, 'v2': row.variation_2, 'v3': row.variation_3,
            'cv1': row.cached_v1, 'cv2': row.cached_v2, 'cv3': row.cached_v3,
            'fen': row.fen
        } for row in pos_records
    }

    moves = session.query(Move.from_position_id, Move.to_position_id, Move.priority_score).all()

    children = defaultdict(list)
    parents = defaultdict(list)
    for from_id, to_id, prio in moves:
        children[from_id].append(to_id)
        parents[to_id].append((from_id, prio or 0.0))

    for to_id in parents:
        parents[to_id].sort(key=lambda x: x[1], reverse=True)

    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    start_pos_id = start_pos.id if start_pos else next((pid for pid, d in pos_dict.items() if d['fen'] and d['fen'].startswith(start_fen)), None)

    root_ids = [start_pos_id] if start_pos_id else []
    for pid in pos_dict:
        if pid not in parents and pid != start_pos_id:
            root_ids.append(pid)

    queue = deque(root_ids)
    visited = set()
    updates = []

    while queue:
        curr_id = queue.popleft()
        curr = pos_dict.get(curr_id)
        if not curr:
            continue

        new_v1, new_v2, new_v3 = curr['v1'], curr['v2'], curr['v3']
        if not (new_v1 and new_v2 and new_v3):
            p_v1, p_v2, p_v3 = None, None, None
            for p_id, _ in parents.get(curr_id, []):
                p_data = pos_dict.get(p_id)
                if not p_data:
                    continue
                if p_v1 is None and p_data['cv1']: p_v1 = p_data['cv1']
                if p_v2 is None and p_data['cv2']: p_v2 = p_data['cv2']
                if p_v3 is None and p_data['cv3']: p_v3 = p_data['cv3']
                if p_v1 and p_v2 and p_v3:
                    break
            if not new_v1: new_v1 = p_v1
            if not new_v2: new_v2 = p_v2
            if not new_v3: new_v3 = p_v3

        changed = (curr['cv1'] != new_v1) or (curr['cv2'] != new_v2) or (curr['cv3'] != new_v3)
        curr['cv1'], curr['cv2'], curr['cv3'] = new_v1, new_v2, new_v3

        if not changed and curr_id in visited:
            continue
        visited.add(curr_id)

        if changed:
            updates.append({
                'id': curr_id,
                'cached_v1': new_v1,
                'cached_v2': new_v2,
                'cached_v3': new_v3
            })

        for child_id in children.get(curr_id, []):
            queue.append(child_id)

    if updates:
        batch_size = 500
        for i in range(0, len(updates), batch_size):
            session.bulk_update_mappings(Position, updates[i:i + batch_size])
        commit_with_retry(session)

    return len(updates)


def _update_cached_names_recursive_standalone(session: Session, pos: Position, visited: Optional[Set[int]] = None) -> None:
    """
    High-performance wrapper to update cached variation names downstream.
    """
    rebuild_cached_names_fast(session, start_pos=pos)
