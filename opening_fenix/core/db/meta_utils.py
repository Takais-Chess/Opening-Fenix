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

def _update_cached_names_recursive_standalone(session: Session, pos: Position, visited: Optional[Set[int]] = None) -> None:
    """
    Recursively updates cached variation names downstream.
    Used for database repairs.
    """
    if visited is None: visited = set()
    
    new_v1, new_v2, new_v3 = pos.variation_1, pos.variation_2, pos.variation_3
    
    if not (new_v1 and new_v2 and new_v3):
        incoming_moves = session.query(Move).filter_by(to_position_id=pos.id).order_by(Move.priority_score.desc()).all()
        p_v1, p_v2, p_v3 = None, None, None
        for move in incoming_moves:
            parent = session.get(Position, move.from_position_id)
            if not parent: continue
            if p_v1 is None and parent.cached_v1: p_v1 = parent.cached_v1
            if p_v2 is None and parent.cached_v2: p_v2 = parent.cached_v2
            if p_v3 is None and parent.cached_v3: p_v3 = parent.cached_v3
            if p_v1 and p_v2 and p_v3: break
        
        if not new_v1: new_v1 = p_v1
        if not new_v2: new_v2 = p_v2
        if not new_v3: new_v3 = p_v3
            
    names_changed = (pos.cached_v1 != new_v1) or (pos.cached_v2 != new_v2) or (pos.cached_v3 != new_v3)

    pos.cached_v1 = new_v1
    pos.cached_v2 = new_v2
    pos.cached_v3 = new_v3
    
    if not names_changed and pos.id in visited:
        return
        
    visited.add(pos.id)
    
    children_moves = session.query(Move).filter_by(from_position_id=pos.id).all()
    for move in children_moves:
        child_pos = session.get(Position, move.to_position_id)
        if child_pos:
            _update_cached_names_recursive_standalone(session, child_pos, visited)
