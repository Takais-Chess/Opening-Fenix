import os
import json
import threading
import queue
import time
from typing import Any, Dict, List, Tuple
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta
from opening_fenix.core.services.analysis_service import run_db_analysis
from opening_fenix.core.services.lichess_service import run_lichess_import, run_lichess_orphan_cleanup
from opening_fenix.core.services.priority_service import calculate_priority_scores
from opening_fenix.core.services.hole_finder_service import find_repertoire_transpositions, save_cached_transpositions
from opening_fenix.core.logger import logger

_ORIG_GET_META = get_meta
_ORIG_DATABASE_MANAGER = DatabaseManager

def get_repertoire_elo(repo_name):
    """Retrieves the target Elo category for a specific repertoire from its metadata (fast sqlite3 path)."""
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return "high"  # Default

    try:
        if get_meta is _ORIG_GET_META and DatabaseManager is _ORIG_DATABASE_MANAGER:
            from opening_fenix.core.services.repertoire_core_service import get_repertoire_meta_fast
            meta = get_repertoire_meta_fast(repo_name, db_path=db_path)
            val = meta.get("lichess_elo") or meta.get("elo") or "high"
        else:
            db = DatabaseManager(db_path)
            session = db.get_session()
            try:
                val = get_meta(session, "lichess_elo", "high")
            finally:
                session.close()
                db.close()
    except Exception as e:
        logger.debug(f"Could not fetch Elo for {repo_name}: {e}")
        return "high"

    try:
        val_str = str(val).strip()
        from opening_fenix.core.utils import ELO_INTERNAL_MAP
        if val_str in ELO_INTERNAL_MAP:
            return ELO_INTERNAL_MAP[val_str]

        val_lower = val_str.lower()
        if "low" in val_lower or "hobby" in val_lower:
            return "low"
        if "mid" in val_lower or "verein" in val_lower:
            return "mid"
        if "master" in val_lower or "meister" in val_lower:
            return "masters"
        return "high"
    except Exception as e:
        logger.debug(f"Could not fetch Elo for {repo_name}: {e}")
        return "high"

def list_all_repertoires(include_elo=False):
    """Returns a list of dictionaries containing 'name' and 'elo'."""
    repo_base = os.path.join(get_user_dir(), "repertoires")
    if not os.path.exists(repo_base):
        return []

    unique_names = set()
    for root, dirs, files in os.walk(repo_base):
        for folder in dirs:
            if os.path.exists(os.path.join(root, folder, f"{folder}.db")):
                unique_names.add(folder)

    return [{'name': n, 'elo': get_repertoire_elo(n) if include_elo else "Laden..."} for n in sorted(unique_names)]

