import collections
from typing import Set, Dict, List, Tuple, Optional
from collections import deque
from sqlalchemy import or_
from opening_fenix.core.db.models import Position

class RepertoireNavigator:
    """
    Handles complex BFS traversal logic for repertoire variations and reachable moves.
    Extracted from TrainingManager to improve maintainability.
    """
    def __init__(self, repertoire_manager):
        self.repertoire_manager = repertoire_manager

    def build_variation_move_set(self, variation_name: str, cache_data: Dict) -> Set[int]:
        """
        Calculates all Move IDs belonging to a variation using cached moves.
        """
        variation_move_ids = set()
        if not variation_name or not self.repertoire_manager.repo_session:
            return variation_move_ids

        pos_cache = cache_data['pos_cache']
        forward_moves_cache = cache_data['forward_moves_cache']
        move_parent_cache = cache_data['move_parent_cache']

        # 1. Find all positions explicitly named (V1, V2, or V3)
        roots = self.repertoire_manager.repo_session.query(Position.id).filter(
            or_(
                Position.variation_1 == variation_name, 
                Position.variation_2 == variation_name,
                Position.variation_3 == variation_name
            )
        ).all()
        root_ids = {r.id for r in roots}

        # 2. Find all lead-up moves (to reach the variation)
        queue = deque(root_ids)
        visited_leadup = set(root_ids)
        while queue:
            curr_id = queue.popleft()
            parents = move_parent_cache.get(curr_id, [])
            if parents:
                m = parents[0]
                variation_move_ids.add(m.id)
                if m.from_position_id not in visited_leadup:
                    visited_leadup.add(m.from_position_id)
                    queue.append(m.from_position_id)

        # 3. Find all descendant moves (inside the variation)
        queue = deque()
        visited_descendants = set()

        for rid in root_ids:
            p = pos_cache.get(rid)
            if not p: continue
            
            f = {1: None, 2: None, 3: None}
            if p.variation_1 == variation_name: f[1] = variation_name
            if p.variation_2 == variation_name: f[2] = variation_name
            if p.variation_3 == variation_name: f[3] = variation_name
            
            if f[2] or f[3]: f[1] = p.variation_1 or p.cached_v1
            if f[3]: f[2] = p.variation_2 or p.cached_v2
            
            f_tuple = (f[1], f[2], f[3])
            queue.append((rid, f))
            visited_descendants.add((rid, f_tuple))

        while queue:
            curr_id, f = queue.popleft()
            children = forward_moves_cache.get(curr_id, [])
            for m in children:
                child_pos = pos_cache.get(m.to_position_id)
                if child_pos:
                    v = [child_pos.variation_1, child_pos.variation_2, child_pos.variation_3]
                    cv = [child_pos.cached_v1, child_pos.cached_v2, child_pos.cached_v3]
                    
                    pruned = False
                    for i in [1, 2, 3]:
                        f_name = f[i]
                        child_v = v[i-1]
                        child_cv = cv[i-1]
                        
                        if f_name:
                            if (child_v and child_v != f_name) or (not child_v and child_cv and child_cv != f_name):
                                pruned = True; break
                        else:
                            if child_v:
                                has_lower_filter = False
                                for j in range(i + 1, 4):
                                    if f[j]:
                                        has_lower_filter = True; break
                                if has_lower_filter:
                                    pruned = True; break
                    
                    if pruned: continue

                variation_move_ids.add(m.id)
                f_state = (f[1], f[2], f[3])
                if (m.to_position_id, f_state) not in visited_descendants:
                    visited_descendants.add((m.to_position_id, f_state))
                    queue.append((m.to_position_id, f))

        return variation_move_ids

    def calculate_reachable_moves(self, variation_filter: Optional[str], max_lvl: int, side: str, cache_data: Dict) -> List[Tuple[str, str]]:
        """Calculates all reachable moves for a given configuration."""
        pos_cache = cache_data['pos_cache']
        forward_moves_cache = cache_data['forward_moves_cache']
        move_parent_cache = cache_data['move_parent_cache']
        rep_move_cache = cache_data['rep_move_cache']
        
        valid_move_ids = self.build_variation_move_set(variation_filter, cache_data) if variation_filter else None
        reachable = []
        
        root_positions = [pos_id for pos_id in pos_cache if pos_id not in move_parent_cache]
        if not root_positions and pos_cache:
            root_positions = [min(pos_cache.keys())]

        queue = deque(root_positions)
        visited = set(root_positions)
        
        while queue:
            curr_id = queue.popleft()
            pos = pos_cache.get(curr_id)
            if not pos: continue
            
            is_player = f' {side} ' in pos.fen
            moves = forward_moves_cache.get(curr_id, [])
            
            for m in moves:
                if is_player:
                    rep = rep_move_cache.get(m.id)
                    if rep and rep.level <= max_lvl:
                        if valid_move_ids is None or m.id in valid_move_ids:
                            reachable.append((pos.fen, m.uci))
                        if m.to_position_id not in visited:
                            visited.add(m.to_position_id); queue.append(m.to_position_id)
                else:
                    if m.to_position_id not in visited:
                        visited.add(m.to_position_id); queue.append(m.to_position_id)
        return reachable
