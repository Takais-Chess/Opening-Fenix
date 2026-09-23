import os
import sys
import json
import re
import difflib
import chess
from typing import Any

ELO_DISPLAY_MAP = {
    "low": "Hobby Spieler",
    "mid": "Vereins Spieler",
    "high": "Lichess Meister Elo",
    "masters": "Meister Datenbank"
}

ELO_INTERNAL_MAP = {v: k for k, v in ELO_DISPLAY_MAP.items()}

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
        for text in re.split(r'(\d+)', str(s))
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

    import re
    # If already formatted with move number prefix (e.g. '3.d4', '1...c5'), return as-is
    if re.match(r'^\d+\.', move_str.strip()):
        return move_str

    import chess
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
        return sys._MEIPASS
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

def get_default_user_dir():
    """Returns the default local directory where user data (profiles, config, repertoires) is stored."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
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
                return exe_dir
            except Exception:
                pass

        appdata = os.getenv("APPDATA") or os.path.expanduser("~")
        user_dir = os.path.join(appdata, "Opening Fenix")
        os.makedirs(user_dir, exist_ok=True)
        return user_dir

    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

def get_custom_data_dir():
    """Returns the configured custom data directory if set and existing, otherwise None."""
    default_dir = get_default_user_dir()
    master_cfg_path = os.path.join(default_dir, "config.json")
    if os.path.exists(master_cfg_path):
        try:
            with open(master_cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            custom_dir = cfg.get("custom_data_dir")
            if custom_dir and isinstance(custom_dir, str) and custom_dir.strip():
                custom_dir = os.path.abspath(custom_dir.strip())
                if os.path.exists(custom_dir):
                    return custom_dir
        except Exception:
            pass
    return None

def set_custom_data_dir(target_dir):
    """Updates or clears the custom_data_dir in the master config.json."""
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
        cfg.pop("custom_data_dir", None)
    else:
        target_dir = os.path.abspath(str(target_dir).strip())
        os.makedirs(target_dir, exist_ok=True)
        os.makedirs(os.path.join(target_dir, "repertoires"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "profiles"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "backups"), exist_ok=True)
        cfg["custom_data_dir"] = target_dir

    with open(master_cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

def get_user_dir():
    """Returns the active user data directory (custom cloud dir if configured, else default)."""
    custom = get_custom_data_dir()
    if custom:
        return custom
    return get_default_user_dir()

def migrate_user_data(source_dir, target_dir):
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
                            summary[folder] += 1
                    else:
                        if not os.path.exists(d_path):
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

    # Ensure build mode (is_public) is persistently recorded in user config if missing
    if os.path.exists(user_config):
        try:
            with open(user_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "is_public" not in cfg:
                base_pub = os.path.exists(os.path.join(get_base_path(), "PUBLIC_VERSION")) or os.path.exists(os.path.join(get_base_path(), "public.flag"))
                cfg["is_public"] = True if base_pub else False
                with open(user_config, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save build type to user config: {e}")

    # 2. Ensure profiles directory exists (profiles are user-created only, never bundled)
    dest_profiles = os.path.join(user_dir, "profiles")
    os.makedirs(dest_profiles, exist_ok=True)

    # 3. Seed repertoires
    is_pub = is_public_version()

    repertoires_seeded = False
    if os.path.exists(user_config):
        try:
            with open(user_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            repertoires_seeded = cfg.get("repertoires_seeded", False)
        except Exception:
            pass

    # If repertoires_seeded is not yet recorded, check if repertoires already exist in user_dir
    dest_repertoires = os.path.join(user_dir, "repertoires")
    if not repertoires_seeded and os.path.exists(dest_repertoires) and os.listdir(dest_repertoires):
        repertoires_seeded = True
        if os.path.exists(user_config):
            try:
                with open(user_config, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["repertoires_seeded"] = True
                with open(user_config, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

    has_custom_dir = bool(get_custom_data_dir())
    custom_has_repertoires = False
    if has_custom_dir:
        cust_repo_dir = os.path.join(user_dir, "repertoires")
        if os.path.exists(cust_repo_dir) and any(os.path.isdir(os.path.join(cust_repo_dir, d)) for d in os.listdir(cust_repo_dir)):
            custom_has_repertoires = True

    if not custom_has_repertoires:
        # For repertoires without a custom dir: We do NOT skip based on repertoires_seeded flag.
        # Any missing repertoire in user_dir will be copied, but existing repertoires
        # are NEVER overwritten (checked via `if not os.path.exists(d_path)`).
        dest_folder = os.path.join(user_dir, "repertoires")
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder, exist_ok=True)
            
        for src in sources:
            src_folder = os.path.join(src, "repertoires")
            if os.path.exists(src_folder) and os.path.isdir(src_folder):
                for item in os.listdir(src_folder):
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
    if not repertoires_seeded and os.path.exists(user_config):
        try:
            with open(user_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["repertoires_seeded"] = True
            with open(user_config, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

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

def normalize_fen(board):
    return " ".join(board.fen().split(" ")[:4])

def get_repertoire_dir(repo_name, is_test=None):
    """
    Returns the path to the repertoire's specific folder.
    Now more robust: if is_test is None, it checks both the regular and test subfolders.
    """
    repo_base = os.path.join(get_user_dir(), "repertoires")
    
    # If is_test is explicitly provided, respect it
    if is_test is True:
        return os.path.join(repo_base, "test", repo_name)
    elif is_test is False:
        return os.path.join(repo_base, repo_name)
        
    # If is_test is None, we probe both locations
    regular_path = os.path.join(repo_base, repo_name)
    test_path = os.path.join(repo_base, "test", repo_name)
    
    if os.path.exists(regular_path) and os.path.isdir(regular_path):
        return regular_path
    elif os.path.exists(test_path) and os.path.isdir(test_path):
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


def parse_comment(raw_comment: str, lang: str = "de") -> str:
    """
    Resolves a position comment for a target language code (e.g. 'de', 'en').
    Hierarchy: requested lang -> 'en' -> 'de' -> first non-empty -> raw string.
    """
    if not raw_comment or not raw_comment.strip():
        return ""
    
    # If not a JSON object string, return raw text directly
    raw = raw_comment.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        return raw

    comment_dict = get_multilingual_comment_dict(raw)
    if not comment_dict:
        return raw

    target_lang = lang.lower() if lang else "de"
    if target_lang in comment_dict and comment_dict[target_lang]:
        return comment_dict[target_lang]
    if "en" in comment_dict and comment_dict["en"]:
        return comment_dict["en"]
    if "de" in comment_dict and comment_dict["de"]:
        return comment_dict["de"]
    for val in comment_dict.values():
        if val:
            return val
    return raw


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


def parse_pgn_tagged_comment(comment_text: str) -> dict:
    """
    Parses inline PGN language tags like '[:de] Deutscher Text [:en] English text'
    or '[de] Deutscher Text [en] English text'.
    Returns a dictionary mapping language codes to comment strings.
    """
    if not comment_text or not comment_text.strip():
        return {}
    import re
    matches = re.findall(r'\[:?([a-zA-Z]{2})\]\s*([^\[]+)', comment_text)
    if matches:
        res = {}
        for lang, text in matches:
            t = text.strip()
            if t:
                res[lang.lower()] = t
        return res
    return {}


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


def parse_chessbase_annotations(text: str) -> dict:
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

    # 1. Parse [%csl ...] tags (Colored Squares List)
    csl_matches = re.findall(r'\[%(?:csl|CSL)\s+([^\]]+)\]', text)
    for block in csl_matches:
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
    cal_matches = re.findall(r'\[%(?:cal|CAL)\s+([^\]]+)\]', text)
    for block in cal_matches:
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

    # 3. Clean text of all [%csl ...] and [%cal ...] tags
    clean = clean_chessbase_annotations(text)

    return {
        "clean_text": clean,
        "highlights": highlights,
        "arrows": arrows,
    }


def clean_chessbase_annotations(text: str) -> str:
    """Removes [%csl ...], [%cal ...], and other [%...] annotation tags from comment text for clean UI presentation."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = re.sub(r'\[%[^\]]+\]', '', text)
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in cleaned.split('\n')]
    # Remove empty lines at beginning and end, collapse 3+ newlines to 2
    res = '\n'.join(lines).strip()
    return re.sub(r'\n{3,}', '\n\n', res)


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