class MaintenanceOrchestrator:
    def __init__(self, repo_configs, tasks, engine_settings, 
                 overall_progress_callback, repo_status_callback, check_cancel):
        self.repo_configs = repo_configs
        if isinstance(tasks, (list, tuple, set)):
            self.tasks = {t: True for t in tasks}
        elif isinstance(tasks, dict):
            self.tasks = dict(tasks)
        else:
            self.tasks = {}
        self.engine_settings = engine_settings or {}
        self.overall_cb = overall_progress_callback
        self.repo_status_cb = repo_status_callback # (repo_name, task_type, progress, status)
        self.check_cancel = check_cancel
        
        self.active_tasks = [t for t in ['cleanup', 'lichess', 'engine', 'transpositions', 'stats'] if self.tasks.get(t)]
        self.tasks_done = {cfg['name']: set() for cfg in repo_configs}
        self.lock = threading.Lock()
        self.completed_repos = set()
        self.total_repos = len(repo_configs)
        self._is_aborted = False
        self.stats_queue = queue.Queue()

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
            elo = cfg.get('elo', 'high')

            # 1. Engine Analysis
            if self.tasks.get('engine') and not self._is_aborted:
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
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
                time.sleep(0.01)

            # 2. 2-Move Transposition Scan
            if self.tasks.get('transpositions') and not self._is_aborted:
                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "transpositions", 0, "Überleitungen...")

                def on_transpos_progress(curr, total, msg=None):
                    if not self.repo_status_cb: return
                    pct = int((curr / max(1, total)) * 100) if total > 0 else 0
                    status_text = f"{curr}/{total}" if total > 0 else (msg or "Überleitungen...")
                    self.repo_status_cb(name, "transpositions", pct, status_text)

                transpos_success = False
                try:
                    db_path = get_repertoire_db_path(name)
                    if os.path.exists(db_path):
                        db_m = DatabaseManager(db_path)
                        sess = db_m.get_session()
                        try:
                            eng_path = self.engine_settings.get('path', '')
                            eng_depth = self.engine_settings.get('transpos_depth') or self.engine_settings.get('depth', 25)
                            eng_threads = self.engine_settings.get('threads', 1)

                            candidates = find_repertoire_transpositions(
                                sess,
                                elo_range=elo,
                                engine_path=eng_path,
                                threads_count=eng_threads,
                                depth=eng_depth,
                                progress_callback=on_transpos_progress,
                                cancel_check=self.check_cancel
                            )
                            two_move_candidates = [
                                h for h in (candidates or [])
                                if isinstance(h, dict) and h.get("depth", 1) == 2
                            ]
                            save_cached_transpositions(sess, two_move_candidates, merge=True)
                            transpos_success = True
                        except Exception as e:
                            logger.error(f"Transpositions scan failed for {name}: {e}")
                        finally:
                            sess.close()
                            db_m.close()
                except Exception as e:
                    logger.error(f"Transpositions DB error for {name}: {e}")

                if self._is_aborted or (self.check_cancel and self.check_cancel()):
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "transpositions", 100, "Fertig" if transpos_success else "Fehler")
                self._mark_task_finished(name, "transpositions")
                time.sleep(0.01)

            time.sleep(0.01)

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
                primary_elo, elo_list = self._resolve_repo_elos(cfg)
                total_elos = len(elo_list)
                overall_success = True

                for idx, curr_elo in enumerate(elo_list):
                    if self.check_cancel and self.check_cancel():
                        self._is_aborted = True
                        break
                    slice_start = idx * 100.0 / total_elos
                    slice_span = 100.0 / total_elos

                    def _make_progress_cb(s_start=slice_start, s_span=slice_span, i=idx, tot_e=total_elos):
                        def _cb(pct, *args):
                            if not self.repo_status_cb:
                                return
                            if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                                status_text = f"{args[0]}/{args[1]}"
                            elif len(args) == 1 and isinstance(args[0], str):
                                status_text = args[0]
                            else:
                                status_text = f"{pct}%"
                            if tot_e > 1:
                                status_text = f"[{i + 1}/{tot_e}] {status_text}"
                            scaled_pct = int(s_start + pct * (s_span / 100.0))
                            self.repo_status_cb(name, "lichess", scaled_pct, status_text)
                        return _cb

                    kwargs = dict(
                        progress_callback=_make_progress_cb(),
                        check_cancel=self.check_cancel,
                        reuse_other_courses=reuse_courses,
                        max_data_age_days=max_age,
                    )
                    if curr_elo != primary_elo:
                        kwargs["preserve_primary_elo"] = True
                    ok, _msg = run_lichess_import(name, curr_elo, **kwargs)
                    if not ok:
                        overall_success = False
                        if self.check_cancel and self.check_cancel():
                            self._is_aborted = True
                            break

                if self.check_cancel and self.check_cancel():
                    self._is_aborted = True
                    break
                if self.repo_status_cb:
                    self.repo_status_cb(name, "lichess", 100, "Fertig" if overall_success else "Fehlgeschlagen")
                self._mark_task_finished(name, "lichess")
                time.sleep(0.01)  # Yield GIL between stages

            # Pipelining: As soon as Lichess/cleanup finishes for this course, queue it for Stats!
            # The next course can immediately start downloading Lichess in parallel with this course calculating stats.
            if self.tasks.get('stats') and not self._is_aborted:
                self.stats_queue.put(cfg)

            time.sleep(0.01)  # Yield GIL between repertoires

        # Signal completion to _stats_worker
        if self.tasks.get('stats'):
            self.stats_queue.put(None)

    def _resolve_repo_elos(self, cfg: Dict[str, Any]) -> Tuple[str, List[str]]:
        """Resolves (primary_elo, ordered_elo_list) for a batch course config."""
        from opening_fenix.core.utils import parse_elo_list
        primary = cfg.get('elo', 'high')
        explicit = parse_elo_list(cfg.get('elos') or [])
        if explicit:
            ordered = [primary] + [e for e in explicit if e != primary] if primary in explicit else explicit
            return ordered[0], ordered
        try:
            from opening_fenix.core.services.repertoire_core_service import get_repertoire_lichess_elos_fast
            def_elo, avail = get_repertoire_lichess_elos_fast(cfg['name'])
            if avail:
                p = def_elo or primary
                ordered = [p] + [e for e in avail if e != p] if p in avail else avail
                return ordered[0], ordered
        except Exception:
            pass
        return primary, [primary]

    def _stats_worker(self):
        while not self._is_aborted:
            if self.check_cancel and self.check_cancel():
                self._is_aborted = True
                break
            try:
                cfg = self.stats_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if cfg is None:
                self.stats_queue.task_done()
                break

            if self._is_aborted or (self.check_cancel and self.check_cancel()):
                self._is_aborted = True
                self.stats_queue.task_done()
                break

            name = cfg['name']
            primary_elo, elo_list = self._resolve_repo_elos(cfg)

            if self.repo_status_cb:
                self.repo_status_cb(name, "stats", 0, "Statistiken...")
            try:
                # Compute secondary Elos first, primary last so Move.priority_score stays synced to primary
                ordered_stats_elos = [e for e in elo_list if e != primary_elo] + [primary_elo]
                for curr_elo in ordered_stats_elos:
                    if curr_elo == primary_elo:
                        calculate_priority_scores(name, curr_elo)
                    else:
                        calculate_priority_scores(name, curr_elo, update_move_column=False)
                if self.repo_status_cb:
                    self.repo_status_cb(name, "stats", 100, "Fertig")
            except Exception as e:
                logger.error(f"Stats failed for {name}: {e}")
                if self.repo_status_cb:
                    self.repo_status_cb(name, "stats", 100, "Fehler")
            self._mark_task_finished(name, "stats")
            self.stats_queue.task_done()
            time.sleep(0.01)

    def run(self):
        if self.check_cancel and self.check_cancel():
            return False, "Abgebrochen durch Benutzer"

        if not self.repo_configs or not self.active_tasks:
            return True, "Wartung erfolgreich abgeschlossen."

        threads = []
        if self.tasks.get('engine') or self.tasks.get('transpositions'):
            t_eng = threading.Thread(target=self._engine_worker, daemon=True)
            threads.append(t_eng)
            t_eng.start()

        if any(self.tasks.get(t) for t in ['cleanup', 'lichess']):
            t_data = threading.Thread(target=self._data_worker, daemon=True)
            threads.append(t_data)
            t_data.start()
        elif self.tasks.get('stats'):
            # If neither cleanup nor lichess is running, enqueue all repos directly for stats
            for cfg in self.repo_configs:
                self.stats_queue.put(cfg)
            self.stats_queue.put(None)

        if self.tasks.get('stats'):
            t_stats = threading.Thread(target=self._stats_worker, daemon=True)
            threads.append(t_stats)
            t_stats.start()

        while any(t.is_alive() for t in threads):
            if self.check_cancel and self.check_cancel():
                self._is_aborted = True
                self.stats_queue.put(None)
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
