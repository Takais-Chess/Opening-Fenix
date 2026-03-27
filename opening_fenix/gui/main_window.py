import sys
import os
import json
import chess
import chess.pgn
import webbrowser
import math
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, 
    QVBoxLayout, QLabel, QTextBrowser, QPushButton,
    QCheckBox, QMessageBox, QInputDialog, QDialog, 
    QScrollArea, QTabWidget, QFormLayout,
    QLineEdit, QFileDialog, QListWidget, QProgressBar, 
    QComboBox, QSpinBox, QGroupBox, QFrame, QButtonGroup,
    QGridLayout, QListWidgetItem, QSlider, QScroller, QMenu, QSizePolicy,
    QTabBar, QStackedWidget, QGraphicsDropShadowEffect
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPolygonF, QIcon, QPixmap, QFontMetrics, QAction
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QPoint, QTimer, QUrl, QPointF, QEvent, QSize
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtMultimedia import QSoundEffect

from opening_fenix.core.repertoire import RepertoireManager
from opening_fenix.core.training import TrainingManager
from opening_fenix.core.data_tools import get_base_path, get_user_dir, get_repertoire_analysis_status
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget
from opening_fenix.gui.widgets.charts import PieChartWidget
from opening_fenix.gui.widgets.common import ZoomableTextBrowser, AspectRatioFrame
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog
from opening_fenix.creator.creator_window import CreatorWindow

# Import centralized styles
from opening_fenix.gui.styles import MAIN_WINDOW_STYLE, COLORS
from opening_fenix.gui.widgets.title_bar import CustomTitleBar

