from PyQt6.QtCore import QThread, pyqtSignal
from opening_fenix.core.data_tools import run_db_analysis, run_lichess_import_and_calculate_scores, detect_islands, enrich_position
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.services.hole_finder_service import run_hole_finder_task


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

class RepertoireStatsWorker(QThread):
    stats_ready = pyqtSignal(int, str, float, str) # row_index, analysis_status, coverage_pct, elo
    finished = pyqtSignal()

    def __init__(self, repo_data_list):
        """
        repo_data_list: List of dicts {'row': int, 'name': str}
        """
        super().__init__()
        self.repo_data_list = repo_data_list

    def run(self):
        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        service = RepertoireService()
        for item in self.repo_data_list:
            try:
                service.set_active_repertoire(item['name'])
                info = service.get_repertoire_info()
                self.stats_ready.emit(item['row'], info.get('depth', 'Error'), info.get('coverage_pct', 0.0), info.get('elo', 'high'))
                service.close()
            except Exception as e:
                print(f"DEBUG: StatsWorker Error for {item['name']}: {e}")
                self.stats_ready.emit(item['row'], "Error", 0.0, "high")
        self.finished.emit()

class HoleFinderThread(QThread):
    finished_signal = pyqtSignal(list, str)
    
    def __init__(self, repo_name, is_test, threshold, elo_range, mode="holes", level=None):
        super().__init__()
        self.repo_name = repo_name
        self.is_test = is_test
        self.threshold = threshold
        self.elo_range = elo_range
        self.mode = mode
        self.level = level

    def run(self):
        try:
            results = run_hole_finder_task(
                self.repo_name, 
                self.is_test, 
                self.threshold, 
                self.elo_range, 
                self.mode, 
                self.level
            )
            self.finished_signal.emit(results, self.mode)
        except Exception as e:
            print(f"DEBUG: HoleFinderThread Error: {e}")
            self.finished_signal.emit(results, self.mode)
        except Exception as e:
            print(f"DEBUG: HoleFinderThread Error: {e}")
            self.finished_signal.emit([], self.mode)

class TranspositionSearchThread(QThread):
    finished_signal = pyqtSignal(list)
    info_signal = pyqtSignal(list) # Emits partial PVs during calculation
    
    def __init__(self, fen, engine_path, threads=4, depth=20, multipv=5):
        super().__init__()
        self.fen = fen
        self.engine_path = engine_path
        self.threads = threads
        self.depth = depth
        self.multipv = multipv
        self._is_running = True
        self._engine = None

    def stop(self):
        """Signals the engine to stop analysis immediately."""
        self._is_running = False

    def run(self):
        import chess.engine
        import subprocess
        import sys
        
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
                
            self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path, creationflags=creationflags)
            self._engine.configure({"Threads": self.threads})
            
            board = chess.Board(self.fen)
            limit = chess.engine.Limit(depth=self.depth)
            
            # Start streaming analysis
            current_best_pvs = {} # multipv_id -> {score, pv}
            
            with self._engine.analysis(board, limit, multipv=self.multipv) as analysis:
                for info in analysis:
                    if not self._is_running:
                        break
                    
                    # We only care about PV updates
                    if "pv" in info:
                        score = 0
                        if "score" in info:
                            if info["score"].is_mate():
                                mate = info["score"].white().mate()
                                score = 10000 if mate > 0 else -10000
                            else:
                                score = info["score"].white().score() or 0
                                
                        pv_idx = info.get("multipv", 1)
                        pv_uci = [m.uci() for m in info["pv"]]
                        
                        # Store current best for this index
                        current_best_pvs[pv_idx] = {
                            "score": score,
                            "moves": pv_uci
                        }
                        
                        # Emit for early exit check
                        self.info_signal.emit([{
                            "score": score,
                            "moves": pv_uci
                        }])

            # Conversion to sorted list
            results = []
            for idx in sorted(current_best_pvs.keys()):
                results.append(current_best_pvs[idx])
            
            self._engine.quit()
            self.finished_signal.emit(results)
        except Exception as e:
            if self._engine:
                try: self._engine.quit()
                except: pass
            print(f"DEBUG: TranspositionSearchThread Error: {e}")
            self.finished_signal.emit([])

