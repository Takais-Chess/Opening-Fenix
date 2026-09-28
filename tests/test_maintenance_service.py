import pytest
import os
from unittest.mock import MagicMock, patch
from opening_fenix.core.services.maintenance_service import (
    get_repertoire_elo,
    list_all_repertoires,
    MaintenanceOrchestrator,
    run_group_maintenance
)

@pytest.fixture
def mock_repo_dir(temp_dir, monkeypatch):
    repo_base = os.path.join(temp_dir, "repertoires")
    os.makedirs(repo_base, exist_ok=True)
    monkeypatch.setattr("opening_fenix.core.services.maintenance_service.get_user_dir", lambda: temp_dir)
    return repo_base

def test_get_repertoire_elo_nonexistent(tmp_path):
    # Test path that doesn't exist
    assert get_repertoire_elo("NonExistentRepo") == "high"

def test_get_repertoire_elo_with_db(mock_user_dir, sample_repertoire):
    # The sample_repertoire fixture creates a DB. 
    # We need to ensure get_meta returns what we expect or we mock it.
    with patch("opening_fenix.core.services.maintenance_service.get_meta") as mock_get_meta:
        mock_get_meta.return_value = "low_elo"
        assert get_repertoire_elo(sample_repertoire) == "low"
        
        mock_get_meta.return_value = "mid_range"
        assert get_repertoire_elo(sample_repertoire) == "mid"
        
        mock_get_meta.return_value = "masters_level"
        assert get_repertoire_elo(sample_repertoire) == "masters"
        
        mock_get_meta.return_value = "something_else"
        assert get_repertoire_elo(sample_repertoire) == "high"

def test_list_all_repertoires(mock_repo_dir):
    # Create some dummy repo structures
    repo1_dir = os.path.join(mock_repo_dir, "Repo1")
    os.makedirs(repo1_dir)
    with open(os.path.join(repo1_dir, "Repo1.db"), "w") as f: f.write("")
    
    # Repo without DB should be ignored
    os.makedirs(os.path.join(mock_repo_dir, "RepoNoDB"))
    
    # Test subdirectory
    test_dir = os.path.join(mock_repo_dir, "test")
    os.makedirs(test_dir)
    repo2_dir = os.path.join(test_dir, "Repo2")
    os.makedirs(repo2_dir)
    with open(os.path.join(repo2_dir, "Repo2.db"), "w") as f: f.write("")
    
    with patch("opening_fenix.core.services.maintenance_service.get_repertoire_elo") as mock_elo:
        mock_elo.return_value = "mid"
        repos = list_all_repertoires(include_elo=True)
        
        assert len(repos) == 2
        names = [r['name'] for r in repos]
        assert "Repo1" in names
        assert "Repo2" in names
        assert all(r['elo'] == "mid" for r in repos)

@patch("opening_fenix.core.services.maintenance_service.run_db_analysis")
@patch("opening_fenix.core.services.maintenance_service.run_lichess_import")
@patch("opening_fenix.core.services.maintenance_service.calculate_priority_scores")
def test_maintenance_orchestrator_full_run(mock_priority, mock_lichess, mock_analysis):
    mock_analysis.return_value = (True, "Analysis OK")
    mock_lichess.return_value = (True, "Lichess OK")
    
    repo_configs = [{'name': 'Repo1', 'elo': 'high'}]
    tasks = {'engine': True, 'lichess': True, 'stats': True}
    engine_settings = {'path': 'path/to/engine', 'depth': 10, 'threads': 1}
    
    progress_calls = []
    status_calls = []
    
    def progress_cb(curr, total, name):
        progress_calls.append((curr, total, name))
        
    def status_cb(name, task, p, status):
        status_calls.append((name, task, p, status))
        
    orchestrator = MaintenanceOrchestrator(
        repo_configs, tasks, engine_settings,
        progress_cb, status_cb, lambda: False
    )
    
    success, msg = orchestrator.run()
    
    assert success is True
    assert mock_analysis.called
    assert mock_lichess.called
    assert mock_priority.called
    assert len(progress_calls) > 0
    assert progress_calls[-1] == (1, 1, 'Repo1')

