import os
import sqlite3
from opening_fenix.core import utils
from opening_fenix.core.utils import get_user_dir
from opening_fenix.core.logger import logger

def update_repertoire_name_globally(old_name: str, new_name: str):
    """
    Scans all profile databases in the profiles/ directory and updates the 
    repertoire_name reference to ensure learning progress is preserved.
    """
    profiles_dir = os.path.join(utils.get_user_dir(), "profiles")
    if not os.path.exists(profiles_dir):
        logger.warning(f"Profiles directory not found at {profiles_dir}")
        return

    profile_files = [f for f in os.listdir(profiles_dir) if f.endswith(".db")]
    
    updated_count = 0
    for pf in profile_files:
        db_path = os.path.join(profiles_dir, pf)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 1. Update Training Data
            cursor.execute(
                "UPDATE training_data SET repertoire_name = ? WHERE repertoire_name = ?",
                (new_name, old_name)
            )
            training_rows = cursor.rowcount
            
            # 2. Update User Repertoire Settings
            cursor.execute(
                "UPDATE user_repertoire_settings SET repertoire_name = ? WHERE repertoire_name = ?",
                (new_name, old_name)
            )
            settings_rows = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if training_rows > 0 or settings_rows > 0:
                logger.info(f"Updated profile '{pf}': {training_rows} training records, {settings_rows} settings.")
                updated_count += 1
                
        except Exception as e:
            logger.error(f"Failed to update profile '{pf}' during repertoire rename: {e}")

    logger.info(f"Global profile update complete. {updated_count} profiles modified.")


def delete_repertoire_from_profiles_globally(repo_name: str) -> int:
    """
    Scans all profile databases in the profiles/ directory and deletes any
    user_repertoire_settings and training_data entries for the given repertoire.
    Also cleans up active in-memory Qt training sessions.
    Returns the number of profiles modified.
    """
    if not repo_name:
        return 0

    profiles_dir = os.path.join(utils.get_user_dir(), "profiles")
    if not os.path.exists(profiles_dir):
        return 0

    profile_files = [f for f in os.listdir(profiles_dir) if f.endswith(".db")]
    modified_count = 0

    for pf in profile_files:
        db_path = os.path.join(profiles_dir, pf)
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            cursor = conn.cursor()
            
            cursor.execute(
                "DELETE FROM user_repertoire_settings WHERE repertoire_name = ?",
                (repo_name,)
            )
            urs_count = cursor.rowcount
            
            cursor.execute(
                "DELETE FROM training_data WHERE repertoire_name = ?",
                (repo_name,)
            )
            td_count = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if urs_count > 0 or td_count > 0:
                logger.info(f"Cleaned up deleted repertoire '{repo_name}' from profile '{pf}' ({urs_count} settings, {td_count} training rows).")
                modified_count += 1
        except Exception as e:
            logger.error(f"Failed to clean up profile '{pf}' for deleted repertoire '{repo_name}': {e}")

    # Also clean up any active in-memory Qt sessions and caches
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            for w in app.allWidgets():
                # Check MainWindow training_manager
                tm = getattr(w, "training_manager", None)
                if tm:
                    if getattr(tm, "user_session", None):
                        try:
                            from opening_fenix.core.db.models import UserRepertoireSettings, TrainingData
                            tm.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).delete()
                            tm.user_session.query(TrainingData).filter_by(repertoire_name=repo_name).delete()
                            tm.user_session.commit()
                        except Exception:
                            pass
                    if hasattr(tm, "_user_settings_cache"):
                        tm._user_settings_cache = None
                    if hasattr(tm, "_reachable_moves_cache"):
                        tm._reachable_moves_cache = None
                    if hasattr(tm, "_last_stats_cache"):
                        tm._last_stats_cache = None
                # Check sorted_repo_names on MainWindow
                if hasattr(w, "sorted_repo_names") and isinstance(w.sorted_repo_names, list):
                    if repo_name in w.sorted_repo_names:
                        w.sorted_repo_names.remove(repo_name)
    except Exception:
        pass

    logger.info(f"Global profile deletion complete for '{repo_name}'. {modified_count} profiles modified.")
    return modified_count
