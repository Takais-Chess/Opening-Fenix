import os
import sys
import json
import re
import tempfile
import difflib
import threading
import functools
import chess
from typing import Any, Optional, Dict, List

# --- PRECOMPILED REGEXES & CACHES ---
_RE_NAT_DIGITS = re.compile(r'(\d+)')
_RE_LEADING_MOVENUM = re.compile(r'^\d+\.')
_RE_PGN_TAGGED_COMMENT = re.compile(r'\[:?([a-zA-Z]{2})\]\s*([^\[]+)')
_RE_CSL_TAG = re.compile(r'\[%(?:csl|CSL)\s+([^\]]+)\]')
_RE_CAL_TAG = re.compile(r'\[%(?:cal|CAL)\s+([^\]]+)\]')
_RE_CB_TAG_ALL = re.compile(r'\[%[^\]]+\]')
_RE_HORIZ_WS = re.compile(r'[ \t]+')
_RE_MULTI_NL = re.compile(r'\n{3,}')
_RE_LEAD_CB_TAGS = re.compile(r'^((?:\[%\w+\s+[^\]]+\]\s*)+)')
_RE_TRAIL_CB_TAGS = re.compile(r'((?:\s*\[%\w+\s+[^\]]+\])+)$')
_RE_PARA_SPLIT = re.compile(r"(\n\s*\n+)")
_RE_BLANK_PARA = re.compile(r"^\n\s*\n+$")
_RE_CLEAN_PUNCT_NL = re.compile(r"\s*\n\s*([,.;:!?])")
_RE_CLEAN_PAREN_OPEN_NL = re.compile(r"\(\s*\n\s*")
_RE_CLEAN_PAREN_CLOSE_NL = re.compile(r"\s*\n\s*\)")
_RE_CLEAN_PARA_SPLIT = re.compile(r"\n\s*\n+")
_RE_MOVE_TOKEN = re.compile(r"^(\d+\.+)?\s*([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[\+#]?|[O-O0-]+)$", re.IGNORECASE)
_RE_LIST_ITEM = re.compile(r"^([-*•]|\d+[\.)])\s+")
_RE_JOIN_PUNCT = re.compile(r"\s+([,.;:!?])")
_RE_JOIN_PAREN_OPEN = re.compile(r"\(\s+")
_RE_JOIN_PAREN_CLOSE = re.compile(r"\s+\)")
_RE_MULTI_SPACE = re.compile(r" +")

_FROZEN_DEFAULT_DIR_CACHE: Dict[str, str] = {}
_CUSTOM_DATA_DIR_CACHE: Dict[str, Any] = {"key": None, "value": None, "configured_value": None}
_APP_RESTART_REQUESTED: bool = False
_SSL_CONTEXT_LOCK = threading.Lock()
_SSL_CONTEXT_CACHE: Dict[bool, Any] = {}

ELO_DISPLAY_MAP = {
    "low": "Hobby Spieler",
    "mid": "Vereins Spieler",
    "high": "Lichess Meister Elo",
    "masters": "Meister Datenbank"
}

VALID_ELO_KEYS = tuple(ELO_DISPLAY_MAP.keys())

ELO_INTERNAL_MAP = {v: k for k, v in ELO_DISPLAY_MAP.items()}


def parse_elo_list(raw) -> List[str]:
    """Parses a comma-separated string or iterable of Elo keys into a deduplicated canonical-order list."""
    if not raw:
        return []
    if isinstance(raw, str):
        items = [part.strip().lower() for part in raw.split(",") if part.strip()]
    else:
        items = [str(part).strip().lower() for part in raw if str(part).strip()]
    seen = set()
    valid = []
    for k in VALID_ELO_KEYS:
        if k in items and k not in seen:
            seen.add(k)
            valid.append(k)
    return valid


def serialize_elo_list(elos) -> str:
    """Serializes an iterable of Elo keys into a canonical comma-separated string."""
    return ",".join(parse_elo_list(elos))

# --- CASTLING NORMALIZATION CONSTANTS & HELPERS ---
CASTLING_SANS = {'O-O', 'O-O-O', '0-0', '0-0-0'}

CASTLE_FRC_TO_STD = {
    'e1h1': 'e1g1',
    'e1a1': 'e1c1',
    'e8h8': 'e8g8',
    'e8a8': 'e8c8',
}

CASTLE_STD_TO_FRC = {
    'e1g1': 'e1h1',
    'e1c1': 'e1a1',
    'e8g8': 'e8h8',
    'e8c8': 'e8a8',
}

CASTLING_ALT = {
    'e1g1': 'e1h1', 'e1h1': 'e1g1',
    'e1c1': 'e1a1', 'e1a1': 'e1c1',
    'e8g8': 'e8h8', 'e8h8': 'e8g8',
    'e8c8': 'e8a8', 'e8a8': 'e8c8',
}

def natural_sort_key(s: Any) -> list:
    """
    Key function for natural (alphanumeric) sorting.
    Splits string into numeric and non-numeric chunks so that e.g.:
    '1) Archangel' < '2) Archangel' < '11) Archangel'.
    Guaranteed type-safe by tagging chunks with (0, int) and (1, str).
    """
    if s is None:
        return []
    return [
        (0, int(text)) if text.isdigit() else (1, text.lower())
        for text in _RE_NAT_DIGITS.split(str(s))
        if text
    ]

def normalize_castling_uci(uci: str, san: str = None) -> str:
    """
    If a move is a castling move and in Chess960 format (e.g. e1h1),
    converts it to standard chess UCI format (e.g. e1g1).
    """
    if not uci:
        return uci
    uci_clean = uci.strip().lower()
    if san and san in CASTLING_SANS:
        return CASTLE_FRC_TO_STD.get(uci_clean, uci_clean)
    return uci_clean

def get_canonical_castling_uci(board, move) -> str:
    """
    Given a python-chess Board and Move, returns standard chess UCI.
    Guarantees that castling moves return e1g1, e1c1, e8g8, e8c8 instead of Chess960 king-captures-rook UCIs.
    """
    if board is not None and move is not None:
        try:
            if board.is_kingside_castling(move):
                import chess
                return "e1g1" if board.turn == chess.WHITE else "e8g8"
            elif board.is_queenside_castling(move):
                import chess
                return "e1c1" if board.turn == chess.WHITE else "e8c8"
        except Exception:
            pass
    return move.uci() if hasattr(move, "uci") else str(move)

