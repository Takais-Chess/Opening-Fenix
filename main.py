import sys
import os
import gc
import json
import sqlite3
import traceback
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt, QLocale

# Tune Python garbage collector thresholds to eliminate Gen-2 stop-the-world pauses during chess operations
gc.set_threshold(50000, 50, 50)

from PyQt6.QtGui import QIcon

from opening_fenix.core.utils import get_base_path, get_user_dir
from opening_fenix.core.version import APP_VERSION
from opening_fenix.gui.styles import set_consistent_icon, setup_light_palette
from opening_fenix.gui.window_manager import WindowManager
from opening_fenix.core.logger import logger

def cleanup_temp_db_files():
    """
    Attempts to clean up SQLite WAL files by running a checkpoint
    and only deleting side-files for databases that checkpointed cleanly.
    """
    repo_dir = os.path.join(get_user_dir(), "repertoires")
    profiles_dir = os.path.join(get_user_dir(), "profiles")

    for base_folder in [repo_dir, profiles_dir]:
        if not os.path.exists(base_folder):
            continue
        for root, _, files in os.walk(base_folder):
            for f in files:
                if not f.endswith(".db"):
                    continue
                db_path = os.path.join(root, f)
                wal_path = db_path + "-wal"
                shm_path = db_path + "-shm"
                if not (os.path.exists(wal_path) or os.path.exists(shm_path)):
                    continue
                checkpoint_ok = False
                conn = None
                try:
                    conn = sqlite3.connect(db_path, timeout=2.0)
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    checkpoint_ok = True
                except Exception as e:
                    logger.debug(f"Could not checkpoint {f}: {e}")
                finally:
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass
                if checkpoint_ok:
                    for sidecar in (wal_path, shm_path):
                        if os.path.exists(sidecar):
                            try:
                                os.remove(sidecar)
                            except Exception as e:
                                logger.debug(f"Could not remove WAL/SHM file {sidecar}: {e}")

def ensure_default_engine_path():
    """
    Checks if an engine path is set in config.json. If not valid, and if a Stockfish
    executable is found in any bundled 'engines' folder, sets it as default.
    Returns the loaded/updated config dictionary to avoid duplicate config reads at startup.
    """
    config_path = os.path.join(get_user_dir(), "config.json")
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
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
                with open(config_path, "w", encoding="utf-8") as f_out:
                    json.dump(config, f_out, indent=4, ensure_ascii=False)
                logger.info(f"Set default engine path to {found_engine}")
            except Exception as e:
                logger.error(f"Could not save config with default engine path: {e}")
    return config

