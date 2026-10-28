import uuid
import time
import collections
import threading
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from opening_fenix.core.logger import logger
from opening_fenix.core.translation import tr_ui
from opening_fenix.core.services.analysis_service import run_db_analysis
from opening_fenix.core.services.lichess_service import run_lichess_import_and_calculate_scores
from opening_fenix.core.services.maintenance_service import run_group_maintenance


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class JobType(Enum):
    LICHESS = "lichess"
    ENGINE_SCAN = "engine_scan"
    COMBINED = "combined"
    BATCH_MAINTENANCE = "batch_maintenance"


class BackgroundJob:
    """Base class for all background tasks executed by BackgroundTaskManager."""

    def __init__(self, title: str, repo_name: str, job_type: JobType, details: Optional[Dict[str, Any]] = None):
        self.job_id: str = str(uuid.uuid4())
        self.title: str = title
        self.repo_name: str = repo_name
        self.job_type: JobType = job_type
        self.status: JobStatus = JobStatus.QUEUED
        self.progress: int = 0
        self.status_message: str = tr_ui("task_center.job_queued", "In Warteschlange...")
        self.details: Dict[str, Any] = details or {}
        self.created_at: float = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.error_message: Optional[str] = None
        self._is_canceled: bool = False

    def cancel(self):
        self._is_canceled = True

    def is_canceled(self) -> bool:
        return self._is_canceled

    def execute(self, progress_cb: Callable[[int], None], status_cb: Callable[[str], None]) -> Tuple[bool, str]:
        raise NotImplementedError


class LichessJob(BackgroundJob):
    def __init__(self, repo_name: str, elo_category: str, reuse_other_courses: bool = True, max_data_age_days: Optional[int] = 180):
        super().__init__(
            title=tr_ui("task_center.job_title_lichess", "Lichess-Import: {repo}", repo=repo_name),
            repo_name=repo_name,
            job_type=JobType.LICHESS,
            details={"elo_category": elo_category, "reuse_other_courses": reuse_other_courses, "max_data_age_days": max_data_age_days}
        )
        self.elo_category = elo_category
        self.reuse_other_courses = reuse_other_courses
        self.max_data_age_days = max_data_age_days
        self.lichess_pct: int = 0
        self.lichess_status: str = ""

    def execute(self, progress_cb: Callable[[int], None], status_cb: Callable[[str], None]) -> Tuple[bool, str]:
        tm = get_task_manager()
        def on_prog(pct, *args):
            p = max(0, min(100, int(pct)))
            self.lichess_pct = p
            progress_cb(p)
            if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                st = tr_ui("task_center.job_positions_fmt", "{cur}/{tot} Stellungen", cur=args[0], tot=args[1])
                self.lichess_status = st
                status_cb(st)
            elif len(args) == 1 and isinstance(args[0], str):
                self.lichess_status = args[0]
                status_cb(args[0])
            tm.sub_progress.emit(self, "lichess", self.lichess_pct, self.lichess_status)

        return run_lichess_import_and_calculate_scores(
            repo_name=self.repo_name,
            elo_category=self.elo_category,
            progress_callback=on_prog,
            check_cancel=self.is_canceled,
            reuse_other_courses=self.reuse_other_courses,
            max_data_age_days=self.max_data_age_days
        )


class EngineScanJob(BackgroundJob):
    def __init__(self, repo_name: str, depth: int, threads: int, engine_path: str, reuse_other_courses: bool = True):
        super().__init__(
            title=tr_ui("task_center.job_title_engine", "Engine-Scan (T{depth}): {repo}", depth=depth, repo=repo_name),
            repo_name=repo_name,
            job_type=JobType.ENGINE_SCAN,
            details={"depth": depth, "threads": threads, "engine_path": engine_path, "reuse_other_courses": reuse_other_courses}
        )
        self.depth = depth
        self.threads = threads
        self.engine_path = engine_path
        self.reuse_other_courses = reuse_other_courses
        self.engine_pct: int = 0
        self.engine_status: str = ""

    def execute(self, progress_cb: Callable[[int], None], status_cb: Callable[[str], None]) -> Tuple[bool, str]:
        tm = get_task_manager()
        def on_prog(pct, *args):
            p = max(0, min(100, int(pct)))
            self.engine_pct = p
            progress_cb(p)
            if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                st = tr_ui("task_center.job_positions_fmt", "{cur}/{tot} Stellungen", cur=args[0], tot=args[1])
                self.engine_status = st
                status_cb(st)
            elif len(args) == 1 and isinstance(args[0], str):
                self.engine_status = args[0]
                status_cb(args[0])
            tm.sub_progress.emit(self, "engine", self.engine_pct, self.engine_status)

        def on_st(st: str):
            self.engine_status = str(st)
            status_cb(self.engine_status)
            tm.sub_progress.emit(self, "engine", self.engine_pct, self.engine_status)

        return run_db_analysis(
            repo_name=self.repo_name,
            engine_path=self.engine_path,
            depth=self.depth,
            threads=self.threads,
            progress_callback=on_prog,
            check_cancel=self.is_canceled,
            reuse_other_courses=self.reuse_other_courses,
            status_callback=on_st
        )


