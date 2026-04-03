import sys
import os
import json
import sqlite3
import traceback
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt

from PyQt6.QtGui import QIcon

from opening_fenix.core.data_tools import get_base_path, get_user_dir
from opening_fenix.core.migration import migrate_legacy_profiles
from opening_fenix.gui.dialogs.login_dialog import LoginDialog
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.gui.styles import set_consistent_icon
from opening_fenix.gui.window_manager import WindowManager
from opening_fenix.core.logger import logger

def cleanup_temp_db_files():
    """
    Attempts to clean up SQLite WAL files by running a checkpoint 
    and then deleting the side-files if they are no longer needed.
    """
    repo_dir = os.path.join(get_user_dir(), "repertoires")
    profiles_dir = os.path.join(get_user_dir(), "profiles")
    
    for folder in [repo_dir, profiles_dir]:
        if not os.path.exists(folder):
            continue
        for f in os.listdir(folder):
            if f.endswith(".db"):
                db_path = os.path.join(folder, f)
                try:
                    conn = sqlite3.connect(db_path)
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.close()
                except Exception as e:
                    logger.debug(f"Could not checkpoint {f}: {e}")
            
            if f.endswith(".db-wal") or f.endswith(".db-shm"):
                try:
                    os.remove(os.path.join(folder, f))
                except Exception as e:
                    logger.debug(f"Could not remove WAL/SHM file {f}: {e}")

def ensure_default_engine_path():
    """
    Checks if an engine path is set in config.json. If not, and if a Stockfish
    executable is found in the bundled 'engines' folder, sets it as default.
    """
    config_path = os.path.join(get_user_dir(), "config.json")
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception as e:
            logger.warning(f"Error loading config.json: {e}")
    
    if not config.get("engine_path") or not os.path.exists(config["engine_path"]):
        # Look in bundled engines folder
        engines_dir = os.path.join(get_base_path(), "engines")
        if os.path.exists(engines_dir):
            for f in os.listdir(engines_dir):
                if f.lower().startswith("stockfish") and f.lower().endswith(".exe"):
                    config["engine_path"] = os.path.abspath(os.path.join(engines_dir, f))
                    try:
                        with open(config_path, "w") as f_out:
                            json.dump(config, f_out, indent=4)
                        logger.info(f"Set default engine path to {config['engine_path']}")
                    except Exception as e:
                        logger.error(f"Could not save config with default engine path: {e}")
                    break

if __name__ == "__main__":
    if sys.platform == 'win32':
        import ctypes
        # More unique and descriptive ID to ensure correct taskbar grouping/caching
        myappid = 'OpeningFenix.Lab.RepertoireTrainer.1.0' 
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except (AttributeError, OSError):
             pass

    try:
        logger.info("Opening Fenix starting...")

        # Enable High DPI scaling and rounding policies for sharp UI
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        
        QApplication.setStyle("Fusion")
        app = QApplication(sys.argv)
        
        # Explicitly set application identity for Windows taskbar grouping
        app.setApplicationName("OpeningFenix")
        app.setOrganizationName("OpeningFenixLab")
        app.setApplicationVersion("2.1.0")
        app.setApplicationDisplayName("Opening Fenix")
        
        # Set icon on the app instance immediately
        set_consistent_icon(app)

        logger.info("Application initialized, setting up services...")

        from opening_fenix.core.utils import migrate_repertoire_storage
        migrate_repertoire_storage()
        migrate_legacy_profiles()
        ensure_default_engine_path()

        config_path = os.path.join(get_user_dir(), "config.json")
        last_profile = None
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    last_profile = config.get("last_profile")
            except Exception as e:
                logger.warning(f"Error reading last_profile from config: {e}")

        initial_profile = None
        if last_profile:
            profile_path = os.path.join(get_user_dir(), "profiles", f"{last_profile}.db")
            if os.path.exists(profile_path):
                 initial_profile = last_profile

        # Start the WindowManager to handle app lifecycle
        manager = WindowManager()
        manager.start_application(initial_profile)
                
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.critical(f"Critical error during startup: {error_msg}")
        # Show error in a message box if possible
        if 'app' in locals():
            QMessageBox.critical(None, "Kritischer Fehler", f"Das Programm ist abgestürzt:\n\n{error_msg}")
    finally:
        cleanup_temp_db_files()
        sys.exit()
