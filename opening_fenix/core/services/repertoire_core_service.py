import os
import sqlite3
import gc
import time
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional, Tuple, Set
from opening_fenix.core.db.models import RepertoireLevel, Base, Move, RepertoireMove, Position, LichessData
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.data_tools import get_user_dir, get_meta, set_meta, delete_repertoire_db
from opening_fenix.core.utils import get_repertoire_dir, get_repertoire_db_path
from opening_fenix.core.services.analysis_service import get_repertoire_analysis_status
from opening_fenix.core.services.profile_service import update_repertoire_name_globally
from opening_fenix.core.logger import logger
import json

def fetch_repertoire_levels(session: Session) -> List[Dict[str, Any]]:
    """Standalone function to fetch repertoire levels using a provided session."""
    if not session: return []
    lvls = session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
    return [{"id": l.id, "name": l.name, "order": l.order, "target_elo": l.target_elo} for l in lvls]

def fetch_repertoire_info(session: Session, repo_name: str, fast_only: bool = False) -> Dict[str, Any]:
    """Standalone function to fetch repertoire info using a provided session. Safe for background threads."""
    if not session:
        return {"name": repo_name, "levels": [], "moves": "N/A", "level_details": []}

    levels_objs = session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
    levels = [{"name": l.name, "order": l.order, "target_elo": l.target_elo} for l in levels_objs]
    
    if fast_only:
        return {
            "name": get_meta(session, "name", repo_name),
            "levels": [lvl['name'] for lvl in levels],
            "level_details": [], # Defer counts
            "depth": "Laden...", 
            "elo": get_meta(session, "lichess_elo", "N/A"),
            "coverage_pct": 0,
            "moves": "Laden...",
            "description": get_meta(session, "description", "")
        }

    # 1. Fetch move counts for all levels in a single query
    level_counts = session.query(RepertoireMove.level, func.count(RepertoireMove.move_id))\
        .filter(RepertoireMove.is_active == True)\
        .group_by(RepertoireMove.level).all()
    counts_map = {lvl_order: count for lvl_order, count in level_counts}

    level_details = []
    for lvl in levels:
        count = sum(cnt for ord, cnt in counts_map.items() if ord <= lvl['order'])
        level_details.append({
            "name": lvl['name'],
            "order": lvl['order'],
            "target_elo": lvl['target_elo'],
            "moves": count
        })

    total_moves = sum(counts_map.values())
    
    # Calculate coverage %
    total_pos = session.query(func.count(Position.id)).scalar() or 0
    elo_cat = get_meta(session, "lichess_elo", "N/A")
    
    cached_count = get_meta(session, "cov_cache_count", "-1")
    cached_pct = get_meta(session, "cov_cache_pct", "")
    cached_elo = get_meta(session, "cov_cache_elo", "")
    
    if str(total_pos) == str(cached_count) and cached_elo == elo_cat and cached_pct:
        coverage_pct = float(cached_pct)
    else:
        covered_pos = session.query(func.count(func.distinct(Position.id)))\
            .join(LichessData, Position.fen == LichessData.fen)\
            .filter(LichessData.elo_range == elo_cat).scalar() or 0
        
        coverage_pct = (covered_pos / total_pos * 100) if total_pos > 0 else 0
        coverage_pct = min(100.0, coverage_pct) # Hard cap at 100%
        
        # Save to cache
        set_meta(session, "cov_cache_count", total_pos)
        set_meta(session, "cov_cache_pct", coverage_pct)
        set_meta(session, "cov_cache_elo", elo_cat)
        session.commit()
    

    return {
        "name": get_meta(session, "name", repo_name),
        "levels": [lvl['name'] for lvl in levels],
        "level_details": level_details,
        "depth": get_repertoire_analysis_status(repo_name, session),
        "elo": elo_cat,
        "coverage_pct": coverage_pct,
        "moves": total_moves,
        "description": get_meta(session, "description", "")
    }