def format_move_notation(fen_or_board, move_str: str, ply_depth: int = None) -> str:
    """
    Formats a chess move or sequence of moves with algebraic move numbers.
    Examples:
      - White move at ply 0 (1st move): 'e4' -> '1.e4'
      - Black move at ply 1 (1st move): 'c5' -> '1...c5'
      - White move at ply 4 (3rd move): 'd4' -> '3.d4'
      - 2-move sequence starting Black at ply 1: 'c5  Nf3' -> '1...c5  2.Nf3'
      - 2-move sequence starting White at ply 4: 'd4  cxd4' -> '3.d4  3...cxd4'
      - Diagnostic suffix: 'c5 (L1→L2)' -> '1...c5 (L1→L2)'
    """
    if not move_str or move_str.strip() in ("", "—", "-"):
        return move_str or ""

    # If already formatted with move number prefix (e.g. '3.d4', '1...c5'), return as-is
    if _RE_LEADING_MOVENUM.match(move_str.strip()):
        return move_str

    is_white = True
    fullmove = 1

    if ply_depth is not None:
        is_white = (ply_depth % 2 == 0)
        fullmove = (ply_depth // 2) + 1
    elif isinstance(fen_or_board, chess.Board):
        is_white = (fen_or_board.turn == chess.WHITE)
        fullmove = fen_or_board.fullmove_number
    elif isinstance(fen_or_board, str) and fen_or_board.strip():
        parts = fen_or_board.strip().split()
        if len(parts) > 1:
            is_white = (parts[1] == 'w')
        if len(parts) >= 6 and parts[5].isdigit():
            fullmove = int(parts[5])

    tokens = [t for t in move_str.strip().split() if t]
    res = []
    curr_white = is_white
    curr_move = fullmove

    for t in tokens:
        # Check if token is diagnostic tag like (L1→L2)
        if t.startswith('(') and t.endswith(')'):
            if res:
                res[-1] = f"{res[-1]} {t}"
            else:
                res.append(t)
            continue
        if curr_white:
            res.append(f"{curr_move}.{t}")
            curr_white = False
        else:
            res.append(f"{curr_move}...{t}")
            curr_white = True
            curr_move += 1

    return "  ".join(res)

def get_elo_display(internal_key):
    if not internal_key:
        return "N/A"
    from opening_fenix.core.translation import tr_ui
    key_lower = internal_key.lower()
    default_val = ELO_DISPLAY_MAP.get(key_lower, internal_key.capitalize())
    return tr_ui(f"elo.{key_lower}", default_val)

def get_elo_internal(display_name):
    if not display_name:
        return "high"
    cleaned = str(display_name).strip()
    # If already an internal key
    if cleaned.lower() in ELO_DISPLAY_MAP:
        return cleaned.lower()
    # Support legacy numeric ranges
    legacy_map = {
        "1200-1600": "low",
        "1600-2000": "mid",
        "2000+": "high",
        "master": "masters",
        "masters": "masters",
    }
    if cleaned.lower() in legacy_map:
        return legacy_map[cleaned.lower()]
    # First try the static German map (fast path)
    if cleaned in ELO_INTERNAL_MAP:
        return ELO_INTERNAL_MAP[cleaned]
    # Fall back: compare against current translated display names for each key
    try:
        from opening_fenix.core.translation import tr_ui
        for key in ELO_DISPLAY_MAP:
            if tr_ui(f"elo.{key}", ELO_DISPLAY_MAP[key]).lower() == cleaned.lower():
                return key
    except Exception:
        pass
    return "high"


def is_free_training_profile(name: str) -> bool:
    if not name:
        return False
    try:
        from opening_fenix.core.translation import tr_ui
        return name in ("Freies Training", "Open Training") or name == tr_ui("login.free_training", "Freies Training")
    except Exception:
        return name in ("Freies Training", "Open Training")

def get_last_active_profile_name() -> str:
    """
    Resolves the most recently active profile name from config.json or existing profile databases.
    Returns the profile name string, or 'Default' if no profiles exist.
    """
    user_dir = get_user_dir()
    config_path = os.path.join(user_dir, "config.json")
    profiles_dir = os.path.join(user_dir, "profiles")
    
    # 1. Try reading config.json
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            
            # Check last_profile
            last_prof = cfg.get("last_profile")
            if last_prof:
                if (is_free_training_profile(last_prof) or 
                        os.path.exists(os.path.join(profiles_dir, f"{last_prof}.db")) or 
                        os.path.exists(os.path.join(profiles_dir, f"{last_prof}_settings.json"))):
                    return last_prof

            # Check auto_login_profile
            auto_prof = cfg.get("auto_login_profile")
            if auto_prof:
                if (is_free_training_profile(auto_prof) or 
                        os.path.exists(os.path.join(profiles_dir, f"{auto_prof}.db")) or 
                        os.path.exists(os.path.join(profiles_dir, f"{auto_prof}_settings.json"))):
                    return auto_prof

            # Check profile_last_used dict (sorted by timestamp descending)
            last_used = cfg.get("profile_last_used", {})
            if isinstance(last_used, dict) and last_used:
                sorted_profs = sorted(last_used.items(), key=lambda x: str(x[1]), reverse=True)
                for p_name, _ in sorted_profs:
                    if (is_free_training_profile(p_name) or 
                            os.path.exists(os.path.join(profiles_dir, f"{p_name}.db")) or 
                            os.path.exists(os.path.join(profiles_dir, f"{p_name}_settings.json"))):
                        return p_name
        except Exception:
            pass

    # 2. Check profiles directory for any existing profiles
    if os.path.exists(profiles_dir):
        try:
            db_files = [f[:-3] for f in os.listdir(profiles_dir) if f.endswith(".db")]
            if db_files:
                return sorted(db_files)[0]
            json_settings = [f[:-14] for f in os.listdir(profiles_dir) if f.endswith("_settings.json")]
            if json_settings:
                return sorted(json_settings)[0]
        except Exception:
            pass

    return "Default"


def get_base_path():
    """Gibt den Basispfad der Anwendung zurück, um Probleme mit dem Arbeitsverzeichnis zu vermeiden."""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return meipass
        return os.path.dirname(os.path.abspath(sys.executable))
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

def get_default_user_dir():
    """Returns the default local directory where user data (profiles, config, repertoires) is stored."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        cached = _FROZEN_DEFAULT_DIR_CACHE.get(exe_dir)
        if cached is not None:
            return cached

        pfn = get_msix_package_family_name()
        if pfn:
            local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
            user_dir = os.path.join(local_appdata, "Packages", pfn, "LocalCache", "Roaming", "Opening Fenix")
            os.makedirs(user_dir, exist_ok=True)
            _FROZEN_DEFAULT_DIR_CACHE[exe_dir] = user_dir
            return user_dir

        # Never store user data inside Program Files even if elevated/writable!
        is_program_files = False
        try:
            exe_norm = os.path.normcase(os.path.abspath(exe_dir))
            for pf_env in ["ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"]:
                pf_val = os.environ.get(pf_env)
                if pf_val and exe_norm.startswith(os.path.normcase(os.path.abspath(pf_val))):
                    is_program_files = True
                    break
        except Exception:
            pass

        if not is_program_files:
            try:
                test_file = os.path.join(exe_dir, ".perm_test")
                with open(test_file, "w") as f:
                    f.write("1")
                os.remove(test_file)
                _FROZEN_DEFAULT_DIR_CACHE[exe_dir] = exe_dir
                return exe_dir
            except Exception:
                pass

        appdata = os.getenv("APPDATA") or os.path.expanduser("~")
        user_dir = os.path.join(appdata, "Opening Fenix")
        os.makedirs(user_dir, exist_ok=True)
        _FROZEN_DEFAULT_DIR_CACHE[exe_dir] = user_dir
        return user_dir

    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

def request_app_restart(flag: bool = True) -> None:
    """Flags the process to relaunch after main.py completes shutdown cleanup & cloud sync."""
    global _APP_RESTART_REQUESTED
    _APP_RESTART_REQUESTED = bool(flag)

def is_app_restart_requested() -> bool:
    return bool(_APP_RESTART_REQUESTED)

def get_configured_custom_data_dir():
    """
    Returns the configured custom_data_dir from master config.json even if the
    cloud drive / folder is temporarily offline or unmounted. Returns None if not configured.
    """
    default_dir = get_default_user_dir()
    master_cfg_path = os.path.join(default_dir, "config.json")
    try:
        st = os.stat(master_cfg_path)
        cache_key = (default_dir, st.st_mtime_ns, st.st_size)
    except OSError:
        _CUSTOM_DATA_DIR_CACHE["key"] = (default_dir, None, None)
        _CUSTOM_DATA_DIR_CACHE["value"] = None
        _CUSTOM_DATA_DIR_CACHE["configured_value"] = None
        return None

    if _CUSTOM_DATA_DIR_CACHE["key"] == cache_key:
        return _CUSTOM_DATA_DIR_CACHE.get("configured_value")

    configured = None
    try:
        with open(master_cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        custom_dir = cfg.get("custom_data_dir")
        if custom_dir and isinstance(custom_dir, str) and custom_dir.strip():
            configured = os.path.abspath(custom_dir.strip())
    except Exception:
        pass
    _CUSTOM_DATA_DIR_CACHE["key"] = cache_key
    _CUSTOM_DATA_DIR_CACHE["configured_value"] = configured
    _CUSTOM_DATA_DIR_CACHE["value"] = configured if (configured and os.path.exists(configured)) else None
    return configured

def is_cloud_sync_configured() -> bool:
    """Returns True if a non-default cloud sync folder is configured (even if currently offline)."""
    configured = get_configured_custom_data_dir()
    if not configured:
        return False
    default_dir = get_default_user_dir()
    return os.path.normcase(os.path.abspath(configured)) != os.path.normcase(os.path.abspath(default_dir))

def is_cloud_dir_offline() -> bool:
    """Returns True if cloud sync is configured, but the cloud folder is currently unreachable/unmounted."""
    if not is_cloud_sync_configured():
        return False
    configured = get_configured_custom_data_dir()
    return not bool(configured and os.path.exists(configured))

def get_custom_data_dir():
    """Returns the configured custom data directory if set and currently existing/online, otherwise None."""
    configured = get_configured_custom_data_dir()
    if configured and os.path.exists(configured):
        _CUSTOM_DATA_DIR_CACHE["value"] = configured
        return configured
    _CUSTOM_DATA_DIR_CACHE["value"] = None
    return None

def get_local_workspace_dir():
    """
    Returns the local working directory where active SQLite databases run.
    When a cloud sync folder (custom_data_dir) is configured, live databases ALWAYS run
    inside <default_user_dir>/local_workspace (even if the cloud drive is temporarily offline)
    so cloud sync clients never touch open SQLite .db / .db-wal files and offline launches
    never silently jump back to an outdated default_dir.
    """
    default_dir = get_default_user_dir()
    configured = get_configured_custom_data_dir()
    if configured and os.path.normcase(os.path.abspath(configured)) != os.path.normcase(os.path.abspath(default_dir)):
        ws_dir = os.path.join(default_dir, "local_workspace")
        os.makedirs(ws_dir, exist_ok=True)
        return ws_dir
    return default_dir

def set_custom_data_dir(target_dir):
    """Updates or clears the custom_data_dir (cloud sync folder) in the master config.json."""
    default_dir = get_default_user_dir()
    os.makedirs(default_dir, exist_ok=True)
    master_cfg_path = os.path.join(default_dir, "config.json")
    
    cfg = {}
    if os.path.exists(master_cfg_path):
        try:
            with open(master_cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    if target_dir is None or not str(target_dir).strip():
        # Merge any data from local_workspace back to default_dir before disconnecting cloud sync
        ws_dir = os.path.join(default_dir, "local_workspace")
        if os.path.exists(ws_dir):
            try:
                migrate_user_data(ws_dir, default_dir, overwrite_newer=True)
            except Exception:
                pass
        cfg.pop("custom_data_dir", None)
    else:
        target_dir = os.path.abspath(str(target_dir).strip())
        os.makedirs(target_dir, exist_ok=True)
        os.makedirs(os.path.join(target_dir, "repertoires"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "profiles"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "backups"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "cloud_sync"), exist_ok=True)
        readme_path = os.path.join(target_dir, "README_CLOUD_SYNC.txt")
        if not os.path.exists(readme_path):
            try:
                with open(readme_path, "w", encoding="utf-8") as rf:
                    rf.write(
                        "Opening Fenix — Cloud Sync Folder\n"
                        "=================================\n\n"
                        "• cloud_sync/ : Verified atomic snapshots & sync manifest used to sync between PCs.\n"
                        "• backups/    : Historical safety backups (including sync conflict backups).\n\n"
                        "Live SQLite databases run safely in your local AppData workspace to prevent\n"
                        "Google Drive / OneDrive database corruption. Do not manually edit files inside cloud_sync/.\n"
                    )
            except Exception:
                pass
        ws_dir = os.path.join(default_dir, "local_workspace")
        os.makedirs(os.path.join(ws_dir, "repertoires"), exist_ok=True)
        os.makedirs(os.path.join(ws_dir, "profiles"), exist_ok=True)
        os.makedirs(os.path.join(ws_dir, "backups"), exist_ok=True)
        cfg["custom_data_dir"] = target_dir

    with open(master_cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    _CUSTOM_DATA_DIR_CACHE["key"] = None
    _CUSTOM_DATA_DIR_CACHE["value"] = None
    _CUSTOM_DATA_DIR_CACHE["configured_value"] = None

def get_user_dir():
    """Returns the active local working directory (local_workspace when cloud sync is configured, else default)."""
    return get_local_workspace_dir()

def migrate_user_data(source_dir, target_dir, overwrite_newer: bool = False):
    """
    Copies repertoires, profiles, and backups from source_dir to target_dir.
    Returns a dictionary summarizing copied items.
    """
    import shutil
    summary = {"repertoires": 0, "profiles": 0, "backups": 0}
    if not source_dir or not target_dir:
        return summary
    if not os.path.exists(source_dir):
        return summary
    if os.path.abspath(source_dir) == os.path.abspath(target_dir):
        return summary

    os.makedirs(target_dir, exist_ok=True)

    for folder in ["repertoires", "profiles", "backups"]:
        src_folder = os.path.join(source_dir, folder)
        dest_folder = os.path.join(target_dir, folder)
        os.makedirs(dest_folder, exist_ok=True)
        if os.path.exists(src_folder) and os.path.isdir(src_folder):
            for item in os.listdir(src_folder):
                s_path = os.path.join(src_folder, item)
                d_path = os.path.join(dest_folder, item)
                try:
                    if os.path.isdir(s_path):
                        if not os.path.exists(d_path):
                            shutil.copytree(s_path, d_path)
                            summary[folder] += 1
                        else:
                            for sub_item in os.listdir(s_path):
                                sub_s = os.path.join(s_path, sub_item)
                                sub_d = os.path.join(d_path, sub_item)
                                if not os.path.exists(sub_d):
                                    if os.path.isdir(sub_s):
                                        shutil.copytree(sub_s, sub_d)
                                    else:
                                        shutil.copy2(sub_s, sub_d)
                                elif overwrite_newer and os.path.isfile(sub_s) and os.path.isfile(sub_d):
                                    if os.path.getmtime(sub_s) > os.path.getmtime(sub_d):
                                        shutil.copy2(sub_s, sub_d)
                            summary[folder] += 1
                    else:
                        if not os.path.exists(d_path):
                            shutil.copy2(s_path, d_path)
                            summary[folder] += 1
                        elif overwrite_newer and os.path.isfile(s_path) and os.path.isfile(d_path):
                            if os.path.getmtime(s_path) > os.path.getmtime(d_path):
                                shutil.copy2(s_path, d_path)
                                summary[folder] += 1
                except Exception as e:
                    print(f"Warning: Could not copy {s_path} to {d_path}: {e}")

    # Also copy config.json if not present in target
    src_cfg = os.path.join(source_dir, "config.json")
    dest_cfg = os.path.join(target_dir, "config.json")
    if os.path.exists(src_cfg) and not os.path.exists(dest_cfg):
        try:
            shutil.copy2(src_cfg, dest_cfg)
        except Exception:
            pass

    return summary

def ensure_user_data_seeded():
    r"""
    Ensures that default profiles, repertoires, and config.json bundled with the
    application are copied to the writable user_dir (%APPDATA%\Opening Fenix)
    on first run when installed in a read-only directory like Program Files.
    """
    user_dir = get_user_dir()
    
    # Locate candidate source directories for bundled assets
    sources = []
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        sources.append(exe_dir)
        if hasattr(sys, '_MEIPASS'):
            sources.append(sys._MEIPASS)
            
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    root_dir = os.path.dirname(parent_dir)
    sources.append(root_dir)

    import shutil

    # 1. Seed config.json if not present
    user_config = os.path.join(user_dir, "config.json")
    if not os.path.exists(user_config):
        for src in sources:
            src_config = os.path.join(src, "config.json")
            if os.path.exists(src_config):
                try:
                    shutil.copy(src_config, user_config)
                    break
                except Exception as e:
                    print(f"Warning: Could not copy config.json from {src_config}: {e}")

    cfg = {}
    cfg_dirty = False
    has_user_config = os.path.exists(user_config)
    if has_user_config:
        try:
            with open(user_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read user config: {e}")

    # Ensure build mode (is_public) is persistently recorded in user config if missing
    if has_user_config and "is_public" not in cfg:
        base_pub = os.path.exists(os.path.join(get_base_path(), "PUBLIC_VERSION")) or os.path.exists(os.path.join(get_base_path(), "public.flag"))
        cfg["is_public"] = bool(base_pub)
        cfg_dirty = True

    # 2. Ensure profiles directory exists (profiles are user-created only, never bundled)
    dest_profiles = os.path.join(user_dir, "profiles")
    os.makedirs(dest_profiles, exist_ok=True)

    # 3. Seed repertoires
    is_pub = is_public_version()
    repertoires_seeded = cfg.get("repertoires_seeded", False) if has_user_config else False

    # If repertoires_seeded is not yet recorded, check if repertoires already exist in user_dir
    dest_folder = os.path.join(user_dir, "repertoires")
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder, exist_ok=True)
    elif not repertoires_seeded and os.listdir(dest_folder):
        repertoires_seeded = True
        if has_user_config:
            cfg["repertoires_seeded"] = True
            cfg_dirty = True

    # Collect repertoires intentionally deleted via Cloud Sync so we never resurrect them
    deleted_cloud_repos = set()
    try:
        local_sync_state_path = os.path.join(user_dir, "local_sync_state.json")
        if os.path.exists(local_sync_state_path):
            with open(local_sync_state_path, "r", encoding="utf-8") as f_st:
                st_data = json.load(f_st)
                if isinstance(st_data, dict):
                    deleted_cloud_repos.update(st_data.get("known_deleted_repertoires", []))
        cloud_dir_active = get_custom_data_dir()
        if cloud_dir_active:
            manifest_path = os.path.join(cloud_dir_active, "cloud_sync", "sync_manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f_mf:
                    mf_data = json.load(f_mf)
                    if isinstance(mf_data, dict):
                        deleted_cloud_repos.update((mf_data.get("deleted_repertoires") or {}).keys())
    except Exception:
        pass

    dest_folder_abs = os.path.abspath(dest_folder)
    for src in sources:
        src_folder = os.path.join(src, "repertoires")
        if os.path.exists(src_folder) and os.path.isdir(src_folder):
            if os.path.abspath(src_folder) == dest_folder_abs:
                continue
            for item in os.listdir(src_folder):
                if item in deleted_cloud_repos:
                    continue
                s_path = os.path.join(src_folder, item)
                d_path = os.path.join(dest_folder, item)
                
                is_ex = is_example_repertoire(item)
                if is_pub and not is_ex:
                    continue
                if not is_pub and is_ex:
                    continue

                if not os.path.exists(d_path):
                    try:
                        if os.path.isdir(s_path):
                            shutil.copytree(s_path, d_path)
                        else:
                            shutil.copy(s_path, d_path)
                    except Exception as e:
                        print(f"Warning: Could not seed {item} into {dest_folder}: {e}")

    # Mark repertoires as seeded in config.json after seeding
    if not repertoires_seeded and has_user_config:
        cfg["repertoires_seeded"] = True
        cfg_dirty = True

    if cfg_dirty and has_user_config:
        try:
            with open(user_config, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save user config: {e}")

def _update_lichess_delay_config(delay_value):
    """Safely reads, updates, and writes the lichess_delay to the config file."""
    config = {}
    config_path = os.path.join(get_user_dir(), "config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
    except (IOError, json.JSONDecodeError):
        print("WARN: Could not read config.json. A new one will be created.")
        config = {}
    
    config["lichess_delay"] = delay_value
    
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
        print(f"INFO: Saved Lichess delay of {delay_value:.3f}s to config.json")
    except IOError:
        print("ERROR: Could not write to config.json.")

def get_configured_engine_hash(default: int = 256) -> int:
    """Reads engine_hash from config.json, returning configured MB (default 256)."""
    try:
        config_path = os.path.join(get_user_dir(), "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                val = cfg.get("engine_hash")
                if val is not None:
                    return max(16, int(val))
    except Exception:
        pass
    return default

def normalize_fen(board):
    return " ".join(board.fen().split(" ")[:4])

def validate_safe_name(name: str, label: str = "Name") -> str:
    """Validates that a repertoire or profile name cannot traverse directories."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    if "\x00" in name or "/" in name or "\\" in name or name.strip() in (".", ".."):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def write_json_atomic(path: str, data: dict, indent: int = 4) -> None:
    """Atomically writes a JSON file via a temporary file in the same directory."""
    import tempfile
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def get_repertoire_dir(repo_name, is_test=None):
    """
    Returns the path to the repertoire's specific folder.
    Now more robust: if is_test is None, it checks both the regular and test subfolders.
    """
    validate_safe_name(repo_name, "Repertoire name")
    repo_base = os.path.join(get_user_dir(), "repertoires")
    
    # If is_test is explicitly provided, respect it
    if is_test is True:
        return os.path.join(repo_base, "test", repo_name)
    elif is_test is False:
        return os.path.join(repo_base, repo_name)
        
    # If is_test is None, we probe both locations
    regular_path = os.path.join(repo_base, repo_name)
    if os.path.isdir(regular_path):
        return regular_path
    test_path = os.path.join(repo_base, "test", repo_name)
    if os.path.isdir(test_path):
        return test_path

    # Fallback for frozen executable if app was installed to Program Files
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        exe_regular = os.path.join(exe_dir, "repertoires", repo_name)
        exe_test = os.path.join(exe_dir, "repertoires", "test", repo_name)
        if os.path.exists(exe_regular) and os.path.isdir(exe_regular):
            return exe_regular
        if os.path.exists(exe_test) and os.path.isdir(exe_test):
            return exe_test
            
        if hasattr(sys, '_MEIPASS'):
            mei_regular = os.path.join(sys._MEIPASS, "repertoires", repo_name)
            mei_test = os.path.join(sys._MEIPASS, "repertoires", "test", repo_name)
            if os.path.exists(mei_regular) and os.path.isdir(mei_regular):
                return mei_regular
            if os.path.exists(mei_test) and os.path.isdir(mei_test):
                return mei_test
        
    # Default fallback if neither exists (using the "test" prefix heuristic for new creations)
    is_test_by_name = repo_name.lower().startswith("test")
    if is_test_by_name:
        return test_path
    else:
        return regular_path

def get_repertoire_db_path(repo_name, is_test=None):
    """
    Returns the path to the repertoire's .db file.
    Uses the robust get_repertoire_dir for lookups.
    """
    # Probing for the directory first
    repo_dir = get_repertoire_dir(repo_name, is_test)
    return os.path.join(repo_dir, f"{repo_name}.db")


def initialize_repertoire_assets(repo_dir):
    """Creates the default PGN files and Tactics folder for a new repertoire."""
    if not os.path.exists(repo_dir):
        os.makedirs(repo_dir)
        
    assets = [
        "Model Games.pgn",
        "Typical Motives.pgn"
    ]
    
    for asset in assets:
        path = os.path.join(repo_dir, asset)
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write("") # Create empty file
                
    tactics_dir = os.path.join(repo_dir, "Tactics")
    if not os.path.exists(tactics_dir):
        os.makedirs(tactics_dir)
        tactics_pgn = os.path.join(tactics_dir, "Tactics.pgn")
        with open(tactics_pgn, "w") as f:
            f.write("")

def migrate_repertoire_storage():
    """Migrates existing .db files in the repertoires/ directory to their own subfolders."""
    repo_base = os.path.join(get_user_dir(), "repertoires")
    if not os.path.exists(repo_base):
        return
        
    # Get all .db files directly in the repertoires folder
    legacy_files = [f for f in os.listdir(repo_base) if f.endswith(".db") and os.path.isfile(os.path.join(repo_base, f))]
    
    if not legacy_files:
        return # Nothing to migrate
        
    print(f"INFO: Migrating {len(legacy_files)} legacy repertoires to new folder structure...")
    
    import shutil
    
    for f in legacy_files:
        repo_name = f[:-3]
        old_db_path = os.path.join(repo_base, f)
        
        is_test = repo_name.lower().startswith("test")
        new_dir = get_repertoire_dir(repo_name, is_test)
        new_db_path = get_repertoire_db_path(repo_name, is_test)
        
        try:
            if not os.path.exists(new_dir):
                os.makedirs(new_dir)
                
            shutil.move(old_db_path, new_db_path)
            
            # Check for auxiliary files (WAL, SHM)
            for ext in [".db-wal", ".db-shm"]:
                old_aux = os.path.join(repo_base, f"{repo_name}{ext}")
                new_aux = os.path.join(new_dir, f"{repo_name}{ext}")
                if os.path.exists(old_aux):
                    shutil.move(old_aux, new_aux)
                    
            # Initialize assets
            initialize_repertoire_assets(new_dir)
            
        except Exception as e:
            print(f"ERROR: Failed to migrate repertoire {repo_name}: {e}")


def localize_san(san: str, language: str = 'en') -> str:
    """
    Converts English SAN (Standard Algebraic Notation) to a localized version.
    Currently supports German ('de').
    """
    if not san or language == 'en':
        return san
    
    if language == 'de':
        # Piece mappings: K=K, Q=D (Dame), R=T (Turm), B=L (Läufer), N=S (Springer)
        # Note: P (Pawn) is implicit in SAN and doesn't need mapping unless it's a promotion.
        
        # 1. Handle piece moves (start of string)
        # King (K) is same in both languages.
        piece_map = {"Q": "D", "R": "T", "B": "L", "N": "S"}
        if san[0] in piece_map:
            san = piece_map[san[0]] + san[1:]
            
        # 2. Handle promotions (e.g., e8=Q)
        for eng, ger in piece_map.items():
            san = san.replace(f"={eng}", f"={ger}")
            
        return san
        
    return san


def is_public_version() -> bool:
    """
    Returns True if running the public release/version, False if private.
    Checks:
    1. Environment variable FENIX_SHARE_BUILD == '1', FENIX_PUBLIC_BUILD == '1', or APP_BUILD_TYPE == 'Public'
    2. Bundled 'PUBLIC_VERSION' or 'public.flag' file in base path or exe path
    3. config.json 'is_public' setting (explicitly True/False)
    4. Marker file in user path
    """
    env_share = os.environ.get('FENIX_SHARE_BUILD') == '1'
    env_public = os.environ.get('FENIX_PUBLIC_BUILD') == '1'
    env_build_type = os.environ.get('APP_BUILD_TYPE', '').lower() == 'public'
    if env_share or env_public or env_build_type:
        return True

    # Check for marker file in app bundle first (get_base_path() or exe dir)
    bundle_dirs = [get_base_path()]
    if getattr(sys, 'frozen', False):
        bundle_dirs.append(os.path.dirname(sys.executable))
    for dir_path in bundle_dirs:
        if os.path.exists(os.path.join(dir_path, "PUBLIC_VERSION")) or os.path.exists(os.path.join(dir_path, "public.flag")):
            return True

    # Check config.json in user dir or base dir
    for dir_path in [get_user_dir(), get_base_path()]:
        config_path = os.path.join(dir_path, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if cfg.get("is_public") is False:
                        return False
                    if cfg.get("is_public") is True:
                        return True
            except Exception:
                pass

    # Check for marker file in user_dir
    if os.path.exists(os.path.join(get_user_dir(), "PUBLIC_VERSION")) or os.path.exists(os.path.join(get_user_dir(), "public.flag")):
        return True

    return False


def get_msix_package_family_name() -> Optional[str]:
    """
    Returns the Windows MSIX Package Family Name (e.g. 'TakaisChess.OpeningFenixChess_re6rtymtb0s24')
    if the current process is running inside an MSIX package, else None.
    """
    if sys.platform != 'win32':
        return None

    try:
        import ctypes
        length = ctypes.c_uint32(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFamilyName(ctypes.byref(length), None)
        # ERROR_INSUFFICIENT_BUFFER (122) means the process has a package family name
        if rc == 122 and length.value > 0:
            buf = ctypes.create_unicode_buffer(length.value)
            rc2 = ctypes.windll.kernel32.GetCurrentPackageFamilyName(ctypes.byref(length), buf)
            if rc2 == 0 and buf.value:
                return buf.value
    except Exception:
        pass

    return None


def get_real_temp_dir() -> str:
    """
    Returns a non-virtualized physical temp directory suitable for passing paths to
    external processes (e.g. headless Edge/Chrome) when running inside MSIX.
    Falls back to tempfile.gettempdir() outside MSIX or on error.
    """
    try:
        pfn = get_msix_package_family_name()
        if pfn:
            local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
            real_tmp = os.path.join(local_appdata, "Packages", pfn, "LocalCache", "Local", "Temp")
            os.makedirs(real_tmp, exist_ok=True)
            return real_tmp
    except Exception:
        pass

    return tempfile.gettempdir()


def is_store_version() -> bool:
    """
    Returns True if running as a Microsoft Store (MSIX) package.
    Checks:
    1. Environment variable FENIX_STORE_BUILD == '1'
    2. Bundled 'STORE_VERSION' or 'store.flag' file in base path or exe path
    3. Windows MSIX package identity via GetCurrentPackageFullName
    """
    if os.environ.get('FENIX_STORE_BUILD') == '1':
        return True

    bundle_dirs = [get_base_path()]
    if getattr(sys, 'frozen', False):
        bundle_dirs.append(os.path.dirname(sys.executable))
    for dir_path in bundle_dirs:
        if os.path.exists(os.path.join(dir_path, "STORE_VERSION")) or os.path.exists(os.path.join(dir_path, "store.flag")):
            return True

    if sys.platform == 'win32':
        try:
            import ctypes
            length = ctypes.c_uint32(0)
            # ERROR_INSUFFICIENT_BUFFER (122) means the process has a package identity (MSIX)
            # APPMODEL_ERROR_NO_PACKAGE (15700) means it does not
            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
            if rc in (0, 122):
                return True
        except Exception:
            pass

    return False


def is_example_repertoire(name: str) -> bool:
    """
    Returns True if the repertoire name indicates an example/sample course/repertoire.
    """
    if not name:
        return False
    name_lower = name.lower()
    return "example" in name_lower or "sample" in name_lower


def filter_repertoires_by_build_type(repo_names: list[str]) -> list[str]:
    """
    Filters repertoires based on the build type.
    All user-created and seeded repertoires in the user directory remain visible.
    """
    return list(repo_names)


def get_multilingual_comment_dict(raw_comment: str, default_lang: str = "de") -> dict:
    """
    Parses a raw position comment string.
    Returns a dictionary mapping language codes (e.g. 'de', 'en') to text strings.
    If raw_comment is a plain string, returns a dict with default_lang key.
    """
    if not raw_comment or not raw_comment.strip():
        return {}
    raw = raw_comment.strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {k.lower(): str(v).strip() for k, v in data.items() if v and str(v).strip()}
        except Exception:
            pass
    target = default_lang.lower() if default_lang else "de"
    return {target: raw}


def parse_comment(raw_comment: str, lang: str = "de", default_lang: Optional[str] = None) -> str:
    """
    Resolves a position comment for a target language code (e.g. 'de', 'en') or 'all'.
    Returns the comment in the target language, or all available languages if 'all',
    or an empty string if not available.
    Does not fall back to other languages if the requested language is missing.
    """
    if not raw_comment or not raw_comment.strip():
        return ""
    
    raw = raw_comment.strip()
    target_lang = lang.lower() if lang else "de"

    # Multilingual JSON format
    if raw.startswith("{") and raw.endswith("}"):
        comment_dict = get_multilingual_comment_dict(raw)
        if comment_dict:
            if target_lang == "all":
                valid_items = {k: v for k, v in comment_dict.items() if v and str(v).strip()}
                if not valid_items:
                    return ""
                sorted_keys = sorted(valid_items.keys(), key=lambda k: ({"de": 0, "en": 1}.get(k, 2), k))
                return "\n".join(f"[{k.upper()}] {valid_items[k]}" for k in sorted_keys)
            return comment_dict.get(target_lang, "")
        return ""

    # Inline PGN tagged format: [:de] ... [:en] ...
    if "[:" in raw or (raw.startswith("[") and not raw.startswith("[%")):
        tagged = parse_pgn_tagged_comment(raw)
        if tagged:
            if target_lang == "all":
                valid_items = {k: v for k, v in tagged.items() if v and str(v).strip()}
                if not valid_items:
                    return ""
                sorted_keys = sorted(valid_items.keys(), key=lambda k: ({"de": 0, "en": 1}.get(k, 2), k))
                return "\n".join(f"[{k.upper()}] {valid_items[k]}" for k in sorted_keys)
            return tagged.get(target_lang, "")

    # Plain text comment (non-JSON)
    def_lang = default_lang.lower() if default_lang else "de"
    if target_lang in (def_lang, "all"):
        return raw
    return ""


def resolve_auto_comment_language(
    app_lang: Optional[str],
    available_langs: Optional[List[str]] = None,
    repo_meta_lang: Optional[str] = None,
    fallback_lang: Optional[str] = None,
) -> str:
    """
    Resolves 'auto' comment language for a repertoire.
    Prefers the app language if present in available_langs; otherwise falls back to
    repo_meta_lang (if available), 'en' (if available), the first available language,
    or finally app_lang / repo_meta_lang / fallback_lang / 'de'.
    """
    available = [l.lower() for l in (available_langs or []) if l]
    app_l = app_lang.lower() if app_lang and app_lang != "auto" else None
    meta_l = repo_meta_lang.lower() if repo_meta_lang and repo_meta_lang != "auto" else None
    fb_l = fallback_lang.lower() if fallback_lang and fallback_lang != "auto" else "de"

    if available:
        if app_l and app_l in available:
            return app_l
        if meta_l and meta_l in available:
            return meta_l
        if "en" in available:
            return "en"
        return available[0]

    return app_l or meta_l or fb_l

def format_multilingual_comment(comment_dict: dict) -> str:
    """
    Serializes a dictionary of language comments (e.g. {'de': '...', 'en': '...'})
    into a database-ready comment string.
    If only one language is present, returns plain text string.
    If multiple languages are present, returns a JSON string.
    """
    if not comment_dict:
        return ""
    cleaned = {k.lower(): str(v).strip() for k, v in comment_dict.items() if v and str(v).strip()}
    if not cleaned:
        return ""
    if len(cleaned) == 1 and "de" in cleaned:
        return cleaned["de"]
    return json.dumps(cleaned, ensure_ascii=False)


def matches_variation_name(raw_name: Optional[str], target_name: Optional[str]) -> bool:
    """
    Checks if a raw variation name (plain text or multilingual JSON) matches a target variation name.
    Matches either exact string, or any language value inside the JSON dictionary (case-insensitive).
    """
    if not raw_name or not target_name:
        return False
    r_str = str(raw_name).strip()
    t_str = str(target_name).strip()
    if r_str == t_str or r_str.lower() == t_str.lower():
        return True
    if r_str.startswith('{') and r_str.endswith('}'):
        v_dict = get_multilingual_variation_dict(r_str)
        t_low = t_str.lower()
        return any(str(v).strip().lower() == t_low for v in v_dict.values())
    return False


def parse_pgn_tagged_comment(comment_text: str) -> dict:
    """
    Parses inline PGN language tags like '[:de] Deutscher Text [:en] English text'
    or '[de] Deutscher Text [en] English text'.
    Returns a dictionary mapping language codes to comment strings.
    """
    if not comment_text or "[" not in comment_text:
        return {}
    matches = _RE_PGN_TAGGED_COMMENT.findall(comment_text)
    if matches:
        res = {}
        for lang, text in matches:
            t = text.strip()
            if t:
                res[lang.lower()] = t
        return res
    return {}


# --- MULTILINGUAL VARIATION HELPERS ---

def get_multilingual_variation_dict(raw_name: str, default_lang: str = "de") -> dict:
    """
    Parses a raw variation name string.
    Returns a dictionary mapping language codes (e.g. 'de', 'en') to variation name strings.
    If raw_name is a plain string, returns a dict with default_lang key.
    """
    if not raw_name or not str(raw_name).strip():
        return {}
    raw = str(raw_name).strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {k.lower(): str(v).strip() for k, v in data.items() if v and str(v).strip()}
        except Exception:
            pass
    target = default_lang.lower() if default_lang else "de"
    return {target: raw}


@functools.lru_cache(maxsize=4096)
def parse_variation_name(raw_name: str, lang: str = "de", default_lang: Optional[str] = None) -> str:
    """
    Resolves a variation name for a target language code (e.g. 'de', 'en') or 'all'.
    Falls back gracefully to default_lang or any available language if the requested language is missing,
    ensuring variation names never appear blank in the UI.
    """
    if not raw_name or not str(raw_name).strip():
        return ""
    raw = str(raw_name).strip()
    target_lang = lang.lower() if lang else "de"
    if target_lang == "auto":
        target_lang = (default_lang or "de").lower()

    if raw.startswith("{") and raw.endswith("}"):
        v_dict = get_multilingual_variation_dict(raw, default_lang=default_lang or "de")
        if not v_dict:
            return ""
        if target_lang == "all":
            valid_items = {k: v for k, v in v_dict.items() if v and str(v).strip()}
            if not valid_items:
                return ""
            if len(valid_items) == 1:
                return next(iter(valid_items.values()))
            sorted_keys = sorted(valid_items.keys(), key=lambda k: ({"de": 0, "en": 1}.get(k, 2), k))
            return " / ".join(f"[{k.upper()}] {valid_items[k]}" for k in sorted_keys)
        
        if target_lang in v_dict and v_dict[target_lang]:
            return v_dict[target_lang]
        
        # Graceful fallback: default_lang, then de, then first available
        def_k = (default_lang or "de").lower()
        if def_k in v_dict and v_dict[def_k]:
            return v_dict[def_k]
        if "de" in v_dict and v_dict["de"]:
            return v_dict["de"]
        return next(iter(v_dict.values()))

    # Plain text variation name
    return raw


def format_multilingual_variation(variation_dict: dict) -> str:
    """
    Serializes a dictionary of language variation names (e.g. {'de': '...', 'en': '...'})
    into a database-ready string.
    If only one language is present and it is 'de', returns a plain text string for backward compatibility.
    Otherwise returns a JSON string.
    """
    if not variation_dict:
        return ""
    cleaned = {k.lower(): str(v).strip() for k, v in variation_dict.items() if v and str(v).strip()}
    if not cleaned:
        return ""
    if len(cleaned) == 1 and "de" in cleaned:
        return cleaned["de"]
    return json.dumps(cleaned, ensure_ascii=False)


# --- CHESSBASE PGN ANNOTATIONS ([%csl ...] & [%cal ...]) ---

CHESSBASE_COLOR_MAP = {
    'G': 'green',
    'R': 'red',
    'Y': 'yellow',
    'B': 'blue',
    'O': 'orange',
}

COLOR_TO_CHESSBASE_CODE = {
    'green': 'G',
    'red': 'R',
    'yellow': 'Y',
    'blue': 'B',
    'orange': 'O',
}


def parse_chessbase_annotations(text: str, clean: bool = True) -> dict:
    """
    Parses ChessBase / PGN standard colored square ([%csl ...]) and colored arrow ([%cal ...]) tags.
    Example: "[%csl Re5,Gd4] [%cal Ge2e4] Good move!"
    Returns:
        {
            "clean_text": "Good move!",
            "highlights": [(chess.E5, "red"), (chess.D4, "green")],
            "arrows": [(chess.E2, chess.E4, "green")]
        }
    """
    if not text or not isinstance(text, str):
        return {"clean_text": "", "highlights": [], "arrows": []}

    highlights = []
    arrows = []

    if "[%" in text:
        # 1. Parse [%csl ...] tags (Colored Squares List)
        for block in _RE_CSL_TAG.findall(text):
            for item in block.split(','):
                item = item.strip()
                if len(item) >= 3:
                    color_char = item[0].upper()
                    sq_str = item[1:].strip().lower()
                    color_name = CHESSBASE_COLOR_MAP.get(color_char, "green")
                    try:
                        sq = chess.parse_square(sq_str)
                        highlights.append((sq, color_name))
                    except (ValueError, IndexError):
                        pass

        # 2. Parse [%cal ...] tags (Colored Arrows List)
        for block in _RE_CAL_TAG.findall(text):
            for item in block.split(','):
                item = item.strip()
                if len(item) >= 5:
                    color_char = item[0].upper()
                    from_str = item[1:3].strip().lower()
                    to_str = item[3:5].strip().lower()
                    color_name = CHESSBASE_COLOR_MAP.get(color_char, "green")
                    try:
                        from_sq = chess.parse_square(from_str)
                        to_sq = chess.parse_square(to_str)
                        arrows.append((from_sq, to_sq, color_name))
                    except (ValueError, IndexError):
                        pass

    clean_res = clean_chessbase_annotations(text) if clean else ""

    return {
        "clean_text": clean_res,
        "highlights": highlights,
        "arrows": arrows,
    }


def clean_chessbase_annotations(text: str) -> str:
    """Removes [%csl ...], [%cal ...], and other [%...] annotation tags from comment text for clean UI presentation."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = _RE_CB_TAG_ALL.sub('', text) if "[%" in text else text
    lines = [_RE_HORIZ_WS.sub(' ', line).strip() for line in cleaned.split('\n')]
    # Remove empty lines at beginning and end, collapse 3+ newlines to 2
    res = '\n'.join(lines).strip()
    return _RE_MULTI_NL.sub('\n\n', res) if '\n\n\n' in res else res


def _resolve_chessbase_color_code(col) -> str:
    """Converts QColor, hex string, or color name to ChessBase 1-character code (G, R, Y, B, O)."""
    if isinstance(col, str):
        c_lower = col.lower()
        if c_lower in COLOR_TO_CHESSBASE_CODE:
            return COLOR_TO_CHESSBASE_CODE[c_lower]
        if c_lower in ['g', 'r', 'y', 'b', 'o']:
            return c_lower.upper()

    if hasattr(col, 'red') and hasattr(col, 'green') and hasattr(col, 'blue'):
        r, g, b = col.red(), col.green(), col.blue()
        if r > 180 and g > 140 and b < 80:
            return 'Y'  # Yellow
        elif r > 180 and g > 80 and b < 80:
            return 'O'  # Orange
        elif r > 180 and g < 100 and b < 100:
            return 'R'  # Red
        elif b > 180 and r < 120:
            return 'B'  # Blue
        elif g > 150 and r < 120:
            return 'G'  # Green

    return 'G'


def serialize_chessbase_annotations(arrows=None, highlights=None, clean_text: str = "") -> str:
    """
    Serializes arrows and square highlights into standard ChessBase PGN tags [%csl ...] and [%cal ...].
    Optionally prepends them to clean_text.
    """
    tags = []

    # 1. Highlights [%csl ...]
    if highlights:
        hl_items = highlights.items() if isinstance(highlights, dict) else highlights
        entries = []
        for item in hl_items:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                sq, col = item[0], item[1]
                code = _resolve_chessbase_color_code(col)
                sq_name = chess.square_name(sq)
                entries.append(f"{code}{sq_name}")
        if entries:
            entries.sort()
            tags.append(f"[%csl {','.join(entries)}]")

    # 2. Arrows [%cal ...]
    if arrows:
        arrow_items = arrows.items() if isinstance(arrows, dict) else arrows
        entries = []
        for item in arrow_items:
            if isinstance(item, (tuple, list)):
                if len(item) == 2 and isinstance(item[0], (tuple, list)):
                    (from_sq, to_sq), col = item
                elif len(item) == 3:
                    from_sq, to_sq, col = item[0], item[1], item[2]
                elif len(item) == 2:
                    (from_sq, to_sq), col = item[0], item[1]
                else:
                    continue
                code = _resolve_chessbase_color_code(col)
                arrow_name = f"{chess.square_name(from_sq)}{chess.square_name(to_sq)}"
                entries.append(f"{code}{arrow_name}")
        if entries:
            entries.sort()
            tags.append(f"[%cal {','.join(entries)}]")

    tag_str = " ".join(tags).strip()
    clean = clean_chessbase_annotations(clean_text).strip() if clean_text else ""
    if tag_str and clean:
        return f"{tag_str} {clean}".strip()
    return tag_str or clean


def update_comment_with_annotations(comment_data, arrows=None, highlights=None) -> str:
    """
    Given a raw comment (plain string or JSON multilingual string) and board arrows/highlights,
    updates the comment to include the serialized [%csl ...] and [%cal ...] tags.
    """
    tag_str = serialize_chessbase_annotations(arrows, highlights, clean_text="")

    if not comment_data:
        return tag_str

    if isinstance(comment_data, str) and comment_data.strip().startswith("{") and comment_data.strip().endswith("}"):
        comment_dict = get_multilingual_comment_dict(comment_data)
        updated = {}
        for lang, text in comment_dict.items():
            clean = clean_chessbase_annotations(text)
            if tag_str and clean:
                updated[lang] = f"{tag_str} {clean}".strip()
            elif tag_str:
                updated[lang] = tag_str
            else:
                updated[lang] = clean
        return format_multilingual_comment(updated)
    else:
        clean = clean_chessbase_annotations(str(comment_data))
        if tag_str and clean:
            return f"{tag_str} {clean}".strip()
        elif tag_str:
            return tag_str
        return clean


# --- POSITION EVALUATION SYMBOLS & CONTENT DETECTION ---

EVAL_SYMBOLS = ["+−", "±", "⩲", "=", "∞", "⇆", "⩱", "∓", "−+"]
ALL_EVAL_SYMBOLS = ["+−", "+-", "±", "⩲", "=", "∞", "⇆", "⩱", "∓", "−+", "-+"]


def extract_eval_symbol(text: str):
    """
    Extracts a chess position evaluation symbol from a comment string if present.
    Recognizes symbols alone, on the last line, or trailing after whitespace.
    Normalizes '+-' -> '+−' and '-+' -> '−+'.
    """
    if not text or not isinstance(text, str):
        return None
    cleaned = clean_chessbase_annotations(text).strip()
    if not cleaned:
        return None

    def _normalize(sym: str) -> str:
        if sym == "+-": return "+−"
        if sym == "-+": return "−+"
        return sym

    if cleaned in ALL_EVAL_SYMBOLS:
        return _normalize(cleaned)

    lines = cleaned.split('\n')
    last_line = lines[-1].strip()
    if last_line in ALL_EVAL_SYMBOLS:
        return _normalize(last_line)

    tokens = last_line.split()
    if tokens and tokens[-1] in ALL_EVAL_SYMBOLS:
        return _normalize(tokens[-1])

    return None


def strip_eval_symbol(text: str) -> str:
    """
    Removes any trailing evaluation symbol from the comment text.
    Preserves all preceding text and line breaks.
    """
    if not text or not isinstance(text, str):
        return ""
    s = text.rstrip()
    if not s:
        return ""
    if s.strip() in ALL_EVAL_SYMBOLS:
        return ""

    lines = s.split('\n')
    if lines:
        last_line = lines[-1].strip()
        if last_line in ALL_EVAL_SYMBOLS:
            lines.pop()
            return '\n'.join(lines).rstrip()

        tokens = lines[-1].split()
        if tokens and tokens[-1] in ALL_EVAL_SYMBOLS:
            tokens.pop()
            lines[-1] = " ".join(tokens)
            return '\n'.join(lines).rstrip()

    return s


def has_meaningful_comment(text: str) -> bool:
    """
    Checks if a comment string contains actual verbal commentary,
    ignoring ChessBase drawing tags ([%csl ...], [%cal ...]) and evaluation symbols (+-, =, etc.).
    Returns True ONLY if there is actual written text.
    """
    if not text or not isinstance(text, str):
        return False
    clean = clean_chessbase_annotations(text)
    without_eval = strip_eval_symbol(clean)
    return bool(without_eval.strip())


def get_lang_display_label(code: str) -> str:
    """Returns a friendly display label with flag for common chess language codes."""
    if not code:
        return ""
    c = code.lower().strip()
    flags = {
        "en": "🇬🇧 EN (English)",
        "de": "🇩🇪 DE (Deutsch)",
        "es": "🇪🇸 ES (Español)",
        "fr": "🇫🇷 FR (Français)",
        "it": "🇮🇹 IT (Italiano)",
        "ru": "🇷🇺 RU (Русский)",
        "pl": "🇵🇱 PL (Polski)",
        "zh": "🇨🇳 ZH (Chinese)",
        "pt": "🇵🇹 PT (Português)",
        "nl": "🇳🇱 NL (Nederlands)",
        "uk": "🇺🇦 UK (Українська)",
        "cs": "🇨🇿 CS (Čeština)",
        "tr": "🇹🇷 TR (Türkçe)",
    }
    return flags.get(c, f"🌐 {c.upper()}")


def translate_chess_comment(comment_text: str, src_lang: str = "en", tgt_lang: str = "de", timeout: float = 6.0, raise_on_error: bool = False) -> str:
    """
    Translates a chess position comment using Google Translate while safely preserving
    ChessBase diagram tags ([%csl ...], [%cal ...]) and evaluation symbols (+-, =, etc.).
    Returns translated text string. If offline or error occurs, returns cleaned original text
    (or raises if raise_on_error=True).
    """
    if not comment_text or not isinstance(comment_text, str) or not comment_text.strip():
        return ""

    import re
    import urllib.request
    import urllib.parse
    import json
    from opening_fenix.core.logger import logger

    # 1. Extract ChessBase tags
    tags = re.findall(r'(\[%c[s|a]l [^\]]+\])', comment_text)
    tags_part = " ".join(tags) if tags else ""

    # 2. Extract evaluation symbol
    eval_sym = extract_eval_symbol(comment_text)

    # 3. Get purely verbal text
    clean_text = clean_chessbase_annotations(comment_text)
    verbal_text = strip_eval_symbol(clean_text).strip()

    if not verbal_text:
        res_parts = []
        if tags_part: res_parts.append(tags_part)
        if eval_sym: res_parts.append(eval_sym)
        return "\n".join(res_parts) if eval_sym else tags_part

    # 4. Call Google Translate
    translated_verbal = verbal_text
    try:
        q = urllib.parse.quote(verbal_text)
        src = src_lang.lower().strip() if src_lang else "auto"
        tgt = tgt_lang.lower().strip() if tgt_lang else "de"
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={src}&tl={tgt}&dt=t&q={q}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with safe_urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and data[0]:
                chunks = [chunk[0] for chunk in data[0] if chunk and chunk[0]]
                if chunks:
                    translated_verbal = ''.join(chunks).strip()

        # If translation returned exact original verbal text and src was not auto, try sl=auto as intelligent fallback
        if src != "auto" and translated_verbal == verbal_text:
            url_auto = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={tgt}&dt=t&q={q}"
            req_auto = urllib.request.Request(url_auto, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            try:
                with safe_urlopen(req_auto, timeout=timeout) as resp_auto:
                    data_auto = json.loads(resp_auto.read().decode('utf-8'))
                    if data_auto and data_auto[0]:
                        chunks_auto = [chunk[0] for chunk in data_auto[0] if chunk and chunk[0]]
                        if chunks_auto:
                            translated_verbal = ''.join(chunks_auto).strip()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Google translate request failed: {e}")
        if raise_on_error:
            raise
        return comment_text

    # 5. Reassemble: [tags] [translated verbal] [eval_sym]
    parts = []
    if tags_part:
        parts.append(tags_part)
    if translated_verbal:
        parts.append(translated_verbal)

    res = " ".join(parts) if tags_part else translated_verbal
    if eval_sym:
        res = f"{res}\n{eval_sym}" if res else eval_sym

    return res


def strip_outer_parentheses_single(s: str) -> str:
    """
    Strips redundant balanced outer parentheses wrapping an entire comment or segment,
    while safely preserving leading/trailing ChessBase annotation tags ([%cal...], [%csl...]).
    Internal parentheses like '(better was 5.Nf3)' or '(Kasparov 1985)' remain untouched.
    """
    if not s or not isinstance(s, str):
        return s
    orig = s
    trimmed = s.strip()
    if "(" not in trimmed or ")" not in trimmed:
        return orig

    # Extract leading [%...] tags
    has_tag = "[%" in trimmed
    m_lead = _RE_LEAD_CB_TAGS.match(trimmed) if has_tag else None
    tag_prefix = ''
    body = trimmed
    if m_lead:
        tag_prefix = m_lead.group(0)
        body = trimmed[m_lead.end():].strip()

    # Extract trailing [%...] tags
    m_trail = _RE_TRAIL_CB_TAGS.search(body) if has_tag else None
    tag_suffix = ''
    if m_trail:
        tag_suffix = m_trail.group(0)
        body = body[:m_trail.start()].strip()

    # Check if body is fully enclosed by matching outer parentheses
    changed_body = False
    while body.startswith('(') and body.endswith(')'):
        depth = 0
        is_fully_enclosed = True
        for i, ch in enumerate(body):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                # If depth drops to 0 before the final character, outer parens do not enclose the entire string
                if depth == 0 and i < len(body) - 1:
                    is_fully_enclosed = False
                    break
        if is_fully_enclosed and depth == 0:
            body = body[1:-1].strip()
            changed_body = True
        else:
            break

    if not changed_body:
        return orig

    # Reconstruct text preserving tags and inner whitespace
    res = body
    if tag_prefix:
        res = f"{tag_prefix.strip()} {res}".strip()
    if tag_suffix:
        res = f"{res} {tag_suffix.strip()}".strip()
    return res


def clean_outer_parentheses_from_text(text: str) -> str:
    """
    Removes outer parentheses from text, handling multi-part comments separated by ' | '
    and multi-paragraph comments.
    """
    if not text or not isinstance(text, str):
        return ""
    if "(" not in text or ")" not in text:
        return text
    # Split by ' | ' for combined comments across lines/chapters
    parts = text.split(" | ")
    cleaned_parts = []
    for part in parts:
        p_clean = strip_outer_parentheses_single(part)
        if p_clean != part:
            cleaned_parts.append(p_clean)
        elif "\n" in part:
            # Check paragraph by paragraph if the entire part was not wrapped
            paras = _RE_PARA_SPLIT.split(part)
            cleaned_paras = [strip_outer_parentheses_single(p) if not _RE_BLANK_PARA.match(p) else p for p in paras]
            cleaned_parts.append(''.join(cleaned_paras))
        else:
            cleaned_parts.append(part)
    return " | ".join(cleaned_parts)


def clean_comment_parentheses(comment: str) -> tuple[str, bool]:
    """
    Cleans enclosing outer parentheses from a comment string, supporting
    both multilingual JSON comments and plain text comments.
    Returns (cleaned_comment_str, was_changed_bool).
    """
    if not comment or not isinstance(comment, str):
        return comment, False

    raw = comment.strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                changed = False
                new_data = {}
                for lang, val in data.items():
                    if isinstance(val, str):
                        new_val = clean_outer_parentheses_from_text(val)
                        if new_val != val:
                            changed = True
                        new_data[lang] = new_val
                    else:
                        new_data[lang] = val
                if changed:
                    return json.dumps(new_data, ensure_ascii=False), True
                return comment, False
        except Exception:
            pass

    new_val = clean_outer_parentheses_from_text(comment)
    return new_val, new_val != comment


def clean_comment_text(text: str) -> str:
    """
    Cleans hard-wrapped line breaks and isolated move/punctuation tokens
    typically generated by web PGN exporters (like Chessable).
    Preserves genuine paragraph breaks (double newlines) and intentional multi-line comments.
    Also strips redundant outer parentheses wrapping whole comments or segments.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if "\n" not in text:
        return clean_outer_parentheses_from_text(text.strip())

    # Fix isolated punctuation after newline: e.g. \n,\n -> ,\n
    text = _RE_CLEAN_PUNCT_NL.sub(r"\1", text)
    # Fix isolated parentheses
    text = _RE_CLEAN_PAREN_OPEN_NL.sub(r"(", text)
    text = _RE_CLEAN_PAREN_CLOSE_NL.sub(r")", text)
    
    paragraphs = _RE_CLEAN_PARA_SPLIT.split(text.strip())
    cleaned_paras = []
    
    for p in paragraphs:
        lines = [line.strip() for line in p.split("\n") if line.strip()]
        if not lines:
            continue
        # Preserve lists where every line starts with a bullet or number
        is_list = len(lines) > 1 and all(_RE_LIST_ITEM.match(l) for l in lines)
        if is_list:
            cleaned_paras.append("\n".join(lines))
            continue
            
        has_isolated_moves = any(_RE_MOVE_TOKEN.match(l) for l in lines)
        has_mid_sentence = any(
            not lines[i].endswith(('.', '!', '?', ':', ';')) and (i + 1 < len(lines) and (lines[i+1][0].islower() or _RE_MOVE_TOKEN.match(lines[i+1])))
            for i in range(len(lines) - 1)
        )
        has_pgn_wrap = any(len(l) >= 60 for l in lines) and any(not l.endswith(('.', '!', '?')) for l in lines[:-1])
        
        if has_isolated_moves or has_mid_sentence or has_pgn_wrap:
            joined = " ".join(lines)
            joined = _RE_JOIN_PUNCT.sub(r"\1", joined)
            joined = _RE_JOIN_PAREN_OPEN.sub("(", joined)
            joined = _RE_JOIN_PAREN_CLOSE.sub(")", joined)
            joined = _RE_MULTI_SPACE.sub(" ", joined)
            cleaned_paras.append(joined.strip())
        else:
            cleaned_paras.append("\n".join(lines))
            
    res = "\n\n".join(cleaned_paras)
    return clean_outer_parentheses_from_text(res)


def combine_comments(existing_comment: str, new_comment: str, default_lang: str = "de") -> str:
    """
    Combines an incoming comment with an existing position comment,
    preserving multilingual JSON payload structures and PGN language tags.
    Cleans hard-wrapped line breaks and prevents near-duplicate paragraph duplication.
    """
    if not new_comment or not new_comment.strip():
        return existing_comment or ""
    
    target = default_lang.lower() if default_lang else "de"
    raw_new = new_comment.strip()
    is_json_incoming = raw_new.startswith("{") and raw_new.endswith("}")

    if is_json_incoming:
        inc_dict = get_multilingual_comment_dict(raw_new, default_lang=target)
        inc_dict = {k: clean_comment_text(v) for k, v in inc_dict.items()}
    else:
        cleaned_incoming = clean_comment_text(new_comment)
        tagged = parse_pgn_tagged_comment(cleaned_incoming)
        if tagged:
            inc_dict = {k: clean_comment_text(v) for k, v in tagged.items()}
        else:
            inc_dict = {target: cleaned_incoming} if cleaned_incoming else {}

    if not existing_comment or not existing_comment.strip():
        return format_multilingual_comment(inc_dict)
        
    ext_dict = get_multilingual_comment_dict(existing_comment, default_lang=target)
    ext_dict = {k: clean_comment_text(v) for k, v in ext_dict.items()}
    
    # Merge dictionaries key by key
    merged = dict(ext_dict)
    for lang, val in inc_dict.items():
        if not val:
            continue
        if lang in merged and merged[lang]:
            existing_val = merged[lang]
            # Exact or substring containment
            if val in existing_val:
                continue
            if existing_val in val:
                merged[lang] = val
                continue
            
            # Near-duplicate prevention for long comments (e.g. repeated chapter overviews)
            if len(val) > 80 and len(existing_val) > 80:
                parts = [p.strip() for p in existing_val.split(" | ")]
                is_dup = False
                for p_idx, part in enumerate(parts):
                    if len(part) > 80:
                        matcher = difflib.SequenceMatcher(None, val, part)
                        if matcher.quick_ratio() >= 0.75 and matcher.ratio() >= 0.75:
                            # Keep the longer or more detailed version
                            if len(val) > len(part):
                                parts[p_idx] = val
                            is_dup = True
                            break
                if is_dup:
                    merged[lang] = " | ".join(parts)
                    continue

            merged[lang] = existing_val + " | " + val
        else:
            merged[lang] = val
            
    return format_multilingual_comment(merged)


def get_repertoire_comment_stats(session) -> str:
    """
    Scans comments in a repertoire database session and returns a formatted string such as:
    '1,548 EN (86%), 245 DE (14%)' or translated 'Keine Kommentare' / 'No comments'.
    """
    try:
        from opening_fenix.core.translation import tr_ui
        no_comments = tr_ui("repo_settings.no_comments", "Keine Kommentare")
    except Exception:
        no_comments = "Keine Kommentare"

    if not session:
        return no_comments
    from opening_fenix.core.db.models import Position
    
    try:
        comments = session.query(Position.comment).filter(
            Position.comment.isnot(None),
            Position.comment != ""
        ).all()
    except Exception:
        return no_comments
        
    if not comments:
        return no_comments
        
    counts = {}
    for (raw_c,) in comments:
        c_dict = get_multilingual_comment_dict(raw_c)
        for lang, val in c_dict.items():
            if lang and has_meaningful_comment(val):
                lang_upper = lang.upper()
                counts[lang_upper] = counts.get(lang_upper, 0) + 1
                
    if not counts:
        return no_comments
        
    total = sum(counts.values())
    try:
        from opening_fenix.core.translation import translator
        is_de = (translator.current_lang == "de")
    except Exception:
        is_de = False

    parts = []
    for lang_code, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        pct = int(round((cnt / total) * 100))
        cnt_str = f"{cnt:,}".replace(",", ".") if is_de else f"{cnt:,}"
        parts.append(f"{cnt_str} {lang_code} ({pct}%)")
        
    return ", ".join(parts)


def release_repertoire_locks(repo_name: str, checkpoint_wal: bool = False) -> None:
    """
    Safely terminates any background threads, closes database sessions/managers,
    optionally checkpoints SQLite WAL files, and removes read-only file attributes for the
    specified repertoire across the entire application.
    Vital on Windows to avoid [WinError 5] or [WinError 32] during rename or delete.
    """
    if not repo_name:
        return

    import gc
    import stat
    import time
    import sqlite3
    from opening_fenix.core.logger import logger

    # 1. Stop background threads and close sessions across all active Qt widgets
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            for w in app.topLevelWidgets():
                try:
                    # Check CreatorWindow save timer
                    if hasattr(w, "save_timer") and w.save_timer:
                        try:
                            w.save_timer.stop()
                            w.details_changed = False
                        except Exception:
                            pass

                    # Check CreatorWindow enrichment threads
                    if hasattr(w, "enrichment_threads") and isinstance(w.enrichment_threads, list):
                        for t in list(w.enrichment_threads):
                            try:
                                if getattr(t, "repo_name", None) == repo_name:
                                    t.requestInterruption()
                                    t.wait(1000)
                                    if t in w.enrichment_threads:
                                        w.enrichment_threads.remove(t)
                            except Exception:
                                pass

                    # Check engine thread
                    if hasattr(w, "engine_thread") and w.engine_thread:
                        try:
                            w.engine_thread.stop_engine()
                            w.engine_thread.running = False
                            w.engine_thread.is_active = False
                            w.engine_thread.wait(1000)
                        except Exception:
                            pass

                    # Check other creator threads
                    for thread_attr in [
                        "hole_thread", "global_transpos_thread", "_fen_index_thread",
                        "_bfs_thread", "_path_quality_thread", "_instant_multipv_thread"
                    ]:
                        if hasattr(w, thread_attr):
                            th = getattr(w, thread_attr)
                            if th:
                                try:
                                    if hasattr(th, "stop"):
                                        th.stop()
                                    if hasattr(th, "requestInterruption"):
                                        th.requestInterruption()
                                    th.wait(2000)
                                except Exception:
                                    pass
                                try:
                                    setattr(w, thread_attr, None)
                                except Exception:
                                    pass

                    # Check unified settings dialog stats workers
                    for worker_attr in ["creator_stats_loader", "stats_loader"]:
                        if hasattr(w, worker_attr):
                            sw = getattr(w, worker_attr)
                            if sw:
                                try:
                                    sw.requestInterruption()
                                    sw.wait(2000)
                                except Exception:
                                    pass
                                try:
                                    setattr(w, worker_attr, None)
                                except Exception:
                                    pass

                    # Check backends (CreatorBackend)
                    for b_attr in ["backend", "_owned_backend"]:
                        if hasattr(w, b_attr):
                            b = getattr(w, b_attr)
                            b_name = getattr(b, "active_repo_name", None)
                            w_name = getattr(w, "active_repo_name", None)
                            if b and (b_name == repo_name or w_name == repo_name):
                                try:
                                    b.close()
                                    b.active_repo_name = None
                                    b.clear_cache()
                                except Exception:
                                    pass

                    # Check MainWindow repertoire_manager and training_manager
                    if hasattr(w, "repertoire_manager"):
                        rm = getattr(w, "repertoire_manager")
                        if rm and getattr(rm, "active_repertoire_name", None) == repo_name:
                            try:
                                rm.close()
                                if hasattr(rm, "core") and rm.core:
                                    rm.core.active_repertoire_name = None
                            except Exception:
                                pass

                    if hasattr(w, "training_manager"):
                        tm = getattr(w, "training_manager")
                        if tm:
                            if hasattr(tm, "_user_settings_cache"): tm._user_settings_cache = None
                            if hasattr(tm, "_reachable_moves_cache"): tm._reachable_moves_cache = None
                            if hasattr(tm, "_last_stats_cache"): tm._last_stats_cache = None

                except Exception as e:
                    logger.debug(f"Error releasing locks in widget {w}: {e}")
    except Exception as e:
        logger.debug(f"Error accessing Qt widgets for lock release: {e}")

    # 2. Dispose any open DatabaseManager instances bound to regular or test database paths or dirs
    try:
        from opening_fenix.core.db.database import DatabaseManager
        for is_t in (False, True):
            p = get_repertoire_db_path(repo_name, is_test=is_t)
            if p:
                DatabaseManager.close_all_for_path(p)
            d = get_repertoire_dir(repo_name, is_test=is_t)
            if d:
                DatabaseManager.close_all_for_directory(d)
    except Exception as e:
        logger.debug(f"Error disposing DatabaseManager instances for {repo_name}: {e}")

    # 3. Checkpoint WAL and truncate auxiliary files ONLY if requested (e.g. rename, not delete)
    if checkpoint_wal:
        for is_t in (False, True):
            db_path = get_repertoire_db_path(repo_name, is_test=is_t)
            if db_path and os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path, timeout=3)
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.close()
                except Exception as e:
                    logger.debug(f"WAL checkpoint for {repo_name} (is_test={is_t}): {e}")

    # 4. Strip read-only attributes on directory and files only if needed (regular and test)
    for is_t in (False, True):
        repo_dir = get_repertoire_dir(repo_name, is_test=is_t)
        if repo_dir and os.path.exists(repo_dir):
            if not os.access(repo_dir, os.W_OK):
                try:
                    os.chmod(repo_dir, stat.S_IWRITE)
                except Exception:
                    pass
            for root, dirs, files in os.walk(repo_dir):
                for d in dirs:
                    dp = os.path.join(root, d)
                    if not os.access(dp, os.W_OK):
                        try: os.chmod(dp, stat.S_IWRITE)
                        except Exception: pass
                for f in files:
                    fp = os.path.join(root, f)
                    if not os.access(fp, os.W_OK):
                        try: os.chmod(fp, stat.S_IWRITE)
                        except Exception: pass

    # 5. Trigger garbage collection once to release any uncollected file descriptors
    gc.collect()
    try:
        from PyQt6.QtWidgets import QApplication
        if QApplication.instance():
            QApplication.processEvents()
    except Exception:
        pass


def get_ssl_context(verify: bool = True):
    """
    Creates (and caches per verify flag) a robust SSLContext for HTTPS requests.
    - If verify=False, returns an unverified context.
    - If verify=True, loads certifi CA bundle and merges all Windows Root and CA store certificates.
    """
    verify_key = bool(verify)
    cached = _SSL_CONTEXT_CACHE.get(verify_key)
    if cached is not None:
        return cached

    with _SSL_CONTEXT_LOCK:
        cached = _SSL_CONTEXT_CACHE.get(verify_key)
        if cached is not None:
            return cached

        import ssl
        if not verify_key and hasattr(ssl, "_create_unverified_context"):
            ctx = ssl._create_unverified_context()
            try:
                ctx.set_alpn_protocols(['http/1.1'])
            except Exception:
                pass
            if hasattr(ctx, 'post_handshake_auth') and ctx.post_handshake_auth is not None:
                ctx.post_handshake_auth = True
            _SSL_CONTEXT_CACHE[verify_key] = ctx
            return ctx

        try:
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()

            if sys.platform == "win32" and hasattr(ssl, "enum_certificates"):
                for store_name in ("ROOT", "CA"):
                    try:
                        for cert, encoding, trust in ssl.enum_certificates(store_name):
                            if encoding == "x509_asn":
                                ctx.load_verify_locations(cadata=cert)
                    except Exception:
                        pass
            try:
                ctx.set_alpn_protocols(['http/1.1'])
            except Exception:
                pass
            if hasattr(ctx, 'post_handshake_auth') and ctx.post_handshake_auth is not None:
                ctx.post_handshake_auth = True
            _SSL_CONTEXT_CACHE[verify_key] = ctx
            return ctx
        except Exception:
            ctx = ssl.create_default_context()
            _SSL_CONTEXT_CACHE[verify_key] = ctx
            return ctx


def safe_urlopen(req, timeout: int = 15, allow_unverified_fallback: bool = False):
    """
    Executes urllib.request.urlopen with verified TLS (certifi + Windows certificate store).
    Does NOT silently downgrade to unverified TLS on certificate errors unless
    allow_unverified_fallback=True is explicitly requested.
    """
    import ssl
    import urllib.request
    import urllib.error

    ctx = get_ssl_context(verify=True)
    try:
        return urllib.request.urlopen(req, context=ctx, timeout=timeout)
    except (urllib.error.URLError, ssl.SSLError, Exception) as e:
        err_str = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err_str or "certificate verify failed" in err_str or "SSLCertVerificationError" in err_str:
            if allow_unverified_fallback:
                unverified_ctx = get_ssl_context(verify=False)
                return urllib.request.urlopen(req, context=unverified_ctx, timeout=timeout)
        raise

