import os
import json
import datetime
from opening_fenix.core.models import DatabaseManager, UserBase, TrainingData, UserRepertoireSettings
from opening_fenix.core.data_tools import get_user_dir

def migrate_legacy_profiles():
    """
    Migrates legacy JSON profiles to the new SQLite database format.
    """
    profiles_dir = os.path.join(get_user_dir(), "profiles")
    if not os.path.exists(profiles_dir):
        return

    # Find all JSON profile files
    json_files = [f for f in os.listdir(profiles_dir) if f.endswith(".json") and not f.endswith("_settings.json")]
    
    for json_file in json_files:
        profile_name = json_file.replace(".json", "")
        db_path = os.path.join(profiles_dir, f"{profile_name}.db")
        
        # Skip if DB already exists (assume already migrated or new profile)
        if os.path.exists(db_path):
            continue
            
        print(f"Migrating profile '{profile_name}'...")
        
        try:
            # 1. Load JSON data
            with open(os.path.join(profiles_dir, json_file), "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 2. Initialize new DB
            db = DatabaseManager(db_path, base=UserBase)
            session = db.get_session()
            
            # 3. Migrate Active Repos & Settings
            active_repos = data.get("_meta_active_repos", [])
            settings = data.get("_meta_settings", {})
            
            # Save settings to sidecar JSON (as per current design decision)
            settings_path = os.path.join(profiles_dir, f"{profile_name}_settings.json")
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=4)
                
            # Create UserRepertoireSettings for active repos
            if active_repos:
                for repo_name in active_repos:
                    # Default level 1, can be adjusted by user later
                    urs = UserRepertoireSettings(repertoire_name=repo_name, active_level=1)
                    session.add(urs)
            
            # 4. Migrate Training Data
            # The old format was: { "epd_string": { "box": int, "next_due": "iso_date_string" }, ... }
            # We need to map EPD to FEN + Move UCI.
            # The old system used EPDs which are FENs without move clocks.
            # However, the key was the position AFTER the move.
            # The new system stores (FEN_BEFORE, MOVE_UCI).
            # This is tricky. We need to reverse-engineer the move from the repertoire DBs.
            
            # Strategy:
            # Iterate through all available repertoire DBs.
            # For each repertoire, load all moves.
            # Calculate the resulting EPD for each move.
            # If that EPD exists in the user's JSON progress, create a TrainingData entry.
            
            repo_dir = os.path.join(get_user_dir(), "repertoires")
            if os.path.exists(repo_dir):
                import sqlite3
                import chess
                
                repo_files = [f for f in os.listdir(repo_dir) if f.endswith(".db")]
                
                for repo_file in repo_files:
                    repo_name = repo_file.replace(".db", "")
                    
                    # Only migrate data for active repos to save time/space? 
                    # No, migrate everything found in JSON that matches a repo.
                    
                    repo_db_path = os.path.join(repo_dir, repo_file)
                    try:
                        conn = sqlite3.connect(repo_db_path)
                        cursor = conn.cursor()
                        
                        # Get all moves: uci, from_fen
                        # We need to reconstruct the board to get the resulting EPD
                        # This is slow but necessary.
                        
                        # Optimization: Get all positions and moves
                        cursor.execute("SELECT id, fen FROM positions")
                        positions = {row[0]: row[1] for row in cursor.fetchall()}
                        
                        cursor.execute("SELECT from_position_id, uci FROM moves")
                        moves = cursor.fetchall()
                        
                        conn.close()
                        
                        for from_pos_id, uci in moves:
                            if from_pos_id not in positions: continue
                            
                            from_fen = positions[from_pos_id]
                            
                            # Calculate resulting EPD
                            board = chess.Board(from_fen)
                            try:
                                move = chess.Move.from_uci(uci)
                                board.push(move)
                                epd = board.epd(hm_moves=False, fm_moves=False)
                                
                                # Check if this EPD is in the legacy JSON data
                                if epd in data:
                                    entry_data = data[epd]
                                    
                                    # Create TrainingData
                                    # Check if already exists (duplicate EPDs in different repos?)
                                    existing = session.query(TrainingData).filter_by(
                                        repertoire_name=repo_name,
                                        fen=from_fen,
                                        move_uci=uci
                                    ).first()
                                    
                                    if not existing:
                                        next_due_str = entry_data.get("next_due")
                                        if next_due_str:
                                            try:
                                                next_due = datetime.datetime.fromisoformat(next_due_str)
                                            except:
                                                next_due = datetime.datetime.now()
                                        else:
                                            next_due = datetime.datetime.now()
                                            
                                        td = TrainingData(
                                            repertoire_name=repo_name,
                                            fen=from_fen,
                                            move_uci=uci,
                                            box=entry_data.get("box", 0),
                                            next_due=next_due,
                                            streak=0, # Legacy didn't track streak explicitly in the same way
                                            last_review=datetime.datetime.now() # Approximate
                                        )
                                        session.add(td)
                                        
                            except ValueError:
                                continue
                                
                    except Exception as e:
                        print(f"Error processing repo {repo_name}: {e}")
            
            session.commit()
            session.close()
            db.close()
            
            # Rename old JSON to .json.bak to prevent re-migration
            os.rename(os.path.join(profiles_dir, json_file), os.path.join(profiles_dir, json_file + ".bak"))
            print(f"Profile '{profile_name}' migrated successfully.")
            
        except Exception as e:
            print(f"Failed to migrate profile '{profile_name}': {e}")
            # Clean up partial DB
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except: pass

if __name__ == "__main__":
    migrate_legacy_profiles()
