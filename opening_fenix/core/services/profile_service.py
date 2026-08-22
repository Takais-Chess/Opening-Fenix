import os
import sqlite3
from opening_fenix.core.utils import get_user_dir
from opening_fenix.core.logger import logger

def update_repertoire_name_globally(old_name: str, new_name: str):
    """
    Scans all profile databases in the profiles/ directory and updates the 
    repertoire_name reference to ensure learning progress is preserved.
    """
    profiles_dir = os.path.join(get_user_dir(), "profiles")
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
