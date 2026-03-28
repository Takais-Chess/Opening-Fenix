import os
import sqlite3
import gc
import time
from typing import List, Dict, Any, Optional
from opening_fenix.core.db.models import RepertoireLevel, Base, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.data_tools import get_user_dir, get_meta, set_meta, delete_repertoire_db
from opening_fenix.core.logger import logger

class RepertoireService:
    def __init__(self):
        self.active_repertoire_name = None
        self.repo_db = None
        self.repo_session = None

    def get_all_repertoires(self) -> List[str]:
        repo_dir = os.path.join(get_user_dir(), "repertoires")
        if not os.path.exists(repo_dir): 
            return []
        
        files = []
        for f in os.listdir(repo_dir):
            if f.endswith(".db"):
                try:
                    db_path = os.path.join(repo_dir, f)
                    conn = sqlite3.connect(db_path)
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                    conn.close()
                    files.append(f[:-3])
                except sqlite3.DatabaseError as e:
                    logger.debug(f"Skipping {f} due to database error: {e}")
        return files

    def set_active_repertoire(self, repo_name: Optional[str]) -> None:
        self.close()
        self.active_repertoire_name = repo_name
        
        if not repo_name: 
            return

        db_path = os.path.join(get_user_dir(), "repertoires", f"{repo_name}.db")
        self.repo_db = DatabaseManager(db_path, base=Base)
        self.repo_session = self.repo_db.get_session()

    def close(self) -> None:
        if self.repo_session:
            self.repo_session.close()
            self.repo_session = None
        if self.repo_db:
            self.repo_db.close()
            self.repo_db = None

    def delete_repertoire(self, repo_name: str) -> bool:
        if self.active_repertoire_name == repo_name:
            self.set_active_repertoire(None)
        
        gc.collect()
        time.sleep(0.5) 
        success, _ = delete_repertoire_db(repo_name)
        return success

    def get_repertoire_levels(self) -> List[Dict[str, Any]]:
        if not self.repo_session: return []
        levels = self.repo_session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
        return [{"name": lvl.name, "order": lvl.order, "target_elo": lvl.target_elo} for lvl in levels]

    def get_level_info(self, level_order: int) -> Optional[RepertoireLevel]:
        if not self.repo_session: return None
        return self.repo_session.query(RepertoireLevel).filter_by(order=level_order).first()

    def update_level_elo(self, level_order: int, target_elo: int) -> None:
        if not self.repo_session: return
        lvl = self.repo_session.query(RepertoireLevel).filter_by(order=level_order).first()
        if lvl:
            lvl.target_elo = target_elo
            self.repo_session.commit()

    def get_repertoire_info(self) -> Dict[str, Any]:
        if not self.repo_session:
            return {"name": self.active_repertoire_name, "levels": [], "moves": "N/A"}

        from opening_fenix.core.db.models import RepertoireMove
        levels = self.get_repertoire_levels()
        moves_count = self.repo_session.query(RepertoireMove.move_id).filter(RepertoireMove.is_active == True).distinct().count()

        return {
            "name": get_meta(self.repo_session, "name", self.active_repertoire_name),
            "levels": [lvl['name'] for lvl in levels],
            "depth": get_meta(self.repo_session, "analysis_depth", "N/A"),
            "elo": get_meta(self.repo_session, "lichess_elo", "N/A"),
            "moves": moves_count,
            "description": get_meta(self.repo_session, "description", "")
        }

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
