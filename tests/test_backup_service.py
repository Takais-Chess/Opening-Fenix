import os
import json
import pytest
import sqlite3
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QApplication, QWidget
from opening_fenix.core.services.backup_service import (
    create_repertoire_backup,
    list_repertoire_backups,
    compute_repertoire_checksum,
    prune_repertoire_backups,
    restore_repertoire_from_backup,
    get_repertoire_backup_dir
)
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


@pytest.fixture
def temp_repo(tmp_path, monkeypatch):
    """Creates a temporary repertoire directory structure with DB and PGN files."""
    user_dir = tmp_path / "user_data"
    user_dir.mkdir()
    
    monkeypatch.setattr("opening_fenix.core.services.backup_service.get_user_dir", lambda: str(user_dir))
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(user_dir))

    repo_name = "TestBackupRepo"
    repo_dir = user_dir / "repertoires" / repo_name
    repo_dir.mkdir(parents=True)
    
    # Create DB file with table schema
    db_path = repo_dir / f"{repo_name}.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE positions (id TEXT PRIMARY KEY, fen TEXT, comment TEXT, level INT, priority REAL)")
    c.execute("INSERT INTO metadata VALUES ('name', 'TestBackupRepo')")
    c.execute("INSERT INTO positions (id, fen, comment, level, priority) VALUES ('pos1', 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', '{\"en\": \"Initial comment\"}', 1, 1.0)")
    conn.commit()
    conn.close()
    
    # Create PGN directories & sample files
    ideas_dir = repo_dir / "typical_ideas"
    ideas_dir.mkdir()
    (ideas_dir / "ideas.pgn").write_text("[Event \"Typical Idea 1\"]\n1. e4 e5 *")

    games_dir = repo_dir / "model_games"
    games_dir.mkdir()
    (games_dir / "game1.pgn").write_text("[Event \"Model Game 1\"]\n1. d4 d5 *")
    
    return repo_name, user_dir


def test_backup_creation_and_deduplication(temp_repo):
    repo_name, user_dir = temp_repo
    
    # 1. Create first backup
    zip_path1 = create_repertoire_backup(repo_name, trigger_type="auto")
    assert zip_path1 is not None
    assert os.path.exists(zip_path1)
    
    backups1 = list_repertoire_backups(repo_name)
    assert len(backups1) == 1
    assert backups1[0]["trigger_type"] == "auto"
    assert "EN" in backups1[0]["comment_stats"]

    # 2. Trigger second backup without modifying anything -> Should be skipped (deduplicated)
    zip_path2 = create_repertoire_backup(repo_name, trigger_type="auto")
    assert zip_path2 is None
    
    backups2 = list_repertoire_backups(repo_name)
    assert len(backups2) == 1


def test_backup_and_restore(temp_repo):
    repo_name, user_dir = temp_repo
    db_path = get_repertoire_db_path(repo_name)

    # Backup initial state
    zip_path = create_repertoire_backup(repo_name, trigger_type="manual")
    assert zip_path is not None

    # Modify DB file
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE positions SET comment = '{\"en\": \"Modified comment\"}' WHERE id = 'pos1'")
    conn.commit()
    conn.close()

    # Verify modification
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT comment FROM positions WHERE id = 'pos1'")
    assert "Modified" in c.fetchone()[0]
    conn.close()

    # Restore from initial backup
    ok = restore_repertoire_from_backup(repo_name, zip_path)
    assert ok is True

    # Verify restoration
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT comment FROM positions WHERE id = 'pos1'")
    assert "Initial comment" in c.fetchone()[0]
    conn.close()


def test_retention_pruning(temp_repo):
    repo_name, user_dir = temp_repo
    b_dir = get_repertoire_backup_dir(repo_name)

    now = datetime.now()
    
    # Create dummy backup files spanning different days, including multiple on day 12 and day 45
    for idx, days_ago in enumerate([0, 1, 2, 3, 4, 5, 6, 12, 12.01, 12.02, 15, 45, 45.01, 400]):
        dt = now - timedelta(days=days_ago)
        fname = f"backup_{repo_name}_{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{idx}.zip"
        fp = os.path.join(b_dir, fname)
        with open(fp, "w") as f:
            f.write("dummy zip content")
        os.utime(fp, (dt.timestamp(), dt.timestamp()))

    backups_before = list_repertoire_backups(repo_name)
    assert len(backups_before) >= 12

    # Prune
    prune_repertoire_backups(repo_name)

    backups_after = list_repertoire_backups(repo_name)
    assert len(backups_after) < len(backups_before)


def test_repo_settings_dialog_backup_integration(qapp, temp_repo):
    from opening_fenix.gui.dialogs.repo_settings_dialog import RepoSettingsDialog
    repo_name, user_dir = temp_repo

    class MockBackend:
        def __init__(self, name):
            self.active_repo_name = name
            self.session = None
        def scan_and_update_metadata(self): pass
        def get_repertoire_info(self, fast_only=False): return {"name": self.active_repo_name, "moves": 10, "levels": 1, "elo": 800, "depth": 5, "description": ""}
        def get_repo_info_fast(self): return {"name": self.active_repo_name, "moves": 10, "levels": 1, "elo": 800, "depth": 5, "description": ""}
        def get_repertoire_levels(self): return []
        def get_stats_tuple(self): return (0, 0, {})
        def get_meta(self, k, default=None): return default

    class MockMainWindow(QWidget):
        def __init__(self, name):
            super().__init__()
            self.backend = MockBackend(name)
            self.config = {}

    mw = MockMainWindow(repo_name)
    dialog = RepoSettingsDialog(parent=mw, backend=mw.backend)
    dialog.refresh_backups_list()
    assert dialog.tbl_backups.rowCount() == 0

    dialog.create_manual_backup_now()
    assert dialog.tbl_backups.rowCount() == 1
    dialog.close()
