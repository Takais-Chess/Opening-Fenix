import os
from typing import Optional, Tuple, Set, Any
from sqlalchemy import or_
from sqlalchemy.orm import Session
from opening_fenix.core.db.models import Metadata, Position, Move
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_user_dir

def get_meta(session: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieves a metadata value from the database."""
    m = session.query(Metadata).filter_by(key=key).first()
    return m.value if m else default

def set_meta(session: Session, key: str, value: Any) -> None:
    """Sets or updates a metadata value in the database."""
    m = session.query(Metadata).filter_by(key=key).first()
    if m:
        m.value = str(value)
    else:
        session.add(Metadata(key=key, value=str(value)))

def delete_repertoire_db(repo_name: str) -> Tuple[bool, str]:
    """
    Deletes the database file for a given repertoire.
    
    Args:
        repo_name: The name of the repertoire to delete.
        
    Returns:
        A tuple (success, message).
    """
    try:
        db_path = os.path.join(get_user_dir(), "repertoires", f"{repo_name}.db")
        if os.path.exists(db_path):
            os.remove(db_path)
            return True, f"Repertoire '{repo_name}' wurde gelöscht."
        else:
            return False, "Repertoire-Datei nicht gefunden."
    except Exception as e:
        return False, f"Fehler beim Löschen: {e}"

def check_all_databases_integrity() -> str:
    """
    Checks all repertoire databases for missing variation caches.
    Returns a formatted string containing the results.
    """
    repo_dir = os.path.join(get_user_dir(), "repertoires")
    if not os.path.exists(repo_dir):
        return "Keine Repertoires gefunden."

    results = []
    for filename in os.listdir(repo_dir):
        if filename.endswith(".db"):
            repo_name = filename[:-3]
            db_path = os.path.join(repo_dir, filename)
            
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
    repo_dir = os.path.join(get_user_dir(), "repertoires")
    if not os.path.exists(repo_dir):
        return "Keine Repertoires gefunden."

    results = []
    for filename in os.listdir(repo_dir):
        if filename.endswith(".db"):
            repo_name = filename[:-3]
            db_path = os.path.join(repo_dir, filename)
            
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
    if pos.id in visited: return
    visited.add(pos.id)
    
    new_v1, new_v2, new_v3 = pos.variation_1, pos.variation_2, pos.variation_3
    
    if not (new_v1 and new_v2 and new_v3):
        incoming_moves = session.query(Move).filter_by(to_position_id=pos.id).order_by(Move.priority_score.desc()).all()
        p_v1, p_v2, p_v3 = None, None, None
        for move in incoming_moves:
            parent = session.query(Position).get(move.from_position_id)
            if not parent: continue
            if p_v1 is None and parent.cached_v1: p_v1 = parent.cached_v1
            if p_v2 is None and parent.cached_v2: p_v2 = parent.cached_v2
            if p_v3 is None and parent.cached_v3: p_v3 = parent.cached_v3
            if p_v1 and p_v2 and p_v3: break
        
        if not new_v1: new_v1 = p_v1
        if not new_v2: new_v2 = p_v2
        if not new_v3: new_v3 = p_v3
            
    pos.cached_v1 = new_v1
    pos.cached_v2 = new_v2
    pos.cached_v3 = new_v3
    
    children_moves = session.query(Move).filter_by(from_position_id=pos.id).all()
    for move in children_moves:
        child_pos = session.query(Position).get(move.to_position_id)
        if child_pos:
            _update_cached_names_recursive_standalone(session, child_pos, visited)
