import os
import datetime
import random
import json
from collections import deque
from typing import List, Dict, Tuple, Any, Optional, Set
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, TrainingData, UserBase, UserRepertoireSettings
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.data_tools import get_user_dir

BOX_INTERVALS = {
    1: datetime.timedelta(minutes=5),
    2: datetime.timedelta(days=1),
    3: datetime.timedelta(days=3),
    4: datetime.timedelta(days=9),
    5: datetime.timedelta(days=21),
    6: datetime.timedelta(days=63),
    7: datetime.timedelta(days=180)
}

class TrainingManager:
    def __init__(self, profile_name: str, repertoire_manager: Any) -> None:
        self.profile_name = profile_name
        self.repertoire_manager = repertoire_manager
        
        self.user_db = None
        self.user_session = None
        self.settings = { "auto_delay": 200, "anim_speed": 300, "stop_at_variation_end": False }
        
        # Optimization Caches
        self._variation_move_ids = set()
        self._active_filter_name = None
        self._forward_moves_cache = None
        self._rep_move_cache = None
        self._pos_cache = None
        self._td_cache = None
        
        # O(1) index caches for hot-path lookups
        self._move_by_id_cache: Optional[Dict[int, Move]] = None
        self._move_by_fen_uci_cache: Optional[Dict[Tuple[str, str], Move]] = None
        
        self.init_user_db()
        self.load_settings()

    def init_user_db(self) -> None:
        if self.profile_name == "Freies Training":
            # Use in-memory DB for free training to avoid saving progress
            # DatabaseManager constructor already calls create_all()
            self.user_db = DatabaseManager(":memory:", base=UserBase)
            self.user_session = self.user_db.get_session()
            return

        profiles_dir = os.path.join(get_user_dir(), "profiles")
        if not os.path.exists(profiles_dir):
            os.makedirs(profiles_dir)
            
        db_path = os.path.join(profiles_dir, f"{self.profile_name}.db")
        self.user_db = DatabaseManager(db_path, base=UserBase)
        self.user_session = self.user_db.get_session()

    def load_settings(self) -> None:
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        settings_path = os.path.join(profiles_dir, f"{self.profile_name}_settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    self.settings.update(json.load(f))
            except: pass

    def save_settings(self) -> None:
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        settings_path = os.path.join(profiles_dir, f"{self.profile_name}_settings.json")
        with open(settings_path, "w") as f:
            json.dump(self.settings, f, indent=4)

    def get_setting(self, key: str) -> Any:
        return self.settings.get(key)

    def set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save_settings()

    def get_visible_repos(self) -> List[str]:
        if self.profile_name == "Freies Training":
            # All repertoires are visible in free training
            return self.repertoire_manager.get_all_repertoires()
            
        if not self.user_session: return []
        settings = self.user_session.query(UserRepertoireSettings).all()
        return [s.repertoire_name for s in settings]

    def set_repo_visibility(self, repo_name: str, is_visible: bool) -> None:
        if not self.user_session: return
        existing = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if is_visible:
            if not existing:
                new_setting = UserRepertoireSettings(repertoire_name=repo_name, active_level=1)
                self.user_session.add(new_setting)
        else:
            if existing:
                self.user_session.delete(existing)
        self.user_session.commit()

    def is_repo_visible(self, repo_name: str) -> bool:
        if not self.user_session: return False
        return self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).count() > 0

    def get_active_level(self) -> int:
        if self.profile_name == "Freies Training":
            return 999 # All levels active
            
        if not self.user_session or not self.repertoire_manager.active_repertoire_name: return 1
        with self.user_session.no_autoflush:
            settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).first()
            return settings.active_level if settings else 1

    def set_active_level(self, level_order: int) -> None:
        if not self.user_session or not self.repertoire_manager.active_repertoire_name: return
        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).first()
        if not settings:
            settings = UserRepertoireSettings(repertoire_name=self.repertoire_manager.active_repertoire_name, active_level=level_order)
            self.user_session.add(settings)
        else:
            settings.active_level = level_order
        self.user_session.commit()
        # Invalidate caches
        self._td_cache = None
        
    def close(self) -> None:
        if self.user_session:
            self.user_session.close()
            self.user_session = None
        if self.user_db:
            self.user_db.close()
            self.user_db = None

    def on_repertoire_changed(self):
        """Called when switching repertoires to ensure no data leaks between them."""
        self._variation_move_ids = set()
        self._active_filter_name = None
        self._forward_moves_cache = None
        self._rep_move_cache = None
        self._pos_cache = None
        self._td_cache = None
        self._move_by_id_cache = None
        self._move_by_fen_uci_cache = None

    def reset_repertoire_progress(self) -> Tuple[bool, str]:
        if not self.repertoire_manager.active_repertoire_name: return False, "Kein Repertoire aktiv."
        try:
            num_deleted = self.user_session.query(TrainingData).filter(TrainingData.repertoire_name == self.repertoire_manager.active_repertoire_name).delete(synchronize_session=False)
            self.user_session.commit()
            # Invalidate caches
            self._td_cache = None
            return True, f"{num_deleted} Fortschritts-Einträge zurückgesetzt."
        except Exception as e:
            self.user_session.rollback()
            return False, f"Fehler: {e}"

    def rename_repertoire_in_user_data(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        """
        Updates the repertoire name in TrainingData and UserRepertoireSettings
        when a repertoire is renamed.
        """
        if not self.user_session: return False, "No user session."
        try:
            # Update TrainingData
            self.user_session.query(TrainingData).filter(
                TrainingData.repertoire_name == old_name
            ).update({TrainingData.repertoire_name: new_name}, synchronize_session=False)

            # Update UserRepertoireSettings
            settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=old_name).first()
            if settings:
                existing_new = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=new_name).first()
                if existing_new:
                    self.user_session.delete(settings)
                else:
                    new_settings = UserRepertoireSettings(repertoire_name=new_name, active_level=settings.active_level)
                    self.user_session.add(new_settings)
                    self.user_session.delete(settings)

            self.user_session.commit()
            self._td_cache = None
            return True, "User data updated."
        except Exception as e:
            self.user_session.rollback()
            return False, f"Error updating user data: {e}"

    def _ensure_forward_cache(self):
        if self._forward_moves_cache is not None:
            return
            
        if not self.repertoire_manager.repo_session:
            return
            
        self._forward_moves_cache = {}
        self._pos_cache = {}
        self._move_by_id_cache = {}
        self._move_by_fen_uci_cache = {}
        self._move_parent_cache = {} # Local parent cache for training algorithms
        
        # Load all positions to memory
        for p in self.repertoire_manager.repo_session.query(Position).all():
            self._pos_cache[p.id] = p
            
        # Get all moves via public API
        all_moves = self.repertoire_manager.core.get_all_moves()
            
        for m in all_moves:
            # Build Forward Cache
            if m.from_position_id not in self._forward_moves_cache:
                self._forward_moves_cache[m.from_position_id] = []
            self._forward_moves_cache[m.from_position_id].append(m)
            
            # Build Parent Cache
            if m.to_position_id not in self._move_parent_cache:
                self._move_parent_cache[m.to_position_id] = []
            self._move_parent_cache[m.to_position_id].append(m)
            
            # Build O(1) index caches
            self._move_by_id_cache[m.id] = m
            if m.from_position_id in self._pos_cache:
                pos_fen = self._pos_cache[m.from_position_id].fen
                self._move_by_fen_uci_cache[(pos_fen, m.uci)] = m
                
        for k in self._forward_moves_cache:
            self._forward_moves_cache[k].sort(key=lambda m: m.priority_score, reverse=True)
            
        # Sort parent cache too for predictable ancestor selection
        for k in self._move_parent_cache:
            self._move_parent_cache[k].sort(key=lambda m: m.priority_score, reverse=True)
            
        all_rep_moves = self.repertoire_manager.core.get_all_active_repertoire_moves()
        self._rep_move_cache = {rm.move_id: rm for rm in all_rep_moves}

    def _ensure_td_cache(self):
        if self._td_cache is not None:
            return
            
        self._td_cache = {}
        tds = self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).all()
        for td in tds:
            self._td_cache[(td.fen, td.move_uci)] = td

    def _build_variation_move_set(self, variation_name):
        """
        Optimized: Pre-calculates all Move IDs belonging to a variation using cached moves.
        """
        if self._active_filter_name == variation_name and self._variation_move_ids:
            return self._variation_move_ids

        self._variation_move_ids = set()
        self._active_filter_name = variation_name
        if not variation_name or not self.repertoire_manager.repo_session:
            return self._variation_move_ids

        self._ensure_forward_cache()

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
        # RESTRICTED: Only follow the most played (highest priority) path back.
        queue = deque(root_ids)
        visited = set(root_ids)
        while queue:
            curr_id = queue.popleft()
            parents = self._move_parent_cache.get(curr_id, [])
            if parents:
                # Take only the first (best) parent move
                m = parents[0]
                self._variation_move_ids.add(m.id)
                if m.from_position_id not in visited:
                    visited.add(m.from_position_id)
                    queue.append(m.from_position_id)

        # 3. Find all descendant moves (inside the variation)
        # We run a BFS with root-specific context to ensure that filtering a lower level 
        # (e.g., V2) doesn't pollute the context of a higher level filter (e.g., V1).
        queue = deque()
        # visited: (position_id, (filter_v1, filter_v2, filter_v3))
        visited = set()

        for rid in root_ids:
            p = self._pos_cache.get(rid)
            if not p: continue
            
            # Determine the filter context for this root
            f = {1: None, 2: None, 3: None}
            if p.variation_1 == variation_name: f[1] = variation_name
            if p.variation_2 == variation_name: f[2] = variation_name
            if p.variation_3 == variation_name: f[3] = variation_name
            
            # Anchor parents: if filtering for V2, also lock the V1 parent opening.
            if f[2] or f[3]: f[1] = p.variation_1 or p.cached_v1
            if f[3]: f[2] = p.variation_2 or p.cached_v2
            
            f_tuple = (f[1], f[2], f[3])
            queue.append((rid, f))
            visited.add((rid, f_tuple))

        while queue:
            curr_id, f = queue.popleft()
            children = self._forward_moves_cache.get(curr_id, [])
            for m in children:
                child_pos = self._pos_cache.get(m.to_position_id)
                if child_pos:
                    v = [child_pos.variation_1, child_pos.variation_2, child_pos.variation_3]
                    cv = [child_pos.cached_v1, child_pos.cached_v2, child_pos.cached_v3]
                    
                    pruned = False
                    for i in [1, 2, 3]:
                        f_name = f[i]
                        child_v = v[i-1]
                        child_cv = cv[i-1]
                        
                        if f_name:
                            # Prune if the level we are filtering for changes to a DIFFERENT name.
                            if (child_v and child_v != f_name) or (not child_v and child_cv and child_cv != f_name):
                                pruned = True; break
                        else:
                            # If this level has no filter, we only prune if an EXPLICIT name appears 
                            # that belongs to a level HIGHER than our finest current filter.
                            # Example: Filtering for V2, but child suddenly has a new V1.
                            if child_v:
                                has_lower_filter = False
                                for j in range(i + 1, 4):
                                    if f[j]:
                                        has_lower_filter = True; break
                                if has_lower_filter:
                                    pruned = True; break
                    
                    if pruned: continue

                self._variation_move_ids.add(m.id)
                f_state = (f[1], f[2], f[3])
                if (m.to_position_id, f_state) not in visited:
                    visited.add((m.to_position_id, f_state))
                    queue.append((m.to_position_id, f))

        return self._variation_move_ids

    def get_stats(self, variation_filter=None):
        if not self.repertoire_manager.repo_session: return 0, 0, {}
        max_lvl = self.get_active_level()
        side = self.repertoire_manager.get_repertoire_color()
        
        self._ensure_forward_cache()
        self._ensure_td_cache()
        valid_move_ids = self._build_variation_move_set(variation_filter) if variation_filter else None

        # Reachability Analysis: find all active player-turn repertoire moves that are reachable from the root
        # and not blocked by any inactive/out-of-repertoire player-side move.
        reachable_repo_moves = []
        
        # Start from positions with no parents (usually the initial position)
        root_positions = [pos_id for pos_id in self._pos_cache if pos_id not in self._move_parent_cache]
        if not root_positions and self._pos_cache:
            # Fallback for very complex transpositions that might create a loop at the very top (unlikely)
            root_positions = [min(self._pos_cache.keys())]

        queue = deque(root_positions)
        visited = set(root_positions)
        
        while queue:
            curr_id = queue.popleft()
            pos = self._pos_cache.get(curr_id)
            if not pos: continue
            
            is_player = f' {side} ' in pos.fen
            moves = self._forward_moves_cache.get(curr_id, [])
            
            for m in moves:
                if is_player:
                    rep = self._rep_move_cache.get(m.id)
                    if rep and rep.level <= max_lvl:
                        # Found a valid player-turn move in the active repertoire
                        if valid_move_ids is None or m.id in valid_move_ids:
                            reachable_repo_moves.append((pos.fen, m.uci))
                        
                        # Only follow if this branch is active
                        if m.to_position_id not in visited:
                            visited.add(m.to_position_id); queue.append(m.to_position_id)
                else:
                    # Always follow opponent moves to find more player moves
                    if m.to_position_id not in visited:
                        visited.add(m.to_position_id); queue.append(m.to_position_id)
        
        user_map = self._td_cache
        new_c, due_c = 0, 0
        done_dist = {i: 0 for i in range(1, 8)} 
        lookahead = datetime.datetime.now() + datetime.timedelta(minutes=5)
        
        for fen, uci in reachable_repo_moves:
            entry = user_map.get((fen, uci))
            if self.profile_name == "Freies Training":
                if not entry: due_c += 1 # Moves not yet trained successfully are due
                else: done_dist[7] = done_dist.get(7, 0) + 1 # Use box 7 to show progress
            else:
                if not entry: new_c += 1
                elif entry.next_due <= lookahead: due_c += 1
                else: done_dist[entry.box] = done_dist.get(entry.box, 0) + 1
        return new_c, due_c, done_dist

    def get_next_move(self, mode='due', last_move_obj=None, last_was_success=False, only_continuation=False, variation_filter=None):
        if not self.repertoire_manager.repo_session: return None, []
        self.repertoire_manager._ensure_priority_cache()
        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        max_lvl = self.get_active_level()
        side = self.repertoire_manager.get_repertoire_color()
        lookahead = datetime.datetime.now() + datetime.timedelta(minutes=5)
        
        valid_move_ids = self._build_variation_move_set(variation_filter) if variation_filter else None

        # 1. Continuation Flow
        if last_move_obj and last_was_success:
            downstream_move, path = self._find_downstream_due_move(last_move_obj.to_position_id, mode, variation_filter=variation_filter)
            if downstream_move: return downstream_move, path
        if only_continuation: return None, []

        # 2. Due Mode
        if mode == 'due':
            due_items = list(self._td_cache.values())
            due_items = [td for td in due_items if td.next_due <= lookahead]
            
            # IMPROVEMENT: Use the actual priority from the cache to sort due items.
            due_items.sort(key=lambda x: (x.box, -self.repertoire_manager.priority_cache.get((x.fen, x.move_uci), 0.0)))
            
            for item in due_items:
                # O(1) move lookup via FEN+UCI index
                found_move = self._move_by_fen_uci_cache.get((item.fen, item.move_uci))
                
                if not found_move or (valid_move_ids is not None and found_move.id not in valid_move_ids): continue
                
                rep_move = self._rep_move_cache.get(found_move.id)
                if not rep_move or rep_move.level > max_lvl: continue
                
                return self._get_ancestor(found_move, check_due=True, variation_filter=variation_filter), []

            if self.profile_name == "Freies Training":
                # In free training, we only pick moves not yet successfully trained in this session
                learned_keys = set(self._td_cache.keys())
                candidates = []
                for from_pos_id, m_list in self._forward_moves_cache.items():
                    pos_fen = self._pos_cache[from_pos_id].fen
                    if f' {side} ' not in pos_fen: continue
                    for m in m_list:
                        rep_move = self._rep_move_cache.get(m.id)
                        if not rep_move or rep_move.level > max_lvl: continue
                        if (pos_fen, m.uci) not in learned_keys:
                            if valid_move_ids is not None and m.id not in valid_move_ids: continue
                            candidates.append(m)
                if candidates:
                    candidates.sort(key=lambda x: x.priority_score, reverse=True)
                    return self._get_ancestor(candidates[0], check_due=False, variation_filter=variation_filter), []
                return None, [] # All moves trained

        # 3. New Mode
        elif mode == 'new':
            learned_keys = set(self._td_cache.keys())

            candidates = []
            for from_pos_id, m_list in self._forward_moves_cache.items():
                pos_fen = self._pos_cache[from_pos_id].fen
                if f' {side} ' not in pos_fen: continue
                
                for m in m_list:
                    rep_move = self._rep_move_cache.get(m.id)
                    if not rep_move or rep_move.level > max_lvl: continue
                    
                    if (pos_fen, m.uci) not in learned_keys:
                        if valid_move_ids is not None and m.id not in valid_move_ids: continue
                        candidates.append(m)
            
            if candidates:
                # Sort by priority score DESCENDING (highest first)
                candidates.sort(key=lambda x: x.priority_score, reverse=True)
                top_prio = candidates[0].priority_score
                # Pick among those that share the absolute highest priority score
                best = [m for m in candidates if m.priority_score == top_prio]
                return self._get_ancestor(random.choice(best), check_due=False, variation_filter=variation_filter), []
        
        return None, []

    def _get_ancestor(self, move_obj, check_due=False, variation_filter=None):
        """Iterative ancestor search to find the entry point of a sequence."""
        curr_move = move_obj
        self._ensure_forward_cache()
        self._ensure_td_cache()
            
        # If filtering, find the entry point FEN for the variation
        entry_fen = None
        if variation_filter:
            entry_fen = self.repertoire_manager.get_variation_entry_point_fen(variation_filter)
            
        def clean_fen(f): return " ".join(f.split(" ")[:4])
        target_entry_fen = clean_fen(entry_fen) if entry_fen else None

        for _ in range(50): # Safety limit
            # Stop if we are already at the variation entry point
            if target_entry_fen:
                curr_fen = clean_fen(self._pos_cache[curr_move.from_position_id].fen)
                if curr_fen == target_entry_fen:
                    break

            # Parent cache is pre-sorted by priority_score descending
            parents = self._move_parent_cache.get(curr_move.from_position_id, [])
            if not parents: break
            parent_move = parents[0]
            
            # Check if parent_move is at the boundary
            if target_entry_fen:
                parent_fen = clean_fen(self._pos_cache[parent_move.from_position_id].fen)
                if parent_fen == target_entry_fen:
                    break

            grandparents = self._move_parent_cache.get(parent_move.from_position_id, [])
            if not grandparents: break
            grandparent_move = grandparents[0]
            
            key = (self._pos_cache[grandparent_move.from_position_id].fen, grandparent_move.uci)
            if check_due:
                p_data = self._td_cache.get(key)
                if p_data and p_data.next_due <= datetime.datetime.now(): curr_move = grandparent_move; continue
            else:
                is_learned = key in self._td_cache
                if not is_learned: curr_move = grandparent_move; continue
            break
        return curr_move

    def _find_downstream_due_move(self, start_pos_id, mode, variation_filter=None):
        queue = deque([(start_pos_id, 0, [])])
        visited = {start_pos_id}
        lookahead = datetime.datetime.now() + datetime.timedelta(minutes=5)
        max_lvl = self.get_active_level()
        side = self.repertoire_manager.get_repertoire_color()
        valid_move_ids = self._build_variation_move_set(variation_filter) if variation_filter else None
        
        self._ensure_forward_cache()
        self._ensure_td_cache()

        while queue:
            curr_id, depth, path = queue.popleft()
            if depth >= 30: continue
            
            pos = self._pos_cache.get(curr_id)
            if not pos: continue
            
            is_player = f' {side} ' in pos.fen
            moves = self._forward_moves_cache.get(curr_id, [])
            
            # Moves are already sorted by priority in _forward_moves_cache

            for m in moves:
                if is_player:
                    rep = self._rep_move_cache.get(m.id)
                    if rep and rep.level <= max_lvl:
                        if valid_move_ids is not None and m.id not in valid_move_ids: continue
                        
                        td = self._td_cache.get((pos.fen, m.uci))
                        if (mode == 'due' and td and td.next_due <= lookahead) or (mode == 'new' and not td):
                            return m, path
                        
                        # Only follow player moves that ARE in the active repertoire
                        if m.to_position_id not in visited:
                            visited.add(m.to_position_id); queue.append((m.to_position_id, depth + 1, path + [m.san]))
                else:
                    # Always follow opponent moves
                    if m.to_position_id not in visited:
                        visited.add(m.to_position_id); queue.append((m.to_position_id, depth + 1, path + [m.san]))
        return None, []

    def _get_rating_settings(self):
        repo_name = self.repertoire_manager.active_repertoire_name
        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if not settings:
            settings = UserRepertoireSettings(repertoire_name=repo_name, rating=800.0, last_rating_update=datetime.datetime.now())
            self.user_session.add(settings)
            self.user_session.commit()
        return settings

    def _apply_rating_decay(self, settings):
        if not settings.last_rating_update:
            settings.last_rating_update = datetime.datetime.now()
            return
        
        now = datetime.datetime.now()
        days_passed = (now - settings.last_rating_update).total_seconds() / 86400.0
        if days_passed < 0.1: # Only decay if at least 2.4 hours passed
            return
            
        # Calculate decay factor based on box distribution
        dist = self.get_box_distribution()
        total = sum(dist.values())
        if total == 0: return
        
        weighted_sum = sum(box * count for box, count in dist.items())
        avg_box = weighted_sum / total
        
        # Base decay: 2.0 points per day.
        # Adjusted by average box: (8 - avg_box) / 8.0
        decay_per_day = 2.0 * ((8.0 - avg_box) / 8.0)
        total_decay = decay_per_day * days_passed
        
        settings.rating = max(800.0, settings.rating - total_decay)
        settings.last_rating_update = now

    def update_rating(self, move_id, success):
        self._ensure_forward_cache()
        settings = self._get_rating_settings()
        self._apply_rating_decay(settings)

        rep_move = self._rep_move_cache.get(move_id)
        if not rep_move: return
        
        level_info = self.repertoire_manager.get_level_info(rep_move.level)
        target_elo = level_info.target_elo if (level_info and level_info.target_elo) else 1500
        
        # O(1) move lookup via ID index
        move = self._move_by_id_cache.get(move_id)
        
        priority = move.priority_score if move else 0.5
        priority_weight = 0.8 + (0.4 * priority)
        
        # Elo expected score for training
        # User wants E=0.95 when rating = target_elo
        # E = 1 / (1 + (1/19) * 10^((target - rating)/400))
        current_rating = settings.rating
        exponent = (target_elo - current_rating) / 400.0
        expected_score = 1.0 / (1.0 + (1.0/19.0) * (10**exponent))
        
        # K-factor. Slow rise.
        K = 15.0 * priority_weight
        
        actual_score = 1.0 if success else 0.0
        change = K * (actual_score - expected_score)
        
        settings.rating += change
        if settings.rating < 800: settings.rating = 800.0
        settings.last_rating_update = datetime.datetime.now()
        self.user_session.commit()

    def get_current_elo(self):
        with self.user_session.no_autoflush:
            self._ensure_forward_cache()
            settings = self._get_rating_settings()
            self._apply_rating_decay(settings)
            
            # Progress factor calculation
            # Fraction of seen moves in the current level(s)
            max_lvl = self.get_active_level()
            total_moves_in_level = sum(1 for m in self._rep_move_cache.values() if m.level <= max_lvl)
            if total_moves_in_level == 0: return 800
            
            # Count training data entries for these moves
            seen_moves = self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).count()
            # Note: this counts all seen moves in the repo, not just in this level.
            # But usually we train by level so it's a good approximation.
            
            progress_factor = min(1.0, seen_moves / total_moves_in_level)
            
            # Final Elo: starting 800 + (rating - 800) * progress_factor
            return int(800 + (settings.rating - 800) * progress_factor)

    def register_success(self, move_id, success):
        # In free training, if move is correct, mark it as learned for the session.
        # If move is wrong, don't create/update entry so it remains in the queue.
        if self.profile_name == "Freies Training":
            if not success: return # Keep as "due"
            
            self._ensure_forward_cache()
            self._ensure_td_cache()
            move = self._move_by_id_cache.get(move_id)
            if not move: return
            fen = self._pos_cache[move.from_position_id].fen
            
            entry = TrainingData(repertoire_name=self.repertoire_manager.active_repertoire_name, fen=fen, move_uci=move.uci, box=7, next_due=datetime.datetime.max)
            self.user_session.add(entry)
            self.user_session.commit()
            if self._td_cache is not None: self._td_cache[(fen, move.uci)] = entry
            return

        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        # O(1) move lookup via ID index
        move = self._move_by_id_cache.get(move_id)
            
        if not move: return
        
        fen = self._pos_cache[move.from_position_id].fen
        
        entry = self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name, fen=fen, move_uci=move.uci).first()
        now = datetime.datetime.now()
        if not entry:
            entry = TrainingData(repertoire_name=self.repertoire_manager.active_repertoire_name, fen=fen, move_uci=move.uci, box=0, streak=0, next_due=now)
            self.user_session.add(entry)
        if success: entry.box = min(7, entry.box + 1); entry.streak += 1
        else: entry.box = 1; entry.streak = 0
        entry.next_due = now + BOX_INTERVALS.get(entry.box, datetime.timedelta(days=1)); entry.last_review = now
        self.user_session.commit()
        
        # Update Rating
        self.update_rating(move_id, success)

        # Update cache in-place instead of full invalidation
        if self._td_cache is not None:
            self._td_cache[(fen, move.uci)] = entry

    def is_move_new(self, move_id):
        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        # O(1) move lookup via ID index
        move = self._move_by_id_cache.get(move_id)
            
        if not move: return False
        
        fen = self._pos_cache[move.from_position_id].fen
        return (fen, move.uci) not in self._td_cache
    
    def get_box_distribution(self):
        dist = {i: 0 for i in range(8)}
        with self.user_session.no_autoflush:
            for d in self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).all(): dist[d.box] = dist.get(d.box, 0) + 1
        return dist

    def get_future_reviews(self):
        timeline, now = {}, datetime.datetime.now()
        for i in range(8): timeline[(now + datetime.timedelta(days=i)).date()] = 0
        with self.user_session.no_autoflush:
            for d in self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).all():
                date = d.next_due.date()
                if date < now.date(): date = now.date()
                if date in timeline: timeline[date] += 1
        return timeline