if __name__ == "__main__":
    # Strip Windows Program Compatibility Assistant shim variables inherited from Setup installer
    # so child processes (such as headless Chromium for PDF textbook export) are not aborted by PCA.
    os.environ.pop("__COMPAT_LAYER", None)

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
            
        myappid = f'OpeningFenix.Lab.V{APP_VERSION}' 
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except (AttributeError, OSError):
             pass

    try:
        logger.info(f"Opening Fenix starting (v{APP_VERSION})...")

        # Enable High DPI scaling and rounding policies for sharp UI
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        
        QApplication.setStyle("Fusion")
        app = QApplication(sys.argv)
        setup_light_palette(app)
        
        # Explicitly set application identity for Windows taskbar grouping
        app.setApplicationName("OpeningFenix")
        app.setOrganizationName("OpeningFenixLab")
        app.setApplicationVersion(APP_VERSION)
        app.setApplicationDisplayName("Opening Fenix")
        
        # Set icon on the app instance immediately
        set_consistent_icon(app)

        logger.info("Application initialized, setting up services...")

        # Pre-load UI language BEFORE cloud sync dialogs so startup warnings are properly localized
        from opening_fenix.core.translation import translator, tr_ui
        _pre_cfg_path = os.path.join(get_user_dir(), "config.json")
        _pre_cfg = {}
        if os.path.exists(_pre_cfg_path):
            try:
                with open(_pre_cfg_path, "r", encoding="utf-8") as _f:
                    _pre_cfg = json.load(_f)
            except Exception:
                _pre_cfg = {}
        if "ui_language" in _pre_cfg:
            _pre_lang = _pre_cfg["ui_language"]
        else:
            _sys_loc = QLocale.system().name().lower()
            _pre_lang = "de" if _sys_loc.startswith("de") else "en"
        translator.load_language(_pre_lang)

        from opening_fenix.core.services.cloud_sync_service import CloudSyncService, format_relative_time
        from opening_fenix.gui.widgets.cloud_sync_widgets import (
            run_sync_with_progress,
            CloudSyncConflictDialog,
        )

        if CloudSyncService.is_offline():
            logger.warning(
                f"CloudSync folder is currently offline/unmounted ({CloudSyncService.get_configured_cloud_dir()}). "
                f"Continuing safely in local_workspace ({get_user_dir()})."
            )
        elif CloudSyncService.is_enabled():
            while True:
                other_sess = CloudSyncService.check_other_active_session()
                if not other_sess:
                    break
                other_dev = other_sess.get("device_name", "Unknown")
                other_time_raw = other_sess.get("heartbeat_at") or other_sess.get("started_at") or ""
                other_time_rel = format_relative_time(other_time_raw) if other_time_raw else other_time_raw
                other_time_disp = f"{other_time_rel} ({other_time_raw})" if other_time_rel and other_time_rel != other_time_raw else other_time_raw
                warn_box = QMessageBox()
                warn_box.setIcon(QMessageBox.Icon.Warning)
                warn_box.setWindowTitle(tr_ui("cloud_sync.lock_title", "Cloud-Synchronisation aktiv"))
                warn_box.setText(
                    tr_ui(
                        "cloud_sync.lock_message",
                        "Opening Fenix scheint noch auf einem anderen Gerät geöffnet zu sein:\n\n"
                        "Gerät: {device}\n"
                        "Letzte Aktivität: {time}\n\n"
                        "Bitte schließe Opening Fenix auf dem anderen Gerät und warte kurz, bis Google Drive / OneDrive "
                        "die Synchronisation abgeschlossen hat.",
                        device=other_dev,
                        time=other_time_disp,
                    )
                )
                btn_retry = warn_box.addButton(tr_ui("cloud_sync.lock_btn_retry", "🔄 Erneut prüfen"), QMessageBox.ButtonRole.AcceptRole)
                btn_open = warn_box.addButton(tr_ui("cloud_sync.lock_btn_open_anyway", "Trotzdem öffnen"), QMessageBox.ButtonRole.DestructiveRole)
                warn_box.addButton(tr_ui("cloud_sync.lock_btn_exit", "Beenden"), QMessageBox.ButtonRole.RejectRole)
                warn_box.exec()
                clicked = warn_box.clickedButton()
                if clicked == btn_retry:
                    continue
                elif clicked == btn_open:
                    break
                else:
                    sys.exit(0)

            CloudSyncService.acquire_session_lock()
            try:
                sync_res = run_sync_with_progress(
                    direction="both",
                    title=tr_ui("cloud_sync.startup_title", "☁️ Cloud-Synchronisation"),
                    subtitle=tr_ui("cloud_sync.startup_subtitle", "Prüfe Cloud-Ordner auf aktuelle Repertoires & Profile..."),
                )
                logger.info(
                    f"Startup CloudSync finished: pulled_repos={len(sync_res.get('pulled_repertoires', []))}, "
                    f"pushed_repos={len(sync_res.get('pushed_repertoires', []))}, "
                    f"merged_profiles={len(sync_res.get('merged_profiles', []))}, "
                    f"migrated_repos={len(sync_res.get('migrated_repertoires', []))}"
                )
                if sync_res.get("conflicts") or sync_res.get("provider_conflict_files"):
                    CloudSyncConflictDialog(
                        conflicts=sync_res.get("conflicts"),
                        merged_profiles=sync_res.get("merged_profiles"),
                        provider_conflict_files=sync_res.get("provider_conflict_files"),
                    ).exec()
            except Exception as sync_err:
                logger.error(f"Startup CloudSync error: {sync_err}")

        from opening_fenix.core.utils import migrate_repertoire_storage, ensure_user_data_seeded
        ensure_user_data_seeded()
        migrate_repertoire_storage()
        
        # Check if legacy profiles exist before importing migration (to save import time)
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        if os.path.exists(profiles_dir) and any(f.endswith(".json") and not f.endswith("_settings.json") for f in os.listdir(profiles_dir)):
            from opening_fenix.core.migration import migrate_legacy_profiles
            migrate_legacy_profiles()
            
        config_path = os.path.join(get_user_dir(), "config.json")
        config = ensure_default_engine_path() or {}
        auto_login_profile = config.get("auto_login_profile")
        ui_lang = "de"

        # Persistent language determination:
        # If already configured in config.json (or synced via shared_settings.json), strictly use saved preference.
        # If running for the first time (no ui_language key), detect system locale once and save it.
        if "ui_language" in config:
            ui_lang = config["ui_language"]
        else:
            sys_locale = QLocale.system().name().lower()  # e.g., 'de_at', 'de_de', 'en_us'
            ui_lang = "de" if sys_locale.startswith("de") else "en"
            config["ui_language"] = ui_lang
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)
                logger.info(f"First start: Detected system locale '{sys_locale}', saved '{ui_lang}' to config.json.")
            except Exception as e:
                logger.error(f"Failed to persist initial ui_language to config.json: {e}")

        # Re-apply TranslationManager in case CloudSync pulled a synced language preference
        translator.load_language(ui_lang)

        initial_profile = None
        if auto_login_profile:
            if auto_login_profile == "Freies Training":
                initial_profile = auto_login_profile
            else:
                profile_path = os.path.join(get_user_dir(), "profiles", f"{auto_login_profile}.db")
                if os.path.exists(profile_path):
                     initial_profile = auto_login_profile

        # Start periodic CloudSync heartbeat manager
        from opening_fenix.core.services.cloud_sync_manager import CloudSyncManager
        CloudSyncManager.instance().start_heartbeat()

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
        try:
            from opening_fenix.core.services.cloud_sync_manager import CloudSyncManager
            CloudSyncManager.instance().stop()
        except Exception:
            pass
        cleanup_temp_db_files()
        try:
            from opening_fenix.core.services.cloud_sync_service import CloudSyncService
            if CloudSyncService.is_enabled():
                if 'app' in locals() and QApplication.instance() is not None:
                    from opening_fenix.core.translation import tr_ui
                    from opening_fenix.gui.widgets.cloud_sync_widgets import run_sync_with_progress
                    sync_res = run_sync_with_progress(
                        direction="push",
                        title=tr_ui("cloud_sync.shutdown_title", "☁️ Cloud-Synchronisation"),
                        subtitle=tr_ui("cloud_sync.shutdown_subtitle", "Sichere Änderungen in deinen Cloud-Ordner..."),
                    )
                else:
                    sync_res = CloudSyncService.sync_now(direction="push")
                logger.info(
                    f"Shutdown CloudSync finished: pushed_repos={len(sync_res.get('pushed_repertoires', []))}, "
                    f"pushed_profiles={len(sync_res.get('pushed_profiles', []))}"
                )
                CloudSyncService.release_session_lock()
        except Exception as e:
            logger.error(f"Shutdown CloudSync error: {e}")

        # Deferred clean restart: launch new instance ONLY after DB cleanup, cloud push, and lock release complete
        try:
            from opening_fenix.core.utils import is_app_restart_requested
            if is_app_restart_requested():
                import subprocess
                if getattr(sys, 'frozen', False):
                    args = [sys.executable] + sys.argv[1:]
                else:
                    args = [sys.executable] + sys.argv
                subprocess.Popen(args)
        except Exception as e:
            logger.error(f"Failed to relaunch application on restart: {e}")
        sys.exit()
