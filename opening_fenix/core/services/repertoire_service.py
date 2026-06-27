import os
import json
import sqlite3
import gc
import time
import chess
from collections import deque
from typing import List, Dict, Tuple, Any, Optional, Set
from sqlalchemy import or_, text
from sqlalchemy.orm import joinedload
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, Base, TrainingData
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.data_tools import get_user_dir, get_meta, set_meta, delete_repertoire_db
from opening_fenix.core.logger import logger

from opening_fenix.core.services.repertoire_core_service import RepertoireService
from opening_fenix.core.services.tree_navigation_service import TreeNavigationService
from opening_fenix.core.services.explorer_service import ExplorerService

class RepertoireManager:
    def __init__(self, profile_name: str = "Default") -> None:
        self.profile_name = profile_name
        
        # New split services
        self.core = RepertoireService()
        self.nav = None
        self.explorer = None
        
        self.priority_cache = None 

    @property
    def active_repertoire_name(self):
        return self.core.active_repertoire_name

    @property
    def is_active_test(self):
        return self.core.is_active_test

    def get_all_repertoires(self) -> List[str]:
        return self.core.get_all_repertoires()

    def set_active_repertoire(self, repo_name: Optional[str], is_test: Optional[bool] = None) -> None:
        self.core.set_active_repertoire(repo_name, is_test)
        
        if repo_name:
            self.nav = TreeNavigationService(self.core.repo_session)
            self.explorer = ExplorerService(self.core.repo_session)
        else:
            self.nav = None
            self.explorer = None
            
        self.priority_cache = None 

    @property
    def repo_session(self):
        return self.core.repo_session

    @property
    def repo_db(self):
        return self.core.repo_db

    def close(self) -> None:
        self.core.close()

    def delete_repertoire(self, repo_name: str) -> Tuple[bool, str]:
        # If the deleted repertoire was active, we need to clear our sub-services too
        if self.active_repertoire_name == repo_name:
            self.set_active_repertoire(None)
            
        success = self.core.delete_repertoire(repo_name)
        return success, "Gelöscht" if success else "Fehler beim Löschen"

    def rename_repertoire(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        """Renames the repertoire and re-initializes sub-services if the renamed repo was active."""
        was_active = (self.active_repertoire_name == old_name)
        
        success, msg = self.core.rename_repertoire(old_name, new_name)
        
        if success and was_active:
            # Re-initialize with new name
            self.set_active_repertoire(new_name)
            
        return success, msg

    def get_repertoire_levels(self) -> List[Dict[str, Any]]:
        return self.core.get_repertoire_levels()

    def get_level_info(self, level_order: int) -> Optional[RepertoireLevel]:
        return self.core.get_level_info(level_order)

    def update_level_elo(self, level_order: int, target_elo: int) -> None:
        self.core.update_level_elo(level_order, target_elo)

    def move_all_to_level(self, level: int) -> int:
        return self.core.move_all_to_level(level)

    def get_repertoire_info(self, fast_only=False) -> Dict[str, Any]:
        return self.core.get_repertoire_info(fast_only=fast_only)

    def set_repertoire_description(self, description: str) -> None:
        self.core.set_repertoire_description(description)

    def get_repertoire_color(self) -> str:
        return self.core.get_repertoire_color()

    def get_repertoire_start_move(self) -> int:
        return self.core.get_start_move()

    def set_repertoire_start_move(self, start_move: int) -> None:
        if not self.repo_session: return
        set_meta(self.repo_session, "start_move", str(start_move))
        self.repo_session.commit()

    def get_variation_structure(self):
        if not self.nav: return {}
        return self.nav.get_variation_structure()

    def _prepare_variation_filter(self, variation_name):
        """Internal helper for training_manager and tests."""
        if not self.nav: return {"roots": set(), "lead_up": set()}
        return self.nav.get_variation_filter_info(variation_name)

    def get_variation_entry_point_fen(self, variation_name: str) -> Optional[str]:
        if not self.nav: return None
        return self.nav.get_variation_entry_point_fen(variation_name)

    def get_history_for_move(self, move_obj, variation_name: Optional[str] = None):
        if not self.nav or not move_obj: return []
        return self.nav.get_history_for_move_recursive(move_obj.id, variation_name=variation_name)

    def get_history_for_fen(self, fen, variation_name: Optional[str] = None):
        if not self.repo_session: return []
        board = chess.Board(fen)
        clean_fen = " ".join(board.fen().split(" ")[:4])
        pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()
        if not pos: return []
        
        # Priority for path retrieval: if we have a variation filter, prefer moves that lead to this position 
        # and belong to that variation.
        prio_sql = ""
        if variation_name:
            prio_sql = f"CASE WHEN (p.variation_1 = '{variation_name}' OR p.variation_2 = '{variation_name}' OR p.variation_3 = '{variation_name}') THEN 1 ELSE 0 END DESC,"

        query = text(f"""
            SELECT m.id FROM moves m
            JOIN positions p ON m.from_position_id = p.id
            WHERE m.to_position_id = :pid
            ORDER BY {prio_sql} m.priority_score DESC
            LIMIT 1
        """)
        try:
            res = self.repo_session.execute(query, {"pid": pos.id}).fetchone()
            if not res: return []
            move_id = res[0]
            # Since get_history_for_move_recursive takes an ID, we just need the Move object or its proxy
            # But the service now takes move_id directly, so let's simplify.
            return self.nav.get_history_for_move_recursive(move_id, variation_name=variation_name)
        except Exception as e:
            logger.error(f"Error in get_history_for_fen: {e}")
            return []

    def get_repertoire_root_fen(self):
        if not self.repo_session: return None
        any_move = self.repo_session.query(Move).join(RepertoireMove).first()
        if not any_move: return None
        return self.nav.get_absolute_ancestor_fen(any_move.id)

    def get_explorer_data_for_fen(self, fen, training_manager):
        if not self.explorer: return {}
        self.explorer.training_manager = training_manager
        return self.explorer.get_explorer_data_for_fen(fen, self.get_repertoire_color())

    def get_repertoire_moves_for_fen(self, fen):
        if not self.repo_session: return []
        board = chess.Board(fen)
        clean_fen = " ".join(board.fen().split(" ")[:4])
        pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()

        all_ucis = set()
        repertoire_color = self.get_repertoire_color()
        is_player_turn = (board.turn == chess.WHITE and repertoire_color == 'w') or \
                         (board.turn == chess.BLACK and repertoire_color == 'b')

        if not pos: return []

        if is_player_turn:
            player_moves = self.repo_session.query(Move.uci)\
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                .filter(Move.from_position_id == pos.id, RepertoireMove.is_active == True).all()
            for move in player_moves: all_ucis.add(move[0])
        else:
            opponent_moves = self.repo_session.query(Move).filter(Move.from_position_id == pos.id).all()
            for move in opponent_moves:
                our_next = self.repo_session.query(RepertoireMove)\
                    .join(Move, RepertoireMove.move_id == Move.id)\
                    .filter(Move.from_position_id == move.to_position_id, RepertoireMove.is_active == True).first()
                if our_next: all_ucis.add(move.uci)

        return list(all_ucis)

    def _ensure_priority_cache(self):
        if self.priority_cache is None and self.repo_session:
            try:
                q = self.repo_session.query(Position.fen, Move.uci, Move.priority_score)\
                    .join(Move, Position.id == Move.from_position_id)
                self.priority_cache = {(fen, uci): prio for fen, uci, prio in q.all()}
            except Exception as e:
                logger.error(f"Error loading priority cache: {e}")
                self.priority_cache = {}

    def check_if_alternative_good_move(self, move_obj, played_uci):
        return bool(self.get_alternative_move_type(move_obj, played_uci))

    def get_alternative_move_type(self, move_obj, played_uci):
        if not self.repo_session: return None
        
        # 1. Check if the move is active in the repertoire (only select the ID to keep it light)
        exists = self.repo_session.query(RepertoireMove.id).join(Move).filter(
            Move.from_position_id == move_obj.from_position_id,
            Move.uci == played_uci,
            RepertoireMove.is_active == True
        ).first() is not None
        
        if exists:
            return 'repertoire'
            
        # 2. Check if it is a good move (only select the good_moves column to keep it light)
        good_moves_json = self.repo_session.query(Position.good_moves).filter(
            Position.id == move_obj.from_position_id
        ).scalar()
        
        if good_moves_json:
            try:
                good_list = json.loads(good_moves_json)
                if played_uci in good_list:
                    return 'good'
            except Exception as e:
                logger.debug(f"Error parsing good_moves in get_alternative_move_type: {e}")
                
        return None