class CombinedSyncJob(BackgroundJob):
    def __init__(self, repo_name: str, elo_category: str, depth: int, threads: int, engine_path: str,
                 reuse_other_courses: bool = True, max_data_age_days: Optional[int] = 180):
        super().__init__(
            title=tr_ui("task_center.job_title_combined", "Vollständiger Sync: {repo}", repo=repo_name),
            repo_name=repo_name,
            job_type=JobType.COMBINED,
            details={
                "elo_category": elo_category, "depth": depth, "threads": threads,
                "engine_path": engine_path, "reuse_other_courses": reuse_other_courses,
                "max_data_age_days": max_data_age_days
            }
        )
        self.elo_category = elo_category
        self.depth = depth
        self.threads = threads
        self.engine_path = engine_path
        self.reuse_other_courses = reuse_other_courses
        self.max_data_age_days = max_data_age_days
        self.lichess_pct: int = 0
        self.lichess_status: str = ""
        self.engine_pct: int = 0
        self.engine_status: str = ""

    def execute(self, progress_cb: Callable[[int], None], status_cb: Callable[[str], None]) -> Tuple[bool, str]:
        import threading
        tm = get_task_manager()

        lich_prog = [0]
        eng_prog = [0]
        lich_status = [tr_ui("task_center.job_started", "Gestartet...")]
        eng_status = [tr_ui("task_center.job_started", "Gestartet...")]
        results = {}
        lock = threading.Lock()

        def update_combined(stream_key: Optional[str] = None):
            with lock:
                self.lichess_pct = lich_prog[0]
                self.lichess_status = lich_status[0]
                self.engine_pct = eng_prog[0]
                self.engine_status = eng_status[0]
                avg_pct = int((lich_prog[0] + eng_prog[0]) / 2)
                l_pct, l_st = lich_prog[0], lich_status[0]
                e_pct, e_st = eng_prog[0], eng_status[0]
            progress_cb(avg_pct)
            status_cb(f"🌐 Lichess {l_pct}% ({l_st})  |  🤖 Engine {e_pct}% ({e_st})")
            if stream_key in ("lichess", None):
                tm.sub_progress.emit(self, "lichess", l_pct, l_st)
            if stream_key in ("engine", None):
                tm.sub_progress.emit(self, "engine", e_pct, e_st)

        def run_lich():
            def on_lich_prog(pct, *args):
                with lock:
                    lich_prog[0] = max(0, min(100, pct))
                    if args and isinstance(args[0], (str, int)):
                        if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                            lich_status[0] = tr_ui("task_center.job_positions_fmt", "{cur}/{tot} Stellungen", cur=args[0], tot=args[1])
                        else:
                            lich_status[0] = str(args[0])
                update_combined("lichess")

            try:
                succ, msg = run_lichess_import_and_calculate_scores(
                    repo_name=self.repo_name,
                    elo_category=self.elo_category,
                    progress_callback=on_lich_prog,
                    check_cancel=self.is_canceled,
                    reuse_other_courses=self.reuse_other_courses,
                    max_data_age_days=self.max_data_age_days
                )
            except Exception as e:
                succ, msg = False, str(e)

            with lock:
                results['lichess'] = (succ, msg)
                if succ:
                    lich_prog[0] = 100
                    lich_status[0] = tr_ui("task_center.indicator_finished", "Fertig!")
            update_combined("lichess")

        def run_eng():
            def on_eng_prog(pct, *args):
                with lock:
                    eng_prog[0] = max(0, min(100, pct))
                    if args and isinstance(args[0], (str, int)):
                        if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                            eng_status[0] = tr_ui("task_center.job_positions_fmt", "{cur}/{tot} Stellungen", cur=args[0], tot=args[1])
                        else:
                            eng_status[0] = str(args[0])
                update_combined("engine")

            def on_eng_st(st):
                with lock:
                    eng_status[0] = str(st)
                update_combined("engine")

            try:
                succ, msg = run_db_analysis(
                    repo_name=self.repo_name,
                    engine_path=self.engine_path,
                    depth=self.depth,
                    threads=self.threads,
                    progress_callback=on_eng_prog,
                    check_cancel=self.is_canceled,
                    reuse_other_courses=self.reuse_other_courses,
                    status_callback=on_eng_st
                )
            except Exception as e:
                succ, msg = False, str(e)

            with lock:
                results['engine'] = (succ, msg)
                if succ:
                    eng_prog[0] = 100
                    eng_status[0] = tr_ui("task_center.indicator_finished", "Fertig!")
            update_combined("engine")

        update_combined()
        t_lich = threading.Thread(target=run_lich, name=f"Parallel-Lichess-{self.repo_name}", daemon=True)
        t_eng = threading.Thread(target=run_eng, name=f"Parallel-Engine-{self.repo_name}", daemon=True)

        t_lich.start()
        t_eng.start()

        while t_lich.is_alive() or t_eng.is_alive():
            if self.is_canceled():
                break
            time.sleep(0.1)

        t_lich.join(timeout=2.0)
        t_eng.join(timeout=2.0)

        if self.is_canceled():
            return False, tr_ui("task_center.job_canceled", "Vom Benutzer abgebrochen.")

        l_succ, l_msg = results.get('lichess', (False, "Lichess-Import unvollständig"))
        e_succ, e_msg = results.get('engine', (False, "Engine-Scan unvollständig"))

        if l_succ and e_succ:
            progress_cb(100)
            return True, f"Paralleles Update für '{self.repo_name}' erfolgreich abgeschlossen."
        elif not l_succ and not e_succ:
            return False, f"Fehler bei beiden Aufgaben: Lichess ({l_msg}), Engine ({e_msg})"
        elif not l_succ:
            return False, f"Engine fertig, aber Lichess-Fehler: {l_msg}"
        else:
            return False, f"Lichess fertig, aber Engine-Fehler: {e_msg}"


