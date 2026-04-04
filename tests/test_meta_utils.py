from opening_fenix.core.utils import get_repertoire_db_path
import os
import pytest
from sqlalchemy.orm import Session
from opening_fenix.core.db.models import Metadata, Position, Move
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import (
    get_meta, set_meta, delete_repertoire_db, 
    check_all_databases_integrity, repair_all_databases_cache
)

def test_meta_get_set(mock_user_dir, sample_repertoire):
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Test setting
    set_meta(session, "version", "2.0")
    session.commit()
    
    # Test getting
    assert get_meta(session, "version") == "2.0"
    
    # Test updating
    set_meta(session, "version", "2.1")
    session.commit()
    assert get_meta(session, "version") == "2.1"
    
    # Test default
    assert get_meta(session, "non_existent", "default") == "default"
    
    session.close()
    db.close()

def test_delete_repertoire_db(mock_user_dir, sample_repertoire):
    # Test successful deletion
    success, msg = delete_repertoire_db(sample_repertoire)
    assert success is True
    db_path = get_repertoire_db_path(sample_repertoire)
    assert not os.path.exists(db_path)
    
    # Test non-existent
    success, msg = delete_repertoire_db("NonExistent")
    assert success is False
    assert "nicht gefunden" in msg

def test_check_integrity(mock_user_dir, sample_repertoire):
    # The sample repertoire has no cached variations, but also no variations defined
    # So it should be OK
    result = check_all_databases_integrity()
    assert "OK" in result
    
    # Now add a variation without cache
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    pos = session.query(Position).first()
    pos.variation_1 = "Ruy Lopez"
    pos.cached_v1 = None
    session.commit()
    session.close()
    db.close()
    
    result = check_all_databases_integrity()
    assert "Cache unvollständig" in result

def test_repair_cache(mock_user_dir, sample_repertoire):
    # Setup corrupted cache
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Start position: e4
    # pos1 (start) -> m1 (e4) -> pos2 (e4_fen)
    start_pos = session.query(Position).filter(Position.fen.like("%w KQkq -")).first()
    start_pos.variation_1 = "King's Pawn"
    
    # Mark child position as missing cache
    child_pos = session.query(Position).filter(~Position.fen.like("%w KQkq -")).first()
    child_pos.cached_v1 = None
    
    session.commit()
    session.close()
    db.close()
    
    # Run repair
    result = repair_all_databases_cache()
    assert "Repariert" in result
    
    # Verify repair
    db = DatabaseManager(db_path)
    session = db.get_session()
    child_pos = session.query(Position).filter(~Position.fen.like("%w KQkq -")).first()
    assert child_pos.cached_v1 == "King's Pawn"
    session.close()
    db.close()

def test_repair_no_repertoires(mock_user_dir):
    # Remove the repertoires directory entirely
    repo_dir = os.path.join(mock_user_dir, "repertoires")
    import shutil
    shutil.rmtree(repo_dir)
        
    result = repair_all_databases_cache()
    assert "Keine Repertoires gefunden" in result
