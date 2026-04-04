from PyQt6.QtCore import QThread, pyqtSignal
from opening_fenix.core.data_tools import run_db_analysis, run_lichess_import_and_calculate_scores, detect_islands, enrich_position
from opening_fenix.core.services.import_service import import_pgn_to_db

class AnalysisThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name, depth, threads, engine_path):
        super().__init__()
        self.repo_name = repo_name
        self.depth = depth
        self.threads = threads
        self.engine_path = engine_path
        self._is_canceled = False

    def run(self):
        success, msg = run_db_analysis(
            self.repo_name, 
            self.engine_path, 
            self.depth, 
            self.threads, 
            progress_callback=self.progress_signal.emit,
            check_cancel=lambda: self._is_canceled
        )
        self.finished_signal.emit(success, msg)

    def cancel(self):
        self._is_canceled = True

class LichessImportThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name, elo_category):
        super().__init__()
        self.repo_name = repo_name
        self.elo_category = elo_category
        self._is_canceled = False

    def run(self):
        success, msg = run_lichess_import_and_calculate_scores(
            self.repo_name, 
            self.elo_category, 
            progress_callback=self.progress_signal.emit,
            check_cancel=lambda: self._is_canceled
        )
        self.finished_signal.emit(success, msg)

    def cancel(self):
        self._is_canceled = True

class IslandDetectionThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name):
        super().__init__()
        self.repo_name = repo_name

    def run(self):
        success, msg = detect_islands(self.repo_name)
        self.finished_signal.emit(success, msg)


class BackgroundEnrichmentThread(QThread):
    """
    Background thread to enrich a position with Lichess data, engine analysis,
    and local priority scores. Silently works in the background.
    """
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name, fen, elo_category, engine_path, depth=10):
        super().__init__()
        self.repo_name = repo_name
        self.fen = fen
        self.elo_category = elo_category
        self.engine_path = engine_path
        self.depth = depth

    def run(self):
        success, msg = enrich_position(
            self.repo_name,
            self.fen,
            self.elo_category,
            self.engine_path,
            self.depth
        )
        self.finished_signal.emit(success, msg)

class PGNImportThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, pgn_path, repo_name, side, level_name, level_order):
        super().__init__()
        self.pgn_path = pgn_path
        self.repo_name = repo_name
        self.side = side
        self.level_name = level_name
        self.level_order = level_order

    def run(self):
        success, msg = import_pgn_to_db(
            self.pgn_path,
            self.repo_name,
            self.side,
            self.level_name,
            self.level_order,
            progress_callback=self.progress_signal.emit
        )
        self.finished_signal.emit(success, msg)

from opening_fenix.core.services.maintenance_service import run_group_maintenance

class MaintenanceThread(QThread):
    # Overall summary: (current_repo_index, total_repos, last_completed_name)
    overall_progress_signal = pyqtSignal(int, int, str)
    # Granular status: (repo_name, task_type, percentage, status_text)
    repo_status_signal = pyqtSignal(str, str, int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_configs, tasks, engine_settings=None):
        super().__init__()
        self.repo_configs = repo_configs
        self.tasks = tasks
        self.engine_settings = engine_settings
        self._is_canceled = False

    def run(self):
        success, msg = run_group_maintenance(
            self.repo_configs,
            self.tasks,
            self.engine_settings,
            overall_progress_callback=self.overall_progress_signal.emit,
            repo_status_callback=self.repo_status_signal.emit,
            check_cancel=lambda: self._is_canceled
        )
        self.finished_signal.emit(success, msg)

    def cancel(self):
        self._is_canceled = True