@patch("opening_fenix.core.services.maintenance_service.run_db_analysis")
def test_maintenance_orchestrator_cancel(mock_analysis):
    import time
    def mock_run(*args, **kwargs):
        time.sleep(1)
        return (True, "OK")
    mock_analysis.side_effect = mock_run
    
    repo_configs = [{'name': 'Repo1', 'elo': 'high'}]
    tasks = {'engine': True}
    
    # Orchestrator that cancels immediately
    orchestrator = MaintenanceOrchestrator(
        repo_configs, tasks, {'path': 'fake', 'depth': 10, 'threads': 1},
        None, lambda *args: None, lambda: True
    )
    
    success, msg = orchestrator.run()
    assert success is False
    assert "Abgebrochen" in msg

def test_run_group_maintenance_wrapper():
    with patch.object(MaintenanceOrchestrator, 'run') as mock_run:
        mock_run.return_value = (True, "Success")
        res = run_group_maintenance([], {}, None)
        assert res == (True, "Success")

def test_dual_mode_cell(qapp):
    from opening_fenix.gui.dialogs.unified_settings_dialog import DualModeCell
    cell = DualModeCell("Initial Text")
    assert cell.text() == "Initial Text"
    assert not cell.label.isHidden()
    assert cell.progress_bar.isHidden()

    # Switch to progress mode with custom format_str
    cell.show_progress(45, "Calculating 45%", format_str="45% (15/33)")
    assert cell.label.isHidden()
    assert not cell.progress_bar.isHidden()
    assert cell.progress_bar.value() == 45
    assert cell.progress_bar.format() == "45% (15/33)"

    # Test heartbeat animation
    cell.update_heartbeat("...")
    assert cell.progress_bar.format() == "45% (15/33) ..."

    # Switch back to text mode
    cell.show_text("Laden...", "Loading tooltip")
    assert not cell.label.isHidden()
    assert cell.progress_bar.isHidden()
    assert cell.text() == "Laden..."

    # Test update_loading_text
    cell.update_loading_text("Laden..")
    assert cell.text() == "Laden.."

    # Finished text mode
    cell.show_text("Tiefe: 18 ✓", "Finished")
    assert not cell.label.isHidden()
    assert cell.progress_bar.isHidden()
    assert cell.text() == "Tiefe: 18 ✓"
    # update_loading_text should not touch completed text
    cell.update_loading_text("Laden...")
    assert cell.text() == "Tiefe: 18 ✓"

@patch("opening_fenix.core.services.maintenance_service.run_db_analysis")
def test_engine_worker_micro_progress(mock_analysis):
    def fake_analysis(name, path, depth, threads, progress_callback, check_cancel):
        progress_callback(12, 15, 120)
        return True, "OK"
    mock_analysis.side_effect = fake_analysis

    status_events = []
    def status_cb(repo_name, task_type, pct, text):
        status_events.append((repo_name, task_type, pct, text))

    orchestrator = MaintenanceOrchestrator(
        [{'name': 'TestRepo', 'elo': 'high'}],
        {'engine': True},
        {'path': 'stockfish.exe', 'depth': 18, 'threads': 1},
        None, status_cb, lambda: False
    )
    orchestrator._engine_worker()

    assert any(ev == ('TestRepo', 'engine', 12, '15/120') for ev in status_events)
    assert any(ev == ('TestRepo', 'engine', 100, 'Fertig') for ev in status_events)


@patch("opening_fenix.core.services.maintenance_service.get_repertoire_db_path")
@patch("opening_fenix.core.services.maintenance_service.DatabaseManager")
@patch("opening_fenix.core.services.maintenance_service.find_repertoire_transpositions")
@patch("opening_fenix.core.services.maintenance_service.save_cached_transpositions")
def test_maintenance_orchestrator_transpositions_2move(mock_save, mock_find, mock_db_m, mock_db_path, tmp_path):
    mock_db_file = tmp_path / "TestRepo.db"
    mock_db_file.write_text("dummy")
    mock_db_path.return_value = str(mock_db_file)

    mock_db_instance = MagicMock()
    mock_session = MagicMock()
    mock_db_instance.get_session.return_value = mock_session
    mock_db_m.return_value = mock_db_instance

    # Return mix of 1-move and 2-move transpositions
    mock_find.return_value = [
        {"depth": 1, "path_ucis": ["e2e4"], "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"},
        {"depth": 2, "path_ucis": ["c7c5", "g1f3"], "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR"}
    ]

    status_events = []
    def status_cb(repo_name, task_type, pct, text):
        status_events.append((repo_name, task_type, pct, text))

    orchestrator = MaintenanceOrchestrator(
        [{'name': 'TestRepo', 'elo': 'high'}],
        {'transpositions': True},
        {'path': 'stockfish.exe', 'depth': 18, 'transpos_depth': 25, 'threads': 2},
        None, status_cb, lambda: False
    )
    orchestrator._engine_worker()

    assert mock_find.called
    assert mock_find.call_args[1]["depth"] == 25
    assert mock_save.called
    saved_items = mock_save.call_args[0][1]
    assert len(saved_items) == 1
    assert saved_items[0]["depth"] == 2
    assert saved_items[0]["path_ucis"] == ["c7c5", "g1f3"]

    assert any(ev == ('TestRepo', 'transpositions', 0, 'Überleitungen...') for ev in status_events)
    assert any(ev == ('TestRepo', 'transpositions', 100, 'Fertig') for ev in status_events)
    assert 'transpositions' in orchestrator.tasks_done['TestRepo']


