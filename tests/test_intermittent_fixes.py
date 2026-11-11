import os
import pytest
import sqlite3
import chess
from opening_fenix.core.services.maintenance_service import MaintenanceOrchestrator
from opening_fenix.core.translation import tr_ui
from opening_fenix.core.services.backup_service import create_repertoire_backup
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.db.models import Base

def test_maintenance_orchestrator_accepts_list_and_set():
    """Verify MaintenanceOrchestrator does not crash with AttributeError when tasks is a list or set."""
    repo_configs = [{"name": "TestRepo"}]
    
    # 1. Tasks as list
    orch_list = MaintenanceOrchestrator(repo_configs, tasks=['lichess', 'engine'], engine_settings=None,
                                        overall_progress_callback=None, repo_status_callback=None, check_cancel=None)
    assert 'lichess' in orch_list.active_tasks
    assert 'engine' in orch_list.active_tasks
    assert 'cleanup' not in orch_list.active_tasks

    # 2. Tasks as set
    orch_set = MaintenanceOrchestrator(repo_configs, tasks={'cleanup', 'stats'}, engine_settings=None,
                                       overall_progress_callback=None, repo_status_callback=None, check_cancel=None)
    assert 'cleanup' in orch_set.active_tasks
    assert 'stats' in orch_set.active_tasks
    assert 'lichess' not in orch_set.active_tasks

    # 3. Tasks as dict
    orch_dict = MaintenanceOrchestrator(repo_configs, tasks={'cleanup': True, 'stats': False}, engine_settings=None,
                                        overall_progress_callback=None, repo_status_callback=None, check_cancel=None)
    assert 'cleanup' in orch_dict.active_tasks
    assert 'stats' not in orch_dict.active_tasks


def test_course_intro_translation_formatting_no_keyerror(caplog):
    """Verify tr_ui formats course_intro placeholders cleanly without KeyError warnings."""
    with caplog.at_level("WARNING"):
        res_moves = tr_ui("course_intro.moves_count", "♟️ {moves} Züge", moves=142)
        res_elo = tr_ui("course_intro.target_elo", "🎓 Ziel-Elo: {target_elo}", target_elo=1850)
    
    assert "142" in res_moves
    assert "1850" in res_elo
    assert "Formatting placeholder error" not in caplog.text


def test_online_backup_with_live_wal(tmp_path):
    """Verify create_repertoire_backup clones WAL pages atomically via online backup."""
    import uuid
    from opening_fenix.core.utils import get_repertoire_dir, get_repertoire_db_path
    
    repo_name = f"OnlineBackupTest_{uuid.uuid4().hex[:8]}"
    db_path = get_repertoire_db_path(repo_name)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Initialize a test DB in WAL mode
    db = DatabaseManager(db_path)
    session = db.get_session()
    from opening_fenix.core.db.models import Position
    pos = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    session.add(pos)
    session.commit()
    session.close()

    # Create backup
    zip_path = create_repertoire_backup(repo_name, trigger_type="manual")
    assert zip_path is not None
    assert os.path.exists(zip_path)

    db.close()
    try:
        import shutil
        repo_dir = get_repertoire_dir(repo_name)
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)
    except Exception:
        pass


def test_safe_urlopen_used_in_network_modules():
    """Verify that lichess_lockout_service and lichess_service import and use safe_urlopen."""
    import inspect
    import opening_fenix.core.services.lichess_lockout_service as lls
    import opening_fenix.core.services.lichess_service as ls
    import opening_fenix.core.utils as cu

    # check safe_urlopen is imported and called in lockout service
    lls_src = inspect.getsource(lls)
    assert "safe_urlopen(req" in lls_src
    assert "urllib.request.urlopen" not in lls_src

    ls_src = inspect.getsource(ls.verify_lichess_token)
    assert "safe_urlopen(req" in ls_src
    assert "urllib.request.urlopen" not in ls_src

    cu_src = inspect.getsource(cu.translate_chess_comment)
    assert "safe_urlopen(req" in cu_src
    assert "urllib.request.urlopen" not in cu_src


def test_instant_multipv_engine_quit_in_finally():
    """Verify InstantMultiPVThread quits engine even when exception is raised."""
    from unittest.mock import MagicMock, patch
    from opening_fenix.core.threads import InstantMultiPVThread
    
    thread = InstantMultiPVThread("dummy_engine_path", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", ["e2e4"])
    
    mock_engine = MagicMock()
    # Simulate an error during engine analysis
    mock_engine.analyse.side_effect = RuntimeError("Crash during analysis")

    with patch("chess.engine.SimpleEngine.popen_uci", return_value=mock_engine):
        # We invoke run directly
        thread.run()

    # Verify engine.quit() was called in finally
    assert mock_engine.quit.called

