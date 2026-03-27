import sys
import os
import json
import sqlite3
import traceback
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtGui import QIcon

from opening_fenix.core.data_tools import get_base_path, get_user_dir
from opening_fenix.core.migration import migrate_legacy_profiles
from opening_fenix.gui.dialogs.login_dialog import LoginDialog
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.creator.creator_window import CreatorWindow

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
                except:
                    pass
            
            if f.endswith(".db-wal") or f.endswith(".db-shm"):
                try:
                    os.remove(os.path.join(folder, f))
                except:
                    pass

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
        except: pass
    
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
                        print(f"INFO: Set default engine path to {config['engine_path']}")
                    except: pass
                    break

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            import ctypes
            myappid = 'OpeningFenix.OpeningFenix.1.0' 
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except (AttributeError, OSError): pass

        app = QApplication(sys.argv)

        icon_path = os.path.join(get_base_path(), "assets", "Logo", "favicon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))

        migrate_legacy_profiles()
        ensure_default_engine_path()

        config_path = os.path.join(get_user_dir(), "config.json")
        last_profile = None
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    last_profile = config.get("last_profile")
            except (OSError, json.JSONDecodeError): pass

        initial_profile = None
        if last_profile:
            profile_path = os.path.join(get_user_dir(), "profiles", f"{last_profile}.db")
            if os.path.exists(profile_path):
                 initial_profile = last_profile

        current_profile = initial_profile
        login = None # Keep reference to the dialog for the transition

        while True:
            if not current_profile:
                login = LoginDialog()
                result = login.exec()
                
                if getattr(login, 'open_creator_requested', False):
                     login.show()
                     QApplication.processEvents()
                     creator = CreatorWindow()
                     creator.showMaximized()
                     login.hide()
                     QApplication.restoreOverrideCursor()
                     app.exec()
                     continue

                if result == QDialog.DialogCode.Accepted:
                    current_profile = login.selected_profile
                else:
                    break 

            if current_profile:
                # Update last used timestamp in config
                try:
                    import datetime
                    config = {}
                    if os.path.exists(config_path):
                        with open(config_path, "r") as f: 
                            config = json.load(f)
                    
                    config["last_profile"] = current_profile
                    if "profile_last_used" not in config:
                        config["profile_last_used"] = {}
                    config["profile_last_used"][current_profile] = datetime.datetime.now().isoformat()
                    
                    with open(config_path, "w") as f: 
                        json.dump(config, f, indent=4)
                except Exception as e:
                    print(f"DEBUG: Could not update config: {e}")

                if login:
                    login.show()
                    QApplication.processEvents()
                main_win = MainWindow(current_profile)
                main_win.showMaximized()
                if login:
                    login.hide()
                    QApplication.restoreOverrideCursor()
                app.exec()
                
                # Ensure cursor is restored if app.exec() returns unexpectedly
                while QApplication.overrideCursor():
                    QApplication.restoreOverrideCursor()

                if main_win.switch_requested:
                    current_profile = None 
                    continue
                else:
                    break
                
    except Exception as e:
        error_msg = traceback.format_exc()
        print(error_msg)
        # Show error in a message box if possible
        if 'app' in locals():
            QMessageBox.critical(None, "Kritischer Fehler", f"Das Programm ist abgestürzt:\n\n{error_msg}")
    finally:
        cleanup_temp_db_files()
        sys.exit()
