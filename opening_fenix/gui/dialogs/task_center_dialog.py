import os
import multiprocessing
from typing import Optional, List, Dict, Any

from PyQt6 import sip
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
    QTabWidget, QGroupBox, QComboBox, QSpinBox, QCheckBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QMessageBox,
    QScrollArea, QAbstractItemView, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QCursor

from opening_fenix.core.services.task_manager_service import (
    get_task_manager, LichessJob, EngineScanJob, CombinedSyncJob,
    BatchMaintenanceJob, JobStatus, JobType
)
from opening_fenix.core.services.repertoire_service import RepertoireService
from opening_fenix.core.services.maintenance_service import get_repertoire_elo
from opening_fenix.core.threads import RepertoireStatsWorker
from opening_fenix.core.utils import get_elo_display, get_elo_internal, ELO_DISPLAY_MAP, get_repertoire_db_path
from opening_fenix.core.services.update_service import get_config_dict
from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import set_consistent_icon
from opening_fenix.core.translation import tr_ui, tr_widget


class BatchDualModeCell(QWidget):
    """
    A table cell widget that displays either a text label (when idle/finished)
    or a live progress bar (when Engine or Lichess is actively processing that repertoire).
    """
    def __init__(self, initial_text: str = "-", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(scale(6), scale(3), scale(6), scale(3))
        layout.setSpacing(0)

        self.label = QLabel(initial_text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(f"font-size: {scale(12)}px; color: #1e293b; font-weight: 500; background: transparent;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setFixedHeight(scale(20))
        self.progress_bar.hide()

        self._base_format = ""

        layout.addWidget(self.label)
        layout.addWidget(self.progress_bar)

    def show_text(self, text: str, tooltip: Optional[str] = None):
        self.progress_bar.hide()
        self._base_format = ""
        self.label.setText(text)
        self.label.show()
        if tooltip is not None:
            self.setToolTip(tooltip)
            self.label.setToolTip(tooltip)

    def show_progress(self, pct: int, tooltip: Optional[str] = None, format_str: Optional[str] = None):
        self.label.hide()
        self.progress_bar.setValue(max(0, min(100, pct)))
        self._base_format = format_str if format_str is not None else f"{pct}%"
        self.progress_bar.setFormat(self._base_format)
        self.progress_bar.show()
        if tooltip is not None:
            self.setToolTip(tooltip)
            self.progress_bar.setToolTip(tooltip)

    def text(self) -> str:
        return self.label.text()


class TaskCenterDialog(QDialog):
    """
    Dedicated, non-blocking Task & Analysis Center.
    Enables users to launch single or batch Lichess imports and Stockfish scans,
    freely minimize the window, and continue working without interruptions.
    """
    def __init__(self, parent=None, active_repo_name: Optional[str] = None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("task_center.title", "⚡ Aufgaben- & Analyse-Zentrum – Opening Fenix"))
        self.resize(scale(980), scale(780))
        self.setMinimumSize(scale(860), scale(660))

        # Full native window capabilities: minimize, maximize, close
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(False)

        self.active_repo_name = active_repo_name
        self.tm = get_task_manager()
        self.config = get_config_dict()
        self.stats_worker: Optional[RepertoireStatsWorker] = None
        self._batch_stats_loaded = False
        self._batch_name_to_row: Dict[str, int] = {}

        self._init_ui()
        self._apply_dialog_styles()
        self._connect_signals()
        self._refresh_queue_display()
        self._sync_running_state_to_ui()

    def _apply_dialog_styles(self):
        """Applies clean, authentic Opening Fenix light-theme styling with crisp contrast."""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #f8fafc;
            }}
            QWidget {{
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                color: #0f172a;
            }}
            QFrame#TopHeaderCard {{
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: {scale(8)}px;
            }}
            QFrame#TopHeaderCard QLabel {{
                border: none;
                background: transparent;
            }}
            QFrame#SubCard {{
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: {scale(6)}px;
            }}
            QFrame#SubCard QLabel {{
                border: none;
                background: transparent;
            }}
            QTabWidget::pane {{
                border: 1px solid #e2e8f0;
                border-radius: {scale(8)}px;
                background-color: #ffffff;
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: #f1f5f9;
                color: #475569;
                border: 1px solid #e2e8f0;
                border-bottom: none;
                border-top-left-radius: {scale(6)}px;
                border-top-right-radius: {scale(6)}px;
                padding: {scale(8)}px {scale(18)}px;
                margin-right: {scale(4)}px;
                font-weight: 600;
                font-size: {scale(13)}px;
            }}
            QTabBar::tab:selected {{
                background-color: #ffffff;
                color: #0284c7;
                border-color: #cbd5e1;
                border-bottom: 2px solid #0284c7;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: #e2e8f0;
                color: #0f172a;
            }}
            QGroupBox {{
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: {scale(8)}px;
                margin-top: {scale(12)}px;
                padding: {scale(10)}px;
                font-weight: bold;
                color: #0f172a;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {scale(12)}px;
                padding: 0 {scale(6)}px;
                color: #0f172a;
                font-size: {scale(13)}px;
            }}
            QComboBox, QSpinBox {{
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: {scale(6)}px;
                padding: {scale(4)}px {scale(8)}px;
                color: #0f172a;
                font-size: {scale(13)}px;
            }}
            QComboBox:hover, QSpinBox:hover {{
                border-color: #94a3b8;
            }}
            QComboBox:focus, QSpinBox:focus {{
                border-color: #0284c7;
            }}
            QCheckBox {{
                color: #1e293b;
                font-size: {scale(13)}px;
                spacing: {scale(8)}px;
            }}
            QTableWidget {{
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: {scale(6)}px;
                gridline-color: #f1f5f9;
                color: #0f172a;
                selection-background-color: #e0f2fe;
                selection-color: #0f172a;
            }}
            QHeaderView::section {{
                background-color: #f8fafc;
                color: #475569;
                font-weight: 600;
                font-size: {scale(12)}px;
                border: none;
                border-bottom: 1px solid #e2e8f0;
                padding: {scale(6)}px;
            }}
            QProgressBar {{
                background-color: #e2e8f0;
                border: none;
                border-radius: {scale(4)}px;
                text-align: center;
                color: #0f172a;
                font-weight: bold;
                font-size: {scale(11)}px;
            }}
            QProgressBar::chunk {{
                background-color: #0284c7;
                border-radius: {scale(4)}px;
            }}
            QProgressBar[class="SuccessBar"]::chunk {{
                background-color: #16a34a;
                border-radius: {scale(4)}px;
            }}
        """)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scale(18), scale(16), scale(18), scale(16))
        main_layout.setSpacing(scale(10))

        # Top Header Card
        header = QFrame()
        header.setObjectName("TopHeaderCard")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(scale(16), scale(10), scale(16), scale(10))

        v_titles = QVBoxLayout()
        v_titles.setSpacing(scale(2))
        lbl_title = QLabel(tr_ui("task_center.header_title", "<b>Hintergrund-Aufgaben & Daten-Synchronisation</b>"))
        lbl_title.setStyleSheet("font-size: 15px; color: #0f172a;")
        lbl_sub = QLabel(tr_ui("task_center.header_subtitle", "Lichess-Daten laden und Stockfish-Alternativen im Hintergrund berechnen."))
        lbl_sub.setStyleSheet("font-size: 11px; color: #64748b;")
        v_titles.addWidget(lbl_title)
        v_titles.addWidget(lbl_sub)
        h_layout.addLayout(v_titles)
        h_layout.addStretch()

        self.lbl_active_job_pill = QLabel(tr_ui("task_center.status_idle", "Bereit"))
        self.lbl_active_job_pill.setFixedHeight(scale(28))
        self._update_pill_badge("idle", tr_ui("task_center.status_idle", "Bereit"))
        h_layout.addWidget(self.lbl_active_job_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        main_layout.addWidget(header)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tabs, 1)

        # Tab 1: Single Repertoire
        self.tab_single = QWidget()
        self._init_tab_single(self.tab_single)
        self.tabs.addTab(self.tab_single, tr_ui("task_center.tab_single", "🎯 Einzelnes Repertoire"))

        # Tab 2: Batch Maintenance
        self.tab_batch = QWidget()
        self._init_tab_batch(self.tab_batch)
        self.tabs.addTab(self.tab_batch, tr_ui("task_center.tab_batch", "🚜 Wartungs-Batch (Multi)"))

        # Tab 3: Queue & History
        self.tab_queue = QWidget()
        self._init_tab_queue(self.tab_queue)
        self.tabs.addTab(self.tab_queue, tr_ui("task_center.tab_queue", "📋 Warteschlange && Verlauf").replace("&", "&&").replace("&&&&", "&&"))

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(0, scale(4), 0, 0)
        self.lbl_footer_info = QLabel(tr_ui("task_center.footer_info", "💡 Aufgaben laufen im Hintergrund weiter. Du kannst dieses Fenster minimieren oder schließen."))
        self.lbl_footer_info.setStyleSheet("color: #64748b; font-size: 11px;")
        bottom_bar.addWidget(self.lbl_footer_info)
        bottom_bar.addStretch()

        btn_minimize = QPushButton(tr_ui("task_center.btn_minimize", "🗕 Minimieren"))
        btn_minimize.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border-color: #94a3b8;
            }
        """)
        btn_minimize.clicked.connect(self.showMinimized)
        bottom_bar.addWidget(btn_minimize)

        btn_close = QPushButton(tr_ui("task_center.btn_run_in_background", "✕ Im Hintergrund ausführen"))
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                border: 1px solid #0284c7;
                border-radius: 6px;
                padding: 7px 18px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
        """)
        btn_close.clicked.connect(self.close)
        bottom_bar.addWidget(btn_close)
        main_layout.addLayout(bottom_bar)

    def _on_tab_changed(self, idx: int):
        if idx == 1 and not self._batch_stats_loaded:
            self._batch_stats_loaded = True
            self._start_batch_stats_worker()

    def _update_pill_badge(self, state: str, text: str):
        if state == "running":
            self.lbl_active_job_pill.setStyleSheet(f"""
                QLabel {{
                    background-color: #e0f2fe;
                    color: #0369a1;
                    border: 1px solid #7dd3fc;
                    border-radius: {scale(14)}px;
                    padding: {scale(4)}px {scale(12)}px;
                    font-weight: bold;
                    font-size: {scale(11)}px;
                }}
            """)
        else:
            self.lbl_active_job_pill.setStyleSheet(f"""
                QLabel {{
                    background-color: #f1f5f9;
                    color: #475569;
                    border: 1px solid #cbd5e1;
                    border-radius: {scale(14)}px;
                    padding: {scale(4)}px {scale(12)}px;
                    font-weight: bold;
                    font-size: {scale(11)}px;
                }}
            """)
        self.lbl_active_job_pill.setText(text)

    # ─── TAB 1: SINGLE REPERTOIRE (WITH SEPARATE INLINE PROGRESS BARS) ──────

    def _init_tab_single(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(scale(16), scale(12), scale(16), scale(12))
        layout.setSpacing(scale(8))

        # Repertoire Selector
        sel_card = QFrame()
        sel_card.setObjectName("SubCard")
        h_sel = QHBoxLayout(sel_card)
        h_sel.setContentsMargins(scale(12), scale(6), scale(12), scale(6))
        lbl_repo = QLabel(tr_ui("task_center.select_repo", "<b>Ziel-Repertoire:</b>"))
        lbl_repo.setStyleSheet("color: #0f172a; font-size: 13px; font-weight: bold;")
        self.combo_repo = QComboBox()
        self.combo_repo.setFixedHeight(scale(32))
        self.combo_repo.setMinimumWidth(scale(300))
        all_repos = RepertoireService().get_all_repertoires()
        for r in all_repos:
            self.combo_repo.addItem(r)
        if self.active_repo_name and self.active_repo_name in all_repos:
            self.combo_repo.setCurrentText(self.active_repo_name)
        self.combo_repo.currentTextChanged.connect(self._on_repo_selection_changed)
        h_sel.addWidget(lbl_repo)
        h_sel.addWidget(self.combo_repo, 1)
        layout.addWidget(sel_card)

        v_cards = QVBoxLayout()
        v_cards.setSpacing(scale(8))

        # Card 1: Lichess Data
        card_lich = QGroupBox(tr_ui("task_center.card_lich_title", "🌐 Lichess-Datenbank Import"))
        l_lich = QVBoxLayout(card_lich)
        l_lich.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        l_lich.setSpacing(scale(6))

        h_lich_opts = QHBoxLayout()
        lbl_elo = QLabel(tr_ui("task_center.lbl_elo_category", "Elo-Kategorie:"))
        lbl_elo.setStyleSheet("color: #334155; font-size: 12px; font-weight: 500;")
        h_lich_opts.addWidget(lbl_elo)
        self.combo_elo = QComboBox()
        self.combo_elo.setFixedHeight(scale(28))
        for k in ["low", "mid", "high", "masters"]:
            self.combo_elo.addItem(get_elo_display(k), k)
        self._on_repo_selection_changed(self.combo_repo.currentText())
        h_lich_opts.addWidget(self.combo_elo, 1)

        lbl_age = QLabel(tr_ui("task_center.lbl_max_age", "Max. Datenalter:"))
        lbl_age.setStyleSheet("color: #334155; font-size: 12px; font-weight: 500;")
        h_lich_opts.addWidget(lbl_age)
        self.combo_max_age = QComboBox()
        self.combo_max_age.setFixedHeight(scale(28))
        self.combo_max_age.addItem(tr_ui("task_center.age_90", "90 Tage"), 90)
        self.combo_max_age.addItem(tr_ui("task_center.age_180", "180 Tage (Standard)"), 180)
        self.combo_max_age.addItem(tr_ui("task_center.age_365", "1 Jahr"), 365)
        self.combo_max_age.addItem(tr_ui("task_center.age_unlimited", "Unbegrenzt"), 9999)
        self.combo_max_age.setCurrentIndex(1)
        h_lich_opts.addWidget(self.combo_max_age, 1)
        l_lich.addLayout(h_lich_opts)

        self.chk_lich_reuse = QCheckBox(tr_ui("task_center.reuse_courses", "Daten aus anderen Kursen wiederverwenden"))
        self.chk_lich_reuse.setChecked(True)
        l_lich.addWidget(self.chk_lich_reuse)

        self.btn_start_lich = QPushButton(tr_ui("task_center.btn_start_lich", "🌐 Lichess-Import starten").replace("&", "&&").replace("&&&&", "&&"))
        self.btn_start_lich.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start_lich.setFixedHeight(scale(32))
        self._style_single_btn(self.btn_start_lich, "#0284c7", "#0369a1")
        self.btn_start_lich.clicked.connect(self._on_start_single_lichess)
        l_lich.addWidget(self.btn_start_lich)

        # Inline Lichess Progress Bar & Status
        h_lich_prog = QHBoxLayout()
        h_lich_prog.setSpacing(scale(10))
        self.lbl_single_lich_status = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        self.lbl_single_lich_status.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500;")
        self.lbl_single_lich_status.setMinimumWidth(scale(180))
        self.pb_single_lich = QProgressBar()
        self.pb_single_lich.setRange(0, 100)
        self.pb_single_lich.setValue(0)
        self.pb_single_lich.setFixedHeight(scale(18))
        h_lich_prog.addWidget(self.lbl_single_lich_status)
        h_lich_prog.addWidget(self.pb_single_lich, 1)
        l_lich.addLayout(h_lich_prog)

        v_cards.addWidget(card_lich)

        # Card 2: Engine Analysis
        card_eng = QGroupBox(tr_ui("task_center.card_eng_title", "🤖 Engine-Alternativzüge scannen"))
        l_eng = QVBoxLayout(card_eng)
        l_eng.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        l_eng.setSpacing(scale(6))

        h_eng_opts = QHBoxLayout()
        lbl_depth = QLabel(tr_ui("task_center.lbl_search_depth", "Suchtiefe:"))
        lbl_depth.setStyleSheet("color: #334155; font-size: 12px; font-weight: 500;")
        h_eng_opts.addWidget(lbl_depth)
        self.spin_depth = QSpinBox()
        self.spin_depth.setFixedHeight(scale(28))
        self.spin_depth.setMinimumWidth(scale(80))
        self.spin_depth.setRange(8, 30)
        try:
            depth_val = int(self.config.get("engine_depth", 18))
        except (ValueError, TypeError):
            depth_val = 18
        self.spin_depth.setValue(depth_val)
        h_eng_opts.addWidget(self.spin_depth)

        h_eng_opts.addSpacing(scale(14))
        lbl_threads = QLabel(tr_ui("task_center.lbl_cpu_threads", "CPU-Threads:"))
        lbl_threads.setStyleSheet("color: #334155; font-size: 12px; font-weight: 500;")
        h_eng_opts.addWidget(lbl_threads)
        self.combo_threads = QComboBox()
        self.combo_threads.setFixedHeight(scale(28))
        self.combo_threads.setMinimumWidth(scale(80))
        max_cpus = multiprocessing.cpu_count()
        for t in range(1, max_cpus + 1):
            self.combo_threads.addItem(str(t))
        self.combo_threads.setCurrentText(str(min(4, max(1, int(max_cpus * 0.25)))))
        h_eng_opts.addWidget(self.combo_threads)
        h_eng_opts.addStretch()
        l_eng.addLayout(h_eng_opts)

        self.chk_eng_reuse = QCheckBox(tr_ui("task_center.reuse_eng_cache", "Analysen aus anderen Kursen wiederverwenden"))
        self.chk_eng_reuse.setChecked(True)
        l_eng.addWidget(self.chk_eng_reuse)

        self.btn_start_eng = QPushButton(tr_ui("task_center.btn_start_eng", "🤖 Engine-Scan starten"))
        self.btn_start_eng.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start_eng.setFixedHeight(scale(32))
        self._style_single_btn(self.btn_start_eng, "#2563eb", "#1d4ed8")
        self.btn_start_eng.clicked.connect(self._on_start_single_engine)
        l_eng.addWidget(self.btn_start_eng)

        # Inline Engine Progress Bar & Status
        h_eng_prog = QHBoxLayout()
        h_eng_prog.setSpacing(scale(10))
        self.lbl_single_eng_status = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        self.lbl_single_eng_status.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500;")
        self.lbl_single_eng_status.setMinimumWidth(scale(180))
        self.pb_single_eng = QProgressBar()
        self.pb_single_eng.setRange(0, 100)
        self.pb_single_eng.setValue(0)
        self.pb_single_eng.setFixedHeight(scale(18))
        h_eng_prog.addWidget(self.lbl_single_eng_status)
        h_eng_prog.addWidget(self.pb_single_eng, 1)
        l_eng.addLayout(h_eng_prog)

        v_cards.addWidget(card_eng)

        # Card 3: Combined Action (Parallel execution)
        card_comb = QGroupBox(tr_ui("task_center.card_comb_title", "⚡ Vollständiges Update"))
        l_comb = QVBoxLayout(card_comb)
        l_comb.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        l_comb.setSpacing(scale(6))
        lbl_comb_desc = QLabel(tr_ui("task_center.comb_desc", "Führt Lichess-Import und Stockfish-Analyse gleichzeitig im Hintergrund aus."))
        lbl_comb_desc.setStyleSheet("color: #475569; font-size: 12px;")
        l_comb.addWidget(lbl_comb_desc)

        self.btn_start_comb = QPushButton(tr_ui("task_center.btn_start_comb", "⚡ Vollständiges Update starten"))
        self.btn_start_comb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start_comb.setFixedHeight(scale(32))
        self._style_single_btn(self.btn_start_comb, "#16a34a", "#15803d")
        self.btn_start_comb.clicked.connect(self._on_start_combined)
        l_comb.addWidget(self.btn_start_comb)
        v_cards.addWidget(card_comb)

        layout.addLayout(v_cards)

    def _style_single_btn(self, btn: QPushButton, bg: str, hover: str):
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
        """)

    # ─── TAB 2: BATCH MAINTENANCE (WITH RICH 6-COLUMN LIVE TABLE) ───────────

    def _init_tab_batch(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(scale(16), scale(10), scale(16), scale(12))
        layout.setSpacing(scale(8))

        # Top Section: Two Cards side-by-side (Tasks and Engine Settings)
        h_config = QHBoxLayout()
        h_config.setSpacing(scale(12))

        # ── Left Card: Tasks ──
        grp_tasks = QGroupBox("📋 " + tr_ui("task_center.batch_tasks_title", "Aufgaben"))
        v_tasks = QVBoxLayout(grp_tasks)
        v_tasks.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        v_tasks.setSpacing(scale(4))

        self.chk_b_eng = QCheckBox(tr_ui("repo_settings.task_engine", "Engine-Analyse (Alternativen)"))
        self.chk_b_eng.setChecked(True)

        self.chk_b_transpos = QCheckBox(tr_ui("repo_settings.task_transpositions", "Überleitungen scannen (2-Züge)"))
        self.chk_b_transpos.setToolTip(tr_ui("repo_settings.task_transpositions_tip", "Sucht mit der Engine nach 2-zügigen Überleitungen und speichert sie im Repertoire."))
        self.chk_b_transpos.setChecked(False)

        self.chk_b_lich = QCheckBox(tr_ui("repo_settings.task_lichess", "Lichess-Import (Trend-Daten)"))
        self.chk_b_lich.setChecked(True)

        # Lichess cross-course options (indented)
        h_lich_opts = QHBoxLayout()
        h_lich_opts.setContentsMargins(scale(22), 0, 0, 0)
        h_lich_opts.setSpacing(scale(8))
        self.chk_batch_reuse = QCheckBox(tr_ui("repo_settings.chk_batch_reuse_courses", "⚡ Daten aus anderen Kursen nutzen"))
        self.chk_batch_reuse.setChecked(True)
        h_lich_opts.addWidget(self.chk_batch_reuse)

        self.combo_batch_max_age = QComboBox()
        self.combo_batch_max_age.setFixedHeight(scale(26))
        self.combo_batch_max_age.addItem(tr_ui("repo_settings.age_90_days", "Max. 3 Monate"), 90)
        self.combo_batch_max_age.addItem(tr_ui("repo_settings.age_180_days", "Max. 6 Monate (Empfohlen)"), 180)
        self.combo_batch_max_age.addItem(tr_ui("repo_settings.age_365_days", "Max. 1 Jahr"), 365)
        self.combo_batch_max_age.addItem(tr_ui("repo_settings.age_unlimited", "Beliebig"), 9999)
        self.combo_batch_max_age.setCurrentIndex(1)
        h_lich_opts.addWidget(self.combo_batch_max_age)
        h_lich_opts.addStretch()

        self.chk_b_cleanup = QCheckBox(tr_ui("repo_settings.task_cleanup_lichess", "Verwaiste Lichess-Daten bereinigen"))
        self.chk_b_cleanup.setChecked(True)

        self.chk_b_stats = QCheckBox(tr_ui("repo_settings.task_stats", "Statistiken && Prioritäten berechnen").replace("&", "&&").replace("&&&&", "&&"))
        self.chk_b_stats.setChecked(True)

        v_tasks.addWidget(self.chk_b_eng)
        v_tasks.addWidget(self.chk_b_transpos)
        v_tasks.addWidget(self.chk_b_lich)
        v_tasks.addLayout(h_lich_opts)
        v_tasks.addWidget(self.chk_b_cleanup)
        v_tasks.addWidget(self.chk_b_stats)
        v_tasks.addStretch()
        h_config.addWidget(grp_tasks, 1)

        # ── Right Card: Engine Settings ──
        self.grp_b_engine = QGroupBox("⚙️ " + tr_ui("task_center.batch_engine_title", "Engine-Einstellungen"))
        v_engine = QVBoxLayout(self.grp_b_engine)
        v_engine.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        v_engine.setSpacing(scale(6))

        f_eng = QFormLayout()
        f_eng.setSpacing(scale(6))

        self.spin_b_engine_depth = QSpinBox()
        self.spin_b_engine_depth.setFixedHeight(scale(26))
        self.spin_b_engine_depth.setRange(10, 50)
        self.spin_b_engine_depth.setValue(18)
        self.spin_b_engine_depth.setSuffix(f" {tr_ui('repo_settings.moves_unit', 'Züge')}")

        self.spin_b_transpos_depth = QSpinBox()
        self.spin_b_transpos_depth.setFixedHeight(scale(26))
        self.spin_b_transpos_depth.setRange(10, 50)
        self.spin_b_transpos_depth.setValue(25)
        self.spin_b_transpos_depth.setSuffix(f" {tr_ui('repo_settings.moves_unit', 'Züge')}")

        self.combo_b_threads = QComboBox()
        self.combo_b_threads.setFixedHeight(scale(26))
        max_cpu = multiprocessing.cpu_count()
        for i in range(1, max_cpu + 1):
            self.combo_b_threads.addItem(f"{i} Thread{'s' if i > 1 else ''}", i)
        default_threads = max(1, min(6, int(max_cpu * 0.25)))
        idx_def = self.combo_b_threads.findData(default_threads)
        if idx_def >= 0:
            self.combo_b_threads.setCurrentIndex(idx_def)

        f_eng.addRow(tr_ui("repo_settings.engine_depth_label", "Engine-Tiefe:"), self.spin_b_engine_depth)
        f_eng.addRow(tr_ui("repo_settings.transpos_depth_label", "Überleitungen-Tiefe:"), self.spin_b_transpos_depth)
        f_eng.addRow(tr_ui("repo_settings.engine_threads_label", "Threads:"), self.combo_b_threads)
        v_engine.addLayout(f_eng)

        lbl_threads_hint = QLabel(tr_ui("repo_settings.engine_threads_hint", "Standard: 25% der CPU-Kerne ({threads} von {max} Threads)", threads=default_threads, max=max_cpu))
        lbl_threads_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        v_engine.addWidget(lbl_threads_hint)
        v_engine.addStretch()
        h_config.addWidget(self.grp_b_engine, 1)

        layout.addLayout(h_config)

        def _update_batch_enables():
            lich_on = self.chk_b_lich.isChecked()
            self.chk_batch_reuse.setEnabled(lich_on)
            self.combo_batch_max_age.setEnabled(lich_on and self.chk_batch_reuse.isChecked())

            eng_on = self.chk_b_eng.isChecked()
            trans_on = self.chk_b_transpos.isChecked()
            self.grp_b_engine.setEnabled(eng_on or trans_on)
            self.spin_b_engine_depth.setEnabled(eng_on)
            self.spin_b_transpos_depth.setEnabled(trans_on)
            self._update_idle_batch_progress_format()

        self.chk_b_lich.toggled.connect(lambda _: _update_batch_enables())
        self.chk_batch_reuse.toggled.connect(lambda _: _update_batch_enables())
        self.chk_b_eng.toggled.connect(lambda _: _update_batch_enables())
        self.chk_b_transpos.toggled.connect(lambda _: _update_batch_enables())
        self.chk_b_cleanup.toggled.connect(lambda _: _update_batch_enables())
        self.chk_b_stats.toggled.connect(lambda _: _update_batch_enables())

        # Table Header Bar: Selection count + Select All / Select None
        h_tbl_ctrl = QHBoxLayout()
        h_tbl_ctrl.setContentsMargins(0, scale(2), 0, 0)
        self.lbl_b_repo_count = QLabel()
        self.lbl_b_repo_count.setStyleSheet("font-weight: 600; color: #475569; font-size: 12px;")
        h_tbl_ctrl.addWidget(self.lbl_b_repo_count)
        h_tbl_ctrl.addStretch()

        btn_all = QPushButton(tr_ui("task_center.btn_select_all", "Alle auswählen"))
        btn_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_all.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 5px; padding: 4px 10px; font-weight: 500; font-size: 11px;")
        btn_all.clicked.connect(lambda: self._set_all_batch_checked(True))

        btn_none = QPushButton(tr_ui("task_center.btn_select_none", "Keine auswählen"))
        btn_none.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_none.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 5px; padding: 4px 10px; font-weight: 500; font-size: 11px;")
        btn_none.clicked.connect(lambda: self._set_all_batch_checked(False))

        h_tbl_ctrl.addWidget(btn_all)
        h_tbl_ctrl.addWidget(btn_none)
        layout.addLayout(h_tbl_ctrl)

        # 6-Column Live Repertoire Table
        self.table_batch = QTableWidget()
        self.table_batch.setColumnCount(6)
        self.table_batch.setHorizontalHeaderLabels([
            "",
            tr_ui("task_center.col_repertoire", "Repertoire"),
            tr_ui("task_center.col_target_elo", "Ziel-Elo (Lichess)"),
            tr_ui("repo_settings.col_analysis", "Analyse"),
            tr_ui("repo_settings.col_coverage", "Coverage"),
            tr_ui("repo_settings.col_progress", "Fortschritt")
        ])
        header = self.table_batch.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_batch.setColumnWidth(0, scale(42))
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table_batch.setColumnWidth(2, scale(155))
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_batch.setColumnWidth(3, scale(165))
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_batch.setColumnWidth(4, scale(125))
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table_batch.setColumnWidth(5, scale(140))

        self.table_batch.verticalHeader().setVisible(False)
        self.table_batch.verticalHeader().setDefaultSectionSize(scale(32))
        self.table_batch.setAlternatingRowColors(True)
        self.table_batch.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table_batch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_batch.setShowGrid(False)

        self._populate_batch_table()
        layout.addWidget(self.table_batch, 1)

        # Bottom Live Overall Progress & Start/Stop Bar
        bottom_batch_frame = QFrame()
        bottom_batch_frame.setObjectName("SubCard")
        h_batch_bot = QHBoxLayout(bottom_batch_frame)
        h_batch_bot.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        h_batch_bot.setSpacing(scale(14))

        v_batch_prog = QVBoxLayout()
        v_batch_prog.setSpacing(scale(3))
        self.lbl_batch_overall = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        self.lbl_batch_overall.setStyleSheet("font-weight: 600; color: #0f172a; font-size: 12px;")
        self.pb_batch_overall = QProgressBar()
        self.pb_batch_overall.setRange(0, 100)
        self.pb_batch_overall.setValue(0)
        self.pb_batch_overall.setFixedHeight(scale(20))
        v_batch_prog.addWidget(self.lbl_batch_overall)
        v_batch_prog.addWidget(self.pb_batch_overall)
        h_batch_bot.addLayout(v_batch_prog, 1)

        self.btn_run_batch = QPushButton(tr_ui("repo_settings.btn_start_batch_run", "🚀 Wartungs-Batch starten"))
        self.btn_run_batch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_run_batch.setFixedHeight(scale(38))
        self.btn_run_batch.setMinimumWidth(scale(230))
        self._style_single_btn(self.btn_run_batch, "#7c3aed", "#6d28d9")
        self.btn_run_batch.clicked.connect(self._on_start_batch)
        h_batch_bot.addWidget(self.btn_run_batch)

        layout.addWidget(bottom_batch_frame)
        _update_batch_enables()

    def _populate_batch_table(self):
        all_repos = RepertoireService().get_all_repertoires()
        self.table_batch.setRowCount(len(all_repos))
        self._batch_name_to_row.clear()
        total_tasks = self._get_selected_batch_task_count()

        from opening_fenix.core.services.repertoire_core_service import get_repertoire_meta_fast

        for row, r_name in enumerate(all_repos):
            self._batch_name_to_row[r_name] = row

            # Col 0: Checkbox
            chk = QCheckBox()
            chk.setChecked(True)
            chk.toggled.connect(self._update_batch_selection_count)
            chk_widget = QWidget()
            chk_widget.setStyleSheet("background: transparent;")
            ch_lay = QHBoxLayout(chk_widget)
            ch_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ch_lay.setContentsMargins(0, 0, 0, 0)
            ch_lay.addWidget(chk)
            chk_widget.checkbox = chk
            self.table_batch.setCellWidget(row, 0, chk_widget)

            # Col 1: Repertoire Name + Color Icon
            meta = get_repertoire_meta_fast(r_name)
            c_code = meta.get("color", "w") if meta else "w"
            c_icon = "♔" if c_code == "w" else "♚"
            item_name = QTableWidgetItem(f"{c_icon} {r_name}")
            item_name.setData(Qt.ItemDataRole.UserRole, r_name)
            item_name.setToolTip(r_name)
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_batch.setItem(row, 1, item_name)

            # Col 2: Target Elo
            repo_elo = get_repertoire_elo(r_name)
            elo_disp = get_elo_display(repo_elo)
            item_elo = QTableWidgetItem(elo_disp)
            item_elo.setToolTip(elo_disp)
            item_elo.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_elo.setFlags(item_elo.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_batch.setItem(row, 2, item_elo)

            # Col 3: Analysis DualModeCell
            cell_ana = BatchDualModeCell(tr_ui("analysis.loading", "Laden..."))
            self.table_batch.setCellWidget(row, 3, cell_ana)

            # Col 4: Coverage DualModeCell
            cell_cov = BatchDualModeCell(tr_ui("analysis.loading", "Laden..."))
            self.table_batch.setCellWidget(row, 4, cell_cov)

            # Col 5: Per-Repo Task Progress Bar
            pb_container = QWidget()
            pb_container.setStyleSheet("background: transparent;")
            h_pb = QHBoxLayout(pb_container)
            h_pb.setContentsMargins(scale(6), scale(3), scale(10), scale(3))
            pb = QProgressBar()
            pb.setFixedHeight(scale(20))
            pb.setRange(0, total_tasks)
            pb.setValue(0)
            pb.setTextVisible(True)
            pb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pb.setFormat(f"0/{total_tasks} {tr_ui('repo_settings.progress_done', 'erledigt')}")
            h_pb.addWidget(pb)
            pb_container.progress_bar = pb
            self.table_batch.setCellWidget(row, 5, pb_container)

        self._update_batch_selection_count()

    def _start_batch_stats_worker(self):
        worker_data = []
        for r_name, row in self._batch_name_to_row.items():
            worker_data.append({'row': row, 'name': r_name})
        if not worker_data:
            return
        if self.stats_worker and self.stats_worker.isRunning():
            try:
                self.stats_worker.disconnect()
                self.stats_worker.stop()
                self.stats_worker.wait(200)
            except Exception:
                pass

        self.stats_worker = RepertoireStatsWorker(worker_data)

        def _on_stats(row, status, cov, elo):
            if sip.isdeleted(self) or row >= self.table_batch.rowCount():
                return
            cell_a = self._get_batch_dual_cell(row, 3)
            if cell_a and cell_a.progress_bar.isHidden():
                status_str = str(status)
                cell_a.show_text(status_str, f"{tr_ui('repo_settings.col_analysis', 'Analyse')}: {status_str}")
            cell_c = self._get_batch_dual_cell(row, 4)
            if cell_c and cell_c.progress_bar.isHidden():
                cov_str = f"{cov:.1f}%"
                cell_c.show_text(cov_str, f"Coverage: {cov_str}")

        self.stats_worker.stats_ready.connect(_on_stats)
        self.stats_worker.start()

    def _get_batch_row_checkbox(self, row: int) -> Optional[QCheckBox]:
        w = self.table_batch.cellWidget(row, 0)
        if hasattr(w, "checkbox"):
            return w.checkbox
        if w:
            return w.findChild(QCheckBox)
        return None

    def _get_batch_dual_cell(self, row: int, col: int) -> Optional[BatchDualModeCell]:
        w = self.table_batch.cellWidget(row, col)
        if isinstance(w, BatchDualModeCell):
            return w
        return None

    def _get_batch_row_progressbar(self, row: int) -> Optional[QProgressBar]:
        w = self.table_batch.cellWidget(row, 5)
        if hasattr(w, "progress_bar"):
            return w.progress_bar
        return None

    def _get_selected_batch_task_count(self) -> int:
        return sum([
            self.chk_b_eng.isChecked(),
            self.chk_b_transpos.isChecked(),
            self.chk_b_lich.isChecked(),
            self.chk_b_cleanup.isChecked(),
            self.chk_b_stats.isChecked()
        ]) or 1

    def _update_idle_batch_progress_format(self):
        curr = self.tm.get_current_job()
        if curr and curr.job_type == JobType.BATCH_MAINTENANCE and curr.status == JobStatus.RUNNING:
            return
        total_tasks = self._get_selected_batch_task_count()
        if not hasattr(self, 'table_batch'):
            return
        for r in range(self.table_batch.rowCount()):
            pb = self._get_batch_row_progressbar(r)
            if pb and pb.value() == 0:
                pb.setRange(0, total_tasks)
                pb.setFormat(f"0/{total_tasks} {tr_ui('repo_settings.progress_done', 'erledigt')}")

    def _update_batch_selection_count(self):
        if not hasattr(self, 'table_batch') or not hasattr(self, 'lbl_b_repo_count'):
            return
        total = self.table_batch.rowCount()
        selected = 0
        for r in range(total):
            cb = self._get_batch_row_checkbox(r)
            if cb and cb.isChecked():
                selected += 1
        self.lbl_b_repo_count.setText(
            tr_ui("task_center.batch_selected_count", "Ausgewählt: {sel} von {tot} Repertoires", sel=selected, tot=total)
        )

    def _set_all_batch_checked(self, checked: bool):
        for r in range(self.table_batch.rowCount()):
            cb = self._get_batch_row_checkbox(r)
            if cb:
                cb.setChecked(checked)
        self._update_batch_selection_count()

    # ─── TAB 3: QUEUE & HISTORY (WITH DUAL PARALLEL STREAM BARS) ────────────

    def _init_tab_queue(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(scale(16), scale(14), scale(16), scale(14))
        layout.setSpacing(scale(10))

        # Current Job Box
        self.box_current = QGroupBox(tr_ui("task_center.curr_job_title", "Aktuell laufende Aufgabe"))
        l_curr = QVBoxLayout(self.box_current)
        l_curr.setSpacing(scale(8))

        self.lbl_curr_title = QLabel(tr_ui("task_center.no_active_job", "Keine aktive Aufgabe"))
        self.lbl_curr_title.setStyleSheet("font-weight: bold; color: #0f172a; font-size: 14px;")
        l_curr.addWidget(self.lbl_curr_title)

        self.lbl_curr_status = QLabel(tr_ui("task_center.waiting_for_start", "Warte auf Start..."))
        self.lbl_curr_status.setStyleSheet("color: #64748b; font-size: 12px;")
        l_curr.addWidget(self.lbl_curr_status)

        self.pb_curr = QProgressBar()
        self.pb_curr.setRange(0, 100)
        self.pb_curr.setValue(0)
        self.pb_curr.setFixedHeight(scale(18))
        l_curr.addWidget(self.pb_curr)

        # Dual Parallel Stream Progress Box (shown when Lichess & Engine run in parallel)
        self.parallel_streams_frame = QFrame()
        self.parallel_streams_frame.setObjectName("SubCard")
        v_streams = QVBoxLayout(self.parallel_streams_frame)
        v_streams.setContentsMargins(scale(10), scale(8), scale(10), scale(8))
        v_streams.setSpacing(scale(6))

        h_st_lich = QHBoxLayout()
        lbl_st_lich_icon = QLabel("🌐 Lichess:")
        lbl_st_lich_icon.setFixedWidth(scale(85))
        lbl_st_lich_icon.setStyleSheet("font-weight: 600; font-size: 12px; color: #0284c7;")
        self.pb_curr_lich = QProgressBar()
        self.pb_curr_lich.setRange(0, 100)
        self.pb_curr_lich.setValue(0)
        self.pb_curr_lich.setFixedHeight(scale(16))
        self.lbl_curr_lich_st = QLabel("-")
        self.lbl_curr_lich_st.setMinimumWidth(scale(180))
        self.lbl_curr_lich_st.setStyleSheet("font-size: 11px; color: #475569;")
        h_st_lich.addWidget(lbl_st_lich_icon)
        h_st_lich.addWidget(self.pb_curr_lich, 1)
        h_st_lich.addWidget(self.lbl_curr_lich_st)
        v_streams.addLayout(h_st_lich)

        h_st_eng = QHBoxLayout()
        lbl_st_eng_icon = QLabel("🤖 Engine:")
        lbl_st_eng_icon.setFixedWidth(scale(85))
        lbl_st_eng_icon.setStyleSheet("font-weight: 600; font-size: 12px; color: #2563eb;")
        self.pb_curr_eng = QProgressBar()
        self.pb_curr_eng.setRange(0, 100)
        self.pb_curr_eng.setValue(0)
        self.pb_curr_eng.setFixedHeight(scale(16))
        self.lbl_curr_eng_st = QLabel("-")
        self.lbl_curr_eng_st.setMinimumWidth(scale(180))
        self.lbl_curr_eng_st.setStyleSheet("font-size: 11px; color: #475569;")
        h_st_eng.addWidget(lbl_st_eng_icon)
        h_st_eng.addWidget(self.pb_curr_eng, 1)
        h_st_eng.addWidget(self.lbl_curr_eng_st)
        v_streams.addLayout(h_st_eng)

        self.parallel_streams_frame.hide()
        l_curr.addWidget(self.parallel_streams_frame)

        h_curr_btns = QHBoxLayout()
        h_curr_btns.addStretch()
        self.btn_cancel_curr = QPushButton(tr_ui("task_center.btn_cancel", "🛑 Abbrechen"))
        self.btn_cancel_curr.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_cancel_curr.setFixedHeight(scale(30))
        self.btn_cancel_curr.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
            QPushButton:disabled {
                background-color: #e2e8f0;
                color: #94a3b8;
            }
        """)
        self.btn_cancel_curr.clicked.connect(self.tm.cancel_current)
        self.btn_cancel_curr.setEnabled(False)
        h_curr_btns.addWidget(self.btn_cancel_curr)
        l_curr.addLayout(h_curr_btns)
        layout.addWidget(self.box_current)

        # Queue & History List
        lbl_q = QLabel(tr_ui("task_center.queue_title", "Warteschlange & Verlauf:"))
        lbl_q.setStyleSheet("font-weight: bold; color: #0f172a; font-size: 13px;")
        layout.addWidget(lbl_q)

        self.table_queue = QTableWidget()
        self.table_queue.setColumnCount(3)
        self.table_queue.setHorizontalHeaderLabels([
            tr_ui("task_center.col_repertoire", "Repertoire"),
            tr_ui("task_center.col_task", "Aufgabe"),
            tr_ui("task_center.col_status", "Status")
        ])
        self.table_queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_queue.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_queue.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_queue.verticalHeader().setVisible(False)
        self.table_queue.verticalHeader().setDefaultSectionSize(scale(34))
        self.table_queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table_queue, 1)

        # Clear queue button
        h_q_act = QHBoxLayout()
        h_q_act.addStretch()
        btn_clear = QPushButton(tr_ui("task_center.btn_clear_queue", "Warteschlange leeren"))
        btn_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_clear.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 14px; font-weight: 500;")
        btn_clear.clicked.connect(self.tm.clear_queue)
        h_q_act.addWidget(btn_clear)
        layout.addLayout(h_q_act)

    def _on_repo_selection_changed(self, repo_name: str):
        if not repo_name or not hasattr(self, 'combo_elo'):
            return
        self.active_repo_name = repo_name
        elo_key = get_repertoire_elo(repo_name)
        idx = self.combo_elo.findData(elo_key)
        if idx >= 0:
            self.combo_elo.blockSignals(True)
            self.combo_elo.setCurrentIndex(idx)
            self.combo_elo.blockSignals(False)
        self._update_single_tab_for_current_job()

    def set_active_repertoire(self, repo_name: str):
        if not repo_name:
            return
        self.active_repo_name = repo_name
        if hasattr(self, 'combo_repo') and self.combo_repo:
            idx = self.combo_repo.findText(repo_name)
            if idx >= 0:
                self.combo_repo.blockSignals(True)
                self.combo_repo.setCurrentIndex(idx)
                self.combo_repo.blockSignals(False)
            else:
                self.combo_repo.addItem(repo_name)
                self.combo_repo.setCurrentText(repo_name)
        self._on_repo_selection_changed(repo_name)

    # ─── ACTIONS ────────────────────────────────────────────────────────────

    def _on_start_single_lichess(self):
        curr = self.tm.get_current_job()
        if curr and curr.job_type == JobType.LICHESS and curr.status == JobStatus.RUNNING and curr.repo_name == self.combo_repo.currentText():
            self.tm.cancel_current()
            return

        repo = self.combo_repo.currentText()
        if not repo:
            QMessageBox.warning(self, tr_ui("task_center.msg_hint", "Hinweis"), tr_ui("task_center.msg_select_repo", "Bitte wähle ein Repertoire aus."))
            return

        from opening_fenix.gui.dialogs.lichess_token_dialog import prompt_lichess_token_if_missing
        proceed, _ = prompt_lichess_token_if_missing(self, self.config)
        if not proceed:
            return

        elo = self.combo_elo.currentData()
        max_age = self.combo_max_age.currentData()
        reuse = self.chk_lich_reuse.isChecked()

        self.pb_single_lich.setValue(0)
        self.lbl_single_lich_status.setText(tr_ui("task_center.job_started", "Gestartet..."))
        job = LichessJob(repo, elo, reuse_other_courses=reuse, max_data_age_days=max_age)
        self.tm.enqueue(job)

    def _on_start_single_engine(self):
        curr = self.tm.get_current_job()
        if curr and curr.job_type == JobType.ENGINE_SCAN and curr.status == JobStatus.RUNNING and curr.repo_name == self.combo_repo.currentText():
            self.tm.cancel_current()
            return

        repo = self.combo_repo.currentText()
        if not repo:
            QMessageBox.warning(self, tr_ui("task_center.msg_hint", "Hinweis"), tr_ui("task_center.msg_select_repo", "Bitte wähle ein Repertoire aus."))
            return

        from opening_fenix.gui.dialogs.engine_setup_dialog import prompt_engine_if_missing
        ep = prompt_engine_if_missing(self, self.config)
        if not ep:
            return

        depth = self.spin_depth.value()
        threads = int(self.combo_threads.currentText())
        reuse = self.chk_eng_reuse.isChecked()

        self.pb_single_eng.setValue(0)
        self.lbl_single_eng_status.setText(tr_ui("task_center.job_started", "Gestartet..."))
        job = EngineScanJob(repo, depth, threads, ep, reuse_other_courses=reuse)
        self.tm.enqueue(job)

    def _on_start_combined(self):
        curr = self.tm.get_current_job()
        if curr and curr.job_type == JobType.COMBINED and curr.status == JobStatus.RUNNING and curr.repo_name == self.combo_repo.currentText():
            self.tm.cancel_current()
            return

        repo = self.combo_repo.currentText()
        if not repo:
            QMessageBox.warning(self, tr_ui("task_center.msg_hint", "Hinweis"), tr_ui("task_center.msg_select_repo", "Bitte wähle ein Repertoire aus."))
            return

        from opening_fenix.gui.dialogs.lichess_token_dialog import prompt_lichess_token_if_missing
        proceed, _ = prompt_lichess_token_if_missing(self, self.config)
        if not proceed:
            return

        from opening_fenix.gui.dialogs.engine_setup_dialog import prompt_engine_if_missing
        ep = prompt_engine_if_missing(self, self.config)
        if not ep:
            return

        elo = self.combo_elo.currentData()
        max_age = self.combo_max_age.currentData()
        depth = self.spin_depth.value()
        threads = int(self.combo_threads.currentText())
        reuse_lich = self.chk_lich_reuse.isChecked()
        reuse_eng = self.chk_eng_reuse.isChecked()

        self.pb_single_lich.setValue(0)
        self.pb_single_eng.setValue(0)
        self.lbl_single_lich_status.setText(tr_ui("task_center.job_started", "Gestartet..."))
        self.lbl_single_eng_status.setText(tr_ui("task_center.job_started", "Gestartet..."))
        job = CombinedSyncJob(repo, elo, depth, threads, ep, reuse_other_courses=(reuse_lich and reuse_eng), max_data_age_days=max_age)
        self.tm.enqueue(job)

    def _on_start_batch(self):
        curr = self.tm.get_current_job()
        if curr and curr.job_type == JobType.BATCH_MAINTENANCE and curr.status == JobStatus.RUNNING:
            self.lbl_batch_overall.setText(tr_ui("repo_settings.stopping_maintenance", "Wartung wird gestoppt..."))
            self.btn_run_batch.setEnabled(False)
            self.tm.cancel_current()
            return

        selected_repos = []
        for r in range(self.table_batch.rowCount()):
            cb = self._get_batch_row_checkbox(r)
            if cb and cb.isChecked():
                item = self.table_batch.item(r, 1)
                r_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
                selected_repos.append(r_name)

        if not selected_repos:
            QMessageBox.information(self, tr_ui("task_center.msg_info", "Info"), tr_ui("task_center.msg_no_batch_repos", "Bitte wähle mindestens ein Repertoire für den Wartungs-Batch aus."))
            return

        tasks = {
            'engine': self.chk_b_eng.isChecked(),
            'transpositions': self.chk_b_transpos.isChecked(),
            'lichess': self.chk_b_lich.isChecked(),
            'cleanup': self.chk_b_cleanup.isChecked(),
            'stats': self.chk_b_stats.isChecked(),
            'lichess_reuse_courses': self.chk_batch_reuse.isChecked() if self.chk_b_lich.isChecked() else False,
            'lichess_max_age_days': self.combo_batch_max_age.currentData() if self.chk_b_lich.isChecked() else 180
        }

        active_tasks = [t for t in ['cleanup', 'lichess', 'stats', 'engine', 'transpositions'] if tasks.get(t)]
        if not active_tasks:
            QMessageBox.warning(self, tr_ui("task_center.msg_hint", "Hinweis"), tr_ui("task_center.msg_select_task", "Bitte wähle mindestens eine Aufgabe aus."))
            return

        if tasks['lichess']:
            from opening_fenix.gui.dialogs.lichess_token_dialog import prompt_lichess_token_if_missing
            proceed, _ = prompt_lichess_token_if_missing(self, self.config)
            if not proceed:
                return

        ep = None
        if tasks['engine'] or tasks['transpositions']:
            from opening_fenix.gui.dialogs.engine_setup_dialog import prompt_engine_if_missing
            ep = prompt_engine_if_missing(self, self.config)
            if not ep:
                return

        if self.stats_worker and self.stats_worker.isRunning():
            try:
                self.stats_worker.disconnect()
                self.stats_worker.stop()
                self.stats_worker.wait(200)
            except Exception:
                pass

        repo_configs = []
        for name in selected_repos:
            repo_configs.append({"name": name, "elo": get_repertoire_elo(name)})

        eng_settings = {
            "path": ep or "",
            "depth": self.spin_b_engine_depth.value(),
            "transpos_depth": self.spin_b_transpos_depth.value(),
            "threads": int(self.combo_b_threads.currentData() or self.combo_b_threads.currentText().split()[0])
        }

        # Prepare table rows for live batch tracking
        total_tasks_count = len(active_tasks)
        selected_set = set(selected_repos)
        for r in range(self.table_batch.rowCount()):
            item = self.table_batch.item(r, 1)
            r_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
            pb = self._get_batch_row_progressbar(r)
            if r_name in selected_set:
                if pb:
                    pb.setProperty("class", "")
                    pb.style().unpolish(pb)
                    pb.style().polish(pb)
                    pb.setRange(0, total_tasks_count)
                    pb.setValue(0)
                    pb.setFormat(f"0/{total_tasks_count} {tr_ui('repo_settings.progress_done', 'erledigt')}")
            else:
                if pb:
                    pb.setValue(0)
                    pb.setFormat("-")

        self.pb_batch_overall.setValue(0)
        self.lbl_batch_overall.setText(f"Starte Wartung für {len(selected_repos)} Repertoires...")
        job = BatchMaintenanceJob(repo_configs, tasks, eng_settings)
        self.tm.enqueue(job)

    # ─── REAL-TIME SYNC ─────────────────────────────────────────────────────

    def _connect_signals(self):
        self.tm.task_started.connect(self._on_task_started)
        self.tm.task_progress.connect(self._on_task_progress)
        self.tm.sub_progress.connect(self._on_sub_progress)
        self.tm.batch_repo_status.connect(self._on_batch_repo_status)
        self.tm.batch_overall_progress.connect(self._on_batch_overall_progress)
        self.tm.task_finished.connect(self._on_task_finished)
        self.tm.queue_updated.connect(self._refresh_queue_display)
        self.tm.all_completed.connect(self._on_all_completed)

    def _sync_running_state_to_ui(self):
        """Restores live progress bars and batch table cells if TaskCenterDialog is opened while a job is running."""
        curr = self.tm.get_current_job()
        if not curr or curr.status != JobStatus.RUNNING:
            return
        self._on_task_started(curr)
        if curr.job_type == JobType.BATCH_MAINTENANCE and hasattr(curr, 'repo_task_status'):
            for r_name, t_map in curr.repo_task_status.items():
                for t_type, (pct, st) in t_map.items():
                    if pct > 0 or st != "Wartend":
                        self._on_batch_repo_status(curr, r_name, t_type, pct, st)

    def _update_single_tab_for_current_job(self):
        if not hasattr(self, "btn_start_lich") or not hasattr(self, "btn_start_eng") or not hasattr(self, "btn_start_comb"):
            return
        curr = self.tm.get_current_job()
        selected_repo = self.combo_repo.currentText() if hasattr(self, 'combo_repo') else ""

        # Reset buttons to default state first
        self.btn_start_lich.setText(tr_ui("task_center.btn_start_lich", "🌐 Lichess-Import starten").replace("&", "&&").replace("&&&&", "&&"))
        self._style_single_btn(self.btn_start_lich, "#0284c7", "#0369a1")

        self.btn_start_eng.setText(tr_ui("task_center.btn_start_eng", "🤖 Engine-Scan starten"))
        self._style_single_btn(self.btn_start_eng, "#2563eb", "#1d4ed8")

        self.btn_start_comb.setText(tr_ui("task_center.btn_start_comb", "⚡ Vollständiges Update starten"))
        self._style_single_btn(self.btn_start_comb, "#16a34a", "#15803d")

        if not curr or curr.status != JobStatus.RUNNING or curr.repo_name != selected_repo:
            return

        if curr.job_type == JobType.LICHESS:
            self.btn_start_lich.setText(tr_ui("repo_settings.btn_stop_fetch", "🛑 Import stoppen"))
            self._style_single_btn(self.btn_start_lich, "#ef4444", "#dc2626")
            self.pb_single_lich.setValue(getattr(curr, 'lichess_pct', curr.progress))
            self.lbl_single_lich_status.setText(getattr(curr, 'lichess_status', curr.status_message) or "...")
        elif curr.job_type == JobType.ENGINE_SCAN:
            self.btn_start_eng.setText(tr_ui("repo_settings.btn_stop_scan", "🛑 Engine-Scan stoppen"))
            self._style_single_btn(self.btn_start_eng, "#ef4444", "#dc2626")
            self.pb_single_eng.setValue(getattr(curr, 'engine_pct', curr.progress))
            self.lbl_single_eng_status.setText(getattr(curr, 'engine_status', curr.status_message) or "...")
        elif curr.job_type == JobType.COMBINED:
            self.btn_start_comb.setText(tr_ui("task_center.btn_cancel", "🛑 Abbrechen"))
            self._style_single_btn(self.btn_start_comb, "#ef4444", "#dc2626")
            self.pb_single_lich.setValue(getattr(curr, 'lichess_pct', 0))
            self.lbl_single_lich_status.setText(getattr(curr, 'lichess_status', "") or "...")
            self.pb_single_eng.setValue(getattr(curr, 'engine_pct', 0))
            self.lbl_single_eng_status.setText(getattr(curr, 'engine_status', "") or "...")

    def _on_task_started(self, job):
        if sip.isdeleted(self):
            return
        self._update_pill_badge("running", tr_ui("task_center.status_active", "Aktiv: {title}", title=job.title))
        self.lbl_curr_title.setText(f"{job.title}")
        self.lbl_curr_status.setText(job.status_message)
        self.pb_curr.setValue(job.progress)
        self.btn_cancel_curr.setEnabled(True)

        is_parallel = job.job_type in (JobType.COMBINED, JobType.BATCH_MAINTENANCE)
        self.parallel_streams_frame.setVisible(is_parallel)
        if is_parallel:
            self.pb_curr_lich.setValue(getattr(job, 'lichess_pct', 0))
            self.lbl_curr_lich_st.setText(getattr(job, 'lichess_status', "-") or "-")
            self.pb_curr_eng.setValue(getattr(job, 'engine_pct', 0))
            self.lbl_curr_eng_st.setText(getattr(job, 'engine_status', "-") or "-")

        if job.job_type == JobType.BATCH_MAINTENANCE:
            self.btn_run_batch.setEnabled(True)
            self.btn_run_batch.setText(tr_ui("repo_settings.btn_stop_batch_run", "🛑 Wartungs-Batch stoppen"))
            self._style_single_btn(self.btn_run_batch, "#ef4444", "#dc2626")
            self.pb_batch_overall.setValue(job.progress)

        self._update_single_tab_for_current_job()
        self._refresh_queue_display()

    def _on_task_progress(self, job, pct, status_text):
        if sip.isdeleted(self):
            return
        self.pb_curr.setValue(pct)
        self.lbl_curr_status.setText(status_text)
        if job.job_type == JobType.BATCH_MAINTENANCE:
            self.pb_batch_overall.setValue(pct)
            self.lbl_batch_overall.setText(status_text)

    def _on_sub_progress(self, job, stream_key: str, pct: int, status_text: str):
        if sip.isdeleted(self):
            return
        # Update Tab 3 Dual Stream bars
        if stream_key == "lichess":
            self.pb_curr_lich.setValue(pct)
            self.lbl_curr_lich_st.setText(status_text or f"{pct}%")
        elif stream_key == "engine":
            self.pb_curr_eng.setValue(pct)
            self.lbl_curr_eng_st.setText(status_text or f"{pct}%")

        # Update Tab 1 Single Repertoire bars if matching repo
        if hasattr(self, 'combo_repo') and job.repo_name == self.combo_repo.currentText():
            if stream_key == "lichess":
                self.pb_single_lich.setValue(pct)
                self.lbl_single_lich_status.setText(status_text or f"{pct}%")
            elif stream_key == "engine":
                self.pb_single_eng.setValue(pct)
                self.lbl_single_eng_status.setText(status_text or f"{pct}%")

    def _on_batch_overall_progress(self, job, completed_count: int, total_count: int, last_name: str):
        if sip.isdeleted(self):
            return
        self.lbl_batch_overall.setText(
            f"Gesamtfortschritt ({completed_count}/{total_count} Repertoires fertig) — Zuletzt: {last_name} ✓"
        )

    def _on_batch_repo_status(self, job, name: str, task_type: str, pct: int, status_text: str):
        if sip.isdeleted(self):
            return
        row = self._batch_name_to_row.get(name)
        if row is None or row >= self.table_batch.rowCount():
            return

        depth = job.engine_settings.get("depth", 18) if hasattr(job, "engine_settings") else 18
        transpos_depth = job.engine_settings.get("transpos_depth", 25) if hasattr(job, "engine_settings") else 25
        active_tasks = getattr(job, "active_tasks", ['cleanup', 'lichess', 'stats', 'engine'])
        total_tasks_count = max(1, len(active_tasks))
        completed_set = getattr(job, "completed_tasks", {}).get(name, set())
        task_status_map = getattr(job, "repo_task_status", {}).get(name, {})

        # 1. Col 3: Engine / Transpositions
        if task_type == "engine":
            cell_a = self._get_batch_dual_cell(row, 3)
            if cell_a:
                if pct < 100:
                    fmt = f"{pct}% ({status_text})" if status_text and status_text != "Analysiere..." else f"{pct}%"
                    cell_a.show_progress(pct, f"Engine-Analyse: {pct}% ({status_text})", format_str=fmt)
                else:
                    if status_text == "Fehlgeschlagen":
                        cell_a.show_text("Fehler ⚠️", "Engine-Analyse fehlgeschlagen")
                    else:
                        depth_str = tr_ui("analysis.depth", "Tiefe: {depth}", depth=depth)
                        cell_a.show_text(f"{depth_str} ✓", f"Engine-Analyse abgeschlossen ({depth_str})")
        elif task_type == "transpositions":
            cell_a = self._get_batch_dual_cell(row, 3)
            if cell_a:
                if pct < 100:
                    fmt = f"{pct}% ({status_text})" if status_text and status_text != "Überleitungen..." else f"{pct}%"
                    cell_a.show_progress(pct, f"Überleitungen: {pct}% ({status_text})", format_str=fmt)
                elif "engine" not in active_tasks:
                    depth_str = tr_ui("analysis.depth", "Tiefe: {depth}", depth=transpos_depth)
                    cell_a.show_text(f"{depth_str} ✓", f"Überleitungen abgeschlossen ({depth_str})")

        # 2. Col 4: Lichess Coverage
        if task_type == "lichess":
            cell_c = self._get_batch_dual_cell(row, 4)
            if cell_c:
                if pct < 100:
                    fmt = f"{pct}% ({status_text})" if status_text and not status_text.endswith("%") else f"{pct}%"
                    cell_c.show_progress(pct, f"Lichess-Import: {status_text} ({pct}%)", format_str=fmt)
                else:
                    if status_text == "Fehlgeschlagen":
                        cell_c.show_text("Fehler ⚠️", "Lichess-Import fehlgeschlagen")
                    else:
                        try:
                            from opening_fenix.core.db.database import DatabaseManager
                            from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_info
                            db_path = get_repertoire_db_path(name)
                            db_m = DatabaseManager(db_path)
                            s = db_m.get_session()
                            info = fetch_repertoire_info(s, name, fast_only=False)
                            s.close()
                            db_m.close()
                            actual_cov = info.get("coverage_pct", 0.0)
                            cell_c.show_text(f"{actual_cov:.1f}% ✓", f"Lichess-Import abgeschlossen (Coverage: {actual_cov:.1f}%)")
                        except Exception:
                            cell_c.show_text("Fertig ✓", "Lichess-Import abgeschlossen")

        # 3. Col 5: Per-Repo Task Progress Bar + Rich Tooltip
        done_count = len(completed_set)
        pb = self._get_batch_row_progressbar(row)
        if pb:
            pb.setRange(0, total_tasks_count)
            pb.setValue(done_count)
            if done_count >= total_tasks_count:
                pb.setFormat(f"{total_tasks_count}/{total_tasks_count} Fertig ✓")
                pb.setProperty("class", "SuccessBar")
                pb.style().unpolish(pb)
                pb.style().polish(pb)
            else:
                pb.setFormat(f"{done_count}/{total_tasks_count} {tr_ui('repo_settings.progress_done', 'erledigt')}")

            task_labels = {
                'cleanup': ('🧹', tr_ui("repo_settings.task_lbl_cleanup", "Bereinigung")),
                'lichess': ('🌐', tr_ui("repo_settings.task_lbl_lichess", "Lichess-Import")),
                'engine': ('🤖', tr_ui("repo_settings.task_lbl_engine", "Engine-Analyse")),
                'stats': ('📊', tr_ui("repo_settings.task_lbl_stats", "Statistiken & Prio")),
                'transpositions': ('🔄', tr_ui("repo_settings.task_lbl_transpos", "Überleitungen (2-Züge)"))
            }
            tooltip_lines = [f"<b>{name} ({done_count}/{total_tasks_count}):</b>"]
            for t in active_tasks:
                t_icon, t_name = task_labels.get(t, ('•', t))
                t_pct, t_st = task_status_map.get(t, (0, "Wartend"))
                if t in completed_set:
                    badge = "✓ Fertig"
                elif t_pct > 0 or t == task_type:
                    badge = f"▶ {t_pct}% ({t_st})"
                else:
                    badge = "⏳ Ausstehend"
                tooltip_lines.append(f"• {t_icon} {t_name}: <b>{badge}</b>")
            pb.setToolTip("<br>".join(tooltip_lines))

    def _on_task_finished(self, job, success, message):
        if sip.isdeleted(self):
            return
        if hasattr(self, 'combo_repo') and job.repo_name == self.combo_repo.currentText():
            if job.job_type in (JobType.LICHESS, JobType.COMBINED):
                if success:
                    self.pb_single_lich.setValue(100)
                self.lbl_single_lich_status.setText(message if job.job_type == JobType.LICHESS else tr_ui("task_center.indicator_finished", "Fertig!"))
            if job.job_type in (JobType.ENGINE_SCAN, JobType.COMBINED):
                if success:
                    self.pb_single_eng.setValue(100)
                self.lbl_single_eng_status.setText(message if job.job_type == JobType.ENGINE_SCAN else tr_ui("task_center.indicator_finished", "Fertig!"))

        if job.job_type == JobType.BATCH_MAINTENANCE:
            self.btn_run_batch.setEnabled(True)
            self.btn_run_batch.setText(tr_ui("repo_settings.btn_start_batch_run", "🚀 Wartungs-Batch starten"))
            self._style_single_btn(self.btn_run_batch, "#7c3aed", "#6d28d9")
            if success:
                self.pb_batch_overall.setValue(100)
                self.lbl_batch_overall.setText(f"{tr_ui('repo_settings.status_done', 'Fertig')}: {message}")
            else:
                self.lbl_batch_overall.setText(f"{tr_ui('repo_settings.status_aborted', 'Abgebrochen')}: {message}")
                self._start_batch_stats_worker()

        self._update_single_tab_for_current_job()
        self._refresh_queue_display()

    def _on_all_completed(self):
        if sip.isdeleted(self):
            return
        self._update_pill_badge("idle", tr_ui("task_center.status_idle", "Bereit"))
        self.lbl_curr_title.setText(tr_ui("task_center.no_active_job", "Keine aktive Aufgabe"))
        self.lbl_curr_status.setText(tr_ui("task_center.all_tasks_completed", "Alle Aufgaben abgeschlossen."))
        self.pb_curr.setValue(100)
        self.btn_cancel_curr.setEnabled(False)
        self.parallel_streams_frame.hide()
        self._update_single_tab_for_current_job()
        self._refresh_queue_display()

    def _refresh_queue_display(self):
        if sip.isdeleted(self):
            return
        curr = self.tm.get_current_job()
        if curr and curr.status == JobStatus.RUNNING:
            self._update_pill_badge("running", tr_ui("task_center.status_active", "Aktiv: {title}", title=curr.title))
            self.lbl_curr_title.setText(f"{curr.title}")
            self.lbl_curr_status.setText(curr.status_message)
            self.pb_curr.setValue(curr.progress)
            self.btn_cancel_curr.setEnabled(True)
            is_parallel = curr.job_type in (JobType.COMBINED, JobType.BATCH_MAINTENANCE)
            self.parallel_streams_frame.setVisible(is_parallel)
        else:
            self._update_pill_badge("idle", tr_ui("task_center.status_idle", "Bereit"))
            self.lbl_curr_title.setText(tr_ui("task_center.no_active_job", "Keine aktive Aufgabe"))
            self.lbl_curr_status.setText(tr_ui("task_center.waiting_for_start", "Warte auf Start..."))
            self.pb_curr.setValue(0)
            self.btn_cancel_curr.setEnabled(False)
            self.parallel_streams_frame.hide()

        q = self.tm.get_queue()
        hist = list(reversed(self.tm.get_history()))
        combined_rows = list(q) + hist

        self.table_queue.setRowCount(len(combined_rows))
        for row, job in enumerate(combined_rows):
            self.table_queue.setItem(row, 0, QTableWidgetItem(job.repo_name))
            self.table_queue.setItem(row, 1, QTableWidgetItem(job.title))
            st_label = job.status.value
            if job.status == JobStatus.COMPLETED:
                st_label = f"✅ {job.status_message or job.status.value}"
            elif job.status == JobStatus.CANCELED:
                st_label = f"⏹ {job.status_message or job.status.value}"
            elif job.status == JobStatus.FAILED:
                st_label = f"❌ {job.status_message or job.status.value}"
            elif job.status == JobStatus.QUEUED:
                st_label = f"⏳ {tr_ui('task_center.job_queued', 'In Warteschlange...')}"
            self.table_queue.setItem(row, 2, QTableWidgetItem(st_label))

    def closeEvent(self, event):
        if self.stats_worker and self.stats_worker.isRunning():
            try:
                self.stats_worker.disconnect()
                self.stats_worker.stop()
                self.stats_worker.wait(200)
            except Exception:
                pass
        super().closeEvent(event)
