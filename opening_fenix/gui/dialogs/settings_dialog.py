import os
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QFormLayout, QComboBox, 
    QHBoxLayout, QLabel, QListWidget, QScrollArea, QFrame, 
    QGroupBox, QSpinBox, QPushButton, QCheckBox, QProgressBar, QSlider, 
    QLineEdit, QFileDialog, QMessageBox, QStackedWidget, QListWidgetItem,
    QTextEdit, QGridLayout
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from opening_fenix.core.data_tools import get_base_path, get_user_dir, get_repertoire_analysis_status
from opening_fenix.gui.widgets.board_widget import THEMES

# Import centralized styles
from opening_fenix.gui.styles import COLORS, get_repo_settings_style
from opening_fenix.gui.scaling import scale



class RepoLoadButton(QPushButton):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.repo_name = name
        self.setFixedHeight(scale(50))
        self.setStyleSheet(f"""

            QPushButton {{
                background-color: {COLORS['white']};
                color: {COLORS['brown_text']};
                border: 2px solid {COLORS['border']};
                border-radius: {scale(8)}px;
                font-size: {scale(16)}px;
                font-weight: bold;
            }}

            QPushButton:hover {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: 2px solid {COLORS['burnt_orange']};
            }}
        """)

class LoadRepertoireDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Repertoire Laden")
        self.setMinimumSize(scale(450), scale(400))
        self.selected_repo = None

        
        self.setStyleSheet(f"""
            QDialog {{ background-color: {COLORS['beige']}; }}
            QLabel {{ font-family: 'Segoe UI'; color: {COLORS['brown_text']}; font-size: {scale(20)}px; font-weight: bold; margin-bottom: {scale(10)}px; }}
            QScrollArea {{ border: none; background: transparent; }}
        """)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        lbl_title = QLabel("Repertoire laden")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter) # Center aligned as requested
        layout.addWidget(lbl_title)
        
        # Scroll Area for Buttons
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setSpacing(scale(10))
        
        repo_dir = os.path.join(get_user_dir(), "repertoires")

        if os.path.exists(repo_dir):
            row, col = 0, 0
            for f in os.listdir(repo_dir):
                if f.endswith(".db"):
                    name = f[:-3]
                    btn = RepoLoadButton(name)
                    btn.clicked.connect(lambda checked, n=name: self.on_repo_click(n))
                    self.grid_layout.addWidget(btn, row, col)
                    col += 1
                    if col > 1:  # 2 columns max
                        col = 0
                        row += 1
                        
        # Add stretch to push buttons to top
        self.grid_layout.setRowStretch(self.grid_layout.rowCount(), 1)
        
        self.scroll_area.setWidget(scroll_widget)
        layout.addWidget(self.scroll_area)
        
        # Bottom Buttons
        h_btn = QHBoxLayout()
        b_cancel = QPushButton("Abbrechen")
        b_cancel.setStyleSheet(f"""
            QPushButton {{ 
                font-family: 'Segoe UI'; font-size: {scale(14)}px; padding: {scale(10)}px {scale(15)}px; border-radius: {scale(8)}px; 
                background-color: {COLORS['dark_beige']}; color: {COLORS['brown_text']}; font-weight: bold; 
                border: 1px solid {COLORS['border']};
            }}

            QPushButton:hover {{ background-color: {COLORS['button_hover']}; }}
        """)
        b_cancel.clicked.connect(self.reject)
        
        h_btn.addStretch()
        h_btn.addWidget(b_cancel)
        layout.addLayout(h_btn)

    def on_repo_click(self, name):
        self.selected_repo = name
        self.accept()