@patch("opening_fenix.core.services.maintenance_service.run_lichess_import")
@patch("opening_fenix.core.services.maintenance_service.calculate_priority_scores")
def test_maintenance_orchestrator_pipelined_stats(mock_priority, mock_lichess):
    import time
    order_of_events = []

    def fake_lichess(name, elo, progress_callback, check_cancel, reuse_other_courses, max_data_age_days):
        order_of_events.append(f"lichess_start_{name}")
        time.sleep(0.05)
        order_of_events.append(f"lichess_done_{name}")
        return True, "OK"
    mock_lichess.side_effect = fake_lichess

    def fake_priority(name, elo):
        order_of_events.append(f"stats_start_{name}")
        time.sleep(0.05)
        order_of_events.append(f"stats_done_{name}")
    mock_priority.side_effect = fake_priority

    repo_configs = [
        {'name': 'CourseA', 'elo': 'high'},
        {'name': 'CourseB', 'elo': 'high'}
    ]
    tasks = {'lichess': True, 'stats': True}

    orchestrator = MaintenanceOrchestrator(
        repo_configs, tasks, {}, None, None, lambda: False
    )
    success, msg = orchestrator.run()

    assert success is True
    # Pipelining check: CourseB lichess should start before or right when CourseA stats runs
    assert "lichess_done_CourseA" in order_of_events
    assert "stats_done_CourseA" in order_of_events
    assert "lichess_done_CourseB" in order_of_events
    assert "stats_done_CourseB" in order_of_events

    # CourseB lichess should start before CourseA stats completes
    idx_lichess_b = order_of_events.index("lichess_start_CourseB")
    idx_stats_a_done = order_of_events.index("stats_done_CourseA")
    assert idx_lichess_b <= idx_stats_a_done


def test_maintenance_ui_transpositions_checkbox(qapp):
    from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
    with patch.object(UnifiedSettingsDialog, 'ensure_backend_for_active_repo'), \
         patch.object(UnifiedSettingsDialog, 'refresh_creator_info'), \
         patch.object(UnifiedSettingsDialog, 'refresh_maintenance_table'):
        dlg = UnifiedSettingsDialog()
        try:
            assert hasattr(dlg, "chk_m_transpos")
            # Default state MUST be unchecked
            assert dlg.chk_m_transpos.isChecked() is False

            # Transposition depth spinbox must exist, default to 25, and be disabled when task is unchecked
            assert hasattr(dlg, "spin_m_transpos_depth")
            assert dlg.spin_m_transpos_depth.value() == 25
            assert dlg.spin_m_transpos_depth.isEnabled() is False

            # Label must NOT contain ♟️ emoji
            text = dlg.chk_m_transpos.text()
            assert "♟" not in text
            assert "Überleitungen scannen (2-Züge)" in text or "Scan Transpositions (2-Move)" in text

            # If user checks it, spinbox must become enabled
            dlg.chk_m_transpos.setChecked(True)
            assert dlg.chk_m_transpos.isChecked() is True
            assert dlg.spin_m_transpos_depth.isEnabled() is True

            # Simulate navigation to maintenance tab
            class FakeItem:
                def data(self, col, role):
                    from PyQt6.QtCore import Qt
                    if role == Qt.ItemDataRole.UserRole:
                        return dlg.pages.indexOf(dlg.page_cr_maintenance)
                    return None
            dlg.on_tree_item_clicked(FakeItem(), 0)

            # Must be unchecked again and spinbox disabled
            assert dlg.chk_m_transpos.isChecked() is False
            assert dlg.spin_m_transpos_depth.isEnabled() is False
        finally:
            dlg.close()

