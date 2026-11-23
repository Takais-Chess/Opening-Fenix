import sys
import os
from PyQt6 import sip
import json
import chess
import chess.pgn
import webbrowser
import math
import time
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, 
    QVBoxLayout, QLabel, QTextBrowser, QPushButton,
    QCheckBox, QMessageBox, QInputDialog, QDialog, 
    QScrollArea, QTabWidget, QFormLayout,
    QLineEdit, QFileDialog, QListWidget, QProgressBar, 
    QComboBox, QSpinBox, QGroupBox, QFrame, QButtonGroup,
    QGridLayout, QListWidgetItem, QSlider, QScroller, QScrollerProperties, QMenu, QSizePolicy, QSplitter,
    QTabBar, QStackedWidget, QGraphicsDropShadowEffect
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPolygonF, QIcon, QPixmap, QFontMetrics, QAction, QTextCursor
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QPoint, QTimer, QUrl, QPointF, QEvent, QSize, QThread
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtMultimedia import QSoundEffect

from opening_fenix.core.repertoire import RepertoireManager
from opening_fenix.core.training import TrainingManager
from opening_fenix.core.utils import get_base_path, get_user_dir, localize_san, parse_comment, is_free_training_profile
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget
from opening_fenix.gui.widgets.charts import PieChartWidget
from opening_fenix.gui.widgets.common import ZoomableTextBrowser, AspectRatioFrame
from opening_fenix.gui.widgets.tour_overlay import GuidedTourOverlay

# Lazy-loaded dialog/window classes (CreatorWindow kept at module level for test monkeypatching)
CreatorWindow = None

# Import centralized styles
from opening_fenix.gui.styles import get_main_window_style, COLORS, set_consistent_icon, get_settings_gear_icon

from opening_fenix.gui.widgets.title_bar import CustomTitleBar
from opening_fenix.gui.scaling import scale
from opening_fenix.core.services.update_service import get_config_dict
from opening_fenix.core.logger import logger
from opening_fenix.core.db.database import DatabaseCorruptedException
from opening_fenix.core.version import APP_VERSION
from opening_fenix.core.translation import tr_ui

import array
import queue
import tempfile
import wave

if sys.platform == "win32":
    try:
        import winsound
    except ImportError:
        winsound = None
else:
    winsound = None

_WIN_SOUND_QUEUE: "queue.SimpleQueue[str | None]" = queue.SimpleQueue()
_WIN_SOUND_WORKER_STARTED = False
_WIN_SOUND_LOCK = threading.Lock()


def _ensure_win_sound_worker():
    global _WIN_SOUND_WORKER_STARTED
    if _WIN_SOUND_WORKER_STARTED or winsound is None:
        return
    with _WIN_SOUND_LOCK:
        if _WIN_SOUND_WORKER_STARTED:
            return
        _WIN_SOUND_WORKER_STARTED = True

        def _worker():
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
            while True:
                wav_path = _WIN_SOUND_QUEUE.get()
                if wav_path is None:
                    break
                try:
                    winsound.PlaySound(
                        wav_path,
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                    )
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True, name="OpeningFenixAudioWorker").start()


class _WinAsyncSoundEffect:
    """
    Zero-latency asynchronous Windows sound effect wrapper using a dedicated background
    WinMM thread and cached volume-scaled PCM WAV files.
    Eliminates the 35-65ms Qt6 WASAPI QSoundEffect.play() main-thread freeze between moves.
    """
    _scaled_file_cache: dict[tuple[str, int], str] = {}

    def __init__(self, name: str, source_path: str, volume: float = 1.0):
        self.name = name
        self.source_path = source_path
        self._volume = 1.0
        self._active_path = source_path
        _ensure_win_sound_worker()
        self.setVolume(volume)

    def volume(self) -> float:
        return self._volume

    def setVolume(self, vol: float) -> None:
        self._volume = max(0.0, min(1.0, float(vol)))
        vol_pct = int(round(self._volume * 100))
        if vol_pct <= 0:
            self._active_path = ""
            return
        if vol_pct >= 99:
            self._active_path = self.source_path
            return
        key = (self.source_path, vol_pct)
        cached = self._scaled_file_cache.get(key)
        if cached and os.path.exists(cached):
            self._active_path = cached
            return
        try:
            cache_dir = os.path.join(tempfile.gettempdir(), "opening_fenix_sounds")
            os.makedirs(cache_dir, exist_ok=True)
            out_path = os.path.join(cache_dir, f"{self.name}_{vol_pct}.wav")
            if not os.path.exists(out_path):
                with wave.open(self.source_path, "rb") as r:
                    params = r.getparams()
                    raw = r.readframes(params.nframes)
                if params.sampwidth == 2:
                    samples = array.array("h")
                    samples.frombytes(raw)
                    scale_f = self._volume
                    for i in range(len(samples)):
                        samples[i] = int(samples[i] * scale_f)
                    scaled_bytes = samples.tobytes()
                else:
                    scaled_bytes = raw
                with wave.open(out_path, "wb") as w:
                    w.setparams(params)
                    w.writeframes(scaled_bytes)
            self._scaled_file_cache[key] = out_path
            self._active_path = out_path
        except Exception:
            self._active_path = self.source_path

    def play(self) -> None:
        if not self._active_path or winsound is None:
            return
        _WIN_SOUND_QUEUE.put_nowait(self._active_path)