class BatchMaintenanceJob(BackgroundJob):
    def __init__(self, repo_configs: List[Dict[str, Any]], tasks: Any, engine_settings: Optional[Dict[str, Any]] = None):
        super().__init__(
            title=tr_ui("task_center.job_title_batch", "Wartungs-Batch ({count} Repertoires)", count=len(repo_configs)),
            repo_name="Multi",
            job_type=JobType.BATCH_MAINTENANCE,
            details={"repo_count": len(repo_configs), "tasks": tasks, "engine_settings": engine_settings}
        )
        self.repo_configs = repo_configs
        self.tasks = tasks
        self.engine_settings = engine_settings or {}

        if isinstance(self.tasks, (list, tuple, set)):
            self.tasks_dict = {t: True for t in self.tasks}
        elif isinstance(self.tasks, dict):
            self.tasks_dict = dict(self.tasks)
        else:
            self.tasks_dict = {}

        self.active_tasks = [t for t in ['cleanup', 'lichess', 'stats', 'engine', 'transpositions'] if self.tasks_dict.get(t)]
        self.completed_tasks: Dict[str, set] = {cfg['name']: set() for cfg in self.repo_configs}
        self.repo_task_status: Dict[str, Dict[str, Tuple[int, str]]] = {
            cfg['name']: {t: (0, "Wartend") for t in self.active_tasks}
            for cfg in self.repo_configs
        }
        self.completed_repos_count: int = 0
        self.last_completed_repo: str = ""
        self.lichess_pct: int = 0
        self.lichess_status: str = ""
        self.engine_pct: int = 0
        self.engine_status: str = ""

    def execute(self, progress_cb: Callable[[int], None], status_cb: Callable[[str], None]) -> Tuple[bool, str]:
        tm = get_task_manager()
        total_repos = max(1, len(self.repo_configs))
        num_tasks = max(1, len(self.active_tasks))
        total_units = total_repos * num_tasks
        lock = threading.Lock()

        def _recalc_overall_pct() -> int:
            total_sum = 0
            for r_name, t_map in self.repo_task_status.items():
                for t_key in self.active_tasks:
                    p_val, _ = t_map.get(t_key, (0, ""))
                    total_sum += max(0, min(100, p_val))
            return int(total_sum / max(1, total_units))

        def on_overall_prog(cur, tot, last_name):
            with lock:
                self.completed_repos_count = cur
                self.last_completed_repo = last_name
                overall_pct = max(self.progress, int((cur / max(1, tot)) * 100), _recalc_overall_pct())
                self.progress = overall_pct
            progress_cb(overall_pct)
            status_cb(f"Gesamtfortschritt ({cur}/{tot}): {last_name} ✓")
            tm.batch_overall_progress.emit(self, cur, tot, last_name)

        def on_repo_status(name, t_type, p, st):
            p_clamped = max(0, min(100, int(p)))
            with lock:
                if name in self.repo_task_status:
                    self.repo_task_status[name][t_type] = (p_clamped, str(st))
                if p_clamped >= 100 and t_type in self.active_tasks and name in self.completed_tasks:
                    self.completed_tasks[name].add(t_type)
                overall_pct = max(self.progress, _recalc_overall_pct())
                self.progress = overall_pct
                if t_type == "lichess":
                    self.lichess_pct = p_clamped
                    self.lichess_status = f"{name}: {st}"
                elif t_type in ("engine", "transpositions"):
                    self.engine_pct = p_clamped
                    self.engine_status = f"{name}: {st}"
            progress_cb(overall_pct)
            status_cb(f"[{name}] {t_type} ({p_clamped}%): {st}")
            tm.batch_repo_status.emit(self, name, t_type, p_clamped, str(st))
            if t_type == "lichess":
                tm.sub_progress.emit(self, "lichess", p_clamped, f"{name}: {st}")
            elif t_type in ("engine", "transpositions"):
                tm.sub_progress.emit(self, "engine", p_clamped, f"{name}: {st}")

        # Ensure engine_settings has 'path' if 'engine_path' was provided
        eng_settings = dict(self.engine_settings)
        if 'engine_path' in eng_settings and 'path' not in eng_settings:
            eng_settings['path'] = eng_settings['engine_path']

        return run_group_maintenance(
            repo_configs=self.repo_configs,
            tasks=self.tasks_dict,
            engine_settings=eng_settings,
            overall_progress_callback=on_overall_prog,
            repo_status_callback=on_repo_status,
            check_cancel=self.is_canceled
        )


