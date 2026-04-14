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
