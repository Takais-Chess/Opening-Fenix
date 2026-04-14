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
        
        val = val.lower()
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
    return [{'name': n, 'elo': get_repertoire_elo(n) if include_elo else "Laden..."} for n in unique_names]

class MaintenanceOrchestrator:
    def __init__(self, repo_configs, tasks, engine_settings, 
                 overall_progress_callback, repo_status_callback, check_cancel):
        self.repo_configs = repo_configs
        self.tasks = tasks
        self.engine_settings = engine_settings
        self.overall_cb = overall_progress_callback
        self.repo_status_cb = repo_status_callback # (repo_name, task_type, progress, status)
        self.check_cancel = check_cancel
        
        self.engine_queue = queue.Queue()
        self.lichess_queue = queue.Queue()
        self.cleanup_queue = queue.Queue()
        self.repo_configs_dict = {cfg['name']: cfg for cfg in repo_configs}
        self.stats_pending = {cfg['name']: {'engine': False, 'lichess': False, 'cleanup': False} for cfg in repo_configs}
        self.stats_lock = threading.Lock()
        
        self.completed_repos = set()
        self.total_repos = len(repo_configs)
        self._is_aborted = False

    def run(self):
        # 1. Fill Queues
        for cfg in self.repo_configs:
            if self.tasks.get('engine'):
                self.engine_queue.put(cfg)
            else:
                with self.stats_lock: self.stats_pending[cfg['name']]['engine'] = True
            
            if self.tasks.get('lichess'):
                self.lichess_queue.put(cfg)
            else:
                with self.stats_lock: self.stats_pending[cfg['name']]['lichess'] = True

            if self.tasks.get('cleanup'):
                self.cleanup_queue.put(cfg)
            else:
                with self.stats_lock: self.stats_pending[cfg['name']]['cleanup'] = True

        # 2. Start Workers
        t1 = threading.Thread(target=self._engine_worker, daemon=True)
        t2 = threading.Thread(target=self._lichess_worker, daemon=True)
        t3 = threading.Thread(target=self._cleanup_worker, daemon=True)
        t1.start(); t2.start(); t3.start()

        # 3. Wait for all completion or cancel
        while t1.is_alive() or t2.is_alive() or t3.is_alive():
            if self.check_cancel and self.check_cancel():
                self._is_aborted = True
                break
            time.sleep(0.5)

        if self._is_aborted:
            return False, "Abgebrochen durch Benutzer"
        return True, "Wartung erfolgreich abgeschlossen."

    def _engine_worker(self):
        while not self.engine_queue.empty() and not self._is_aborted:
            cfg = self.engine_queue.get()
            name = cfg['name']
            
            self.repo_status_cb(name, "engine", 0, "Analysiere...")
            success, msg = run_db_analysis(
                name, self.engine_settings['path'], self.engine_settings['depth'], self.engine_settings['threads'],
                progress_callback=lambda p: self.repo_status_cb(name, "engine", p, "Analysiere..."),
                check_cancel=self.check_cancel
            )
            
            self.repo_status_cb(name, "engine", 100, "Fertig" if success else "Fehlgeschlagen")
            self._mark_task_done(name, 'engine')
            self.engine_queue.task_done()

    def _lichess_worker(self):
        while not self.lichess_queue.empty() and not self._is_aborted:
            cfg = self.lichess_queue.get()
            name = cfg['name']
            elo = cfg['elo']
            
            self.repo_status_cb(name, "lichess", 0, "Lichess...")
            success, msg = run_lichess_import(
                name, elo,
                progress_callback=lambda p: self.repo_status_cb(name, "lichess", p, "Lichess..."),
                check_cancel=self.check_cancel
            )
            
            self.repo_status_cb(name, "lichess", 100, "Fertig" if success else "Fehlgeschlagen")
            self._mark_task_done(name, 'lichess')
            self.lichess_queue.task_done()

    def _cleanup_worker(self):
        while not self.cleanup_queue.empty() and not self._is_aborted:
            cfg = self.cleanup_queue.get()
            name = cfg['name']
            
            self.repo_status_cb(name, "cleanup", 0, "Cleanup...")
            success, msg = run_lichess_orphan_cleanup(
                name,
                progress_callback=lambda p: self.repo_status_cb(name, "cleanup", p, "Cleanup...")
            )
            
            self.repo_status_cb(name, "cleanup", 100, "Fertig" if success else "Fehler")
            self._mark_task_done(name, 'cleanup')
            self.cleanup_queue.task_done()

    def _mark_task_done(self, name, task_type):
        with self.stats_lock:
            self.stats_pending[name][task_type] = True
            ready_for_stats = self.stats_pending[name]['engine'] and self.stats_pending[name]['lichess'] and self.stats_pending[name]['cleanup']
            
        if ready_for_stats and self.tasks.get('stats') and not self._is_aborted:
            self.repo_status_cb(name, "stats", 0, "Statistiken...")
            try:
                elo_cat = self.repo_configs_dict.get(name, {}).get('elo', 'high')
                calculate_priority_scores(name, elo_cat)
                self.repo_status_cb(name, "stats", 100, "Abgeschlossen")
            except Exception as e:
                logger.error(f"Stats failed for {name}: {e}")
                self.repo_status_cb(name, "stats", 100, "Fehler")
        
        # Update overall 
        if ready_for_stats:
            self.completed_repos.add(name)
            if self.overall_cb:
                self.overall_cb(len(self.completed_repos), self.total_repos, name)

def run_group_maintenance(repo_configs, tasks, engine_settings=None, 
                          overall_progress_callback=None, repo_status_callback=None, check_cancel=None):
    """Wrapper to maintain compatibility with existing signals."""
    orchestrator = MaintenanceOrchestrator(
        repo_configs, tasks, engine_settings,
        overall_progress_callback, repo_status_callback, check_cancel
    )
    return orchestrator.run()