class _WorkerThread(QThread):
    def __init__(self, manager: "BackgroundTaskManager"):
        super().__init__()
        self.manager = manager

    def run(self):
        while True:
            job = self.manager._get_next_job()
            if not job:
                break

            self.manager._set_current_job(job)
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
            job.status_message = tr_ui("task_center.job_started", "Gestartet...")
            self.manager.task_started.emit(job)

            def on_progress(pct: int):
                job.progress = max(0, min(100, pct))
                self.manager.task_progress.emit(job, job.progress, job.status_message)

            def on_status(text: str):
                job.status_message = text
                self.manager.task_progress.emit(job, job.progress, job.status_message)

            try:
                success, message = job.execute(on_progress, on_status)
                if job.is_canceled():
                    job.status = JobStatus.CANCELED
                    job.status_message = tr_ui("task_center.job_canceled", "Vom Benutzer abgebrochen.")
                elif success:
                    job.status = JobStatus.COMPLETED
                    job.status_message = message or tr_ui("task_center.job_completed", "Erfolgreich abgeschlossen.")
                    job.progress = 100
                else:
                    job.status = JobStatus.FAILED
                    job.status_message = message or tr_ui("task_center.job_failed", "Fehlgeschlagen.")
                    job.error_message = message
            except Exception as e:
                logger.error(f"Error executing background task {job.title}: {e}", exc_info=True)
                job.status = JobStatus.FAILED
                job.status_message = str(e)
                job.error_message = str(e)
                success = False
                message = str(e)

            job.finished_at = time.time()
            self.manager._finish_current_job(job, success, message)

        self.manager._on_worker_finished()


