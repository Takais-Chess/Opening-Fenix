import os
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QFormLayout, QComboBox, 
    QHBoxLayout, QLabel, QListWidget, QScrollArea, QFrame, 
    QGroupBox, QSpinBox, QPushButton, QCheckBox, QProgressBar, QSlider, 
    QLineEdit, QFileDialog, QMessageBox, QStackedWidget, QListWidgetItem,
    QTextEdit, QGridLayout, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QIcon, QFont
from PyQt6 import sip
from opening_fenix.core.data_tools import get_base_path, get_user_dir, get_repertoire_analysis_status
from opening_fenix.gui.widgets.board_widget import THEMES

# Import centralized styles
from opening_fenix.gui.styles import COLORS, get_bw_glass_style, set_consistent_icon
from opening_fenix.gui.scaling import scale


class NoWheelComboBox(QComboBox):
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
        self.setWindowTitle("Repertoire Laden")
        self.setMinimumSize(scale(520), scale(420))
        self.selected_repo = None
        self.setStyleSheet(get_bw_glass_style())
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        lbl_title = QLabel("Repertoire auswählen")
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #111111; margin-bottom: 5px;")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel("Klicke auf ein Repertoire, um es zu laden.")
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
        b_cancel = QPushButton("Abbrechen")
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
        self.main_window = main_window
        self.repo_name = repo_name

    def run(self):
        # We need to temporarily switch to the repo to get stats, 
        # then switch back if it wasn't the active one.
        original_repo = self.main_window.repertoire_manager.active_repertoire_name
        self.main_window.repertoire_manager.set_active_repertoire(self.repo_name)
        
        info = self.main_window.repertoire_manager.get_repertoire_info(fast_only=False)
        
        if original_repo and original_repo != self.repo_name:
            self.main_window.repertoire_manager.set_active_repertoire(original_repo)
            
        self.stats_ready.emit(info)


