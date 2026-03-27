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