class RepertoireService:
    def __init__(self):
        self.active_repertoire_name = None
        self.is_active_test = False
        self.repo_db = None
        self.repo_session = None

    def get_all_repertoires(self) -> List[str]:
        repo_base = os.path.join(get_user_dir(), "repertoires")
        if not os.path.exists(repo_base):
            return []
        
        files = []
        
        # Scan normally
        for f in os.listdir(repo_base):
            if f != "test" and os.path.isdir(os.path.join(repo_base, f)):
                files.append(f)
                
        # Scan test layer
        test_base = os.path.join(repo_base, "test")
        if os.path.exists(test_base):
            for f in os.listdir(test_base):
                if os.path.isdir(os.path.join(test_base, f)):
                    files.append(f)
                    
        # Filter only those that actually have a database
        valid_repos = []
        for repo_name in files:
            db_path = get_repertoire_db_path(repo_name)
            if os.path.exists(db_path):
                # Verify SQLite header just in case
                try:
                    conn = sqlite3.connect(db_path)
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                    conn.close()
                    valid_repos.append(repo_name)
                except sqlite3.DatabaseError as e:
                    logger.debug(f"Skipping {repo_name} due to database error: {e}")
                    
        return valid_repos

    def set_active_repertoire(self, repo_name: Optional[str], is_test: Optional[bool] = False) -> None:
        self.close()
        self.active_repertoire_name = repo_name
        self.is_active_test = (is_test is True)
        
        if not repo_name: 
            return

        db_path = get_repertoire_db_path(repo_name, is_test)
        self.repo_db = DatabaseManager(db_path, base=Base)
        self.repo_session = self.repo_db.get_session()

    def close(self) -> None:
        if self.repo_session:
            try:
                self.repo_session.close()
            except Exception:
                pass
            self.repo_session = None
        if self.repo_db:
            try:
                self.repo_db.close()
            except Exception:
                pass
            self.repo_db = None

    def delete_repertoire(self, repo_name: str) -> bool:
        if self.active_repertoire_name == repo_name:
            self.set_active_repertoire(None)
        
        gc.collect()
        time.sleep(0.5) 
        success, _ = delete_repertoire_db(repo_name)
        return success

    def rename_repertoire(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        """
        Renames the repertoire folder, its internal database file,
        auxiliary SQLite files, and updates all user profiles.
        """
        if not old_name or not new_name or old_name == new_name:
            return False, "Ungültiger oder identischer Name."

        # 1. Validation
        import re
        if not re.match(r'^[a-zA-Z0-9_\- ]+$', new_name):
            return False, "Ungültige Zeichen im Namen."

        old_dir = get_repertoire_dir(old_name)
        new_dir = os.path.join(os.path.dirname(old_dir), new_name)
        
        if os.path.exists(new_dir):
            return False, "Ein Repertoire mit diesem Namen existiert bereits."

        # 2. Close Active Connection (Vital for Windows)
        active_was_old = (self.active_repertoire_name == old_name)
        if active_was_old:
            self.close()

        # Try to ensure files are not locked
        import gc
        gc.collect()
        time.sleep(0.5)

        try:
            # 3. Rename Folder
            os.rename(old_dir, new_dir)
            
            # 4. Rename Database File
            old_db = os.path.join(new_dir, f"{old_name}.db")
            new_db = os.path.join(new_dir, f"{new_name}.db")
            if os.path.exists(old_db):
                os.rename(old_db, new_db)
            
            # 5. Rename Auxiliary Files
            for ext in [".db-wal", ".db-shm"]:
                old_aux = os.path.join(new_dir, f"{old_name}{ext}")
                new_aux = os.path.join(new_dir, f"{new_name}{ext}")
                if os.path.exists(old_aux):
                    os.rename(old_aux, new_aux)
            
            # 6. Global Profile Update (Keep learning progress)
            update_repertoire_name_globally(old_name, new_name)

            # 7. Update Metadata inside the DB
            try:
                db = DatabaseManager(new_db, base=Base)
                session = db.get_session()
                # Update meta "name" (internal display name)
                set_meta(session, "name", new_name)
                session.commit()
                session.close()
                db.close()
            except Exception as e:
                logger.error(f"Renamed files but failed to update internal metadata: {e}")
            
            # 8. Re-load if it was active
            if active_was_old:
                self.set_active_repertoire(new_name)

            return True, f"Erfolgreich umbenannt in '{new_name}'."

        except Exception as e:
            logger.exception(f"Critical error during repertoire rename from '{old_name}' to '{new_name}': {e}")
            return False, f"Fehler beim Umbenennen: {str(e)}"

    def get_repertoire_levels(self) -> List[Dict[str, Any]]:
        return fetch_repertoire_levels(self.repo_session)

    def get_level_info(self, level_order: int) -> Optional[RepertoireLevel]:
        if not self.repo_session: return None
        return self.repo_session.query(RepertoireLevel).filter_by(order=level_order).first()

    def update_level_elo(self, level_order: int, target_elo: int) -> None:
        if not self.repo_session: return
        lvl = self.repo_session.query(RepertoireLevel).filter_by(order=level_order).first()
        if lvl:
            lvl.target_elo = target_elo
            self.repo_session.commit()

    def get_repertoire_info(self, fast_only=False) -> Dict[str, Any]:
        return fetch_repertoire_info(self.repo_session, self.active_repertoire_name, fast_only=fast_only)

    def set_repertoire_description(self, description: str) -> None:
        if not self.repo_session: return
        set_meta(self.repo_session, "description", description)
        self.repo_session.commit()

    def get_repertoire_color(self) -> str:
        if not self.repo_session: return 'w'
        return get_meta(self.repo_session, "color", "w")

    def get_start_move(self) -> int:
        if not self.repo_session: return 1
        try:
            val = get_meta(self.repo_session, "start_move", 1)
            return int(val) if val is not None else 1
        except (ValueError, TypeError):
            return 1

    def get_all_moves(self) -> List[Move]:
        if not self.repo_session: return []
        return self.repo_session.query(Move).all()

    def get_all_active_repertoire_moves(self) -> List[RepertoireMove]:
        if not self.repo_session: return []
        return self.repo_session.query(RepertoireMove).filter(RepertoireMove.is_active == True).all()

    def move_all_to_level(self, level: int) -> int:
        if not self.repo_session: return 0
        from opening_fenix.core.db.models import RepertoireMove
        updated_count = self.repo_session.query(RepertoireMove).filter(RepertoireMove.is_active == True).update({"level": level})
        self.repo_session.commit()
        return updated_count

    def check_logical_integrity(self) -> int:
        """
        Checks for orphaned moves in the database (moves pointing to missing positions).
        Returns the number of orphaned moves found.
        """
        if not self.repo_session: return 0
        try:
            from sqlalchemy import text
            with self.repo_session.bind.connect() as conn:
                result = conn.execute(text(
                    "SELECT COUNT(*) FROM moves WHERE from_position_id NOT IN (SELECT id FROM positions) "
                    "OR to_position_id NOT IN (SELECT id FROM positions)"
                )).scalar()
                return int(result or 0)
        except Exception as e:
            logger.error(f"Error checking logical integrity: {e}")
            return 0

    def repair_logical_integrity(self) -> int:
        """
        Deletes orphaned moves to restore database consistency.
        Returns the number of deleted moves.
        """
        if not self.repo_session: return 0
        try:
            from sqlalchemy import text
            with self.repo_session.bind.connect() as conn:
                # 1. Delete associated repertoire_moves first
                conn.execute(text(
                    "DELETE FROM repertoire_moves WHERE move_id IN ("
                    "SELECT id FROM moves WHERE from_position_id NOT IN (SELECT id FROM positions) "
                    "OR to_position_id NOT IN (SELECT id FROM positions))"
                ))
                # 2. Delete the orphaned moves
                result = conn.execute(text(
                    "DELETE FROM moves WHERE from_position_id NOT IN (SELECT id FROM positions) "
                    "OR to_position_id NOT IN (SELECT id FROM positions)"
                ))
                conn.commit()
                deleted = result.rowcount
                logger.info(f"Repaired logical integrity: {deleted} orphaned moves deleted.")
                return deleted
        except Exception as e:
            logger.error(f"Error repairing logical integrity: {e}")
            return 0
