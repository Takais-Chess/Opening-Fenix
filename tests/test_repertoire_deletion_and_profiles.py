import os
import pytest
import sqlite3
from opening_fenix.core import utils
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Base, UserBase, Position, Move, UserRepertoireSettings, TrainingData
from opening_fenix.core.db.meta_utils import delete_repertoire_db
from opening_fenix.core.services.profile_service import delete_repertoire_from_profiles_globally
from opening_fenix.core.services.repertoire_service import RepertoireManager
from opening_fenix.core.services.training_service import TrainingManager


def test_repertoire_deletion_cleans_filesystem_and_profiles(mock_user_dir):
    """
    Verifies that when a repertoire is deleted:
    1. Files on disk are completely removed.
    2. UserRepertoireSettings and TrainingData across all profiles are completely removed.
    3. Missing repertoires are not resurrected.
    """
    repo_name = "TestDeleteRepertoire"
    repo_dir = utils.get_repertoire_dir(repo_name, is_test=False)
    db_path = utils.get_repertoire_db_path(repo_name, is_test=False)

    # 1. Initialize repertoire on disk with positions & moves
    utils.initialize_repertoire_assets(repo_dir)
    db = DatabaseManager(db_path, base=Base)
    session = db.get_session()
    pos = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3")
    session.add(pos)
    session.commit()
    session.close()
    db.close()

    assert os.path.exists(repo_dir)
    assert os.path.exists(db_path)

    # 2. Setup user profile referencing this repertoire inside mock_user_dir
    profiles_dir = os.path.join(mock_user_dir, "profiles")
    os.makedirs(profiles_dir, exist_ok=True)
    profile_path = os.path.join(profiles_dir, "TestUser.db")
    prof_db = DatabaseManager(profile_path, base=UserBase)
    prof_session = prof_db.get_session()
    prof_session.add(UserRepertoireSettings(repertoire_name=repo_name, active_level=1))
    prof_session.add(TrainingData(
        repertoire_name=repo_name,
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",
        move_uci="e2e4",
        box=1
    ))
    prof_session.commit()
    prof_session.close()
    prof_db.close()

    # Verify profile has the entries
    conn = sqlite3.connect(profile_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM user_repertoire_settings WHERE repertoire_name = ?", (repo_name,))
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM training_data WHERE repertoire_name = ?", (repo_name,))
    assert cur.fetchone()[0] == 1
    conn.close()

    # 3. Delete repertoire
    success, msg = delete_repertoire_db(repo_name)
    assert success is True
    assert not os.path.exists(repo_dir)
    assert not os.path.exists(db_path)

    # 4. Verify profile was cleaned up
    conn = sqlite3.connect(profile_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM user_repertoire_settings WHERE repertoire_name = ?", (repo_name,))
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM training_data WHERE repertoire_name = ?", (repo_name,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_training_manager_get_visible_repos_self_heals(mock_user_dir):
    """
    Verifies that get_visible_repos() filters out and cleans up any orphaned
    repertoire entries from the profile database.
    """
    rm = RepertoireManager(profile_name="SelfHealUser")
    tm = TrainingManager(profile_name="SelfHealUser", repertoire_manager=rm)

    # Inject an orphaned repertoire setting directly into the profile session
    orphan_repo = "NonExistentGhostRepo"
    tm.user_session.add(UserRepertoireSettings(repertoire_name=orphan_repo, active_level=1))
    tm.user_session.commit()

    # Verify it was written
    count_before = tm.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=orphan_repo).count()
    assert count_before == 1

    # Calling get_visible_repos should self-heal and not return the ghost
    visible = tm.get_visible_repos()
    assert orphan_repo not in visible

    # Verify self-healing deleted the orphaned row
    count_after = tm.user_session.query(UserRepertoireSettings).filter_by(repertoire_name=orphan_repo).count()
    assert count_after == 0

    tm.user_session.close()
    tm.user_db.close()


def test_set_active_repertoire_does_not_create_ghost_db(mock_user_dir):
    """
    Verifies that calling set_active_repertoire with a non-existent name
    does NOT recreate an empty database file on disk.
    """
    rm = RepertoireManager(profile_name="GhostTestUser")
    ghost_name = "DefinitelyNonExistentRepo"
    ghost_db = utils.get_repertoire_db_path(ghost_name, is_test=False)

    assert not os.path.exists(ghost_db)

    # Try setting it active with create_if_missing=False
    rm.set_active_repertoire(ghost_name, create_if_missing=False)

    # It must not create the file or folder
    assert not os.path.exists(ghost_db)
    assert rm.active_repertoire_name is None
