import os
import sys
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

def test_repertoire_seeding_preserves_existing_and_adds_new(mock_user_dir, monkeypatch, tmp_path):
    """Test that ensure_user_data_seeded adds new repertoires while never overwriting existing ones."""
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: mock_user_dir)
    
    # Create fake source bundled repertoires: "Existing_Course" and "New_Course"
    fake_source = tmp_path / "fake_bundle"
    source_existing = fake_source / "repertoires" / "Existing_Course"
    source_existing.mkdir(parents=True)
    (source_existing / "Existing_Course.db").write_text("bundled version")
    
    source_new = fake_source / "repertoires" / "New_Course"
    source_new.mkdir(parents=True)
    (source_new / "New_Course.db").write_text("new course content")
    
    # Mock sources in ensure_user_data_seeded
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_source / "app.exe"))
    monkeypatch.setattr("opening_fenix.core.utils.is_public_version", lambda: False)
    monkeypatch.setattr("opening_fenix.core.utils.is_example_repertoire", lambda name: False)

    # In user's repertoires directory: user already has Existing_Course with custom content
    user_repos_dir = os.path.join(mock_user_dir, "repertoires")
    user_existing = os.path.join(user_repos_dir, "Existing_Course")
    os.makedirs(user_existing, exist_ok=True)
    with open(os.path.join(user_existing, "Existing_Course.db"), "w", encoding="utf-8") as f:
        f.write("user modified content - DO NOT OVERWRITE")
    
    ensure_user_data_seeded()
    
    # 1. Existing repertoire must NOT be overwritten
    with open(os.path.join(user_existing, "Existing_Course.db"), "r", encoding="utf-8") as f:
        assert f.read() == "user modified content - DO NOT OVERWRITE"
        
    # 2. New repertoire must be added
    assert os.path.exists(os.path.join(user_repos_dir, "New_Course", "New_Course.db"))
    with open(os.path.join(user_repos_dir, "New_Course", "New_Course.db"), "r", encoding="utf-8") as f:
        assert f.read() == "new course content"

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
