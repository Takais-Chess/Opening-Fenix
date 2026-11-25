import sys
import threading
from typing import Optional, Dict, Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QThread

from opening_fenix.core.logger import logger
from opening_fenix.core.services.cloud_sync_service import (
    CloudSyncService,
    HEARTBEAT_INTERVAL_SECONDS,
    format_relative_time,
)
from opening_fenix.core.threads import CloudSyncThread


class CloudSyncManager(QObject):
    """
    Application-wide Qt coordinator for Cloud Sync:
    - Periodic 60s session heartbeat (background daemon thread, never blocks GUI)
    - Detects cloud folder offline <-> online transitions and auto-syncs on reconnect
    - Debounced background push after training sessions & Creator edits
    - Publishes live status updates to top-bar status pills & Settings UI
    """

    sync_started = pyqtSignal(str)
    sync_progress = pyqtSignal(str, int, int)
    sync_finished = pyqtSignal(dict)
    status_changed = pyqtSignal(dict)
    conflicts_detected = pyqtSignal(list)

    _instance: Optional["CloudSyncManager"] = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[CloudSyncThread] = None
        self._pending_direction: Optional[str] = None
        self._pending_worker_scopes: Optional[set] = None
        self._pending_worker_full: bool = False
        self._debounced_scopes: Optional[set] = None
        self._debounced_full: bool = False
        self._was_offline: bool = CloudSyncService.is_offline()
        self._last_summary: Optional[Dict[str, Any]] = None
        self._last_errors: list = []

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(HEARTBEAT_INTERVAL_SECONDS * 1000)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat_tick)

    @classmethod
    def instance(cls) -> "CloudSyncManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        if cls._instance is not None:
            cls._instance.stop()
            cls._instance = None

    def start_heartbeat(self) -> None:
        """Starts the 60s background heartbeat timer (skipped automatically under pytest)."""
        if "pytest" in sys.modules:
            return
        if not CloudSyncService.is_configured():
            self.refresh_status()
            return
        if not self._heartbeat_timer.isActive():
            self._heartbeat_timer.start()
        self.refresh_status()

    def stop(self) -> None:
        """Stops timers and waits briefly for any running background sync."""
        if self._heartbeat_timer.isActive():
            self._heartbeat_timer.stop()
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        self.wait_for_active_sync(1500)

    def wait_for_active_sync(self, timeout_ms: int = 2000) -> None:
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.wait(timeout_ms)
            except Exception:
                pass

    def is_syncing(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def schedule_background_push(self, delay_ms: int = 30000, scopes=None) -> None:
        """
        Schedules a debounced background push (Local -> Cloud) after training/Creator writes.
        Repeated calls within delay_ms coalesce their scopes into a single snapshot push.
        """
        if "pytest" in sys.modules:
            return
        if not CloudSyncService.is_configured():
            return
        if CloudSyncService.is_offline():
            self._was_offline = True
            self.refresh_status()
            return
        if scopes is None:
            self._debounced_full = True
            self._debounced_scopes = None
        elif not self._debounced_full:
            if self._debounced_scopes is None:
                self._debounced_scopes = set(scopes)
            else:
                self._debounced_scopes.update(scopes)
        self._debounce_timer.start(max(1000, int(delay_ms)))

    def _on_debounce_timeout(self) -> None:
        scopes_to_run = None if self._debounced_full else self._debounced_scopes
        self._debounced_scopes = None
        self._debounced_full = False
        if CloudSyncService.is_enabled():
            self.trigger_sync(direction="push", scopes=scopes_to_run)
        else:
            self.refresh_status()

    def _on_heartbeat_tick(self) -> None:
        if not CloudSyncService.is_configured():
            self._heartbeat_timer.stop()
            self.refresh_status()
            return

        currently_offline = CloudSyncService.is_offline()
        if currently_offline:
            if not self._was_offline:
                logger.warning("CloudSyncManager: Cloud folder went offline; continuing in local_workspace.")
            self._was_offline = True
            self.refresh_status()
            return

        # Reconnected after being offline -> trigger automatic bidirectional sync!
        if self._was_offline and not currently_offline:
            self._was_offline = False
            logger.info("CloudSyncManager: Cloud folder reconnected! Triggering automatic sync...")
            CloudSyncService.acquire_session_lock()
            self.trigger_sync(direction="both")
            return

        # Normal online tick: update heartbeat off the GUI thread
        def _bg_hb():
            try:
                CloudSyncService.update_session_heartbeat()
            except Exception as e:
                logger.debug(f"CloudSyncManager heartbeat error: {e}")

        threading.Thread(target=_bg_hb, daemon=True, name="CloudSyncHeartbeat").start()
        self.refresh_status()

    def trigger_sync(self, direction: str = "both", scopes=None) -> bool:
        """Starts an asynchronous CloudSyncThread if enabled and not already running."""
        if not CloudSyncService.is_enabled():
            self.refresh_status()
            return False

        if self.is_syncing():
            # Queue a follow-up sync once current finishes (coalescing direction & scopes)
            if direction == "both" or self._pending_direction is None:
                self._pending_direction = direction
            if scopes is None:
                self._pending_worker_full = True
                self._pending_worker_scopes = None
            elif not self._pending_worker_full:
                if self._pending_worker_scopes is None:
                    self._pending_worker_scopes = set(scopes)
                else:
                    self._pending_worker_scopes.update(scopes)
            return True

        self._worker = CloudSyncThread(direction=direction, parent=self, scopes=scopes)
        self._worker.progress_signal.connect(self.sync_progress.emit)
        self._worker.finished_signal.connect(self._on_worker_finished)
        self.sync_started.emit(direction)
        self.refresh_status(syncing=True)
        self._worker.start(QThread.Priority.LowPriority)
        return True

    def _on_worker_finished(self, summary: dict) -> None:
        self._last_summary = summary
        self._last_errors = list(summary.get("errors") or [])
        self._worker = None
        self.sync_finished.emit(summary)
        self.refresh_status(syncing=False)

        conflicts = list(summary.get("conflicts") or [])
        provider_conflicts = list(summary.get("provider_conflict_files") or [])
        if conflicts or provider_conflicts:
            self.conflicts_detected.emit(conflicts)

        if self._pending_direction:
            next_dir = self._pending_direction
            next_scopes = None if self._pending_worker_full else self._pending_worker_scopes
            self._pending_direction = None
            self._pending_worker_scopes = None
            self._pending_worker_full = False
            QTimer.singleShot(300, lambda d=next_dir, s=next_scopes: self.trigger_sync(direction=d, scopes=s))

    def get_ui_status_snapshot(self, syncing: Optional[bool] = None) -> Dict[str, Any]:
        """Builds a UI-ready status dictionary for status pills & banners."""
        is_syncing_now = self.is_syncing() if syncing is None else syncing
        st = CloudSyncService.get_sync_status()
        configured = st.get("configured", False)
        offline = st.get("offline", False)
        other_sess = st.get("other_active_session")
        provider_conflicts = st.get("provider_conflict_files") or []

        if not configured:
            state = "local_only"
        elif is_syncing_now:
            state = "syncing"
        elif offline:
            state = "offline"
        elif provider_conflicts or self._last_errors:
            state = "warning"
        elif other_sess:
            state = "other_device"
        else:
            state = "synced"

        last_sync_at = st.get("last_sync_at")
        return {
            "state": state,
            "configured": configured,
            "offline": offline,
            "enabled": st.get("enabled", False),
            "cloud_dir": st.get("cloud_dir"),
            "local_dir": st.get("local_dir"),
            "last_sync_at": last_sync_at,
            "last_sync_rel": format_relative_time(last_sync_at) if last_sync_at else "",
            "last_sync_device": st.get("last_sync_device") or "",
            "other_active_session": other_sess,
            "provider_conflict_files": provider_conflicts,
            "last_errors": list(self._last_errors),
            "repertoire_count": st.get("repertoire_count", 0),
            "profile_count": st.get("profile_count", 0),
        }

    def refresh_status(self, syncing: Optional[bool] = None) -> Dict[str, Any]:
        info = self.get_ui_status_snapshot(syncing=syncing)
        self.status_changed.emit(info)
        return info
