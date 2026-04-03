from opening_fenix.core.utils import get_repertoire_db_path
import pytest
import os
import chess
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.services.priority_service import calculate_priority_scores, detect_islands
from opening_fenix.core.services.analysis_service import run_db_analysis, get_repertoire_analysis_status

def test_import_pgn_invalid_path(mock_user_dir):
    """Test importing from a non-existent PGN file."""
    success, msg = import_pgn_to_db("non_existent.pgn", "TestRepo", "w", "Basic", 1)
    assert success is False
    assert "Fehler beim Import" in msg

def test_import_pgn_malformed_content(mock_user_dir, temp_dir):
    """Test importing a malformed PGN file."""
    pgn_path = os.path.join(temp_dir, "malformed.pgn")
    with open(pgn_path, "w") as f:
        f.write("This is not a PGN file.")
    
    success, msg = import_pgn_to_db(pgn_path, "TestRepo", "w", "Basic", 1)
    # chess.pgn might just return None for games it can't read, and import_pgn_to_db returns False if no moves found
    assert success is False
    assert "Keine neuen Züge" in msg or "Fehler" in msg

def test_import_pgn_empty_file(mock_user_dir, temp_dir):
    """Test importing an empty PGN file."""
    pgn_path = os.path.join(temp_dir, "empty.pgn")
    with open(pgn_path, "w") as f:
        f.write("")
        
    success, msg = import_pgn_to_db(pgn_path, "TestRepo", "w", "Basic", 1)
    assert success is False
    assert "Keine neuen Züge" in msg

def test_calculate_priority_invalid_repo(mock_user_dir):
    """Test calculating priority for a non-existent repository."""
    success, msg = calculate_priority_scores("NonExistentRepo", "1600")
    # It might fail because the DB file doesn't exist
    assert success is False
    assert "no positions" in msg.lower()

def test_calculate_priority_empty_db(mock_user_dir):
    """Test calculating priority for an empty repository."""
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base
    
    repo_name = "EmptyRepo"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path, base=Base)
    db.close()
    
    success, msg = calculate_priority_scores(repo_name, "1600")
    assert success is False
    assert "no positions" in msg.lower() or "Error" in msg

def test_analysis_status_non_existent(mock_user_dir):
    """Test getting analysis status for a non-existent repo."""
    status = get_repertoire_analysis_status("MissingRepo")
    assert "nicht gefunden" in status.lower()

def test_run_analysis_invalid_engine(mock_user_dir, sample_repertoire):
    """Test running analysis with an invalid engine path."""
    success, msg = run_db_analysis(sample_repertoire, "invalid_engine_path", 10, 1)
    assert success is False
    assert "Fehler" in msg

def test_detect_islands_empty_repo(mock_user_dir):
    """Test island detection on an empty repo."""
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base
    
    repo_name = "IslandEmpty"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path, base=Base)
    db.close()
    
    success, msg = detect_islands(repo_name)
    assert success is True
    assert "no positions" in msg.lower()

def test_import_pgn_valid_small(mock_user_dir, temp_dir):
    """Test a valid small PGN import to ensure basic functionality works in the new test suite."""
    pgn_path = os.path.join(temp_dir, "small.pgn")
    with open(pgn_path, "w") as f:
        f.write("[Event \"Test\"]\n[Site \"?\"]\n[Date \"????.??.??\"]\n[Round \"?\"]\n[White \"?\"]\n[Black \"?\"]\n[Result \"*\"]\n\n1. e4 e5 2. Nf3 Nc6 *\n")
        
    success, msg = import_pgn_to_db(pgn_path, "SmallRepo", "w", "Main", 1)
    assert success is True
    assert "erfolgreich importiert" in msg
