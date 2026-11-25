import os
import datetime
import random
import json
from collections import deque, OrderedDict
from typing import List, Dict, Tuple, Any, Optional, Set
from sqlalchemy import or_, and_
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import joinedload, Session
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, TrainingData, UserBase, UserRepertoireSettings
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import is_free_training_profile, get_user_dir
from opening_fenix.core.services.navigator_service import RepertoireNavigator

@dataclass(slots=True)
class _CachedPosition:
    id: int
    fen: str
    comment: Optional[str]
    good_moves: Optional[str]
    variation_1: Optional[str]
    variation_2: Optional[str]
    variation_3: Optional[str]
    cached_v1: Optional[str]
    cached_v2: Optional[str]
    cached_v3: Optional[str]
    _good_moves_set: Optional[frozenset] = None


def _norm_fen4(fen: str) -> str:
    if not fen:
        return ""
    s = fen.strip()
    if s.count(" ") >= 5:
        return s.rsplit(" ", 2)[0]
    parts = s.split(" ")
    return " ".join(parts[:4])


@dataclass(slots=True)
class _CachedMove:
    id: int
    from_position_id: int
    to_position_id: int
    uci: str
    san: str
    priority_score: float
    nag: Optional[int]
    from_position: Optional[_CachedPosition] = None


@dataclass(slots=True)
class _CachedRepMove:
    move_id: int
    level: int
    is_active: bool


DEFAULT_BOX_INTERVALS = {
    "standard": {
        1: (5, "minutes"),
        2: (1, "days"),
        3: (3, "days"),
        4: (9, "days"),
        5: (21, "days"),
        6: (63, "days"),
        7: (180, "days")
    },
    "relaxed": {
        1: (10, "minutes"),
        2: (2, "days"),
        3: (7, "days"),
        4: (20, "days"),
        5: (60, "days"),
        6: (180, "days"),
        7: (365, "days")
    }
}

BOX_INTERVALS = {
    1: datetime.timedelta(minutes=5),
    2: datetime.timedelta(days=1),
    3: datetime.timedelta(days=3),
    4: datetime.timedelta(days=9),
    5: datetime.timedelta(days=21),
    6: datetime.timedelta(days=63),
    7: datetime.timedelta(days=180)
}

