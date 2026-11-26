import time
import threading
import pytest
from PyQt6.QtWidgets import QApplication

from opening_fenix.core.services.task_manager_service import (
    BackgroundTaskManager,
    BackgroundJob,
    CombinedSyncJob,
    JobStatus,
    JobType,
)


@pytest.fixture(autouse=True)
def clean_task_manager(qapp):
    BackgroundTaskManager.reset_instance()
    yield
    tm = BackgroundTaskManager.get_instance()
    tm.clear_queue()
    tm.cancel_current()
    # Wait briefly for any active worker
    deadline = time.time() + 3.0
    while tm.is_running() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    BackgroundTaskManager.reset_instance()


class _QuickJob(BackgroundJob):
    def __init__(self, name: str, executed_list: list, delay: float = 0.01):
        super().__init__(title=name, repo_name="TestRepo", job_type=JobType.LICHESS)
        self.executed_list = executed_list
        self.delay = delay

    def execute(self, progress_cb, status_cb):
        time.sleep(self.delay)
        if self.is_canceled():
            return False, "Abgebrochen"
        self.executed_list.append(self.title)
        progress_cb(100)
        return True, "OK"


def test_rapid_stop_and_restart_never_strands_job(qapp):
    """
    Regression test for the worker exit/restart race condition:
    rapidly finishing/canceling and immediately enqueueing new jobs must
    never leave a job stranded in the queue without an active worker.
    """
    tm = BackgroundTaskManager.get_instance()
    executed = []

    for i in range(10):
        job = _QuickJob(f"Job-{i}", executed, delay=0.005)
        tm.enqueue(job)
        # Wait until it finishes, then immediately enqueue next right around worker exit
        deadline = time.time() + 10.0
        while job.status in (JobStatus.QUEUED, JobStatus.RUNNING) and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.002)
        assert job.status == JobStatus.COMPLETED

    assert executed == [f"Job-{i}" for i in range(10)]


def test_combined_sync_job_waits_for_child_threads_on_cancel(monkeypatch):
    """
    Regression test: CombinedSyncJob.execute() must wait for both child threads
    to exit cleanly on cancel rather than returning after a 2s timeout and
    leaving zombie threads running against SQLite/Stockfish.
    """
    from opening_fenix.core.services import lichess_service, analysis_service

    lich_exited = threading.Event()
    eng_exited = threading.Event()

    def slow_cancel_lich(repo_name, elo_category, progress_callback, check_cancel, reuse_other_courses, max_data_age_days):
        while not check_cancel():
            progress_callback(10, "Running")
            time.sleep(0.02)
        # Simulate cleanup/priority calc taking > 2.0s (previously caused 2s join timeout)
        time.sleep(2.2)
        lich_exited.set()
        return False, "Import abgebrochen."

    def slow_cancel_eng(repo_name, engine_path, depth, threads, progress_callback, check_cancel, reuse_other_courses, status_callback):
        while not check_cancel():
            progress_callback(15)
            time.sleep(0.02)
        time.sleep(2.2)
        eng_exited.set()
        return False, "Analyse abgebrochen."

    monkeypatch.setattr(lichess_service, "run_lichess_import_and_calculate_scores", slow_cancel_lich)
    monkeypatch.setattr(analysis_service, "run_db_analysis", slow_cancel_eng)

    job = CombinedSyncJob("TestRepo", "high", depth=12, threads=1, engine_path="dummy.exe")
    result_holder = {}

    def run_job():
        result_holder["res"] = job.execute(lambda p: None, lambda s: None)

    t = threading.Thread(target=run_job)
    t.start()
    time.sleep(0.1)
    job.cancel()
    t.join(timeout=6.0)

    assert not t.is_alive()
    assert lich_exited.is_set()
    assert eng_exited.is_set()
    assert result_holder["res"][0] is False


def test_task_center_dialog_cancel_and_restart_ui(qapp, monkeypatch):
    """
    Verifies TaskCenterDialog UI state transitions on stop and restart:
    - task_canceling disables cancel/stop buttons and shows stopping text
    - canceled CombinedSyncJob does NOT show 'Fertig!'
    - stale sub_progress from a canceled job is ignored
    """
    from opening_fenix.gui.dialogs.task_center_dialog import TaskCenterDialog
    from opening_fenix.core.services.repertoire_service import RepertoireService

    monkeypatch.setattr(RepertoireService, "get_all_repertoires", lambda self: ["TestRepo"])
    dlg = TaskCenterDialog(active_repo_name="TestRepo")

    job = CombinedSyncJob("TestRepo", "high", depth=12, threads=1, engine_path="dummy.exe")
    job.status = JobStatus.RUNNING
    tm = BackgroundTaskManager.get_instance()
    tm._current_job = job

    dlg._on_task_started(job)
    assert dlg.btn_cancel_curr.isEnabled() is True
    assert dlg.btn_start_comb.isEnabled() is True

    # Trigger cancel
    tm.cancel_current()
    qapp.processEvents()

    assert job.is_canceled() is True
    assert dlg.btn_cancel_curr.isEnabled() is False
    assert dlg.btn_start_comb.isEnabled() is False

    # Stale sub_progress after cancel must be ignored
    dlg.pb_single_lich.setValue(25)
    dlg._on_sub_progress(job, "lichess", 88, "Stale")
    assert dlg.pb_single_lich.value() == 25

    # Finishing as canceled must NOT show "Fertig!"
    job.status = JobStatus.CANCELED
    tm._current_job = None
    dlg._on_task_finished(job, False, "Vom Benutzer abgebrochen.")
    assert "Fertig" not in dlg.lbl_single_lich_status.text()
    assert "Fertig" not in dlg.lbl_single_eng_status.text()
    assert dlg.btn_start_comb.isEnabled() is True

    dlg.close()


def test_lichess_cancel_does_not_jump_progress_to_96(monkeypatch):
    """
    Regression test: canceling Lichess import should not emit progress 96%
    before returning.
    """
    from opening_fenix.core.services import lichess_service, priority_service

    monkeypatch.setattr(
        lichess_service,
        "run_lichess_import",
        lambda *args, **kwargs: (False, "Import abgebrochen."),
    )
    monkeypatch.setattr(
        priority_service,
        "calculate_priority_scores",
        lambda *args, **kwargs: (True, "OK"),
    )

    emitted = []
    succ, msg = lichess_service.run_lichess_import_and_calculate_scores(
        "TestRepo",
        "high",
        progress_callback=lambda pct, *a: emitted.append(pct),
        check_cancel=lambda: True,
    )

    assert succ is False
    assert 96 not in emitted
