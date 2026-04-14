import pytest
import os
import sqlite3
from opening_fenix.core.services.profile_service import update_repertoire_name_globally

def test_update_repertoire_name_globally_basic(mock_user_dir):
    profiles_dir = os.path.join(mock_user_dir, "profiles")
    os.makedirs(profiles_dir, exist_ok=True)
    
    # Create a dummy profile database
    db_path = os.path.join(profiles_dir, "test_user.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
        CREATE TABLE training_data (
            id INTEGER PRIMARY KEY,
            repertoire_name TEXT,
            fen TEXT,
            move_uci TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE user_repertoire_settings (
            repertoire_name TEXT PRIMARY KEY,
            active_level INTEGER
        )
    """)
    
    # Insert data
    cursor.execute("INSERT INTO training_data (repertoire_name, fen, move_uci) VALUES (?, ?, ?)", 
                   ("OldRepo", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -", "e2e4"))
    cursor.execute("INSERT INTO user_repertoire_settings (repertoire_name, active_level) VALUES (?, ?)", 
                   ("OldRepo", 1))
    
    conn.commit()
    conn.close()
    
    # Run update
    update_repertoire_name_globally("OldRepo", "NewRepo")
    
    # Verify results
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT repertoire_name FROM training_data")
    assert cursor.fetchone()[0] == "NewRepo"
    
    cursor.execute("SELECT repertoire_name FROM user_repertoire_settings")
    assert cursor.fetchone()[0] == "NewRepo"
    
    conn.close()

def test_update_repertoire_name_globally_missing_dir(mock_user_dir, monkeypatch):
    # Mock get_user_dir to point to a non-existent directory
    monkeypatch.setattr("opening_fenix.core.services.profile_service.get_user_dir", lambda: "/non/existent/path")
    
    # This should not crash, but just log a warning and return
    update_repertoire_name_globally("Old", "New")

def test_update_repertoire_name_globally_corrupt_db(mock_user_dir):
    profiles_dir = os.path.join(mock_user_dir, "profiles")
    os.makedirs(profiles_dir, exist_ok=True)
    
    # Create a corrupt/invalid file with .db extension
    db_path = os.path.join(profiles_dir, "corrupt.db")
    with open(db_path, "w") as f:
        f.write("not a database")
        
    # Should not crash, just log and continue
    update_repertoire_name_globally("Old", "New")
