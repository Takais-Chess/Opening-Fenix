import os
import sys
import json

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
        return os.path.dirname(sys.executable)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return os.path.dirname(parent_dir)

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

