import pytest
import os
from opening_fenix.core.repertoire import RepertoireManager

def test_delete_repertoire(mock_user_dir, sample_repertoire, repertoire_manager):
    # Verify repertoire exists
    assert sample_repertoire in repertoire_manager.get_all_repertoires()
    
    # Delete it
    success, msg = repertoire_manager.delete_repertoire(sample_repertoire)
    assert success is True
    
    # Verify it is deleted
    assert sample_repertoire not in repertoire_manager.get_all_repertoires()
    assert repertoire_manager.active_repertoire_name is None

def test_get_repertoire_info(repertoire_manager):
    info = repertoire_manager.get_repertoire_info()
    assert info["name"] == "TestRepo" or info["name"] is None # It defaults based on meta
    assert len(info["levels"]) == 1
    assert info["levels"][0] == "Basic"
    assert info["moves"] == 1 # 1 repertoire move in sample_repertoire

def test_update_level_elo(repertoire_manager):
    levels = repertoire_manager.get_repertoire_levels()
    order = levels[0]["order"]
    
    repertoire_manager.update_level_elo(order, 1800)
    
    updated = repertoire_manager.get_level_info(order)
    assert updated.target_elo == 1800

def test_get_variation_structure(repertoire_manager):
    # The sample repertoire has no variations set, so it should be empty
    struct = repertoire_manager.get_variation_structure()
    assert isinstance(struct, dict)
    assert len(struct) == 0

def test_get_repertoire_root_fen(repertoire_manager):
    root_fen = repertoire_manager.get_repertoire_root_fen()
    # It should trace back to the starting fen in the database (1. e4 in sample repo)
    assert "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR" in root_fen or "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR" in root_fen
