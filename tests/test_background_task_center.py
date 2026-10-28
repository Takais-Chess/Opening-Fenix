import pytest
import time
from PyQt6.QtWidgets import QApplication, QWidget

from opening_fenix.core.services.task_manager_service import (
    BackgroundTaskManager, BackgroundJob, JobStatus, JobType,
    LichessJob, EngineScanJob, CombinedSyncJob, BatchMaintenanceJob,
    get_task_manager
)
from opening_fenix.gui.widgets.task_progress_indicator import TaskProgressIndicator
from opening_fenix.gui.dialogs.task_center_dialog import TaskCenterDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class DummyTestJob(BackgroundJob):
    def __init__(self, title="Test Job", repo="TestRepo", sleep_time=0.05, should_fail=False):
        super().__init__(title, repo, JobType.LICHESS)
        self.sleep_time = sleep_time
        self.should_fail = should_fail

    def execute(self, progress_cb, status_cb):
        status_cb("Running dummy test...")
        for i in range(1, 5):
            if self.is_canceled():
                return False, "Canceled"
            time.sleep(self.sleep_time)
            progress_cb(i * 25)

        if self.should_fail:
            return False, "Simulated failure"
        return True, "Simulated success"


def test_task_manager_singleton():
    tm1 = get_task_manager()
    tm2 = get_task_manager()
    assert tm1 is tm2


def test_job_instantiations():
    lj = LichessJob("TestSicilian", "high", reuse_other_courses=True, max_data_age_days=90)
    assert lj.repo_name == "TestSicilian"
    assert lj.job_type == JobType.LICHESS
    assert lj.details["max_data_age_days"] == 90

    ej = EngineScanJob("TestSicilian", depth=14, threads=2, engine_path="stockfish.exe")
    assert ej.depth == 14
    assert ej.threads == 2
    assert ej.job_type == JobType.ENGINE_SCAN

    cj = CombinedSyncJob("TestSicilian", "high", depth=12, threads=2, engine_path="stockfish.exe")
    assert cj.job_type == JobType.COMBINED

    bj = BatchMaintenanceJob([{"name": "Rep1"}], ["lichess", "engine"])
    assert bj.job_type == JobType.BATCH_MAINTENANCE


def test_task_manager_execution_and_cancellation(qapp):
    tm = BackgroundTaskManager() # Separate instance for isolated test
    job = DummyTestJob("Fast Job", "Repo1", sleep_time=0.01)

    completed_events = []
    tm.task_finished.connect(lambda j, s, m: completed_events.append((j, s, m)))

    tm.enqueue(job)

    # Process events until completed
    timeout = time.time() + 3.0
    while len(completed_events) == 0 and time.time() < timeout:
        qapp.processEvents()
        time.sleep(0.02)

    assert len(completed_events) == 1
    assert completed_events[0][1] is True
    assert job.status == JobStatus.COMPLETED


def test_task_manager_cancel_current(qapp):
    tm = BackgroundTaskManager()
    slow_job = DummyTestJob("Slow Job", "Repo2", sleep_time=0.2)

    tm.enqueue(slow_job)

    # Wait until it starts running
    timeout = time.time() + 2.0
    while slow_job.status != JobStatus.RUNNING and time.time() < timeout:
        qapp.processEvents()
        time.sleep(0.01)

    assert slow_job.status == JobStatus.RUNNING
    tm.cancel_current()

    timeout = time.time() + 2.0
    while slow_job.status == JobStatus.RUNNING and time.time() < timeout:
        qapp.processEvents()
        time.sleep(0.01)

    assert slow_job.status == JobStatus.CANCELED


def test_task_progress_indicator_behavior(qapp):
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    indicator = TaskProgressIndicator(parent)

    # By default, when idle, indicator should be hidden
    assert indicator.isHidden()

    # Simulate task started signal
    test_job = DummyTestJob("Active Job", "French")
    test_job.status = JobStatus.RUNNING
    indicator._on_task_started(test_job)

    assert not indicator.isHidden()
    assert "French" in indicator.lbl_text.text()

    # Simulate task progress signal
    indicator._on_task_progress(test_job, 50, "50% done")
    assert indicator.progress_bar.value() == 50

    # Simulate finish
    indicator._on_task_finished(test_job, True, "Done")
    assert "Fertig" in indicator.lbl_text.text()
    assert indicator.progress_bar.value() == 100


def test_task_center_dialog_initialization(qapp):
    dlg = TaskCenterDialog(None, active_repo_name=None)
    assert dlg.tabs.count() == 3
    assert dlg.combo_repo is not None
    assert dlg.spin_depth.value() >= 8

    # Verify closing does not raise exceptions
    dlg.close()


def test_repertoire_elo_sync(qapp, monkeypatch):
    from opening_fenix.gui.dialogs import task_center_dialog

    # Mock get_repertoire_elo
    elo_mock_map = {
        "HobbyRepo": "low",
        "ClubRepo": "mid",
        "MasterRepo": "masters",
        "DefaultRepo": "high"
    }
    monkeypatch.setattr(task_center_dialog, "get_repertoire_elo", lambda name: elo_mock_map.get(name, "high"))

    dlg = TaskCenterDialog(None, active_repo_name=None)
    dlg.combo_repo.addItem("HobbyRepo")
    dlg.combo_repo.addItem("ClubRepo")
    dlg.combo_repo.addItem("MasterRepo")

    dlg.set_active_repertoire("HobbyRepo")
    assert dlg.combo_elo.currentData() == "low"

    dlg.set_active_repertoire("ClubRepo")
    assert dlg.combo_elo.currentData() == "mid"

    dlg.set_active_repertoire("MasterRepo")
    assert dlg.combo_elo.currentData() == "masters"

    dlg.close()


