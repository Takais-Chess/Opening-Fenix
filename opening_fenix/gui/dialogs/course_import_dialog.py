import os
import sys
from typing import Optional, Dict, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QComboBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QProgressBar, QMessageBox, QWidget, QFrame, QAbstractItemView,
    QTableWidget, QTableWidgetItem, QCheckBox, QApplication,
    QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, QTimer, QCoreApplication
from PyQt6.QtGui import QFont, QPixmap

from opening_fenix.core.services.course_import_service import (
    analyze_course_pgns,
    CourseAnalysisResult,
    CourseChapterInfo,
    CourseGameInfo,
    CourseImportPlan,
    CourseImportResult,
    CATEGORY_LEVEL_1,
    CATEGORY_LEVEL_2,
    CATEGORY_MOTIVES,
    CATEGORY_TACTICS,
    CATEGORY_MODEL,
    CATEGORY_INTRO,
    CATEGORY_IGNORE
)
from opening_fenix.core.threads import CourseImportThread
from opening_fenix.gui.styles import get_login_dialog_style, COLORS, set_consistent_icon, get_chevron_icon_path
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui, translator
from opening_fenix.core.utils import get_elo_display, ELO_DISPLAY_MAP
from opening_fenix.gui.native_close_filter import install_taskbar_close_filter, uninstall_taskbar_close_filter

class NoWheelComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events to prevent accidental value changes while scrolling."""
    def wheelEvent(self, event):
        event.ignore()

CATEGORY_BADGE_INFO = {
    CATEGORY_LEVEL_1: ("⚡", "Quickstarter"),
    CATEGORY_LEVEL_2: ("📚", "Tiefe Theorie"),
    CATEGORY_MOTIVES: ("💡", "Motive"),
    CATEGORY_TACTICS: ("🧩", "Puzzles"),
    CATEGORY_MODEL: ("🏆", "Muster"),
    CATEGORY_INTRO: ("📖", "Einleitung"),
    CATEGORY_IGNORE: ("🚫", "Ignoriert"),
}

class ChapterLinesDialog(QDialog):
    """
    Dedicated modal dialog for inspecting and customizing individual lines within a chapter.
    Supports real-time search filtering, bulk selection, bulk destination setting,
    and individual line dropdowns.
    """
    def __init__(self, chapter: CourseChapterInfo, default_target: str, current_game_targets: Dict[int, str], parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.chapter = chapter
        self.default_target = default_target
        self.result_targets: Dict[int, str] = {}
        
        # Working copy of targets
        self.game_targets: Dict[int, str] = {}
        for g in chapter.games:
            if g.game_id in current_game_targets:
                self.game_targets[g.game_id] = current_game_targets[g.game_id]
            else:
                if default_target not in (CATEGORY_TACTICS, CATEGORY_MODEL, CATEGORY_INTRO, CATEGORY_IGNORE, CATEGORY_MOTIVES):
                    if g.is_puzzle:
                        self.game_targets[g.game_id] = CATEGORY_TACTICS
                    elif g.is_model:
                        self.game_targets[g.game_id] = CATEGORY_MODEL
                    elif g.is_intro:
                        self.game_targets[g.game_id] = CATEGORY_INTRO
                    else:
                        self.game_targets[g.game_id] = default_target
                else:
                    self.game_targets[g.game_id] = default_target

        self.setWindowTitle(tr_ui("course_import.dlg_edit_lines_title", "Linien anpassen: {chapter}", chapter=chapter.name))
        self.setMinimumSize(scale(760), scale(560))
        self.resize(scale(840), scale(620))
        self.setStyleSheet(get_login_dialog_style())

        self.target_options = [
            (CATEGORY_LEVEL_1, tr_ui("course_import.target_level_1", "⚡ Level 1 (Quickstarter)")),
            (CATEGORY_LEVEL_2, tr_ui("course_import.target_level_2", "📚 Level 2 (Tiefe Theorie)")),
            (CATEGORY_MOTIVES, tr_ui("course_import.target_motives", "💡 Typische Motive (Typical Motives.pgn)")),
            (CATEGORY_TACTICS, tr_ui("course_import.target_tactics", "🧩 Taktik (Tactics.pgn)")),
            (CATEGORY_MODEL, tr_ui("course_import.target_model", "🏆 Musterpartie (Model Games.pgn)")),
            (CATEGORY_INTRO, tr_ui("course_import.target_intro", "📖 Einleitung (Introductions from pgn import.pgn)")),
            (CATEGORY_IGNORE, tr_ui("course_import.target_ignore", "🚫 Ignorieren (Überspringen)")),
        ]

        self.table_combos: Dict[int, NoWheelComboBox] = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(20), scale(16), scale(20), scale(16))
        layout.setSpacing(scale(10))

        # Title & Subtitle
        lbl_title = QLabel(self.chapter.name)
        lbl_title.setStyleSheet(f"font-size: {scale(16)}px; font-weight: bold; color: {COLORS['brown_text']}; border: none; background: transparent;")
        layout.addWidget(lbl_title)

        # Header info & category breakdown badges
        self.header_info_layout = QHBoxLayout()
        self.header_info_layout.setSpacing(scale(8))

        self.lbl_sub = QLabel(tr_ui("course_import.games_multi", "{count} Partien", count=len(self.chapter.games)))
        self.lbl_sub.setStyleSheet(f"font-size: {scale(12)}px; color: #666; border: none; background: transparent;")
        self.header_info_layout.addWidget(self.lbl_sub)

        self.badges_container = QWidget()
        self.badges_layout = QHBoxLayout(self.badges_container)
        self.badges_layout.setContentsMargins(0, 0, 0, 0)
        self.badges_layout.setSpacing(scale(6))
        self.header_info_layout.addWidget(self.badges_container)
        self.header_info_layout.addStretch()

        layout.addLayout(self.header_info_layout)
        self._refresh_header_breakdown()

        # Search Bar & Bulk Actions
        filter_card = QFrame()
        filter_card.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 0.65);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
            }}
        """)
        v_filter = QVBoxLayout(filter_card)
        v_filter.setContentsMargins(scale(10), scale(8), scale(10), scale(8))
        v_filter.setSpacing(scale(8))

        # Search line edit
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr_ui("course_import.search_lines_placeholder", "Linie suchen (z. B. Variante, ECO)..."))
        self.search_input.setFixedHeight(scale(32))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: white;
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                padding: 0 {scale(8)}px;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
            }}
            QLineEdit:focus {{
                border: 1.5px solid {COLORS['burnt_orange']};
            }}
        """)
        self.search_input.textChanged.connect(self.on_search_changed)
        v_filter.addWidget(self.search_input)

        # Bulk Actions Row
        row_bulk = QHBoxLayout()
        row_bulk.setSpacing(scale(8))

        btn_select_all = QPushButton(tr_ui("course_import.btn_select_all", "Alle markieren"))
        btn_select_all.setFixedHeight(scale(28))
        btn_select_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_select_all.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(4)}px;
                padding: 0 {scale(10)}px;
                font-size: {scale(11)}px;
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: white;
            }}
        """)
        btn_select_all.clicked.connect(self.on_select_all)
        row_bulk.addWidget(btn_select_all)

        btn_deselect_all = QPushButton(tr_ui("course_import.btn_deselect_all", "Auswahl aufheben"))
        btn_deselect_all.setFixedHeight(scale(28))
        btn_deselect_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_deselect_all.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(4)}px;
                padding: 0 {scale(10)}px;
                font-size: {scale(11)}px;
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: white;
            }}
        """)
        btn_deselect_all.clicked.connect(self.on_deselect_all)
        row_bulk.addWidget(btn_deselect_all)

        row_bulk.addStretch()

        lbl_bulk_apply = QLabel(tr_ui("course_import.bulk_apply", "Markierte setzen auf:"))
        lbl_bulk_apply.setStyleSheet(f"font-size: {scale(11)}px; font-weight: bold; color: {COLORS['brown_text']}; border: none; background: transparent;")
        row_bulk.addWidget(lbl_bulk_apply)

        self.bulk_combo = NoWheelComboBox()
        self.bulk_combo.setFixedHeight(scale(28))
        self.bulk_combo.setStyleSheet(self._get_combo_style())
        for cat_id, cat_label in self.target_options:
            self.bulk_combo.addItem(cat_label, cat_id)
        row_bulk.addWidget(self.bulk_combo)

        btn_apply = QPushButton(tr_ui("course_import.btn_apply", "Zuweisen"))
        btn_apply.setFixedHeight(scale(28))
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(4)}px;
                padding: 0 {scale(12)}px;
                font-size: {scale(11)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
        """)
        btn_apply.clicked.connect(self.on_apply_bulk)
        row_bulk.addWidget(btn_apply)

        v_filter.addLayout(row_bulk)
        layout.addWidget(filter_card)

        # Table of Lines
        self.table = QTableWidget(len(self.chapter.games), 4)
        self.table.setHorizontalHeaderLabels([
            "✓",
            tr_ui("course_import.col_chapter_tree", "Linie / Variante"),
            tr_ui("course_import.col_details", "Typ / Info"),
            tr_ui("course_import.col_target", "Ziel-Zuweisung")
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, scale(36))
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, scale(230))

        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: rgba(255, 255, 255, 0.7);
                alternate-background-color: rgba(245, 243, 238, 0.7);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
                outline: none;
            }}
            QHeaderView::section {{
                background-color: rgba(255, 255, 255, 0.9);
                border: none;
                border-bottom: 1px solid {COLORS['glass_border']};
                font-weight: bold;
                padding: {scale(6)}px {scale(8)}px;
                color: {COLORS['brown_text']};
            }}
        """)

        for row, g in enumerate(self.chapter.games):
            self.table.setRowHeight(row, scale(32))

            # Checkbox item
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, chk_item)

            # Title item
            title_item = QTableWidgetItem(g.title)
            title_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            title_item.setToolTip(f"{g.title}\n{g.chapter_name}")
            self.table.setItem(row, 1, title_item)

            # Type / Info item
            if g.is_puzzle:
                txt_type = "🧩 Puzzle"
            elif g.is_model:
                txt_type = "🏆 Muster"
            elif g.is_intro:
                txt_type = "📖 Einleitung"
            elif g.eco:
                txt_type = f"ECO {g.eco}"
            else:
                txt_type = tr_ui("course_import.line_badge", "Linie")
            type_item = QTableWidgetItem(txt_type)
            type_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, type_item)

            # ComboBox
            cb = NoWheelComboBox()
            cb.setFixedHeight(scale(26))
            cb.setStyleSheet(self._get_combo_style())
            for cat_id, cat_label in self.target_options:
                cb.addItem(cat_label, cat_id)
            
            curr_target = self.game_targets.get(g.game_id, self.default_target)
            idx = cb.findData(curr_target)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            
            cb.currentIndexChanged.connect(
                lambda _, c=cb, gid=g.game_id: self._on_line_target_changed(gid, c.currentData())
            )
            self.table.setCellWidget(row, 3, cb)
            self.table_combos[g.game_id] = cb

        layout.addWidget(self.table, 1)

        # Footer
        row_footer = QHBoxLayout()
        row_footer.setSpacing(scale(10))

        self.lbl_selected_count = QLabel("")
        self.lbl_selected_count.setStyleSheet(f"font-size: {scale(11)}px; color: #666; border: none; background: transparent;")
        row_footer.addWidget(self.lbl_selected_count)

        row_footer.addStretch()

        btn_cancel = QPushButton(tr_ui("course_import.btn_cancel", "Abbrechen"))
        btn_cancel.setFixedHeight(scale(34))
        btn_cancel.setFixedWidth(scale(110))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.6);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                color: {COLORS['brown_text']};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.9);
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        row_footer.addWidget(btn_cancel)

        btn_save = QPushButton(tr_ui("course_import.btn_save", "Übernehmen"))
        btn_save.setFixedHeight(scale(34))
        btn_save.setFixedWidth(scale(130))
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(6)}px;
                font-weight: bold;
                font-size: {scale(12)}px;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
        """)
        btn_save.clicked.connect(self.on_accept_changes)
        row_footer.addWidget(btn_save)

        layout.addLayout(row_footer)

    def _get_combo_style(self):
        return f"""
            QComboBox {{
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(0, 0, 0, 0.15);
                border-radius: {scale(6)}px;
                padding: 0 {scale(24)}px 0 {scale(8)}px;
                font-size: {scale(11)}px;
                color: {COLORS['brown_text']};
            }}
            QComboBox:hover {{
                border: 1.5px solid {COLORS['burnt_orange']};
            }}
            QComboBox:focus {{
                border: 1.5px solid {COLORS['burnt_orange']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {scale(20)}px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
            }}
            QComboBox::down-arrow {{
                image: url("{get_chevron_icon_path()}");
                width: {scale(10)}px;
                height: {scale(10)}px;
                margin-right: {scale(6)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['beige']};
                color: {COLORS['brown_text']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                selection-background-color: rgba(211, 84, 0, 0.15);
                selection-color: {COLORS['burnt_orange']};
                padding: {scale(2)}px;
                outline: none;
            }}
        """

    def _refresh_header_breakdown(self):
        while self.badges_layout.count():
            item = self.badges_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        counts = {}
        for g in self.chapter.games:
            target = self.game_targets.get(g.game_id, self.default_target)
            counts[target] = counts.get(target, 0) + 1

        is_mixed = len(counts) > 1
        if is_mixed:
            tag_mixed = QLabel(tr_ui("course_import.mixed_categories_badge", "🎨 Gemischt:"))
            tag_mixed.setStyleSheet(f"font-size: {scale(11)}px; font-weight: bold; color: {COLORS['burnt_orange']}; border: none; background: transparent;")
            self.badges_layout.addWidget(tag_mixed)

            badge_styles = {
                CATEGORY_LEVEL_1: ("rgba(255, 235, 150, 0.65)", "#f1c40f"),
                CATEGORY_LEVEL_2: ("rgba(174, 214, 241, 0.65)", "#3498db"),
                CATEGORY_MOTIVES: ("rgba(254, 249, 231, 0.85)", "#e67e22"),
                CATEGORY_TACTICS: ("rgba(212, 239, 223, 0.65)", "#2ecc71"),
                CATEGORY_MODEL: ("rgba(235, 222, 240, 0.65)", "#9b59b6"),
                CATEGORY_INTRO: ("rgba(230, 230, 230, 0.65)", "#95a5a6"),
                CATEGORY_IGNORE: ("rgba(250, 219, 216, 0.65)", "#e74c3c"),
            }
            order_map = {
                CATEGORY_LEVEL_1: 0,
                CATEGORY_LEVEL_2: 1,
                CATEGORY_MOTIVES: 2,
                CATEGORY_TACTICS: 3,
                CATEGORY_MODEL: 4,
                CATEGORY_INTRO: 5,
                CATEGORY_IGNORE: 6
            }
            for cat in sorted(counts.keys(), key=lambda c: order_map.get(c, 99)):
                cnt = counts[cat]
                icon, name = CATEGORY_BADGE_INFO.get(cat, ("", cat))
                bg, border = badge_styles.get(cat, ("rgba(255,255,255,0.8)", COLORS['glass_border']))
                b = QLabel(f"{icon} {cnt}× {name}")
                b.setStyleSheet(f"""
                    background-color: {bg};
                    border: 1px solid {border};
                    border-radius: {scale(4)}px;
                    padding: 0 {scale(6)}px;
                    font-size: {scale(11)}px;
                    font-weight: bold;
                    color: {COLORS['brown_text']};
                """)
                self.badges_layout.addWidget(b)
            self.badges_container.setVisible(True)
        else:
            self.badges_container.setVisible(False)

    def _on_line_target_changed(self, game_id: int, target: str):
        self.game_targets[game_id] = target
        self._refresh_header_breakdown()

    def on_search_changed(self, text: str):
        q = text.strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            item_type = self.table.item(row, 2)
            title = item.text().lower() if item else ""
            t_info = item_type.text().lower() if item_type else ""
            match = (q in title) or (q in t_info)
            self.table.setRowHidden(row, not match)

    def on_select_all(self):
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                item = self.table.item(row, 0)
                if item:
                    item.setCheckState(Qt.CheckState.Checked)

    def on_deselect_all(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def on_apply_bulk(self):
        target = self.bulk_combo.currentData()
        count = 0
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                g = self.chapter.games[row]
                self.game_targets[g.game_id] = target
                cb = self.table_combos.get(g.game_id)
                if cb:
                    cb.blockSignals(True)
                    idx = cb.findData(target)
                    if idx >= 0:
                        cb.setCurrentIndex(idx)
                    cb.blockSignals(False)
                count += 1
        
        self._refresh_header_breakdown()
        
        target_name = self.bulk_combo.currentText()
        if count > 0:
            self.lbl_selected_count.setText(
                tr_ui("course_import.bulk_assigned_info", "{count} Linie(n) auf '{target}' gesetzt.", count=count, target=target_name)
            )

    def on_accept_changes(self):
        self.result_targets = dict(self.game_targets)
        self.accept()

class CourseImportDialog(QDialog):
    """
    Automated Course Import Assistant Dialog.
    Supports single or multiple PGN files (e.g. Part 1 + Part 2), smart classification,
    per-game puzzle extraction, customizable chapter and line-level targets.
    """
    _FORBIDDEN_CHARS = set('\\/:*?"<>|')

    def __init__(self, parent=None, initial_pgn_path: Optional[str] = None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("course_import.window_title", "Kurs-Import-Assistent (Chessable PGN)"))
        self.setMinimumSize(scale(760), scale(320))
        self.resize(scale(840), scale(350))
        self.setStyleSheet(get_login_dialog_style())

        self.selected_paths: List[str] = []
        self.analysis_result: Optional[CourseAnalysisResult] = None
        self.import_thread: Optional[CourseImportThread] = None
        self.imported_repo_name: Optional[str] = None
        self.custom_chapter_targets: Dict[str, str] = {}
        self.custom_game_targets: Dict[int, str] = {}
        self.chapter_combos: Dict[str, NoWheelComboBox] = {}
        self.game_combos: Dict[int, NoWheelComboBox] = {}
        self.chapter_items: Dict[str, QTreeWidgetItem] = {}
        self.game_to_chapter: Dict[int, CourseChapterInfo] = {}
        self._details_expanded = False
        self._taskbar_filter = None

        self.init_ui()
        self._install_taskbar_close_filter()

        if initial_pgn_path and os.path.exists(initial_pgn_path):
            self.load_files([initial_pgn_path])

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scale(24), scale(18), scale(24), scale(18))
        main_layout.setSpacing(scale(12))

        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(scale(6))

        title_row = QHBoxLayout()
        title_row.setSpacing(scale(10))
        title_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_title = QLabel(tr_ui("course_import.dialog_title", "⚡ Automatisierter Kurs-Import"))
        lbl_title.setObjectName("LoginTitle")
        title_row.addWidget(lbl_title)

        self.badge_experimental = QLabel(tr_ui("course_import.badge_experimental", "🧪 Experimentell"))
        self.badge_experimental.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(230, 126, 34, 0.14);
                color: {COLORS['burnt_orange']};
                border: 1.5px solid {COLORS['burnt_orange']};
                border-radius: {scale(11)}px;
                padding: {scale(2)}px {scale(10)}px;
                font-size: {scale(11)}px;
                font-weight: bold;
            }}
        """)
        title_row.addWidget(self.badge_experimental)
        header_layout.addLayout(title_row)

        self.lbl_sub = QLabel(
            tr_ui(
                "course_import.subtitle_initial",
                "<b>Experimentelle Funktion:</b> Liest Kurs-PGNs (z. B. von Chessable) ein und versucht, diese automatisch in ein Repertoire mit <b>Quickstarter</b>, <b>Tiefe Theorie</b>, <b>Motiven</b> und <b>Puzzles</b> zu strukturieren.<br><span style='color: #c0392b;'>Hinweis:</span> Externe Kursformate variieren stark – die automatische Erkennung funktioniert daher noch nicht bei jedem Kurs fehlerfrei."
            )
        )
        self.lbl_sub.setObjectName("LoginSubtitle")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_sub.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.5);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                padding: {scale(8)}px {scale(14)}px;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
            }}
        """)
        header_layout.addWidget(self.lbl_sub)
        main_layout.addLayout(header_layout)

        # 1. File Selection Section (supports multiple files)
        file_box = QFrame()
        file_box.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 0.55);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(10)}px;
            }}
        """)
        v_file_box = QVBoxLayout(file_box)
        v_file_box.setContentsMargins(scale(14), scale(12), scale(14), scale(10))
        v_file_box.setSpacing(scale(6))

        f_layout = QHBoxLayout()
        f_layout.setContentsMargins(0, 0, 0, 0)
        f_layout.setSpacing(scale(10))

        lbl_file = QLabel(tr_ui("course_import.lbl_file", "Kurs-PGN:"))
        lbl_file.setStyleSheet(f"font-weight: bold; font-size: {scale(13)}px; color: {COLORS['brown_text']}; border: none; background: transparent;")
        f_layout.addWidget(lbl_file)

        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("z.B. Part 1.pgn, Part 2.pgn...")
        self.file_input.setReadOnly(True)
        self.file_input.setFixedHeight(scale(34))
        self.file_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                padding: 0 {scale(8)}px;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
            }}
        """)
        f_layout.addWidget(self.file_input, 1)

        self.btn_browse = QPushButton(tr_ui("course_import.btn_select_file", "📄 PGNs auswählen..."))
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.setFixedHeight(scale(34))
        self.btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.85);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                padding: 0 {scale(14)}px;
                font-weight: bold;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 1.0);
                border-color: {COLORS['burnt_orange']};
            }}
        """)
        self.btn_browse.clicked.connect(self.on_browse_files)
        f_layout.addWidget(self.btn_browse)
        v_file_box.addLayout(f_layout)

        self.lbl_file_hint = QLabel(tr_ui("course_import.file_hint", "Wähle eine oder mehrere PGN-Dateien aus (z. B. Part 1.pgn, Part 2.pgn), um die Analyse zu starten."))
        self.lbl_file_hint.setStyleSheet(f"font-size: {scale(11)}px; color: #7f8c8d; font-style: italic; border: none; background: transparent; padding-left: {scale(2)}px;")
        v_file_box.addWidget(self.lbl_file_hint)

        main_layout.addWidget(file_box)

        # Bottom Section (Hidden until PGN is selected and loaded)
        self.bottom_container = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(scale(12))

        # 2. Configuration Box
        self.config_box = QFrame()
        self.config_box.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(10)}px;
            }}
        """)
        cfg_layout = QVBoxLayout(self.config_box)
        cfg_layout.setContentsMargins(scale(14), scale(12), scale(14), scale(12))
        cfg_layout.setSpacing(scale(10))

        # Row 1: Repertoire Name (Full Width so long course names are fully visible)
        v_name = QVBoxLayout()
        v_name.setSpacing(scale(3))
        lbl_name = QLabel(tr_ui("course_import.lbl_repo_name", "Repertoire-Name:"))
        lbl_name.setStyleSheet(f"font-weight: bold; font-size: {scale(12)}px; color: {COLORS['brown_text']}; border: none; background: transparent;")
        self.name_input = QLineEdit()
        self.name_input.setFixedHeight(scale(36))
        self.name_input.setClearButtonEnabled(True)
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                padding: 0 {scale(26)}px 0 {scale(10)}px;
                font-size: {scale(13)}px;
                color: {COLORS['brown_text']};
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['burnt_orange']};
            }}
        """)
        self.name_input.textChanged.connect(lambda t: self.name_input.setToolTip(t))
        v_name.addWidget(lbl_name)
        v_name.addWidget(self.name_input)
        cfg_layout.addLayout(v_name)

        # Row 2: Color, Elo, Language
        row_opts = QHBoxLayout()
        row_opts.setSpacing(scale(14))

        # Color
        v_color = QVBoxLayout()
        v_color.setSpacing(scale(3))
        lbl_color = QLabel(tr_ui("course_import.lbl_color", "Deine Farbe:"))
        lbl_color.setStyleSheet(f"font-weight: bold; font-size: {scale(12)}px; color: {COLORS['brown_text']}; border: none; background: transparent;")
        self.color_combo = QComboBox()
        self.color_combo.setFixedHeight(scale(36))
        self.color_combo.addItem(tr_ui("course_import.color_white", "♔ Weiß"), "w")
        self.color_combo.addItem(tr_ui("course_import.color_black", "♚ Schwarz"), "b")
        cfg_combo_style = f"""
            QComboBox {{
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                padding: 0 {scale(26)}px 0 {scale(10)}px;
                font-size: {scale(13)}px;
                color: {COLORS['brown_text']};
            }}
            QComboBox:hover {{
                border: 1.5px solid {COLORS['burnt_orange']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {scale(22)}px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
            }}
            QComboBox::down-arrow {{
                image: url("{get_chevron_icon_path()}");
                width: {scale(11)}px;
                height: {scale(11)}px;
                margin-right: {scale(6)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['beige']};
                color: {COLORS['brown_text']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                selection-background-color: rgba(211, 84, 0, 0.15);
                selection-color: {COLORS['burnt_orange']};
                padding: {scale(2)}px;
                outline: none;
            }}
        """
        self.color_combo.setStyleSheet(cfg_combo_style)
        v_color.addWidget(lbl_color)
        v_color.addWidget(self.color_combo)
        row_opts.addLayout(v_color, 1)

        # Lichess Elo
        v_elo = QVBoxLayout()
        v_elo.setSpacing(scale(3))
        lbl_elo = QLabel(tr_ui("course_import.lbl_elo", "Lichess Elo:"))
        lbl_elo.setStyleSheet(f"font-weight: bold; font-size: {scale(12)}px; color: {COLORS['brown_text']}; border: none; background: transparent;")
        self.elo_combo = QComboBox()
        self.elo_combo.setFixedHeight(scale(36))
        for k in ELO_DISPLAY_MAP.keys():
            self.elo_combo.addItem(get_elo_display(k), k)
        idx_high = self.elo_combo.findData("high")
        if idx_high >= 0:
            self.elo_combo.setCurrentIndex(idx_high)
        self.elo_combo.setStyleSheet(cfg_combo_style)
        v_elo.addWidget(lbl_elo)
        v_elo.addWidget(self.elo_combo)
        row_opts.addLayout(v_elo, 2)

        # Comment Language
        v_lang = QVBoxLayout()
        v_lang.setSpacing(scale(3))
        lbl_lang = QLabel(tr_ui("course_import.lbl_lang", "Kommentar-Sprache:"))
        lbl_lang.setStyleSheet(f"font-weight: bold; font-size: {scale(12)}px; color: {COLORS['brown_text']}; border: none; background: transparent;")
        self.lang_combo = QComboBox()
        self.lang_combo.setFixedHeight(scale(36))
        self.lang_combo.addItem("English (EN)", "en")
        self.lang_combo.addItem("Deutsch (DE)", "de")
        self.lang_combo.addItem(tr_ui("creator.comment_lang_auto", "Automatisch"), "auto")

        # Set default to active app language
        app_lang = getattr(translator, "current_lang", "de")
        idx_lang = self.lang_combo.findData(app_lang)
        if idx_lang >= 0:
            self.lang_combo.setCurrentIndex(idx_lang)

        self.lang_combo.setStyleSheet(cfg_combo_style)
        v_lang.addWidget(lbl_lang)
        v_lang.addWidget(self.lang_combo)
        row_opts.addLayout(v_lang, 2)

        cfg_layout.addLayout(row_opts)

        # Cover status
        self.lbl_cover_status = QLabel("")
        self.lbl_cover_status.setStyleSheet(f"font-size: {scale(11)}px; color: #555; border: none; background: transparent; padding-top: {scale(2)}px;")
        cfg_layout.addWidget(self.lbl_cover_status)

        bottom_layout.addWidget(self.config_box)

        # 3. Overview Badges
        self.cards_frame = QFrame()
        self.cards_frame.setStyleSheet("background: transparent; border: none;")
        cards_layout = QHBoxLayout(self.cards_frame)
        cards_layout.setContentsMargins(0, scale(2), 0, scale(2))
        cards_layout.setSpacing(scale(8))

        def create_badge(title, color_bg, border_color):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {color_bg};
                    border: 1.5px solid {border_color};
                    border-radius: {scale(8)}px;
                }}
            """)
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(scale(6), scale(6), scale(6), scale(6))
            fl.setSpacing(scale(2))
            l_title = QLabel(title)
            l_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_title.setStyleSheet(f"font-size: {scale(11)}px; font-weight: bold; color: {COLORS['brown_text']}; border: none; background: transparent;")
            l_cnt = QLabel("0")
            l_cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_cnt.setStyleSheet(f"font-size: {scale(14)}px; font-weight: bold; color: {COLORS['brown_text']}; border: none; background: transparent;")
            fl.addWidget(l_title)
            fl.addWidget(l_cnt)
            return frame, l_cnt

        self.card_l1, self.val_l1 = create_badge(tr_ui("course_import.card_level_1", "⚡ Quickstarter"), "rgba(255, 235, 150, 0.55)", "#f1c40f")
        self.card_l2, self.val_l2 = create_badge(tr_ui("course_import.card_level_2", "📚 Tiefe Theorie"), "rgba(174, 214, 241, 0.55)", "#3498db")
        self.card_mot, self.val_mot = create_badge(tr_ui("course_import.card_motives", "💡 Motive"), "rgba(254, 249, 231, 0.65)", "#e67e22")
        self.card_tac, self.val_tac = create_badge(tr_ui("course_import.card_tactics", "🧩 Puzzles"), "rgba(212, 239, 223, 0.55)", "#2ecc71")
        self.card_mod, self.val_mod = create_badge(tr_ui("course_import.card_model", "🏆 Musterpartien"), "rgba(235, 222, 240, 0.55)", "#9b59b6")
        self.card_intro, self.val_intro = create_badge(tr_ui("course_import.card_intro", "📖 Einleitungen"), "rgba(230, 230, 230, 0.55)", "#95a5a6")

        cards_layout.addWidget(self.card_l1)
        cards_layout.addWidget(self.card_l2)
        cards_layout.addWidget(self.card_mot)
        cards_layout.addWidget(self.card_tac)
        cards_layout.addWidget(self.card_mod)
        cards_layout.addWidget(self.card_intro)
        bottom_layout.addWidget(self.cards_frame)

        # 4. Details / Customization Section (Collapsible Tree View for Chapters & Lines)
        self.details_bar_widget = QWidget()
        details_bar = QHBoxLayout(self.details_bar_widget)
        details_bar.setContentsMargins(0, 0, 0, 0)
        details_bar.setSpacing(scale(8))

        self.btn_toggle_details = QPushButton()
        self._update_toggle_button_text(0, expanded=False)
        self.btn_toggle_details.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_details.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {COLORS['burnt_orange']};
                font-weight: bold;
                font-size: {scale(12)}px;
                text-align: left;
                padding: {scale(2)}px 0;
            }}
            QPushButton:hover {{
                text-decoration: underline;
            }}
        """)
        self.btn_toggle_details.clicked.connect(self.toggle_details_tree)
        details_bar.addWidget(self.btn_toggle_details)

        details_bar.addStretch()

        self.btn_expand_all = QPushButton(tr_ui("course_import.btn_expand_all", "📂 Alle aufklappen"))
        self.btn_expand_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand_all.setFixedHeight(scale(24))
        self.btn_expand_all.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.65);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(4)}px;
                padding: 0 {scale(8)}px;
                font-size: {scale(11)}px;
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.95);
            }}
        """)
        self.btn_expand_all.clicked.connect(lambda: self.tree_details.expandAll())
        self.btn_expand_all.setVisible(False)
        details_bar.addWidget(self.btn_expand_all)

        self.btn_collapse_all = QPushButton(tr_ui("course_import.btn_collapse_all", "📁 Alle zuklappen"))
        self.btn_collapse_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse_all.setFixedHeight(scale(24))
        self.btn_collapse_all.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.65);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(4)}px;
                padding: 0 {scale(8)}px;
                font-size: {scale(11)}px;
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.95);
            }}
        """)
        self.btn_collapse_all.clicked.connect(lambda: self.tree_details.collapseAll())
        self.btn_collapse_all.setVisible(False)
        details_bar.addWidget(self.btn_collapse_all)

        bottom_layout.addWidget(self.details_bar_widget)

        self.tree_details = QTreeWidget()
        self.tree_details.setColumnCount(3)
        self.tree_details.setHeaderLabels([
            tr_ui("course_import.col_chapter_tree", "Kapitel & Linien"),
            tr_ui("course_import.col_details", "Details / Info"),
            tr_ui("course_import.col_target", "Ziel-Zuweisung")
        ])
        self.tree_details.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree_details.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_details.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree_details.setColumnWidth(2, scale(230))
        self.tree_details.setUniformRowHeights(True)
        self.tree_details.itemClicked.connect(self.on_tree_item_clicked)
        self.tree_details.itemExpanded.connect(self.on_tree_item_expanded)
        self.tree_details.setAlternatingRowColors(True)
        self.tree_details.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree_details.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree_details.setIndentation(scale(16))
        self.tree_details.setStyleSheet(f"""
            QTreeWidget {{
                background-color: rgba(255, 255, 255, 0.7);
                alternate-background-color: rgba(245, 243, 238, 0.7);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
                outline: none;
            }}
            QTreeWidget::item {{
                border: none;
                padding: {scale(4)}px {scale(4)}px;
            }}
            QTreeWidget::item:hover {{
                background-color: transparent;
            }}
            QTreeWidget::item:selected {{
                background-color: transparent;
                color: {COLORS['brown_text']};
            }}
            QHeaderView::section {{
                background-color: rgba(255, 255, 255, 0.9);
                border: none;
                border-bottom: 1px solid {COLORS['glass_border']};
                font-weight: bold;
                padding: {scale(6)}px {scale(10)}px;
                color: {COLORS['brown_text']};
            }}
        """)
        self.tree_details.setVisible(False)
        bottom_layout.addWidget(self.tree_details, 1)

        self.lbl_details_hint = QLabel(tr_ui("course_import.embedded_hint", "ℹ️ 🧩 = Kapitel enthält eingebettete Taktikaufgaben, die beim Import automatisch in Tactics/Tactics.pgn extrahiert werden."))
        self.lbl_details_hint.setStyleSheet(f"font-size: {scale(11)}px; color: #666; font-style: italic; border: none; background: transparent; padding-top: {scale(2)}px;")
        self.lbl_details_hint.setVisible(False)
        bottom_layout.addWidget(self.lbl_details_hint)

        self.bottom_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        bottom_layout.addItem(self.bottom_spacer)

        main_layout.addWidget(self.bottom_container, 1)

        # 5. Progress & Status
        self.progress_container = QWidget()
        p_layout = QVBoxLayout(self.progress_container)
        p_layout.setContentsMargins(0, 0, 0, 0)
        p_layout.setSpacing(scale(4))

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"font-size: {scale(12)}px; font-weight: bold; color: {COLORS['burnt_orange']};")
        p_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(scale(16))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(255, 255, 255, 0.5);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                text-align: center;
                font-size: {scale(10)}px;
                font-weight: bold;
                color: {COLORS['brown_text']};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['burnt_orange']};
                border-radius: {scale(7)}px;
            }}
        """)
        p_layout.addWidget(self.progress_bar)
        self.progress_container.setVisible(False)
        main_layout.addWidget(self.progress_container)

        # 6. Action Buttons Footer
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(scale(12))

        self.btn_cancel = QPushButton(tr_ui("course_import.btn_cancel", "Abbrechen"))
        self.btn_cancel.setFixedHeight(scale(42))
        self.btn_cancel.setFixedWidth(scale(130))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                color: {COLORS['brown_text']};
                font-size: {scale(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.8);
            }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btns_layout.addWidget(self.btn_cancel)

        btns_layout.addStretch()

        self.btn_import = QPushButton(tr_ui("course_import.btn_import", "🚀 Kurs importieren"))
        self.btn_import.setFixedHeight(scale(42))
        self.btn_import.setMinimumWidth(scale(200))
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(8)}px;
                font-size: {scale(14)}px;
                font-weight: bold;
                padding: 0 {scale(20)}px;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
            QPushButton:disabled {{
                background-color: #bdc3c7;
            }}
        """)
        self.btn_import.setEnabled(False)
        self.btn_import.setVisible(False)
        self.btn_import.clicked.connect(self.on_start_import)
        btns_layout.addWidget(self.btn_import)

        main_layout.addLayout(btns_layout)

        # Initially hide the bottom section until a PGN course is selected
        self.bottom_container.setVisible(False)

    def on_browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr_ui("course_import.btn_select_file", "PGN-Dateien auswählen (Mehrfachauswahl möglich)"),
            "",
            tr_ui("creator.dlg_select_pgn_file_filter", "PGN-Dateien (*.pgn)")
        )
        if paths:
            self.load_files(paths)

    def load_files(self, paths: List[str]):
        self.selected_paths = [p for p in paths if os.path.exists(p)]
        if not self.selected_paths:
            return

        # Display file info in QLineEdit
        if len(self.selected_paths) == 1:
            self.file_input.setText(self.selected_paths[0])
            self.file_input.setToolTip(self.selected_paths[0])
        else:
            base_names = [os.path.basename(p) for p in self.selected_paths]
            self.file_input.setText(f"{len(self.selected_paths)} Dateien: {', '.join(base_names)}")
            self.file_input.setToolTip("\n".join(self.selected_paths))

        self.file_input.setCursorPosition(0)

        try:
            res = analyze_course_pgns(self.selected_paths)
            self.analysis_result = res
            self.custom_chapter_targets = {c.name: c.target_type for c in res.chapters}
            self.custom_game_targets.clear()

            # Pre-fill inputs
            self.name_input.setText(res.suggested_repo_name)
            self.name_input.setCursorPosition(0)
            self.name_input.setToolTip(res.suggested_repo_name)
            idx = self.color_combo.findData(res.suggested_color)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)

            if hasattr(res, 'suggested_elo') and res.suggested_elo:
                idx_elo = self.elo_combo.findData(res.suggested_elo)
                if idx_elo >= 0:
                    self.elo_combo.setCurrentIndex(idx_elo)

            # Cover image status
            if res.cover_image_path:
                cover_name = os.path.basename(res.cover_image_path)
                self.lbl_cover_status.setText(f"🖼️ {tr_ui('course_import.cover_found', 'Gefunden: {name}', name=cover_name)}")
                self.lbl_cover_status.setStyleSheet(f"font-size: {scale(11)}px; color: #27ae60; font-weight: bold; border: none; background: transparent;")
            else:
                self.lbl_cover_status.setText(f"ℹ️ {tr_ui('course_import.cover_none', 'Kein Cover im Kursordner')}")
                self.lbl_cover_status.setStyleSheet(f"font-size: {scale(11)}px; color: #7f8c8d; border: none; background: transparent;")

            self.update_cards()
            self.populate_details_tree()

            self._details_expanded = False
            # Reveal bottom section, enable import, and adjust window
            self.bottom_container.setVisible(True)
            self.btn_import.setVisible(True)
            self.btn_import.setEnabled(True)
            self.lbl_file_hint.setVisible(False)
            self.lbl_sub.setText(
                tr_ui(
                    "course_import.subtitle",
                    "Verwandelt Kurs-PGNs vollautomatisch in strukturierte Repertoires mit <b>Quickstarter</b>, <b>Tiefe Theorie</b> und <b>Puzzles</b>."
                )
            )
            self.bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
            self.setMinimumSize(scale(800), scale(640))
            self.resize(scale(880), scale(720))

        except Exception as e:
            QMessageBox.critical(self, tr_ui("creator.dlg_import_error_title", "Fehler"), f"Fehler beim Analysieren der PGN-Datei:\n{e}")

    def _update_toggle_button_text(self, count: int = 0, expanded: bool = False):
        if expanded:
            self.btn_toggle_details.setText(tr_ui("course_import.details_collapse", "🔼 Kapitel-Details einklappen"))
        else:
            raw_text = tr_ui("course_import.details_expand", "🔍 Kapitel & Linien prüfen und anpassen ({count} Kapitel)", count=count)
            # Escape '&' to '&&' to fix Qt mnemonic accelerator bug on Windows (which renders '&' as an underscore like '_Linien')
            safe_text = raw_text.replace("&", "&&") if "&&" not in raw_text else raw_text
            self.btn_toggle_details.setText(safe_text)

    def update_cards(self):
        if not self.analysis_result:
            return
        
        counts = {
            CATEGORY_LEVEL_1: 0,
            CATEGORY_LEVEL_2: 0,
            CATEGORY_MOTIVES: 0,
            CATEGORY_TACTICS: 0,
            CATEGORY_MODEL: 0,
            CATEGORY_INTRO: 0,
            CATEGORY_IGNORE: 0,
        }

        for c in self.analysis_result.chapters:
            ch_target = self.custom_chapter_targets.get(c.name, c.target_type)
            for g in c.games:
                if g.game_id in self.custom_game_targets:
                    effective = self.custom_game_targets[g.game_id]
                else:
                    if ch_target not in (CATEGORY_TACTICS, CATEGORY_MODEL, CATEGORY_INTRO, CATEGORY_IGNORE, CATEGORY_MOTIVES):
                        if g.is_puzzle:
                            effective = CATEGORY_TACTICS
                        elif g.is_model:
                            effective = CATEGORY_MODEL
                        elif g.is_intro:
                            effective = CATEGORY_INTRO
                        else:
                            effective = ch_target
                    else:
                        effective = ch_target
                counts[effective] = counts.get(effective, 0) + 1

        def fmt_games(c):
            if c == 1:
                return tr_ui("course_import.games_one", "1 Partie")
            return tr_ui("course_import.games_multi", "{count} Partien", count=c)

        def fmt_puzzles(c):
            if c == 1:
                return tr_ui("course_import.puzzles_one", "1 Puzzle")
            return tr_ui("course_import.puzzles_multi", "{count} Puzzles", count=c)

        self.val_l1.setText(fmt_games(counts.get(CATEGORY_LEVEL_1, 0)))
        self.val_l2.setText(fmt_games(counts.get(CATEGORY_LEVEL_2, 0)))
        self.val_mot.setText(fmt_games(counts.get(CATEGORY_MOTIVES, 0)))
        self.val_tac.setText(fmt_puzzles(counts.get(CATEGORY_TACTICS, 0)))
        self.val_mod.setText(fmt_games(counts.get(CATEGORY_MODEL, 0)))
        self.val_intro.setText(fmt_games(counts.get(CATEGORY_INTRO, 0)))

    def populate_details_tree(self):
        if not self.analysis_result:
            return

        chapters = self.analysis_result.chapters
        self._update_toggle_button_text(len(chapters), expanded=self.tree_details.isVisible())
        self.tree_details.clear()
        self.chapter_combos.clear()
        self.game_combos.clear()

        target_options = [
            (CATEGORY_LEVEL_1, tr_ui("course_import.target_level_1", "⚡ Level 1 (Quickstarter)")),
            (CATEGORY_LEVEL_2, tr_ui("course_import.target_level_2", "📚 Level 2 (Tiefe Theorie)")),
            (CATEGORY_MOTIVES, tr_ui("course_import.target_motives", "💡 Typische Motive (Typical Motives.pgn)")),
            (CATEGORY_TACTICS, tr_ui("course_import.target_tactics", "🧩 Taktik (Tactics.pgn)")),
            (CATEGORY_MODEL, tr_ui("course_import.target_model", "🏆 Musterpartie (Model Games.pgn)")),
            (CATEGORY_INTRO, tr_ui("course_import.target_intro", "📖 Einleitung (Introductions from pgn import.pgn)")),
            (CATEGORY_IGNORE, tr_ui("course_import.target_ignore", "🚫 Ignorieren (Überspringen)")),
        ]

        combo_style = f"""
            QComboBox {{
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(0, 0, 0, 0.15);
                border-radius: {scale(6)}px;
                padding: 0 {scale(24)}px 0 {scale(8)}px;
                font-size: {scale(11)}px;
                color: {COLORS['brown_text']};
            }}
            QComboBox:hover {{
                border: 1.5px solid {COLORS['burnt_orange']};
            }}
            QComboBox:focus {{
                border: 1.5px solid {COLORS['burnt_orange']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {scale(20)}px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
            }}
            QComboBox::down-arrow {{
                image: url("{get_chevron_icon_path()}");
                width: {scale(10)}px;
                height: {scale(10)}px;
                margin-right: {scale(6)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['beige']};
                color: {COLORS['brown_text']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(6)}px;
                selection-background-color: rgba(211, 84, 0, 0.15);
                selection-color: {COLORS['burnt_orange']};
                padding: {scale(2)}px;
                outline: none;
            }}
        """

        self.chapter_items.clear()
        self.game_to_chapter.clear()

        for ch in chapters:
            # 1. Top-level Chapter Item
            ch_item = QTreeWidgetItem(self.tree_details)
            ch_item.setText(0, ch.name)
            font = ch_item.font(0)
            font.setBold(True)
            ch_item.setFont(0, font)
            ch_item.setToolTip(0, "\n".join(ch.sample_titles) if ch.sample_titles else ch.name)
            ch_item.setSizeHint(0, QSize(scale(200), scale(36)))
            ch_item.setSizeHint(1, QSize(scale(220), scale(36)))
            ch_item.setSizeHint(2, QSize(scale(230), scale(36)))

            self.chapter_items[ch.name] = ch_item

            target = self.custom_chapter_targets.get(ch.name, ch.target_type)

            # Column 1 container widget: label + [ 🎨 Gemischt ] badge + [ 🔍 Linien anpassen ] button
            col1_widget = QWidget()
            col1_layout = QHBoxLayout(col1_widget)
            col1_layout.setContentsMargins(scale(4), 0, scale(4), 0)
            col1_layout.setSpacing(scale(8))

            lbl_cnt = QLabel("")
            lbl_cnt.setStyleSheet(f"font-size: {scale(11)}px; color: {COLORS['brown_text']}; border: none; background: transparent;")
            col1_layout.addWidget(lbl_cnt)

            lbl_mixed = QLabel("")
            lbl_mixed.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba(254, 249, 231, 0.95);
                    border: 1px solid #f39c12;
                    border-radius: {scale(4)}px;
                    padding: 0 {scale(6)}px;
                    font-size: {scale(11)}px;
                    font-weight: bold;
                    color: #d35400;
                }}
            """)
            lbl_mixed.setVisible(False)
            col1_layout.addWidget(lbl_mixed)

            btn_edit = QPushButton(tr_ui("course_import.btn_edit_lines", "🔍 Linien anpassen"))
            btn_edit.setFixedHeight(scale(24))
            btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_edit.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.85);
                    border: 1px solid {COLORS['glass_border']};
                    border-radius: {scale(4)}px;
                    padding: 0 {scale(8)}px;
                    font-size: {scale(11)}px;
                    font-weight: bold;
                    color: {COLORS['burnt_orange']};
                }}
                QPushButton:hover {{
                    background-color: {COLORS['burnt_orange']};
                    color: white;
                }}
            """)
            btn_edit.clicked.connect(lambda _, c=ch: self.open_chapter_lines_dialog(c))
            col1_layout.addWidget(btn_edit)
            col1_layout.addStretch()

            ch_item._lbl_cnt = lbl_cnt
            ch_item._lbl_mixed = lbl_mixed

            self.tree_details.setItemWidget(ch_item, 1, col1_widget)
            self._update_chapter_row_info(ch, ch_item)

            # Chapter ComboBox (Column 2)
            ch_combo = NoWheelComboBox()
            ch_combo.setFixedHeight(scale(28))
            ch_combo.setStyleSheet(combo_style)
            ch_combo.blockSignals(True)
            for cat_id, cat_label in target_options:
                ch_combo.addItem(cat_label, cat_id)
            idx = ch_combo.findData(target)
            if idx >= 0:
                ch_combo.setCurrentIndex(idx)
            ch_combo.blockSignals(False)

            ch_combo.currentIndexChanged.connect(
                lambda _, c=ch_combo, ch_obj=ch, item=ch_item: self.on_chapter_target_changed(ch_obj.name, c.currentData(), ch_obj, item)
            )
            self.tree_details.setItemWidget(ch_item, 2, ch_combo)
            self.chapter_combos[ch.name] = ch_combo

            # 2. Child Game Items
            for g in ch.games:
                self.game_to_chapter[g.game_id] = ch

                g_item = QTreeWidgetItem(ch_item)
                g_item.setText(0, f"↳  {g.title}")
                g_font = g_item.font(0)
                g_font.setPointSize(max(9, g_font.pointSize() - 1))
                g_item.setFont(0, g_font)
                g_item.setToolTip(0, f"{g.title}\n{g.chapter_name}")
                g_item.setSizeHint(0, QSize(scale(200), scale(32)))
                g_item.setSizeHint(1, QSize(scale(80), scale(32)))
                g_item.setSizeHint(2, QSize(scale(230), scale(32)))

                # Game Details Badge
                if g.is_puzzle:
                    g_item.setText(1, "🧩 Puzzle")
                elif g.is_model:
                    g_item.setText(1, "🏆 Muster")
                elif g.is_intro:
                    g_item.setText(1, "📖 Einleitung")
                elif g.eco:
                    g_item.setText(1, f"ECO {g.eco}")
                else:
                    g_item.setText(1, tr_ui("course_import.line_badge", "Linie"))
                g_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)

                # Game ComboBox
                g_combo = NoWheelComboBox()
                g_combo.setFixedHeight(scale(26))
                g_combo.setStyleSheet(combo_style)
                g_combo.blockSignals(True)
                for cat_id, cat_label in target_options:
                    g_combo.addItem(cat_label, cat_id)
                
                # Determine initial game target
                curr_g_target = self.custom_game_targets.get(g.game_id, g.target_type)
                g_idx = g_combo.findData(curr_g_target)
                if g_idx >= 0:
                    g_combo.setCurrentIndex(g_idx)
                g_combo.blockSignals(False)

                g_combo.currentIndexChanged.connect(
                    lambda _, c=g_combo, gid=g.game_id: self.on_game_target_changed(gid, c.currentData())
                )
                self.tree_details.setItemWidget(g_item, 2, g_combo)
                self.game_combos[g.game_id] = g_combo

    def _get_chapter_category_breakdown(self, ch: CourseChapterInfo) -> Dict[str, int]:
        ch_target = self.custom_chapter_targets.get(ch.name, ch.target_type)
        breakdown: Dict[str, int] = {}
        for g in ch.games:
            if g.game_id in self.custom_game_targets:
                eff = self.custom_game_targets[g.game_id]
            else:
                if ch_target not in (CATEGORY_TACTICS, CATEGORY_MODEL, CATEGORY_INTRO, CATEGORY_IGNORE, CATEGORY_MOTIVES):
                    if g.is_puzzle:
                        eff = CATEGORY_TACTICS
                    elif g.is_model:
                        eff = CATEGORY_MODEL
                    elif g.is_intro:
                        eff = CATEGORY_INTRO
                    else:
                        eff = ch_target
                else:
                    eff = ch_target
            breakdown[eff] = breakdown.get(eff, 0) + 1
        return breakdown

    def _update_chapter_row_info(self, ch: CourseChapterInfo, ch_item: QTreeWidgetItem):
        breakdown = self._get_chapter_category_breakdown(ch)
        total = len(ch.games)
        txt_cnt = tr_ui("course_import.games_one", "1 Partie") if total == 1 else tr_ui("course_import.games_multi", "{count} Partien", count=total)

        lbl_cnt = getattr(ch_item, "_lbl_cnt", None)
        lbl_mixed = getattr(ch_item, "_lbl_mixed", None)

        if lbl_cnt:
            lbl_cnt.setText(txt_cnt)

        # Check if multiple categories exist in this chapter
        is_mixed = len(breakdown) > 1
        if is_mixed:
            order_map = {
                CATEGORY_LEVEL_1: 0,
                CATEGORY_LEVEL_2: 1,
                CATEGORY_MOTIVES: 2,
                CATEGORY_TACTICS: 3,
                CATEGORY_MODEL: 4,
                CATEGORY_INTRO: 5,
                CATEGORY_IGNORE: 6
            }
            sorted_cats = sorted(breakdown.keys(), key=lambda c: order_map.get(c, 99))
            cat_labels = []
            tooltip_lines = [
                tr_ui("course_import.mixed_breakdown_title", "Dieses Kapitel enthält verschiedene Kategorien:"),
                ""
            ]
            for cat in sorted_cats:
                count = breakdown[cat]
                icon, name = CATEGORY_BADGE_INFO.get(cat, ("", cat))
                cat_labels.append(f"{icon} {count}")
                tooltip_lines.append(f"• {count}× {icon} {name}")
            tooltip_lines.append("")
            tooltip_lines.append(tr_ui("course_import.mixed_breakdown_hint", "Klicke auf 'Linien anpassen', um die Zuweisungen zu bearbeiten."))

            if lbl_mixed:
                lbl_mixed.setText(f"🎨 {' · '.join(cat_labels)}")
                lbl_mixed.setToolTip("\n".join(tooltip_lines))
                lbl_mixed.setVisible(True)
        else:
            if lbl_mixed:
                lbl_mixed.setVisible(False)

    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        # Single click on chapter row (column 0) toggles expand/collapse smoothly
        if item.parent() is None and column == 0:
            item.setExpanded(not item.isExpanded())

    def on_tree_item_expanded(self, item: QTreeWidgetItem):
        # Ensure all child widgets are unhidden and geometries refreshed
        for i in range(item.childCount()):
            child = item.child(i)
            w = self.tree_details.itemWidget(child, 2)
            if w:
                w.show()
                w.update()
        self.tree_details.updateGeometries()

    def open_chapter_lines_dialog(self, ch: CourseChapterInfo):
        ch_target = self.custom_chapter_targets.get(ch.name, ch.target_type)
        dlg = ChapterLinesDialog(ch, ch_target, self.custom_game_targets, parent=self)
        if dlg.exec():
            for gid, target in dlg.result_targets.items():
                self.custom_game_targets[gid] = target
                g_combo = self.game_combos.get(gid)
                if g_combo:
                    g_combo.blockSignals(True)
                    idx = g_combo.findData(target)
                    if idx >= 0:
                        g_combo.setCurrentIndex(idx)
                    g_combo.blockSignals(False)
            ch_item = self.chapter_items.get(ch.name)
            if ch_item:
                self._update_chapter_row_info(ch, ch_item)
            self.update_cards()

    def on_chapter_target_changed(self, chapter_name: str, new_target: str, ch_obj: CourseChapterInfo, ch_item: QTreeWidgetItem):
        self.custom_chapter_targets[chapter_name] = new_target
        self._update_chapter_row_info(ch_obj, ch_item)

        # Update non-overridden child games
        for g in ch_obj.games:
            if g.game_id not in self.custom_game_targets:
                if new_target not in (CATEGORY_TACTICS, CATEGORY_MODEL, CATEGORY_INTRO, CATEGORY_IGNORE, CATEGORY_MOTIVES):
                    if g.is_puzzle:
                        g_eff = CATEGORY_TACTICS
                    elif g.is_model:
                        g_eff = CATEGORY_MODEL
                    else:
                        g_eff = new_target
                else:
                    g_eff = new_target
                
                g_combo = self.game_combos.get(g.game_id)
                if g_combo:
                    g_combo.blockSignals(True)
                    idx = g_combo.findData(g_eff)
                    if idx >= 0:
                        g_combo.setCurrentIndex(idx)
                    g_combo.blockSignals(False)

        self._update_chapter_row_info(ch_obj, ch_item)
        self.update_cards()

    def on_game_target_changed(self, game_id: int, new_target: str):
        self.custom_game_targets[game_id] = new_target
        ch = self.game_to_chapter.get(game_id)
        if ch:
            ch_item = self.chapter_items.get(ch.name)
            if ch_item:
                self._update_chapter_row_info(ch, ch_item)
        self.update_cards()

    def toggle_details_tree(self):
        self._details_expanded = not getattr(self, "_details_expanded", False)
        visible = self._details_expanded
        self.tree_details.setVisible(visible)
        self.btn_expand_all.setVisible(visible)
        self.btn_collapse_all.setVisible(visible)
        self.lbl_details_hint.setVisible(visible)
        count = len(self.analysis_result.chapters) if self.analysis_result else 0
        if visible:
            self.bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            self.tree_details.setMinimumHeight(scale(220))
            if self.height() < scale(680):
                self.resize(self.width(), scale(720))
            self._update_toggle_button_text(count, expanded=True)
        else:
            self.bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
            self.tree_details.setMinimumHeight(0)
            self._update_toggle_button_text(count, expanded=False)
        self.bottom_container.layout().invalidate()
        self.update()
        if self.parent():
            self.parent().update()

    def on_start_import(self):
        if not self.analysis_result or not self.selected_paths:
            return

        repo_name = self.name_input.text().strip()
        if not repo_name:
            QMessageBox.warning(self, tr_ui("creator.new_repo_invalid_name_title", "Ungültiger Name"), tr_ui("creator.new_repo_invalid_name_empty", "Der Repertoire-Name darf nicht leer sein."))
            return

        bad = [c for c in repo_name if c in self._FORBIDDEN_CHARS]
        if bad:
            bad_str = "  " + "  ".join(sorted(set(bad)))
            QMessageBox.warning(self, tr_ui("creator.new_repo_invalid_name_title", "Ungültiger Name"), f"Der Name enthält ungültige Zeichen:\n\n{bad_str}")
            return

        # Prepare Plan with multiple PGN paths and game overrides
        plan = CourseImportPlan(
            pgn_paths=self.selected_paths,
            repo_name=repo_name,
            side=self.color_combo.currentData() or "w",
            chapter_targets=self.custom_chapter_targets,
            cover_image_path=self.analysis_result.cover_image_path,
            target_lang=self.lang_combo.currentData() or "de",
            game_targets=self.custom_game_targets,
            elo=self.elo_combo.currentData() or "high"
        )

        # Disable inputs & show progress
        self.btn_browse.setEnabled(False)
        self.name_input.setEnabled(False)
        self.color_combo.setEnabled(False)
        self.elo_combo.setEnabled(False)
        self.lang_combo.setEnabled(False)
        self.btn_import.setEnabled(False)
        self.btn_cancel.setEnabled(False)

        self.progress_container.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(tr_ui("course_import.status_preparing", "Vorbereitung..."))

        # Launch Thread
        self.import_thread = CourseImportThread(plan)
        self.import_thread.progress_signal.connect(self.on_import_progress)
        self.import_thread.finished_signal.connect(self.on_import_finished)
        self.import_thread.start()

    def on_import_progress(self, pct: int, text: str):
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(text)

    def on_import_finished(self, success: bool, message: str, result: Optional[CourseImportResult]):
        self.btn_browse.setEnabled(True)
        self.name_input.setEnabled(True)
        self.color_combo.setEnabled(True)
        self.elo_combo.setEnabled(True)
        self.lang_combo.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.progress_container.setVisible(False)

        if success:
            self.imported_repo_name = self.name_input.text().strip()
            QMessageBox.information(self, tr_ui("creator.dlg_success", "Erfolg"), message)
            self.accept()
        else:
            QMessageBox.critical(self, tr_ui("creator.dlg_import_error_title", "Fehler"), message)

    def _install_taskbar_close_filter(self):
        self._taskbar_filter = install_taskbar_close_filter(self, self._cancel_and_cleanup_thread)

    def _uninstall_taskbar_close_filter(self):
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None

    def _cancel_and_cleanup_thread(self):
        if self.import_thread and self.import_thread.isRunning():
            try:
                self.import_thread.requestInterruption()
                if not self.import_thread.wait(300):
                    self.import_thread.terminate()
            except Exception:
                pass

    def _handle_taskbar_close(self):
        self._uninstall_taskbar_close_filter()
        self._cancel_and_cleanup_thread()
        self.reject()

    def closeEvent(self, event):
        self._cancel_and_cleanup_thread()
        self._uninstall_taskbar_close_filter()
        super().closeEvent(event)

    def reject(self):
        self._cancel_and_cleanup_thread()
        self._uninstall_taskbar_close_filter()
        super().reject()

    def accept(self):
        self._uninstall_taskbar_close_filter()
        super().accept()