class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Einstellungen")
        self.resize(scale(800), scale(600))
        
        self.setStyleSheet(get_repo_settings_style())



        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. SIDEBAR
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(scale(200))
        self.sidebar.currentRowChanged.connect(self.display_page)

        
        items = ["Darstellung & Audio", "Training & Verhalten", "Repertoires"]
        for text in items:
            item = QListWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.sidebar.addItem(item)
            
        layout.addWidget(self.sidebar)

        # 2. CONTENT AREA (Stacked Widget)
        self.pages = QStackedWidget()
        
        self.page_display = QWidget(); self.init_page_display(self.page_display)
        self.page_behavior = QWidget(); self.init_page_behavior(self.page_behavior)
        self.page_repo = QWidget(); self.init_page_repo(self.page_repo)
        
        self.pages.addWidget(self.page_display)
        self.pages.addWidget(self.page_behavior)
        self.pages.addWidget(self.page_repo)
        
        layout.addWidget(self.pages, 1)
        
        self.sidebar.setCurrentRow(0)

    def display_page(self, index):
        self.pages.setCurrentIndex(index)

    def init_page_display(self, page):
        l = QVBoxLayout(page)
        
        # Design Group
        grp_design = QGroupBox("Visuelles Design")
        form_design = QFormLayout(grp_design)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(THEMES.keys())
        self.combo_theme.setCurrentText(self.main_window.training_manager.get_setting("theme") or "Blau (Turnier)")
        self.combo_theme.currentTextChanged.connect(self.on_theme_changed)
        form_design.addRow("Brett-Farbe:", self.combo_theme)

        self.spin_anim = QSpinBox()
        self.spin_anim.setRange(50, 1000); self.spin_anim.setSuffix(" ms")
        self.spin_anim.setValue(self.main_window.training_manager.get_setting("anim_speed") or 300)
        self.spin_anim.valueChanged.connect(lambda v: self.main_window.training_manager.set_setting("anim_speed", v))
        self.spin_anim.setToolTip("Wie schnell (in Millisekunden) die Figuren über das Brett gleiten sollen.")
        form_design.addRow("Animations-Tempo:", self.spin_anim)
        l.addWidget(grp_design)
        
        # Audio Group
        grp_audio = QGroupBox("Audio Einstellungen")
        form_audio = QFormLayout(grp_audio)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.main_window.training_manager.get_setting("master_volume") or 100)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        
        self.lbl_volume = QLabel(f"{self.volume_slider.value()}%")
        h = QHBoxLayout(); h.addWidget(self.volume_slider); h.addWidget(self.lbl_volume)
        form_audio.addRow("Gesamtlautstärke:", h)
        l.addWidget(grp_audio)
        
        l.addStretch()

    def on_theme_changed(self, theme_name):
        self.main_window.training_manager.set_setting("theme", theme_name)
        self.main_window.apply_theme()

    def on_volume_changed(self, value):
        self.lbl_volume.setText(f"{value}%")
        self.main_window.training_manager.set_setting("master_volume", value)
        self.main_window.set_master_volume(value)

    def init_page_behavior(self, page):
        l = QVBoxLayout(page)
        grp = QGroupBox("Trainingsablauf")
        form = QFormLayout(grp)
        
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 2000); self.spin_delay.setSuffix(" ms")
        self.spin_delay.setValue(self.main_window.training_manager.get_setting("auto_delay") or 200)
        self.spin_delay.valueChanged.connect(lambda v: self.main_window.training_manager.set_setting("auto_delay", v))
        self.spin_delay.setToolTip("Wie lange (in Millisekunden) nach einem korrekten Zug gewartet werden soll, bevor die nächste Aufgabe geladen wird.")
        form.addRow("Auto-Weiter Verzögerung:", self.spin_delay)
        
        l.addWidget(grp); l.addStretch()

    def init_page_repo(self, page):
        self.selected_repo = None
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(15))


        # Dropdown for selecting the Repertoire to edit
        h_select = QHBoxLayout()
        h_select.addWidget(QLabel("<b>Repertoire auswählen:</b>"))
        
        self.combo_select_repo = QComboBox()
        self.combo_select_repo.setMinimumWidth(scale(250))
        repos = self.main_window.repertoire_manager.get_all_repertoires()

        self.combo_select_repo.addItems(repos)
        self.combo_select_repo.currentTextChanged.connect(self.on_repo_selected)
        h_select.addWidget(self.combo_select_repo)
        h_select.addStretch()
        layout.addLayout(h_select)

        # Scroll area for the details (gives it full width)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        self.details_layout = QVBoxLayout(scroll_widget)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Training Settings
        self.grp_train = QGroupBox("Trainingseinstellungen")
        self.train_form = QFormLayout(self.grp_train)
        
        self.combo_repo_level = QComboBox()
        self.combo_repo_level.currentIndexChanged.connect(self.on_level_changed)
        self.train_form.addRow("Maximales Trainings-Level:", self.combo_repo_level)
        
        self.chk_visible = QCheckBox("Repertoire für dieses Profil aktivieren (in der Top-Bar anzeigen)")
        self.chk_visible.clicked.connect(self.toggle_visibility)
        self.train_form.addRow("", self.chk_visible)

        self.details_layout.addWidget(self.grp_train)

        # 2. Information
        self.grp_info = QGroupBox("Informationen")
        self.info_form = QFormLayout(self.grp_info)
        self.lbl_name = QLabel("-")
        self.lbl_color = QLabel("-")
        self.lbl_levels = QLabel("-")
        self.lbl_depth = QLabel("-")
        self.lbl_elo = QLabel("-")
        self.lbl_moves = QLabel("-")
        self.txt_description = QTextEdit()
        self.txt_description.setReadOnly(True)
        self.txt_description.setMaximumHeight(scale(80))
        
        self.info_form.addRow("Name:", self.lbl_name)

        self.info_form.addRow("Farbe:", self.lbl_color)
        self.info_form.addRow("Levels:", self.lbl_levels)
        self.info_form.addRow("Analyse-Status:", self.lbl_depth)
        self.info_form.addRow("Lichess Elo:", self.lbl_elo)
        self.info_form.addRow("Anzahl Züge:", self.lbl_moves)
        self.info_form.addRow("Beschreibung:", self.txt_description)
        self.details_layout.addWidget(self.grp_info)

        self.danger_layout.addWidget(self.btn_reset)
        self.details_layout.addWidget(self.grp_danger)
        
        # 4. Bulk Actions
        self.grp_bulk = QGroupBox("Massen-Aktionen")
        self.bulk_form = QFormLayout(self.grp_bulk)
        
        self.combo_bulk_level = QComboBox()
        self.bulk_form.addRow("Ziel-Level:", self.combo_bulk_level)
        
        self.btn_bulk_move = QPushButton("Alle Züge auf dieses Level setzen")
        self.btn_bulk_move.clicked.connect(self.move_all_moves_to_level)
        self.btn_bulk_move.setToolTip("Setzt das Level ALLER Züge in diesem Repertoire auf das oben ausgewählte Level.")
        self.bulk_form.addRow("", self.btn_bulk_move)
        
        self.details_layout.addWidget(self.grp_bulk)

        self.details_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        
        # Initialize with the currently active repertoire if possible
        active_repo = self.main_window.repertoire_manager.active_repertoire_name
        if active_repo:
            self.combo_select_repo.setCurrentText(active_repo)
        elif repos:
            self.combo_select_repo.setCurrentIndex(0)

    def on_repo_selected(self, repo_name):
        if not repo_name: return
        self.selected_repo = repo_name
        
        # Save current repo state to restore later
        original_repo = self.main_window.repertoire_manager.active_repertoire_name
        
        # Set to selected repo to fetch info
        self.main_window.repertoire_manager.set_active_repertoire(repo_name)
        
        info = self.main_window.repertoire_manager.get_repertoire_info()
        analysis_status = get_repertoire_analysis_status(repo_name)
        
        self.lbl_name.setText(info.get("name", "-"))
        self.lbl_color.setText("Weiß" if self.main_window.repertoire_manager.get_repertoire_color() == 'w' else "Schwarz")
        self.lbl_levels.setText(", ".join(info.get("levels", [])) or "-")
        self.lbl_depth.setText(analysis_status)
        self.lbl_elo.setText(info.get("elo", "-"))
        self.lbl_moves.setText(str(info.get("moves", "0")))
        self.txt_description.setPlainText(info.get("description", ""))
        
        self.combo_repo_level.blockSignals(True)
        self.combo_repo_level.clear()
        self.combo_bulk_level.clear()
        levels = self.main_window.repertoire_manager.get_repertoire_levels()
        for lvl in levels:
            lvl_text = f"Level {lvl['order']} ({lvl['name']})"
            self.combo_repo_level.addItem(lvl_text, userData=lvl['order'])
            self.combo_bulk_level.addItem(lvl_text, userData=lvl['order'])
        
        active_lvl = self.main_window.training_manager.get_active_level()
        idx = self.combo_repo_level.findData(active_lvl)
        if idx != -1: self.combo_repo_level.setCurrentIndex(idx)
        self.combo_repo_level.blockSignals(False)
        
        self.chk_visible.setChecked(self.main_window.training_manager.is_repo_visible(repo_name))
        
        # Restore
        if original_repo and original_repo != repo_name:
            self.main_window.repertoire_manager.set_active_repertoire(original_repo)

    def on_level_changed(self, index):
        if self.selected_repo:
            level_order = self.combo_repo_level.currentData()
            if level_order is not None:
                # We need to temporarily set the manager to the selected repo to update its specific setting
                original_repo = self.main_window.repertoire_manager.active_repertoire_name
                self.main_window.repertoire_manager.set_active_repertoire(self.selected_repo)
                
                self.main_window.training_manager.set_active_level(level_order)
                
                # Restore
                if original_repo and original_repo != self.selected_repo:
                    self.main_window.repertoire_manager.set_active_repertoire(original_repo)

    def toggle_visibility(self):
        if self.selected_repo:
            self.main_window.training_manager.set_repo_visibility(self.selected_repo, self.chk_visible.isChecked())
            self.main_window.refresh_repertoire_buttons()

    def reset_repo_progress(self):
        if not self.selected_repo: return
        if QMessageBox.question(self, "Reset", f"Fortschritt für {self.selected_repo} wirklich löschen?") == QMessageBox.StandardButton.Yes:
            original_repo = self.main_window.repertoire_manager.active_repertoire_name
            self.main_window.repertoire_manager.set_active_repertoire(self.selected_repo)
            
            self.main_window.training_manager.reset_repertoire_progress()
            
            if original_repo and original_repo != self.selected_repo:
                self.main_window.repertoire_manager.set_active_repertoire(original_repo)
                
            QMessageBox.information(self, "Erfolg", "Fortschritt zurückgesetzt.")
            self.main_window.refresh_repertoire_buttons()

    def move_all_moves_to_level(self):
        if not self.selected_repo: return
        
        target_level = self.combo_bulk_level.currentData()
        level_name = self.combo_bulk_level.currentText()
        
        if target_level is None: return
        
        msg = f"Möchten Sie wirklich ALLE Züge des Repertoires '{self.selected_repo}' auf '{level_name}' setzen?"
        if QMessageBox.question(self, "Bestätigung", msg) == QMessageBox.StandardButton.Yes:
            # Temporarily switch to the selected repo
            original_repo = self.main_window.repertoire_manager.active_repertoire_name
            self.main_window.repertoire_manager.set_active_repertoire(self.selected_repo)
            
            count = self.main_window.repertoire_manager.move_all_to_level(target_level)
            
            # Restore
            if original_repo and original_repo != self.selected_repo:
                self.main_window.repertoire_manager.set_active_repertoire(original_repo)
                
            QMessageBox.information(self, "Erfolg", f"{count} Züge wurden auf {level_name} gesetzt.")