class MainWindow(QMainWindow):
    switch_requested = False
    _integrity_checked_signal = pyqtSignal(str, int)
    _preload_stats_ready_signal = pyqtSignal(str, int)
    def __init__(self, profile_name):
        super().__init__()
        self.profile_name = profile_name
        display_profile_name = tr_ui("login.free_training", "Freies Training") if is_free_training_profile(profile_name) else profile_name
        self.setWindowTitle(tr_ui("main_window.window_title", "Opening Fenix v{version} - {profile}", version=APP_VERSION, profile=display_profile_name))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        
        set_consistent_icon(self)

        self.setMinimumSize(scale(1000), scale(700))
        self.resize(scale(1400), scale(850))

        
        self.repertoire_manager = RepertoireManager(profile_name=profile_name)
        self.training_manager = TrainingManager(profile_name=profile_name, repertoire_manager=self.repertoire_manager)
        
        # Load profile-specific or global language setting before initializing UI
        from opening_fenix.core.translation import translator
        profile_lang = self.training_manager.get_setting("ui_language") or getattr(translator, "current_lang", None)
        if not profile_lang:
            try:
                config_path = os.path.join(get_user_dir(), "config.json")
                if os.path.exists(config_path):
                    with open(config_path, "r") as f:
                        profile_lang = json.load(f).get("ui_language")
            except Exception:
                pass
        profile_lang = profile_lang or "de"
        translator.load_language(profile_lang)
        
        self.current_move_obj = None
        self._preloaded_challenge = None
        self._had_alternate_attempt = False
        self.session_review_count = 0
        self._preload_lock = threading.Lock()
        self._checked_integrity_repos = set()
        self._integrity_checked_signal.connect(self._on_integrity_check_result)
        self._preload_stats_ready_signal.connect(self._on_preload_stats_ready)
        self._repo_preload_gen = 0
        self._preloaded_start_challenge = None
        self._challenge_preload_gen = 0
        self._cached_anim_history = None
        self._auto_continue_timer = QTimer(self)
        self._auto_continue_timer.setSingleShot(True)
        self._auto_continue_timer.timeout.connect(self._on_auto_continue_timeout)
        self._pending_auto_continue = None
        self._db_commit_timer = QTimer(self)
        self._db_commit_timer.setSingleShot(True)
        self._db_commit_timer.timeout.connect(self._on_db_commit_timer)
        self.waiting_for_next = False
        self.show_comments = True
        self.mode = "TRAINER"
        self.training_mode = 'due' 
        self.button_state = 'start' 
        self.active_variation_filter = None 
        self.active_variation_entry_fen = None # Cache for start_animation efficiency
        
        self.creator_window = None
        self.sounds = {}
        self.animation_moves = []
        self._turbo_leadup_remaining = 0
        self.sorted_repo_names = None
        self.repo_mini_donuts = {}
        self._auto_size_board = True
        
        # Debounce timer for updating the large stats pie chart
        self.stats_update_timer = QTimer()
        self.stats_update_timer.setSingleShot(True)
        self.stats_update_timer.timeout.connect(self._on_stats_timer_timeout)
        self._pending_stats_task = None

        self.init_ui()
        # Lazy load sounds to ensure audio system is initialized within the event loop
        QTimer.singleShot(200, self.init_sounds)
        self.init_animation()
        self.previous_fen_for_animation = None
        
        self.refresh_repertoire_buttons()
        # Pre-select the first repertoire from our sorted list
        if self.sorted_repo_names:
            # OPTIMIZATION: skip refresh_buttons here since they were just refreshed on the line above
            self.change_repertoire(self.sorted_repo_names[0], refresh_buttons=False)
        else:
            self.change_repertoire(None, refresh_buttons=False)
        
        self.set_button_state('start')
        self.setStyleSheet(get_main_window_style())

        # Trigger background update check 2 seconds after startup
        QTimer.singleShot(2000, self.check_for_updates)

    def check_for_updates(self):
        import sys
        if "pytest" in sys.modules:
            return
        if sip.isdeleted(self):
            return
        if getattr(self, 'board_widget', None) and (self.board_widget.is_animating or self.animation_moves):
            QTimer.singleShot(500, self.check_for_updates)
            return
        from opening_fenix.core.services.update_service import UpdateCheckWorker

        self.update_checker = UpdateCheckWorker(manual=False, parent=self)
        self.update_checker.update_found.connect(self.on_update_found)

        from opening_fenix.core.threads import AutoBackupThread
        self.backup_worker = AutoBackupThread(parent=self)

        # Delay heavy background workers until 3 seconds after window startup to avoid GIL animation starvation
        QTimer.singleShot(3000, self._start_background_workers)

    def _start_background_workers(self):
        if sip.isdeleted(self):
            return
        if getattr(self, 'board_widget', None) and (self.board_widget.is_animating or self.animation_moves):
            QTimer.singleShot(500, self._start_background_workers)
            return
        try:
            if hasattr(self, 'update_checker') and self.update_checker and not self.update_checker.isRunning():
                logger.info("MainWindow: Starting background UpdateCheckWorker...")
                self.update_checker.start(QThread.Priority.LowPriority)
            if hasattr(self, 'backup_worker') and self.backup_worker and not self.backup_worker.isRunning():
                logger.info("MainWindow: Starting background AutoBackupThread...")
                self.backup_worker.start(QThread.Priority.IdlePriority)
        except Exception as e:
            logger.warning(f"MainWindow error starting background workers: {e}")

    def on_update_found(self, release_info: dict):
        from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
        UpdateDialog(release_info, self).exec()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'board_widget') and self.board_widget:
            self.board_widget.update_animation_metrics()
        self._fit_board_splitter()
        # Connect screenChanged if window handle is available
        if hasattr(self, 'windowHandle') and self.windowHandle():
            try:
                self.windowHandle().screenChanged.connect(self._on_screen_changed)
            except Exception:
                pass

        # Re-apply icon after native handle is created (needed for FramelessWindowHint on Windows)
        QTimer.singleShot(0, lambda: set_consistent_icon(self))
        QTimer.singleShot(0, self.trigger_board_adjust)
        QTimer.singleShot(100, self.trigger_board_adjust)
        # Start the onboarding tour if not shown yet
        QTimer.singleShot(500, self.check_for_onboarding)
        # Pre-warm settings dialog during idle time for instant opening
        QTimer.singleShot(1500, self._prewarm_settings_dialog)
        if is_free_training_profile(self.profile_name) and not getattr(self, '_free_training_setup_shown', False):
            self._free_training_setup_shown = True
            QTimer.singleShot(200, self.open_free_training_setup)

    def trigger_board_adjust(self):
        if hasattr(self, 'board_panel') and hasattr(self, 'main_splitter'):
            # Allow board to shrink/expand freely
            self.board_panel.setMinimumWidth(0)
            self.board_panel.setMaximumWidth(16777215)
            
            # Auto-suggest a square width based on current height
            if getattr(self, '_auto_size_board', True):
                h = self.board_panel.height()
                if h > 0:
                    total_w = self.main_splitter.width()
                    # Only suggest if we have enough space for tools too
                    # Reduced threshold from 350 to 250 to favor board size on small screens
                    if total_w > h + scale(250):
                        self.main_splitter.setSizes([h, total_w - h])
            
            self.board_panel.adjust_size()
            if self.centralWidget() and self.centralWidget().layout():
                self.centralWidget().layout().activate()
            self.board_widget.update()

    def check_for_onboarding(self):
        """Check if the guided tour should be started for this profile."""
        if is_free_training_profile(self.profile_name):
            return
            
        guide_shown = self.training_manager.get_setting("guide_shown")
        if not guide_shown:
            self.start_guided_tour()

    def start_guided_tour(self):
        """Initializes and starts the step-by-step guided tour."""
        self.tour = GuidedTourOverlay(self)
        
        # Step 1: Welcome (Moved to first)
        self.tour.add_step(None, tr_ui("tour.step1_title", "Willkommen bei Opening Fenix!"), 
            tr_ui("tour.step1_text", "Lass uns kurz die wichtigsten Funktionen durchgehen, damit du direkt mit deinem Training starten kannst."))

        # Step 2: Trainer Overview (NEW / Moved to second)
        self.tour.add_step(None, tr_ui("tour.step2_title", "Der Trainer"), 
            tr_ui("tour.step2_text", "Das Programm besteht aus 2 Modulen. Dem Trainer und dem Creator. \nMit dem Trainer übst du deine Züge aus den Reperotires und lernst neue. Zum Creator wird später noch etwas gesagt."))
            
        # Step 3: Repertoires
        self.tour.add_step(self.repo_scroll, tr_ui("tour.step3_title", "Deine Repertoires"), 
            tr_ui("tour.step3_text", "Hier oben findest du alle Eröffnungen, die du für dieses Profil gewählt hast. Du kannst jederzeit zwischen ihnen wechseln."))
            
        # Step 4: Elo
        self.tour.add_step(self.lbl_elo, tr_ui("tour.step4_title", "Dein Fortschritt (Elo)"), 
            tr_ui("tour.step4_text", "Diese Elo zeigt dir, wie gut du das Repertoire bereits beherrschst. Sie wird steigen, je mehr du das Repertoire lernst und übst."))
            
        # Step 5: Training Hub
        self.tour.add_step(self.side_panel, tr_ui("tour.step5_title", "Das Training Center"), 
            tr_ui("tour.step5_text", "Hier schlägt das Herz der App. Die Grafik zeigt dir, wie viele Züge du bereits gelernt hast und wie viele zur Wiederholung fällig sind."))

        # Step 6: Notation
        self.tour.add_step(self.txt_notation, tr_ui("tour.step6_title", "Notation & Details"), 
            tr_ui("tour.step6_text", "Hier siehst du den Partieverlauf und deine Kommentare. Ein Klick auf einen Zug bringt dich an die entsprechende Stelle im Creator."))
            
        # Step 7: Starten Button (Updated Text)
        self.tour.add_step(self.btn_smart, tr_ui("tour.step7_title", "Training Starten"), 
            tr_ui("tour.step7_text", "Klicke hier, um mit dem Training zu starten und zur nächsten Variante zu gehen"))
            
        # Step 8: Learn New
        self.tour.add_step(self.btn_learn_new, tr_ui("tour.step8_title", "Neues lernen (🧠)"), 
            tr_ui("tour.step8_text", "Aktiviere das Gehirn-Icon, um gezielt neue Züge aus deinem Repertoire zu lernen, die du noch nicht kennst."))

        # Step 9: Auto-Weiter (Updated Text)
        self.tour.add_step(self.btn_auto_continue, tr_ui("tour.step9_title", "Auto-Weiter (⚡)"), 
            tr_ui("tour.step9_text", "Ist dieser Button aktiv, springt die App am Ende einer Variante automatisch zur nächsten fälligen Aufgabe. Ideal falls man Züge wiederholt und schon vertraut ist mit der Eröffnung"))

        # Step 10: Lichess (Updated Text)
        self.tour.add_step(self.btn_lichess, tr_ui("tour.step10_title", "Lichess Analyse"), 
            tr_ui("tour.step10_text", "Du verstehst nicht warum dein Zug falsch ist? Mit dem Lichess-Button kannst du die aktuelle Position direkt in der Lichess-Analyse mit der Engine prüfen."))
            
        # Step 11: Creator
        self.tour.add_step(self.btn_creator, tr_ui("tour.step11_title", "Repertoire Creator (✏️)"), 
            tr_ui("tour.step11_text", "Möchtest du das gesamte Repertoire durchstöbern oder das Repertoire bearbeiten? Mit dem Creator-Button (✏️) springst du direkt in den Editor."))
            
        # Step 12: Filter (Updated Text)
        self.tour.add_step(self.btn_filter, tr_ui("tour.step12_title", "Fokussiertes Training"), 
            tr_ui("tour.step12_text", "Nutze den Variantenfilter oben, um nur bestimmte Varianten zu trainieren oder lernen - ideal, wenn man eine neue Variante lernt und man möchte alle züge zu dieser Variante lernen bevor man etwas anderes lernt oder um sich auf eine spezielle Eröffnung vorzubereiten"))

        # Step 13: Ressourcen (NEW)
        self.tour.add_step(self.btn_resources, tr_ui("tour.step13_title", "Ressourcen"), 
            tr_ui("tour.step13_text", "Hier findest du einen Ordner mit weiteren PGN Dateien die für den Kurs nützlich sind. Du kannst sie mithilfe von Lichess öffnen oder einem anderen Schach Programm"))

        self.tour.finished.connect(self.on_tour_finished)
        self.tour.start_tour()

    def on_tour_finished(self):
        """Mark the tour as shown, show the FAQ dialog, then proceed to course intro if needed."""
        self.training_manager.set_setting("guide_shown", True)
        from opening_fenix.gui.dialogs.faq_dialog import FAQDialog
        FAQDialog(self).exec()
        
        # After FAQ is closed, ensure we show the intro for the correctly prioritized repertoire
        # We use sorted_repo_names[0] to be consistent with the UI tabs
        active_repo = self.repertoire_manager.active_repertoire_name
        if not active_repo and self.sorted_repo_names:
            active_repo = self.sorted_repo_names[0]
            
        if active_repo:
            # After FAQ, if we are already on the right repo, we still need to trigger 
            # the Course Intro check which was suppressed during the tour.
            # Calling change_repertoire with refresh_buttons=False is fast.
            self.change_repertoire(active_repo, refresh_buttons=False)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 0. CUSTOM TITLE BAR (MERGED) ---
        display_profile_name = tr_ui("login.free_training", "Freies Training") if is_free_training_profile(self.profile_name) else self.profile_name
        self.custom_title_bar = CustomTitleBar(self, title=f" {display_profile_name}")
        self.custom_title_bar.setFixedHeight(scale(65))
        main_layout.addWidget(self.custom_title_bar)


        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(10, 6, 20, 6)
        top_layout.setSpacing(scale(14))

        self.btn_scroll_left = QPushButton("◄")
        self.btn_scroll_left.setFixedSize(scale(30), scale(40))
        self.btn_scroll_left.setStyleSheet(f"border: none; background: transparent; color: #8d6e63; font-size: {scale(18)}px;")

        self.btn_scroll_left.clicked.connect(self.scroll_tabs_left)
        self.btn_scroll_left.hide()

        self.btn_scroll_right = QPushButton("►")
        self.btn_scroll_right.setFixedSize(scale(30), scale(40))
        self.btn_scroll_right.setStyleSheet(f"border: none; background: transparent; color: #8d6e63; font-size: {scale(18)}px;")

        self.btn_scroll_right.clicked.connect(self.scroll_tabs_right)
        self.btn_scroll_right.hide()

        self.repo_scroll = QScrollArea()
        self.repo_scroll.setWidgetResizable(True)
        self.repo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.repo_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.repo_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.repo_tabs_widget = QWidget()
        self.repo_tabs_widget.setStyleSheet("background: transparent;")
        self.repo_tabs_widget.setFixedHeight(scale(40))
        self.repo_tabs_layout = QHBoxLayout(self.repo_tabs_widget)
        self.repo_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.repo_tabs_layout.setSpacing(15)
        self.repo_button_group = QButtonGroup(self)
        self.repo_button_group.buttonClicked.connect(self.on_repertoire_button_clicked)
        
        self.repo_scroll.setWidget(self.repo_tabs_widget)
        QScroller.grabGesture(self.repo_scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        
        # Disable vertical drag bounciness/overshoot
        scroller = QScroller.scroller(self.repo_scroll.viewport())
        props = scroller.scrollerProperties()
        props.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy, 
                              QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        scroller.setScrollerProperties(props)
        
        self.repo_scroll.horizontalScrollBar().valueChanged.connect(self.update_tab_scroll_arrows)

        top_layout.addWidget(self.btn_scroll_left)
        top_layout.addWidget(self.repo_scroll, 1)
        top_layout.addWidget(self.btn_scroll_right)

        top_right_container = QWidget()
        top_right_layout = QHBoxLayout(top_right_container)
        top_right_layout.setSpacing(scale(15))
        top_right_layout.setContentsMargins(scale(15), 0, scale(15), 0)

        self.btn_filter = QPushButton(tr_ui("main_window.filter_label", "Filter ▾"))
        self.btn_filter.setFixedHeight(scale(40))
        self.btn_filter.setFlat(True)
        # Added subtle hover styling for the top bar flat buttons
        self.btn_filter.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: {scale(14)}px; border-radius: {scale(18)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)

        self.btn_filter.clicked.connect(self.show_filter_menu)

        self.lbl_elo = QLabel("🎓 800")
        self.lbl_elo.setStyleSheet(f"font-size: {scale(20)}px; color: {COLORS['burnt_orange']}; font-weight: bold;")

        display_profile_name = tr_ui("login.free_training", "Freies Training") if is_free_training_profile(self.profile_name) else self.profile_name
        self.btn_switch_profile = QPushButton(display_profile_name)
        self.btn_switch_profile.setFixedHeight(scale(40))
        self.btn_switch_profile.setFlat(True)
        self.btn_switch_profile.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: {scale(14)}px; border-radius: {scale(18)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)

        self.btn_switch_profile.clicked.connect(self.handle_profile_button_click)
        self.btn_settings = QPushButton()
        self.btn_settings.setIcon(get_settings_gear_icon(22))
        self.btn_settings.setIconSize(QSize(scale(22), scale(22)))
        self.btn_settings.setFixedSize(scale(40), scale(40))
        self.btn_settings.setStyleSheet(f"""
            QPushButton {{ font-size: {scale(24)}px; border: none; background: transparent; border-radius: {scale(20)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)

        self.btn_settings.clicked.connect(self.open_settings)

        from opening_fenix.gui.widgets.cloud_sync_widgets import CloudSyncStatusPill
        self.cloud_sync_pill = CloudSyncStatusPill(self, compact_height=40, icon_only=True)
        self.cloud_sync_pill.open_settings_requested.connect(self.open_storage_settings)

        top_right_layout.addWidget(self.btn_filter)
        top_right_layout.addWidget(self.lbl_elo)
        top_right_layout.addWidget(self.btn_switch_profile)
        top_right_layout.addWidget(self.cloud_sync_pill)
        top_right_layout.addWidget(self.btn_settings)
        top_layout.addWidget(top_right_container)

        # Repertoire Resources Pill (Container approach to match the User/Settings pill)
        self.res_pill = QWidget()
        self.res_pill.setProperty("class", "GlassPill")
        res_pill_layout = QHBoxLayout(self.res_pill)
        res_pill_layout.setContentsMargins(scale(15), 0, scale(15), 0)
        res_pill_layout.setSpacing(0)

        self.btn_resources = QPushButton(tr_ui("main_window.resources_btn", "📁 Ressourcen"))
        self.btn_resources.setFlat(True)
        self.btn_resources.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: {scale(14)}px; border-radius: {scale(18)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_resources.setFixedHeight(scale(40)) # Use 40px to drive the pill height, matching btn_settings
        self.btn_resources.setToolTip(tr_ui("main_window.resources_tooltip", "Öffne den Repertoire-Ordner für weitere Ressourcen (Model Games, Tactics, etc.)"))
        self.btn_resources.clicked.connect(self.open_repertoire_folder)
        res_pill_layout.addWidget(self.btn_resources)
        
        top_layout.addWidget(self.res_pill)
        
        # Apply GlassPill classes to the top elements and unify their height
        pill_height = scale(52)
        for pill in [self.repo_scroll, top_right_container, self.res_pill]:
            pill.setProperty("class", "GlassPill")
            pill.setFixedHeight(pill_height)
            self.repolish(pill)
        
        # Inject merged top bar into the custom title bar before the stretch and window controls
        self.custom_title_bar.layout.insertLayout(1, top_layout, 1)

        # --- 2. CONTENT AREA (Now with Splitter) ---
        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(scale(10), scale(10), scale(10), scale(10))
        content_layout.setSpacing(0)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_layout.addWidget(self.main_splitter)

        self.board_panel = AspectRatioFrame()
        self.board_panel.setObjectName("BoardPanel")
        board_inner_layout = QVBoxLayout(self.board_panel)
        board_inner_layout.setContentsMargins(0, 0, 0, 0)
        self.board_widget = ChessBoardWidget(self)
        self.board_widget.move_executed.connect(self.check_user_move)
        board_inner_layout.addWidget(self.board_widget)
        
        # Board Container to provide the visual gap to the right (matching Creator style)
        self.board_container = QWidget()
        board_container_layout = QVBoxLayout(self.board_container)
        board_container_layout.setContentsMargins(0, 0, scale(10), 0)
        board_container_layout.addWidget(self.board_panel)
        self.main_splitter.addWidget(self.board_container)

        self.side_panel = QFrame()
        self.side_panel.setObjectName("SidePanel")
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(20, 20, 20, 20)
        side_layout.setSpacing(15)

        side_layout.addWidget(QLabel(tr_ui("main_window.notation_label", "NOTATION")), 0, Qt.AlignmentFlag.AlignLeft)
        self.txt_notation = ZoomableTextBrowser()
        self.txt_notation.setObjectName("NotationView")
        self.txt_notation.setOpenLinks(False)
        self.txt_notation.anchorClicked.connect(self.on_notation_click)
        side_layout.addWidget(self.txt_notation, 1)

        training_hub = QWidget()
        hub_layout = QVBoxLayout(training_hub)
        hub_layout.setContentsMargins(0, 0, 0, 0)
        hub_layout.setSpacing(20)

        stats_actions_row = QHBoxLayout()
        stats_actions_row.setSpacing(15)
        self.progress_bar = PieChartWidget()
        self.progress_bar.setMinimumSize(scale(160), scale(160))
        stats_actions_row.addWidget(self.progress_bar, 1)


        actions_grid = QGridLayout()
        actions_grid.setSpacing(8)
        
        # UPGRADED ICONS
        self.btn_learn_new = QPushButton("🧠")
        self.btn_learn_new.setObjectName("ActionButton")
        self.btn_learn_new.setCheckable(True)
        self.btn_learn_new.clicked.connect(self.toggle_learning_mode)
        self.btn_learn_new.setToolTip(tr_ui("main_window.learn_mode_tooltip", "<b>Lern-Modus</b><br>Trainiere neue Züge, die du noch nicht kennst."))
        if is_free_training_profile(self.profile_name):
            self.btn_learn_new.setChecked(False)
            self.btn_learn_new.setEnabled(False)
        
        self.btn_auto_continue = QPushButton("⚡")
        self.btn_auto_continue.setObjectName("ActionButton")
        self.btn_auto_continue.setCheckable(True)
        self.btn_auto_continue.clicked.connect(self.toggle_auto_continue_btn)
        self.btn_auto_continue.setToolTip(tr_ui("main_window.auto_continue_tooltip", "<b>Auto-Weiter</b><br>Springe nach einem korrekten Zug automatisch zum nächsten."))
        
        # Use custom Lichess Icon
        self.btn_lichess = QPushButton()
        self.btn_lichess.setObjectName("ActionButton")
        lichess_icon_path = os.path.join(get_base_path(), "assets", "Icons", "lichess.png")
        if os.path.exists(lichess_icon_path):
            self.btn_lichess.setIcon(QIcon(lichess_icon_path))
            self.btn_lichess.setIconSize(QSize(scale(24), scale(24)))
        else:

            self.btn_lichess.setText("🔬")
        self.btn_lichess.clicked.connect(self.open_lichess_analysis)
        self.btn_lichess.setToolTip(tr_ui("main_window.lichess_tooltip", "<b>Lichess Analyse</b><br>Öffne die aktuelle Stellung in der Lichess-Analyse."))
        
        self.btn_creator = QPushButton("✏️")
        self.btn_creator.setObjectName("ActionButton")
        self.btn_creator.clicked.connect(lambda: self.open_creator_at_current_position(chess.STARTING_FEN))
        self.btn_creator.setToolTip(tr_ui("main_window.creator_tooltip", "<b>Repertoire Creator</b><br>Öffne den Creator an der Startposition, um dein Repertoire zu bearbeiten."))
        
        actions_grid.addWidget(self.btn_learn_new, 0, 0)
        actions_grid.addWidget(self.btn_auto_continue, 0, 1)
        actions_grid.addWidget(self.btn_lichess, 1, 0)
        actions_grid.addWidget(self.btn_creator, 1, 1)

        stats_actions_row.addLayout(actions_grid, 1)
        hub_layout.addLayout(stats_actions_row)

        self.btn_smart = QPushButton(tr_ui("main_window.btn_start", "TRAINING STARTEN"))
        self.btn_smart.setObjectName("StartButton"); self.btn_smart.clicked.connect(self.on_smart_click)
        hub_layout.addWidget(self.btn_smart)

        side_layout.addWidget(training_hub)
        
        # Side Container to provide the visual gap to the left (matching Creator style)
        self.side_container = QWidget()
        side_container_layout = QVBoxLayout(self.side_container)
        side_container_layout.setContentsMargins(scale(5), 0, 0, 0)
        side_container_layout.addWidget(self.side_panel)
        self.side_container.setMinimumWidth(scale(250))
        self.main_splitter.addWidget(self.side_container)
        
        # Initial proportions: Auto-fit square board container
        self._auto_size_board = True
        self.main_splitter.splitterMoved.connect(lambda: setattr(self, '_auto_size_board', False))
        
        main_layout.addWidget(content_wrapper, 1)

        # Floating Background Task Progress Indicator
        from opening_fenix.gui.widgets.task_progress_indicator import TaskProgressIndicator
        self.task_indicator = TaskProgressIndicator(self)
        self.task_indicator.clicked.connect(self.open_task_center)

    def open_task_center(self, initial_tab=None):
        from opening_fenix.gui.dialogs.task_center_dialog import TaskCenterDialog
        from PyQt6 import sip
        active_repo = getattr(self.training_manager, 'active_repo_name', None) if getattr(self, 'training_manager', None) else None
        if not hasattr(self, 'task_center_dialog') or not self.task_center_dialog or sip.isdeleted(self.task_center_dialog):
            self.task_center_dialog = TaskCenterDialog(None, active_repo_name=active_repo)
        else:
            if active_repo and hasattr(self.task_center_dialog, 'set_active_repertoire'):
                self.task_center_dialog.set_active_repertoire(active_repo)
        if initial_tab is not None and not isinstance(initial_tab, bool) and hasattr(self.task_center_dialog, 'tabs'):
            self.task_center_dialog.tabs.setCurrentIndex(int(initial_tab))
        self.task_center_dialog.show()
        self.task_center_dialog.raise_()
        self.task_center_dialog.activateWindow()

    def scroll_tabs_left(self):
        sb = self.repo_scroll.horizontalScrollBar()
        sb.setValue(sb.value() - scale(100))


    def scroll_tabs_right(self):
        sb = self.repo_scroll.horizontalScrollBar()
        sb.setValue(sb.value() + scale(100))


    def update_tab_scroll_arrows(self):
        sb = self.repo_scroll.horizontalScrollBar()
        self.btn_scroll_left.setVisible(sb.value() > 0)
        self.btn_scroll_right.setVisible(sb.value() < sb.maximum())

    def on_repertoire_button_clicked(self, button):
        self.change_repertoire(button.property("repo_name"), refresh_buttons=False)

    def change_repertoire(self, repo_name, reset_filter=True, refresh_buttons=True, clear_persistent_stats=False):
        self._cancel_auto_continue()
        self._flush_pending_stats()
        # Cancel any ongoing animations before switching
        self.animation_moves = []
        self._turbo_leadup_remaining = 0
        self._preloaded_challenge = None
        self._cached_anim_history = None
        if hasattr(self.board_widget, 'abort_piece_slide'):
            self.board_widget.abort_piece_slide()

        # Update checked state of existing buttons immediately (Fast UI feedback)
        for btn in self.repo_button_group.buttons():
            btn.setChecked(btn.property("repo_name") == repo_name)
        
        if repo_name == self.repertoire_manager.active_repertoire_name and not refresh_buttons:
            # We are already on this repo and no UI rebuild requested.
            # But we still need to check if the Course Intro should be shown now (e.g. after tour).
            self._check_for_course_intro(repo_name)
            return

        # Reset all caches and trainer state
        self._preloaded_start_challenge = None
        self._repo_preload_gen += 1
        self._challenge_preload_gen += 1
        self._flush_db_commits()
        with self._preload_lock:
            pass
        try:
            self.repertoire_manager.set_active_repertoire(repo_name)
        except DatabaseCorruptedException as e:
            QMessageBox.critical(self, tr_ui("main.dlg_db_defective_title", "Datenbank defekt"), f"Das Repertoire '{repo_name}' ist beschädigt und kann nicht geladen werden.\n\nFehler: {e}")
            self.repertoire_manager.set_active_repertoire(None)
            self.lbl_elo.setText("🎓 800")
            self.progress_bar.update_stats(0, 0, {})
            
            # Remove from sorted_repo_names and refresh UI
            if self.sorted_repo_names and repo_name in self.sorted_repo_names:
                self.sorted_repo_names.remove(repo_name)
            
            next_repo = self.sorted_repo_names[0] if self.sorted_repo_names else None
            
            if next_repo:
                QTimer.singleShot(0, lambda: self.change_repertoire(next_repo))
            else:
                self.refresh_repertoire_buttons()
            return
            
        self.training_manager.on_repertoire_changed(clear_persistent_stats=clear_persistent_stats)
        
        if reset_filter:
            self.active_variation_filter = None
            self.btn_filter.setText(tr_ui("main_window.filter_label", "Filter ▾"))
        
        if repo_name:
            is_player_white = self.repertoire_manager.get_repertoire_color() == 'w'
            self.board_widget.flipped = not is_player_white
            self.board_widget.set_fen(chess.STARTING_FEN)
            self.update_settings_from_manager()
        
        # Immediate update of large chart, mini charts update automatically in refresh_repertoire_buttons
        stats_res = self._do_update_stats_display(allow_stale_cache=not clear_persistent_stats)
        
        self.txt_notation.clear()
        self.set_button_state('start')
        self.current_move_obj = None
        
        if refresh_buttons:
            self.refresh_repertoire_buttons()
        
        self._check_for_course_intro(repo_name, precomputed_stats=stats_res)
        
        # Background preload + integrity check without blocking the UI thread
        if repo_name:
            if clear_persistent_stats:
                self._checked_integrity_repos.discard(repo_name)
            self._schedule_repertoire_preload()

    def _on_integrity_check_result(self, repo_name, orphaned):
        if orphaned <= 0 or sip.isdeleted(self) or self.repertoire_manager.active_repertoire_name != repo_name:
            return
        reply = QMessageBox.warning(
            self,
            "Inkonsistenz gefunden",
            f"In diesem Repertoire wurden {orphaned} verwaiste (beschädigte) Züge gefunden.\n"
            "Dies geschieht meist durch Reparaturen der Datenbank. Wenn sie nicht entfernt werden, "
            "können Fehler beim Training auftreten.\n\nSollen die defekten Züge jetzt entfernt werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.repertoire_manager.core.repair_logical_integrity()
            self._checked_integrity_repos.discard(repo_name)
            self.change_repertoire(repo_name, reset_filter=False, refresh_buttons=False, clear_persistent_stats=True)

    def _check_for_course_intro(self, repo_name, precomputed_stats=None):
        # Handle Course Intro and Learning Modes
        if self.repertoire_manager.repo_session:
            if precomputed_stats is not None:
                new, due, done_dist = precomputed_stats
            else:
                new, due, done_dist = self.training_manager.get_stats(allow_stale_cache=True)
            learned = sum(done_dist.values()) if isinstance(done_dist, dict) else 0
            
            # Show Course Intro Splash if no moves have been learned yet and not free training
            # BUGFIX: Don't show if the onboarding tour is currently active or not yet shown
            guide_shown = self.training_manager.get_setting("guide_shown")
            if learned == 0 and due == 0 and repo_name and not is_free_training_profile(self.profile_name) and guide_shown:
                from opening_fenix.gui.dialogs.course_intro_dialog import CourseIntroDialog
                repo_info = self.repertoire_manager.get_repertoire_info()
                self._current_intro = CourseIntroDialog(self, repo_info)
                self._current_intro.setWindowModality(Qt.WindowModality.NonModal)
                
                # Connect the dialog acceptance to start learning
                self._current_intro.accepted.connect(self._start_learning_from_intro)
                self._current_intro.show()
            
            # Auto-activate "Neue lernen" when repertoire has no due or learned moves yet
            elif due == 0 and learned == 0:
                self.btn_learn_new.setChecked(True)
                self.training_mode = 'new'

    def _start_learning_from_intro(self):
        """Callback from Course Intro dialog to immediately start learning."""
        self.btn_learn_new.setChecked(True)
        self.training_mode = 'new'
        # Emulate a click on the STARTEN button
        if self.button_state == 'start':
            # Use singleShot to let the dialog close cleanly first
            QTimer.singleShot(100, self.on_smart_click)

    def show_filter_menu(self):
        if is_free_training_profile(self.profile_name):
            self.open_free_training_setup()
            return
        if not self.repertoire_manager.active_repertoire_name: return
        menu = QMenu(self)
        action_all = QAction(f"Alle {self.repertoire_manager.active_repertoire_name}", self)
        action_all.triggered.connect(lambda: self.set_variation_filter(None))
        menu.addAction(action_all); menu.addSeparator()
        eff_lang = self.get_effective_comment_language()
        structure = self.repertoire_manager.get_variation_structure(lang=eff_lang)
        for v1, v2_list in structure.items():
            if v2_list:
                v1_menu = menu.addMenu(v1)
                v1_all = QAction(f"Alle {v1}", self); v1_all.triggered.connect(lambda checked, n=v1: self.set_variation_filter(n)); v1_menu.addAction(v1_all); v1_menu.addSeparator()
                for v2 in v2_list:
                    act = QAction(v2, self); act.triggered.connect(lambda checked, n=v2: self.set_variation_filter(n)); v1_menu.addAction(act)
            else:
                act = QAction(v1, self); act.triggered.connect(lambda checked, n=v1: self.set_variation_filter(n)); menu.addAction(act)
        menu.exec(self.btn_filter.mapToGlobal(QPoint(0, self.btn_filter.height())))

    def set_variation_filter(self, var_name):
        self._cancel_auto_continue()
        self.active_variation_filter = var_name
        self.active_variation_entry_fen = None # Reset cache
        self._preloaded_challenge = None
        self._cached_anim_history = None
        eff_lang = self.get_effective_comment_language()
        from opening_fenix.core.utils import parse_variation_name
        display_name = parse_variation_name(var_name, lang=eff_lang) if var_name else ""
        if display_name and len(display_name) > 12:
            self.btn_filter.setText(tr_ui("main_window.filter_label_short", "{var}.. ▾", var=display_name[:12]))
        else:
            self.btn_filter.setText(tr_ui("main_window.filter_label_named", "{var} ▾", var=display_name or "Filter"))
        
        # If a filter is selected, jump the board to the start of that variation
        if var_name:
            entry_fen = self.repertoire_manager.get_variation_entry_point_fen(var_name)
            if entry_fen:
                self.active_variation_entry_fen = entry_fen # Cache for start_animation
                self.board_widget.set_fen(entry_fen)
                hist = self.repertoire_manager.get_history_for_fen(entry_fen, variation_name=var_name, training_manager=self.training_manager)
                # Ensure the last move is highlighted in notation if we jumped to a specific FEN
                self.update_notation_display(temp_hist=hist, reveal_move=True)
                
        self.current_move_obj = None
        self.load_next_challenge()
        self.update_stats_display()

    def refresh_repertoire_buttons(self):
        scroll_pos = self.repo_scroll.horizontalScrollBar().value()
        self.repo_mini_donuts = {}
        while self.repo_tabs_layout.count():
            item = self.repo_tabs_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        visible_repos = self.training_manager.get_visible_repos()
        active_repo = self.repertoire_manager.active_repertoire_name
        
        if is_free_training_profile(self.profile_name):
            if active_repo:
                visible_repos = [active_repo]
            elif visible_repos:
                visible_repos = [visible_repos[0]]
        
        # 1. Collect stats for all visible repertoires and sort if necessary
        repo_data = [] # List of (repo_name, stats_tuple)
        original_repo = active_repo
        
        for repo_name in visible_repos:
            # OPTIMIZATION: Use the fast persistent cache path instead of full repo switch
            stats = self.training_manager.get_stats_for_repertoire(repo_name)
            repo_data.append((repo_name, stats))
        
        if self.sorted_repo_names is None:
            # Primary sort: due moves (stats[1]) descending
            # Secondary sort: Elo rating descending (highest Elo first)
            # Tertiary sort: repertoire name ascending (alphabetical tie-breaker)
            ratings = (
                self.training_manager.get_ratings_for_all_repertoires()
                if hasattr(self.training_manager, "get_ratings_for_all_repertoires")
                else {}
            )
            repo_data.sort(
                key=lambda x: (
                    -int(x[1][1] if x[1] and len(x[1]) > 1 else 0),
                    -float(ratings.get(x[0], 800.0)),
                    str(x[0])
                )
            )
            self.sorted_repo_names = [rd[0] for rd in repo_data]
        else:
            # Use cached order, new ones at the end
            cached_order = {name: i for i, name in enumerate(self.sorted_repo_names)}
            repo_data.sort(key=lambda x: cached_order.get(x[0], 9999))
            
        # 2. Create UI components in the determined order
        for repo_name, (new, due, dist) in repo_data:
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(5)

            mini_donut = PieChartWidget(parent=container, show_text=False)
            mini_donut.setFixedSize(scale(24), scale(24))
            mini_donut.update_stats(new, due, dist)
            self.repo_mini_donuts[repo_name] = mini_donut


            btn = QPushButton(repo_name)
            btn.setObjectName("RepoTab"); btn.setCheckable(True); btn.setProperty("repo_name", repo_name)
            if repo_name == active_repo: btn.setChecked(True)
            
            layout.addWidget(mini_donut); layout.addWidget(btn)
            self.repo_tabs_layout.addWidget(container)
            self.repo_button_group.addButton(btn)

        self.repo_tabs_layout.addStretch()
        QTimer.singleShot(0, lambda: self.repo_scroll.horizontalScrollBar().setValue(scroll_pos))
        QTimer.singleShot(100, self.update_tab_scroll_arrows)

    def update_stats_display(self):
        """
        Schedules an update for the large statistics chart.
        Uses a timer to avoid blocking the main thread during fast move inputs.
        Longer delay during active training for less DB overhead.
        """
        if not self.stats_update_timer.isActive():
            # Use longer debounce during active training for less overhead
            delay = 150 if self.button_state in ('waiting_for_move', 'correct') else 50
            self.stats_update_timer.start(delay)
            
    def _on_stats_timer_timeout(self):
        if getattr(self, 'board_widget', None) and (self.board_widget.is_animating or self.animation_moves):
            self.stats_update_timer.start(100)
            return
        self._do_update_stats_display()

    def _do_update_stats_display(self, allow_stale_cache=False):
        active_repo = self.repertoire_manager.active_repertoire_name
        if not active_repo:
            self.progress_bar.update_stats(0, 0, {})
            self.lbl_elo.setText("🎓 800")
            return 0, 0, {}
        new, due, done_dist = self.training_manager.get_stats(
            variation_filter=self.active_variation_filter,
            allow_stale_cache=allow_stale_cache,
        )
        self.progress_bar.update_stats(new, due, done_dist)
        
        mini_donut = getattr(self, 'repo_mini_donuts', {}).get(active_repo)
        if mini_donut is not None and not sip.isdeleted(mini_donut):
            if self.active_variation_filter:
                r_new, r_due, r_dist = self.training_manager.get_stats(
                    variation_filter=None,
                    auto_commit=False,
                    allow_stale_cache=allow_stale_cache,
                )
                mini_donut.update_stats(r_new, r_due, r_dist)
            else:
                mini_donut.update_stats(new, due, done_dist)
        
        # Update Elo display
        try:
            elo = self.training_manager.get_current_elo(allow_stale_cache=allow_stale_cache)
        except TypeError:
            elo = self.training_manager.get_current_elo()
        self.lbl_elo.setText(f"🎓 {elo}")
        return new, due, done_dist

    def _on_db_commit_timer(self):
        if getattr(self, 'board_widget', None) and (self.board_widget.is_animating or self.animation_moves):
            self._db_commit_timer.start(300)
            return
        self._flush_db_commits()

    def _flush_db_commits(self):
        if getattr(self, '_db_commit_timer', None) and self._db_commit_timer.isActive():
            self._db_commit_timer.stop()
        if getattr(self, 'training_manager', None) and hasattr(self.training_manager, 'flush_pending_commits'):
            try:
                flushed = self.training_manager.flush_pending_commits()
                if flushed or flushed is None:
                    from opening_fenix.core.services.cloud_sync_manager import CloudSyncManager
                    CloudSyncManager.instance().schedule_background_push(delay_ms=15000)
            except Exception as e:
                logger.error(f"Error flushing pending DB commits: {e}")

    def _cancel_auto_continue(self):
        """Cancels any pending delayed auto-continue transition."""
        if getattr(self, '_auto_continue_timer', None) and self._auto_continue_timer.isActive():
            self._auto_continue_timer.stop()
        self._pending_auto_continue = None

    def _on_auto_continue_timeout(self):
        pending = getattr(self, '_pending_auto_continue', None)
        self._pending_auto_continue = None
        if pending is None:
            return
        path, anim_ctx = pending
        self._load_new_challenge_sequence(path, anim_ctx=anim_ctx)

    def _precompute_move_anim_context(self, move_obj, var_filter):
        """Precomputes history and lead-up entry FEN in memory so animation starts with zero DB/tree lag."""
        if not move_obj:
            return None
        try:
            history = self.repertoire_manager.get_history_for_move(
                move_obj,
                variation_name=var_filter,
                training_manager=self.training_manager,
            )
            var_name = None
            entry_fen = None
            if not var_filter and hasattr(self.training_manager, 'get_move_variation_name'):
                var_name = self.training_manager.get_move_variation_name(move_obj)
                if var_name:
                    entry_fen = self.repertoire_manager.get_variation_entry_point_fen(var_name)
            return {
                'move_id': getattr(move_obj, 'id', None),
                'var_filter': var_filter,
                'history': history,
                'var_name': var_name,
                'entry_fen': entry_fen,
            }
        except Exception:
            return None

    def _schedule_repertoire_preload(self, exclude_move_ids=None):
        """Warms up training caches and pre-fetches the next start challenge + history in a background thread."""
        repo_name = self.repertoire_manager.active_repertoire_name
        if not repo_name:
            return
        gen = self._repo_preload_gen
        mode = self.training_mode
        var_filter = self.active_variation_filter
        eff_lang = self.get_effective_comment_language()
        should_check_integrity = repo_name not in self._checked_integrity_repos

        def _is_stale():
            return self._repo_preload_gen != gen or self.repertoire_manager.active_repertoire_name != repo_name

        def _worker():
            try:
                for step in (
                    lambda: self.training_manager._ensure_forward_cache(),
                    lambda: self.training_manager._ensure_td_cache(),
                    lambda: self.training_manager._ensure_reachable_moves_cache(var_filter),
                ):
                    if _is_stale():
                        return
                    with self._preload_lock:
                        if _is_stale():
                            return
                        step()

                if not _is_stale():
                    self._preload_stats_ready_signal.emit(repo_name, gen)

                if should_check_integrity and not _is_stale():
                    with self._preload_lock:
                        if _is_stale():
                            return
                        orphaned = self.repertoire_manager.core.check_logical_integrity()
                    if not _is_stale():
                        self._checked_integrity_repos.add(repo_name)
                        if orphaned > 0:
                            self._integrity_checked_signal.emit(repo_name, orphaned)

                if _is_stale():
                    return
                with self._preload_lock:
                    if _is_stale():
                        return
                    next_move, _ = self.training_manager.get_next_move(
                        mode=mode,
                        variation_filter=var_filter,
                        exclude_move_ids=exclude_move_ids,
                    )
                    if _is_stale():
                        return
                    anim_ctx = self._precompute_move_anim_context(next_move, var_filter) if next_move else None
                    if not _is_stale():
                        self._preloaded_start_challenge = (repo_name, mode, var_filter, next_move, anim_ctx)
                if not _is_stale():
                    with self._preload_lock:
                        if not _is_stale():
                            self.repertoire_manager.get_variation_structure(lang=eff_lang)
            except Exception as e:
                logger.debug(f"Background repertoire preload skipped: {e}")

        t = threading.Thread(target=_worker, daemon=True)
        self._challenge_preload_thread = t
        t.start()

    def _on_preload_stats_ready(self, repo_name, gen):
        """Syncs stale persistent stats on the main thread once preload caches are warm."""
        if (
            sip.isdeleted(self)
            or self._repo_preload_gen != gen
            or self.repertoire_manager.active_repertoire_name != repo_name
        ):
            return
        if getattr(self, 'board_widget', None) and (self.board_widget.is_animating or self.animation_moves):
            return
        self._do_update_stats_display(allow_stale_cache=False)

    def preload_next_challenge(self):
        """Preloads the next challenge/move sequence in a background thread while the user is thinking."""
        if not self.repertoire_manager.active_repertoire_name or not self.current_move_obj:
            self._preloaded_challenge = None
            return

        repo_name = self.repertoire_manager.active_repertoire_name
        last_move = self.current_move_obj
        mode = self.training_mode
        var_filter = self.active_variation_filter
        r_gen = self._repo_preload_gen
        c_gen = self._challenge_preload_gen
        stop_at_end = self.training_manager.get_setting("stop_at_variation_end")

        def _worker():
            with self._preload_lock:
                if (
                    self._repo_preload_gen != r_gen
                    or self._challenge_preload_gen != c_gen
                    or self.repertoire_manager.active_repertoire_name != repo_name
                ):
                    return
                try:
                    next_move, path = self.training_manager.get_next_move(
                        mode=mode,
                        last_move_obj=last_move,
                        last_was_success=True,
                        only_continuation=True,
                        variation_filter=var_filter,
                    )
                    if self._repo_preload_gen != r_gen or self._challenge_preload_gen != c_gen:
                        return

                    if next_move:
                        result = {
                            'type': 'continuation',
                            'next_move': next_move,
                            'path': path,
                            'source_move_id': last_move.id,
                        }
                    elif stop_at_end:
                        result = {
                            'type': 'stop_at_end',
                            'last_move': last_move,
                            'source_move_id': last_move.id,
                        }
                    else:
                        next_challenge_move, _ = self.training_manager.get_next_move(
                            mode=mode,
                            variation_filter=var_filter,
                            exclude_move_ids={last_move.id},
                        )
                        anim_ctx = (
                            self._precompute_move_anim_context(next_challenge_move, var_filter)
                            if next_challenge_move
                            else None
                        )
                        result = {
                            'type': 'auto_continue',
                            'next_move': next_challenge_move,
                            'path': [],
                            'anim_ctx': anim_ctx,
                            'source_move_id': last_move.id,
                        }

                    if self._repo_preload_gen == r_gen and self._challenge_preload_gen == c_gen:
                        self._preloaded_challenge = result
                except Exception as e:
                    logger.error(f"Error in preload_next_challenge: {e}")
                    if self._repo_preload_gen == r_gen and self._challenge_preload_gen == c_gen:
                        self._preloaded_challenge = None

        t = threading.Thread(target=_worker, daemon=True)
        self._challenge_preload_thread = t
        t.start()
    def _is_training_limit_reached(self) -> bool:
        if is_free_training_profile(self.profile_name):
            return False
            
        if self.training_mode == 'new':
            max_new = self.training_manager.get_setting("max_new_cards_per_day") or 0
            if max_new > 0:
                today_count = self.training_manager.get_today_new_cards_count()
                if today_count >= max_new:
                    return True
        else: # 'due' mode
            max_reviews = self.training_manager.get_setting("max_reviews_per_session") or 0
            if max_reviews > 0:
                curr_reviews = getattr(self, 'session_review_count', 0)
                if curr_reviews >= max_reviews:
                    return True
        return False

    def _reveal_variation_end_drawings(self, last_move):
        """Displays user drawings (arrows/circles) from the concluding position of a variation."""
        if not last_move:
            return
        final_comment = ""
        if getattr(last_move, 'to_position', None):
            final_comment = getattr(last_move.to_position, 'comment', '') or ''
        if not final_comment and getattr(last_move, 'comment', None):
            final_comment = getattr(last_move, 'comment', '') or ''
        
        if final_comment:
            self.board_widget.load_user_drawings_from_comment(final_comment)
            self.board_widget.update()

    def _handle_variation_end_stop(self, last_move):
        """Updates UI when stopping at the end of a variation and warms up the next start challenge."""
        self.current_move_obj = last_move
        self.update_notation_display(reveal_move=True)
        self.set_button_state('start')
        self.current_move_obj = None
        last_id = getattr(last_move, 'id', None)
        self._schedule_repertoire_preload(exclude_move_ids={last_id} if last_id is not None else None)

    def _schedule_auto_continue(self, path=None, anim_ctx=None, exclude_move_id=None):
        """Transitions to the next variation immediately or after auto_delay (preloading during the wait)."""
        delay = self.training_manager.get_setting("auto_delay") or 0
        if delay > 0:
            if self.current_move_obj is None:
                exclude_ids = {exclude_move_id} if exclude_move_id is not None else None
                self._schedule_repertoire_preload(exclude_move_ids=exclude_ids)
            self._pending_auto_continue = (path or [], anim_ctx)
            self._auto_continue_timer.start(delay)
        else:
            self._load_new_challenge_sequence(path or [], anim_ctx=anim_ctx)

    def load_next_challenge(self, last_success=False, last_move=None):
        self._cancel_auto_continue()
        self.waiting_for_next = False
        if not self.repertoire_manager.active_repertoire_name: return

        limit_reached = self._is_training_limit_reached()
        enforce_after_var = self.training_manager.get_setting("enforce_limit_after_variation")
        if enforce_after_var is None:
            enforce_after_var = True

        # If limit reached and not in a continuation or not waiting for variation end, stop!
        if limit_reached and not (enforce_after_var and last_success and last_move):
            self.current_move_obj = None
            self.btn_smart.setText(tr_ui("main_window.btn_limit_reached", "🎯 ZIEL ERREICHT!"))
            self.btn_smart.setEnabled(False)
            return

        # Try to use preloaded challenge
        if last_success and last_move and self._preloaded_challenge:
            pre = self._preloaded_challenge
            self._preloaded_challenge = None  # Clear it
            
            # Verify the preloaded data matches the current move context
            if pre.get('source_move_id') == last_move.id:
                logger.debug(f"Preloaded challenge HIT! Type: {pre['type']}")
                if pre['type'] == 'continuation':
                    self.current_move_obj = pre['next_move']
                    self._load_new_challenge_sequence(pre['path'])
                    return
                elif pre['type'] in ('stop_at_end', 'auto_continue'):
                    self._reveal_variation_end_drawings(last_move)
                    if limit_reached:
                        self.current_move_obj = last_move
                        self.update_notation_display(reveal_move=True)
                        self.btn_smart.setText(tr_ui("main_window.btn_limit_reached", "🎯 ZIEL ERREICHT!"))
                        self.btn_smart.setEnabled(False)
                        self.current_move_obj = None
                        return

                    if self.training_manager.get_setting("stop_at_variation_end"):
                        self._handle_variation_end_stop(last_move)
                        return
                    else:
                        anim_ctx = None
                        if pre['type'] == 'auto_continue':
                            self.current_move_obj = pre['next_move']
                            anim_ctx = pre.get('anim_ctx')
                        else:
                            next_challenge_move, _ = self.training_manager.get_next_move(
                                mode=self.training_mode,
                                variation_filter=self.active_variation_filter
                            )
                            self.current_move_obj = next_challenge_move
                        self._schedule_auto_continue(pre.get('path', []), anim_ctx=anim_ctx, exclude_move_id=last_move.id)
                        return
            else:
                logger.debug(f"Preloaded challenge MISS: source_move_id mismatch. Expected {last_move.id}, got {pre.get('source_move_id')}")
        else:
            logger.debug(f"Preloaded challenge MISS: no preloaded challenge available (last_success={last_success}, last_move={last_move is not None}, has_preload={self._preloaded_challenge is not None})")

        path_to_animate = []
        if last_success and last_move:
            next_move, path = self.training_manager.get_next_move(mode=self.training_mode, last_move_obj=last_move, last_was_success=True, only_continuation=True, variation_filter=self.active_variation_filter)
            if next_move:
                self.current_move_obj = next_move
                path_to_animate = path
            else:
                self._reveal_variation_end_drawings(last_move)
                if limit_reached:
                    self.current_move_obj = last_move
                    self.update_notation_display(reveal_move=True)
                    self.btn_smart.setText(tr_ui("main_window.btn_limit_reached", "🎯 ZIEL ERREICHT!"))
                    self.btn_smart.setEnabled(False)
                    self.current_move_obj = None
                    return

                if self.training_manager.get_setting("stop_at_variation_end"):
                    self._handle_variation_end_stop(last_move)
                    return
                else:
                    # Auto-Weiter: Jump to next variation with delay (preload during delay)
                    self.current_move_obj = None
                    self._schedule_auto_continue(exclude_move_id=getattr(last_move, 'id', None))
                    return

        if limit_reached:
            self.current_move_obj = None
            self.btn_smart.setText(tr_ui("main_window.btn_limit_reached", "🎯 ZIEL ERREICHT!"))
            self.btn_smart.setEnabled(False)
            return

        self._load_new_challenge_sequence(path_to_animate)

    def _load_new_challenge_sequence(self, path_to_animate=None, anim_ctx=None):
        self._had_alternate_attempt = False
        self.board_widget.clear_user_drawings()
        if not self.current_move_obj:
            if self._is_training_limit_reached():
                self.btn_smart.setText(tr_ui("main_window.btn_limit_reached", "🎯 ZIEL ERREICHT!"))
                self.btn_smart.setEnabled(False)
                return
            pre_start = None
            with self._preload_lock:
                if (
                    self._preloaded_start_challenge is not None
                    and self._preloaded_start_challenge[0] == self.repertoire_manager.active_repertoire_name
                    and self._preloaded_start_challenge[1] == self.training_mode
                    and self._preloaded_start_challenge[2] == self.active_variation_filter
                ):
                    pre_start = self._preloaded_start_challenge[3]
                    if len(self._preloaded_start_challenge) > 4:
                        anim_ctx = self._preloaded_start_challenge[4]
                    self._preloaded_start_challenge = None
            if pre_start is not None:
                self.current_move_obj = pre_start
            else:
                self.current_move_obj, _ = self.training_manager.get_next_move(mode=self.training_mode, variation_filter=self.active_variation_filter)

        if self.current_move_obj:
            self.start_animation(path_to_animate or [], anim_ctx=anim_ctx)
            if not self.board_widget.is_animating:
                reveal = (self.training_mode == 'new')
                self.update_notation_display(reveal_move=reveal)
        else:
            self.btn_smart.setText(tr_ui("main_window.btn_done", "🎉 FERTIG!"))
            self.btn_smart.setEnabled(False)
            if is_free_training_profile(self.profile_name):
                QTimer.singleShot(400, self.open_free_training_setup)

    def on_notation_click(self, url):
        # Extract the FEN from the URL and properly decode percent-encoding (e.g., %20 -> " ")
        raw_fen = url.toString().replace("fen:", "")
        # Robust decoding path: ensure we handle '+' and other characters
        decoded_fen = QUrl.fromPercentEncoding(raw_fen.encode('utf-8'))
        
        self.open_creator_at_current_position(decoded_fen)
        
    def open_creator_at_current_position(self, fen=None):
        active_repo = self.repertoire_manager.active_repertoire_name
        is_test = self.repertoire_manager.is_active_test
        
        target_fen = fen or (self.board_widget.board.fen() if active_repo else chess.STARTING_FEN)
        
        # Check if window exists and is not deleted
        if self.creator_window and not sip.isdeleted(self.creator_window):
            # 1. Restore if minimized
            if self.creator_window.isMinimized():
                self.creator_window.showNormal()
            
            # 2. Update Repertoire if it changed in the main window
            # Switch if name OR folder context (test vs. regular) changed OR session was closed
            if (self.creator_window.backend.active_repo_name != active_repo or 
                self.creator_window.is_test != is_test or
                (active_repo is not None and self.creator_window.backend.session is None)):
                self.creator_window.load_repertoire(active_repo, self.training_manager, is_test)
            
            # 3. Update FEN
            self.creator_window.set_board_to_fen(target_fen)
            
            # 4. Ensure it's visible, on top, and active
            self.creator_window.show()
            self.creator_window.raise_()
            self.creator_window.activateWindow()
        else:
            global CreatorWindow
            if CreatorWindow is None:
                from opening_fenix.creator.creator_window import CreatorWindow as _CreatorWindow
                CreatorWindow = _CreatorWindow
            self.creator_window = CreatorWindow(
                repertoire_name=active_repo, 
                initial_fen=target_fen, 
                training_manager=self.training_manager,
                is_test=is_test
            )
            self.creator_window.closed.connect(self.on_creator_closed)
            self.creator_window.showMaximized()

    def on_creator_closed(self):
        # Reset cached sorted repo names and update the UI buttons
        self.sorted_repo_names = None
        self.refresh_repertoire_buttons()
        # If the active repertoire changed in the creator, switch to it
        if self.creator_window and not sip.isdeleted(self.creator_window):
            creator_repo = self.creator_window.backend.active_repo_name
            if creator_repo and creator_repo != self.repertoire_manager.active_repertoire_name:
                self.change_repertoire(creator_repo, clear_persistent_stats=True)
            else:
                self.change_repertoire(self.repertoire_manager.active_repertoire_name, clear_persistent_stats=True)



    def set_button_state(self, state):
        self.button_state = state
        if state == 'start':
            self.btn_smart.setText(tr_ui("main_window.btn_start", "TRAINING STARTEN")); self.btn_smart.setEnabled(True)
        elif state == 'waiting_for_move':
            if self.training_mode == 'new':
                self.btn_smart.setText(tr_ui("main_window.btn_play_move", "SPIELE DEN ZUG")); self.btn_smart.setEnabled(False)
            else:
                self.btn_smart.setText(tr_ui("main_window.btn_your_turn", "DU BIST AM ZUG")); self.btn_smart.setEnabled(False)
        elif state == 'correct':
            self.btn_smart.setText(tr_ui("main_window.btn_correct", "KORREKT!")); self.btn_smart.setEnabled(False)
        elif state == 'show_solution_prompt':
            self.btn_smart.setText(tr_ui("main_window.btn_wrong", "FALSCH! LÖSUNG ANZEIGEN")); self.btn_smart.setEnabled(True)

    def on_smart_click(self):
        self._cancel_auto_continue()
        if self.button_state == 'start':
            self.load_next_challenge()
        elif self.button_state == 'show_solution_prompt':
            self.board_widget.solution_arrow = chess.Move.from_uci(self.current_move_obj.uci)
            self.board_widget.update()
            self.btn_smart.setEnabled(False)

    def _flush_pending_stats(self):
        if getattr(self, '_pending_stats_task', None):
            task = self._pending_stats_task
            self._pending_stats_task = None
            try:
                task()
            except Exception as e:
                logger.error(f"Error flushing pending training stats: {e}")

    def check_user_move(self, move):
        if self.button_state not in ['waiting_for_move', 'show_solution_prompt'] or not self.current_move_obj: return
        self._challenge_preload_gen += 1
        if move.uci() == self.current_move_obj.uci:
            is_cap = self.board_widget.board.is_capture(move)
            self.play_sound("capture" if is_cap else "move")
            self.board_widget.board.push(move)
            self.board_widget.last_move = move
            self.board_widget.solution_arrow = None
            self.board_widget.update()

            was_waiting = (self.button_state == 'waiting_for_move')
            current_move = self.current_move_obj
            had_alt = getattr(self, '_had_alternate_attempt', False)
            self._had_alternate_attempt = False
            self.set_button_state('correct')
            
            # Prepare deferred stats task to run once animation finishes (zero thread blocking during piece slide)
            def record_stats():
                if was_waiting:
                    was_new = self.training_manager.is_move_new(current_move.id)
                    self.training_manager.register_success(current_move.id, True, had_alternate_attempt=had_alt, was_new=was_new, defer_commit=True)
                    if getattr(self, '_db_commit_timer', None):
                        self._db_commit_timer.start(1500)
                    if self.training_mode == 'due':
                        self.session_review_count = getattr(self, 'session_review_count', 0) + 1
                    self.update_stats_display()
                
            self._pending_stats_task = record_stats

            # 1. Launch next challenge / opponent animation immediately
            self.load_next_challenge(True, current_move)

            # 2. If no animation is running (e.g. static board or line end), flush stats right away
            if not self.board_widget.is_animating:
                self._flush_pending_stats()
        else:
            alt_type = self.repertoire_manager.get_alternative_move_type(
                self.current_move_obj, move.uci(), training_manager=self.training_manager
            )
            if alt_type:
                alt_policy = self.training_manager.get_setting("alternate_move_policy") or "no_penalty"
                if alt_policy == "mistake":
                    self.play_sound("error")
                    self.board_widget.update()
                    if self.button_state == 'waiting_for_move':
                        current_move = self.current_move_obj
                        self.set_button_state('show_solution_prompt')
                        def process_after_fail():
                            self.training_manager.register_success(current_move.id, False, defer_commit=True)
                            if getattr(self, '_db_commit_timer', None):
                                self._db_commit_timer.start(1500)
                            self.update_stats_display()
                        QTimer.singleShot(0, process_after_fail)
                    return

                is_cap = self.board_widget.board.is_capture(move)
                self.play_sound("capture" if is_cap else "move")
                if alt_type == 'repertoire':
                    self.btn_smart.setText(tr_ui("main_window.btn_alt_repertoire", "GUTER ZUG (ANDERER REPERTOIRE-WEG)"))
                else:
                    self.btn_smart.setText(tr_ui("main_window.btn_alt_not_repertoire", "GUTER ZUG (NICHT IM REPERTOIRE)"))
                
                if alt_policy == "keep_box":
                    self._had_alternate_attempt = True

                # Visual snap-back of incorrect piece
                self.board_widget.update()
                QTimer.singleShot(1500, lambda: self.set_button_state(self.button_state))
                return

            self.play_sound("error")
            # Visual snap-back of incorrect piece
            self.board_widget.update()
            
            if self.button_state == 'waiting_for_move':
                current_move = self.current_move_obj
                self.set_button_state('show_solution_prompt')
                
                # Defer the failure DB registration and stats update
                def process_after_fail():
                    self.training_manager.register_success(current_move.id, False, defer_commit=True)
                    self.update_stats_display()
                    
                QTimer.singleShot(0, process_after_fail)

    def get_effective_comment_language(self) -> str:
        from opening_fenix.core.translation import translator
        active_repo = getattr(self.repertoire_manager, 'active_repertoire_name', None)
        if self.training_manager and active_repo and hasattr(self.training_manager, 'get_comment_language'):
            repo_profile_lang = self.training_manager.get_comment_language(active_repo)
            if repo_profile_lang and repo_profile_lang != "auto":
                return repo_profile_lang

        lang_setting = self.training_manager.get_setting("comment_language")
        if lang_setting and lang_setting != "auto":
            return lang_setting
        current_app_lang = getattr(translator, "current_lang", None)
        if current_app_lang:
            return current_app_lang
        if self.repertoire_manager and self.repertoire_manager.repo_session:
            from opening_fenix.core.data_tools import get_meta
            repo_lang = get_meta(self.repertoire_manager.repo_session, "comment_language", "auto")
            if repo_lang and repo_lang != "auto":
                return repo_lang
        return self.training_manager.get_setting("notation_language") or "de"

    def update_notation_display(self, temp_hist=None, reveal_move=False):
        hist = temp_hist or self.repertoire_manager.get_history_for_move(self.current_move_obj, variation_name=self.active_variation_filter, training_manager=self.training_manager)
        if not hist:
            self.txt_notation.clear()
            return

        html = "<body style='line-height: 1.6;'>"
        start_move_offset = self.repertoire_manager.get_repertoire_start_move() - 1
        notation_lang = self.training_manager.get_setting("notation_language") or "en"
        comment_lang = self.get_effective_comment_language()
        repo_default_lang = "de"
        if self.repertoire_manager and self.repertoire_manager.repo_session:
            from opening_fenix.core.data_tools import get_meta
            meta_lang = get_meta(self.repertoire_manager.repo_session, "comment_language", "de")
            if meta_lang and meta_lang != "auto":
                repo_default_lang = meta_lang
        
        # Determine if the first move in history is Black (to adjust numbering/dots)
        # In hist, 'fen' is the position AFTER the move. If 'w' follows, Black just moved.
        first_fen = hist[0].get('fen', "")
        starts_with_black = " w " in first_fen
        
        for i, item in enumerate(hist):
            is_last = (i == len(hist) - 1)
            if is_last and not reveal_move: break
            
            # Adjusted move number calculation
            idx_for_calc = i + 1 if starts_with_black else i
            move_num = (idx_for_calc // 2) + 1 + start_move_offset
            
            # Formatting logic
            if i == 0 and starts_with_black:
                html += f"<b>{move_num}...</b> "
            elif idx_for_calc % 2 == 0:
                html += f"<b>{move_num}.</b> "
                
            style = f"text-decoration:none; color:{COLORS['brown_text']}; font-weight:bold;"
            if is_last and reveal_move: style += f" background-color: {COLORS['burnt_orange']}; color: white; border-radius: 3px; padding: 0 2px;"
            nag_map = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
            nag_text = nag_map.get(item.get('nag'), "")
            san = localize_san(item['san'], notation_lang)
            html += f"<a href='fen:{item['fen']}' style='{style}'>{san}{nag_text}</a> "
            if item.get('comment'):
                comment_text = parse_comment(item['comment'], comment_lang, default_lang=repo_default_lang)
                if comment_text:
                    from opening_fenix.core.utils import clean_chessbase_annotations
                    clean_text = clean_chessbase_annotations(comment_text)
                    if clean_text:
                        import re
                        lines = clean_text.split('\n')
                        formatted_lines = []
                        for line in lines:
                            m = re.match(r'^(\[[A-Za-z]{2,3}\])\s*(.*)$', line)
                            if m:
                                formatted_lines.append(f"<b>{m.group(1)}</b> {m.group(2)}")
                            else:
                                formatted_lines.append(line)
                        formatted_comment = "<br>".join(formatted_lines)
                        html += f"<p style='font-style: italic; color: {COLORS['light_text']}; margin: 0 0 10px 15px;'>{formatted_comment}</p>"
        html += "</body>"
        self.txt_notation.setHtml(html)
        # Use a singleShot timer to ensure the layout is complete before scrolling.
        # moveCursor(End) is more robust than manually setting scrollbar values.
        self._scroll_notation_to_bottom()
        QTimer.singleShot(50, self._scroll_notation_to_bottom)

    def _scroll_notation_to_bottom(self):
        doc = self.txt_notation.document()
        if doc and doc.documentLayout():
            doc.documentLayout().documentSize()
        self.txt_notation.moveCursor(QTextCursor.MoveOperation.End)
        self.txt_notation.ensureCursorVisible()
        sb = self.txt_notation.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())

    def _prewarm_settings_dialog(self):
        """Warms up repertoire metadata caches in a background thread without blocking the GUI main thread."""
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        if getattr(self, 'board_widget', None) and (self.board_widget.is_animating or self.animation_moves):
            QTimer.singleShot(500, self._prewarm_settings_dialog)
            return

        first_visible = None
        ordered_active_repos = []
        try:
            vis = self.training_manager.get_visible_repos() if getattr(self, 'training_manager', None) else []
            if vis:
                first_visible = sorted(vis)[0]
                ordered_active_repos = list(self.sorted_repo_names or vis)
        except Exception:
            pass

        def _bg_prewarm():
            try:
                from opening_fenix.gui.dialogs.unified_settings_dialog import prewarm_priority_repertoire_assets
                from opening_fenix.creator.repo_selection_dialog import _load_favorite_repertoires
                tm = getattr(self, 'training_manager', None)
                if tm and hasattr(tm, 'prewarm_repertoire_graph'):
                    favs = _load_favorite_repertoires()
                    # Prioritize active profile's top repertoires (active first, then favorites in active, then remaining)
                    active_favs = [r for r in ordered_active_repos if r in favs]
                    active_rest = [r for r in ordered_active_repos if r not in favs]
                    graph_targets = []
                    for r in (ordered_active_repos[:1] + active_favs + active_rest):
                        if r not in graph_targets:
                            graph_targets.append(r)
                    for vr in graph_targets:
                        tm.prewarm_repertoire_graph(vr, respect_budget=True)
                prewarm_priority_repertoire_assets(
                    profile_name=self.profile_name,
                    explicit_active=ordered_active_repos,
                    first_stat_repo=first_visible,
                )
            except Exception as e:
                logger.debug(f"Background settings metadata prewarm skipped: {e}")

        t = threading.Thread(target=_bg_prewarm, daemon=True, name="SettingsMetadataPrewarm")
        self._prewarm_thread = t
        t.start()

    def open_settings(self):
        from PyQt6 import sip
        if not hasattr(self, 'settings_dialog') or not self.settings_dialog or sip.isdeleted(self.settings_dialog):
            from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog
            self.settings_dialog = SettingsDialog(self)
            self.settings_dialog.finished.connect(self._on_settings_closed)
        else:
            if hasattr(self.settings_dialog, 'on_reopen'):
                self.settings_dialog.on_reopen()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def open_storage_settings(self):
        self.open_settings()
        if hasattr(self, 'settings_dialog') and self.settings_dialog and hasattr(self.settings_dialog, 'navigate_to_storage'):
            self.settings_dialog.navigate_to_storage()

    def _on_settings_closed(self):
        self.refresh_repertoire_buttons()
        self.update_settings_from_manager()
        try:
            from opening_fenix.core.services.cloud_sync_manager import CloudSyncManager
            CloudSyncManager.instance().refresh_status()
        except Exception:
            pass
        self._do_update_stats_display()

    def update_settings_from_manager(self):
        self.apply_theme()
        self.btn_auto_continue.setChecked(not self.training_manager.get_setting("stop_at_variation_end"))

    def apply_theme(self):
        t_name = self.training_manager.get_setting("theme") or get_config_dict().get("theme") or "Braun (Klassisch)"
        self.board_widget.set_theme(t_name)
        hl_color = self.training_manager.get_setting("highlight_color") or get_config_dict().get("highlight_color") or "Gelb (Standard)"
        self.board_widget.set_highlight_color(hl_color)

    def set_master_volume(self, volume):
        if hasattr(self, 'sounds'):
            for sound in self.sounds.values(): sound.setVolume(volume / 100.0)

    def toggle_learning_mode(self):
        self.training_mode = 'new' if self.btn_learn_new.isChecked() else 'due'
        self.change_repertoire(self.repertoire_manager.active_repertoire_name, reset_filter=False)

    def toggle_auto_continue_btn(self):
        self._cancel_auto_continue()
        self.training_manager.set_setting("stop_at_variation_end", not self.btn_auto_continue.isChecked())
        # Invalidate preloaded challenge since the auto-continue preference changed
        self._preloaded_challenge = None

    def switch_profile(self):
        self.switch_requested = True; self.close()

    def handle_profile_button_click(self):
        if is_free_training_profile(self.profile_name):
            menu = QMenu(self)
            act_setup = QAction(tr_ui("main_window.menu_setup_open_training", "🎯 Training anpassen (Repertoire, Level, Variation)"), self)
            act_setup.triggered.connect(self.open_free_training_setup)
            act_switch = QAction(tr_ui("main_window.menu_switch_profile", "👤 Profil wechseln"), self)
            act_switch.triggered.connect(self.switch_profile)
            menu.addAction(act_setup)
            menu.addSeparator()
            menu.addAction(act_switch)
            menu.exec(self.btn_switch_profile.mapToGlobal(QPoint(0, self.btn_switch_profile.height())))
        else:
            self.switch_profile()

    def open_free_training_setup(self):
        from opening_fenix.gui.dialogs.open_training_dialog import OpenTrainingSetupDialog
        from opening_fenix.core.db.models import TrainingData

        dlg = OpenTrainingSetupDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            selections = dlg.get_selections()
            selected_repo = selections[0]
            selected_level = selections[1]
            selected_variation = selections[2]
            selected_comment_lang = selections[3] if len(selections) > 3 else "auto"
            if selected_repo:
                self.training_manager.set_setting("comment_language", selected_comment_lang)
                if hasattr(self.training_manager, 'set_comment_language'):
                    self.training_manager.set_comment_language(selected_comment_lang, selected_repo)
                self.change_repertoire(selected_repo)
                self.training_manager.set_active_level(selected_level, selected_repo)
                self.set_variation_filter(selected_variation)
                if self.training_manager.user_session:
                    try:
                        self.training_manager.user_session.query(TrainingData).filter_by(
                            repertoire_name=selected_repo
                        ).delete(synchronize_session=False)
                        self.training_manager.user_session.commit()
                    except Exception:
                        pass
                self.training_manager._td_cache = None
                self.training_manager._reachable_moves_cache = None
                self.training_manager._last_stats_cache = None
                
                self.update_stats_display()
                QTimer.singleShot(100, self.on_smart_click)

    def init_sounds(self):
        volume = self.training_manager.get_setting("master_volume")
        if volume is None:
            volume = 100
        vol_float = max(0.0, min(1.0, float(volume) / 100.0))
        for s in ["move", "capture", "error"]:
            path = os.path.join(get_base_path(), "assets", "sounds", f"{s}.wav")
            if os.path.exists(path):
                if sys.platform == "win32":
                    self.sounds[s] = _WinAsyncSoundEffect(s, os.path.abspath(path), vol_float)
                else:
                    eff = QSoundEffect()
                    eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                    eff.setVolume(vol_float)
                    self.sounds[s] = eff

    def play_sound(self, name):
        if name in self.sounds: self.sounds[name].play()

    def init_animation(self):
        self.board_widget.piece_slide_finished.connect(self.animation_step)
        self.board_widget.skip_all_animations_requested.connect(self.skip_all_animations)

    def start_animation(self, path_to_animate, anim_ctx=None):
        self._turbo_leadup_remaining = 0
        if path_to_animate:
             self.animation_moves = list(path_to_animate)
             self._advance_animation_sequence()
             return

        move_id = getattr(self.current_move_obj, 'id', None)
        if (
            anim_ctx
            and anim_ctx.get('move_id') == move_id
            and anim_ctx.get('var_filter') == self.active_variation_filter
            and anim_ctx.get('history')
        ):
            history = anim_ctx['history']
        else:
            history = self.repertoire_manager.get_history_for_move(
                self.current_move_obj,
                variation_name=self.active_variation_filter,
                training_manager=self.training_manager,
            )
        self._cached_anim_history = (move_id, self.active_variation_filter, history)
        full_moves = [h['san'] for h in history[:-1]]
        def clean_fen(f): return " ".join(f.split(" ")[:4])
        
        # ── VARIATION FILTER TRUNCATION ──
        reset_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        if self.active_variation_filter:
            entry_fen = self.active_variation_entry_fen
            if entry_fen:
                # Identify where the variation starts in the history
                c_entry = clean_fen(entry_fen)
                boundary_idx = -1
                for i, item in enumerate(history[:-1]):
                    if clean_fen(item['fen']) == c_entry:
                        boundary_idx = i
                        break
                
                # Truncate to start only from variation boundary IF current move is inside the variation
                if boundary_idx != -1:
                    reset_fen = entry_fen
                    full_moves = full_moves[boundary_idx + 1:]
                    history = history[boundary_idx + 1:]
                else:
                    # Current move is a lead-up move starting BEFORE the variation entry point
                    # Reset fen remains the standard starting FEN
                    pass

        current_fen = clean_fen(self.board_widget.board.fen())
        target_fen = clean_fen(self.current_move_obj.from_position.fen)
        if current_fen == target_fen: self.finalize_animation_state(); return

        # ?? SMART LEAD-UP SKIP (NO VARIATION FILTER) ??
        turbo_boundary_idx = -1
        if not self.active_variation_filter and self.current_move_obj and hasattr(self.training_manager, 'should_skip_leadup_animation'):
            use_precomputed = (
                anim_ctx is not None
                and anim_ctx.get('move_id') == move_id
                and anim_ctx.get('var_filter') is None
                and anim_ctx.get('var_name') is not None
            )
            var_name = anim_ctx['var_name'] if use_precomputed else self.training_manager.get_move_variation_name(self.current_move_obj)
            if var_name:
                entry_fen = anim_ctx['entry_fen'] if use_precomputed else self.repertoire_manager.get_variation_entry_point_fen(var_name)
                if entry_fen:
                    c_entry = clean_fen(entry_fen)
                    boundary_idx = -1
                    for i, item in enumerate(history[:-1]):
                        if clean_fen(item['fen']) == c_entry:
                            boundary_idx = i
                            break
                    if boundary_idx != -1:
                        already_in_variation = any(clean_fen(item['fen']) == current_fen for item in history[boundary_idx:-1])
                        if not already_in_variation:
                            if self.training_manager.should_skip_leadup_animation(
                                var_name,
                                history[:boundary_idx + 1],
                                training_mode=getattr(self, 'training_mode', 'review'),
                                record_session_view=True,
                            ):
                                skip_style = self.training_manager.get_setting('leadup_skip_style') or 'instant'
                                if skip_style == 'turbo':
                                    turbo_boundary_idx = boundary_idx
                                else:
                                    reset_fen = entry_fen
                                    full_moves = full_moves[boundary_idx + 1:]
                                    history = history[boundary_idx + 1:]
        
        match_idx = -1
        # Check against reset point (STARTING_FEN or VARIATION_ENTRY_FEN)
        if current_fen == clean_fen(reset_fen):
            match_idx = -1
        else:
            for i, item in enumerate(history[:-1]):
                if clean_fen(item['fen']) == current_fen:
                    match_idx = i; break
        
        if match_idx != -1 or current_fen == clean_fen(reset_fen):
            self.animation_moves = full_moves[match_idx + 1:]
            if turbo_boundary_idx != -1:
                self._turbo_leadup_remaining = max(0, (turbo_boundary_idx + 1) - (match_idx + 1))
            logger.debug(f"Animation: starting from match_idx {match_idx}, {len(self.animation_moves)} moves remaining.")
        else:
            logger.info(f"Animation: current board position not found in history. Resetting to {reset_fen}.")
            self.board_widget.set_fen(reset_fen)
            self.animation_moves = full_moves
            if turbo_boundary_idx != -1:
                self._turbo_leadup_remaining = max(0, turbo_boundary_idx + 1)

        if not self.animation_moves:
            self.finalize_animation_state()
        else:
            self._advance_animation_sequence()

    def _advance_animation_sequence(self):
        if not self.animation_moves: self.finalize_animation_state(); return
        move_san = self.animation_moves.pop(0)
        try:
            move = self.board_widget.board.parse_san(move_san)
            piece = self.board_widget.board.piece_at(move.from_square)
            if not piece:
                logger.error(f"Animation: No piece found at {chess.square_name(move.from_square)} for move {move_san}")
                self.finalize_animation_state()
                return
            duration_override = None
            if getattr(self, '_turbo_leadup_remaining', 0) > 0:
                self._turbo_leadup_remaining -= 1
                duration_override = 45
            self.board_widget.start_piece_slide(piece, move.from_square, move.to_square, move, duration_override=duration_override)
        except Exception as e:
            logger.error(f"Animation: Failed to parse or play move '{move_san}': {e}")
            self.finalize_animation_state()

    def animation_step(self):
        is_cap = getattr(self.board_widget, 'last_move_was_capture', False)
        self.play_sound("capture" if is_cap else "move")
        self._advance_animation_sequence()

    def skip_all_animations(self):
        """Instantly finishes all pending moves in the current animation sequence."""
        self._turbo_leadup_remaining = 0
        if not (self.board_widget.is_animating or self.animation_moves):
            return

        is_cap = False
        if self.board_widget.is_animating and self.board_widget.animating_piece_data:
            m = self.board_widget.animating_piece_data['move']
            if self.board_widget.board.is_capture(m):
                is_cap = True
        self.play_sound("capture" if is_cap else "move")
        
        # 1. Handle currently sliding piece
        if self.board_widget.is_animating:
            if self.board_widget.animating_piece_data:
                move = self.board_widget.animating_piece_data['move']
                self.board_widget.board.push(move)
                self.board_widget.last_move = move
            self.board_widget.abort_piece_slide()
            
        # 2. Handle all remaining moves in the sequence
        while self.animation_moves:
            move_san = self.animation_moves.pop(0)
            try:
                move = self.board_widget.board.parse_san(move_san)
                self.board_widget.board.push(move)
                self.board_widget.last_move = move
            except:
                pass
                
        # 3. Finalize UI state
        self.finalize_animation_state()

    def finalize_animation_state(self):
        self._flush_pending_stats()
        self.set_button_state('waiting_for_move')
        
        # FIX: If we are in "new" learning mode, immediately show the solution arrow
        if self.training_mode == 'new' and self.current_move_obj:
            self.board_widget.solution_arrow = chess.Move.from_uci(self.current_move_obj.uci)
        else:
            self.board_widget.solution_arrow = None

        # Keep board clean during intermediate solving challenges (drawings shown only at variation end)
        self.board_widget.clear_user_drawings()
            
        self.board_widget.update()
        cached_hist = None
        cached = getattr(self, '_cached_anim_history', None)
        self._cached_anim_history = None
        if cached and self.current_move_obj and cached[0] == getattr(self.current_move_obj, 'id', None) and cached[1] == self.active_variation_filter:
            cached_hist = cached[2]
        self.update_notation_display(temp_hist=cached_hist, reveal_move=(self.training_mode == 'new'))
        
        # Preload the next challenge in the background while user is thinking
        self._preloaded_challenge = None
        QTimer.singleShot(0, self.preload_next_challenge)

    def open_lichess_analysis(self):
        if not self.repertoire_manager.active_repertoire_name: return
        url = f"https://lichess.org/analysis/{self.board_widget.board.fen().replace(' ', '_')}"
        webbrowser.open(url)
        
    def on_repertoire_deleted(self):
        """Handles UI updates after a repertoire is deleted."""
        self.refresh_repertoire_buttons()
        visible_repos = self.training_manager.get_visible_repos()
        if visible_repos:
            self.change_repertoire(visible_repos[0])
        else:
            self.change_repertoire(None)

    def open_repertoire_folder(self):
        """Opens the active repertoire's folder in Windows Explorer."""
        repo_name = self.repertoire_manager.active_repertoire_name
        if not repo_name:
            return
        
        from opening_fenix.core.utils import get_repertoire_dir
        path = get_repertoire_dir(repo_name)
        
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, tr_ui("main.dlg_folder_not_found_title", "Ordner nicht gefunden"), f"Der Repertoire-Ordner konnte nicht gefunden werden:\n{path}")

    def repolish(self, widget):
        if widget:
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _fit_board_splitter(self):
        if not getattr(self, '_auto_size_board', True):
            return
        if not hasattr(self, 'main_splitter') or not hasattr(self, 'board_widget'):
            return
        h = self.main_splitter.height()
        total_w = self.main_splitter.width()
        if h > 100 and total_w > h:
            desired_board_w = h
            desired_side_w = max(scale(280), total_w - desired_board_w)
            cur = self.main_splitter.sizes()
            if len(cur) == 2 and abs(cur[0] - desired_board_w) <= 1 and abs(cur[1] - desired_side_w) <= 1:
                return
            self.main_splitter.setSizes([desired_board_w, desired_side_w])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_board_splitter()

    def _on_screen_changed(self, screen):
        if hasattr(self, 'board_widget') and self.board_widget:
            self.board_widget.update_animation_metrics()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, 'custom_title_bar') and self.custom_title_bar:
                self.custom_title_bar.update_maximize_button()
            if hasattr(self, 'board_widget') and self.board_widget:
                self.board_widget.update_animation_metrics()
            self._fit_board_splitter()

    def closeEvent(self, event):
        """Clean up resources before closing."""
        self._cancel_auto_continue()
        self._repo_preload_gen += 1
        self._challenge_preload_gen += 1
        self._flush_pending_stats()
        self._flush_db_commits()
        self._flush_pending_stats()
        from PyQt6.QtWidgets import QDialog, QApplication
        for w in list(QApplication.topLevelWidgets()):
            if isinstance(w, QDialog) and w != self:
                try:
                    w.reject()
                except:
                    try: w.close()
                    except: pass

        if hasattr(self, 'creator_window') and self.creator_window:
            try:
                self.creator_window.close()
            except: pass

        if hasattr(self, '_bg_cloud_sync_worker') and self._bg_cloud_sync_worker and self._bg_cloud_sync_worker.isRunning():
            try:
                self._bg_cloud_sync_worker.wait(500)
            except Exception: pass
        try:
            from opening_fenix.core.services.cloud_sync_manager import CloudSyncManager
            CloudSyncManager.instance().wait_for_active_sync(500)
        except Exception:
            pass
        if hasattr(self, 'backup_worker') and self.backup_worker and self.backup_worker.isRunning():
            try:
                self.backup_worker.requestInterruption()
                self.backup_worker.wait(200)
            except Exception: pass
        if hasattr(self, 'update_checker') and self.update_checker and self.update_checker.isRunning():
            try:
                self.update_checker.requestInterruption()
                self.update_checker.wait(200)
            except Exception: pass

        with self._preload_lock:
            pass
        if self.training_manager:
            self.training_manager.close()
        if self.repertoire_manager:
            self.repertoire_manager.close()
        super().closeEvent(event)
