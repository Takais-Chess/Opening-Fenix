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
from opening_fenix.core.services.navigator_service import RepertoireNavigator

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
        self.settings = { 
            "auto_delay": 200, 
            "anim_speed": 300, 
            "stop_at_variation_end": True,
            "notation_language": "en"
        }
        
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
        
        # New: Stat Caching
        self._reachable_moves_cache = None # List of (fen, uci) reachable for current repo/level
        self._last_stats_cache = None # (new, due, dist)
        
        self.navigator = RepertoireNavigator(repertoire_manager)
        
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

    def get_active_level(self, repo_name: Optional[str] = None) -> int:
        if self.profile_name == "Freies Training":
            return 999 # All levels active
            
        if not repo_name:
            repo_name = self.repertoire_manager.active_repertoire_name
            
        if not self.user_session or not repo_name: 
            return 1
            
        with self.user_session.no_autoflush:
            settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
            return settings.active_level if settings else 1

    def set_active_level(self, level_order: int, repo_name: Optional[str] = None) -> None:
        if not self.user_session: return
        if not repo_name:
            repo_name = self.repertoire_manager.active_repertoire_name
        if not repo_name: return

        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if not settings:
            settings = UserRepertoireSettings(repertoire_name=repo_name, active_level=level_order)
            self.user_session.add(settings)
        else:
            settings.active_level = level_order
        self.user_session.commit()
        # Invalidate caches
        if repo_name == self.repertoire_manager.active_repertoire_name:
            self._variation_move_ids = set()
            self._rep_move_cache = None
            self._last_stats_cache = None
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
        self._reachable_moves_cache = None
        self._last_stats_cache = None

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

        self._ensure_forward_cache()
        cache_data = {
            'pos_cache': self._pos_cache,
            'forward_moves_cache': self._forward_moves_cache,
            'move_parent_cache': self._move_parent_cache
        }
        
        self._variation_move_ids = self.navigator.build_variation_move_set(variation_name, cache_data)
        self._active_filter_name = variation_name
        return self._variation_move_ids

    def _ensure_reachable_moves_cache(self, variation_filter=None):
        """
        Calculates and caches the list of reachable moves for the current repertoire, level, and variation filter.
        Only runs BFS if the cache is empty or the configuration (level/filter/repertoire) changed.
        """
        active_level = self.get_active_level()
        cache_key = (self.repertoire_manager.active_repertoire_name, active_level, variation_filter)
        
        if getattr(self, "_reachable_moves_cache_key", None) == cache_key and self._reachable_moves_cache is not None:
            return self._reachable_moves_cache
            
        # Re-calculate
        self._reachable_moves_cache = self._calculate_reachable_moves(variation_filter)
        self._reachable_moves_cache_key = cache_key
        return self._reachable_moves_cache

    def _calculate_reachable_moves(self, variation_filter):
        """Internal BFS to find all reachable moves for a given configuration."""
        max_lvl = self.get_active_level()
        side = self.repertoire_manager.get_repertoire_color()
        self._ensure_forward_cache()
        
        cache_data = {
            'pos_cache': self._pos_cache,
            'forward_moves_cache': self._forward_moves_cache,
            'move_parent_cache': self._move_parent_cache,
            'rep_move_cache': self._rep_move_cache
        }
        
        return self.navigator.calculate_reachable_moves(variation_filter, max_lvl, side, cache_data)

    def get_stats_for_repertoire(self, repo_name: str) -> Tuple[int, int, Dict[int, int]]:
        """Fast path for checking persistent stats cache without full repertoire switch."""
        if not self.user_session: return 0, 0, {}
        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if settings and settings.last_dist_json:
            try:
                dist = json.loads(settings.last_dist_json)
                dist = {int(k): v for k, v in dist.items()}
                new_c = settings.last_new_count
                due_c = settings.last_due_count
                
                # CATCH-UP: If time has passed since the last full update, some "learned" moves
                # might have become "due". We update our counts to reflect this.
                if settings.stats_updated_at:
                    now = datetime.datetime.now()
                    lookahead = now + datetime.timedelta(minutes=5)
                    
                    # Find moves for this repertoire that are now due but weren't during the last check
                    # We query the TrainingData table directly (available in user_session)
                    newly_due = self.user_session.query(TrainingData).filter(
                        TrainingData.repertoire_name == repo_name,
                        TrainingData.next_due > settings.stats_updated_at,
                        TrainingData.next_due <= lookahead
                    ).all()
                    
                    for td in newly_due:
                        # Remove from learned distribution and add to due count
                        if td.box in dist and dist[td.box] > 0:
                            dist[td.box] -= 1
                            due_c += 1
                
                return new_c, due_c, dist
            except Exception as e:
                from opening_fenix.core.logger import logger
                logger.error(f"Error in fast-path stats catch-up: {e}")
        return 0, 0, {}

    def get_stats(self, variation_filter=None, use_cache=True):
        if not self.repertoire_manager.repo_session: return 0, 0, {}
        
        # 1. Check persistent DB cache first if no variation filter and use_cache is True
        if not variation_filter and use_cache:
            settings = self.user_session.query(UserRepertoireSettings).filter_by(
                repertoire_name=self.repertoire_manager.active_repertoire_name
            ).first()
            
            if settings and settings.last_dist_json and settings.stats_updated_at:
                # Basic check: only use if updated in the last 1 minute (for due moves)
                # This ensures "due" status is somewhat fresh.
                if (datetime.datetime.now() - settings.stats_updated_at).total_seconds() < 60:
                    try:
                        dist = json.loads(settings.last_dist_json)
                        # Box keys in JSON are strings, convert back to int
                        dist = {int(k): v for k, v in dist.items()}
                        return settings.last_new_count, settings.last_due_count, dist
                    except: pass

        # 2. Use "Smart Incremental" local cache approach
        reachable_repo_moves = self._ensure_reachable_moves_cache(variation_filter)
        
        self._ensure_td_cache()
        user_map = self._td_cache
        new_c, due_c = 0, 0
        done_dist = {i: 0 for i in range(1, 8)} 
        lookahead = datetime.datetime.now() + datetime.timedelta(minutes=5)
        
        for fen, uci in reachable_repo_moves:
            entry = user_map.get((fen, uci))
            if self.profile_name == "Freies Training":
                if not entry: due_c += 1
                else: done_dist[7] = done_dist.get(7, 0) + 1
            else:
                if not entry: new_c += 1
                elif entry.next_due <= lookahead: due_c += 1
                else: done_dist[entry.box] = done_dist.get(entry.box, 0) + 1
        
        # 3. Update persistent cache if no filter
        if not variation_filter:
            self._update_persistent_stats_cache(new_c, due_c, done_dist)
            
        return new_c, due_c, done_dist

    def _update_persistent_stats_cache(self, new_c, due_c, dist):
        """Saves stats to the UserRepertoireSettings table."""
        if not self.user_session or not self.repertoire_manager.active_repertoire_name: return
        try:
            settings = self.user_session.query(UserRepertoireSettings).filter_by(
                repertoire_name=self.repertoire_manager.active_repertoire_name
            ).first()
            if settings:
                settings.last_new_count = new_c
                settings.last_due_count = due_c
                settings.last_dist_json = json.dumps(dist)
                settings.stats_updated_at = datetime.datetime.now()
                self.user_session.commit()
        except Exception as e:
            logger.error(f"Error updating stats cache: {e}")
            self.user_session.rollback()

    def get_next_move(self, mode='due', last_move_obj=None, last_was_success=False, only_continuation=False, variation_filter=None, exclude_move_ids=None):
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
            
            reachable_repo_moves = self._ensure_reachable_moves_cache(variation_filter)
            reachable_keys = set(reachable_repo_moves)

            for item in due_items:
                if (item.fen, item.move_uci) not in reachable_keys: continue
                
                # O(1) move lookup via FEN+UCI index
                found_move = self._move_by_fen_uci_cache.get((item.fen, item.move_uci))
                
                if not found_move or (valid_move_ids is not None and found_move.id not in valid_move_ids): continue
                if exclude_move_ids and found_move.id in exclude_move_ids: continue
                
                rep_move = self._rep_move_cache.get(found_move.id)
                if not rep_move or rep_move.level > max_lvl: continue
                
                return self._get_ancestor(found_move, check_due=True, variation_filter=variation_filter), []

            if self.profile_name == "Freies Training":
                # In free training, we only pick moves not yet successfully trained in this session
                learned_keys = set(self._td_cache.keys())
                candidates = []
                for fen, uci in reachable_keys:
                    if (fen, uci) not in learned_keys:
                        m = self._move_by_fen_uci_cache.get((fen, uci))
                        if m:
                            if exclude_move_ids and m.id in exclude_move_ids: continue
                            candidates.append(m)
                if candidates:
                    candidates.sort(key=lambda x: x.priority_score, reverse=True)
                    return self._get_ancestor(candidates[0], check_due=False, variation_filter=variation_filter), []
                return None, [] # All moves trained

        # 3. New Mode
        elif mode == 'new':
            reachable_repo_moves = self._ensure_reachable_moves_cache(variation_filter)
            reachable_keys = set(reachable_repo_moves)
            
            if variation_filter:
                self._ensure_forward_cache()
                learned_keys = set(self._td_cache.keys())
                filter_info = self.repertoire_manager._prepare_variation_filter(variation_filter)
                lead_up_pos_ids = filter_info.get('lead_up', set())
                
                lead_up_candidates = []
                for pos_id in lead_up_pos_ids:
                    pos = self._pos_cache.get(pos_id)
                    if not pos: continue
                    
                    for m in self._forward_moves_cache.get(pos_id, []):
                        if (pos.fen, m.uci) in reachable_keys and (pos.fen, m.uci) not in learned_keys:
                            if exclude_move_ids and m.id in exclude_move_ids: continue
                            lead_up_candidates.append(m)
                
                if lead_up_candidates:
                    # Prioritize the earliest unlearned lead-up move (highest priority first)
                    lead_up_candidates.sort(key=lambda x: x.priority_score, reverse=True)
                    return self._get_ancestor(lead_up_candidates[0], check_due=False, variation_filter=None), []

            learned_keys = set(self._td_cache.keys())

            candidates = []
            for fen, uci in reachable_keys:
                if (fen, uci) not in learned_keys:
                    m = self._move_by_fen_uci_cache.get((fen, uci))
                    if m:
                        if exclude_move_ids and m.id in exclude_move_ids: continue
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
            # 1. Stop if the CURRENT move already starts at the variation boundary
            if target_entry_fen:
                pos = self._pos_cache.get(curr_move.from_position_id)
                if pos and clean_fen(pos.fen) == target_entry_fen:
                    break

            # 2. Look at the parent move (usually an opponent move)
            parents = self._move_parent_cache.get(curr_move.from_position_id, [])
            if not parents: break
            parent_move = parents[0]
            
            # 3. If the PARENT move starts at the boundary, we must stop here!
            if target_entry_fen:
                pos = self._pos_cache.get(parent_move.from_position_id)
                if pos and clean_fen(pos.fen) == target_entry_fen:
                    break

            # 4. Look at the grandparent move (usually the previous player move)
            grandparents = self._move_parent_cache.get(parent_move.from_position_id, [])
            if not grandparents: break
            grandparent_move = grandparents[0]
            
            # 5. Check library status
            gp_pos = self._pos_cache.get(grandparent_move.from_position_id)
            if not gp_pos: break
            key = (gp_pos.fen, grandparent_move.uci)
            if check_due:
                p_data = self._td_cache.get(key)
                if p_data and p_data.next_due <= datetime.datetime.now(): 
                    curr_move = grandparent_move
                    continue
            else:
                is_learned = key in self._td_cache
                if not is_learned: 
                    curr_move = grandparent_move
                    continue
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
            pos = self._pos_cache.get(move.from_position_id)
            if not pos: return
            fen = pos.fen
            
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
        
        pos = self._pos_cache.get(move.from_position_id)
        if not pos: return
        fen = pos.fen
        
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

        # New: Trigger immediate (smart) cache update for the current repertoire
        self.get_stats(use_cache=False) 

    def is_move_new(self, move_id):
        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        # O(1) move lookup via ID index
        move = self._move_by_id_cache.get(move_id)
            
        if not move: return False
        
        pos = self._pos_cache.get(move.from_position_id)
        if not pos: return False
        fen = pos.fen
        return (fen, move.uci) not in self._td_cache
    
    def get_box_distribution(self):
        dist = {i: 0 for i in range(8)}
        with self.user_session.no_autoflush:
            from sqlalchemy import func
            results = self.user_session.query(TrainingData.box, func.count(TrainingData.id))\
                .filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name)\
                .group_by(TrainingData.box).all()
            for box, count in results:
                if box in dist:
                    dist[box] = count
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
