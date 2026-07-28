import os
import sys
import json

ELO_DISPLAY_MAP = {
    "low": "Hobby Spieler",
    "mid": "Vereins Spieler",
    "high": "Lichess Meister Elo",
    "masters": "Meister Datenbank"
}

ELO_INTERNAL_MAP = {v: k for k, v in ELO_DISPLAY_MAP.items()}

def get_elo_display(internal_key):
    if not internal_key:
        return "N/A"
    from opening_fenix.core.translation import tr_ui
    key_lower = internal_key.lower()
    default_val = ELO_DISPLAY_MAP.get(key_lower, internal_key.capitalize())
    return tr_ui(f"elo.{key_lower}", default_val)

def get_elo_internal(display_name):
    # First try the static German map (fast path)
    if display_name in ELO_INTERNAL_MAP:
        return ELO_INTERNAL_MAP[display_name]
    # Fall back: compare against current translated display names for each key
    try:
        from opening_fenix.core.translation import tr_ui
        for key in ELO_DISPLAY_MAP:
            if tr_ui(f"elo.{key}", ELO_DISPLAY_MAP[key]) == display_name:
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

def get_base_path():
    """Gibt den Basispfad der Anwendung zurück, um Probleme mit dem Arbeitsverzeichnis zu vermeiden."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

def get_user_dir():
    """Returns the directory where user data (profiles, config, repertoires) is stored."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        try:
            test_file = os.path.join(exe_dir, ".perm_test")
            with open(test_file, "w") as f:
                f.write("1")
            os.remove(test_file)
            return exe_dir
        except Exception:
            appdata = os.getenv("APPDATA") or os.path.expanduser("~")
            user_dir = os.path.join(appdata, "Opening Fenix")
            os.makedirs(user_dir, exist_ok=True)
            return user_dir

    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

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

    # 2. Seed profiles and repertoires
    is_pub = is_public_version()
    for folder in ["profiles", "repertoires"]:
        dest_folder = os.path.join(user_dir, folder)
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder, exist_ok=True)
            
        for src in sources:
            src_folder = os.path.join(src, folder)
            if os.path.exists(src_folder) and os.path.isdir(src_folder):
                for item in os.listdir(src_folder):
                    s_path = os.path.join(src_folder, item)
                    d_path = os.path.join(dest_folder, item)
                    
                    if folder == "repertoires":
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
    2. config.json 'is_public' setting
    3. Bundled 'PUBLIC_VERSION' or 'public.flag' file in base path or user path
    """
    env_share = os.environ.get('FENIX_SHARE_BUILD') == '1'
    env_public = os.environ.get('FENIX_PUBLIC_BUILD') == '1'
    env_build_type = os.environ.get('APP_BUILD_TYPE', '').lower() == 'public'
    if env_share or env_public or env_build_type:
        return True

    # Check config.json in user dir or base dir
    for dir_path in [get_user_dir(), get_base_path()]:
        config_path = os.path.join(dir_path, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if cfg.get("is_public") is True:
                        return True
                    if cfg.get("is_public") is False:
                        return False
            except Exception:
                pass

    # Check for marker file in base_path or user_dir
    for dir_path in [get_base_path(), get_user_dir()]:
        if os.path.exists(os.path.join(dir_path, "PUBLIC_VERSION")) or os.path.exists(os.path.join(dir_path, "public.flag")):
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
    Filters repertoire names depending on whether the app is in Public or Private build mode.
    - Public mode: returns ONLY example repertoires.
    - Private mode: returns ALL repertoires (personal + example repertoires so example courses can be viewed & edited).
    """
    is_pub = is_public_version()
    filtered = []
    for name in repo_names:
        is_ex = is_example_repertoire(name)
        if is_pub and is_ex:
            filtered.append(name)
        elif not is_pub:
            filtered.append(name)
    return filtered


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
    alt_lang = "en" if target_lang == "de" else "de"
    if alt_lang in comment_dict and comment_dict[alt_lang]:
        return comment_dict[alt_lang]
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


def combine_comments(existing_comment: str, new_comment: str, default_lang: str = "de") -> str:
    """
    Combines an incoming comment with an existing position comment,
    preserving multilingual JSON payload structures and PGN language tags.
    """
    if not new_comment or not new_comment.strip():
        return existing_comment or ""
    
    target = default_lang.lower() if default_lang else "de"
    # 1. Parse incoming comment (check for PGN tags, JSON, or plain text)
    tagged = parse_pgn_tagged_comment(new_comment)
    if tagged:
        inc_dict = tagged
    else:
        inc_dict = get_multilingual_comment_dict(new_comment, default_lang=target)
        
    if not existing_comment or not existing_comment.strip():
        return format_multilingual_comment(inc_dict)
        
    ext_dict = get_multilingual_comment_dict(existing_comment, default_lang=target)
    
    # Merge dictionaries key by key
    merged = dict(ext_dict)
    for lang, val in inc_dict.items():
        if lang in merged and merged[lang]:
            if val not in merged[lang]:
                merged[lang] = merged[lang] + " | " + val
        else:
            merged[lang] = val
            
    return format_multilingual_comment(merged)


def get_repertoire_comment_stats(session) -> str:
    """
    Scans comments in a repertoire database session and returns a formatted string such as:
    '1,548 EN (86%), 245 DE (14%)' or 'Keine Kommentare'.
    """
    if not session:
        return "Keine Kommentare"
    from opening_fenix.core.db.models import Position
    
    try:
        comments = session.query(Position.comment).filter(
            Position.comment.isnot(None),
            Position.comment != ""
        ).all()
    except Exception:
        return "Keine Kommentare"
        
    if not comments:
        return "Keine Kommentare"
        
    counts = {}
    for (raw_c,) in comments:
        c_dict = get_multilingual_comment_dict(raw_c)
        for lang in c_dict.keys():
            if lang:
                lang_upper = lang.upper()
                counts[lang_upper] = counts.get(lang_upper, 0) + 1
                
    if not counts:
        return "Keine Kommentare"
        
    total = sum(counts.values())
    parts = []
    for lang_code, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        pct = int(round((cnt / total) * 100))
        parts.append(f"{cnt:,} {lang_code} ({pct}%)")
        
    return ", ".join(parts)



