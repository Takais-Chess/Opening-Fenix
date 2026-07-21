import sys
import os
import json
import sqlite3
import traceback
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt

from PyQt6.QtGui import QIcon

from opening_fenix.core.utils import get_base_path, get_user_dir
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
    Checks if an engine path is set in config.json. If not valid, and if a Stockfish
    executable is found in any bundled 'engines' folder, sets it as default.
    """
    config_path = os.path.join(get_user_dir(), "config.json")
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception as e:
            logger.warning(f"Error loading config.json: {e}")
    
    current_engine = config.get("engine_path")
    if not current_engine or not os.path.exists(current_engine):
        candidates = [
            os.path.join(get_base_path(), "engines"),
            os.path.join(get_user_dir(), "engines")
        ]
        if getattr(sys, 'frozen', False):
            candidates.append(os.path.join(os.path.dirname(sys.executable), "engines"))
            if hasattr(sys, '_MEIPASS'):
                candidates.append(os.path.join(sys._MEIPASS, "engines"))

        found_engine = None
        for engines_dir in candidates:
            if os.path.exists(engines_dir) and os.path.isdir(engines_dir):
                for f in os.listdir(engines_dir):
                    if f.lower().endswith(".exe"):
                        found_engine = os.path.abspath(os.path.join(engines_dir, f))
                        break
            if found_engine:
                break

        if found_engine:
            config["engine_path"] = found_engine
            try:
                with open(config_path, "w") as f_out:
                    json.dump(config, f_out, indent=4)
                logger.info(f"Set default engine path to {found_engine}")
            except Exception as e:
                logger.error(f"Could not save config with default engine path: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        import ctypes
        import winreg
        # Aggressive Shell Notification Update
        # Force the shell to forget about the python executable caching
        try:
            SHCNE_ASSOCCHANGED = 0x08000000
            SHCNF_IDLIST = 0x0000
            ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        except Exception:
            pass
            
        # More unique and descriptive ID to ensure Windows taskbar grouping matches the logo.
        # This string should be unique to the app (including version if needed).
        myappid = 'OpeningFenix.Lab.V2.2.0' 
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
        app.setApplicationVersion("2.2.0")
        app.setApplicationDisplayName("Opening Fenix")
        
        # Set icon on the app instance immediately
        set_consistent_icon(app)

        logger.info("Application initialized, setting up services...")

        from opening_fenix.core.utils import migrate_repertoire_storage, ensure_user_data_seeded
        ensure_user_data_seeded()
        migrate_repertoire_storage()
        
        # Check if legacy profiles exist before importing migration (to save import time)
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        if os.path.exists(profiles_dir) and any(f.endswith(".json") and not f.endswith("_settings.json") for f in os.listdir(profiles_dir)):
            from opening_fenix.core.migration import migrate_legacy_profiles
            migrate_legacy_profiles()
            
        ensure_default_engine_path()

        config_path = os.path.join(get_user_dir(), "config.json")
        auto_login_profile = None
        ui_lang = "de"
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    auto_login_profile = config.get("auto_login_profile")
                    ui_lang = config.get("ui_language", "de")
            except Exception as e:
                logger.warning(f"Error reading config: {e}")

        # Initialize TranslationManager with global language
        from opening_fenix.core.translation import translator
        translator.load_language(ui_lang)

        initial_profile = None
        if auto_login_profile:
            if auto_login_profile == "Freies Training":
                initial_profile = auto_login_profile
            else:
                profile_path = os.path.join(get_user_dir(), "profiles", f"{auto_login_profile}.db")
                if os.path.exists(profile_path):
                     initial_profile = auto_login_profile

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
