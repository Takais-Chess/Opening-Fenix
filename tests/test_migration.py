import os
import json
import datetime
import pytest
import sqlite3
import chess
from opening_fenix.core.migration import migrate_legacy_profiles
from opening_fenix.core.models import DatabaseManager, UserBase, TrainingData, UserRepertoireSettings

def test_migrate_legacy_profiles(mock_user_dir):
    # 1. Setup legacy JSON profile
    profile_name = "LegacyProfile"
    profiles_dir = os.path.join(mock_user_dir, "profiles")
    json_path = os.path.join(profiles_dir, f"{profile_name}.json")
    
    # Mock legacy data
    # We need a position that exists in a repertoire to test training data migration
    repo_name = "TestRepo"
    repo_dir = os.path.join(mock_user_dir, "repertoires")
    repo_db_path = os.path.join(repo_dir, f"{repo_name}.db")
    
    # Create a dummy repertoire DB
    conn = sqlite3.connect(repo_db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, fen TEXT)")
    cursor.execute("CREATE TABLE moves (from_position_id INTEGER, uci TEXT)")
    
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    cursor.execute("INSERT INTO positions (id, fen) VALUES (1, ?)", (start_fen,))
    cursor.execute("INSERT INTO moves (from_position_id, uci) VALUES (1, 'e2e4')")
    conn.commit()
    conn.close()
    
    # Calculate resulting EPD for e4
    board = chess.Board(start_fen)
    board.push_uci("e2e4")
    target_epd = board.epd(hm_moves=False, fm_moves=False)
    
    legacy_data = {
        "_meta_active_repos": [repo_name],
        "_meta_settings": {"theme": "dark"},
        target_epd: {"box": 3, "next_due": "2023-10-27T10:00:00"}
    }
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)
        
    # 2. Run migration
    migrate_legacy_profiles()
    
    # 3. Verify results
    db_path = os.path.join(profiles_dir, f"{profile_name}.db")
    assert os.path.exists(db_path)
    
    # Verify DB content
    db = DatabaseManager(db_path, base=UserBase)
    session = db.get_session()
    
    # Check settings migrated to sidecar
    settings_path = os.path.join(profiles_dir, f"{profile_name}_settings.json")
    assert os.path.exists(settings_path)
    with open(settings_path, "r") as f:
        sidecar_settings = json.load(f)
    assert sidecar_settings["theme"] == "dark"
    
    # Check UserRepertoireSettings
    urs = session.query(UserRepertoireSettings).filter_by(repertoire_name=repo_name).first()
    assert urs is not None
    assert urs.active_level == 1
    
    # Check TrainingData
    td = session.query(TrainingData).filter_by(repertoire_name=repo_name, move_uci="e2e4").first()
    assert td is not None
    assert td.box == 3
    assert td.next_due == datetime.datetime.fromisoformat("2023-10-27T10:00:00")
    
    session.close()
    db.close()
    
    # Verify legacy file was renamed
    assert not os.path.exists(json_path)
    assert os.path.exists(json_path + ".bak")

def test_migrate_no_profiles(mock_user_dir):
    # Should not crash if no profiles exist
    migrate_legacy_profiles()
    # If we get here, it didn't crash

def test_migrate_already_exists(mock_user_dir):
    profile_name = "ExistingProfile"
    profiles_dir = os.path.join(mock_user_dir, "profiles")
    db_path = os.path.join(profiles_dir, f"{profile_name}.db")
    json_path = os.path.join(profiles_dir, f"{profile_name}.json")
    
    # Create empty DB
    with open(db_path, "w") as f: f.write("")
    # Create JSON
    with open(json_path, "w") as f: json.dump({}, f)
    
    migrate_legacy_profiles()
    
    # JSON should still exist because DB existed
    assert os.path.exists(json_path)
