import pytest
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtTest import QSignalSpy
from unittest.mock import patch, MagicMock
from opening_fenix.core.threads import (
    AnalysisThread,
    LichessImportThread,
    MaintenanceThread,
    BackgroundEnrichmentThread,
    PGNImportThread,
    IslandDetectionThread
)

@pytest.mark.qt
def test_analysis_thread_success(qtbot):
    with patch("opening_fenix.core.threads.run_db_analysis") as mock_run:
        mock_run.return_value = (True, "Analysis OK")
        
        thread = AnalysisThread("TestRepo", 10, 1, "path/to/engine")
        spy_finished = QSignalSpy(thread.finished_signal)
        spy_progress = QSignalSpy(thread.progress_signal)
        
        # Start thread
        thread.start()
        qtbot.waitUntil(lambda: len(spy_finished) == 1, timeout=5000)
        
        assert len(spy_finished) == 1
        assert spy_finished[0][0] is True
        assert spy_finished[0][1] == "Analysis OK"

@pytest.mark.qt
def test_lichess_import_thread_success(qtbot):
    with patch("opening_fenix.core.threads.run_lichess_import_and_calculate_scores") as mock_run:
        mock_run.return_value = (True, "Lichess OK")
        
        thread = LichessImportThread("TestRepo", "high")
        spy_finished = QSignalSpy(thread.finished_signal)
        
        thread.start()
        qtbot.waitUntil(lambda: len(spy_finished) == 1, timeout=5000)
        
        assert len(spy_finished) == 1
        assert spy_finished[0][0] is True
        assert spy_finished[0][1] == "Lichess OK"

@pytest.mark.qt
def test_maintenance_thread_success(qtbot):
    with patch("opening_fenix.core.threads.run_group_maintenance") as mock_run:
        mock_run.return_value = (True, "Maintenance OK")
        
        repo_configs = [{'name': 'Repo1', 'elo': 'high'}]
        tasks = {'engine': True}
        
        thread = MaintenanceThread(repo_configs, tasks, {'path': 'f', 'depth': 1, 'threads': 1})
        spy_finished = QSignalSpy(thread.finished_signal)
        spy_overall = QSignalSpy(thread.overall_progress_signal)
        spy_status = QSignalSpy(thread.repo_status_signal)
        
        thread.start()
        qtbot.waitUntil(lambda: len(spy_finished) == 1, timeout=5000)
        
        assert len(spy_finished) == 1
        assert spy_finished[0][0] is True
        assert spy_finished[0][1] == "Maintenance OK"

@pytest.mark.qt
def test_thread_cancellation(qtbot):
    thread = AnalysisThread("TestRepo", 10, 1, "path/to/engine")
    assert thread._is_canceled is False
    thread.cancel()
    assert thread._is_canceled is True

@pytest.mark.qt
def test_background_enrichment_thread(qtbot):
    with patch("opening_fenix.core.threads.enrich_position") as mock_run:
        mock_run.return_value = (True, "Enrich OK")
        
        thread = BackgroundEnrichmentThread("repo", "fen", "high", "engine_path")
        spy = QSignalSpy(thread.finished_signal)
        
        thread.start()
        qtbot.waitUntil(lambda: len(spy) == 1, timeout=5000)
        
        assert spy[0][0] is True

@pytest.mark.qt
def test_pgn_import_thread(qtbot):
    with patch("opening_fenix.core.threads.import_pgn_to_db") as mock_run:
        mock_run.return_value = (True, "PGN OK")
        
        # pgn_path, repo_name, side, level_name, level_order
        thread = PGNImportThread("pgn", "repo", "white", "Basic", 1)
        spy = QSignalSpy(thread.finished_signal)
        
        thread.start()
        qtbot.waitUntil(lambda: len(spy) == 1, timeout=5000)
        assert spy[0][0] is True