class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        set_consistent_icon(self)
        self.main_window = main_window
        self.setWindowTitle("Trainer Einstellungen")
        self.setMinimumSize(scale(900), scale(680))
        self.setStyleSheet(get_bw_glass_style())
        
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
            "🎨 Darstellung & Audio",
            "📚 Repertoire-Konfiguration",
            "❓ Hilfe & FAQ",
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

    # ─── Seite 1: Darstellung & Audio ──────────────────────────────────────────

    def init_page_display(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # Optik
        g_design = QGroupBox("🎨 Optik")
        f_design = QFormLayout(g_design)
        f_design.setSpacing(scale(15))

        self.combo_theme = QComboBox()
        self.combo_theme.addItems(THEMES.keys())
        self.combo_theme.setCurrentText(
            self.main_window.training_manager.get_setting("theme") or "Blau (Turnier)"
        )
        self.combo_theme.currentTextChanged.connect(self.on_theme_changed)
        f_design.addRow("Schachbrett-Design:", self.combo_theme)

        self.spin_anim = QSpinBox()
        self.spin_anim.setRange(50, 1000)
        self.spin_anim.setSuffix(" ms")
        self.spin_anim.setValue(self.main_window.training_manager.get_setting("anim_speed") or 300)
        self.spin_anim.valueChanged.connect(
            lambda v: self.main_window.training_manager.set_setting("anim_speed", v)
        )
        self.spin_anim.setToolTip("Wie schnell Figuren über das Brett gleiten (Millisekunden).")
        f_design.addRow("Animations-Tempo:", self.spin_anim)

        self.combo_notation = QComboBox()
        self.combo_notation.addItem("Standard (English) – K, Q, R, B, N", "en")
        self.combo_notation.addItem("Deutsch – K, D, T, L, S", "de")
        curr_lang = self.main_window.training_manager.get_setting("notation_language") or "en"
        idx = self.combo_notation.findData(curr_lang)
        if idx != -1: self.combo_notation.setCurrentIndex(idx)
        self.combo_notation.currentIndexChanged.connect(self.on_notation_language_changed)
        f_design.addRow("Notation-Sprache:", self.combo_notation)

        layout.addWidget(g_design)

        # Audio
        g_audio = QGroupBox("🔊 Klang && Lautstärke")
        f_audio = QFormLayout(g_audio)
        f_audio.setSpacing(scale(15))

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
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
        f_audio.addRow("Gesamtlautstärke:", h_vol)

        layout.addWidget(g_audio)

        # Trainingsablauf
        g_behavior = QGroupBox("🏋️ Trainings-Verhalten")
        f_behavior = QFormLayout(g_behavior)
        f_behavior.setSpacing(scale(15))

        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 2000)
        self.spin_delay.setSuffix(" ms")
        self.spin_delay.setValue(
            self.main_window.training_manager.get_setting("auto_delay") or 200
        )
        self.spin_delay.valueChanged.connect(
            lambda v: self.main_window.training_manager.set_setting("auto_delay", v)
        )
        self.spin_delay.setToolTip(
            "Wartezeit (Millisekunden) nach einem korrekten Zug, "
            "bis die nächste Aufgabe automatisch geladen wird."
        )
        f_behavior.addRow("Auto-Weiter Verzögerung:", self.spin_delay)
        layout.addWidget(g_behavior)

        layout.addStretch()

    def on_theme_changed(self, theme_name):
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

        lbl_title = QLabel("Häufig gestellte Fragen (FAQ)")
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(24)}px; font-weight: 800;")
        layout.addWidget(lbl_title)

        lbl_intro = QLabel("Hier findest du Antworten auf die am häufigsten gestellten Fragen zum Training mit Opening Fenix.")
        lbl_intro.setWordWrap(True)
        lbl_intro.setStyleSheet("color: #666; font-size: 14px;")
        layout.addWidget(lbl_intro)

        from opening_fenix.gui.dialogs.faq_dialog import FAQItem
        faqs = [
            (
                "Wie soll ich mein Training gestalten?",
                "Ich empfehle immer, zuerst die fälligen Züge zu üben und falls danach noch Zeit ist, ein paar Varianten auf einen Schlag zu lernen (ca. 20–50 Züge) und diese direkt zu üben.\n\nDiesem Muster ein paar Mal pro Woche folgen, bis das Repertoire sitzt, und danach alle paar Wochen die fälligen Züge erledigen."
            ),
            (
                "Wie soll ich reagieren, wenn ich einen Zug falsch habe?",
                "Denke kurz darüber nach, warum der Zug falsch ist, und schaue dann mithilfe des Lichess-Buttons nach, warum dein gewählter Zug schlecht ist."
            ),
            (
                "Wie ändere ich das Trainingslevel und wann soll ich das machen?",
                "Das Level kannst du in den Einstellungen des Trainers bei der Repertoire-Auswahl ändern. Man sollte das Level erhöhen, sobald das vorherige Level sitzt und auch die eigene Elo die Ziel-Elo für dieses Repertoire-Level überschritten hat."
            )
        ]

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
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # Repertoire-Cards Bereich
        g_sel = QGroupBox("📂 Repertoire Auswahl && Status")
        v_sel = QVBoxLayout(g_sel)
        
        self.scroll_cards = QScrollArea()
        self.scroll_cards.setWidgetResizable(True)
        self.scroll_cards.setMaximumHeight(scale(420))
        self.scroll_cards.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.card_container = QWidget()
        self.card_container.setStyleSheet("background: transparent;") # Explicitly transparent
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_layout.setSpacing(scale(10))
        
        self.scroll_cards.setWidget(self.card_container)
        v_sel.addWidget(self.scroll_cards)
        layout.addWidget(g_sel)
        
        self.refresh_repertoire_cards()

        # Informationen (read-only)
        self.grp_info = QGroupBox("ℹ️ Repertoire Informationen")
        self.info_form = QFormLayout(self.grp_info)
        self.info_form.setSpacing(scale(12))
        self.lbl_name = QLabel("-")
        self.lbl_name.setStyleSheet("font-weight: bold;")
        self.lbl_color = QLabel("-")
        self.lbl_levels = QLabel("-")
        self.lbl_depth = QLabel("-")
        self.lbl_elo = QLabel("-")
        self.lbl_moves = QLabel("-")
        self.txt_description = QTextEdit()
        self.txt_description.setReadOnly(True)
        self.txt_description.setMaximumHeight(scale(160)) # Doubled size
        self.txt_description.setStyleSheet(
            "background: rgba(0,0,0,0.03); border-radius: 6px; border: 1px solid rgba(0,0,0,0.1); padding: 6px;"
        )
        self.info_form.addRow("Name:", self.lbl_name)
        self.info_form.addRow("Farbe:", self.lbl_color)
        self.info_form.addRow("Levels:", self.lbl_levels)
        self.info_form.addRow("Analyse-Status:", self.lbl_depth)
        self.info_form.addRow("Prio. Score Datenbank Elo:", self.lbl_elo)
        self.info_form.addRow("Züge gesamt:", self.lbl_moves)
        self.info_form.addRow("Beschreibung:", self.txt_description)
        layout.addWidget(self.grp_info)

        # Gefahrenzone
        g_danger = QGroupBox("⚠️ Gefahrenzone")
        v_danger = QVBoxLayout(g_danger)
        lbl_danger = QLabel("Das Zurücksetzen löscht deinen gesamten Trainingsfortschritt für dieses Repertoire.")
        lbl_danger.setWordWrap(True)
        lbl_danger.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        v_danger.addWidget(lbl_danger)

        self.btn_reset = QPushButton("🗑️ Trainingsfortschritt zurücksetzen")
        self.btn_reset.setProperty("class", "Danger")
        self.btn_reset.clicked.connect(self.reset_repo_progress)
        v_danger.addWidget(self.btn_reset)
        layout.addWidget(g_danger)

        layout.addStretch()

        self.stats_loader = None
        self.loading_timer = None

        # Initialize with active repertoire
        active_repo = self.main_window.repertoire_manager.active_repertoire_name
        if active_repo:
            self.on_repo_selected(active_repo)

    def closeEvent(self, event):
        if self.stats_loader and self.stats_loader.isRunning():
            self.stats_loader.terminate()
            self.stats_loader.wait()
        if self.loading_timer:
            self.loading_timer.stop()
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
        
        labels = [self.lbl_depth, self.lbl_elo, self.lbl_moves, self.lbl_levels]
        for lbl in labels:
            if not sip.isdeleted(lbl) and "Laden" in lbl.text():
                lbl.setText(text)

    def on_repo_selected(self, repo_name):
        if not repo_name: return
        self.selected_repo = repo_name

        # Stop existing loader if any
        if self.stats_loader and self.stats_loader.isRunning():
            self.stats_loader.terminate()
            self.stats_loader.wait()

        # 1. Fast Load (Metadata only)
        # We handle the repo switch manually for metadata to be fast
        original_repo = self.main_window.repertoire_manager.active_repertoire_name
        self.main_window.repertoire_manager.set_active_repertoire(repo_name)
        info = self.main_window.repertoire_manager.get_repertoire_info(fast_only=True)
        if original_repo and original_repo != repo_name:
            self.main_window.repertoire_manager.set_active_repertoire(original_repo)

        self.lbl_name.setText(info.get("name", "-"))
        self.lbl_color.setText(
            "Weiß ♟️" if self.main_window.repertoire_manager.get_repertoire_color() == 'w' else "Schwarz ♟️"
        )
        self.txt_description.setPlainText(info.get("description", ""))

        # Set placeholders
        self.lbl_depth.setText("Laden.")
        self.lbl_elo.setText("Laden.")
        self.lbl_moves.setText("Laden.")
        self.lbl_levels.setText("Laden.")

        # Start animation and worker
        self.start_loading_animation()
        self.stats_loader = TrainerRepoStatsWorker(self.main_window, repo_name)
        self.stats_loader.stats_ready.connect(self.on_stats_loaded)
        self.stats_loader.start()

    def on_stats_loaded(self, info):
        # Update labels with actual data
        if sip.isdeleted(self): return
        
        if self.loading_timer: self.loading_timer.stop()
        
        self.lbl_depth.setText(info.get("depth", "-"))

        elo_map = {
            "low": "800–1400 (Hobby)",
            "mid": "1600–1800 (Club)",
            "high": "2000–2500 (Expert)",
            "masters": "Lichess Masters"
        }
        elo_cat = info.get("elo", "-")
        coverage = info.get("coverage_pct", 0)
        rating_info = elo_map.get(elo_cat, elo_cat)
        self.lbl_elo.setText(f"{rating_info} [{coverage:.1f}% Abdeckung]")
        
        self.lbl_moves.setText(str(info.get("moves", "0")))
        
        lvl_details = info.get("level_details", [])
        lvl_text = ""
        for ld in lvl_details:
            lvl_text += f"{ld['order']}: {ld['name']} ({ld['target_elo']} Elo)\n"
        self.lbl_levels.setText(lvl_text.strip() or "-")

    def refresh_repertoire_cards(self):
        # Clear layout
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        repos = self.main_window.repertoire_manager.get_all_repertoires()
        for r_name in sorted(repos):
            is_active = self.main_window.training_manager.is_repo_visible(r_name)
            card = RepertoireConfigCard(r_name, is_active, self)
            card.clicked.connect(lambda n=r_name: self.on_repo_selected(n))
            self.card_layout.addWidget(card)

    def reset_repo_progress(self):
        if not hasattr(self, "selected_repo") or not self.selected_repo: return
        if QMessageBox.warning(
            self, "Fortschritt zurücksetzen",
            f"Trainingsfortschritt für '{self.selected_repo}' wirklich löschen?\n\nDies kann nicht rückgängig gemacht werden.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            original_repo = self.main_window.repertoire_manager.active_repertoire_name
            self.main_window.repertoire_manager.set_active_repertoire(self.selected_repo)
            self.main_window.training_manager.reset_repertoire_progress()
            if original_repo and original_repo != self.selected_repo:
                self.main_window.repertoire_manager.set_active_repertoire(original_repo)
            QMessageBox.information(self, "Erfolg", "Trainingsfortschritt erfolgreich zurückgesetzt.")
            self.main_window.refresh_repertoire_buttons()


class RepertoireConfigCard(QFrame):
    clicked = pyqtSignal()
    
    def __init__(self, repo_name, is_active, parent_dlg):
        super().__init__()
        self.repo_name = repo_name
        self.is_active = is_active
        self.parent_dlg = parent_dlg
        self.main_window = parent_dlg.main_window
        self.init_ui()
        self.update_style()
        
    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(scale(15), scale(12), scale(15), scale(12))
        
        # Header Row
        h_header = QHBoxLayout()
        self.lbl_name = QLabel(self.repo_name)
        self.lbl_name.setStyleSheet("font-weight: 700; font-size: 16px;")
        
        self.btn_status = QPushButton("Aktiv" if self.is_active else "Inaktiv")
        self.btn_status.setCheckable(True)
        self.btn_status.setChecked(self.is_active)
        self.btn_status.setFixedWidth(scale(80))
        self.btn_status.clicked.connect(self.toggle_active)
        
        h_header.addWidget(self.lbl_name)
        h_header.addStretch()
        h_header.addWidget(self.btn_status)
        self.layout.addLayout(h_header)
        
        # Level Row (Only if active)
        self.level_widget = QWidget()
        l_layout = QHBoxLayout(self.level_widget)
        l_layout.setContentsMargins(0, scale(10), 0, 0)
        l_layout.addWidget(QLabel("Lernlevel:"))
        
        self.combo_level = NoWheelComboBox()
        self.combo_level.setMinimumWidth(scale(250))
        self.combo_level.setFixedHeight(scale(35))
        self.populate_levels()
        self.combo_level.currentIndexChanged.connect(self.on_level_changed)
        l_layout.addWidget(self.combo_level)
        l_layout.addStretch()
        
        self.layout.addWidget(self.level_widget)
        self.level_widget.setVisible(self.is_active)
        
        if self.is_active: self.setMinimumHeight(scale(130))
        else: self.setMinimumHeight(scale(55))

    def populate_levels(self):
        original_repo = self.main_window.repertoire_manager.active_repertoire_name
        self.main_window.repertoire_manager.set_active_repertoire(self.repo_name)
        levels = self.main_window.repertoire_manager.get_repertoire_levels()
        
        self.combo_level.blockSignals(True)
        self.combo_level.clear()
        for lvl in levels:
            self.combo_level.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
            
        active_lvl = self.main_window.training_manager.get_active_level()
        idx = self.combo_level.findData(active_lvl)
        if idx != -1: self.combo_level.setCurrentIndex(idx)
        self.combo_level.blockSignals(False)
        
        if original_repo:
            self.main_window.repertoire_manager.set_active_repertoire(original_repo)

    def toggle_active(self):
        self.is_active = not self.is_active
        self.btn_status.setText("Aktiv" if self.is_active else "Inaktiv")
        self.level_widget.setVisible(self.is_active)
        
        if self.is_active: self.setMinimumHeight(scale(130))
        else: self.setMinimumHeight(scale(55))
        
        self.main_window.training_manager.set_repo_visibility(self.repo_name, self.is_active)
        self.main_window.refresh_repertoire_buttons()
        self.update_style()
        self.clicked.emit()

    def on_level_changed(self):
        level = self.combo_level.currentData()
        if level is not None:
            original_repo = self.main_window.repertoire_manager.active_repertoire_name
            self.main_window.repertoire_manager.set_active_repertoire(self.repo_name)
            self.main_window.training_manager.set_active_level(level)
            if original_repo:
                self.main_window.repertoire_manager.set_active_repertoire(original_repo)

    def update_style(self):
        # Using a more premium glassmorphic/flat hybrid look
        if self.is_active:
            bg = "white"
            border = "2px solid #111111"
            opacity = "1"
        else:
            bg = "rgba(0,0,0,0.03)" # Reverting to gray background for buttons
            border = "1px solid rgba(0,0,0,0.1)"
            opacity = "0.7"
            
        self.setStyleSheet(f"""
            RepertoireConfigCard {{
                background-color: {bg};
                border: {border};
                border-radius: 12px;
            }}
            QLabel {{ 
                color: #111111;
                opacity: {opacity};
            }}
        """)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)
