import pytest
import os
import shutil
import tempfile
import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, Base, UserBase
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.repertoire import RepertoireManager
from opening_fenix.core.training import TrainingManager

@pytest.fixture
def temp_dir():
    """Fixture to create a temporary directory for tests with robust cleanup."""
    dir_path = tempfile.mkdtemp()
    yield dir_path
    
    # Robust cleanup for Windows
    def remove_readonly(func, path, excinfo):
        os.chmod(path, 0o777)
        func(path)

    import time
    max_retries = 5
    for i in range(max_retries):
        try:
            shutil.rmtree(dir_path, onerror=remove_readonly)
            break
        except (PermissionError, OSError):
            if i == max_retries - 1:
                # Final attempt: just try to delete what we can
                pass
            time.sleep(0.1) # Wait a bit for file handles to release

@pytest.fixture
def mock_user_dir(temp_dir, monkeypatch):
    """Fixture to mock get_user_dir to point to a temp directory."""
    _apply_mock_user_dir(monkeypatch, temp_dir)
    
    # Create necessary subdirectories
    os.makedirs(os.path.join(temp_dir, "profiles"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "repertoires"), exist_ok=True)
    return temp_dir

def _apply_mock_user_dir(monkeypatch, temp_dir):
    """Helper to apply mocks to multiple modules."""
    paths_to_mock = [
        "opening_fenix.core.data_tools.get_user_dir",
        "opening_fenix.core.services.repertoire_service.get_user_dir",
        "opening_fenix.core.services.training_service.get_user_dir",
        "opening_fenix.core.migration.get_user_dir",
        "opening_fenix.creator.creator_window.get_user_dir",
        "opening_fenix.core.utils.get_user_dir",
        "opening_fenix.core.db.meta_utils.get_user_dir",
        "opening_fenix.core.services.analysis_service.get_user_dir",
        "opening_fenix.core.services.priority_service.get_user_dir",
        "opening_fenix.core.services.lichess_service.get_user_dir",
        "opening_fenix.core.services.import_service.get_user_dir",
        "opening_fenix.core.services.repertoire_core_service.get_user_dir",
        "opening_fenix.core.services.tree_navigation_service.get_user_dir",
        "opening_fenix.core.services.explorer_service.get_user_dir",
        "opening_fenix.core.services.profile_service.get_user_dir"
    ]
    for path in paths_to_mock:
        try:
            monkeypatch.setattr(path, lambda: temp_dir)
        except (ImportError, AttributeError):
            pass # Some paths might not exist yet or be valid in all contexts

@pytest.fixture(scope="module")
def shared_temp_dir():
    """Module-scoped temp directory for grouping tests."""
    dir_path = tempfile.mkdtemp()
    yield dir_path
    # Cleanup logic same as temp_dir
    import time
    max_retries = 5
    for i in range(max_retries):
        try:
            shutil.rmtree(dir_path, ignore_errors=True)
            break
        except:
            time.sleep(0.2)

@pytest.fixture
def sample_repertoire(mock_user_dir):
    """Fixture to create a sample repertoire database."""
    return _create_sample_repertoire(mock_user_dir)

def _create_sample_repertoire(user_dir):
    """Helper to create sample repo data."""
    repo_name = "TestRepo"
    from opening_fenix.core.utils import get_repertoire_db_path
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path, base=Base)
    session = db.get_session()
    
    lvl1 = RepertoireLevel(name="Basic", order=1)
    session.add(lvl1)
    
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    e5_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    
    def norm(f): return " ".join(f.split()[:4])
    
    p1 = Position(fen=norm(start_fen))
    p2 = Position(fen=norm(e4_fen))
    p3 = Position(fen=norm(e5_fen))
    session.add_all([p1, p2, p3])
    session.flush()
    
    m1 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4", priority_score=1.0)
    m2 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="e7e5", san="e5", priority_score=1.0)
    session.add_all([m1, m2])
    session.flush()
    
    rm1 = RepertoireMove(move_id=m1.id, level=1)
    session.add(rm1)
    
    session.commit()
    
    # Verification
    count = session.query(Position).count()
    print(f"DEBUG: Created sample repertoire with {count} positions at {db_path}")
    
    session.close()
    db.close()
    return repo_name

@pytest.fixture
def repertoire_manager(mock_user_dir, sample_repertoire):
    mgr = RepertoireManager(profile_name="TestUser")
    mgr.set_active_repertoire(sample_repertoire)
    yield mgr
    if mgr.repo_session:
        mgr.repo_session.close()
    if mgr.repo_db:
        mgr.repo_db.close()

@pytest.fixture
def training_manager(mock_user_dir, repertoire_manager):
    tm = TrainingManager(profile_name="TestUser", repertoire_manager=repertoire_manager)
    yield tm
    if tm.user_session:
        tm.user_session.close()
    if tm.user_db:
        tm.user_db.close()

@pytest.fixture
def complex_backend(mock_user_dir, sample_repertoire):
    """Fixture for CreatorBackend with sample repertoire."""
    from opening_fenix.creator.creator_window import CreatorBackend
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire("TestRepo")
    yield backend
    backend.close()

@pytest.fixture
def creator_window(qapp, complex_backend):
    """Fixture for CreatorWindow using a complex backend."""
    from opening_fenix.creator.creator_window import CreatorWindow
    win = CreatorWindow("TestRepo")
    win.show()
    yield win
    win.close()

@pytest.fixture(autouse=True)
def silence_ui(monkeypatch):
    """Globally silence interactive dialogs during tests to prevent hangs."""
    from PyQt6.QtWidgets import QMessageBox, QInputDialog
    
    # Mock QMessageBox functions to always return "Yes" or "Ok"
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    
    # Mock QInputDialog.getText to return a fixed name and True
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Test Name", True))

    # Mock CreatorWindow.new_repertoire_dialog
    try:
        from opening_fenix.creator.creator_window import CreatorWindow
        monkeypatch.setattr(CreatorWindow, "new_repertoire_dialog", lambda *args, **kwargs: None)
    except (ImportError, AttributeError):
        pass
    
    # Mock MainWindow.check_for_onboarding
    try:
        from opening_fenix.gui.main_window import MainWindow
        monkeypatch.setattr(MainWindow, "check_for_onboarding", lambda *args, **kwargs: None)
    except (ImportError, AttributeError):
        pass
