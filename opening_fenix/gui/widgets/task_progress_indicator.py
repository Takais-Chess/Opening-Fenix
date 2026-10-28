from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QCursor

from opening_fenix.core.services.task_manager_service import get_task_manager, JobStatus
from opening_fenix.core.translation import tr_ui
from opening_fenix.gui.scaling import scale


class TaskProgressIndicator(QFrame):
    """
    Transient, floating black pill indicator that appears in the top-right corner
    underneath the window close button ONLY when a background task is running.
    Clicking it opens the Task & Analysis Center dialog.
    """
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TaskProgressIndicator")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(tr_ui("task_center.indicator_tooltip", "Klicken, um das Aufgaben- & Analyse-Center zu öffnen"))

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(scale(14), scale(5), scale(14), scale(5))
        self.layout.setSpacing(scale(10))

        # Icon / Spinner Label
        self.lbl_icon = QLabel("⟳")
        self.lbl_icon.setStyleSheet("color: #38bdf8; font-size: 14px; font-weight: bold; background: transparent; border: none;")
        self.layout.addWidget(self.lbl_icon)

        # Status text
        self.lbl_text = QLabel(tr_ui("task_center.indicator_idle", "Hintergrundaufgabe läuft..."))
        self.lbl_text.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600; background: transparent; border: none;")
        self.layout.addWidget(self.lbl_text)

        # Mini Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedSize(scale(65), scale(6))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #334155;
                border: none;
                border-radius: {scale(3)}px;
            }}
            QProgressBar::chunk {{
                background-color: #38bdf8;
                border-radius: {scale(3)}px;
            }}
        """)
        self.layout.addWidget(self.progress_bar)

        # Pop-out arrow
        self.lbl_arrow = QLabel("↗")
        self.lbl_arrow.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: bold; background: transparent; border: none;")
        self.layout.addWidget(self.lbl_arrow)

        # Crisp black pill styling
        self.setStyleSheet(f"""
            QFrame#TaskProgressIndicator {{
                background-color: #111318;
                border: 1px solid #334155;
                border-radius: {scale(17)}px;
            }}
            QFrame#TaskProgressIndicator:hover {{
                background-color: #1e293b;
                border: 1px solid #38bdf8;
            }}
        """)

        self.setFixedHeight(scale(34))
        self.hide()

        # Connect to BackgroundTaskManager
        self.tm = get_task_manager()
        self.tm.task_started.connect(self._on_task_started)
        self.tm.task_progress.connect(self._on_task_progress)
        self.tm.task_finished.connect(self._on_task_finished)
        self.tm.all_completed.connect(self._on_all_completed)

        # Install event filter on parent to maintain top-right position
        if parent:
            parent.installEventFilter(self)

        self._check_initial_state()

    def _check_initial_state(self):
        if self.tm.is_running():
            curr = self.tm.get_current_job()
            if curr:
                self._on_task_started(curr)
                self._on_task_progress(curr, curr.progress, curr.status_message)

    def eventFilter(self, watched, event):
        if watched == self.parent() and event.type() == QEvent.Type.Resize:
            self._update_position()
        return super().eventFilter(watched, event)

    def _update_position(self):
        if not self.parent():
            return
        p_width = self.parent().width()
        w = self.sizeHint().width()
        h = self.height()
        # Top-right directly under the window close button (which is 25px tall at y=0..25)
        self.setGeometry(p_width - w - scale(12), scale(28), w, h)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _on_task_started(self, job):
        self.lbl_icon.setText("⟳")
        self.lbl_icon.setStyleSheet("color: #38bdf8; font-size: 14px; font-weight: bold; background: transparent; border: none;")
        self.lbl_text.setText(f"{job.repo_name} • {job.title}")
        self.progress_bar.setValue(job.progress)
        self.adjustSize()
        self._update_position()
        self.show()
        self.raise_()

    def _on_task_progress(self, job, pct, status_text):
        self.progress_bar.setValue(pct)
        # Shorten repo and status for chip display
        short_title = job.title.split(":")[0] if ":" in job.title else job.title
        self.lbl_text.setText(f"{job.repo_name} • {short_title} ({pct}%)")
        self.adjustSize()
        self._update_position()
        if not self.isVisible():
            self.show()
            self.raise_()

    def _on_task_finished(self, job, success, message):
        if success:
            self.lbl_icon.setText("✓")
            self.lbl_icon.setStyleSheet("color: #4ade80; font-size: 14px; font-weight: bold; background: transparent; border: none;")
            self.lbl_text.setText(f"{job.repo_name} • {tr_ui('task_center.indicator_finished', 'Fertig!')}")
            self.progress_bar.setValue(100)
        else:
            self.lbl_icon.setText("⚠")
            self.lbl_icon.setStyleSheet("color: #f87171; font-size: 14px; font-weight: bold; background: transparent; border: none;")
            self.lbl_text.setText(f"{job.repo_name} • {tr_ui('task_center.indicator_canceled', 'Abgebrochen')}")
        self.adjustSize()
        self._update_position()

    def _on_all_completed(self):
        # Auto-hide after 3.5 seconds
        QTimer.singleShot(3500, self._auto_hide_if_idle)

    def _auto_hide_if_idle(self):
        if not self.tm.is_running():
            self.hide()
