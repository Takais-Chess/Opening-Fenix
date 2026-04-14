import pytest
import os
import json
import chess
from opening_fenix.core.utils import (
    get_base_path,
    get_user_dir,
    _update_lichess_delay_config,
    normalize_fen,
    get_repertoire_dir,
    get_repertoire_db_path,
    initialize_repertoire_assets,
    migrate_repertoire_storage,
    localize_san
)

def test_get_paths():
    # Basic sanity checks
    assert get_base_path() is not None
    assert get_user_dir() is not None

def test_update_lichess_delay_config(mock_user_dir):
    config_path = os.path.join(mock_user_dir, "config.json")
    
    # Update delay
    _update_lichess_delay_config(0.5)
    
    # Verify file content
    with open(config_path, "r") as f:
        config = json.load(f)
    assert config["lichess_delay"] == 0.5
    
    # Update again
    _update_lichess_delay_config(1.0)
    with open(config_path, "r") as f:
        config = json.load(f)
    assert config["lichess_delay"] == 1.0

def test_normalize_fen():
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert normalize_fen(board) == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"

def test_get_repertoire_dir(mock_user_dir):
    repo_base = os.path.join(mock_user_dir, "repertoires")
    
    # Test True
    assert get_repertoire_dir("Repo", is_test=True) == os.path.join(repo_base, "test", "Repo")
    # Test False
    assert get_repertoire_dir("Repo", is_test=False) == os.path.join(repo_base, "Repo")
    
    # Test None (Fallback by discovery)
    regular_path = os.path.join(repo_base, "Exist")
    os.makedirs(regular_path)
    assert get_repertoire_dir("Exist") == regular_path
    
    test_path = os.path.join(repo_base, "test", "ExistTest")
    os.makedirs(test_path)
    assert get_repertoire_dir("ExistTest") == test_path
    
    # Test None (Fallback by name)
    assert get_repertoire_dir("TestNew") == os.path.join(repo_base, "test", "TestNew")
    assert get_repertoire_dir("New") == os.path.join(repo_base, "New")

def test_get_repertoire_db_path(mock_user_dir):
    path = get_repertoire_db_path("MyRepo", is_test=False)
    assert path.endswith("MyRepo\\MyRepo.db") or path.endswith("MyRepo/MyRepo.db")

def test_initialize_repertoire_assets(temp_dir):
    initialize_repertoire_assets(temp_dir)
    assert os.path.exists(os.path.join(temp_dir, "Model Games.pgn"))
    assert os.path.exists(os.path.join(temp_dir, "Typical Motives.pgn"))
    assert os.path.isdir(os.path.join(temp_dir, "Tactics"))
    assert os.path.exists(os.path.join(temp_dir, "Tactics", "Tactics.pgn"))

def test_migrate_repertoire_storage(mock_user_dir):
    repo_base = os.path.join(mock_user_dir, "repertoires")
    os.makedirs(repo_base, exist_ok=True)
    
    # Create legacy DB
    old_db = os.path.join(repo_base, "Legacy.db")
    with open(old_db, "w") as f: f.write("db")
    
    # Create legacy test DB
    old_test_db = os.path.join(repo_base, "TestLegacy.db")
    with open(old_test_db, "w") as f: f.write("test_db")
    
    migrate_repertoire_storage()
    
    # Verify migration
    assert not os.path.exists(old_db)
    assert os.path.exists(os.path.join(repo_base, "Legacy", "Legacy.db"))
    assert os.path.exists(os.path.join(repo_base, "test", "TestLegacy", "TestLegacy.db"))

def test_localize_san():
    assert localize_san("e4", "en") == "e4"
    assert localize_san("e4", "de") == "e4"
    assert localize_san("Nf3", "de") == "Sf3"
    assert localize_san("Bxe4", "de") == "Lxe4"
    assert localize_san("Qd4", "de") == "Dd4"
    assert localize_san("Rad1", "de") == "Tad1"
    assert localize_san("e8=Q", "de") == "e8=D"
    assert localize_san("Kf2", "de") == "Kf2" # King stays K
    assert localize_san("Nf3", "unknown") == "Nf3"
