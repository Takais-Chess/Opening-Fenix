import os
from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QFrame, QGraphicsDropShadowEffect, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS
from opening_fenix.core.translation import tr_ui
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_levels
from opening_fenix.core.services.tree_navigation_service import TreeNavigationService


def fetch_variation_structure_for_repo(repo_name: str) -> Dict[str, List[str]]:
    """Helper to fetch variation structure for any repertoire by name."""
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return {}
    db_manager = DatabaseManager(db_path)
    session = db_manager.get_session()
    try:
        nav = TreeNavigationService(session)
        return nav.get_variation_structure()
    except Exception:
        return {}
    finally:
        session.close()
        db_manager.close()


class OpenTrainingSetupDialog(QDialog):
    """
    Setup dialog presented when launching or configuring Freies Training (Open Training).
    Asks the user what they want to train: Repertoire, Level, and Variation.
    """
    def __init__(self, main_window, parent=None):
        parent_widget = parent if parent is not None else (main_window if isinstance(main_window, QWidget) else None)
        super().__init__(parent_widget)
        self.main_window = main_window
        self.repertoire_manager = main_window.repertoire_manager
        self.training_manager = main_window.training_manager

        self.setWindowTitle(tr_ui("open_training.dialog_title", "Freies Training"))
        self.setFixedWidth(scale(480))
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['beige']};
                border: 2px solid {COLORS['burnt_orange']};
                border-radius: {scale(12)}px;
            }}
            QLabel {{
                color: {COLORS['brown_text']};
                font-size: {scale(14)}px;
            }}
            QComboBox {{
                background-color: white;
                color: {COLORS['brown_text']};
                border: 1px solid #ccc;
                border-radius: {scale(6)}px;
                padding: {scale(8)}px;
                font-size: {scale(14)}px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                color: {COLORS['brown_text']};
                selection-background-color: {COLORS['burnt_orange']};
                selection-color: white;
            }}
        """)

        self.selected_repo = None
        self.selected_level = 999
        self.selected_variation = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Header Title
        lbl_header = QLabel(tr_ui("open_training.header", "🎯 Freies Training Setup"))
        font_header = QFont()
        font_header.setPointSize(scale(18))
        font_header.setBold(True)
        lbl_header.setFont(font_header)
        lbl_header.setStyleSheet(f"color: {COLORS['burnt_orange']};")
        layout.addWidget(lbl_header)

        # Subtitle prompt
        lbl_prompt = QLabel(tr_ui("open_training.prompt", "Was möchtest du trainieren?"))
        font_prompt = QFont()
        font_prompt.setPointSize(scale(13))
        font_prompt.setBold(True)
        lbl_prompt.setFont(font_prompt)
        layout.addWidget(lbl_prompt)

        # Divider line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #d1c7bd;")
        layout.addWidget(line)

        # 1. Repertoire Selection
        lbl_repo = QLabel(tr_ui("open_training.lbl_repertoire", "Repertoire:"))
        lbl_repo.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_repo)

        self.combo_repo = QComboBox()
        layout.addWidget(self.combo_repo)

        # 2. Level Selection
        lbl_level = QLabel(tr_ui("open_training.lbl_level", "Level:"))
        lbl_level.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_level)

        self.combo_level = QComboBox()
        layout.addWidget(self.combo_level)

        # 3. Variation Selection
        lbl_var = QLabel(tr_ui("open_training.lbl_variation", "Variation:"))
        lbl_var.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_var)

        self.combo_variation = QComboBox()
        layout.addWidget(self.combo_variation)

        # 4. Comment Language Selection
        lbl_comment_lang = QLabel(tr_ui("open_training.lbl_comment_lang", "Kommentarsprache:"))
        lbl_comment_lang.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_comment_lang)

        self.combo_comment_lang = QComboBox()
        self.combo_comment_lang.addItem(tr_ui("open_training.comment_lang_auto", "Automatisch (Programmsprache)"), "auto")
        self.combo_comment_lang.addItem(tr_ui("open_training.comment_lang_en", "Englisch (EN)"), "en")
        self.combo_comment_lang.addItem(tr_ui("open_training.comment_lang_de", "Deutsch (DE)"), "de")

        curr_comment_lang = self.training_manager.get_setting("comment_language") or "auto" if self.training_manager else "auto"
        idx_clang = self.combo_comment_lang.findData(curr_comment_lang)
        if idx_clang != -1:
            self.combo_comment_lang.setCurrentIndex(idx_clang)

        layout.addWidget(self.combo_comment_lang)

        # Populate Repertoires
        all_repos = self.repertoire_manager.get_all_repertoires() if self.repertoire_manager else []
        if not all_repos:
            self.combo_repo.addItem(tr_ui("open_training.no_repos_item", "(Keine Repertoires)"), None)
            self.combo_repo.setEnabled(False)
            self.combo_level.setEnabled(False)
            self.combo_variation.setEnabled(False)
            self.combo_comment_lang.setEnabled(False)
        else:
            for repo_name in all_repos:
                self.combo_repo.addItem(repo_name, repo_name)
            
            # Pre-select active repertoire if valid
            active = self.repertoire_manager.active_repertoire_name
            if active in all_repos:
                idx = self.combo_repo.findData(active)
                if idx != -1:
                    self.combo_repo.setCurrentIndex(idx)

        # Connect repertoire change to update level & variation dropdowns
        self.combo_repo.currentIndexChanged.connect(self._on_repo_changed)

        # Initial populate of level and variation for selected repo
        self._on_repo_changed()

        # Action Buttons Layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_cancel = QPushButton(tr_ui("open_training.btn_cancel", "Abbrechen"))
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: #e0e0e0;
                color: #333333;
                border: none;
                border-radius: {scale(8)}px;
                padding: {scale(10)}px {scale(16)}px;
                font-weight: bold;
                font-size: {scale(14)}px;
            }}
            QPushButton:hover {{
                background-color: #d0d0d0;
            }}
        """)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_start = QPushButton(tr_ui("open_training.btn_start", "🚀 Training starten"))
        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(8)}px;
                padding: {scale(10)}px {scale(20)}px;
                font-weight: bold;
                font-size: {scale(14)}px;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
        """)
        self.btn_start.clicked.connect(self._on_start_clicked)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_start)

        layout.addSpacing(10)
        layout.addLayout(btn_layout)

        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 8)
        self.setGraphicsEffect(shadow)

    def _on_repo_changed(self):
        repo_name = self.combo_repo.currentData()
        if not repo_name:
            self.combo_level.clear()
            self.combo_variation.clear()
            return

        # 1. Update Levels dropdown
        self.combo_level.blockSignals(True)
        self.combo_level.clear()

        # Add "All Levels" option
        self.combo_level.addItem(tr_ui("open_training.all_levels", "Alle Level (1 - Max)"), 999)

        db_path = get_repertoire_db_path(repo_name)
        if os.path.exists(db_path):
            db_manager = DatabaseManager(db_path)
            session = db_manager.get_session()
            try:
                levels = fetch_repertoire_levels(session)
                for lvl in levels:
                    lbl = f"Level {lvl['order']}: {lvl['name']}" if lvl['name'] else f"Level {lvl['order']}"
                    self.combo_level.addItem(lbl, lvl['order'])
            except Exception:
                pass
            finally:
                session.close()
                db_manager.close()

        # Pre-select currently active level if possible
        curr_lvl = self.training_manager.get_active_level(repo_name)
        idx_lvl = self.combo_level.findData(curr_lvl)
        if idx_lvl != -1:
            self.combo_level.setCurrentIndex(idx_lvl)
        else:
            self.combo_level.setCurrentIndex(0)

        self.combo_level.blockSignals(False)

        # 2. Update Variations dropdown
        self.combo_variation.blockSignals(True)
        self.combo_variation.clear()

        self.combo_variation.addItem(tr_ui("open_training.all_variations", "Alle Variationen"), None)

        structure = fetch_variation_structure_for_repo(repo_name)
        for v1, v2_list in structure.items():
            self.combo_variation.addItem(v1, v1)
            if v2_list:
                for v2 in v2_list:
                    self.combo_variation.addItem(f"  └ {v2}", v2)

        # Pre-select active variation filter if applicable
        if repo_name == self.repertoire_manager.active_repertoire_name and self.main_window.active_variation_filter:
            idx_var = self.combo_variation.findData(self.main_window.active_variation_filter)
            if idx_var != -1:
                self.combo_variation.setCurrentIndex(idx_var)
            else:
                self.combo_variation.setCurrentIndex(0)
        else:
            self.combo_variation.setCurrentIndex(0)

        self.combo_variation.blockSignals(False)

    def _on_start_clicked(self):
        repo_name = self.combo_repo.currentData()
        if not repo_name:
            QMessageBox.warning(
                self, 
                tr_ui("open_training.no_repo_title", "Kein Repertoire"), 
                tr_ui("open_training.no_repo_msg", "Bitte erstelle oder importiere erst ein Repertoire.")
            )
            return

        self.selected_repo = repo_name
        self.selected_level = self.combo_level.currentData() if self.combo_level.currentData() is not None else 999
        self.selected_variation = self.combo_variation.currentData()
        self.selected_comment_lang = self.combo_comment_lang.currentData() or "auto"
        if self.training_manager:
            self.training_manager.set_setting("comment_language", self.selected_comment_lang)
        self.accept()

    def get_selections(self):
        return self.selected_repo, self.selected_level, self.selected_variation, getattr(self, 'selected_comment_lang', 'auto')