def clean_comment_text(text: str) -> str:
    """
    Cleans hard-wrapped line breaks and isolated move/punctuation tokens
    typically generated by web PGN exporters (like Chessable).
    Preserves genuine paragraph breaks (double newlines) and intentional multi-line comments.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
    # Fix isolated punctuation after newline: e.g. \n,\n -> ,\n
    text = re.sub(r"\s*\n\s*([,.;:!?])", r"\1", text)
    # Fix isolated parentheses
    text = re.sub(r"\(\s*\n\s*", r"(", text)
    text = re.sub(r"\s*\n\s*\)", r")", text)
    
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    cleaned_paras = []
    
    move_pattern = re.compile(r"^(\d+\.+)?\s*([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[\+#]?|[O-O0-]+)$", re.IGNORECASE)
    
    for p in paragraphs:
        lines = [line.strip() for line in p.split("\n") if line.strip()]
        if not lines:
            continue
        # Preserve lists where every line starts with a bullet or number
        is_list = all(re.match(r"^([-*•]|\d+[\.)])\s+", l) for l in lines) and len(lines) > 1
        if is_list:
            cleaned_paras.append("\n".join(lines))
            continue
            
        # Check if the paragraph has hard-wrapping indicators:
        # 1. Any line is an isolated move token (e.g. "3.Nc3", "Bf5")
        # 2. Any line ends mid-sentence and the next line continues in lowercase or move token
        # 3. Any line has typical PGN line wrap length (~60-80 chars) and doesn't end with sentence punctuation
        has_isolated_moves = any(move_pattern.match(l) for l in lines)
        has_mid_sentence = any(
            not lines[i].endswith(('.', '!', '?', ':', ';')) and (i + 1 < len(lines) and (lines[i+1][0].islower() or move_pattern.match(lines[i+1])))
            for i in range(len(lines) - 1)
        )
        has_pgn_wrap = any(len(l) >= 60 for l in lines) and any(not l.endswith(('.', '!', '?')) for l in lines[:-1])
        
        if has_isolated_moves or has_mid_sentence or has_pgn_wrap:
            joined = " ".join(lines)
            joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
            joined = re.sub(r"\(\s+", "(", joined)
            joined = re.sub(r"\s+\)", ")", joined)
            joined = re.sub(r" +", " ", joined)
            cleaned_paras.append(joined.strip())
        else:
            cleaned_paras.append("\n".join(lines))
            
    return "\n\n".join(cleaned_paras)


def combine_comments(existing_comment: str, new_comment: str, default_lang: str = "de") -> str:
    """
    Combines an incoming comment with an existing position comment,
    preserving multilingual JSON payload structures and PGN language tags.
    Cleans hard-wrapped line breaks and prevents near-duplicate paragraph duplication.
    """
    if not new_comment or not new_comment.strip():
        return existing_comment or ""
    
    target = default_lang.lower() if default_lang else "de"
    # 1. Clean incoming comment text
    cleaned_incoming = clean_comment_text(new_comment)

    # 2. Parse incoming comment (check for PGN tags, JSON, or plain text)
    tagged = parse_pgn_tagged_comment(cleaned_incoming)
    if tagged:
        inc_dict = tagged
    else:
        inc_dict = get_multilingual_comment_dict(cleaned_incoming, default_lang=target)
        
    if not existing_comment or not existing_comment.strip():
        return format_multilingual_comment(inc_dict)
        
    ext_dict = get_multilingual_comment_dict(existing_comment, default_lang=target)
    
    # Merge dictionaries key by key
    merged = dict(ext_dict)
    for lang, val in inc_dict.items():
        val = clean_comment_text(val)
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
        for lang in c_dict.keys():
            if lang:
                lang_upper = lang.upper()
                counts[lang_upper] = counts.get(lang_upper, 0) + 1
                
    if not counts:
        return no_comments
        
    total = sum(counts.values())
    parts = []
    for lang_code, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        pct = int(round((cnt / total) * 100))
        parts.append(f"{cnt:,} {lang_code} ({pct}%)")
        
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

    # 4. Strip read-only attributes on directory and all files (regular and test)
    for is_t in (False, True):
        repo_dir = get_repertoire_dir(repo_name, is_test=is_t)
        if repo_dir and os.path.exists(repo_dir):
            try:
                os.chmod(repo_dir, stat.S_IWRITE)
            except Exception:
                pass
            for root, dirs, files in os.walk(repo_dir):
                for d in dirs:
                    try: os.chmod(os.path.join(root, d), stat.S_IWRITE)
                    except Exception: pass
                for f in files:
                    try: os.chmod(os.path.join(root, f), stat.S_IWRITE)
                    except Exception: pass

    # 5. Trigger garbage collection to release file descriptors held by Python objects
    gc.collect()
    try:
        from PyQt6.QtWidgets import QApplication
        if QApplication.instance():
            QApplication.processEvents()
    except Exception:
        pass
    gc.collect()
    time.sleep(0.15)