def parse_interval_delta(val: int, unit: str) -> datetime.timedelta:
    val = max(1, int(val))
    if unit == "minutes":
        return datetime.timedelta(minutes=val)
    elif unit == "hours":
        return datetime.timedelta(hours=val)
    elif unit == "days":
        return datetime.timedelta(days=val)
    elif unit == "months":
        return datetime.timedelta(days=val * 30)
    return datetime.timedelta(days=val)

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
            "notation_language": "en",
            "ui_language": "de",
            "interval_preset": "standard",
            "custom_intervals": {
                "1": {"value": 5, "unit": "minutes"},
                "2": {"value": 1, "unit": "days"},
                "3": {"value": 3, "unit": "days"},
                "4": {"value": 9, "unit": "days"},
                "5": {"value": 21, "unit": "days"},
                "6": {"value": 63, "unit": "days"},
                "7": {"value": 180, "unit": "days"}
            },
            "alternate_move_policy": "no_penalty",
            "queue_priority_order": "priority_first",
            "max_new_cards_per_day": 0,
            "max_reviews_per_session": 0,
            "enforce_limit_after_variation": True,
            "leadup_skip_mode": "leitner_box",
            "leadup_target_box": 3,
            "leadup_session_limit": 3,
            "leadup_show_once_per_session": True,
            "leadup_new_moves_mode": "always_from_start",
            "leadup_skip_style": "instant",
        }
        
        # Optimization Caches
        self._session_variation_seen_counts: Dict[Tuple[str, str], int] = {}
        self._variation_move_ids = set()
        self._active_filter_name = None
        self._forward_moves_cache = None
        self._rep_move_cache = None
        self._pos_cache = None
        self._td_cache = None
        
        # O(1) index caches for hot-path lookups
        self._move_by_id_cache: Optional[Dict[int, Move]] = None
        self._move_by_fen_uci_cache: Optional[Dict[Tuple[str, str], Move]] = None
        self._moves_by_level: Optional[Dict[int, List[int]]] = None
        self._levels_cache: Optional[List[Dict[str, Any]]] = None
        self._cached_elo: Optional[int] = None
        
        # New: Stat Caching
        self._reachable_moves_cache = None
        self._reachable_keys_cache = None
        self._norm_reachable_keys_cache = None # List of (fen, uci) reachable for current repo/level
        self._reachable_moves_by_key = {}
        self._last_stats_cache = None # (cache_key, (new, due, dist))
        self._user_settings_cache = None # Cached UserRepertoireSettings for active repertoire
        self._all_user_settings_cache: Optional[Dict[str, UserRepertoireSettings]] = None
        self._settings_dirty: bool = False
        self._repo_graph_lru: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        
        self.navigator = RepertoireNavigator(repertoire_manager)
        
        self.init_user_db()
        self.load_settings()

    def init_user_db(self) -> None:
        if is_free_training_profile(self.profile_name):
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

    def reset_session_variation_counts(self) -> None:
        """Resets per-session variation intro view counts."""
        self._session_variation_seen_counts.clear()

    @staticmethod
    def get_move_variation_name(move_obj: Any) -> Optional[str]:
        """Returns the most specific raw variation name for a move's target or source position."""
        if not move_obj:
            return None
        for pos_attr in ("to_position", "from_position"):
            pos = getattr(move_obj, pos_attr, None)
            if not pos:
                continue
            for field in ("cached_v3", "variation_3", "cached_v2", "variation_2", "cached_v1", "variation_1"):
                val = getattr(pos, field, None)
                if val and str(val).strip():
                    return str(val).strip()
        return None

    def _are_leadup_moves_mastered(self, history_to_entry: List[Dict[str, Any]], target_box: int) -> bool:
        """Returns True if every player move in history_to_entry has reached at least target_box."""
        if not history_to_entry:
            return False

        self._ensure_td_cache()
        side_raw = (self.repertoire_manager.get_repertoire_color() or "w").lower() if self.repertoire_manager else "w"
        player_turn = "w" if side_raw.startswith("w") else "b"
        starting_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

        checked_player_moves = 0
        for idx, item in enumerate(history_to_entry):
            from_fen = starting_fen if idx == 0 else (history_to_entry[idx - 1].get("fen") or "")
            parts = from_fen.split()
            if len(parts) < 2 or parts[1] != player_turn:
                continue

            checked_player_moves += 1
            norm_fen = " ".join(parts[:4])
            uci = item.get("uci", "")
            td = self._norm_td_cache.get((norm_fen, uci))
            if td is None or (td.box or 0) < target_box:
                return False

        return checked_player_moves > 0

    def should_skip_leadup_animation(
        self,
        variation_name: Optional[str],
        history_to_entry: List[Dict[str, Any]],
        training_mode: str = "review",
        record_session_view: bool = True,
    ) -> bool:
        """
        Determines whether the lead-up animation before a variation's entry point should be skipped.
        Tracks per-session variation intro views when record_session_view is True.
        """
        if not variation_name or not history_to_entry:
            return False

        if training_mode == "new":
            new_mode = self.get_setting("leadup_new_moves_mode") or "always_from_start"
            if new_mode == "always_from_start":
                return False
            if new_mode == "always_skip":
                return True

        mode = self.get_setting("leadup_skip_mode") or "leitner_box"
        if mode == "off":
            return False

        repo_name = getattr(self.repertoire_manager, "active_repertoire_name", "") or ""
        key = (repo_name, variation_name)
        seen_before = self._session_variation_seen_counts.get(key, 0)

        show_once = bool(self.get_setting("leadup_show_once_per_session"))
        if show_once and seen_before == 0:
            if record_session_view:
                self._session_variation_seen_counts[key] = 1
            return False

        if mode == "always":
            should_skip = True
        elif mode == "once_per_session":
            should_skip = seen_before >= 1
        elif mode == "session_count":
            limit = max(1, int(self.get_setting("leadup_session_limit") or 3))
            should_skip = seen_before >= limit
        elif mode == "leitner_box":
            target_box = max(1, int(self.get_setting("leadup_target_box") or 3))
            should_skip = self._are_leadup_moves_mastered(history_to_entry, target_box)
        else:
            should_skip = False

        if record_session_view:
            self._session_variation_seen_counts[key] = seen_before + 1

        return should_skip

    def get_box_interval(self, box: int) -> datetime.timedelta:
        preset = self.get_setting("interval_preset") or "standard"
        if preset == "relaxed":
            val, unit = DEFAULT_BOX_INTERVALS["relaxed"].get(box, (1, "days"))
            return parse_interval_delta(val, unit)
        elif preset == "custom":
            custom = self.get_setting("custom_intervals")
            if isinstance(custom, dict):
                entry = custom.get(str(box)) or custom.get(box)
                if isinstance(entry, dict):
                    return parse_interval_delta(int(entry.get("value", 1)), entry.get("unit", "days"))
                elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                    return parse_interval_delta(int(entry[0]), entry[1])
        # Default standard
        val, unit = DEFAULT_BOX_INTERVALS["standard"].get(box, (1, "days"))
        return parse_interval_delta(val, unit)

    def record_new_card_trained(self, defer_save: bool = False) -> None:
        today_str = datetime.date.today().isoformat()
        daily_data = self.settings.setdefault("daily_new_cards", {})
        if len(daily_data) > 14:
            cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
            self.settings["daily_new_cards"] = {k: v for k, v in daily_data.items() if k >= cutoff}
            daily_data = self.settings["daily_new_cards"]
        daily_data[today_str] = daily_data.get(today_str, 0) + 1
        if defer_save:
            self._settings_dirty = True
        else:
            self.save_settings()
            self._settings_dirty = False

    def get_today_new_cards_count(self) -> int:
        today_str = datetime.date.today().isoformat()
        daily_data = self.settings.get("daily_new_cards", {})
        return daily_data.get(today_str, 0)

    def get_visible_repos(self) -> List[str]:
        all_existing = set(self.repertoire_manager.get_all_repertoires()) if self.repertoire_manager else set()
        if is_free_training_profile(self.profile_name):
            # All repertoires are visible in free training
            return sorted(list(all_existing))
            
        if not self.user_session: return []
        settings = self.user_session.query(UserRepertoireSettings).all()
        
        valid_repos = []
        orphaned = []
        for s in settings:
            if s.repertoire_name in all_existing:
                valid_repos.append(s.repertoire_name)
            else:
                orphaned.append(s)

        # Self-heal profile DB: remove orphaned settings for deleted repertoires
        if orphaned:
            try:
                for s in orphaned:
                    self.user_session.delete(s)
                self.user_session.commit()
            except Exception as e:
                from opening_fenix.core.logger import logger
                logger.warning(f"Failed to clean up orphaned profile settings: {e}")

        self._all_user_settings_cache = {s.repertoire_name: s for s in settings if s not in orphaned}
        return valid_repos

    def _get_all_user_settings_map(self) -> Dict[str, UserRepertoireSettings]:
        if self._all_user_settings_cache is not None:
            return self._all_user_settings_cache
        if not self.user_session:
            return {}
        with self.user_session.no_autoflush:
            rows = self.user_session.query(UserRepertoireSettings).all()
        self._all_user_settings_cache = {s.repertoire_name: s for s in rows}
        return self._all_user_settings_cache

    def _get_repo_user_settings(self, repo_name: Optional[str]) -> Optional[UserRepertoireSettings]:
        if not repo_name or not self.user_session:
            return None
        active = self.repertoire_manager.active_repertoire_name if self.repertoire_manager else None
        if repo_name == active and self._user_settings_cache is not None:
            return self._user_settings_cache
        if self._all_user_settings_cache is not None:
            return self._all_user_settings_cache.get(repo_name)
        with self.user_session.no_autoflush:
            settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        return settings

    def set_repo_visibility(self, repo_name: str, is_visible: bool) -> None:
        if not self.user_session: return
        existing = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        active = self.repertoire_manager.active_repertoire_name if self.repertoire_manager else None
        if is_visible:
            setting = existing
            if not setting:
                setting = UserRepertoireSettings(repertoire_name=repo_name, active_level=1, comment_language="auto")
                self.user_session.add(setting)
            if self._all_user_settings_cache is not None:
                self._all_user_settings_cache[repo_name] = setting
            if repo_name == active:
                self._user_settings_cache = setting
        else:
            if existing:
                self.user_session.delete(existing)
                if self._all_user_settings_cache is not None:
                    self._all_user_settings_cache.pop(repo_name, None)
            if repo_name == active:
                self._user_settings_cache = None
        self.user_session.commit()

    def is_repo_visible(self, repo_name: str) -> bool:
        if not self.user_session: return False
        if self._all_user_settings_cache is not None:
            return repo_name in self._all_user_settings_cache
        return self._get_repo_user_settings(repo_name) is not None

    def get_active_level(self, repo_name: Optional[str] = None) -> int:
        if not self.user_session: 
            return 999 if is_free_training_profile(self.profile_name) else 1

        if not repo_name or repo_name == self.repertoire_manager.active_repertoire_name:
            settings = self._get_rating_settings()
            if settings:
                return settings.active_level
            return 999 if is_free_training_profile(self.profile_name) else 1

        settings = self._get_repo_user_settings(repo_name)
        if settings:
            return settings.active_level
        return 999 if is_free_training_profile(self.profile_name) else 1

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
            settings.stats_updated_at = None
            settings.last_dist_json = None
        self.user_session.commit()
        if self._all_user_settings_cache is not None:
            self._all_user_settings_cache[repo_name] = settings
        # Invalidate level-dependent caches without dropping immutable graph/move/TD caches
        if repo_name == self.repertoire_manager.active_repertoire_name:
            self._user_settings_cache = settings
            self._reachable_moves_cache = None
            self._reachable_keys_cache = None
            self._norm_reachable_keys_cache = None
            self._last_stats_cache = None
            self._user_settings_cache = settings
            self._cached_elo = None

    def get_comment_language(self, repo_name: Optional[str] = None) -> str:
        if not self.user_session:
            return "auto"
        if not repo_name:
            repo_name = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        if not repo_name:
            return "auto"
        settings = self._get_repo_user_settings(repo_name)
        if settings and hasattr(settings, 'comment_language') and settings.comment_language:
            return settings.comment_language
        return "auto"

    def set_comment_language(self, comment_lang: str, repo_name: Optional[str] = None) -> None:
        if not self.user_session: return
        if not repo_name:
            repo_name = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        if not repo_name: return

        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if not settings:
            settings = UserRepertoireSettings(repertoire_name=repo_name, comment_language=comment_lang)
            self.user_session.add(settings)
        else:
            settings.comment_language = comment_lang
        self.user_session.commit()
        if self._all_user_settings_cache is not None:
            self._all_user_settings_cache[repo_name] = settings
        if repo_name == getattr(self.repertoire_manager, 'active_repertoire_name', None):
            self._user_settings_cache = settings
        
    def close(self) -> None:
        if self._settings_dirty:
            self.save_settings()
            self._settings_dirty = False
        self._all_user_settings_cache = None
        if self.user_session:
            self.user_session.close()
            self.user_session = None
        if self.user_db:
            self.user_db.close()
            self.user_db = None

    def on_repertoire_changed(self, clear_persistent_stats: bool = True):
        """Called when switching repertoires to ensure no data leaks between them."""
        self._variation_move_ids = set()
        self._active_filter_name = None
        self._forward_moves_cache = None
        self._rep_move_cache = None
        self._pos_cache = None
        self._td_cache = None
        self._norm_td_cache = None
        self._move_by_id_cache = None
        self._move_by_fen_uci_cache = None
        self._moves_by_level = None
        self._levels_cache = None
        self._cached_elo = None
        self._prio_elo_local = None
        self._reachable_moves_cache = None
        self._reachable_keys_cache = None
        self._norm_reachable_keys_cache = None
        self._reachable_moves_by_key = {}
        self._last_stats_cache = None
        self._user_settings_cache = None
        if clear_persistent_stats:
            if hasattr(self, '_repo_graph_lru'):
                self._repo_graph_lru.clear()
        if clear_persistent_stats and self.user_session and self.repertoire_manager and self.repertoire_manager.active_repertoire_name:
            try:
                settings = self.user_session.query(UserRepertoireSettings).filter_by(
                    repertoire_name=self.repertoire_manager.active_repertoire_name
                ).first()
                if settings:
                    settings.stats_updated_at = None
                    self.user_session.commit()
            except Exception:
                pass

    def invalidate_caches(self):
        """Invalidates all internal caches when priority scores or repertoire data change."""
        if self.repertoire_manager:
            if hasattr(self.repertoire_manager, 'invalidate_priority_cache'):
                self.repertoire_manager.invalidate_priority_cache()
            if getattr(self.repertoire_manager, 'explorer', None) and hasattr(self.repertoire_manager.explorer, 'invalidate_cache'):
                self.repertoire_manager.explorer.invalidate_cache()
        self.on_repertoire_changed(clear_persistent_stats=True)

    def reset_repertoire_progress(self, repo_name: Optional[str] = None) -> Tuple[bool, str]:
        target_repo = repo_name or (self.repertoire_manager.active_repertoire_name if self.repertoire_manager else None)
        if not target_repo: return False, "Kein Repertoire aktiv."
        try:
            num_deleted = self.user_session.query(TrainingData).filter(TrainingData.repertoire_name == target_repo).delete(synchronize_session=False)
            settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=target_repo).first()
            if settings:
                settings.last_dist_json = None
                settings.last_new_count = 0
                settings.last_due_count = 0
                settings.stats_updated_at = None
                settings.rating = 800.0
            self.user_session.commit()
            # Invalidate caches
            self._td_cache = None
            self._norm_td_cache = None
            self._cached_elo = None
            self._last_stats_cache = None
            if self._all_user_settings_cache is not None:
                if settings is not None:
                    self._all_user_settings_cache[target_repo] = settings
                else:
                    self._all_user_settings_cache.pop(target_repo, None)
            if self.repertoire_manager and target_repo == self.repertoire_manager.active_repertoire_name:
                self._user_settings_cache = settings
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
            self._norm_td_cache = None
            self._user_settings_cache = None
            self._all_user_settings_cache = None
            self._last_stats_cache = None
            self._cached_elo = None
            return True, "User data updated."
        except Exception as e:
            self.user_session.rollback()
            return False, f"Error updating user data: {e}"

    def _get_repo_graph_sig_for_path(self, repo_name: str, db_filename: str) -> Optional[Tuple[str, str, int, int]]:
        if not repo_name or not db_filename or db_filename == ":memory:":
            return None
        try:
            abs_p = os.path.abspath(db_filename)
            db_mtime = os.stat(abs_p).st_mtime_ns
            wal_path = abs_p + "-wal"
            wal_mtime = os.stat(wal_path).st_mtime_ns if os.path.exists(wal_path) else 0
            return (repo_name, abs_p, db_mtime, wal_mtime)
        except OSError:
            return None

    def _get_active_repo_graph_sig(self) -> Optional[Tuple[str, str, int, int]]:
        if not self.repertoire_manager:
            return None
        repo_name = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        repo_db = getattr(self.repertoire_manager, 'repo_db', None)
        db_filename = getattr(repo_db, 'db_filename', None) if repo_db else None
        return self._get_repo_graph_sig_for_path(repo_name, db_filename)

    _MAX_CACHED_GRAPH_MOVES = 45_000
    _MAX_CACHED_GRAPH_REPOS = 8

    def _get_lru_cached_moves_total(self) -> int:
        if not hasattr(self, '_repo_graph_lru'):
            return 0
        return sum(int(entry.get('move_count', 0)) for entry in self._repo_graph_lru.values())

    def _put_repo_graph_lru(self, repo_name: str, entry: Dict[str, Any]) -> None:
        if not hasattr(self, '_repo_graph_lru'):
            return
        self._repo_graph_lru[repo_name] = entry
        self._repo_graph_lru.move_to_end(repo_name)
        while len(self._repo_graph_lru) > 1 and (
            len(self._repo_graph_lru) > self._MAX_CACHED_GRAPH_REPOS
            or self._get_lru_cached_moves_total() > self._MAX_CACHED_GRAPH_MOVES
        ):
            self._repo_graph_lru.popitem(last=False)

    def prewarm_repertoire_graph(self, repo_name: str, respect_budget: bool = True) -> bool:
        """
        Thread-safe background preloader that builds the move/position graph for `repo_name`
        using a standalone read-only sqlite3 connection and stores it in `_repo_graph_lru`
        without mutating the active repertoire state.
        """
        if not repo_name or not hasattr(self, '_repo_graph_lru'):
            return False
        from opening_fenix.core.utils import get_repertoire_db_path
        import sqlite3
        db_path = get_repertoire_db_path(repo_name)
        if not db_path or not os.path.exists(db_path):
            return False
        sig = self._get_repo_graph_sig_for_path(repo_name, db_path)
        if sig is None:
            return False
        cached = self._repo_graph_lru.get(repo_name)
        if cached is not None and cached.get('sig') == sig:
            return True
        if respect_budget and len(self._repo_graph_lru) > 0:
            if self._get_lru_cached_moves_total() >= self._MAX_CACHED_GRAPH_MOVES:
                return False
        conn = None
        try:
            conn = sqlite3.connect(sig[1], timeout=5.0)
            cur = conn.cursor()
            if respect_budget and len(self._repo_graph_lru) > 0:
                n_moves = cur.execute("SELECT COUNT(id) FROM moves").fetchone()[0] or 0
                if self._get_lru_cached_moves_total() + n_moves > self._MAX_CACHED_GRAPH_MOVES:
                    return False
            cur.execute("SELECT value FROM metadata WHERE key = 'color'")
            c_row = cur.fetchone()
            side = (c_row[0] if c_row and c_row[0] else 'w').lower()
            pos_rows = cur.execute(
                "SELECT id, fen, comment, good_moves, variation_1, variation_2, variation_3, cached_v1, cached_v2, cached_v3 FROM positions"
            ).fetchall()
            move_rows = cur.execute(
                "SELECT id, from_position_id, to_position_id, uci, san, priority_score, nag FROM moves ORDER BY COALESCE(priority_score, 0.0) DESC"
            ).fetchall()
            rm_rows = cur.execute(
                "SELECT move_id, level, is_active FROM repertoire_moves WHERE is_active = 1"
            ).fetchall()
        except Exception:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        pos_cache = {r[0]: _CachedPosition(*r) for r in pos_rows}
        forward_moves_cache: Dict[int, list] = {}
        move_parent_cache: Dict[int, list] = {}
        move_by_id_cache: Dict[int, _CachedMove] = {}
        move_by_fen_uci_cache: Dict[Tuple[str, str], _CachedMove] = {}

        for r in move_rows:
            m = _CachedMove(r[0], r[1], r[2], r[3], r[4], r[5] or 0.0, r[6], pos_cache.get(r[1]))
            forward_moves_cache.setdefault(m.from_position_id, []).append(m)
            move_parent_cache.setdefault(m.to_position_id, []).append(m)
            move_by_id_cache[m.id] = m
            from_pos = pos_cache.get(m.from_position_id)
            if from_pos is not None:
                move_by_fen_uci_cache[(from_pos.fen, m.uci)] = m

        all_rep_moves = [_CachedRepMove(r[0], r[1] if r[1] is not None else 1, bool(r[2])) for r in rm_rows]
        rep_move_cache = {rm.move_id: rm for rm in all_rep_moves}
        moves_by_level: Dict[int, List[int]] = {}
        for rm in all_rep_moves:
            lvl = rm.level if rm.level is not None else 1
            m = move_by_id_cache.get(rm.move_id)
            if m and m.from_position_id in pos_cache:
                fen = pos_cache[m.from_position_id].fen
                parts = fen.split()
                if len(parts) >= 2 and parts[1].lower() in ('w', 'b') and side in ('w', 'b'):
                    if parts[1].lower() == side:
                        moves_by_level.setdefault(lvl, []).append(rm.move_id)
                else:
                    moves_by_level.setdefault(lvl, []).append(rm.move_id)
            else:
                moves_by_level.setdefault(lvl, []).append(rm.move_id)

        self._put_repo_graph_lru(repo_name, {
            'sig': sig,
            'move_count': len(move_by_id_cache),
            'forward_moves_cache': forward_moves_cache,
            'pos_cache': pos_cache,
            'move_by_id_cache': move_by_id_cache,
            'move_by_fen_uci_cache': move_by_fen_uci_cache,
            'move_parent_cache': move_parent_cache,
            'rep_move_cache': rep_move_cache,
            'moves_by_level': moves_by_level,
        })
        return True

    # ── Multi-Elo priority overlay ─────────────────────────────────────────────
    def get_course_lichess_elos(self, repo_name: Optional[str] = None) -> Tuple[Optional[str], List[str]]:
        """Returns (default_elo, available_elos) for a course. Cheap sqlite3 read, no session needed."""
        from opening_fenix.core.services.repertoire_core_service import get_repertoire_lichess_elos_fast
        if not repo_name:
            repo_name = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        if not repo_name:
            return None, []
        return get_repertoire_lichess_elos_fast(repo_name)

    def get_active_lichess_elo(self, repo_name: Optional[str] = None) -> Optional[str]:
        """Effective Elo for this learner: stored choice if still valid, else the course default."""
        default_elo, available = self.get_course_lichess_elos(repo_name)
        if not available:
            return default_elo
        if not repo_name:
            repo_name = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        chosen = None
        if self.user_session and repo_name:
            settings = self._get_repo_user_settings(repo_name)
            chosen = getattr(settings, 'active_lichess_elo', None) if settings else None
        if chosen in available:
            return chosen
        return default_elo if default_elo in available else available[0]

    def set_active_lichess_elo(self, elo: Optional[str], repo_name: Optional[str] = None) -> None:
        if not self.user_session:
            return
        if not repo_name:
            repo_name = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        if not repo_name:
            return
        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if not settings:
            settings = UserRepertoireSettings(repertoire_name=repo_name, active_lichess_elo=elo)
            self.user_session.add(settings)
        else:
            settings.active_lichess_elo = elo
        self.user_session.commit()
        if self._all_user_settings_cache is not None:
            self._all_user_settings_cache[repo_name] = settings
        if repo_name == getattr(self.repertoire_manager, 'active_repertoire_name', None):
            self._user_settings_cache = settings
            # Priority-dependent caches must be rebuilt; the immutable graph stays cached
            self._reachable_moves_cache = None
            self._reachable_keys_cache = None
            self._norm_reachable_keys_cache = None
            self._last_stats_cache = None
            # Re-apply the Elo overlay immediately (cheap in-memory re-score, no graph rebuild)
            self._apply_priority_overlay()

    def _get_applied_prio_elo(self) -> Optional[str]:
        sig = self._get_active_repo_graph_sig()
        if sig is not None and hasattr(self, '_repo_graph_lru'):
            entry = self._repo_graph_lru.get(sig[0])
            if entry is not None and entry.get('sig') == sig:
                return entry.get('prio_elo')
        return getattr(self, '_prio_elo_local', None)

    def _set_applied_prio_elo(self, elo: Optional[str]) -> None:
        self._prio_elo_local = elo
        sig = self._get_active_repo_graph_sig()
        if sig is not None and hasattr(self, '_repo_graph_lru'):
            entry = self._repo_graph_lru.get(sig[0])
            if entry is not None and entry.get('sig') == sig:
                entry['prio_elo'] = elo

    def _apply_priority_overlay(self) -> None:
        """
        Swaps the cached Move.priority_score values to those of the learner's active Elo.
        Single-Elo / legacy courses are never touched (target is None = DB default state).
        """
        if self._forward_moves_cache is None or self._move_by_id_cache is None:
            return
        repo_sess = getattr(self.repertoire_manager, 'repo_session', None)
        if not repo_sess or not isinstance(repo_sess, Session):
            return
        try:
            default_elo, available = self.get_course_lichess_elos()
            target: Optional[str] = None
            if len(available) > 1:
                target = self.get_active_lichess_elo()
            applied = self._get_applied_prio_elo()
            if target == applied:
                return

            conn = repo_sess.connection()
            if target is None:
                rows = conn.exec_driver_sql("SELECT id, priority_score FROM moves").fetchall()
            else:
                rows = conn.exec_driver_sql(
                    "SELECT move_id, priority_score FROM move_priorities WHERE elo_range = ?", (target,)
                ).fetchall()
                if not rows:
                    return  # Nothing computed for that Elo; keep current scores
            score_map = {r[0]: (r[1] or 0.0) for r in rows}
            for mid, m in self._move_by_id_cache.items():
                m.priority_score = score_map.get(mid, 0.0)
            for lst in self._forward_moves_cache.values():
                lst.sort(key=lambda m: (m.priority_score or 0.0), reverse=True)
            for lst in (self._move_parent_cache or {}).values():
                lst.sort(key=lambda m: (m.priority_score or 0.0), reverse=True)
            self._set_applied_prio_elo(target)
        except Exception:
            # Overlay is best-effort; never break training because of Elo switching
            pass

    def _ensure_forward_cache(self):
        self._ensure_forward_cache_impl()
        self._apply_priority_overlay()

    def _ensure_forward_cache_impl(self):
        if not self.repertoire_manager.repo_session:
            return

        if (
            self._forward_moves_cache is None
            or self._move_by_fen_uci_cache is None
            or self._rep_move_cache is None
            or self._moves_by_level is None
        ):
            sig = self._get_active_repo_graph_sig()
            if sig is not None and hasattr(self, '_repo_graph_lru'):
                cached_graph = self._repo_graph_lru.get(sig[0])
                if cached_graph is not None and cached_graph.get('sig') == sig:
                    self._repo_graph_lru.move_to_end(sig[0])
                    self._forward_moves_cache = cached_graph['forward_moves_cache']
                    self._pos_cache = cached_graph['pos_cache']
                    self._move_by_id_cache = cached_graph['move_by_id_cache']
                    self._move_by_fen_uci_cache = cached_graph['move_by_fen_uci_cache']
                    self._move_parent_cache = cached_graph['move_parent_cache']
                    self._rep_move_cache = cached_graph['rep_move_cache']
                    self._moves_by_level = cached_graph['moves_by_level']
                    return

        if self._forward_moves_cache is None or self._move_by_fen_uci_cache is None:
            self._prio_elo_local = None  # Freshly built caches reflect DB default priorities
            self._forward_moves_cache = {}
            self._pos_cache = {}
            self._move_by_id_cache = {}
            self._move_by_fen_uci_cache = {}
            self._move_parent_cache = {} # Local parent cache for training algorithms
            
            repo_sess = self.repertoire_manager.repo_session
            if isinstance(repo_sess, Session):
                conn = repo_sess.connection()
                pos_rows = conn.exec_driver_sql(
                    "SELECT id, fen, comment, good_moves, variation_1, variation_2, variation_3, cached_v1, cached_v2, cached_v3 FROM positions"
                ).fetchall()
                pos_cache = self._pos_cache
                for r in pos_rows:
                    pos_cache[r[0]] = _CachedPosition(*r)
                move_rows = conn.exec_driver_sql(
                    "SELECT id, from_position_id, to_position_id, uci, san, priority_score, nag FROM moves ORDER BY COALESCE(priority_score, 0.0) DESC"
                ).fetchall()
                all_moves = [
                    _CachedMove(r[0], r[1], r[2], r[3], r[4], r[5] or 0.0, r[6], pos_cache.get(r[1]))
                    for r in move_rows
                ]
                already_sorted = True
            else:
                for p in repo_sess.query(Position).all():
                    self._pos_cache[p.id] = p
                all_moves = self.repertoire_manager.core.get_all_moves()
                already_sorted = False
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
                    
            if not already_sorted:
                for k in self._forward_moves_cache:
                    self._forward_moves_cache[k].sort(key=lambda m: (m.priority_score or 0.0), reverse=True)
                
                # Sort parent cache too for predictable ancestor selection
                for k in self._move_parent_cache:
                    self._move_parent_cache[k].sort(key=lambda m: (m.priority_score or 0.0), reverse=True)
            
        if self._rep_move_cache is None or self._moves_by_level is None:
            if isinstance(self.repertoire_manager.repo_session, Session):
                rm_rows = self.repertoire_manager.repo_session.connection().exec_driver_sql(
                    "SELECT move_id, level, is_active FROM repertoire_moves WHERE is_active = 1"
                ).fetchall()
                all_rep_moves = [_CachedRepMove(r[0], r[1] if r[1] is not None else 1, bool(r[2])) for r in rm_rows]
            else:
                all_rep_moves = self.repertoire_manager.core.get_all_active_repertoire_moves()
            self._rep_move_cache = {rm.move_id: rm for rm in all_rep_moves}
            self._moves_by_level = {}
            side = (self.repertoire_manager.get_repertoire_color() or 'w').lower() if self.repertoire_manager else 'w'
            for rm in all_rep_moves:
                lvl = rm.level if rm.level is not None else 1
                # Only count trainable moves (where it is the player's turn to move)
                m = self._move_by_id_cache.get(rm.move_id) if self._move_by_id_cache else None
                if m and m.from_position_id in self._pos_cache:
                    fen = self._pos_cache[m.from_position_id].fen
                    parts = fen.split()
                    if len(parts) >= 2 and parts[1].lower() in ('w', 'b') and side in ('w', 'b'):
                        if parts[1].lower() == side:
                            self._moves_by_level.setdefault(lvl, []).append(rm.move_id)
                    else:
                        # Synthetic test fallback without full chess FEN
                        self._moves_by_level.setdefault(lvl, []).append(rm.move_id)
                else:
                    self._moves_by_level.setdefault(lvl, []).append(rm.move_id)

            sig = self._get_active_repo_graph_sig()
            if sig is not None and hasattr(self, '_repo_graph_lru'):
                self._put_repo_graph_lru(sig[0], {
                    'sig': sig,
                    'move_count': len(self._move_by_id_cache) if self._move_by_id_cache else 0,
                    'forward_moves_cache': self._forward_moves_cache,
                    'pos_cache': self._pos_cache,
                    'move_by_id_cache': self._move_by_id_cache,
                    'move_by_fen_uci_cache': self._move_by_fen_uci_cache,
                    'move_parent_cache': self._move_parent_cache,
                    'rep_move_cache': self._rep_move_cache,
                    'moves_by_level': self._moves_by_level,
                })

    def _ensure_td_cache(self):
        if self._td_cache is not None:
            return
            
        self._td_cache = {}
        self._norm_td_cache = {}
        tds = self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).all()
        for td in tds:
            self._td_cache[(td.fen, td.move_uci)] = td
            if td.fen:
                norm_f = _norm_fen4(td.fen)
                self._norm_td_cache[(norm_f, td.move_uci)] = td

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
        
        if self._reachable_moves_cache is None:
            self._reachable_moves_by_key = {}
        elif getattr(self, "_reachable_moves_cache_key", None) == cache_key:
            return self._reachable_moves_cache
            
        by_key = getattr(self, "_reachable_moves_by_key", None)
        if by_key is None:
            by_key = {}
            self._reachable_moves_by_key = by_key

        if cache_key in by_key:
            moves_list, keys_set, norm_keys_set = by_key[cache_key]
        else:
            valid_move_ids = self._build_variation_move_set(variation_filter) if variation_filter else None
            moves_list = self._calculate_reachable_moves(variation_filter, valid_move_ids=valid_move_ids)
            keys_set = set(moves_list)
            norm_keys_set = {(_norm_fen4(f), u) for (f, u) in keys_set}
            by_key[cache_key] = (moves_list, keys_set, norm_keys_set)

        self._reachable_moves_cache = moves_list
        self._reachable_keys_cache = keys_set
        self._norm_reachable_keys_cache = norm_keys_set
        self._reachable_moves_cache_key = cache_key
        return self._reachable_moves_cache

    def _calculate_reachable_moves(self, variation_filter, max_lvl=None, valid_move_ids=None):
        """Internal BFS to find all reachable moves for a given configuration."""
        if max_lvl is None:
            max_lvl = self.get_active_level()
        side = self.repertoire_manager.get_repertoire_color()
        self._ensure_forward_cache()
        
        cache_data = {
            'pos_cache': self._pos_cache,
            'forward_moves_cache': self._forward_moves_cache,
            'move_parent_cache': self._move_parent_cache,
            'rep_move_cache': self._rep_move_cache
        }
        
        return self.navigator.calculate_reachable_moves(variation_filter, max_lvl, side, cache_data, valid_move_ids=valid_move_ids)

    def get_box_statistics(self, max_lvl: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculates accurate Leitner box distribution and due counts for reachable player moves.
        If max_lvl is None, evaluates all reachable moves across all levels (max_lvl=999).
        """
        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        target_lvl = max_lvl if max_lvl is not None else 999
        if max_lvl is not None and target_lvl == self.get_active_level():
            reachable = self._ensure_reachable_moves_cache(None)
        else:
            reachable = self._calculate_reachable_moves(None, max_lvl=target_lvl)
        user_map = self._td_cache or {}
        norm_user_map = self._norm_td_cache if getattr(self, '_norm_td_cache', None) is not None else {(_norm_fen4(k[0]), k[1]): v for k, v in user_map.items()}
        
        lookahead = datetime.datetime.now() + datetime.timedelta(minutes=5)
        box_counts = {i: 0 for i in range(1, 8)}
        box_due_counts = {i: 0 for i in range(1, 8)}
        total_due = 0
        total_learned = 0
        
        for fen, uci in reachable:
            entry = user_map.get((fen, uci)) or norm_user_map.get((_norm_fen4(fen), uci))
            if entry and 1 <= entry.box <= 7:
                box_counts[entry.box] += 1
                total_learned += 1
                if entry.next_due and entry.next_due <= lookahead:
                    box_due_counts[entry.box] += 1
                    total_due += 1
                    
        total_trainable = len(reachable)
        total_unlearned = max(0, total_trainable - total_learned)
        learned_pct = (total_learned / total_trainable * 100.0) if total_trainable > 0 else 0.0
        
        return {
            "total_trainable": total_trainable,
            "total_learned": total_learned,
            "total_unlearned": total_unlearned,
            "total_due": total_due,
            "learned_pct": round(learned_pct, 1),
            "box_counts": box_counts,
            "box_due_counts": box_due_counts
        }

    def get_stats_for_repertoire(self, repo_name: str) -> Tuple[int, int, Dict[int, int]]:
        """Fast path for checking persistent stats cache without full repertoire switch."""
        if not self.user_session: return 0, 0, {}
        if (
            self.repertoire_manager
            and repo_name == self.repertoire_manager.active_repertoire_name
            and self.repertoire_manager.repo_session
        ):
            return self.get_stats(variation_filter=None)
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
                        TrainingData.next_due > settings.stats_updated_at + datetime.timedelta(minutes=5),
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

    def get_rating_for_repertoire(self, repo_name: str) -> float:
        """Fast path to get stored rating for a repertoire."""
        if not self.user_session:
            return 800.0
        if (self.repertoire_manager and 
            self.repertoire_manager.active_repertoire_name == repo_name and 
            self._cached_elo is not None):
            return float(self._cached_elo)
        settings = self.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
        if settings and settings.rating is not None:
            return float(settings.rating)
        return 800.0

    def get_ratings_for_all_repertoires(self) -> Dict[str, float]:
        """Returns a dict mapping repertoire_name to rating."""
        if not self.user_session:
            return {}
        try:
            settings = self.user_session.query(UserRepertoireSettings).all()
            ratings = {s.repertoire_name: float(s.rating) if s.rating is not None else 800.0 for s in settings}
        except Exception:
            ratings = {}
        if (self.repertoire_manager and 
            self.repertoire_manager.active_repertoire_name and 
            self._cached_elo is not None):
            ratings[self.repertoire_manager.active_repertoire_name] = float(self._cached_elo)
        return ratings

    def get_stats(self, variation_filter=None, use_cache=True, auto_commit=True, allow_stale_cache=False):
        if not self.repertoire_manager.repo_session: return 0, 0, {}
        repo_name = self.repertoire_manager.active_repertoire_name
        active_level = self.get_active_level()
        mem_cache_key = (repo_name, active_level, variation_filter)

        # 0. Check in-memory stats cache when use_cache=True
        if use_cache and self._last_stats_cache is not None and self._last_stats_cache[0] == mem_cache_key:
            cached_new, cached_due, cached_dist, cached_at = self._last_stats_cache[1]
            if allow_stale_cache or (datetime.datetime.now() - cached_at).total_seconds() < 60:
                return cached_new, cached_due, dict(cached_dist)

        # 1. Check persistent DB cache first if no variation filter and use_cache is True
        if not variation_filter and use_cache:
            settings = self._get_repo_user_settings(repo_name)
            if settings and settings.last_dist_json and (allow_stale_cache or settings.stats_updated_at):
                is_fresh = allow_stale_cache or (
                    settings.stats_updated_at is not None
                    and (datetime.datetime.now() - settings.stats_updated_at).total_seconds() < 60
                )
                if is_fresh:
                    try:
                        dist = json.loads(settings.last_dist_json)
                        dist = {int(k): v for k, v in dist.items()}
                        res = (settings.last_new_count, settings.last_due_count, dist)
                        if settings.stats_updated_at is not None and (datetime.datetime.now() - settings.stats_updated_at).total_seconds() < 60:
                            self._last_stats_cache = (mem_cache_key, (*res, settings.stats_updated_at))
                        return res
                    except Exception:
                        pass

        # 2. Use "Smart Incremental" local cache approach
        reachable_repo_moves = self._ensure_reachable_moves_cache(variation_filter)
        
        self._ensure_td_cache()
        user_map = self._td_cache
        norm_user_map = self._norm_td_cache or {}
        new_c, due_c = 0, 0
        done_dist = {i: 0 for i in range(1, 8)} 
        lookahead = datetime.datetime.now() + datetime.timedelta(minutes=5)
        is_free = is_free_training_profile(self.profile_name)
        
        for fen, uci in reachable_repo_moves:
            entry = user_map.get((fen, uci))
            if entry is None and norm_user_map:
                entry = norm_user_map.get((_norm_fen4(fen), uci))
            if is_free:
                if not entry: due_c += 1
                else: done_dist[7] = done_dist.get(7, 0) + 1
            else:
                if not entry: new_c += 1
                elif entry.next_due <= lookahead: due_c += 1
                else: done_dist[entry.box] = done_dist.get(entry.box, 0) + 1
        
        self._last_stats_cache = (mem_cache_key, (new_c, due_c, dict(done_dist), datetime.datetime.now()))

        # 3. Update persistent cache if no filter
        if not variation_filter:
            self._update_persistent_stats_cache(new_c, due_c, done_dist, auto_commit=auto_commit)
            
        return new_c, due_c, done_dist

    def _update_persistent_stats_cache(self, new_c, due_c, dist, auto_commit=True):
        """Saves stats to the UserRepertoireSettings table."""
        if not self.user_session or not self.repertoire_manager.active_repertoire_name: return
        try:
            settings = self._get_repo_user_settings(self.repertoire_manager.active_repertoire_name)
            if settings:
                settings.last_new_count = new_c
                settings.last_due_count = due_c
                settings.last_dist_json = json.dumps(dist)
                settings.stats_updated_at = datetime.datetime.now()
                if auto_commit:
                    self.user_session.commit()
                    self._has_pending_commit = False
                else:
                    self._has_pending_commit = True
        except Exception as e:
            logger.error(f"Error updating stats cache: {e}")
            if auto_commit:
                self.user_session.rollback()

    def get_next_move(self, mode='due', last_move_obj=None, last_was_success=False, only_continuation=False, variation_filter=None, exclude_move_ids=None):
        if not self.repertoire_manager.repo_session: return None, []
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
            reachable_repo_moves = self._ensure_reachable_moves_cache(variation_filter)
            reachable_keys = self._reachable_keys_cache if self._reachable_keys_cache is not None else set(reachable_repo_moves)
            norm_reachable_keys = self._norm_reachable_keys_cache if self._norm_reachable_keys_cache is not None else {(_norm_fen4(f), u) for (f, u) in reachable_keys}

            # Filter due & reachable moves BEFORE sorting
            due_candidates = []
            for td in self._td_cache.values():
                if td.next_due <= lookahead:
                    if (td.fen, td.move_uci) in reachable_keys or (_norm_fen4(td.fen), td.move_uci) in norm_reachable_keys:
                        found_move = self._move_by_fen_uci_cache.get((td.fen, td.move_uci))
                        if not found_move or (valid_move_ids is not None and found_move.id not in valid_move_ids):
                            continue
                        if exclude_move_ids and found_move.id in exclude_move_ids:
                            continue
                        rep_move = self._rep_move_cache.get(found_move.id)
                        if not rep_move or rep_move.level > max_lvl:
                            continue
                        due_candidates.append((td, found_move))

            if due_candidates:
                sort_order = self.get_setting("queue_priority_order") or "priority_first"
                prio_cache = getattr(self.repertoire_manager, 'priority_cache', None)
                if prio_cache is not None:
                    def _get_prio(pair):
                        return prio_cache.get((pair[0].fen, pair[0].move_uci)) or 0.0
                else:
                    def _get_prio(pair):
                        return pair[1].priority_score or 0.0
                if sort_order == "priority_first":
                    due_candidates.sort(key=lambda pair: (-_get_prio(pair), pair[0].box))
                else:
                    due_candidates.sort(key=lambda pair: (pair[0].box, -_get_prio(pair)))
                return self._get_ancestor(due_candidates[0][1], check_due=True, variation_filter=variation_filter), []

            if is_free_training_profile(self.profile_name):
                td_cache = self._td_cache
                candidates = []
                for fen, uci in reachable_keys:
                    if (fen, uci) not in td_cache:
                        m = self._move_by_fen_uci_cache.get((fen, uci))
                        if m:
                            if exclude_move_ids and m.id in exclude_move_ids: continue
                            candidates.append(m)
                if candidates:
                    candidates.sort(key=lambda x: (x.priority_score or 0.0), reverse=True)
                    return self._get_ancestor(candidates[0], check_due=False, variation_filter=variation_filter), []
                return None, [] # All moves trained

        # 3. New Mode
        elif mode == 'new':
            reachable_repo_moves = self._ensure_reachable_moves_cache(variation_filter)
            reachable_keys = self._reachable_keys_cache if self._reachable_keys_cache is not None else set(reachable_repo_moves)
            td_cache = self._td_cache
            norm_td_cache = self._norm_td_cache if getattr(self, '_norm_td_cache', None) is not None else {}

            if variation_filter:
                # Compute lead_up_pos_ids in memory from _pos_cache + _move_parent_cache if available
                from opening_fenix.core.utils import matches_variation_name
                root_ids = {
                    p.id for p in self._pos_cache.values()
                    if matches_variation_name(p.variation_1, variation_filter)
                    or matches_variation_name(p.variation_2, variation_filter)
                    or matches_variation_name(p.variation_3, variation_filter)
                }
                lead_up_pos_ids = set()
                if root_ids:
                    q_lead = deque(root_ids)
                    seen_lead = set(root_ids)
                    while q_lead:
                        cid = q_lead.popleft()
                        for pm in self._move_parent_cache.get(cid, ()):
                            fp = pm.from_position_id
                            lead_up_pos_ids.add(fp)
                            if fp not in seen_lead:
                                seen_lead.add(fp)
                                q_lead.append(fp)
                    lead_up_pos_ids -= root_ids

                lead_up_candidates = []
                for pos_id in lead_up_pos_ids:
                    pos = self._pos_cache.get(pos_id)
                    if not pos: continue
                    for m in self._forward_moves_cache.get(pos_id, ()):
                        if (pos.fen, m.uci) in reachable_keys and (pos.fen, m.uci) not in td_cache and (_norm_fen4(pos.fen), m.uci) not in norm_td_cache:
                            if exclude_move_ids and m.id in exclude_move_ids: continue
                            lead_up_candidates.append(m)
                
                if lead_up_candidates:
                    lead_up_candidates.sort(key=lambda x: (x.priority_score or 0.0), reverse=True)
                    return self._get_ancestor(lead_up_candidates[0], check_due=False, variation_filter=None), []

            candidates = []
            for fen, uci in reachable_keys:
                if (fen, uci) not in td_cache and (_norm_fen4(fen), uci) not in norm_td_cache:
                    m = self._move_by_fen_uci_cache.get((fen, uci))
                    if m:
                        if exclude_move_ids and m.id in exclude_move_ids: continue
                        candidates.append(m)
            
            if candidates:
                pos_cache = self._pos_cache
                scored = []
                for m in candidates:
                    pos = pos_cache.get(m.from_position_id)
                    depth = 0
                    if pos:
                        try:
                            parts = pos.fen.split(" ")
                            move_num = int(parts[-1])
                            is_black = (parts[1] == 'b')
                            depth = (move_num - 1) * 2 + (1 if is_black else 0)
                        except Exception:
                            depth = 0
                    scored.append(((m.priority_score or 0.0, -depth), m))

                top_key = max(k for k, _ in scored)
                best = [m for k, m in scored if k == top_key]
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
                        is_free = is_free_training_profile(self.profile_name)
                        if (is_free and not td) or (mode == 'due' and td and td.next_due <= lookahead) or (mode == 'new' and not td):
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
        if self._user_settings_cache is not None:
            return self._user_settings_cache
        repo_name = self.repertoire_manager.active_repertoire_name
        if not repo_name or not self.user_session:
            return None
        settings = self._get_repo_user_settings(repo_name)
        if not settings:
            default_lvl = 999 if is_free_training_profile(self.profile_name) else 1
            settings = UserRepertoireSettings(repertoire_name=repo_name, rating=800.0, active_level=default_lvl, comment_language="auto", last_rating_update=datetime.datetime.now())
            self.user_session.add(settings)
            self.user_session.commit()
            if self._all_user_settings_cache is not None:
                self._all_user_settings_cache[repo_name] = settings
        self._user_settings_cache = settings
        return settings

    def _apply_rating_decay(self, settings):
        """
        Maintains settings.last_rating_update timestamp.
        True memory decay is naturally modeled per-move in get_current_elo()
        by treating overdue moves as acting 2 Leitner boxes down.
        """
        if not settings:
            return
        settings.last_rating_update = datetime.datetime.now()

    def _get_cached_levels(self) -> List[Dict[str, Any]]:
        if self._levels_cache is None:
            lvls = (self.repertoire_manager.get_repertoire_levels() if (self.repertoire_manager and hasattr(self.repertoire_manager, 'get_repertoire_levels')) else []) or []
            known_orders = {l.get('order') for l in lvls if l.get('order')}
            
            # Ensure every level present in moves has a level entry
            if self._moves_by_level:
                for lvl_ord in self._moves_by_level:
                    if lvl_ord not in known_orders:
                        lvls.append({
                            "id": lvl_ord,
                            "name": f"Level {lvl_ord}",
                            "order": lvl_ord,
                            "target_elo": 800 + 700 * lvl_ord
                        })
                        known_orders.add(lvl_ord)
                        
            if not lvls:
                lvls = [{"id": 1, "name": "Standard", "order": 1, "target_elo": 1500}]
            self._levels_cache = sorted(lvls, key=lambda x: x.get('order', 1))
        return self._levels_cache

    BOX_WEIGHTS = {
        0: 0.0,
        1: 0.20,
        2: 0.40,
        3: 0.65,
        4: 0.85,
        5: 1.00,  # 100% target reached
        6: 1.05,  # 105% deep retention bonus
        7: 1.10   # 110% permanent mastery bonus
    }

    def update_rating(self, move_id, success, auto_commit=True):
        """
        Updates the player's rating after a move is trained.
        Recalculates the rating based on the updated Leitner box status of the repertoire.
        """
        self._cached_elo = None
        new_elo = self.get_current_elo(use_cache=False)
        settings = self._get_rating_settings()
        if settings:
            settings.rating = float(new_elo)
            settings.last_rating_update = datetime.datetime.now()
        if auto_commit and self.user_session:
            self.user_session.commit()

    def get_current_elo(self, use_cache: bool = True, allow_stale_cache: bool = False) -> int:
        """
        Calculates the player's Elo rating using Tiered Leitner Repertoire Mastery:
        1. Moves in Box 5 are weighted at 100% (1.00), Box 6 at 105% (1.05), Box 7 at 110% (1.10).
        2. Overdue moves (next_due <= now) act as if they are 2 boxes down: max(0, box - 2).
        3. Tiered Level Slicing:
           - Level 1 moves scale rating from 800 to Level 1 Target Elo.
           - Level 2 moves scale rating from Level 1 Target Elo to Level 2 Target Elo.
           - Level 3 moves scale rating from Level 2 Target Elo to Level 3 Target Elo, etc.
           This ensures no Elo drop when unlocking higher levels and automatically weights
           foundational lower-level moves much more heavily than deep sidelines.
        """
        if use_cache and self._cached_elo is not None:
            return self._cached_elo

        if not self.user_session or not self.repertoire_manager or not self.repertoire_manager.active_repertoire_name:
            return 800

        if allow_stale_cache and (self._forward_moves_cache is None or self._td_cache is None):
            settings = self._get_rating_settings()
            if settings and settings.rating is not None:
                return int(round(max(800.0, float(settings.rating))))

        with self.user_session.no_autoflush:
            self._ensure_forward_cache()
            self._ensure_td_cache()

            levels = self._get_cached_levels()
            active_level = self.get_active_level()
            now = datetime.datetime.now()

            # Sum weighted scores per level for trained moves
            level_sums: Dict[int, float] = {}
            for lvl in levels:
                ord_num = lvl.get('order', 1)
                if ord_num <= active_level:
                    level_sums[ord_num] = 0.0

            if self._td_cache:
                for (fen, uci), td in self._td_cache.items():
                    m_cached = self._move_by_fen_uci_cache.get((fen, uci)) if self._move_by_fen_uci_cache else None
                    if m_cached is None:
                        continue
                    rm = self._rep_move_cache.get(m_cached.id) if self._rep_move_cache else None
                    if not rm:
                        continue
                    lvl_num = rm.level if rm.level is not None else 1
                    if lvl_num not in level_sums:
                        continue

                    is_due = bool(td.next_due and td.next_due <= now)
                    eff_box = max(0, td.box - 2) if is_due else td.box
                    w = self.BOX_WEIGHTS.get(eff_box, 0.0)
                    level_sums[lvl_num] += w

            # Compute tiered Elo
            elo = 800.0
            prev_target = 800.0

            for lvl in levels:
                ord_num = lvl.get('order', 1)
                if ord_num > active_level:
                    break
                target = float(lvl.get('target_elo') or 1500)
                delta = max(50.0, target - prev_target)

                moves_in_lvl = len(self._moves_by_level.get(ord_num, [])) if self._moves_by_level else 0
                mastery = (level_sums.get(ord_num, 0.0) / moves_in_lvl) if moves_in_lvl > 0 else 0.0

                elo += delta * mastery
                prev_target = max(prev_target + 50.0, target)

            calculated_elo = int(round(max(800.0, elo)))
            self._cached_elo = calculated_elo

            # Sync with settings.rating for persistence
            settings = self._get_rating_settings()
            if settings and settings.rating != float(calculated_elo):
                settings.rating = float(calculated_elo)
                settings.last_rating_update = now

            return calculated_elo

    def register_success(self, move_id, success, had_alternate_attempt=False, was_new=False, defer_commit=False):
        # In free training, if move is correct, mark it as learned for the session.
        # If move is wrong, don't create/update entry so it remains in the queue.
        if is_free_training_profile(self.profile_name):
            if not success: return # Keep as "due"
            
            self._ensure_forward_cache()
            self._ensure_td_cache()
            move = self._move_by_id_cache.get(move_id)
            if not move: return
            pos = self._pos_cache.get(move.from_position_id)
            if not pos: return
            fen = pos.fen
            
            repo_name = self.repertoire_manager.active_repertoire_name
            entry = self.user_session.query(TrainingData).filter_by(
                repertoire_name=repo_name,
                fen=fen,
                move_uci=move.uci
            ).first()
            if not entry:
                entry = TrainingData(repertoire_name=repo_name, fen=fen, move_uci=move.uci, box=7, next_due=datetime.datetime.max)
                self.user_session.add(entry)
            else:
                entry.box = 7
                entry.next_due = datetime.datetime.max
            self.user_session.commit()
            if self._td_cache is not None:
                self._td_cache[(fen, move.uci)] = entry
                if getattr(self, '_norm_td_cache', None) is not None:
                    self._norm_td_cache[(" ".join(fen.split()[:4]), move.uci)] = entry
            self._cached_elo = None
            settings = self._get_rating_settings()
            if settings:
                settings.stats_updated_at = None
            return

        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        # O(1) move lookup via ID index
        move = self._move_by_id_cache.get(move_id)
            
        if not move: return
        
        pos = self._pos_cache.get(move.from_position_id)
        if not pos: return
        fen = pos.fen
        
        entry = None
        if self._td_cache is not None:
            entry = self._td_cache.get((fen, move.uci))
            if entry is None and getattr(self, '_norm_td_cache', None) is not None:
                entry = self._norm_td_cache.get((_norm_fen4(fen), move.uci))
        elif self.user_session:
            entry = self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name, fen=fen, move_uci=move.uci).first()
        now = datetime.datetime.now()
        is_first_time = (entry is None or entry.box == 0)
        if not entry:
            entry = TrainingData(repertoire_name=self.repertoire_manager.active_repertoire_name, fen=fen, move_uci=move.uci, box=0, streak=0, next_due=now)
            self.user_session.add(entry)
            
        alt_policy = self.get_setting("alternate_move_policy") or "no_penalty"
        if success:
            if had_alternate_attempt and alt_policy == "keep_box":
                # Keep box the same (at least box 1 if it was 0)
                entry.box = max(1, entry.box)
                entry.streak += 1
            else:
                entry.box = min(7, entry.box + 1)
                entry.streak += 1
                
            if was_new or is_first_time:
                self.record_new_card_trained(defer_save=defer_commit)
        else:
            entry.box = 1
            entry.streak = 0
            
        entry.next_due = now + self.get_box_interval(entry.box)
        entry.last_review = now
        
        # Update cache in-place FIRST so rating calculation sees updated box
        if self._td_cache is not None:
            self._td_cache[(fen, move.uci)] = entry
            if getattr(self, '_norm_td_cache', None) is not None:
                self._norm_td_cache[(_norm_fen4(fen), move.uci)] = entry

        # Update Rating in-memory (no standalone commit)
        self.update_rating(move_id, success, auto_commit=False)

        # Update persistent & in-memory stats cache
        self._last_stats_cache = None
        settings = self._get_rating_settings()
        if settings:
            settings.stats_updated_at = None

        # Single batched atomic commit for TrainingData + Rating + StatsCache
        if defer_commit:
            self._has_pending_commit = True
        else:
            self.user_session.commit()
            self._has_pending_commit = False

    def capture_move_snapshot(self, move_id):
        """Captures a move's current SRS state before a mistake so mouse-slip undo can restore it."""
        if is_free_training_profile(self.profile_name):
            return None
        self._ensure_forward_cache()
        self._ensure_td_cache()

        move = self._move_by_id_cache.get(move_id)
        if not move:
            return None
        pos = self._pos_cache.get(move.from_position_id)
        if not pos:
            return None
        fen = pos.fen
        repo_name = self.repertoire_manager.active_repertoire_name

        entry = None
        if self._td_cache is not None:
            entry = self._td_cache.get((fen, move.uci))
            if entry is None and getattr(self, '_norm_td_cache', None) is not None:
                entry = self._norm_td_cache.get((_norm_fen4(fen), move.uci))
        elif self.user_session:
            entry = self.user_session.query(TrainingData).filter_by(
                repertoire_name=repo_name, fen=fen, move_uci=move.uci
            ).first()

        return {
            "move_id": move_id,
            "repertoire_name": repo_name,
            "fen": fen,
            "move_uci": move.uci,
            "existed": entry is not None,
            "box": entry.box if entry is not None else 0,
            "streak": entry.streak if entry is not None else 0,
            "next_due": entry.next_due if entry is not None else None,
            "last_review": entry.last_review if entry is not None else None,
        }

    def restore_move_snapshot(self, snapshot, defer_commit=False) -> bool:
        """Restores a move's pre-mistake SRS state captured by `capture_move_snapshot`."""
        if not snapshot or is_free_training_profile(self.profile_name):
            return False

        self._ensure_td_cache()
        repo_name = snapshot["repertoire_name"]
        fen = snapshot["fen"]
        move_uci = snapshot["move_uci"]
        norm_key = (_norm_fen4(fen), move_uci)

        entry = None
        if self._td_cache is not None:
            entry = self._td_cache.get((fen, move_uci))
            if entry is None and getattr(self, '_norm_td_cache', None) is not None:
                entry = self._norm_td_cache.get(norm_key)
        if entry is None and self.user_session:
            entry = self.user_session.query(TrainingData).filter_by(
                repertoire_name=repo_name, fen=fen, move_uci=move_uci
            ).first()

        if snapshot.get("existed"):
            if entry is None and self.user_session:
                entry = TrainingData(
                    repertoire_name=repo_name,
                    fen=fen,
                    move_uci=move_uci,
                )
                self.user_session.add(entry)
            if entry is not None:
                entry.box = snapshot["box"]
                entry.streak = snapshot["streak"]
                entry.next_due = snapshot["next_due"]
                entry.last_review = snapshot["last_review"]
                if self._td_cache is not None:
                    self._td_cache[(fen, move_uci)] = entry
                if getattr(self, '_norm_td_cache', None) is not None:
                    self._norm_td_cache[norm_key] = entry
        else:
            if entry is not None and self.user_session:
                self.user_session.delete(entry)
            if self._td_cache is not None:
                self._td_cache.pop((fen, move_uci), None)
            if getattr(self, '_norm_td_cache', None) is not None:
                self._norm_td_cache.pop(norm_key, None)

        self._cached_elo = None
        self._last_stats_cache = None
        settings = self._get_rating_settings()
        if settings:
            settings.stats_updated_at = None

        if defer_commit:
            self._has_pending_commit = True
        elif self.user_session:
            self.user_session.commit()
            self._has_pending_commit = False
        return True

    def flush_pending_commits(self):
        if getattr(self, '_settings_dirty', False):
            self.save_settings()
            self._settings_dirty = False
        if getattr(self, '_has_pending_commit', False) and self.user_session:
            try:
                self.user_session.commit()
            finally:
                self._has_pending_commit = False

    def is_move_new(self, move_id):
        self._ensure_forward_cache()
        self._ensure_td_cache()
        
        # O(1) move lookup via ID index
        move = self._move_by_id_cache.get(move_id)
            
        if not move: return False
        
        pos = self._pos_cache.get(move.from_position_id)
        if not pos: return False
        fen = pos.fen
        norm_fen = " ".join(fen.split()[:4]) if fen else ""
        norm_td = getattr(self, '_norm_td_cache', {}) or {}
        return (fen, move.uci) not in self._td_cache and (norm_fen, move.uci) not in norm_td
    
    def get_box_distribution(self):
        dist = {i: 0 for i in range(8)}
        self._ensure_td_cache()
        if self._td_cache is not None:
            for td in self._td_cache.values():
                if td.box in dist:
                    dist[td.box] += 1
            return dist

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
        self._ensure_td_cache()
        if self._td_cache is not None:
            for d in self._td_cache.values():
                date = d.next_due.date()
                if date < now.date(): date = now.date()
                if date in timeline: timeline[date] += 1
            return timeline

        with self.user_session.no_autoflush:
            for d in self.user_session.query(TrainingData).filter_by(repertoire_name=self.repertoire_manager.active_repertoire_name).all():
                date = d.next_due.date()
                if date < now.date(): date = now.date()
                if date in timeline: timeline[date] += 1
        return timeline
