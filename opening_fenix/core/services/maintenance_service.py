import os
import json
import threading
import queue
import time
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta
from opening_fenix.core.services.analysis_service import run_db_analysis
from opening_fenix.core.services.lichess_service import run_lichess_import, run_lichess_orphan_cleanup
from opening_fenix.core.services.priority_service import calculate_priority_scores
from opening_fenix.core.logger import logger

def get_repertoire_elo(repo_name):
    """Retrieves the target Elo category for a specific repertoire from its metadata."""
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return "high" # Default
    
    try:
        db = DatabaseManager(db_path)
        session = db.get_session()
        val = get_meta(session, "elo", "high")
        session.close()
        db.close()
        
        val = val.lower() if val else "high"
        if "low" in val: return "low"
        if "mid" in val: return "mid"
        if "masters" in val: return "masters"
        return "high"
    except Exception as e:
        logger.debug(f"Could not fetch Elo for {repo_name}: {e}")
        return "high"

def list_all_repertoires(include_elo=False):
    """Returns a list of dictionaries containing 'name' and 'elo'."""
    repo_base = os.path.join(get_user_dir(), "repertoires")
    if not os.path.exists(repo_base):
        return []
    
    names = []
    # Standard 
    for item in os.listdir(repo_base):
        if item == "test": continue
        repo_dir = os.path.join(repo_base, item)
        if os.path.isdir(repo_dir):
            if os.path.exists(os.path.join(repo_dir, f"{item}.db")):
                names.append(item)
    # Test
    test_base = os.path.join(repo_base, "test")
    if os.path.exists(test_base) and os.path.isdir(test_base):
        for item in os.listdir(test_base):
            repo_dir = os.path.join(test_base, item)
            if os.path.isdir(repo_dir):
                if os.path.exists(os.path.join(repo_dir, f"{item}.db")):
                    names.append(item)
                    
    unique_names = sorted(list(set(names)))
    from opening_fenix.core.utils import filter_repertoires_by_build_type
    unique_names = filter_repertoires_by_build_type(unique_names)
    return [{'name': n, 'elo': get_repertoire_elo(n) if include_elo else "Laden..."} for n in unique_names]