def test_combined_sync_job_parallel(monkeypatch):
    import time
    from opening_fenix.core.services import task_manager_service

    lich_started = []
    eng_started = []

    def mock_lich(repo_name, elo_category, progress_callback, check_cancel, reuse_other_courses, max_data_age_days):
        lich_started.append(time.time())
        for p in [25, 50, 100]:
            if check_cancel(): break
            progress_callback(p, f"Lichess {p}")
            time.sleep(0.04)
        return True, "Lichess success"

    def mock_eng(repo_name, engine_path, depth, threads, progress_callback, check_cancel, reuse_other_courses, status_callback):
        eng_started.append(time.time())
        for p in [30, 60, 100]:
            if check_cancel(): break
            progress_callback(p)
            status_callback(f"Engine {p}")
            time.sleep(0.04)
        return True, "Engine success"

    monkeypatch.setattr(task_manager_service, "run_lichess_import_and_calculate_scores", mock_lich)
    monkeypatch.setattr(task_manager_service, "run_db_analysis", mock_eng)

    job = CombinedSyncJob("TestRepo", "high", depth=12, threads=2, engine_path="dummy.exe")
    progresses = []
    statuses = []

    succ, msg = job.execute(lambda p: progresses.append(p), lambda s: statuses.append(s))

    assert succ is True
    assert "Paralleles Update" in msg
    assert len(lich_started) == 1 and len(eng_started) == 1
    # Check that both started almost simultaneously (difference < 0.05s)
    assert abs(lich_started[0] - eng_started[0]) < 0.05
    assert len(progresses) > 0
    assert progresses[-1] == 100


def test_batch_maintenance_job_execution(monkeypatch):
    from opening_fenix.core.services import task_manager_service

    called_configs = []
    called_tasks = []
    called_settings = []

    def mock_run_group(repo_configs, tasks, engine_settings, overall_progress_callback, repo_status_callback, check_cancel):
        called_configs.extend(repo_configs)
        called_tasks.append(tasks)
        called_settings.append(engine_settings)
        overall_progress_callback(1, len(repo_configs), repo_configs[0]["name"])
        repo_status_callback(repo_configs[0]["name"], "engine", 100, "Done")
        return True, "Batch finished successfully"

    monkeypatch.setattr(task_manager_service, "run_group_maintenance", mock_run_group)

    tasks_dict = {
        'engine': True,
        'transpositions': False,
        'lichess': True,
        'cleanup': True,
        'stats': True,
        'lichess_reuse_courses': True,
        'lichess_max_age_days': 180
    }
    eng_settings = {'path': 'dummy.exe', 'depth': 18, 'transpos_depth': 25, 'threads': 4}

    job = BatchMaintenanceJob([{"name": "Repo1", "elo": "high"}], tasks_dict, eng_settings)

    progresses = []
    statuses = []
    succ, msg = job.execute(lambda p: progresses.append(p), lambda s: statuses.append(s))

    assert succ is True
    assert "Batch finished" in msg
    assert len(called_configs) == 1
    assert called_tasks[0]['engine'] is True
    assert called_settings[0]['path'] == 'dummy.exe'
    assert len(progresses) >= 1 and progresses[-1] == 100


def test_idea1_and_idea2_progress_widgets(qapp):
    dlg = TaskCenterDialog(None, active_repo_name=None)
    # Idea 1: 6-column live batch table + overall batch progress bar
    assert dlg.table_batch.columnCount() == 6
    assert hasattr(dlg, "pb_batch_overall")
    assert hasattr(dlg, "lbl_batch_overall")
    assert hasattr(dlg, "btn_run_batch")

    # Idea 2: Inline progress bars on Tab 1 + dual stream bars on Tab 3
    assert hasattr(dlg, "pb_single_lich")
    assert hasattr(dlg, "pb_single_eng")
    assert hasattr(dlg, "parallel_streams_frame")
    assert hasattr(dlg, "pb_curr_lich")
    assert hasattr(dlg, "pb_curr_eng")

    # Simulate CombinedSyncJob sub_progress
    comb_job = CombinedSyncJob("TestSicilian", "high", depth=12, threads=2, engine_path="dummy.exe")
    comb_job.status = JobStatus.RUNNING
    dlg.combo_repo.addItem("TestSicilian")
    dlg.set_active_repertoire("TestSicilian")
    dlg._on_sub_progress(comb_job, "lichess", 45, "45/100 positions")
    dlg._on_sub_progress(comb_job, "engine", 70, "70/100 positions")

    assert dlg.pb_single_lich.value() == 45
    assert dlg.pb_single_eng.value() == 70
    assert dlg.pb_curr_lich.value() == 45
    assert dlg.pb_curr_eng.value() == 70
    dlg.close()


