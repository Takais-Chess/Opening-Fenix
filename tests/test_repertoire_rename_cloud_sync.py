import os
import json
import sqlite3
import pytest
from opening_fenix.core.utils import (
    ensure_user_data_seeded,
    get_repertoire_dir,
    get_repertoire_db_path,
    initialize_repertoire_assets
)
from opening_fenix.core.services.repertoire_core_service import RepertoireService
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Base

def test_deleted_repertoire_does_not_reseed_on_startup(mock_user_dir, monkeypatch, tmp_path):
    """Test that ensure_user_data_seeded does not resurrect a deleted or renamed repertoire."""
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: mock_user_dir)
    
    # Create fake source bundled repertoire
    fake_source = tmp_path / "fake_bundle"
    source_repos = fake_source / "repertoires" / "Example_Course"
    source_repos.mkdir(parents=True)
    (source_repos / "Example_Course.db").write_text("sqlite dummy")
    
    # Mock sources in ensure_user_data_seeded
    monkeypatch.setattr("sys.executable", str(fake_source / "app.exe"))
    monkeypatch.setattr("opening_fenix.core.utils.is_public_version", lambda: False)
    monkeypatch.setattr("opening_fenix.core.utils.is_example_repertoire", lambda name: False)

    # Simulate config with repertoires_seeded = True (course was renamed/deleted)
    config_path = os.path.join(mock_user_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"repertoires_seeded": True, "profiles_seeded": True}, f)
        
    user_repos_dir = os.path.join(mock_user_dir, "repertoires")
    os.makedirs(user_repos_dir, exist_ok=True)
    
    ensure_user_data_seeded()
    
    # Should NOT copy bundled Example_Course back into empty user repertoires dir
    assert not os.path.exists(os.path.join(user_repos_dir, "Example_Course"))

def test_repertoire_rename_wal_flushing(mock_user_dir, monkeypatch):
    """Test that rename_repertoire closes connections, checkpoints WAL, and updates database cleanly."""
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: mock_user_dir)
    
    old_name = "Cloud_Sync_Test_Course"
    new_name = "Cloud Sync Test Course"
    
    old_dir = os.path.join(mock_user_dir, "repertoires", old_name)
    os.makedirs(old_dir, exist_ok=True)
    initialize_repertoire_assets(old_dir)
    
    db_path = os.path.join(old_dir, f"{old_name}.db")
    db = DatabaseManager(db_path, base=Base)
    db.close()
    
    service = RepertoireService()
    success, msg = service.rename_repertoire(old_name, new_name)
    
    assert success is True
    new_dir = os.path.join(mock_user_dir, "repertoires", new_name)
    new_db = os.path.join(new_dir, f"{new_name}.db")
    
    assert os.path.exists(new_dir)
    assert os.path.exists(new_db)
    assert not os.path.exists(old_dir)
    assert not os.path.exists(db_path)
