import chess
from collections import deque
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List, Dict, Set, Optional, Any
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.logger import logger

class TreeNavigationService:
    def __init__(self, session: Session):
        self.repo_session = session
        self._move_parent_cache = None 
        self._variation_structure_cache: Optional[Dict[str, List[str]]] = None
        self._variation_filter_cache: Dict[str, Any] = {}

    def get_history_for_move_recursive(self, move_id: int, variation_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Uses a recursive CTE to find the sequence of moves that led to this one.
        Efficiently finds ancestors without loading the entire DB.
        If variation_name is provided, it prioritizes moves belonging to that variation.
        """
        if not self.repo_session: return []

        # Optional: build the set of valid move IDs for the variation to boost them in the query
        v_ids_sql = ""
        if variation_name:
            # We use a subquery to get all move IDs belonging to the variation
            # This is slightly expensive but ensures the path stays inside the variation
            v_ids_query = text("""
                SELECT m.id FROM moves m
                JOIN positions p ON m.from_position_id = p.id
                WHERE p.variation_1 = :v OR p.variation_2 = :v OR p.variation_3 = :v
                   OR p.cached_v1 = :v OR p.cached_v2 = :v OR p.cached_v3 = :v
            """)
            try:
                v_res = self.repo_session.execute(v_ids_query, {"v": variation_name}).fetchall()
                v_ids = [r[0] for r in v_res]
                if v_ids:
                    v_ids_sql = f"CASE WHEN id IN ({','.join(map(str, v_ids))}) THEN 1 ELSE 0 END DESC,"
            except: pass

        # Recursive CTE to find all ancestor moves
        # We start from move_id and work backwards
        query = text(f"""
            WITH RECURSIVE ancestors(id, from_id, to_id, uci, san, level, nag) AS (
                SELECT id, from_position_id, to_position_id, uci, san, 0, nag
                FROM moves
                WHERE id = :move_id
                UNION ALL
                SELECT m.id, m.from_position_id, m.to_position_id, m.uci, m.san, a.level + 1, m.nag
                FROM moves m
                JOIN ancestors a ON m.to_position_id = a.from_id
                WHERE m.id = (
                    SELECT id FROM moves 
                    WHERE to_position_id = a.from_id 
                    ORDER BY {v_ids_sql} priority_score DESC 
                    LIMIT 1
                )
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
                    'nag': r.nag
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
        # Join with moves to get the max incoming priority for each position
        results = self.repo_session.query(
            Position.id, Position.variation_1, Position.variation_2, Position.variation_3,
            Position.cached_v1, Position.cached_v2,
            func.max(Move.priority_score).label('max_prio')
        ).outerjoin(
            Move, Move.to_position_id == Position.id
        ).filter(
            (Position.variation_1 != None) | 
            (Position.variation_2 != None) | 
            (Position.variation_3 != None) |
            (Position.cached_v1 != None) |
            (Position.cached_v2 != None) |
            (Position.cached_v3 != None)
        ).group_by(Position.id).all()

        structure = {} # V1 -> set(V2)
        v1_prios = {}  # V1 -> max_prio
        v2_prios = {}  # (V1, V2) -> max_prio

        for pos_id, v1, v2, v3, cv1, cv2, prio in results:
            prio = prio if prio is not None else 0.0

            # Use cached inheritance if variation tags are missing on the position itself
            if not v1: v1 = cv1
            if not v2: v2 = cv2

            # Final fallbacks for robustness
            if not v1 or (v1 and not v2 and v3): 
                if not v1:
                    v1 = self._find_ancestor_variation(pos_id, 1)
                if not v2:
                    v2 = self._find_ancestor_variation(pos_id, 2)
                
            if not v1: v1 = "Sonstiges"
            
            v1_prios[v1] = max(v1_prios.get(v1, 0.0), prio)
            if v1 not in structure:
                structure[v1] = set()
            
            if v2:
                structure[v1].add(v2)
                key = (v1, v2)
                v2_prios[key] = max(v2_prios.get(key, 0.0), prio)

        # Sort V1s by priority descending, but keep "Sonstiges" at the bottom
        # Use a very low priority for "Sonstiges" to push it down
        def v1_sort_key(name):
            if name == "Sonstiges": return -1.0
            return v1_prios.get(name, 0.0)

        sorted_v1s = sorted(structure.keys(), key=v1_sort_key, reverse=True)
        
        # Build final result with sorted V2s
        res = {}
        for v1 in sorted_v1s:
            v2s = list(structure[v1])
            # Sort V2s by their priority within this V1, also putting "Sonstiges" children at the bottom if any
            sorted_v2s = sorted(v2s, key=lambda v2: (-1.0 if v2 == "Sonstiges" else v2_prios.get((v1, v2), 0.0)), reverse=True)
            res[v1] = sorted_v2s

        self._variation_structure_cache = res
        return res

    def _find_ancestor_variation(self, pos_id: int, level: int) -> Optional[str]:
        """Helper to find the nearest ancestor variation name if not present on current position."""
        col = "variation_1" if level == 1 else "variation_2"
        query = text(f"""
            WITH RECURSIVE ancestors(from_id) AS (
                SELECT from_position_id FROM moves WHERE to_position_id = :pos_id
                UNION ALL
                SELECT m.from_position_id FROM moves m JOIN ancestors a ON m.to_position_id = a.from_id
                LIMIT 100
            )
            SELECT p.{col} FROM ancestors a JOIN positions p ON a.from_id = p.id WHERE p.{col} IS NOT NULL LIMIT 1
        """)
        row = self.repo_session.execute(query, {"pos_id": pos_id}).fetchone()
        return row[0] if row else None

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

    def get_variation_entry_point_fen(self, variation_name: str) -> Optional[str]:
        """
        Finds the FEN of the earliest position (shortest path from root) tagged with this variation.
        """
        if not self.repo_session: return None
        
        # 1. Find all positions explicitly tagged
        roots = self.repo_session.query(Position.id, Position.fen).filter(
            (Position.variation_1 == variation_name) | 
            (Position.variation_2 == variation_name) |
            (Position.variation_3 == variation_name)
        ).all()
        
        if not roots:
            return None
            
        if len(roots) == 1:
            return roots[0].fen

        # 2. If multiple, find the one with shortest path from the absolute starting position
        root_pos_ids = [r.id for r in roots]
        
        # We start from known starting positions (no incoming moves)
        start_positions = self.repo_session.query(Position.id).filter(
            ~Position.id.in_(self.repo_session.query(Move.to_position_id))
        ).all()
        start_ids = [s.id for s in start_positions]
        if not start_ids: 
             # Fallback: take the position with the lowest ID (usually initial)
             first_pos = self.repo_session.query(Position.id).order_by(Position.id).first()
             if first_pos: start_ids = [first_pos.id]
             else: return None

        queue = deque([(sid, 0) for sid in start_ids])
        visited = set(start_ids)
        
        while queue:
            curr_id, depth = queue.popleft()
            
            # Check if this is one of our target roots
            for r in roots:
                if r.id == curr_id:
                    return r.fen
            
            if depth > 100: continue # Safety limit
            
            # Find children moves
            children = self.repo_session.query(Move.to_position_id).filter_by(from_position_id=curr_id).all()
            for c in children:
                if c[0] not in visited:
                    visited.add(c[0])
                    queue.append((c[0], depth + 1))
                    
        # Fallback: just return the first one found if BFS failed
        return roots[0].fen