class MaintenanceOrchestrator:
    def __init__(self, repo_configs, tasks, engine_settings, 
                 overall_progress_callback, repo_status_callback, check_cancel):
        self.repo_configs = repo_configs
        self.tasks = tasks
        self.engine_settings = engine_settings or {}
        self.overall_cb = overall_progress_callback
        self.repo_status_cb = repo_status_callback # (repo_name, task_type, progress, status)
        self.check_cancel = check_cancel
        
        self.active_tasks = [t for t in ['cleanup', 'lichess', 'engine', 'stats'] if self.tasks.get(t)]
        self.tasks_done = {cfg['name']: set() for cfg in repo_configs}
        self.lock = threading.Lock()
        self.completed_repos = set()
        self.total_repos = len(repo_configs)
        self._is_aborted = False

    def _check_repo_done(self, name):
        with self.lock:
            if not self._is_aborted and name not in self.completed_repos:
                if all(t in self.tasks_done[name] for t in self.active_tasks):
                    self.completed_repos.add(name)
                    if self.overall_cb:
                        self.overall_cb(len(self.completed_repos), self.total_repos, name)

    def _mark_task_finished(self, name, task_type):
        with self.lock:
            self.tasks_done[name].add(task_type)
        self._check_repo_done(name)

    def _engine_worker(self):
        for cfg in self.repo_configs:
            if self._is_aborted or (self.check_cancel and self.check_cancel()):
                self._is_aborted = True
                break
            name = cfg['name']
            if self.repo_status_cb:
                self.repo_status_cb(name, "engine", 0, "Analysiere...")

            def on_engine_progress(pct, *args):
                if not self.repo_status_cb: return
                if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                    cur, total = args[0], args[1]
                    status_text = f"{cur}/{total}"
                elif len(args) == 1 and isinstance(args[0], str):
                    status_text = args[0]
                else:
                    status_text = "Analysiere..."
                self.repo_status_cb(name, "engine", pct, status_text)

            success, msg = run_db_analysis(
                name, self.engine_settings.get('path', ''), self.engine_settings.get('depth', 18), self.engine_settings.get('threads', 1),
                progress_callback=on_engine_progress,
                check_cancel=self.check_cancel
            )
            if self._is_aborted or (self.check_cancel and self.check_cancel()):
                self._is_aborted = True
                break
            if self.repo_status_cb:
                self.repo_status_cb(name, "engine", 100, "Fertig" if success else "Fehlgeschlagen")
            self._mark_task_finished(name, "engine")

    def _data_worker(self):
        for cfg in self.repo_configs:
            if self._is_aborted or (self.check_cancel and self.check_cancel()):
                self._is_aborted = True
                break
            name = cfg['name']
            elo = cfg.get('elo', 'high')

            # 1. Cleanup
            if self.tasks.get('cleanup') and not self._is_aborted:
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "cleanup", 0, "Bereinige...")
                success, msg = run_lichess_orphan_cleanup(
                    name,
                    progress_callback=lambda p: self.repo_status_cb(name, "cleanup", p, "Bereinige...") if self.repo_status_cb else None
                )
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "cleanup", 100, "Fertig" if success else "Fehler")
                self._mark_task_finished(name, "cleanup")
                time.sleep(0.01)  # Yield GIL between stages

            # 2. Lichess Import
            if self.tasks.get('lichess') and not self._is_aborted:
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "lichess", 0, "Lichess...")

                def on_lichess_progress(pct, *args):
                    if not self.repo_status_cb: return
                    if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                        cur, total = args[0], args[1]
                        status_text = f"{cur}/{total}"
                    elif len(args) == 1 and isinstance(args[0], str):
                        status_text = args[0]
                    else:
                        status_text = f"{pct}%"
                    self.repo_status_cb(name, "lichess", pct, status_text)

                reuse_courses = bool(self.tasks.get('lichess_reuse_courses', False))
                max_age = self.tasks.get('lichess_max_age_days', 180)

                success, msg = run_lichess_import(
                    name, elo,
                    progress_callback=on_lichess_progress,
                    check_cancel=self.check_cancel,
                    reuse_other_courses=reuse_courses,
                    max_data_age_days=max_age
                )
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "lichess", 100, "Fertig" if success else "Fehlgeschlagen")
                self._mark_task_finished(name, "lichess")
                time.sleep(0.01)  # Yield GIL between stages

            # 3. Stats & Prio (Runs strictly AFTER Lichess import for this course!)
            if self.tasks.get('stats') and not self._is_aborted:
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "stats", 0, "Statistiken...")
                try:
                    calculate_priority_scores(name, elo)
                    if self.repo_status_cb:
                        self.repo_status_cb(name, "stats", 100, "Fertig")
                except Exception as e:
                    logger.error(f"Stats failed for {name}: {e}")
                    if self.repo_status_cb:
                        self.repo_status_cb(name, "stats", 100, "Fehler")
                self._mark_task_finished(name, "stats")
                time.sleep(0.01)  # Yield GIL between stages

            time.sleep(0.01)  # Yield GIL between repertoires

    def run(self):
        if self.check_cancel and self.check_cancel():
            return False, "Abgebrochen durch Benutzer"

        if not self.repo_configs or not self.active_tasks:
            return True, "Wartung erfolgreich abgeschlossen."

        threads = []
        if self.tasks.get('engine'):
            t_eng = threading.Thread(target=self._engine_worker, daemon=True)
            threads.append(t_eng)
            t_eng.start()

        if any(self.tasks.get(t) for t in ['cleanup', 'lichess', 'stats']):
            t_data = threading.Thread(target=self._data_worker, daemon=True)
            threads.append(t_data)
            t_data.start()

        while any(t.is_alive() for t in threads):
            if self.check_cancel and self.check_cancel():
                self._is_aborted = True
                break
            time.sleep(0.1)

        for t in threads:
            t.join(timeout=3.0)

        if self._is_aborted or (self.check_cancel and self.check_cancel()):
            return False, "Abgebrochen durch Benutzer"
        return True, "Wartung erfolgreich abgeschlossen."

def run_group_maintenance(repo_configs, tasks, engine_settings=None, 
                          overall_progress_callback=None, repo_status_callback=None, check_cancel=None):
    """Wrapper to maintain compatibility with existing signals."""
    orchestrator = MaintenanceOrchestrator(
        repo_configs, tasks, engine_settings,
        overall_progress_callback, repo_status_callback, check_cancel
    )
    return orchestrator.run()
