import chess
from collections import deque
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Set, Optional, Any
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.logger import logger

class TreeNavigationService:
    def __init__(self, session: Session):
        self.repo_session = session
        self._move_parent_cache = None 
        self._variation_structure_cache = None
        self._variation_filter_cache = {}

    def get_history_for_move_recursive(self, move_id: int) -> List[Dict[str, Any]]:
        """
        Uses a recursive CTE to find the sequence of moves that led to this one.
        Efficiently finds ancestors without loading the entire DB.
        """
        if not self.repo_session: return []

        # Recursive CTE to find all ancestor moves
        # We start from move_id and work backwards
        query = text("""
            WITH RECURSIVE ancestors(id, from_id, to_id, uci, san, level) AS (
                SELECT id, from_position_id, to_position_id, uci, san, 0
                FROM moves
                WHERE id = :move_id
                UNION ALL
                SELECT m.id, m.from_position_id, m.to_position_id, m.uci, m.san, a.level + 1
                FROM moves m
                JOIN ancestors a ON m.to_position_id = a.from_id
                WHERE m.id = (SELECT id FROM moves WHERE to_position_id = a.from_id ORDER BY priority_score DESC LIMIT 1)
                LIMIT 50 -- Safety limit for depth
            )
            SELECT a.*, p.fen, p.comment
            FROM ancestors a
            JOIN positions p ON a.to_id = p.id
            ORDER BY a.level DESC
        """)
        
        try:
            results = self.repo_session.execute(query, {"move_id": move_id}).fetchall()
            history = []
            for r in results:
                history.append({
                    'san': r.san, 
                    'uci': r.uci, 
                    'fen': r.fen, 
                    'comment': r.comment,
                    'nag': 0 # Default if not in CTE but can be added
                })
            return history
        except Exception as e:
            logger.error(f"Error fetching history with recursive CTE: {e}")
            return []

    def get_absolute_ancestor_fen(self, move_id: int) -> Optional[str]:
        """Finds the root-most FEN for a given move."""
        query = text("""
            WITH RECURSIVE ancestors(from_id, level) AS (
                SELECT from_position_id, 0
                FROM moves
                WHERE id = :move_id
                UNION ALL
                SELECT m.from_position_id, a.level + 1
                FROM moves m
                JOIN ancestors a ON m.to_position_id = a.from_id
                WHERE m.id = (SELECT id FROM moves WHERE to_position_id = a.from_id ORDER BY priority_score DESC LIMIT 1)
                LIMIT 50
            )
            SELECT p.fen
            FROM ancestors a
            JOIN positions p ON a.from_id = p.id
            ORDER BY a.level DESC
            LIMIT 1
        """)
        try:
            result = self.repo_session.execute(query, {"move_id": move_id}).fetchone()
            if result:
                # EPD to FEN for full color/castling info if possible
                board = chess.Board()
                board.set_epd(result.fen)
                return board.fen()
            return None
        except Exception as e:
            logger.error(f"Error finding absolute ancestor: {e}")
            return None

    def get_variation_roots(self, variation_name: str) -> Set[int]:
        if not self.repo_session: return set()
        roots = self.repo_session.query(Position.id).filter(
            (Position.variation_1 == variation_name) | (Position.variation_2 == variation_name)
        ).all()
        return {r.id for r in roots}

    def get_variation_structure(self) -> Dict[str, List[str]]:
        """
        Scans all positions to build a hierarchy of variations (V1 -> [V2, V2, ...]).
        Handles inheritance: If a position has V2 but no V1, it inherits V1 from its ancestors.
        """
        if not self.repo_session: return {}
        if self._variation_structure_cache is not None:
            return self._variation_structure_cache
        
        # 1. Fetch all positions that have ANY variation tag
        tagged_positions = self.repo_session.query(
            Position.id, Position.variation_1, Position.variation_2, Position.variation_3
        ).filter(
            (Position.variation_1 != None) | 
            (Position.variation_2 != None) | 
            (Position.variation_3 != None)
        ).all()
        
        structure = {}
        
        for pos_id, v1, v2, v3 in tagged_positions:
            # If inheritance is needed (missing v1 or v2)
            if not v1 or (v1 and not v2 and v3): 
                # Walk up to find the missing levels
                ancestors = self.get_history_for_move_recursive(self.repo_session.query(Move.id).filter_by(to_position_id=pos_id).first()[0] if self.repo_session.query(Move.id).filter_by(to_position_id=pos_id).first() else None)
                # Note: get_history_for_move_recursive doesn't return variation tags. 
                # We need to query them.
                
                if not v1:
                    # Find first ancestor with v1
                    query = text("""
                        WITH RECURSIVE ancestors(from_id) AS (
                            SELECT from_position_id FROM moves WHERE to_position_id = :pos_id
                            UNION ALL
                            SELECT m.from_position_id FROM moves m JOIN ancestors a ON m.to_position_id = a.from_id
                            LIMIT 100
                        )
                        SELECT p.variation_1 FROM ancestors a JOIN positions p ON a.from_id = p.id WHERE p.variation_1 IS NOT NULL LIMIT 1
                    """)
                    row = self.repo_session.execute(query, {"pos_id": pos_id}).fetchone()
                    if row: v1 = row[0]
                
                if not v2:
                    # Find first ancestor with v2
                    query = text("""
                        WITH RECURSIVE ancestors(from_id) AS (
                            SELECT from_position_id FROM moves WHERE to_position_id = :pos_id
                            UNION ALL
                            SELECT m.from_position_id FROM moves m JOIN ancestors a ON m.to_position_id = a.from_id
                            LIMIT 100
                        )
                        SELECT p.variation_2 FROM ancestors a JOIN positions p ON a.from_id = p.id WHERE p.variation_2 IS NOT NULL LIMIT 1
                    """)
                    row = self.repo_session.execute(query, {"pos_id": pos_id}).fetchone()
                    if row: v2 = row[0]

            if not v1: v1 = "Sonstiges"
            if v1 not in structure: structure[v1] = set()
            if v2: structure[v1].add(v2)
        
        # Convert sets to sorted lists for the UI menu
        res = {k: sorted(list(v)) for k, v in structure.items()}
        self._variation_structure_cache = res
        return res

    def get_variation_filter_info(self, variation_name: str) -> Dict[str, Set[int]]:
        """
        Returns info needed for variation filtering:
        - roots: IDs of positions explicitly tagged with this variation.
        - lead_up: IDs of positions on the path from starting position to these roots.
        """
        if not self.repo_session: return {"roots": set(), "lead_up": set()}
        
        if variation_name in self._variation_filter_cache:
            return self._variation_filter_cache[variation_name]
        
        # 1. Find all positions explicitly tagged
        roots = self.repo_session.query(Position.id).filter(
            (Position.variation_1 == variation_name) | 
            (Position.variation_2 == variation_name) |
            (Position.variation_3 == variation_name)
        ).all()
        root_ids = {r.id for r in roots}
        
        if not root_ids:
            return {"roots": set(), "lead_up": set()}

        # 2. Find all lead-up positions via recursive CTE
        # We find ancestors for each root until we hit the root-most position
        lead_up_ids = set()
        for rid in root_ids:
            query = text("""
                WITH RECURSIVE ancestors(from_id) AS (
                    SELECT from_position_id FROM moves WHERE to_position_id = :root_id
                    UNION ALL
                    SELECT m.from_position_id FROM moves m JOIN ancestors a ON m.to_position_id = a.from_id
                    LIMIT 100
                )
                SELECT from_id FROM ancestors
            """)
            res = self.repo_session.execute(query, {"root_id": rid}).fetchall()
            for r in res:
                lead_up_ids.add(r.from_id)

        # Remove the roots themselves from lead_up if they were included
        lead_up_ids -= root_ids
        
        res = {
            "roots": root_ids,
            "lead_up": lead_up_ids
        }
        self._variation_filter_cache[variation_name] = res
        return res