class MainWindow(QMainWindow):
    switch_requested = False
    def __init__(self, profile_name):
        super().__init__()
        self.profile_name = profile_name
        self.setWindowTitle(f"Opening Fenix - {profile_name}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        
        win_icon_path = os.path.join(get_base_path(), "assets", "Logo", "favicon.ico")
        if os.path.exists(win_icon_path):
            self.setWindowIcon(QIcon(win_icon_path))

        self.setMinimumSize(1000, 700)
        self.resize(1400, 850)
        
        self.repertoire_manager = RepertoireManager(profile_name=profile_name)
        self.training_manager = TrainingManager(profile_name=profile_name, repertoire_manager=self.repertoire_manager)
        
        self.current_move_obj = None
        self.waiting_for_next = False
        self.show_comments = True
        self.mode = "TRAINER"
        self.training_mode = 'due' 
        self.button_state = 'start' 
        self.active_variation_filter = None 
        
        self.creator_window = None
        self.sounds = {}
        self.animation_moves = []
        self.sorted_repo_names = None
        
        # Debounce timer for updating the large stats pie chart
        self.stats_update_timer = QTimer()
        self.stats_update_timer.setSingleShot(True)
        self.stats_update_timer.timeout.connect(self._do_update_stats_display)

        self.init_ui()
        self.init_sounds()
        self.init_animation()
        self.previous_fen_for_animation = None
        
        self.refresh_repertoire_buttons()
        visible_repos = self.training_manager.get_visible_repos()
        if visible_repos:
            self.change_repertoire(visible_repos[0])
        else:
            self.change_repertoire(None)
        
        self.set_button_state('start')

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.trigger_board_adjust)
        QTimer.singleShot(100, self.trigger_board_adjust)

    def trigger_board_adjust(self):
        if hasattr(self, 'board_panel'):
            self.board_panel.setMinimumWidth(0)
            self.board_panel.setMaximumWidth(16777215)
            self.board_panel.adjust_size()
            if self.centralWidget() and self.centralWidget().layout():
                self.centralWidget().layout().activate()
            self.board_widget.update()

    def init_ui(self):
        self.setStyleSheet(MAIN_WINDOW_STYLE)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 0. CUSTOM TITLE BAR (MERGED) ---
        self.custom_title_bar = CustomTitleBar(self, title=f" {self.profile_name}")
        self.custom_title_bar.setFixedHeight(65)
        main_layout.addWidget(self.custom_title_bar)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(10, 6, 20, 6)
        top_layout.setSpacing(0)

        self.btn_scroll_left = QPushButton("◄")
        self.btn_scroll_left.setFixedSize(30, 40)
        self.btn_scroll_left.setStyleSheet("border: none; background: transparent; color: #8d6e63; font-size: 18px;")
        self.btn_scroll_left.clicked.connect(self.scroll_tabs_left)
        self.btn_scroll_left.hide()

        self.btn_scroll_right = QPushButton("►")
        self.btn_scroll_right.setFixedSize(30, 40)
        self.btn_scroll_right.setStyleSheet("border: none; background: transparent; color: #8d6e63; font-size: 18px;")
        self.btn_scroll_right.clicked.connect(self.scroll_tabs_right)
        self.btn_scroll_right.hide()

        self.repo_scroll = QScrollArea()
        self.repo_scroll.setWidgetResizable(True)
        self.repo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.repo_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.repo_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.repo_tabs_widget = QWidget()
        self.repo_tabs_widget.setStyleSheet("background: transparent;")
        self.repo_tabs_layout = QHBoxLayout(self.repo_tabs_widget)
        self.repo_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.repo_tabs_layout.setSpacing(15)
        self.repo_button_group = QButtonGroup(self)
        self.repo_button_group.buttonClicked.connect(self.on_repertoire_button_clicked)
        
        self.repo_scroll.setWidget(self.repo_tabs_widget)
        QScroller.grabGesture(self.repo_scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        self.repo_scroll.horizontalScrollBar().valueChanged.connect(self.update_tab_scroll_arrows)

        top_layout.addWidget(self.btn_scroll_left)
        top_layout.addWidget(self.repo_scroll, 1)
        top_layout.addWidget(self.btn_scroll_right)

        top_right_container = QWidget()
        top_right_layout = QHBoxLayout(top_right_container)
        top_right_layout.setSpacing(15)
        top_right_layout.setContentsMargins(15, 0, 15, 0)

        self.btn_filter = QPushButton("Filter ▾")
        self.btn_filter.setFlat(True)
        # Added subtle hover styling for the top bar flat buttons
        self.btn_filter.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: 14px; border-radius: 18px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_filter.clicked.connect(self.show_filter_menu)

        self.lbl_elo = QLabel("🎓 800")
        self.lbl_elo.setStyleSheet(f"font-size: 20px; color: {COLORS['burnt_orange']}; font-weight: bold;")
        self.btn_switch_profile = QPushButton(self.profile_name)
        self.btn_switch_profile.setFlat(True)
        self.btn_switch_profile.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: 14px; border-radius: 18px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_switch_profile.clicked.connect(self.switch_profile)
        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setFixedSize(40, 40)
        self.btn_settings.setStyleSheet(f"""
            QPushButton {{ font-size: 24px; border: none; background: transparent; border-radius: 20px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_settings.clicked.connect(self.open_settings)

        top_right_layout.addWidget(self.btn_filter)
        top_right_layout.addWidget(self.lbl_elo)
        top_right_layout.addWidget(self.btn_switch_profile)
        top_right_layout.addWidget(self.btn_settings)
        top_layout.addWidget(top_right_container)
        
        # Apply GlassPill classes and small drop shadows to the top elements
        for pill in [self.repo_scroll, top_right_container]:
            pill.setProperty("class", "GlassPill")
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(10)
            shadow.setColor(QColor(0, 0, 0, 30))
            shadow.setOffset(0, 4)
            pill.setGraphicsEffect(shadow)
        
        # Inject merged top bar into the custom title bar before the stretch and window controls
        self.custom_title_bar.layout.insertLayout(1, top_layout, 1)

        # --- 2. CONTENT AREA ---
        content_container = QWidget()
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(20)

        self.board_panel = AspectRatioFrame()
        self.board_panel.setObjectName("BoardPanel")
        board_inner_layout = QVBoxLayout(self.board_panel)
        board_inner_layout.setContentsMargins(15, 15, 15, 15)
        self.board_widget = ChessBoardWidget(self)
        self.board_widget.move_executed.connect(self.check_user_move)
        board_inner_layout.addWidget(self.board_widget)
        content_layout.addWidget(self.board_panel, 3)

        self.side_panel = QFrame()
        self.side_panel.setObjectName("SidePanel")
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(20, 20, 20, 20)
        side_layout.setSpacing(15)

        side_layout.addWidget(QLabel("NOTATION"), 0, Qt.AlignmentFlag.AlignLeft)
        self.txt_notation = ZoomableTextBrowser()
        self.txt_notation.setObjectName("NotationView")
        self.txt_notation.anchorClicked.connect(self.on_notation_click)
        side_layout.addWidget(self.txt_notation, 1)

        training_hub = QWidget()
        hub_layout = QVBoxLayout(training_hub)
        hub_layout.setContentsMargins(0, 0, 0, 0)
        hub_layout.setSpacing(20)

        stats_actions_row = QHBoxLayout()
        stats_actions_row.setSpacing(15)
        self.progress_bar = PieChartWidget()
        self.progress_bar.setMinimumSize(160, 160)
        stats_actions_row.addWidget(self.progress_bar, 1)

        actions_grid = QGridLayout()
        actions_grid.setSpacing(8)
        
        # UPGRADED ICONS
        self.btn_learn_new = QPushButton("🧠")
        self.btn_learn_new.setObjectName("ActionButton")
        self.btn_learn_new.setCheckable(True)
        self.btn_learn_new.clicked.connect(self.toggle_learning_mode)
        self.btn_learn_new.setToolTip("<b>Lern-Modus</b><br>Trainiere neue Züge, die du noch nicht kennst.")
        
        self.btn_auto_continue = QPushButton("⚡")
        self.btn_auto_continue.setObjectName("ActionButton")
        self.btn_auto_continue.setCheckable(True)
        self.btn_auto_continue.clicked.connect(self.toggle_auto_continue_btn)
        self.btn_auto_continue.setToolTip("<b>Auto-Weiter</b><br>Springe nach einem korrekten Zug automatisch zum nächsten.")
        
        # Use custom Lichess Icon
        self.btn_lichess = QPushButton()
        self.btn_lichess.setObjectName("ActionButton")
        lichess_icon_path = os.path.join(get_base_path(), "assets", "Icons", "lichess.png")
        if os.path.exists(lichess_icon_path):
            self.btn_lichess.setIcon(QIcon(lichess_icon_path))
            self.btn_lichess.setIconSize(QSize(24, 24))
        else:
            self.btn_lichess.setText("🔬")
        self.btn_lichess.clicked.connect(self.open_lichess_analysis)
        self.btn_lichess.setToolTip("<b>Lichess Analyse</b><br>Öffne die aktuelle Stellung in der Lichess-Analyse.")
        
        self.btn_creator = QPushButton("✏️")
        self.btn_creator.setObjectName("ActionButton")
        self.btn_creator.clicked.connect(self.open_creator_at_current_position)
        self.btn_creator.setToolTip("<b>Repertoire Creator</b><br>Bearbeite dein Repertoire an dieser Position.")
        
        actions_grid.addWidget(self.btn_learn_new, 0, 0)
        actions_grid.addWidget(self.btn_auto_continue, 0, 1)
        actions_grid.addWidget(self.btn_lichess, 1, 0)
        actions_grid.addWidget(self.btn_creator, 1, 1)

        stats_actions_row.addLayout(actions_grid, 1)
        hub_layout.addLayout(stats_actions_row)

        self.btn_smart = QPushButton("TRAINING STARTEN")
        self.btn_smart.setObjectName("StartButton"); self.btn_smart.clicked.connect(self.on_smart_click)
        hub_layout.addWidget(self.btn_smart)

        side_layout.addWidget(training_hub)
        content_layout.addWidget(self.side_panel, 2)
        main_layout.addWidget(content_container, 1)

        # Apply Drop Shadows for glass depth
        for panel in [self.board_panel, self.side_panel]:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(0, 0, 0, 50))
            shadow.setOffset(0, 6)
            panel.setGraphicsEffect(shadow)

    def scroll_tabs_left(self):
        sb = self.repo_scroll.horizontalScrollBar()
        sb.setValue(sb.value() - 100)

    def scroll_tabs_right(self):
        sb = self.repo_scroll.horizontalScrollBar()
        sb.setValue(sb.value() + 100)

    def update_tab_scroll_arrows(self):
        sb = self.repo_scroll.horizontalScrollBar()
        self.btn_scroll_left.setVisible(sb.value() > 0)
        self.btn_scroll_right.setVisible(sb.value() < sb.maximum())

    def on_repertoire_button_clicked(self, button):
        self.change_repertoire(button.property("repo_name"))

    def change_repertoire(self, repo_name):
        # Cancel any ongoing animations before switching
        self.animation_moves = []
        if hasattr(self.board_widget, 'abort_piece_slide'):
            self.board_widget.abort_piece_slide()

        for btn in self.repo_button_group.buttons():
            btn.setChecked(btn.property("repo_name") == repo_name)
        
        # Reset all caches and trainer state
        self.repertoire_manager.set_active_repertoire(repo_name)
        self.training_manager.on_repertoire_changed()
        
        self.active_variation_filter = None
        self.btn_filter.setText("Filter ▾")
        
        if repo_name:
            is_player_white = self.repertoire_manager.get_repertoire_color() == 'w'
            self.board_widget.flipped = not is_player_white
            self.board_widget.set_fen(chess.STARTING_FEN)
            self.update_settings_from_manager()
        
        # Immediate update of large chart, mini charts update automatically in refresh_repertoire_buttons
        self._do_update_stats_display() 
        
        self.txt_notation.clear()
        self.set_button_state('start')
        self.current_move_obj = None
        self.refresh_repertoire_buttons()

        # Auto-activate "Neue lernen" when repertoire has no due or learned moves yet
        if self.repertoire_manager.repo_session:
            new, due, done_dist = self.training_manager.get_stats()
            learned = sum(done_dist.values()) if isinstance(done_dist, dict) else 0
            if due == 0 and learned == 0:
                self.btn_learn_new.setChecked(True)
                self.training_mode = 'new'

    def show_filter_menu(self):
        if not self.repertoire_manager.active_repertoire_name: return
        menu = QMenu(self)
        action_all = QAction(f"Alle {self.repertoire_manager.active_repertoire_name}", self)
        action_all.triggered.connect(lambda: self.set_variation_filter(None))
        menu.addAction(action_all); menu.addSeparator()
        structure = self.repertoire_manager.get_variation_structure()
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
        self.active_variation_filter = var_name
        self.btn_filter.setText(f"{var_name[:12]}.. ▾" if var_name and len(var_name) > 12 else (var_name or "Filter") + " ▾")
        self.current_move_obj = None; self.load_next_challenge(); self.update_stats_display()

    def refresh_repertoire_buttons(self):
        scroll_pos = self.repo_scroll.horizontalScrollBar().value()
        while self.repo_tabs_layout.count():
            item = self.repo_tabs_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        visible_repos = self.training_manager.get_visible_repos()
        active_repo = self.repertoire_manager.active_repertoire_name
        
        # 1. Collect stats for all visible repertoires and sort if necessary
        repo_data = [] # List of (repo_name, stats_tuple)
        original_repo = active_repo
        
        for repo_name in visible_repos:
            self.repertoire_manager.set_active_repertoire(repo_name)
            self.training_manager.on_repertoire_changed()
            stats = (0, 0, {})
            if self.repertoire_manager.repo_session:
                stats = self.training_manager.get_stats()
            repo_data.append((repo_name, stats))
            
        # Restore active repertoire
        self.repertoire_manager.set_active_repertoire(original_repo)
        self.training_manager.on_repertoire_changed()
        
        if self.sorted_repo_names is None:
            # Sort by due moves (stats[1]) descending
            repo_data.sort(key=lambda x: x[1][1], reverse=True)
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
            mini_donut.setFixedSize(24, 24)
            mini_donut.update_stats(new, due, dist)

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
        Uses a short timer to avoid blocking the main thread during fast move inputs.
        """
        if not self.stats_update_timer.isActive():
            self.stats_update_timer.start(50) # 50ms delay
            
    def _do_update_stats_display(self):
        if not self.repertoire_manager.active_repertoire_name:
            self.progress_bar.update_stats(0, 0, {})
            self.lbl_elo.setText("🎓 800")
            return
        new, due, done_dist = self.training_manager.get_stats(variation_filter=self.active_variation_filter)
        self.progress_bar.update_stats(new, due, done_dist)
        
        # Update Elo display
        elo = self.training_manager.get_current_elo()
        self.lbl_elo.setText(f"🎓 {elo}")

    def load_next_challenge(self, last_success=False, last_move=None):
        self.waiting_for_next = False
        if not self.repertoire_manager.active_repertoire_name: return

        path_to_animate = []
        if last_success and last_move:
            next_move, path = self.training_manager.get_next_move(mode=self.training_mode, last_move_obj=last_move, last_was_success=True, only_continuation=True, variation_filter=self.active_variation_filter)
            if next_move:
                self.current_move_obj = next_move
                path_to_animate = path
            elif self.training_manager.get_setting("stop_at_variation_end"):
                # Variation ended, stay on the current notation
                self.current_move_obj = last_move
                self.update_notation_display(reveal_move=True)
                self.set_button_state('start')
                self.current_move_obj = None # Reset so next start loads a new challenge
                return
            else:
                self.current_move_obj = None

        if not self.current_move_obj:
            self.current_move_obj, _ = self.training_manager.get_next_move(mode=self.training_mode, variation_filter=self.active_variation_filter)

        if self.current_move_obj:
            self.start_animation(path_to_animate)
            # Fix: when learning new moves, we always want to see the move we are supposed to learn.
            # In due mode, we hide it to test the user.
            reveal = (self.training_mode == 'new')
            self.update_notation_display(reveal_move=reveal)
            
        else:
            self.btn_smart.setText("🎉 FERTIG!")
            self.btn_smart.setEnabled(False)

    def on_notation_click(self, url):
        fen = url.toString().replace("fen:", "")
        self.open_creator_at_current_position(fen)

    def open_creator_at_current_position(self, fen=None):
        if not self.repertoire_manager.active_repertoire_name: return
        target_fen = fen or self.board_widget.board.fen()
        if self.creator_window and self.creator_window.isVisible():
            self.creator_window.set_board_to_fen(target_fen)
            self.creator_window.raise_(); self.creator_window.activateWindow()
        else:
            self.creator_window = CreatorWindow(repertoire_name=self.repertoire_manager.active_repertoire_name, initial_fen=target_fen)
            self.creator_window.showMaximized()

    def set_button_state(self, state):
        self.button_state = state
        if state == 'start':
            self.btn_smart.setText("TRAINING STARTEN"); self.btn_smart.setEnabled(True)
        elif state == 'waiting_for_move':
            if self.training_mode == 'new':
                self.btn_smart.setText("SPIELE DEN ZUG"); self.btn_smart.setEnabled(False)
            else:
                self.btn_smart.setText("DU BIST AM ZUG"); self.btn_smart.setEnabled(False)
        elif state == 'correct':
            self.btn_smart.setText("KORREKT!"); self.btn_smart.setEnabled(False)
        elif state == 'show_solution_prompt':
            self.btn_smart.setText("FALSCH! LÖSUNG ANZEIGEN"); self.btn_smart.setEnabled(True)

    def on_smart_click(self):
        if self.button_state == 'start':
            self.load_next_challenge()
        elif self.button_state == 'show_solution_prompt':
            self.board_widget.solution_arrow = chess.Move.from_uci(self.current_move_obj.uci)
            self.board_widget.update()
            self.btn_smart.setEnabled(False)

    def check_user_move(self, move):
        if self.button_state not in ['waiting_for_move', 'show_solution_prompt'] or not self.current_move_obj: return
        if move.uci() == self.current_move_obj.uci:
            self.play_sound("move")
            self.board_widget.board.push(move)
            self.board_widget.solution_arrow = None
            self.board_widget.update()

            if self.button_state == 'waiting_for_move':
                self.training_manager.register_success(self.current_move_obj.id, True)
                self.update_stats_display() # Update big donut chart after successful move

            self.set_button_state('correct')
            self.update_notation_display(reveal_move=True)
            QTimer.singleShot(self.training_manager.get_setting("auto_delay") or 200, lambda: self.load_next_challenge(True, self.current_move_obj))
        else:
            if self.repertoire_manager.check_if_alternative_good_move(self.current_move_obj, move.uci()):
                self.play_sound("move")
                self.btn_smart.setText("GUTER ZUG (NICHT IM REPERTOIRE)")
                QTimer.singleShot(1500, lambda: self.set_button_state(self.button_state))
                return

            self.play_sound("error")
            if self.button_state == 'waiting_for_move':
                self.training_manager.register_success(self.current_move_obj.id, False)
                self.set_button_state('show_solution_prompt')
                self.update_stats_display() # Update big donut chart after failed move

    def update_notation_display(self, temp_hist=None, reveal_move=False):
        hist = temp_hist or self.repertoire_manager.get_history_for_move(self.current_move_obj)
        html = "<body style='line-height: 1.6;'>"
        start_move_offset = self.repertoire_manager.get_repertoire_start_move() - 1
        for i, item in enumerate(hist):
            is_last = (i == len(hist) - 1)
            if is_last and not reveal_move: break
            move_num = (i // 2) + 1 + start_move_offset
            if i % 2 == 0: html += f"<b>{move_num}.</b> "
            style = f"text-decoration:none; color:{COLORS['brown_text']}; font-weight:bold;"
            if is_last and reveal_move: style += f" background-color: {COLORS['burnt_orange']}; color: white; border-radius: 3px; padding: 0 2px;"
            nag_map = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
            nag_text = nag_map.get(item.get('nag'), "")
            html += f"<a href='fen:{item['fen']}' style='{style}'>{item['san']}{nag_text}</a> "
            if item.get('comment'): html += f"<p style='font-style: italic; color: {COLORS['light_text']}; margin: 0 0 10px 15px;'>{item['comment']}</p>"
        html += "</body>"
        self.txt_notation.setHtml(html)
        self.txt_notation.verticalScrollBar().setValue(self.txt_notation.verticalScrollBar().maximum())

    def open_settings(self):
        SettingsDialog(self).exec()
        self.refresh_repertoire_buttons()
        self.update_settings_from_manager()

    def update_settings_from_manager(self):
        self.apply_theme()
        self.btn_auto_continue.setChecked(not self.training_manager.get_setting("stop_at_variation_end"))

    def apply_theme(self):
        t_name = self.training_manager.get_setting("theme") or "Blau (Turnier)"
        self.board_widget.set_theme(t_name)

    def set_master_volume(self, volume):
        if hasattr(self, 'sounds'):
            for sound in self.sounds.values(): sound.setVolume(volume / 100.0)

    def toggle_learning_mode(self):
        self.training_mode = 'new' if self.btn_learn_new.isChecked() else 'due'
        self.change_repertoire(self.repertoire_manager.active_repertoire_name)

    def toggle_auto_continue_btn(self):
        self.training_manager.set_setting("stop_at_variation_end", not self.btn_auto_continue.isChecked())

    def switch_profile(self):
        self.switch_requested = True; self.close()

    def init_sounds(self):
        volume = self.training_manager.get_setting("master_volume") or 100
        for s in ["move", "capture", "error"]:
            path = os.path.join(get_base_path(), "assets", "sounds", f"{s}.wav")
            if os.path.exists(path):
                eff = QSoundEffect(); eff.setSource(QUrl.fromLocalFile(os.path.abspath(path))); eff.setVolume(volume / 100.0); self.sounds[s] = eff

    def play_sound(self, name):
        if name in self.sounds: self.sounds[name].play()

    def init_animation(self):
        self.board_widget.piece_slide_finished.connect(self.animation_step)

    def start_animation(self, path_to_animate):
        if path_to_animate:
             self.animation_moves = path_to_animate
             self._advance_animation_sequence()
             return

        history = self.repertoire_manager.get_history_for_move(self.current_move_obj)
        full_moves = [h['san'] for h in history[:-1]]
        def clean_fen(f): return " ".join(f.split(" ")[:4])
        current_fen = clean_fen(self.board_widget.board.fen())
        target_fen = clean_fen(self.current_move_obj.from_position.fen)
        if current_fen == target_fen: self.finalize_animation_state(); return
        match_idx = -1
        if current_fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -": match_idx = -1
        else:
            for i, item in enumerate(history[:-1]):
                if clean_fen(item['fen']) == current_fen: match_idx = i; break
        if match_idx != -1 or current_fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -":
            self.animation_moves = full_moves[match_idx + 1:]
        else:
            self.board_widget.set_fen(chess.STARTING_FEN); self.animation_moves = full_moves
        if not self.animation_moves: self.finalize_animation_state()
        else: self._advance_animation_sequence()

    def _advance_animation_sequence(self):
        if not self.animation_moves: self.finalize_animation_state(); return
        move_san = self.animation_moves.pop(0)
        try:
            move = self.board_widget.board.parse_san(move_san)
            piece = self.board_widget.board.piece_at(move.from_square)
            self.board_widget.start_piece_slide(piece, move.from_square, move.to_square, move)
        except: self.finalize_animation_state()

    def animation_step(self):
        self.play_sound("move")
        self._advance_animation_sequence()

    def finalize_animation_state(self):
        self.set_button_state('waiting_for_move')
        
        # FIX: If we are in "new" learning mode, immediately show the solution arrow
        if self.training_mode == 'new' and self.current_move_obj:
            self.board_widget.solution_arrow = chess.Move.from_uci(self.current_move_obj.uci)
        else:
            self.board_widget.solution_arrow = None
            
        self.board_widget.update()

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

    def closeEvent(self, event):
        """Clean up resources before closing."""
        if self.training_manager:
            self.training_manager.close()
        if self.repertoire_manager:
            self.repertoire_manager.close()
        super().closeEvent(event)