class BackgroundTaskManager(QObject):
    """
    Central, thread-safe background task queue and manager.
    Decoupled from dialog windows so that tasks continue running regardless
    of window closures or repertoire switching.
    """
    task_enqueued = pyqtSignal(object)
    task_started = pyqtSignal(object)
    task_progress = pyqtSignal(object, int, str)
    sub_progress = pyqtSignal(object, str, int, str)
    batch_repo_status = pyqtSignal(object, str, str, int, str)
    batch_overall_progress = pyqtSignal(object, int, int, str)
    task_finished = pyqtSignal(object, bool, str)
    queue_updated = pyqtSignal()
    all_completed = pyqtSignal()

    _instance = None
    _init_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "BackgroundTaskManager":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = BackgroundTaskManager()
            return cls._instance

    def __init__(self):
        super().__init__()
        self._queue: collections.deque[BackgroundJob] = collections.deque()
        self._history: List[BackgroundJob] = []
        self._current_job: Optional[BackgroundJob] = None
        self._worker: Optional[_WorkerThread] = None
        self._lock = threading.RLock()

    def enqueue(self, job: BackgroundJob) -> None:
        """Adds a job to the queue and starts the worker if idle."""
        with self._lock:
            self._queue.append(job)
            logger.info(f"[TaskManager] Enqueued job: {job.title} (ID: {job.job_id})")
            self.task_enqueued.emit(job)
            self.queue_updated.emit()
            self._ensure_worker_running()

    def cancel_current(self) -> None:
        """Requests cancellation of the currently executing job."""
        with self._lock:
            if self._current_job and self._current_job.status == JobStatus.RUNNING:
                logger.info(f"[TaskManager] Canceling current job: {self._current_job.title}")
                self._current_job.cancel()

    def cancel_task(self, job_id: str) -> None:
        """Cancels a specific job by ID (either current or in queue)."""
        with self._lock:
            if self._current_job and self._current_job.job_id == job_id:
                self.cancel_current()
                return
            # Remove from queue if pending
            new_queue = collections.deque()
            for j in self._queue:
                if j.job_id == job_id:
                    j.status = JobStatus.CANCELED
                    j.status_message = "Aus Warteschlange entfernt."
                    self._history.append(j)
                else:
                    new_queue.append(j)
            self._queue = new_queue
            self.queue_updated.emit()

    def clear_queue(self) -> None:
        """Clears all pending jobs in the queue."""
        with self._lock:
            for j in self._queue:
                j.status = JobStatus.CANCELED
                j.status_message = "Aus Warteschlange entfernt."
                self._history.append(j)
            self._queue.clear()
            self.queue_updated.emit()

    def is_running(self) -> bool:
        with self._lock:
            return self._current_job is not None or len(self._queue) > 0

    def get_current_job(self) -> Optional[BackgroundJob]:
        with self._lock:
            return self._current_job

    def get_queue(self) -> List[BackgroundJob]:
        with self._lock:
            return list(self._queue)

    def get_history(self) -> List[BackgroundJob]:
        with self._lock:
            return list(self._history)

    def _ensure_worker_running(self):
        if self._worker is None or not self._worker.isRunning():
            self._worker = _WorkerThread(self)
            self._worker.start(QThread.Priority.LowPriority)

    def _get_next_job(self) -> Optional[BackgroundJob]:
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def _set_current_job(self, job: Optional[BackgroundJob]):
        with self._lock:
            self._current_job = job
            self.queue_updated.emit()

    def _finish_current_job(self, job: BackgroundJob, success: bool, message: str):
        with self._lock:
            self._history.append(job)
            self._current_job = None
            logger.info(f"[TaskManager] Finished job: {job.title} | Success: {success} | Msg: {message}")
            self.task_finished.emit(job, success, message)
            self.queue_updated.emit()

    def _on_worker_finished(self):
        with self._lock:
            self._worker = None
            if len(self._queue) == 0 and self._current_job is None:
                self.all_completed.emit()


def get_task_manager() -> BackgroundTaskManager:
    """Helper to retrieve the global BackgroundTaskManager singleton."""
    return BackgroundTaskManager.get_instance()
