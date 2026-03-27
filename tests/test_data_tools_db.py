import pytest
import os
import opening_fenix.core.data_tools as dt
from opening_fenix.core.models import DatabaseManager, Metadata

def test_set_and_get_meta(mock_user_dir, sample_repertoire):
    db_path = os.path.join(mock_user_dir, "repertoires", f"{sample_repertoire}.db")
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Test setting a new meta value
    dt.set_meta(session, "test_key", "test_value")
    session.commit()
    
    # Test getting the meta value
    val = dt.get_meta(session, "test_key")
    assert val == "test_value"
    
    # Test updating an existing meta value
    dt.set_meta(session, "test_key", "new_value")
    session.commit()
    val2 = dt.get_meta(session, "test_key")
    assert val2 == "new_value"
    
    # Test getting a non-existent key with default
    val3 = dt.get_meta(session, "non_existent", "default_val")
    assert val3 == "default_val"
    
    session.close()
    db.close()

def test_detect_islands_no_islands(mock_user_dir, sample_repertoire):
    # The sample_repertoire fixture creates a connected valid tree (1. e4 e5).
    # Since the tree ends at e5 (White's turn) but has no further moves defined,
    # detect_islands will report a probability dead end for White.
    success, msg = dt.detect_islands(sample_repertoire)
    assert success is True
    assert "probability dead ends" in msg or "dead end" in msg

def test_get_repertoire_analysis_status(mock_user_dir, sample_repertoire):
    status = dt.get_repertoire_analysis_status(sample_repertoire)
    # The sample repertoire has no analysis_depth set for its positions.
    assert status == "Nicht analysiert" 
