import os
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QFormLayout, QComboBox, 
    QHBoxLayout, QLabel, QListWidget, QScrollArea, QFrame, 
    QGroupBox, QSpinBox, QDoubleSpinBox, QPushButton, QCheckBox, QProgressBar, QSlider, 
    QLineEdit, QFileDialog, QMessageBox, QStackedWidget, QListWidgetItem,
    QTextEdit, QGridLayout, QApplication, QAbstractButton, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QIcon, QFont
from PyQt6 import sip
from opening_fenix.core.data_tools import get_base_path, get_user_dir, get_repertoire_analysis_status
from opening_fenix.core.utils import get_elo_display, get_repertoire_comment_stats
from opening_fenix.gui.widgets.board_widget import THEMES

# Import centralized styles
from opening_fenix.gui.styles import COLORS, get_bw_glass_style, set_consistent_icon
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui
from opening_fenix.gui.widgets.common import AutoAdjustButton


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()


class RepoLoadButton(QPushButton):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.repo_name = name
        self.setFixedHeight(scale(50))
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: #111111;
                border: 1.5px solid rgba(0, 0, 0, 0.15);
                border-radius: {scale(8)}px;
                font-size: {scale(15)}px;
                font-weight: 600;
                padding: {scale(5)}px {scale(15)}px;
            }}
            QPushButton:hover {{
                background-color: #111111;
                color: white;
                border-color: #111111;
            }}
        """)


class LoadRepertoireDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("settings.load_repertoire_title", "Repertoire Laden"))
        self.setMinimumSize(scale(520), scale(420))
        self.selected_repo = None
        self.setStyleSheet(get_bw_glass_style())
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        lbl_title = QLabel(tr_ui("settings.select_repertoire_label", "Repertoire auswählen"))
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #111111; margin-bottom: 5px;")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(tr_ui("settings.select_repertoire_sub", "Klicke auf ein Repertoire, um es zu laden."))
        lbl_sub.setStyleSheet("color: #666; font-size: 13px; margin-bottom: 10px;")
        layout.addWidget(lbl_sub)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setSpacing(scale(10))

        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        repo_names = RepertoireService().get_all_repertoires()

        row, col = 0, 0
        for name in sorted(repo_names):
            btn = RepoLoadButton(name)
            btn.clicked.connect(lambda checked, n=name: self.on_repo_click(n))
            self.grid_layout.addWidget(btn, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1

        self.grid_layout.setRowStretch(self.grid_layout.rowCount(), 1)
        self.scroll_area.setWidget(scroll_widget)
        layout.addWidget(self.scroll_area)

        h_btn = QHBoxLayout()
        b_cancel = QPushButton(tr_ui("login.cancel", "Abbrechen"))
        b_cancel.clicked.connect(self.reject)
        h_btn.addStretch()
        h_btn.addWidget(b_cancel)
        layout.addLayout(h_btn)

    def on_repo_click(self, name):
        self.selected_repo = name
        self.accept()


class TrainerRepoStatsWorker(QThread):
    stats_ready = pyqtSignal(dict)

    def __init__(self, main_window, repo_name):
        super().__init__()
        # We store repo_name but avoid touching main_window during run() to be thread-safe
        self.repo_name = repo_name

    def run(self):
        from opening_fenix.core.db.database import DatabaseManager
        from opening_fenix.core.utils import get_repertoire_db_path
        from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_info
        
        if self.isInterruptionRequested():
            return

        db_path = get_repertoire_db_path(self.repo_name)
        db_manager = DatabaseManager(db_path)
        session = db_manager.get_session()
        
        try:
            if self.isInterruptionRequested():
                return
            info = fetch_repertoire_info(session, self.repo_name, fast_only=False)
            if self.isInterruptionRequested():
                return
            self.stats_ready.emit(info)
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"TrainerRepoStatsWorker error for {self.repo_name}: {e}")
            if not self.isInterruptionRequested():
                self.stats_ready.emit({"name": self.repo_name, "levels": [], "moves": "Fehler", "level_details": []})
        finally:
            try:
                session.close()
            except Exception:
                pass
            try:
                db_manager.close()
            except Exception:
                pass


class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        set_consistent_icon(self)
        self.main_window = main_window
        self.setWindowTitle(tr_ui("settings.window_title", "Trainer Einstellungen"))
        self.setMinimumSize(scale(900), scale(680))
        self.setStyleSheet(get_bw_glass_style())
        if QApplication.instance():
            QApplication.instance().aboutToQuit.connect(self.reject)
        
        self.stats_loader = None
        self.loading_dots = 0
        self.loading_timer = None
        
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(scale(230))
        self.sidebar.currentRowChanged.connect(self.display_page)

        sidebar_items = [
            tr_ui("settings.tab_display", "🎨 Darstellung & Audio"),
            tr_ui("settings.tab_repo", "📚 Repertoire-Konfiguration"),
            tr_ui("settings.tab_faq", "❓ Hilfe & FAQ"),
        ]
        for text in sidebar_items:
            item = QListWidgetItem(text)
            self.sidebar.addItem(item)

        layout.addWidget(self.sidebar)

        # Content Area
        self.pages = QStackedWidget()

        self.page_display = QWidget(); self.init_page_display(self.page_display)
        self.page_repo = QWidget(); self.init_page_repo(self.page_repo)
        self.page_faq = QWidget(); self.init_page_faq(self.page_faq)

        self.pages.addWidget(self.page_display)
        self.pages.addWidget(self.page_repo)
        self.pages.addWidget(self.page_faq)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(self.pages)
        layout.addWidget(scroll, 1)

        self.sidebar.setCurrentRow(0)

    def display_page(self, index):
        self.pages.setCurrentIndex(index)
        if index == 1:
            QTimer.singleShot(0, self.rearrange_cards_grid)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.rearrange_cards_grid)



    # ─── Seite 1: Darstellung & Audio ──────────────────────────────────────────

    def init_page_display(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # Optik
        g_design = QGroupBox(tr_ui("settings.optics_title", "🎨 Optik"))
        f_design = QFormLayout(g_design)
        f_design.setSpacing(scale(15))

        self.combo_theme = NoWheelComboBox()
        for t_key in THEMES.keys():
            self.combo_theme.addItem(tr_ui(f"themes.{t_key}", t_key), t_key)

        current_theme = self.main_window.training_manager.get_setting("theme") or "Blau (Turnier)"
        idx = self.combo_theme.findData(current_theme)
        if idx < 0:
            idx = self.combo_theme.findText(current_theme)
        if idx >= 0:
            self.combo_theme.setCurrentIndex(idx)

        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        f_design.addRow(tr_ui("settings.board_design", "Schachbrett-Design:"), self.combo_theme)

        self.spin_anim = NoWheelSpinBox()
        self.spin_anim.setRange(50, 1000)
        self.spin_anim.setSingleStep(50)
        self.spin_anim.setSuffix(" ms")
        self.spin_anim.setValue(self.main_window.training_manager.get_setting("anim_speed") or 300)
        self.spin_anim.valueChanged.connect(
            lambda v: self.main_window.training_manager.set_setting("anim_speed", v)
        )
        self.spin_anim.setToolTip(tr_ui("settings.anim_speed_tooltip", "Wie schnell Figuren über das Brett gleiten (Millisekunden)."))
        f_design.addRow(tr_ui("settings.anim_speed", "Animations-Tempo:"), self.spin_anim)

        self.combo_notation = NoWheelComboBox()
        self.combo_notation.addItem(tr_ui("settings.notation_standard", "Standard (English) – K, Q, R, B, N"), "en")
        self.combo_notation.addItem(tr_ui("settings.notation_german", "Deutsch – K, D, T, L, S"), "de")
        curr_lang = self.main_window.training_manager.get_setting("notation_language") or "en"
        idx = self.combo_notation.findData(curr_lang)
        if idx != -1: self.combo_notation.setCurrentIndex(idx)
        self.combo_notation.currentIndexChanged.connect(self.on_notation_language_changed)
        f_design.addRow(tr_ui("settings.notation_lang_label", "Notation-Sprache:"), self.combo_notation)

        layout.addWidget(g_design)

        # Audio
        g_audio = QGroupBox(tr_ui("settings.audio_title", "🔊 Klang && Lautstärke"))
        f_audio = QFormLayout(g_audio)
        f_audio.setSpacing(scale(15))

        self.volume_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(
            self.main_window.training_manager.get_setting("master_volume") or 100
        )
        self.volume_slider.valueChanged.connect(self.on_volume_changed)

        self.lbl_volume = QLabel(f"{self.volume_slider.value()}%")
        self.lbl_volume.setStyleSheet("font-weight: bold; min-width: 40px;")
        h_vol = QHBoxLayout()
        h_vol.addWidget(self.volume_slider)
        h_vol.addWidget(self.lbl_volume)
        f_audio.addRow(tr_ui("settings.volume", "Gesamtlautstärke:"), h_vol)

        layout.addWidget(g_audio)

        # Trainingsablauf
        g_behavior = QGroupBox(tr_ui("settings.behavior_title", "🏋️ Trainings-Verhalten"))
        f_behavior = QFormLayout(g_behavior)
        f_behavior.setSpacing(scale(15))

        self.spin_delay = NoWheelSpinBox()
        self.spin_delay.setRange(0, 2000)
        self.spin_delay.setSingleStep(50)
        self.spin_delay.setSuffix(" ms")
        self.spin_delay.setValue(
            self.main_window.training_manager.get_setting("auto_delay") if self.main_window.training_manager.get_setting("auto_delay") is not None else 0
        )
        self.spin_delay.valueChanged.connect(
            lambda v: self.main_window.training_manager.set_setting("auto_delay", v)
        )
        self.spin_delay.setToolTip(
            tr_ui("settings.auto_delay_tooltip", "Wartezeit (Millisekunden) nach einem korrekten Zug, bis die nächste Aufgabe automatisch geladen wird.")
        )
        f_behavior.addRow(tr_ui("settings.auto_delay", "Verzögerung bei Variantenwechsel (Auto-Weiter):"), self.spin_delay)

        layout.addWidget(g_behavior)

        # Software-Updates
        from PyQt6.QtWidgets import QCheckBox, QMessageBox
        from opening_fenix.core.services.update_service import UpdateCheckWorker, get_config_dict, save_config_dict
        from opening_fenix.gui.dialogs.update_dialog import UpdateDialog

        g_updates = QGroupBox(tr_ui("settings.update_title", "🔄 Software-Updates"))
        v_updates = QVBoxLayout(g_updates)
        v_updates.setSpacing(scale(10))

        cfg = get_config_dict()
        chk_auto = QCheckBox(tr_ui("settings.auto_check_updates", "Automatisch nach Updates suchen"))
        chk_auto.setChecked(cfg.get("auto_check_updates", True))
        chk_auto.toggled.connect(self.on_auto_check_updates_toggled)
        v_updates.addWidget(chk_auto)

        h_check = QHBoxLayout()
        self.btn_manual_update = QPushButton(tr_ui("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen"))
        self.btn_manual_update.clicked.connect(self.run_manual_update_check)
        h_check.addWidget(self.btn_manual_update)
        h_check.addStretch()
        v_updates.addLayout(h_check)

        layout.addWidget(g_updates)
        layout.addStretch()

    def on_auto_check_updates_toggled(self, checked: bool):
        from opening_fenix.core.services.update_service import get_config_dict, save_config_dict
        cfg = get_config_dict()
        cfg["auto_check_updates"] = checked
        save_config_dict(cfg)

    def run_manual_update_check(self):
        from opening_fenix.core.services.update_service import UpdateCheckWorker
        self.btn_manual_update.setEnabled(False)
        self.btn_manual_update.setText(tr_ui("settings.checking_updates", "Suche läuft..."))

        self.update_worker = UpdateCheckWorker(manual=True, parent=self)
        self.update_worker.update_found.connect(self.on_manual_update_found)
        self.update_worker.no_update_found.connect(self.on_manual_no_update)
        self.update_worker.check_error.connect(self.on_manual_update_error)
        self.update_worker.start()

    def on_manual_update_found(self, release_info: dict):
        self.btn_manual_update.setEnabled(True)
        self.btn_manual_update.setText(tr_ui("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen"))
        from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
        UpdateDialog(release_info, self).exec()

    def on_manual_no_update(self):
        from PyQt6.QtWidgets import QMessageBox
        from opening_fenix.core.version import APP_VERSION
        self.btn_manual_update.setEnabled(True)
        self.btn_manual_update.setText(tr_ui("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen"))
        QMessageBox.information(
            self,
            tr_ui("settings.no_update_title", "Auf dem neuesten Stand"),
            tr_ui("settings.no_update_msg", "Du nutzt bereits die aktuellste Version ({version}).", version=APP_VERSION)
        )

    def on_manual_update_error(self, err_msg: str):
        from PyQt6.QtWidgets import QMessageBox
        self.btn_manual_update.setEnabled(True)
        self.btn_manual_update.setText(tr_ui("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen"))
        QMessageBox.warning(
            self,
            tr_ui("settings.update_error_title", "Fehler bei Update-Prüfung"),
            tr_ui("settings.update_error_msg", "Konnte GitHub nicht nach Updates prüfen:\n{err}", err=err_msg)
        )

    def on_theme_changed(self, index):
        theme_name = self.combo_theme.currentData()
        if not theme_name:
            theme_name = self.combo_theme.currentText()
        self.main_window.training_manager.set_setting("theme", theme_name)
        self.main_window.apply_theme()

    def on_volume_changed(self, value):
        self.lbl_volume.setText(f"{value}%")
        self.main_window.training_manager.set_setting("master_volume", value)
        self.main_window.set_master_volume(value)

    def on_notation_language_changed(self, index):
        lang = self.combo_notation.currentData()
        self.main_window.training_manager.set_setting("notation_language", lang)
        if hasattr(self.main_window, "update_notation_display"):
            self.main_window.update_notation_display()
        try:
            from PyQt6 import sip
            for w in QApplication.instance().topLevelWidgets():
                try:
                    if hasattr(w, "update_ui_from_fen") and not sip.isdeleted(w):
                        w.update_ui_from_fen()
                except: pass
        except ImportError:
            for w in QApplication.instance().topLevelWidgets():
                try:
                    if hasattr(w, "update_ui_from_fen"): w.update_ui_from_fen()
                except: pass

    # ─── Seite 3: Hilfe & FAQ ──────────────────────────────────────────────────

    def init_page_faq(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        lbl_title = QLabel(tr_ui("settings_faq.title", "Häufig gestellte Fragen (FAQ)"))
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(24)}px; font-weight: 800;")
        layout.addWidget(lbl_title)

        lbl_intro = QLabel(tr_ui("settings_faq.subtitle", "Hier findest du Antworten auf die am häufigsten gestellten Fragen zum Training mit Opening Fenix."))
        lbl_intro.setWordWrap(True)
        lbl_intro.setStyleSheet("color: #666; font-size: 14px;")
        layout.addWidget(lbl_intro)

        from opening_fenix.gui.dialogs.faq_dialog import FAQItem, get_faq_items
        faqs = get_faq_items()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, scale(10), 0)

        for q, a in faqs:
            content_layout.addWidget(FAQItem(q, a))
        
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    # ─── Seite 3: Repertoire-Konfiguration ─────────────────────────────────────

    def init_page_repo(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(12))
        layout.setContentsMargins(scale(12), scale(12), scale(12), scale(12))

        # Repertoire-Cards Bereich
        g_sel = QGroupBox(tr_ui("settings.repo_selection_title", "📂 Repertoire Auswahl && Status"))
        v_sel = QVBoxLayout(g_sel)
        v_sel.setContentsMargins(scale(6), scale(6), scale(6), scale(6))
        v_sel.setSpacing(0)
        
        self.scroll_cards = QScrollArea()
        self.scroll_cards.setWidgetResizable(True)
        self.scroll_cards.setMaximumHeight(scale(420))
        self.scroll_cards.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.card_container = QWidget()
        self.card_container.setStyleSheet("background: transparent;") # Explicitly transparent
        self.card_layout = QGridLayout(self.card_container)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_layout.setContentsMargins(scale(4), scale(4), scale(4), scale(4))
        self.card_layout.setSpacing(scale(8))
        
        self.scroll_cards.setWidget(self.card_container)
        self.scroll_cards.installEventFilter(self)
        self.scroll_cards.viewport().installEventFilter(self)
        v_sel.addWidget(self.scroll_cards)
        layout.addWidget(g_sel)
        
        self.refresh_repertoire_cards()

        # Informationen (read-only)
        self.grp_info = QGroupBox(tr_ui("settings.repo_info_title", "ℹ️ Repertoire Informationen"))
        info_main_layout = QHBoxLayout(self.grp_info)
        info_main_layout.setContentsMargins(scale(15), scale(15), scale(15), scale(15))
        info_main_layout.setSpacing(scale(25))

        # Left Column Widget to enforce fixed width based on cover image size
        left_col_widget = QWidget()
        left_col_widget.setFixedWidth(scale(180))
        left_col = QVBoxLayout(left_col_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(scale(10))
        left_col.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.lbl_info_cover = QLabel()
        self.lbl_info_cover.setFixedSize(scale(180), scale(180))
        self.lbl_info_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_col.addWidget(self.lbl_info_cover)

        self.lbl_name = QLabel("-")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 15px;")
        left_col.addWidget(self.lbl_name)

        self.lbl_color = QLabel("-")
        self.lbl_color.setWordWrap(True)
        self.lbl_color.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_col.addWidget(self.lbl_color)

        # Single Meta Pill container for Database & Comments (same color & style)
        self.meta_pill = QFrame()
        self.meta_pill.setStyleSheet("background: white; border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 12px;")
        meta_lay = QVBoxLayout(self.meta_pill)
        meta_lay.setContentsMargins(scale(10), scale(8), scale(10), scale(8))
        meta_lay.setSpacing(scale(4))

        self.lbl_db_info = QLabel("-")
        self.lbl_db_info.setWordWrap(True)
        self.lbl_db_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_db_info.setStyleSheet("color: #333333; font-size: 11px; font-weight: bold; background: transparent; border: none;")

        self.lbl_comment_stats = QLabel("-")
        self.lbl_comment_stats.setWordWrap(True)
        self.lbl_comment_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_comment_stats.setStyleSheet("color: #333333; font-size: 11px; font-weight: bold; background: transparent; border: none;")

        meta_lay.addWidget(self.lbl_db_info)
        meta_lay.addWidget(self.lbl_comment_stats)
        left_col.addWidget(self.meta_pill)

        self.lbl_levels = QLabel("-")
        self.levels_container = QWidget()
        self.levels_layout = QVBoxLayout(self.levels_container)
        self.levels_layout.setContentsMargins(0, 0, 0, 0)
        self.levels_layout.setSpacing(scale(6))
        left_col.addWidget(self.levels_container)

        # Unused/hidden labels to keep the rest of the code logic happy
        self.lbl_depth = QLabel("-")
        self.lbl_moves = QLabel("-")
        self.lbl_depth.hide()
        self.lbl_moves.hide()

        info_main_layout.addWidget(left_col_widget, 0)

        # Right Column (Description - borderless, nobox)
        self.txt_description = QTextEdit()
        self.txt_description.setReadOnly(True)
        self.txt_description.setStyleSheet(
            "background: transparent; border: none; padding: 0px; font-size: 14px; color: #2c3e50; line-height: 1.4;"
        )
        self.txt_description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        info_main_layout.addWidget(self.txt_description, 1)

        layout.addWidget(self.grp_info)

        # Ordner-Zugriff
        g_folder = QGroupBox(tr_ui("settings.folder_access_title", "📁 Ordner-Zugriff"))
        h_folder = QHBoxLayout(g_folder)
        btn_open_repos = AutoAdjustButton(tr_ui("settings.btn_open_repertoires_folder", "📁 Repertoires-Ordner im Explorer öffnen"))
        btn_open_repos.clicked.connect(self.open_repertoires_folder)
        btn_open_profs = AutoAdjustButton(tr_ui("settings.btn_open_profiles_folder", "📁 Profile-Ordner im Explorer öffnen"))
        btn_open_profs.clicked.connect(self.open_profiles_folder)
        h_folder.addWidget(btn_open_repos)
        h_folder.addWidget(btn_open_profs)
        layout.addWidget(g_folder)

        # Gefahrenzone
        g_danger = QGroupBox(tr_ui("settings.danger_title", "⚠️ Gefahrenzone"))
        v_danger = QVBoxLayout(g_danger)
        lbl_danger = QLabel(tr_ui("settings.danger_desc", "Das Zurücksetzen löscht deinen gesamten Trainingsfortschritt für dieses Repertoire."))
        lbl_danger.setWordWrap(True)
        lbl_danger.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        v_danger.addWidget(lbl_danger)

        self.btn_reset = QPushButton(tr_ui("settings.danger_btn", "🗑️ Trainingsfortschritt zurücksetzen"))
        self.btn_reset.setProperty("class", "Danger")
        self.btn_reset.clicked.connect(self.reset_repo_progress)
        v_danger.addWidget(self.btn_reset)
        layout.addWidget(g_danger)

        layout.addStretch()

    def open_repertoires_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        path = os.path.join(get_user_dir(), "repertoires")
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_profiles_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        path = os.path.join(get_user_dir(), "profiles")
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

        self.stats_loader = None
        self.loading_timer = None

        # Initialize with active repertoire
        active_repo = self.main_window.repertoire_manager.active_repertoire_name
        if active_repo:
            self.on_repo_selected(active_repo)

    def closeEvent(self, event):
        if hasattr(self, "stats_loader") and self.stats_loader and self.stats_loader.isRunning():
            try:
                self.stats_loader.requestInterruption()
                if not self.stats_loader.wait(200):
                    self.stats_loader.terminate()
            except: pass
        if hasattr(self, "update_worker") and self.update_worker and self.update_worker.isRunning():
            try:
                self.update_worker.requestInterruption()
                if not self.update_worker.wait(200):
                    self.update_worker.terminate()
            except: pass
        if hasattr(self, "loading_timer") and self.loading_timer:
            try: self.loading_timer.stop()
            except: pass
        super().closeEvent(event)

    def start_loading_animation(self):
        if not self.loading_timer:
            self.loading_timer = QTimer(self)
            self.loading_timer.timeout.connect(self.update_loading_dots)
        self.loading_timer.start(500)
        self.loading_dots = 0

    def update_loading_dots(self):
        self.loading_dots = (self.loading_dots + 1) % 4
        dots = "." * self.loading_dots
        text = f"Laden{dots}"
        
        labels = [self.lbl_depth, self.lbl_db_info, self.lbl_moves, self.lbl_levels]
        for lbl in labels:
            if not sip.isdeleted(lbl) and "Laden" in lbl.text():
                lbl.setText(text)


    def on_repo_selected(self, repo_name):
        if not repo_name: return
        self.selected_repo = repo_name

        # Stop existing loader if any
        if hasattr(self, "stats_loader") and self.stats_loader and self.stats_loader.isRunning():
            self.stats_loader.requestInterruption()
            self.stats_loader.wait()

        # 1. Fast Load (Metadata only)
        # We use a local session to avoid race conditions with the global repertoire_manager
        from opening_fenix.core.db.database import DatabaseManager
        from opening_fenix.core.utils import get_repertoire_db_path
        from opening_fenix.core.data_tools import get_meta
        from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_info
        
        db_path = get_repertoire_db_path(repo_name)
        db_manager = DatabaseManager(db_path)
        session = db_manager.get_session()
        try:
            info = fetch_repertoire_info(session, repo_name, fast_only=True)
            color = get_meta(session, "color", "w")
            comment_stats_str = get_repertoire_comment_stats(session)
        except:
            info = {"name": repo_name, "description": ""}
            color = 'w'
            comment_stats_str = "Keine Kommentare"
        finally:
            session.close()
            db_manager.close()

        if hasattr(self, 'lbl_comment_stats'):
            if not comment_stats_str or comment_stats_str == "Keine Kommentare":
                stats_display = tr_ui("settings.no_comments", "Keine Kommentare")
            else:
                stats_display = comment_stats_str
            self.lbl_comment_stats.setText(tr_ui("settings.comments_format", "💬 Kommentare: {stats}", stats=stats_display))
        
        # Color Badge Styling (Both Weiß and Schwarz have white backgrounds now)
        if color == 'w':
            self.lbl_color.setText(tr_ui("settings.repo_color_white", "Weiß ♟️"))
        else:
            self.lbl_color.setText(tr_ui("settings.repo_color_black", "Schwarz ♟️"))
        self.lbl_color.setStyleSheet(
            f"padding: {scale(4)}px {scale(8)}px; border-radius: {scale(10)}px; background: white; color: #111111; font-size: {scale(11)}px; font-weight: bold; border: 1px solid rgba(0,0,0,0.15);"
        )
            
        self.txt_description.setPlainText(info.get("description", "-") or "-")
        self.lbl_db_info.setText(tr_ui("settings.db_loading", "📚 Datenbank: Laden..."))

        # Load cover image for details panel
        from opening_fenix.creator.repo_selection_dialog import get_repertoire_cover_path
        from PyQt6.QtGui import QPixmap
        
        cover_path = get_repertoire_cover_path(repo_name)
        if cover_path and os.path.exists(cover_path):
            pix = QPixmap(cover_path).scaled(scale(180), scale(180), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.lbl_info_cover.setPixmap(pix)
        else:
            logo_path = os.path.join(get_base_path(), "assets", "Logo", "Logo.png")
            if os.path.exists(logo_path):
                pix = QPixmap(logo_path).scaled(scale(180), scale(180), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.lbl_info_cover.setPixmap(pix)
        self.lbl_info_cover.setStyleSheet("border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 8px; background: white;")

        # Clear levels and set loading
        self.level_pills = []
        while self.levels_layout.count():
            item = self.levels_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.lbl_levels = QLabel(tr_ui("settings.loading_text", "Laden..."))
        self.lbl_levels.setStyleSheet("color: #888; font-size: 12px;")
        self.levels_layout.addWidget(self.lbl_levels)

        # Start animation and worker
        self.start_loading_animation()
        self.stats_loader = TrainerRepoStatsWorker(self.main_window, repo_name)
        self.stats_loader.stats_ready.connect(self.on_stats_loaded)
        self.stats_loader.start()

    def on_stats_loaded(self, info):
        # Update labels with actual data
        if sip.isdeleted(self): return
        
        if self.loading_timer: self.loading_timer.stop()
        
        # Update Database Elo rating info
        elo_cat = info.get("elo", "-")
        rating_info = get_elo_display(elo_cat)
        self.lbl_db_info.setText(tr_ui("settings.db_info_format", "📚 Datenbank: {rating_info}", rating_info=rating_info))
        
        # Clear and build levels list as a single combined pill container
        self.level_pills = []
        while self.levels_layout.count():
            item = self.levels_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        lvl_details = info.get("level_details", [])
        if not lvl_details:
            lbl = QLabel("-")
            lbl.setStyleSheet("color: #777; font-size: 13px;")
            self.levels_layout.addWidget(lbl)
        else:
            single_levels_pill = QFrame()
            single_levels_pill.setStyleSheet("background: white; border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 12px;")
            p_lay = QVBoxLayout(single_levels_pill)
            p_lay.setContentsMargins(scale(10), scale(8), scale(10), scale(8))
            p_lay.setSpacing(scale(6))

            for ld in lvl_details:
                moves_val = ld.get('moves')
                if moves_val is None:
                    moves_val = 0
                from opening_fenix.core.translation import translator
                if translator.current_lang == "en":
                    moves_formatted = f"{moves_val:,}"
                else:
                    moves_formatted = f"{moves_val:,}".replace(",", ".")
                p_lbl = QLabel(tr_ui("settings.level_pill_format", "Lvl {order}: {name} ({target_elo} Elo) - {moves} Züge", order=ld['order'], name=ld['name'], target_elo=ld['target_elo'], moves=moves_formatted))
                p_lbl.setStyleSheet("color: #333333; font-size: 11px; font-weight: bold; background: transparent; border: none;")
                p_lbl.setWordWrap(True)
                p_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                p_lay.addWidget(p_lbl)

            self.level_pills = [single_levels_pill]
            self.rearrange_levels_grid()

    def refresh_repertoire_cards(self):
        # Clear layout
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        repos = self.main_window.repertoire_manager.get_all_repertoires()
        active_repos = []
        inactive_repos = []
        for r_name in repos:
            is_active = self.main_window.training_manager.is_repo_visible(r_name)
            if is_active:
                active_repos.append(r_name)
            else:
                inactive_repos.append(r_name)
                
        sorted_repos = sorted(active_repos) + sorted(inactive_repos)
        
        for r_name in sorted_repos:
            is_active = self.main_window.training_manager.is_repo_visible(r_name)
            card = RepertoireConfigCard(r_name, is_active, self)
            card.clicked.connect(lambda n=r_name: self.on_repo_selected(n))
            self.card_layout.addWidget(card)
            
        self._current_cols = -1
        self.rearrange_cards_grid()

    def rearrange_cards_grid(self):
        if not hasattr(self, "scroll_cards") or not hasattr(self, "card_layout"):
            return
            
        width = self.scroll_cards.viewport().width()
        if width <= 10:
            return
            
        card_min_width = scale(250)
        spacing = scale(8)
        margins = self.card_layout.contentsMargins()
        avail_width = width - (margins.left() + margins.right()) - scale(8)
        
        cols = max(1, avail_width // (card_min_width + spacing))
        
        if hasattr(self, "_current_cols") and self._current_cols == cols:
            return
        self._current_cols = cols
        
        cards = []
        for i in range(self.card_layout.count()):
            item = self.card_layout.itemAt(i)
            if item and item.widget():
                cards.append(item.widget())
                
        for card in cards:
            self.card_layout.removeWidget(card)
            
        for c in range(max(cols, 10)):
            self.card_layout.setColumnStretch(c, 1 if c < cols else 0)
            
        for idx, card in enumerate(cards):
            r = idx // cols
            c = idx % cols
            self.card_layout.addWidget(card, r, c)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if hasattr(self, "scroll_cards") and (obj == self.scroll_cards or obj == self.scroll_cards.viewport()) and event.type() == QEvent.Type.Resize:
            self.rearrange_cards_grid()
        elif hasattr(self, "levels_container") and obj == self.levels_container and event.type() == QEvent.Type.Resize:
            self.rearrange_levels_grid()
        return super().eventFilter(obj, event)

    def rearrange_levels_grid(self):
        if not hasattr(self, "level_pills") or not self.level_pills:
            return
            
        for pill in self.level_pills:
            self.levels_layout.removeWidget(pill)
            
        for pill in self.level_pills:
            self.levels_layout.addWidget(pill)

    def update_card_selection_highlights(self):
        for i in range(self.card_layout.count()):
            item = self.card_layout.itemAt(i)
            if item and item.widget():
                item.widget().update_style()

    def reset_repo_progress(self):
        if not hasattr(self, "selected_repo") or not self.selected_repo: return
        if QMessageBox.warning(
            self, tr_ui("settings.reset_title", "Fortschritt zurücksetzen"),
            tr_ui("settings.reset_confirm", "Trainingsfortschritt für '{repo_name}' wirklich löschen?\n\nDies kann nicht rückgängig gemacht werden.", repo_name=self.selected_repo),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            original_repo = self.main_window.repertoire_manager.active_repertoire_name
            self.main_window.repertoire_manager.set_active_repertoire(self.selected_repo)
            self.main_window.training_manager.reset_repertoire_progress()
            if original_repo and original_repo != self.selected_repo:
                self.main_window.repertoire_manager.set_active_repertoire(original_repo)
            QMessageBox.information(self, tr_ui("settings.reset_success_title", "Erfolg"), tr_ui("settings.reset_success_desc", "Trainingsfortschritt erfolgreich zurückgesetzt."))
            self.main_window.refresh_repertoire_buttons()


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(scale(44), scale(22))
        
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QBrush
        from PyQt6.QtCore import QRectF, Qt
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background pill shape
        brush_color = QColor("#111111") if self.isChecked() else QColor("#d1d1d6")
        painter.setBrush(QBrush(brush_color))
        painter.setPen(Qt.PenStyle.NoPen)
        
        rect = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2.0
        painter.drawRoundedRect(rect, radius, radius)
        
        # Draw circle slider knob
        knob_color = QColor("white")
        painter.setBrush(QBrush(knob_color))
        
        margin = scale(2)
        knob_size = self.height() - (margin * 2)
        
        if self.isChecked():
            x = self.width() - knob_size - margin
        else:
            x = margin
            
        knob_rect = QRectF(x, margin, knob_size, knob_size)
        painter.drawEllipse(knob_rect)


class RepertoireConfigCard(QFrame):
    clicked = pyqtSignal()
    
    def __init__(self, repo_name, is_active, parent_dlg):
        super().__init__()
        self.repo_name = repo_name
        self.is_active = is_active
        self.parent_dlg = parent_dlg
        self.main_window = parent_dlg.main_window
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.init_ui()
        self.update_style()
        
    def init_ui(self):
        import os
        from PyQt6.QtGui import QPixmap
        from opening_fenix.creator.repo_selection_dialog import get_repertoire_cover_path
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        self.layout.setSpacing(scale(15))
        
        # 1. Cover Image
        self.lbl_cover = QLabel()
        self.lbl_cover.setFixedSize(scale(48), scale(48))
        cover_path = get_repertoire_cover_path(self.repo_name)
        if cover_path and os.path.exists(cover_path):
            pix = QPixmap(cover_path).scaled(scale(48), scale(48), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.lbl_cover.setPixmap(pix)
        else:
            logo_path = os.path.join(get_base_path(), "assets", "Logo", "Logo.png")
            if os.path.exists(logo_path):
                pix = QPixmap(logo_path).scaled(scale(48), scale(48), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.lbl_cover.setPixmap(pix)
        self.lbl_cover.setStyleSheet(f"border: 1px solid rgba(0, 0, 0, 0.1); border-radius: {scale(6)}px; background: white;")
        self.layout.addWidget(self.lbl_cover)
        
        # 2. Info Container
        self.info_widget = QWidget()
        self.info_layout = QVBoxLayout(self.info_widget)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_layout.setSpacing(scale(4))
        
        self.lbl_name = QLabel(self.repo_name)
        self.lbl_name.setObjectName("RepoName")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet(f"font-weight: 700; font-size: {scale(16)}px;")
        self.info_layout.addWidget(self.lbl_name)
        
        # Elo Row (Horizontal container for Elo Rating label + Toggle Switch Button next to it)
        self.elo_row = QWidget()
        self.elo_layout = QHBoxLayout(self.elo_row)
        self.elo_layout.setContentsMargins(0, 0, 0, 0)
        self.elo_layout.setSpacing(scale(8))
        
        # User Elo Rating
        self.lbl_elo = QLabel(f"🎓 {self.fetch_user_elo()} Elo")
        self.lbl_elo.setObjectName("RepoElo")
        self.lbl_elo.setStyleSheet(f"font-size: {scale(13)}px;")
        self.elo_layout.addWidget(self.lbl_elo)
        
        # Toggle Switch Button (now next to Elo)
        self.btn_toggle = ToggleSwitch()
        self.btn_toggle.setChecked(self.is_active)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle_active)
        self.elo_layout.addWidget(self.btn_toggle)
        
        self.elo_layout.addStretch()
        self.info_layout.addWidget(self.elo_row)
        
        # Level combobox (no prefix text, shown in its own row below)
        self.combo_level = NoWheelComboBox()
        self.combo_level.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_level.setMinimumWidth(scale(120))
        self.combo_level.setFixedHeight(scale(35))
        self.populate_levels()
        self.combo_level.currentIndexChanged.connect(self.on_level_changed)
        self.info_layout.addWidget(self.combo_level)
        
        self.layout.addWidget(self.info_widget, 1)
        
        # Set visibility of widgets based on active status
        self.lbl_elo.setVisible(self.is_active)
        self.combo_level.setVisible(self.is_active)
        
        if self.is_active:
            self.setMinimumHeight(scale(130))
            self.setMaximumHeight(scale(160))
        else:
            self.setMinimumHeight(scale(64))
            self.setMaximumHeight(scale(75))

    def fetch_user_elo(self):
        try:
            from opening_fenix.core.db.models import UserRepertoireSettings, TrainingData
            from opening_fenix.core.db.database import DatabaseManager
            from opening_fenix.core.utils import get_repertoire_db_path
            from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_levels
            
            session = self.main_window.training_manager.user_session
            settings = session.query(UserRepertoireSettings).filter_by(repertoire_name=self.repo_name).first()
            rating = settings.rating if settings else 800.0
            
            # Calculate seen factor (progress factor)
            db_path = get_repertoire_db_path(self.repo_name)
            db_manager = DatabaseManager(db_path)
            rep_session = db_manager.get_session()
            try:
                from opening_fenix.core.db.repertoire import Move
                levels = fetch_repertoire_levels(rep_session)
                active_lvl = self.main_window.training_manager.get_active_level(self.repo_name)
                
                # Get total moves in active levels
                total_moves_in_level = rep_session.query(Move).filter(Move.level <= active_lvl).count()
                if total_moves_in_level == 0:
                    return int(rating)
                    
                seen_moves = session.query(TrainingData).filter_by(repertoire_name=self.repo_name).count()
                progress_factor = min(1.0, seen_moves / total_moves_in_level)
                return int(800 + (rating - 800) * progress_factor)
            finally:
                rep_session.close()
                db_manager.close()
        except Exception:
            pass
        return 800

    def populate_levels(self):
        from opening_fenix.core.db.database import DatabaseManager
        from opening_fenix.core.utils import get_repertoire_db_path
        from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_levels
        
        db_path = get_repertoire_db_path(self.repo_name)
        db_manager = DatabaseManager(db_path)
        session = db_manager.get_session()
        try:
            levels = fetch_repertoire_levels(session)
            active_lvl = self.main_window.training_manager.get_active_level(self.repo_name)

            self.combo_level.blockSignals(True)
            self.combo_level.clear()
            for lvl in levels:
                self.combo_level.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
            
            idx = self.combo_level.findData(active_lvl)
            if idx != -1: self.combo_level.setCurrentIndex(idx)
            self.combo_level.blockSignals(False)
        finally:
            session.close()
            db_manager.close()

    def toggle_active(self):
        # Toggle internal active state
        self.is_active = not self.is_active
        
        # Sync toggle switch button checked state
        self.btn_toggle.blockSignals(True)
        self.btn_toggle.setChecked(self.is_active)
        self.btn_toggle.blockSignals(False)
        
        self.lbl_elo.setVisible(self.is_active)
        self.combo_level.setVisible(self.is_active)
        
        if self.is_active:
            self.setMinimumHeight(scale(130))
            self.setMaximumHeight(scale(160))
        else:
            self.setMinimumHeight(scale(64))
            self.setMaximumHeight(scale(75))
        
        self.main_window.training_manager.set_repo_visibility(self.repo_name, self.is_active)
        self.main_window.refresh_repertoire_buttons()
        self.update_style()
        self.clicked.emit()
        # Refresh cards list to re-sort active ones to the top
        self.parent_dlg.refresh_repertoire_cards()

    def on_level_changed(self):
        level = self.combo_level.currentData()
        if level is not None:
            self.main_window.training_manager.set_active_level(level, self.repo_name)
            # Update Elo label with the user's current Elo
            self.lbl_elo.setText(f"🎓 {self.fetch_user_elo()} Elo")

    def update_style(self):
        is_selected = (hasattr(self.parent_dlg, "selected_repo") and self.parent_dlg.selected_repo == self.repo_name)
        
        if self.is_active:
            bg = "white"
            border = "2px solid #3e2723" if is_selected else "1px solid rgba(0, 0, 0, 0.12)"
        else:
            bg = "rgba(0,0,0,0.03)"
            border = "2px dashed #3e2723" if is_selected else "1px solid rgba(0, 0, 0, 0.08)"
            
        self.setStyleSheet(f"""
            RepertoireConfigCard {{
                background-color: {bg};
                border: {border};
                border-radius: {scale(12)}px;
            }}
            QLabel#RepoName {{ 
                color: #111111;
                font-weight: 700;
            }}
            QLabel#RepoElo {{ 
                color: #555555;
            }}
        """)

    def mousePressEvent(self, event):
        # We need to make sure that clicking on the combobox or toggle button doesn't trigger card selection
        child = self.childAt(event.position().toPoint())
        if child and (child == self.combo_level or self.combo_level.isAncestorOf(child) or child == self.btn_toggle):
            super().mousePressEvent(event)
            return
        
        self.parent_dlg.selected_repo = self.repo_name
        self.parent_dlg.on_repo_selected(self.repo_name)
        self.parent_dlg.update_card_selection_highlights()
        self.clicked.emit()
        super().mousePressEvent(event)

