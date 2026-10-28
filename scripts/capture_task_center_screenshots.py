import os
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Add project root to sys.path
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

from opening_fenix.gui.dialogs.task_center_dialog import TaskCenterDialog
from opening_fenix.core.services.task_manager_service import (
    get_task_manager, EngineScanJob, LichessJob, JobStatus
)

def capture_screenshots():
    app = QApplication.instance() or QApplication(sys.argv)
    
    out_dir = r"C:\Users\Felix\.gemini\antigravity\brain\cf2111fb-bb8d-42af-baa7-d1cc69b6f5b8"
    os.makedirs(out_dir, exist_ok=True)

    dlg = TaskCenterDialog(None, active_repo_name="1.e4 giri")
    dlg.show()
    app.processEvents()

    # Capture Tab 1 (Single)
    dlg.tabs.setCurrentIndex(0)
    app.processEvents()
    pix1 = dlg.grab()
    path1 = os.path.join(out_dir, "screenshot_tab1_single.png")
    pix1.save(path1, "PNG")
    print(f"Captured Tab 1: {path1}")

    # Capture Tab 2 (Batch)
    dlg.tabs.setCurrentIndex(1)
    app.processEvents()
    pix2 = dlg.grab()
    path2 = os.path.join(out_dir, "screenshot_tab2_batch.png")
    pix2.save(path2, "PNG")
    print(f"Captured Tab 2: {path2}")

    # Simulate an active job for Tab 3
    tm = get_task_manager()
    job_active = EngineScanJob("1.e4 giri", depth=16, threads=4, engine_path="stockfish.exe")
    job_active.status = JobStatus.RUNNING
    job_active.progress = 42
    job_active.status_message = "Stellung 14/33 (42%) • e4 c5 Nf3 d6 d4"
    
    job_queued = LichessJob("Französisch Giri", "high")
    job_queued.status = JobStatus.QUEUED

    tm._current_job = job_active
    tm._queue.append(job_queued)

    dlg.tabs.setCurrentIndex(2)
    dlg._refresh_queue_display()
    app.processEvents()
    pix3 = dlg.grab()
    path3 = os.path.join(out_dir, "screenshot_tab3_queue.png")
    pix3.save(path3, "PNG")
    print(f"Captured Tab 3: {path3}")

    dlg.close()
    print("All screenshots captured successfully!")

if __name__ == "__main__":
    capture_screenshots()
