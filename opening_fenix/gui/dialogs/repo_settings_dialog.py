import os
import re
import datetime
import multiprocessing
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QComboBox, QInputDialog, QCheckBox, 
    QGroupBox, QFormLayout, QTextEdit, QHeaderView, QScrollArea, 
    QSlider, QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QProgressBar, QProgressDialog, QListWidget, QListWidgetItem,
    QGridLayout, QTableWidget, QStackedWidget, QPlainTextEdit, QWidget, QFrame, QApplication,
    QTableWidgetItem, QFileDialog, QAbstractItemView, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QEvent, QThread
from PyQt6.QtGui import QFont, QIcon
from PyQt6 import sip
from sqlalchemy import func, text
import stat

class NoWheelComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._can_wheel = False
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.timeout.connect(self._enable_wheel)

    def enterEvent(self, event):
        self._wheel_timer.start(200)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._wheel_timer.stop()
        self._can_wheel = False
        super().leaveEvent(event)

    def _enable_wheel(self):
        self._can_wheel = True

    def wheelEvent(self, event):
        if self._can_wheel:
            super().wheelEvent(event)
        else:
            event.ignore()

class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._can_wheel = False
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.timeout.connect(self._enable_wheel)

    def enterEvent(self, event):
        self._wheel_timer.start(200)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._wheel_timer.stop()
        self._can_wheel = False
        super().leaveEvent(event)

    def _enable_wheel(self):
        self._can_wheel = True

    def wheelEvent(self, event):
        if self._can_wheel:
            super().wheelEvent(event)
        else:
            event.ignore()

from opening_fenix.core.models import (
    Position, Move, RepertoireMove, RepertoireLevel
)
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir, localize_san, ELO_DISPLAY_MAP, get_elo_display, get_elo_internal
from opening_fenix.core.services.maintenance_service import list_all_repertoires
from opening_fenix.core.data_tools import get_base_path, get_user_dir
from opening_fenix.core.threads import AnalysisThread, LichessImportThread, PGNImportThread, MaintenanceThread, RepertoireStatsWorker
from opening_fenix.gui.widgets.board_widget import THEMES
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
from opening_fenix.gui.styles import (
    get_bw_glass_style, COLORS, set_consistent_icon
)
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui

class AutoShrinkWrapLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.base_font = None

    def setFont(self, font):
        super().setFont(font)
        if not hasattr(self, "_adjusting_font") or not self._adjusting_font:
            self.base_font = QFont(font)
            self.adjust_font_size()

    def setText(self, text):
        super().setText(text)
        self.adjust_font_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_font_size()

    def adjust_font_size(self):
        text = self.text()
        if not text:
            return
            
        if not self.base_font:
            self.base_font = QFont(self.font())
            
        margins = self.contentsMargins()
        target_width = self.width() - margins.left() - margins.right()
        if target_width <= 0:
            return
            
        words = text.split()
        if not words:
            return
            
        from PyQt6.QtGui import QFontMetrics
        
        current_font = QFont(self.base_font)
        font_size = current_font.pointSize()
        if font_size <= 0:
            font_size = current_font.pixelSize()
            is_pixel = True
        else:
            is_pixel = False
            
        min_size = 7
        
        self._adjusting_font = True
        try:
            while font_size > min_size:
                fm = QFontMetrics(current_font)
                word_too_long = False
                for word in words:
                    clean_word = word.rstrip(":")
                    if fm.horizontalAdvance(clean_word) > target_width:
                        word_too_long = True
                        break
                
                if not word_too_long:
                    break
                    
                font_size -= 1
                if is_pixel:
                    current_font.setPixelSize(font_size)
                else:
                    current_font.setPointSize(font_size)
                    
            super().setFont(current_font)
        finally:
            self._adjusting_font = False


class SingleRepoStatsWorker(QThread):
    stats_ready = pyqtSignal(dict)
    
    def __init__(self, backend):
        super().__init__()
        self.repo_name = backend.active_repo_name
        self.is_test = getattr(backend, "is_test", False)
        
    def run(self):
        temp_backend = None
        try:
            from opening_fenix.creator.creator_window import CreatorBackend
            if self.isInterruptionRequested():
                return
            temp_backend = CreatorBackend(is_test=self.is_test)
            if self.isInterruptionRequested():
                return
            if self.repo_name:
                temp_backend.load_repertoire(self.repo_name)
                if self.isInterruptionRequested():
                    return
                info = temp_backend.get_repertoire_info(fast_only=False)
                if self.isInterruptionRequested():
                    return
                self.stats_ready.emit(info)
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Error in SingleRepoStatsWorker: {e}")
        finally:
            if temp_backend:
                try:
                    temp_backend.close()
                except Exception:
                    pass


class DiagnosticDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("repo_settings.diag_title", "Datenbank-Diagnose"))
        self.setMinimumWidth(scale(500))
        self.backend = backend
        self.setStyleSheet(get_bw_glass_style())
        self.init_ui()
        self.run_diagnostic()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(15))
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        self.lbl_info = QLabel(tr_ui("repo_settings.diag_checking", "Überprüfe Repertoire-Struktur..."))
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(self.lbl_info)
        
        self.txt_results = QTextEdit()
        self.txt_results.setReadOnly(True)
        self.txt_results.setStyleSheet("background-color: white; border-radius: 8px; border: 1px solid rgba(0,0,0,0.1); padding: 10px;")
        layout.addWidget(self.txt_results)
        
        h_btn = QHBoxLayout()
        self.btn_repair = QPushButton(tr_ui("repo_settings.btn_repair_issues", "🔧 Probleme beheben"))
        self.btn_repair.setProperty("class", "Primary")
        self.btn_repair.clicked.connect(self.repair)
        self.btn_repair.setEnabled(False)
        self.btn_repair.setVisible(False)
        
        btn_close = QPushButton(tr_ui("repo_settings.btn_close", "Schließen"))
        btn_close.clicked.connect(self.accept)
        
        h_btn.addStretch()
        h_btn.addWidget(btn_close)
        h_btn.addWidget(self.btn_repair)
        layout.addLayout(h_btn)

    def run_diagnostic(self):
        self.issues = self.backend.run_diagnostic()
        msg = tr_ui("repo_settings.diag_result_title", "<h3 style='margin-bottom: 10px;'>Diagnose-Ergebnis:</h3>")
        
        has_issues = False
        
        # Schema
        if self.issues['schema']:
            msg += tr_ui("repo_settings.diag_schema_outdated", "<p style='color: #e74c3c;'><b>⚠️ Veraltetes Datenbankschema</b><br>Fehlende Spalten: {cols}</p>", cols=', '.join(self.issues['schema']))
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_schema_ok", "<p style='color: #27ae60;'><b>✅ Datenbankschema</b><br>Das Schema ist aktuell.</p>")
            
        # Gaps
        if self.issues['gaps'] > 0:
            msg += tr_ui("repo_settings.diag_gaps_warn", "<p style='color: #e74c3c;'><b>⚠️ Zug-Lücken</b><br>{count} fehlende Repertoire-Links gefunden.</p>", count=self.issues['gaps'])
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_gaps_ok", "<p style='color: #27ae60;'><b>✅ Zug-Kette</b><br>Keine Lücken gefunden.</p>")
            
        # Duplicates
        if self.issues['duplicates'] > 0:
            msg += tr_ui("repo_settings.diag_dups_warn", "<p style='color: #e74c3c;'><b>⚠️ FEN-Duplikate</b><br>{count} doppelte Stellungen gefunden.</p>", count=self.issues['duplicates'])
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_dups_ok", "<p style='color: #27ae60;'><b>✅ Eindeutigkeit</b><br>Keine FEN-Duplikate gefunden.</p>")
            
        # Orphans
        if self.issues.get('orphans', 0) > 0:
            msg += tr_ui("repo_settings.diag_orphans_info", "<p style='color: #f39c12;'><b>ℹ️ Isolierte Stellungen</b><br>{count} Stellungen sind nicht erreichbar.</p>", count=self.issues['orphans'])
        else:
            msg += tr_ui("repo_settings.diag_orphans_ok", "<p style='color: #27ae60;'><b>✅ Erreichbarkeit</b><br>Alle Stellungen sind verknüpft.</p>")

        # Lichess Orphans
        if self.issues.get('orphaned_lichess', 0) > 0:
            msg += tr_ui("repo_settings.diag_orphaned_lichess_warn", "<p style='color: #e67e22;'><b>⚠️ Verwaiste Lichess-Daten</b><br>{count} Cache-Einträge ohne zugehörige Stellung gefunden.</p>", count=self.issues['orphaned_lichess'])
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_orphaned_lichess_ok", "<p style='color: #27ae60;'><b>✅ Lichess-Cache</b><br>Keine verwaisten Daten gefunden.</p>")
            
        self.txt_results.setHtml(msg)
        
        if has_issues:
            self.lbl_info.setText(tr_ui("repo_settings.diag_issues_found", "Probleme identifiziert! 🛠️"))
            self.btn_repair.setEnabled(True)
            self.btn_repair.setVisible(True)
        else:
            self.lbl_info.setText(tr_ui("repo_settings.diag_all_healthy", "Alles gesund! ✨"))
            self.btn_repair.setVisible(False)

    def repair(self):
        self.btn_repair.setEnabled(False)
        self.lbl_info.setText(tr_ui("repo_settings.diag_repairing", "Repariere Datenbank... ⌛"))
        QApplication.processEvents()
        
        self.backend.repair_diagnostic_issues()
        
        self.txt_results.append(tr_ui("repo_settings.diag_repair_done_title", "<br><hr><br><p style='color: #27ae60; font-weight: bold;'>Reparatur erfolgreich abgeschlossen!</p>"))
        self.txt_results.append(tr_ui("repo_settings.diag_repair_done_msg", "<p>Alle identifizierten Löcher wurden gestopft und Duplikate bereinigt.</p>"))
        self.lbl_info.setText(tr_ui("repo_settings.diag_repair_finished", "Reparatur fertig! ✅"))
        if hasattr(self.parent(), 'refresh_info'):
            self.parent().refresh_info()


class DeleteLevelDialog(QDialog):
    """Dialog to select a level to delete and either reassign its moves or delete them if highest level."""
    def __init__(self, levels, default_del_order=None, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("repo_settings.delete_level_dialog_title", "Level löschen"))
        self.setMinimumWidth(scale(460))
        self.setStyleSheet(get_bw_glass_style())
        self.levels = sorted(levels, key=lambda x: x['order'])
        self.default_del_order = default_del_order
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(15))
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        lbl_prompt = QLabel(tr_ui("repo_settings.delete_level_prompt", "Wähle das zu löschende Level und die gewünschte Aktion für die enthaltenen Züge:"))
        lbl_prompt.setWordWrap(True)
        lbl_prompt.setStyleSheet("font-weight: 500; font-size: 13px;")
        layout.addWidget(lbl_prompt)

        form = QFormLayout()
        form.setSpacing(scale(10))

        self.combo_del = NoWheelComboBox()
        for lvl in self.levels:
            self.combo_del.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])

        if self.default_del_order:
            idx = self.combo_del.findData(self.default_del_order)
            if idx >= 0:
                self.combo_del.setCurrentIndex(idx)

        form.addRow(tr_ui("repo_settings.delete_level_select_del", "Zu löschendes Level:"), self.combo_del)

        # Radio Group for Action Mode (Reassign vs Delete Moves)
        self.g_mode = QGroupBox(tr_ui("repo_settings.delete_level_mode_group", "Aktion für enthaltene Züge:"))
        v_mode = QVBoxLayout(self.g_mode)
        v_mode.setSpacing(scale(8))

        self.radio_reassign = QRadioButton(tr_ui("repo_settings.delete_level_mode_reassign", "Züge in ein anderes Level verschieben"))
        self.radio_delete_moves = QRadioButton(tr_ui("repo_settings.delete_level_mode_delete_moves", "Alle Züge in diesem Level unwiderruflich löschen"))
        self.radio_reassign.setChecked(True)

        v_mode.addWidget(self.radio_reassign)
        v_mode.addWidget(self.radio_delete_moves)

        self.combo_target = NoWheelComboBox()
        form.addRow(tr_ui("repo_settings.delete_level_select_target", "Züge neu zuweisen nach:"), self.combo_target)

        layout.addLayout(form)
        layout.addWidget(self.g_mode)

        self.radio_reassign.toggled.connect(self._on_mode_toggled)
        self.radio_delete_moves.toggled.connect(self._on_mode_toggled)
        self.combo_del.currentIndexChanged.connect(self._update_target_combo)
        self._update_target_combo()

        h_btn = QHBoxLayout()
        h_btn.addStretch()

        btn_cancel = QPushButton(tr_ui("login.cancel", "Abbrechen"))
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton(tr_ui("repo_settings.btn_delete_level", "🗑️ Level löschen"))
        btn_ok.setProperty("class", "Danger")
        btn_ok.clicked.connect(self.accept)

        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(btn_ok)
        layout.addLayout(h_btn)

    def _on_mode_toggled(self):
        delete_moves = self.radio_delete_moves.isChecked()
        self.combo_target.setEnabled(not delete_moves)

    def _update_target_combo(self):
        self.combo_target.clear()
        del_order = self.combo_del.currentData()
        max_order = max((lvl['order'] for lvl in self.levels), default=0)
        is_highest = (del_order == max_order)

        # Only allow deleting all moves if it's the highest level
        if is_highest:
            self.g_mode.setVisible(True)
        else:
            self.radio_reassign.setChecked(True)
            self.g_mode.setVisible(False)

        for lvl in self.levels:
            if lvl['order'] != del_order:
                self.combo_target.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])

        self._on_mode_toggled()

    def get_selection(self):
        del_order = self.combo_del.currentData()
        target_order = self.combo_target.currentData()
        max_order = max((lvl['order'] for lvl in self.levels), default=0)
        is_highest = (del_order == max_order)
        delete_moves = is_highest and self.radio_delete_moves.isChecked()
        return del_order, target_order, delete_moves


class MaintenanceRepoWidget(QWidget):
    """Custom row widget for the Centralized Maintenance list."""
    def __init__(self, name, current_elo, parent=None):
        super().__init__(parent)
        self.name = name
        self.setMinimumHeight(scale(45))
        layout = QGridLayout(self)
        layout.setContentsMargins(scale(10), scale(0), scale(10), scale(0))
        layout.setHorizontalSpacing(scale(10))
        
        self.chk = QCheckBox()
        self.chk.setChecked(True)
        layout.addWidget(self.chk, 0, 0)
        
        self.lbl_name = QLabel(name)
        self.lbl_name.setStyleSheet(f"font-weight: 600; font-size: {scale(14)}px; color: {COLORS['dark_accent']};")
        layout.addWidget(self.lbl_name, 0, 1)
        
        lbl_elo_h = QLabel(tr_ui("repo_settings.col_prio_elo", "Prio Elo:"))
        lbl_elo_h.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: {scale(11)}px;")
        lbl_elo_h.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_elo_h, 0, 2)

        self.lbl_elo_val = QLabel(current_elo)
        self.lbl_elo_val.setFixedWidth(scale(70))
        self.lbl_elo_val.setStyleSheet(f"font-weight: bold; color: {COLORS['info_blue']}; font-size: {scale(13)}px; background: rgba(41, 128, 185, 0.05); border-radius: {scale(4)}px; padding: {scale(2)}px;")
        self.lbl_elo_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_elo_val, 0, 3)
        
        self.lbl_status = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        self.lbl_status.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: {scale(11)}px; font-style: italic;")
        self.lbl_status.setFixedWidth(scale(140))
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_status, 0, 4)
        
        layout.setColumnStretch(1, 1)
        
        self._task_states = {"engine": "", "lichess": "", "stats": ""}

    def mousePressEvent(self, event):
        """Toggle checkbox when clicking anywhere on the row."""
        self.chk.setChecked(not self.chk.isChecked())
        super().mousePressEvent(event)

    def update_status(self, task_type, progress, status_text):
        if task_type in self._task_states:
            prefix = task_type[0].upper()
            if progress < 100:
                self._task_states[task_type] = f"{prefix}: {progress}%"
            else:
                self._task_states[task_type] = f"{prefix}: {status_text}"
        
        active_states = [v for k, v in self._task_states.items() if v]
        self.lbl_status.setText(" | ".join(active_states) if active_states else "Bereit")

    def is_checked(self): return self.chk.isChecked()
    def set_checked(self, checked): self.chk.setChecked(checked)
    def get_config(self): return {'name': self.name, 'elo': self.lbl_elo_val.text()}

class RepoSettingsDialog(QDialog):
    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        set_consistent_icon(self)
        self.main_window = parent
        self.setWindowTitle(tr_ui("repo_settings.dialog_title", "Repertoire Einstellungen"))
        self.setMinimumSize(scale(1080), scale(700))
        self.backend = backend
        self.setStyleSheet(get_bw_glass_style())
        
        self.maintenance_loaded = False
        self.stats_loader = None
        self.loading_dots = 0
        self.loading_timer = None

        self.init_ui()
        # Start with fast info (cached/metadata only)
        self.refresh_info(fast_only=True)
        # Immediately start animation and slow fetch
        self.start_loading_animation()
        self.start_slow_stats_fetch()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(scale(220))
        self.sidebar.currentRowChanged.connect(self.display_page)
        
        sidebar_items = [
            (tr_ui("repo_settings.sidebar_gen", "📊 Repertoire-Daten"), tr_ui("repo_settings.sidebar_gen_sub", "Stammdaten und Level")),
            (tr_ui("repo_settings.sidebar_design", "🎨 Design & Audio"), tr_ui("repo_settings.sidebar_design_sub", "Optik und Sound")),
            (tr_ui("repo_settings.sidebar_imex", "📥 Import & Export"), tr_ui("repo_settings.sidebar_imex_sub", "Datentransfer")),
            (tr_ui("repo_settings.sidebar_tools", "🛠️ Repertoire-Werkzeuge"), tr_ui("repo_settings.sidebar_tools_sub", "Wartung & Analyse")),
            (tr_ui("repo_settings.sidebar_maintenance", "🚜 Wartung Center"), tr_ui("repo_settings.sidebar_maintenance_sub", "Stapelverarbeitung"))
        ]
        
        for title, sub in sidebar_items:
            item = QListWidgetItem(title)
            self.sidebar.addItem(item)
            
        main_layout.addWidget(self.sidebar)

        # Content Area
        self.pages = QStackedWidget()
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        
        # Initialize Pages
        self.page_gen = QWidget(); self.init_page_general(self.page_gen)
        self.page_design = QWidget(); self.init_page_design(self.page_design)
        self.page_imex = QWidget(); self.init_page_imex(self.page_imex)
        self.page_tools = QWidget(); self.init_page_tools(self.page_tools)
        self.page_maintenance = QWidget(); self.init_page_maintenance(self.page_maintenance)
        
        for p in [self.page_gen, self.page_design, self.page_imex, self.page_tools, self.page_maintenance]:
            p.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.pages.addWidget(self.page_gen)
        self.pages.addWidget(self.page_design)
        self.pages.addWidget(self.page_imex)
        self.pages.addWidget(self.page_tools)
        self.pages.addWidget(self.page_maintenance)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.pages)
        main_layout.addWidget(scroll, 1)
        
        self.sidebar.setCurrentRow(0)

    def display_page(self, index): 
        self.pages.setCurrentIndex(index)
        if index == 4 and not self.maintenance_loaded:
            self._refresh_maintenance_repo_list()
            self.maintenance_loaded = True

    def init_page_general(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        # 📋 Repertoire Identität (Modern Card-Based Layout)
        g_info = QGroupBox(tr_ui("repo_settings.identity_title", "📋 Repertoire Identität"))
        v_info = QVBoxLayout(g_info)
        v_info.setSpacing(scale(15))
        v_info.setContentsMargins(scale(18), scale(22), scale(18), scale(18))

        # --- 1. Header Card (Title & Rename Button) ---
        card_header = QFrame()
        card_header.setMinimumWidth(0)
        card_header.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['glass_bg']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
            }}
        """)
        h_header = QHBoxLayout(card_header)
        h_header.setContentsMargins(scale(16), scale(12), scale(16), scale(12))
        h_header.setSpacing(scale(15))

        lbl_header_icon = QLabel("🏆")
        lbl_header_icon.setStyleSheet(f"font-size: {scale(22)}px;")
        
        v_name_box = QVBoxLayout()
        v_name_box.setSpacing(scale(2))
        
        lbl_name_sub = QLabel(tr_ui("repo_settings.label_name", "Repertoire Name"))
        lbl_name_sub.setStyleSheet(f"font-size: {scale(11)}px; font-weight: 600; color: {COLORS['text_muted']}; text-transform: uppercase;")
        
        self.l_n = QLabel()
        self.l_n.setStyleSheet(f"font-weight: 900; font-size: {scale(20)}px; color: {COLORS['burnt_orange']};")
        self.l_n.setWordWrap(True)
        self.l_n.setMinimumWidth(0)
        
        v_name_box.addWidget(lbl_name_sub)
        v_name_box.addWidget(self.l_n)

        btn_rename = QPushButton(tr_ui("repo_settings.btn_rename", "✎ Umbenennen"))
        btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rename.setMinimumWidth(scale(110))
        btn_rename.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.85);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                padding: {scale(8)}px {scale(16)}px;
                font-weight: 600;
                font-size: {scale(13)}px;
                color: {COLORS['dark_accent']};
            }}
            QPushButton:hover {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border-color: {COLORS['burnt_orange']};
            }}
        """)
        btn_rename.clicked.connect(self.rename_repertoire)

        h_header.addWidget(lbl_header_icon)
        h_header.addLayout(v_name_box, 1)
        h_header.addWidget(btn_rename, 0, Qt.AlignmentFlag.AlignVCenter)
        
        v_info.addWidget(card_header)

        # --- 2. Metadata Grid (2x2 Badges / Cards) ---
        grid_meta = QGridLayout()
        grid_meta.setSpacing(scale(10))
        grid_meta.setColumnStretch(0, 1)
        grid_meta.setColumnStretch(1, 1)

        def create_mini_card(title_text, widget_or_layout):
            card = QFrame()
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['glass_bg']};
                    border: 1px solid {COLORS['glass_border']};
                    border-radius: {scale(10)}px;
                }}
            """)
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(scale(12), scale(10), scale(12), scale(10))
            c_layout.setSpacing(scale(4))
            
            lbl_title = QLabel(title_text)
            lbl_title.setWordWrap(True)
            lbl_title.setMinimumWidth(0)
            lbl_title.setStyleSheet(f"font-size: {scale(11)}px; font-weight: 600; color: {COLORS['text_muted']};")
            c_layout.addWidget(lbl_title)
            
            if isinstance(widget_or_layout, QWidget):
                c_layout.addWidget(widget_or_layout)
            else:
                c_layout.addLayout(widget_or_layout)
            return card

        # Card A: Prio score ELO
        self.combo_repertoire_elo = NoWheelComboBox()
        self.combo_repertoire_elo.addItems([get_elo_display(k) for k in ELO_DISPLAY_MAP.keys()])
        self.combo_repertoire_elo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_repertoire_elo.setMinimumContentsLength(5)
        self.combo_repertoire_elo.setMinimumWidth(0)
        self.combo_repertoire_elo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_repertoire_elo.currentTextChanged.connect(self.save_repertoire_elo)
        card_elo = create_mini_card(tr_ui("repo_settings.label_prio_elo", "🎯 Prio score ELO"), self.combo_repertoire_elo)

        # Card B: Your Color
        self.combo_repertoire_color = NoWheelComboBox()
        self.combo_repertoire_color.addItem(tr_ui("repo_settings.color_white", "♔ Weiß"), "w")
        self.combo_repertoire_color.addItem(tr_ui("repo_settings.color_black", "♚ Schwarz"), "b")
        self.combo_repertoire_color.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_repertoire_color.setMinimumContentsLength(5)
        self.combo_repertoire_color.setMinimumWidth(0)
        self.combo_repertoire_color.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_repertoire_color.currentTextChanged.connect(self.save_repertoire_color)
        card_color = create_mini_card(tr_ui("repo_settings.label_color", "🎨 Deine Farbe"), self.combo_repertoire_color)

        # Card C: Analysis Status
        self.lbl_ana_status = QLabel("-")
        self.lbl_ana_status.setStyleSheet(f"font-weight: 700; font-size: {scale(13)}px; color: {COLORS['dark_accent']};")
        self.lbl_ana_status.setWordWrap(True)
        self.lbl_ana_status.setMinimumWidth(0)
        card_ana = create_mini_card(tr_ui("repo_settings.label_analysis_status", "🔍 Analyse-Status"), self.lbl_ana_status)

        # Card D: DB Coverage
        self.lbl_db_cov = QLabel("-")
        self.lbl_db_cov.setStyleSheet(f"font-weight: 700; font-size: {scale(13)}px; color: {COLORS['dark_accent']};")
        self.lbl_db_cov.setWordWrap(True)
        self.lbl_db_cov.setMinimumWidth(0)
        card_cov = create_mini_card(tr_ui("repo_settings.label_db_coverage", "📊 Prio. Score Datenbank Elo"), self.lbl_db_cov)

        grid_meta.addWidget(card_elo, 0, 0)
        grid_meta.addWidget(card_color, 0, 1)
        grid_meta.addWidget(card_ana, 1, 0)
        grid_meta.addWidget(card_cov, 1, 1)

        v_info.addLayout(grid_meta)

        # --- 3. Description Section Card ---
        card_desc = QFrame()
        card_desc.setMinimumWidth(0)
        card_desc.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['glass_bg']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
            }}
        """)
        v_desc_layout = QVBoxLayout(card_desc)
        v_desc_layout.setContentsMargins(scale(14), scale(12), scale(14), scale(14))
        v_desc_layout.setSpacing(scale(8))

        lbl_desc_title = QLabel(tr_ui("repo_settings.label_description", "📝 Beschreibung"))
        lbl_desc_title.setStyleSheet(f"font-size: {scale(12)}px; font-weight: 700; color: {COLORS['dark_accent']};")
        
        self.txt_description = QPlainTextEdit()
        self.txt_description.setPlaceholderText(tr_ui("repo_settings.description_placeholder", "Beschreibe dein Repertoire hier..."))
        self.txt_description.setMinimumHeight(scale(100))
        self.txt_description.setMaximumHeight(scale(150))
        self.txt_description.setMinimumWidth(0)
        self.txt_description.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: rgba(255, 255, 255, 0.6);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(10)}px;
                padding: {scale(10)}px;
                font-size: {scale(13)}px;
                color: {COLORS['brown_text']};
                line-height: 1.5;
            }}
            QPlainTextEdit:focus {{
                border: 1.5px solid {COLORS['burnt_orange']};
                background-color: rgba(255, 255, 255, 0.95);
            }}
        """)
        self.txt_description.textChanged.connect(self.save_description)

        v_desc_layout.addWidget(lbl_desc_title)
        v_desc_layout.addWidget(self.txt_description)

        v_info.addWidget(card_desc)

        # --- 4. Cover Image Row ---
        card_cover = QFrame()
        card_cover.setMinimumWidth(0)
        card_cover.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['glass_bg']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
            }}
        """)
        h_cover_layout = QHBoxLayout(card_cover)
        h_cover_layout.setContentsMargins(scale(14), scale(12), scale(14), scale(12))
        h_cover_layout.setSpacing(scale(15))

        lbl_cover_title = QLabel(tr_ui("repo_settings.label_cover_image", "🖼️ Cover-Bild"))
        lbl_cover_title.setMinimumWidth(0)
        lbl_cover_title.setWordWrap(True)
        lbl_cover_title.setStyleSheet(f"font-size: {scale(12)}px; font-weight: 700; color: {COLORS['dark_accent']};")

        self.lbl_cover_preview = QLabel(tr_ui("repo_settings.no_image", "Kein Bild"))
        self.lbl_cover_preview.setStyleSheet("color: #777; font-style: italic; border: 1px dashed #ccc; border-radius: 8px; background-color: rgba(255, 255, 255, 0.5);")
        self.lbl_cover_preview.setFixedSize(scale(64), scale(64))
        self.lbl_cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_cover_preview.setScaledContents(True)

        btn_select_cover = QPushButton(tr_ui("repo_settings.btn_select_image", "Bild wählen..."))
        btn_select_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_select_cover.setMinimumWidth(scale(100))
        btn_select_cover.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.85);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                padding: {scale(8)}px {scale(14)}px;
                font-weight: 600;
                font-size: {scale(12)}px;
                color: {COLORS['dark_accent']};
            }}
            QPushButton:hover {{
                background-color: {COLORS['burnt_orange']};
                color: white;
            }}
        """)
        btn_select_cover.clicked.connect(self.select_cover_image)

        self.btn_remove_cover = QPushButton(tr_ui("repo_settings.btn_remove", "Entfernen"))
        self.btn_remove_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove_cover.setMinimumWidth(scale(90))
        self.btn_remove_cover.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.85);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                padding: {scale(8)}px {scale(14)}px;
                font-weight: 600;
                font-size: {scale(12)}px;
                color: #c0392b;
            }}
            QPushButton:hover {{
                background-color: #e74c3c;
                color: white;
            }}
        """)
        self.btn_remove_cover.clicked.connect(self.remove_cover_image)

        v_cover_btns = QHBoxLayout()
        v_cover_btns.setSpacing(scale(8))
        v_cover_btns.addWidget(btn_select_cover)
        v_cover_btns.addWidget(self.btn_remove_cover)

        h_cover_layout.addWidget(lbl_cover_title)
        h_cover_layout.addStretch()
        h_cover_layout.addWidget(self.lbl_cover_preview)
        h_cover_layout.addLayout(v_cover_btns)

        v_info.addWidget(card_cover)

        g_info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(g_info)

        # 📈 Level-Struktur
        self.g_levels = QGroupBox(tr_ui("repo_settings.levels_title", "📈 Level-Struktur"))
        self.g_levels.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        v_levels = QVBoxLayout(self.g_levels)
        v_levels.setSpacing(scale(10))
        v_levels.setContentsMargins(scale(18), scale(18), scale(18), scale(18))
        
        self.tbl_levels = QTableWidget()
        self.tbl_levels.setColumnCount(3)
        self.tbl_levels.setHorizontalHeaderLabels([
            tr_ui("repo_settings.header_lvl", "Lvl"), 
            tr_ui("repo_settings.header_name", "Bezeichnung"), 
            tr_ui("repo_settings.header_target_elo", "Ziel-Elo (Trainer)")
        ])
        self.tbl_levels.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_levels.verticalHeader().setVisible(False)
        self.tbl_levels.verticalHeader().setDefaultSectionSize(scale(42))
        self.tbl_levels.itemDoubleClicked.connect(self.rename_level)
        v_levels.addWidget(self.tbl_levels)
        
        h_lvl_btns = QHBoxLayout()
        btn_add_lvl = QPushButton(tr_ui("repo_settings.btn_add_level", "➕ Level hinzufügen"))
        btn_add_lvl.clicked.connect(self.add_level)
        btn_delete_lvl = QPushButton(tr_ui("repo_settings.btn_delete_level", "🗑️ Level löschen"))
        btn_delete_lvl.clicked.connect(self.delete_level)
        h_lvl_btns.addWidget(btn_add_lvl)
        h_lvl_btns.addWidget(btn_delete_lvl)
        h_lvl_btns.addStretch()
        v_levels.addLayout(h_lvl_btns)
        
        layout.addWidget(self.g_levels)

        # ⚠️ Gefahrenzone
        g_danger = QGroupBox(tr_ui("repo_settings.danger_zone_title", "⚠️ Gefahrenzone"))
        g_danger.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        v_danger = QVBoxLayout(g_danger)
        btn_delete = QPushButton(tr_ui("repo_settings.btn_delete_repertoire", "🗑️ Repertoire unwiderruflich löschen"))
        btn_delete.setProperty("class", "Danger")
        btn_delete.clicked.connect(self.delete_repertoire_action)
        v_danger.addWidget(btn_delete)
        layout.addWidget(g_danger)

        layout.addStretch()

    def init_page_design(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # 🎨 Oberfläche
        g_ui = QGroupBox(tr_ui("repo_settings.ui_title", "🎨 Oberfläche"))
        f_ui = QFormLayout(g_ui)
        self.combo_theme = QComboBox()
        for t in THEMES.keys(): self.combo_theme.addItem(t)
        current_theme = self.main_window.config.get("theme", "Blau (Turnier)")
        idx = self.combo_theme.findText(current_theme)
        if idx >= 0: self.combo_theme.setCurrentIndex(idx)
        self.combo_theme.currentTextChanged.connect(self.change_board_theme)
        f_ui.addRow(tr_ui("repo_settings.board_design", "Schachbrett Design:"), self.combo_theme)
        layout.addWidget(g_ui)

        # 🔊 Sound & Sprache
        g_sound = QGroupBox(tr_ui("repo_settings.sound_language_title", "🔊 Sound && Sprache"))
        f_sound = QFormLayout(g_sound)
        
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        try:
            vol_val = int(self.main_window.config.get("master_volume", 100))
        except (ValueError, TypeError):
            vol_val = 100
        self.slider_vol.setValue(vol_val)
        self.slider_vol.valueChanged.connect(self.change_volume)
        f_sound.addRow(tr_ui("repo_settings.volume", "Lautstärke:"), self.slider_vol)
        
        self.combo_not = QComboBox()
        self.combo_not.addItem(tr_ui("repo_settings.notation_standard", "Standard (English)"), "en")
        self.combo_not.addItem(tr_ui("repo_settings.notation_german", "Deutsch (S,D,L,K,T)"), "de")
        curr_not = self.main_window.config.get("notation_language", "en")
        idx_not = self.combo_not.findData(curr_not)
        if idx_not >= 0: self.combo_not.setCurrentIndex(idx_not)
        self.combo_not.currentIndexChanged.connect(self.change_notation_language)
        f_sound.addRow(tr_ui("repo_settings.notation_language", "Notation-Sprache:"), self.combo_not)
        
        layout.addWidget(g_sound)

        # 🧱 Tab-Konfiguration
        g_tabs = QGroupBox(tr_ui("repo_settings.tab_config_title", "🧱 Tab-Konfiguration (Sichtbarkeit)"))
        v_tabs = QVBoxLayout(g_tabs)
        lbl_tab_info = QLabel(tr_ui("repo_settings.tab_info", "Wähle aus, welche Tabs in der Creator-Ansicht (unten rechts) angezeigt werden sollen:"))
        lbl_tab_info.setWordWrap(True)
        lbl_tab_info.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 10px;")
        v_tabs.addWidget(lbl_tab_info)
        
        active_tabs = self.main_window.config.get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
        self.chk_details = QCheckBox(tr_ui("repo_settings.tab_details", "📋 Details (Position-Infos)"))
        self.chk_analysis = QCheckBox(tr_ui("repo_settings.tab_analysis", "🧠 Analyse (Engine && Lichess)"))
        self.chk_transpositions = QCheckBox(tr_ui("repo_settings.tab_transpositions", "🔄 Transpositionen (Varianten-Überschneidungen)"))
        self.chk_holes = QCheckBox(tr_ui("repo_settings.tab_search_mode", "🕳️ Such Modus (Repertoire-Lücken)"))
        self.chk_kontrolle = QCheckBox(tr_ui("repo_settings.tab_control", "✅ Kontrolle (Variation Filtering)"))
        
        for chk, key in [(self.chk_details, "DETAILS"), (self.chk_analysis, "ANALYSIS"), 
                         (self.chk_transpositions, "TRANSPOSITIONS"),
                         (self.chk_holes, "HOLES"), (self.chk_kontrolle, "KONTROLLE")]:
            chk.setChecked(key in active_tabs)
            chk.toggled.connect(self.save_tab_settings)
            v_tabs.addWidget(chk)
            
        layout.addWidget(g_tabs)
        layout.addStretch()

    def init_page_imex(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # 📥 Import
        g_import = QGroupBox(tr_ui("repo_settings.import_title", "📥 Import-Möglichkeiten"))
        v_import = QVBoxLayout(g_import)
        h_pgn = QHBoxLayout()
        
        pgn_tip = tr_ui("repo_settings.pgn_tip", "Importiert Züge in das gewählte Level. Existierende Kommentare werden ergänzt (nicht überschrieben). Züge, die bereits vorhanden sind, behalten ihr Level bei (keine Duplikate).")
        
        btn_paste = QPushButton(tr_ui("repo_settings.btn_paste_pgn", "📋 PGN Text einfügen"))
        btn_paste.setToolTip(pgn_tip)
        btn_paste.clicked.connect(self.paste_pgn_dialog)
        
        btn_file = QPushButton(tr_ui("repo_settings.btn_select_pgn_file", "📄 PGN Datei auswählen"))
        btn_file.setToolTip(pgn_tip)
        btn_file.clicked.connect(self.import_pgn_file_dialog)
        
        h_pgn.addWidget(btn_paste)
        h_pgn.addWidget(btn_file)
        v_import.addLayout(h_pgn)
        layout.addWidget(g_import)

        # 📤 Export && Management
        g_export = QGroupBox(tr_ui("repo_settings.export_management_title", "📤 Export && Management"))
        v_export = QVBoxLayout(g_export)
        
        h_manage = QHBoxLayout()
        btn_simple_export = QPushButton(tr_ui("repo_settings.btn_export_simple", "📤 Export (PGN/DB)"))
        btn_simple_export.clicked.connect(self.export_repertoire)
        
        btn_copy_repo = QPushButton(tr_ui("repo_settings.btn_copy_course", "👯 Gesamten Kurs kopieren"))
        btn_copy_repo.setToolTip(tr_ui("repo_settings.copy_course_tip", "Erstellt eine vollständige 1:1 Kopie dieses Repertoires unter einem neuen Namen."))
        btn_copy_repo.clicked.connect(self.copy_repertoire_action)
        
        h_manage.addWidget(btn_simple_export)
        h_manage.addWidget(btn_copy_repo)
        v_export.addLayout(h_manage)
        
        v_export.addSpacing(scale(15))
        btn_full_export = QPushButton(tr_ui("repo_settings.btn_prepare_share", "🚀 Gesamter Kurs für Teilen vorbereiten"))
        btn_full_export.setToolTip(tr_ui("repo_settings.prepare_share_tip", "Exportiert jedes Level als einzelne PGN-Datei, erstellt eine README-Übersicht und öffnet den Ordner zur Weitergabe."))
        btn_full_export.setProperty("class", "Primary")
        btn_full_export.setMinimumHeight(scale(50))
        btn_full_export.clicked.connect(self.prepare_full_course_export)
        v_export.addWidget(btn_full_export)
        
        layout.addWidget(g_export)
        layout.addStretch()

    def init_page_tools(self, page):
        import multiprocessing
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # 1. 🔍 Diagnose & Instandhaltung
        g_diag = QGroupBox(tr_ui("repo_settings.tools_title", "🔍 Diagnose && Instandhaltung"))
        v_diag = QVBoxLayout(g_diag)
        btn_diag = QPushButton(tr_ui("repo_settings.btn_diag", "🔎 Datenbank-Diagnose && Reparatur"))
        btn_diag.clicked.connect(self.run_structure_repair)
        btn_names = QPushButton(tr_ui("repo_settings.btn_names", "🏷️ Variantennamen neu berechnen"))
        btn_names.clicked.connect(self.run_variation_name_repair)
        
        self.btn_wipe_lichess = QPushButton(tr_ui("repo_settings.btn_wipe_lichess", "🗑️ Lichess Datenbank-Daten löschen für alle Elos außer [{elo}]", elo="..."))
        self.btn_wipe_lichess.clicked.connect(self.wipe_other_lichess_data_action)
        self.btn_wipe_lichess.setStyleSheet("color: #e67e22; font-weight: 500;")

        btn_cleanup_lichess = QPushButton(tr_ui("repo_settings.btn_cleanup_lichess", "🧹 Verwaiste Lichess-Daten bereinigen"))
        btn_cleanup_lichess.clicked.connect(self.run_lichess_orphan_cleanup)
        btn_cleanup_lichess.setToolTip(tr_ui("repo_settings.cleanup_lichess_tooltip", "Entfernt Lichess-Explorer-Daten für Stellungen, die nicht mehr in deinem Repertoire existieren."))

        v_diag.addWidget(btn_diag)
        v_diag.addWidget(btn_names)
        v_diag.addWidget(self.btn_wipe_lichess)
        v_diag.addWidget(btn_cleanup_lichess)
        layout.addWidget(g_diag)

        # 2. 🧹 Kommentare Bereinigen
        g_clean = QGroupBox(tr_ui("repo_settings.comments_cleanup_title", "🧹 Kommentare Bereinigen"))
        v_clean = QVBoxLayout(g_clean)
        btn_dedupe = QPushButton(tr_ui("repo_settings.btn_dedupe", "🔄 Doppelte Texte in Kommentaren entfernen"))
        btn_dedupe.clicked.connect(self.clean_comments)
        btn_brackets = QPushButton(tr_ui("repo_settings.btn_brackets", "❌ Text in [eckigen Klammern] löschen"))
        btn_brackets.clicked.connect(self.clean_brackets)
        v_clean.addWidget(btn_dedupe)
        v_clean.addWidget(btn_brackets)
        layout.addWidget(g_clean)

        # 3. 🤖 Engine Analyse
        g_engine = QGroupBox(tr_ui("repo_settings.engine_scan_title", "🤖 Engine-Analyse"))
        v_eng_main = QVBoxLayout(g_engine)
        lbl_eng_desc = QLabel(tr_ui("repo_settings.engine_scan_desc", "Alternativ gute Züge berechnen mit Engine-Analyse des gesamten Repertoires."))
        lbl_eng_desc.setWordWrap(True)
        lbl_eng_desc.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 6px;")
        v_eng_main.addWidget(lbl_eng_desc)

        f_engine = QFormLayout()
        self.txt_engine_path = QLineEdit()
        self.txt_engine_path.setText(self.main_window.config.get("engine_path", ""))
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(scale(42))
        btn_browse.setStyleSheet("padding: 0px; font-weight: bold;")
        btn_browse.clicked.connect(self.browse_engine_path)
        h_path = QHBoxLayout(); h_path.addWidget(self.txt_engine_path); h_path.addWidget(btn_browse)
        f_engine.addRow(tr_ui("repo_settings.engine_path_label", "Engine Pfad:"), h_path)
        
        # Defaults: 18 depth and 25% CPU Threads
        self.s_d = NoWheelSpinBox(); self.s_d.setRange(10, 50); self.s_d.setValue(18)
        self.c_threads = NoWheelComboBox()
        cpu_count = multiprocessing.cpu_count()
        for i in range(1, cpu_count + 1): self.c_threads.addItem(str(i))
        default_threads = max(1, int(cpu_count * 0.25))
        self.c_threads.setCurrentText(str(default_threads))
        f_engine.addRow(tr_ui("repo_settings.search_depth_label", "Suchtiefe:"), self.s_d)
        f_engine.addRow(tr_ui("repo_settings.threads_label", "Threads:"), self.c_threads)
        
        self.btn_start_eng = QPushButton(tr_ui("repo_settings.btn_start_scan", "🚀 Engine-Scan starten"))
        self.btn_start_eng.clicked.connect(self.start_analysis)
        f_engine.addRow("", self.btn_start_eng)
        self.pb_eng = QProgressBar(); self.l_eng_status = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        v_eng_prog = QVBoxLayout()
        v_eng_prog.addWidget(self.l_eng_status); v_eng_prog.addWidget(self.pb_eng)
        f_engine.addRow(tr_ui("repo_settings.progress_label", "Fortschritt:"), v_eng_prog)
        v_eng_main.addLayout(f_engine)
        layout.addWidget(g_engine)

        # 4. 🌐 Lichess Datenbank
        g_lichess = QGroupBox(tr_ui("repo_settings.lichess_scan_title", "🌐 Lichess-Datenbank && Prio Scores"))
        v_lich = QVBoxLayout(g_lichess)
        lbl_lich_desc = QLabel(tr_ui("repo_settings.lichess_scan_desc", "Lichess-Datenbank-Daten herunterladen und Prio-Scores berechnen lassen."))
        lbl_lich_desc.setWordWrap(True)
        lbl_lich_desc.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 6px;")
        v_lich.addWidget(lbl_lich_desc)

        f_token = QFormLayout()
        
        h_token_row = QHBoxLayout()
        self.txt_lichess_token = QLineEdit()
        self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_lichess_token.setText(self.main_window.config.get("lichess_token", ""))
        self.txt_lichess_token.textChanged.connect(self.on_token_changed)
        
        btn_toggle_token = QPushButton("👁️")
        btn_toggle_token.setFixedWidth(scale(42))
        btn_toggle_token.setStyleSheet("padding: 0px; font-size: 14px;")
        btn_toggle_token.setCheckable(True)
        btn_toggle_token.toggled.connect(lambda checked: self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        
        h_token_row.addWidget(self.txt_lichess_token)
        h_token_row.addWidget(btn_toggle_token)
        f_token.addRow(tr_ui("repo_settings.api_token_label", "API-Token:"), h_token_row)
        
        # Elo Selection (Read-only / display based on settings)
        self.lbl_lichess_target_elo = QLabel(tr_ui("repo_settings.target_elo_label", "Ziel-Elo: {elo}", elo="-"))
        self.lbl_lichess_target_elo.setStyleSheet("font-weight: bold; color: #2980b9; background: rgba(41, 128, 185, 0.1); border-radius: 4px; padding: 5px;")
        f_token.addRow(tr_ui("repo_settings.import_focus_label", "Import-Fokus:"), self.lbl_lichess_target_elo)
        v_lich.addLayout(f_token)
        
        h_fetch = QHBoxLayout()
        self.btn_fetch = QPushButton(tr_ui("repo_settings.btn_fetch", "📡 Daten laden && Scores berechnen"))
        self.btn_fetch.clicked.connect(self.start_fetch)
        btn_delete_l = QPushButton(tr_ui("repo_settings.btn_delete_lichess", "🗑️ Daten für diese Elo löschen"))
        btn_delete_l.clicked.connect(self.delete_lichess_action)
        h_fetch.addWidget(self.btn_fetch); h_fetch.addWidget(btn_delete_l)
        v_lich.addLayout(h_fetch)
        self.pb_lich = QProgressBar(); self.l_lich_status = QLabel(tr_ui("repo_settings.status_waiting", "Warte auf Start..."))
        v_lich.addWidget(self.l_lich_status); v_lich.addWidget(self.pb_lich)
        layout.addWidget(g_lichess)

        # 5. ⚡ Prio basiertes Leveling
        g_prio = QGroupBox(tr_ui("repo_settings.prio_leveling_title", "⚡ Level-Anpassung per Prio-Score"))
        v_prio = QVBoxLayout(g_prio)
        lbl_prio_desc = QLabel(tr_ui("repo_settings.prio_leveling_desc", "Alle Züge basierend auf dem Prio-Score auf ein anderes Level setzen."))
        lbl_prio_desc.setWordWrap(True)
        lbl_prio_desc.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 6px;")
        v_prio.addWidget(lbl_prio_desc)

        f_prio = QFormLayout()
        self.spin_prio_threshold = QSpinBox(); self.spin_prio_threshold.setRange(1, 100); self.spin_prio_threshold.setSuffix(" %"); self.spin_prio_threshold.setValue(10)
        self.combo_prio_target = QComboBox()
        f_prio.addRow(tr_ui("repo_settings.prio_threshold_label", "Schwellenwert (Prio > X):"), self.spin_prio_threshold)
        f_prio.addRow(tr_ui("repo_settings.target_level_label", "Ziel-Level:"), self.combo_prio_target)
        v_prio.addLayout(f_prio)
        h_prio_btns = QHBoxLayout()
        self.btn_prio_preview = QPushButton(tr_ui("repo_settings.btn_prio_preview", "🔍 Auswirkung prüfen")); self.btn_prio_preview.clicked.connect(self.preview_priority_level)
        self.btn_prio_apply = QPushButton(tr_ui("repo_settings.btn_prio_apply", "🚀 Level anpassen")); self.btn_prio_apply.setProperty("class", "Primary"); self.btn_prio_apply.clicked.connect(self.apply_priority_level)
        h_prio_btns.addWidget(self.btn_prio_preview); h_prio_btns.addWidget(self.btn_prio_apply)
        v_prio.addLayout(h_prio_btns)
        layout.addWidget(g_prio)

        # 6. 🏗️ Globale Zuweisungen
        g_global = QGroupBox(tr_ui("repo_settings.global_leveling_title", "🏗️ Alle Züge auf ein gewisses Level setzen"))
        v_global = QVBoxLayout(g_global)
        h_global = QHBoxLayout()
        self.combo_global_level = QComboBox()
        btn_global_apply = QPushButton(tr_ui("repo_settings.btn_global_apply", "Alle Züge auf dieses Level setzen"))
        btn_global_apply.clicked.connect(self.global_move_all_level)
        h_global.addWidget(self.combo_global_level); h_global.addWidget(btn_global_apply)
        v_global.addLayout(h_global)
        layout.addWidget(g_global)

        # 7. 🗑️ Massen-Löschung basierend auf Popularity / Prio Score
        g_prune = QGroupBox(tr_ui("repo_settings.popularity_prune_title", "🗑️ Massen-Löschung basierend auf Popularity / Prio Score"))
        v_prune = QVBoxLayout(g_prune)
        lbl_prune_desc = QLabel(tr_ui("repo_settings.popularity_prune_desc", "Löscht alle Züge und deren Unter-Varianten, deren Popularitäts-/Prio-Score unter dem gewählten Schwellenwert liegt."))
        lbl_prune_desc.setWordWrap(True)
        lbl_prune_desc.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 8px;")
        v_prune.addWidget(lbl_prune_desc)

        f_prune = QFormLayout()
        self.spin_prune_threshold = NoWheelSpinBox()
        self.spin_prune_threshold.setRange(1, 90)
        self.spin_prune_threshold.setSuffix(" %")
        self.spin_prune_threshold.setValue(5)

        self.combo_prune_target_level = NoWheelComboBox()

        f_prune.addRow(tr_ui("repo_settings.prune_threshold_label", "Popularitäts-Schwellenwert (Prio < X%):"), self.spin_prune_threshold)
        f_prune.addRow(tr_ui("repo_settings.prune_target_level_label", "Fokus Level:"), self.combo_prune_target_level)
        v_prune.addLayout(f_prune)

        h_prune_btns = QHBoxLayout()
        self.btn_prune_preview = QPushButton(tr_ui("repo_settings.btn_prune_preview", "🔍 Auswirkung prüfen"))
        self.btn_prune_preview.clicked.connect(self.preview_popularity_prune)
        self.btn_prune_apply = QPushButton(tr_ui("repo_settings.btn_prune_apply", "🗑️ Züge löschen"))
        self.btn_prune_apply.setProperty("class", "Danger")
        self.btn_prune_apply.clicked.connect(self.apply_popularity_prune)

        h_prune_btns.addWidget(self.btn_prune_preview)
        h_prune_btns.addWidget(self.btn_prune_apply)
        v_prune.addLayout(h_prune_btns)
        layout.addWidget(g_prune)

        # 8. 📁 System-Ordner im Explorer öffnen
        g_folders = QGroupBox(tr_ui("repo_settings.folder_access_title", "📁 System-Ordner im Explorer öffnen"))
        h_folders = QHBoxLayout(g_folders)
        btn_open_active = QPushButton(tr_ui("repo_settings.btn_open_active_repo", "📁 Aktuellen Repertoire-Ordner im Explorer öffnen"))
        btn_open_active.clicked.connect(self.open_active_repertoire_folder)
        btn_open_all_r = QPushButton(tr_ui("repo_settings.btn_open_all_repos", "📁 Alle Repertoires-Ordner im Explorer öffnen"))
        btn_open_all_r.clicked.connect(self.open_all_repertoires_folder)
        btn_open_profs = QPushButton(tr_ui("repo_settings.btn_open_profiles", "📁 Profile-Ordner im Explorer öffnen"))
        btn_open_profs.clicked.connect(self.open_profiles_folder)
        h_folders.addWidget(btn_open_active)
        h_folders.addWidget(btn_open_all_r)
        h_folders.addWidget(btn_open_profs)
        layout.addWidget(g_folders)

        layout.addStretch()

    def open_active_repertoire_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        if self.active_repo_name:
            path = get_repertoire_dir(self.active_repo_name)
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_all_repertoires_folder(self):
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

    def init_page_maintenance(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # 🚜 Wartungs-Center (Batch)
        g_main = QGroupBox(tr_ui("repo_settings.maintenance_title", "🚜 Wartungs-Center (Batch)"))
        v_main = QVBoxLayout(g_main)
        v_main.setSpacing(scale(15))
        v_main.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        # --- Section 1: Repertoires ---
        lbl_batch = QLabel(tr_ui("repo_settings.maintenance_step1", "1. Wähle Repertoires aus, die verarbeitet werden sollen:"))
        lbl_batch.setStyleSheet("font-weight: bold; color: #444;")
        v_main.addWidget(lbl_batch)
        
        self.main_table = QTableWidget()
        self.main_table.setColumnCount(6)
        self.main_table.setHorizontalHeaderLabels([
            tr_ui("repo_settings.col_select", ""),
            tr_ui("repo_settings.col_name", "Repertoire Name"),
            tr_ui("repo_settings.col_prio_elo", "Prio Elo"),
            tr_ui("repo_settings.col_status", "Analyse-Status"),
            tr_ui("repo_settings.col_coverage", "Datenbank-Coverage"),
            tr_ui("repo_settings.col_progress", "Fortschritt")
        ])
        self.main_table.verticalHeader().setVisible(False)
        self.main_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.main_table.setColumnWidth(0, scale(40))
        self.main_table.setColumnWidth(1, scale(180))
        self.main_table.setColumnWidth(2, scale(100))
        self.main_table.setColumnWidth(3, scale(150))
        self.main_table.setColumnWidth(4, scale(150))
        self.main_table.horizontalHeader().setStretchLastSection(True)
        self.main_table.setMinimumHeight(scale(250))
        self.main_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.main_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        v_main.addWidget(self.main_table)
        
        h_ctrl = QHBoxLayout()
        btn_all = QPushButton(tr_ui("repo_settings.btn_all", "Alle"))
        btn_none = QPushButton(tr_ui("repo_settings.btn_none", "Keine"))
        btn_all.clicked.connect(lambda: self._select_all_maintenance_repos(True))
        btn_none.clicked.connect(lambda: self._select_all_maintenance_repos(False))
        h_ctrl.addWidget(btn_all); h_ctrl.addWidget(btn_none); h_ctrl.addStretch()
        v_main.addLayout(h_ctrl)
        
        # --- Section 2: Tasks ---
        v_main.addSpacing(scale(10))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken); line.setStyleSheet("background-color: rgba(0,0,0,0.05);")
        v_main.addWidget(line)
        v_main.addSpacing(scale(10))

        lbl_tasks = QLabel(tr_ui("repo_settings.maintenance_step2", "2. Aufgaben auswählen & konfigurieren:"))
        lbl_tasks.setStyleSheet("font-weight: bold; color: #444;")
        v_main.addWidget(lbl_tasks)

        f_conf = QFormLayout()
        self.chk_m_engine = QCheckBox(tr_ui("repo_settings.task_engine", "Engine Analyse (Alternativen)"))
        self.chk_m_engine.setChecked(True)
        self.chk_m_lichess = QCheckBox(tr_ui("repo_settings.task_lichess", "Lichess Import (Trend-Daten)"))
        self.chk_m_lichess.setChecked(True)
        self.chk_m_cleanup_lichess = QCheckBox(tr_ui("repo_settings.task_cleanup_lichess", "Verwaiste Lichess-Daten bereinigen"))
        self.chk_m_cleanup_lichess.setChecked(True)
        self.chk_m_stats = QCheckBox(tr_ui("repo_settings.task_stats", "Statistiken && Prioritäten berechnen"))
        self.chk_m_stats.setChecked(True)
        
        v_tasks = QVBoxLayout()
        v_tasks.addWidget(self.chk_m_engine)
        v_tasks.addWidget(self.chk_m_lichess)
        v_tasks.addWidget(self.chk_m_cleanup_lichess)
        v_tasks.addWidget(self.chk_m_stats)
        f_conf.addRow(tr_ui("repo_settings.tasks_label", "Aufgaben:"), v_tasks)
        
        self.spin_m_depth = QSpinBox()
        self.spin_m_depth.setRange(10, 40)
        try:
            depth_val = int(self.main_window.config.get("engine_depth", 20))
        except (ValueError, TypeError):
            depth_val = 20
        self.spin_m_depth.setValue(depth_val)
        f_conf.addRow(tr_ui("repo_settings.engine_depth_label", "Engine Tiefe:"), self.spin_m_depth)
        
        self.spin_m_threads = QSpinBox()
        self.spin_m_threads.setRange(1, multiprocessing.cpu_count())
        self.spin_m_threads.setValue(max(1, multiprocessing.cpu_count() - 1))
        f_conf.addRow(tr_ui("repo_settings.engine_threads_label", "Engine Threads:"), self.spin_m_threads)
        v_main.addLayout(f_conf)
        
        # --- Section 3: Execution ---
        v_main.addSpacing(scale(15))
        self.btn_m_start = QPushButton(tr_ui("repo_settings.btn_start_batch", "🚀 Wartungs-Batch starten"))
        self.btn_m_start.setProperty("class", "Primary")
        self.btn_m_start.setMinimumHeight(scale(50))
        self.btn_m_start.clicked.connect(self.start_centralized_maintenance)
        v_main.addWidget(self.btn_m_start)
        
        self.pb_m_overall = QProgressBar(); self.lbl_m_overall = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        self.pb_m_overall.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v_main.addWidget(self.lbl_m_overall); v_main.addWidget(self.pb_m_overall)
        
        layout.addWidget(g_main)
        layout.addStretch()

    # Logic methods (Delegating or implementing)
    def save_description(self):
        if not self.backend or not getattr(self.backend, 'session', None): return
        self.backend.set_meta("description", self.txt_description.toPlainText())
        self.backend.session.commit()

    def save_repertoire_elo(self, value):
        if not self.backend or not getattr(self.backend, 'session', None): return
        internal_val = get_elo_internal(value)
        self.backend.set_meta("elo", internal_val)
        self.backend.session.commit()

    def save_repertoire_color(self, _=None):
        if not self.backend or not getattr(self.backend, 'session', None): return
        color = self.combo_repertoire_color.currentData()
        self.backend.set_meta("color", color)
        self.backend.session.commit()
        
        # Update UI in main window
        if hasattr(self.main_window, 'board_widget'):
            self.main_window.board_widget.flipped = (color == 'b')
            self.main_window.board_widget.update()

    def save_tab_settings(self, _=None):
        active = []
        if self.chk_details.isChecked(): active.append("DETAILS")
        if self.chk_analysis.isChecked(): active.append("ANALYSIS")
        if self.chk_transpositions.isChecked(): active.append("TRANSPOSITIONS")
        if self.chk_holes.isChecked(): active.append("HOLES")
        if self.chk_kontrolle.isChecked(): active.append("KONTROLLE")
        self.main_window.set_setting("creator_active_tabs", active)
        self.main_window.apply_tab_visibility()

    def save_start_move(self, val):
        if self.backend:
            self.backend.set_repertoire_start_move(val)

    def set_all_levels_elo(self):
        val, ok = QInputDialog.getInt(self, tr_ui("repo_settings.dlg_global_elo_title", "Globales Elo"), tr_ui("repo_settings.dlg_global_elo_prompt", "Ziel-Elo für ALLE Level setzen:"), 1500, 800, 4000)
        if ok and self.backend:
            levels = self.backend.get_repertoire_levels()
            for lvl in levels:
                self.backend.update_level_elo(lvl['order'], val)
            self.refresh_info()
            QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_all_levels_elo_done", "Alle Level wurden auf {val} Elo gesetzt.", val=val))

    def delete_level(self):
        if not self.backend: return
        levels = self.backend.get_repertoire_levels()
        if not levels or len(levels) <= 1:
            QMessageBox.warning(self, tr_ui("repo_settings.dlg_error", "Fehler"), tr_ui("repo_settings.delete_level_min_warn", "Mindestens 1 Level ist erforderlich. Das letzte verbleibende Level kann nicht gelöscht werden."))
            return

        selected_order = None
        curr_row = self.tbl_levels.currentRow()
        if curr_row >= 0:
            try:
                selected_order = int(self.tbl_levels.item(curr_row, 0).text())
            except (ValueError, AttributeError):
                selected_order = None

        dlg = DeleteLevelDialog(levels, default_del_order=selected_order, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            del_order, target_order, delete_moves = dlg.get_selection()
            if del_order:
                if delete_moves:
                    reply = QMessageBox.question(
                        self,
                        tr_ui("repo_settings.delete_level_dialog_title", "Level löschen"),
                        tr_ui("repo_settings.delete_level_confirm_delete_moves", "Möchtest du wirklich Level {level} und ALLE darin enthaltenen Züge unwiderruflich löschen?", level=del_order),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return

                success, msg = self.backend.delete_repertoire_level(del_order, target_level_order=target_order, delete_moves=delete_moves)
                if success:
                    self.refresh_info()
                    QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), msg)
                else:
                    QMessageBox.warning(self, tr_ui("repo_settings.dlg_error", "Fehler"), msg)

    def preview_priority_level(self):
        threshold = self.spin_prio_threshold.value()
        target_lvl = self.combo_prio_target.currentData()
        if not target_lvl: return
        
        impact = self.backend.get_priority_level_impact(threshold, target_lvl)
        QMessageBox.information(self, tr_ui("repo_settings.dlg_preview_title", "Vorschau"), tr_ui("repo_settings.dlg_preview_msg", "Bei einer Priorität > {threshold}% würden {count} Züge in das Level {level} verschoben werden.", threshold=threshold, count=impact, level=target_lvl))

    def apply_priority_level(self):
        threshold = self.spin_prio_threshold.value()
        target_lvl = self.combo_prio_target.currentData()
        if not target_lvl: return
        
        impact = self.backend.get_priority_level_impact(threshold, target_lvl)
        if impact == 0:
            QMessageBox.information(self, "Info", tr_ui("repo_settings.dlg_preview_msg", "Bei einer Priorität > {threshold}% würden {count} Züge in das Level {level} verschoben werden.", threshold=threshold, count=0, level=target_lvl))
            return
            
        reply = QMessageBox.question(self, tr_ui("repo_settings.dlg_apply_title", "Anwenden"), tr_ui("repo_settings.dlg_apply_msg", "{count} Züge werden auf Level {level} gesetzt. Fortfahren?", count=impact, level=target_lvl),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            modified = self.backend.apply_priority_level_update(threshold, target_lvl)
            self.refresh_info()
            QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), tr_ui("repo_settings.dlg_moves_updated", "{count} Züge wurden aktualisiert.", count=modified))

    def preview_popularity_prune(self):
        if not self.backend: return
        threshold = self.spin_prune_threshold.value()
        lvl_filter = self.combo_prune_target_level.currentData()
        moves_cnt, pos_cnt = self.backend.get_low_popularity_prune_impact(threshold, lvl_filter)
        QMessageBox.information(
            self,
            tr_ui("repo_settings.dlg_preview_title", "Vorschau"),
            tr_ui("repo_settings.prune_preview_msg", "Bei einer Popularität < {threshold}% würden {moves} Züge und {positions} Stellungen gelöscht werden.", threshold=threshold, moves=moves_cnt, positions=pos_cnt)
        )

    def apply_popularity_prune(self):
        if not self.backend: return
        threshold = self.spin_prune_threshold.value()
        lvl_filter = self.combo_prune_target_level.currentData()
        moves_cnt, pos_cnt = self.backend.get_low_popularity_prune_impact(threshold, lvl_filter)
        if moves_cnt == 0:
            QMessageBox.information(
                self,
                tr_ui("repo_settings.dlg_preview_title", "Vorschau"),
                tr_ui("repo_settings.prune_preview_msg", "Bei einer Popularität < {threshold}% würden {moves} Züge und {positions} Stellungen gelöscht werden.", threshold=threshold, moves=0, positions=0)
            )
            return

        reply = QMessageBox.question(
            self,
            tr_ui("repo_settings.popularity_prune_title", "Massen-Löschung"),
            tr_ui("repo_settings.prune_apply_confirm", "Möchtest du wirklich {moves} Züge mit Popularität < {threshold}% unwiderruflich löschen?", moves=moves_cnt, threshold=threshold),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = self.backend.apply_low_popularity_prune(threshold, lvl_filter)
            self.refresh_info()
            QMessageBox.information(
                self,
                tr_ui("repo_settings.dlg_done", "Fertig"),
                tr_ui("repo_settings.prune_done", "{count} Züge wurden erfolgreich gelöscht.", count=deleted_count)
            )

    def clean_comments(self):
        n = self.backend.deduplicate_comments_in_repo()
        QMessageBox.information(self, tr_ui("repo_settings.dlg_cleanup_title", "Bereinigung"), tr_ui("repo_settings.dlg_dedup_done", "Fertig! In {count} Stellungen wurden doppelte Kommentar-Texte entfernt.", count=n))

    def clean_brackets(self):
        n = self.backend.clean_brackets_in_repo()
        QMessageBox.information(self, tr_ui("repo_settings.dlg_cleanup_title", "Bereinigung"), tr_ui("repo_settings.dlg_brackets_done", "Fertig! In {count} Stellungen wurde Text in [eckigen Klammern] gelöscht.", count=n))

    def global_move_all_level(self):
        target_lvl = self.combo_global_level.currentData()
        if not target_lvl: return
        
        reply = QMessageBox.question(self, tr_ui("repo_settings.dlg_global_assign_title", "Globale Zuweisung"), 
            tr_ui("repo_settings.dlg_global_assign_msg", "Möchtest du wirklich ALLE Züge des Repertoires auf Level {level} setzen?", level=target_lvl),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            n = self.backend.move_all_to_level(target_lvl)
            self.refresh_info()
            QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_moves_set_to_level", "{count} Züge wurden auf Level {level} gesetzt.", count=n, level=target_lvl))

    def change_board_theme(self, theme):
        self.main_window.board_widget.set_theme(theme)
        self.main_window.set_setting("theme", theme)

    def change_volume(self, val):
        self.main_window.set_setting("master_volume", val)
        if hasattr(self.main_window, 'sounds'):
            for s in self.main_window.sounds.values(): s.setVolume(val / 100.0)

    def change_notation_language(self, idx):
        lang = self.combo_not.currentData()
        self.main_window.set_setting("notation_language", lang)
        if hasattr(self.main_window, "update_ui_from_fen"): self.main_window.update_ui_from_fen()
        for w in QApplication.instance().topLevelWidgets():
            if hasattr(w, "update_notation_display"): w.update_notation_display()

    def update_cover_preview(self):
        from PyQt6.QtGui import QPixmap
        from opening_fenix.creator.repo_selection_dialog import get_repertoire_cover_path
        import os
        
        name = self.l_n.text()
        if not name or name == "Unbekannt":
            self.lbl_cover_preview.clear()
            self.lbl_cover_preview.setText(tr_ui("repo_settings.no_cover_image", "Kein Bild"))
            self.lbl_cover_preview.setStyleSheet("color: #777; font-style: italic; border: 1px dashed #ccc; border-radius: 4px; background-color: #f9f9f9;")
            self.btn_remove_cover.setEnabled(False)
            return
            
        cover_path = get_repertoire_cover_path(name)
        if cover_path and os.path.exists(cover_path):
            pix = QPixmap(cover_path)
            if not pix.isNull():
                self.lbl_cover_preview.setPixmap(pix)
                self.lbl_cover_preview.setStyleSheet("border: 1px solid #ddd; border-radius: 4px;")
                self.btn_remove_cover.setEnabled(True)
                return
                
        self.lbl_cover_preview.clear()
        self.lbl_cover_preview.setText(tr_ui("repo_settings.no_cover_image", "Kein Bild"))
        self.lbl_cover_preview.setStyleSheet("color: #777; font-style: italic; border: 1px dashed #ccc; border-radius: 4px; background-color: #f9f9f9;")
        self.btn_remove_cover.setEnabled(False)

    def select_cover_image(self):
        import shutil
        import os
        from PyQt6.QtWidgets import QMessageBox
        from opening_fenix.core.data_tools import get_user_dir
        
        name = self.l_n.text()
        if not name or name == "Unbekannt":
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Cover-Bild auswählen",
            "",
            "Bilder (*.png *.jpg *.jpeg)"
        )
        if not file_path:
            return
            
        # Get target directory
        repo_base = os.path.join(get_user_dir(), "repertoires")
        repo_dir = os.path.join(repo_base, name)
        
        # If normal directory doesn't exist, try test directory
        if not os.path.exists(repo_dir):
            repo_dir = os.path.join(repo_base, "test", name)
            
        if not os.path.exists(repo_dir):
            QMessageBox.warning(self, tr_ui("repo_settings.dlg_error", "Fehler"), tr_ui("repo_settings.dlg_cover_folder_error", "Repertoire-Ordner für '{name}' wurde nicht gefunden.", name=name))
            return
            
        # Get extension of selected file
        ext = file_path.lower().split(".")[-1]
        if ext not in ("png", "jpg", "jpeg"):
            ext = "png"
            
        # Remove any existing cover images first to avoid conflicts (e.g. cover.jpg and cover.png)
        for f in os.listdir(repo_dir):
            if f.lower().startswith("cover."):
                try:
                    os.remove(os.path.join(repo_dir, f))
                except Exception:
                    pass
                    
        # Copy file to repo_dir as cover.{ext}
        target_path = os.path.join(repo_dir, f"cover.{ext}")
        try:
            shutil.copy(file_path, target_path)
            self.update_cover_preview()
            
            # Notify all top-level windows to refresh their repertoire lists/covers
            for w in QApplication.topLevelWidgets():
                if hasattr(w, "refresh_repertoire_buttons"):
                    w.refresh_repertoire_buttons()
                if hasattr(w, "load_repertoire_list"):
                    w.load_repertoire_list()
                    
            QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_cover_added", "Das Cover-Bild wurde erfolgreich hinzugefügt."))
        except Exception as e:
            QMessageBox.critical(self, tr_ui("repo_settings.dlg_error", "Fehler"), tr_ui("repo_settings.dlg_cover_copy_error", "Das Bild konnte nicht kopiert werden: {error}", error=str(e)))

    def remove_cover_image(self):
        import os
        from PyQt6.QtWidgets import QMessageBox
        from opening_fenix.core.data_tools import get_user_dir
        
        name = self.l_n.text()
        if not name or name == "Unbekannt":
            return
            
        reply = QMessageBox.question(
            self,
            tr_ui("repo_settings.dlg_cover_remove_title", "Cover-Bild entfernen"),
            tr_ui("repo_settings.dlg_cover_remove_msg", "Möchtest du das aktuelle Cover-Bild wirklich löschen?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        repo_base = os.path.join(get_user_dir(), "repertoires")
        repo_dirs = [os.path.join(repo_base, name), os.path.join(repo_base, "test", name)]
        
        deleted = False
        for repo_dir in repo_dirs:
            if os.path.exists(repo_dir):
                for f in os.listdir(repo_dir):
                    if f.lower().startswith("cover."):
                        try:
                            os.remove(os.path.join(repo_dir, f))
                            deleted = True
                        except Exception:
                            pass
                            
        self.update_cover_preview()
        if deleted:
            # Notify all top-level windows to refresh their repertoire lists/covers
            for w in QApplication.topLevelWidgets():
                if hasattr(w, "refresh_repertoire_buttons"):
                    w.refresh_repertoire_buttons()
                if hasattr(w, "load_repertoire_list"):
                    w.load_repertoire_list()
            QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_cover_deleted", "Das Cover-Bild wurde gelöscht."))

    def rename_repertoire(self):
        old_name = self.backend.active_repo_name
        new_name, ok = QInputDialog.getText(self, tr_ui("repo_settings.dlg_rename_title", "Umbenennen"), tr_ui("repo_settings.dlg_rename_prompt", "Neuer Name für das Repertoire:"), QLineEdit.EchoMode.Normal, old_name)
        if ok and new_name and new_name != old_name:
            # Use the new robust renaming logic (filesystem + profiles)
            if hasattr(self.backend, "rename_repertoire"):
                success, msg = self.backend.rename_repertoire(old_name, new_name)
                if success:
                    QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), msg)
                    self.refresh_info()
                    
                    # Notify all top-level windows to refresh their repertoire lists
                    for w in QApplication.topLevelWidgets():
                        # Trainer refresh
                        if hasattr(w, "refresh_repertoire_buttons"):
                            w.refresh_repertoire_buttons()
                        # Creator/General refresh if applicable
                        if hasattr(w, "load_repertoire_list"):
                            w.load_repertoire_list()
                else:
                    QMessageBox.warning(self, tr_ui("repo_settings.dlg_error", "Fehler"), msg)
            else:
                # Legacy fallback (only updates display name metadata)
                self.backend.set_meta("repertoire_display_name", new_name)
                self.refresh_info()

    def rename_level(self, item):
        # Column 0 is the index, do nothing.
        if item.column() == 0: return
        
        # Column 1 is the Designation
        if item.column() == 1:
            lvl_order = int(self.tbl_levels.item(item.row(), 0).text())
            old_name = item.text()
            new_name, ok = QInputDialog.getText(self, tr_ui("repo_settings.dlg_rename_level_title", "Level Umbenennen"), tr_ui("repo_settings.dlg_rename_level_prompt", "Neuer Name für dieses Level:"), QLineEdit.EchoMode.Normal, old_name)
            if ok and new_name and new_name != old_name:
                self.backend.update_level_name(lvl_order, new_name)
                self.refresh_info()

    def add_level(self):
        name, ok = QInputDialog.getText(self, "Level hinzufügen", "Name des neuen Levels:")
        if ok and name:
            self.backend.add_repertoire_level(name)
            self.refresh_info()
    
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
        
        # Only update labels that are still in "Laden" state
        if hasattr(self, "lbl_ana_status") and not sip.isdeleted(self.lbl_ana_status) and "Laden" in self.lbl_ana_status.text():
            self.lbl_ana_status.setText(text)
        if hasattr(self, "lbl_db_cov") and not sip.isdeleted(self.lbl_db_cov) and "Laden" in self.lbl_db_cov.text():
            self.lbl_db_cov.setText(text)

    def start_slow_stats_fetch(self):
        if not self.backend: return
        self.stats_loader = SingleRepoStatsWorker(self.backend)
        self.stats_loader.stats_ready.connect(self.on_stats_loaded)
        self.stats_loader.start()

    def on_stats_loaded(self, info):
        # Stop animation
        if self.loading_timer:
            self.loading_timer.stop()
            
        # Update the UI with final data
        if hasattr(self, "lbl_ana_status") and not sip.isdeleted(self.lbl_ana_status):
            self.lbl_ana_status.setText(info.get('depth', '-'))
            
        if hasattr(self, "lbl_db_cov") and not sip.isdeleted(self.lbl_db_cov):
            cov = info.get("coverage_pct", 0)
            elo_display = get_elo_display(info.get('elo', 'N/A'))
            self.lbl_db_cov.setText(f"{elo_display} [{cov:.1f}% Abdeckung]")

    def refresh_info(self, fast_only=False): 
        if not self.backend: return
        # First update backend data
        self.backend.scan_and_update_metadata()
        info = self.backend.get_repertoire_info(fast_only=fast_only)
        self.l_n.setText(info.get('name', 'Unbekannt'))
        self.txt_description.blockSignals(True)
        self.txt_description.setPlainText(info.get('description', ''))
        self.txt_description.blockSignals(False)
        
        elo = self.backend.get_meta("elo", "high").lower()
        self.combo_repertoire_elo.blockSignals(True)
        self.combo_repertoire_elo.setCurrentText(get_elo_display(elo))
        self.combo_repertoire_elo.blockSignals(False)
        
        color = self.backend.get_meta("color", "w")
        self.combo_repertoire_color.blockSignals(True)
        idx = self.combo_repertoire_color.findData(color)
        if idx >= 0: self.combo_repertoire_color.setCurrentIndex(idx)
        self.combo_repertoire_color.blockSignals(False)
        
        # Update extra info rows
        if fast_only:
            self.lbl_ana_status.setText(tr_ui("repo_settings.status_loading", "Laden..."))
            self.lbl_db_cov.setText(tr_ui("repo_settings.status_loading", "Laden..."))
        else:
            self.lbl_ana_status.setText(info.get('depth', '-'))
            cov = info.get("coverage_pct", 0)
            elo_display = get_elo_display(info.get('elo', 'N/A'))
            self.lbl_db_cov.setText(f"{elo_display} [{cov:.1f}% Abdeckung]")
        
        # Sync Lichess UI
        elo_display = get_elo_display(elo)
        if hasattr(self, 'lbl_lichess_target_elo'):
            self.lbl_lichess_target_elo.setText(tr_ui("repo_settings.target_elo_label", "Ziel-Elo: {elo}", elo=elo_display))
        if hasattr(self, 'btn_wipe_lichess'):
            self.btn_wipe_lichess.setText(tr_ui("repo_settings.btn_wipe_lichess", "🗑️ Lichess-Daten löschen (außer Elo [{elo}])", elo=elo_display))

        # Refresh Table
        self.tbl_levels.setRowCount(0)
        levels = self.backend.get_repertoire_levels()
        
        # Tools Level Combos
        self.combo_prio_target.clear()
        self.combo_global_level.clear()
        if hasattr(self, 'combo_prune_target_level'):
            self.combo_prune_target_level.clear()
            self.combo_prune_target_level.addItem(tr_ui("repo_settings.prune_all_levels", "Alle Level"), None)

        for idx, lvl in enumerate(levels):
            self.tbl_levels.insertRow(idx)
            order_item = QTableWidgetItem(str(lvl['order']))
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_levels.setItem(idx, 0, order_item)
            
            name_item = QTableWidgetItem(lvl['name'])
            name_item.setFont(QFont("Segoe UI", 13, QFont.Weight.Medium)) # Consistent size
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_levels.setItem(idx, 1, name_item)
            
            self.combo_prio_target.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
            self.combo_global_level.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
            if hasattr(self, 'combo_prune_target_level'):
                self.combo_prune_target_level.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
            
            spin = NoWheelSpinBox()
            spin.setRange(800, 4000)
            spin.setSingleStep(50)
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setStyleSheet("QSpinBox { border: none; background: transparent; font-size: 16px; font-weight: 500; } QSpinBox:focus { background: rgba(0,0,0,0.05); }")
            spin.setValue(int(lvl.get('target_elo') or 1500))
            spin.valueChanged.connect(lambda val, lo=lvl['order']: self.backend.update_level_elo(lo, val))
            self.tbl_levels.setCellWidget(idx, 2, spin)
            self.tbl_levels.setRowHeight(idx, scale(42))
            
        self._update_levels_table_height()

        # self._refresh_maintenance_repo_list()  <-- Lazy loaded now!
        if hasattr(self, "update_cover_preview"):
            self.update_cover_preview()

    def _update_levels_table_height(self):
        if not hasattr(self, "tbl_levels"): return
        self.tbl_levels.verticalHeader().setDefaultSectionSize(scale(42))
        header_h = self.tbl_levels.horizontalHeader().height()
        if header_h <= 0:
            header_h = scale(38)
        row_cnt = self.tbl_levels.rowCount()
        rows_h = 0
        for i in range(row_cnt):
            r_h = self.tbl_levels.rowHeight(i)
            rows_h += r_h if r_h > 0 else scale(42)
        total_h = header_h + rows_h + scale(6)
        self.tbl_levels.setFixedHeight(max(scale(80), total_h))



    def delete_repertoire_action(self):
        if QMessageBox.warning(self, tr_ui("repo_settings.dlg_delete_repo_title", "Löschen"), tr_ui("repo_settings.dlg_delete_repo_msg", "Repertoire wirklich unwiderruflich löschen?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.main_window.delete_repertoire_action()
            self.accept()

    def paste_pgn_dialog(self): self.main_window.paste_pgn_dialog()
    def import_pgn_file_dialog(self): self.main_window.import_pgn_file_dialog()
    
    def export_repertoire(self):
        d = ExportDialog(self.backend, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            fmt, scope, transpos_mode, max_l, lang = d.result_data
            start = self.main_window.board_widget.board.fen() if scope == "current" else None
            if fmt == "pgn":
                p = QProgressDialog(tr_ui("repo_settings.dlg_export_progress", "Exportiere..."), tr_ui("repo_settings.dlg_export_cancel", "Abbrechen"), 0, 0, self)
                pgn = self.backend.export_pgn(start, transpos_mode, lambda c: p.setValue(c) or p.wasCanceled(), max_l, language=lang)
                if pgn:
                    path, _ = QFileDialog.getSaveFileName(self, tr_ui("repo_settings.dlg_export_save_title", "Export Speichern"), f"{self.backend.active_repo_name}.pgn", "PGN Dateien (*.pgn)")
                    if path:
                        with open(path, "w", encoding="utf-8") as f: f.write(pgn)
                        QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_export_done", "Export abgeschlossen."))
            else:
                path, _ = QFileDialog.getSaveFileName(self, tr_ui("repo_settings.dlg_export_save_title", "Export Speichern"), f"{self.backend.active_repo_name}.db", "SQLite Datenbank (*.db)")
                if path:
                    s, m = self.backend.export_db(path, start)
                    (QMessageBox.information if s else QMessageBox.warning)(self, tr_ui("repo_settings.dlg_export_result_title", "Ergebnis"), m)

    def copy_repertoire_action(self):
        """Duplicates the current repertoire folder and its database."""
        old_name = self.backend.active_repo_name
        if not old_name: return
        
        new_name, ok = QInputDialog.getText(self, tr_ui("repo_settings.dlg_copy_title", "Kurs kopieren"), tr_ui("repo_settings.dlg_copy_prompt", "Name für die Kopie:"), QLineEdit.EchoMode.Normal, tr_ui("repo_settings.dlg_copy_suffix", "{name} - Kopie", name=old_name))
        if not (ok and new_name and new_name != old_name): return
        
        # Validate name
        if any(c in new_name for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, tr_ui("repo_settings.dlg_invalid_name_title", "Ungültiger Name"), tr_ui("repo_settings.dlg_invalid_name_msg", "Der Name enthält ungültige Zeichen."))
            return

        import shutil
        from opening_fenix.core.utils import get_repertoire_dir
        
        old_dir = get_repertoire_dir(old_name)
        new_dir = os.path.join(os.path.dirname(old_dir), new_name)
        
        if os.path.exists(new_dir):
            QMessageBox.warning(self, tr_ui("repo_settings.dlg_error", "Fehler"), tr_ui("repo_settings.dlg_repo_exists_msg", "Ein Repertoire mit diesem Namen existiert bereits."))
            return
            
        try:
            # 1. Copy folder
            shutil.copytree(old_dir, new_dir)
            
            # 2. Rename DB inside
            old_db = os.path.join(new_dir, f"{old_name}.db")
            new_db = os.path.join(new_dir, f"{new_name}.db")
            if os.path.exists(old_db):
                os.rename(old_db, new_db)
            
            # Also check for WAL/SHM files
            for ext in [".db-wal", ".db-shm"]:
                old_aux = os.path.join(new_dir, f"{old_name}{ext}")
                new_aux = os.path.join(new_dir, f"{new_name}{ext}")
                if os.path.exists(old_aux):
                    os.rename(old_aux, new_aux)

            QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_copy_done", "Repertoire wurde als '{name}' kopiert.\nDu kannst es jetzt über das Hauptmenü laden.", name=new_name))
        except Exception as e:
            QMessageBox.critical(self, tr_ui("repo_settings.dlg_copy_error_title", "Fehler beim Kopieren"), str(e))

    def prepare_full_course_export(self):
        # Implementation moved to method below for readability-ish
        self._prepare_full_course_export_logic()

    def _prepare_full_course_export_logic(self):
        repo_name = self.backend.active_repo_name
        if not repo_name: return
        repo_dir = get_repertoire_dir(repo_name)
        if not os.path.exists(repo_dir): os.makedirs(repo_dir, exist_ok=True)
        levels = self.backend.get_repertoire_levels()
        if not levels: return
        lang_sel, ok = QInputDialog.getItem(self, tr_ui("repo_settings.dlg_export_full_lang_title", "Sprache"), tr_ui("repo_settings.dlg_export_full_lang_prompt", "Notation für Export:"), [tr_ui("repo_settings.notation_standard", "Standard (English)"), tr_ui("repo_settings.notation_german", "Deutsch (S,D,L,K,T)")], 0, False)
        if not ok: return
        lang = "de" if lang_sel == tr_ui("repo_settings.notation_german", "Deutsch (S,D,L,K,T)") else "en"
        progress = QProgressDialog(tr_ui("repo_settings.dlg_export_progress", "Exportiere..."), tr_ui("repo_settings.dlg_export_cancel", "Abbrechen"), 0, len(levels), self)
        safe_repo_name = re.sub(r'[\\/*?:"<>|]', '_', repo_name)
        exported = []
        for i, lvl in enumerate(levels):
            if progress.wasCanceled(): break
            progress.setLabelText(f"L{lvl['order']}: {lvl['name']}...")
            pgn = self.backend.export_pgn(max_l=lvl['order'], transpos_mode=2, language=lang)
            if pgn:
                safe_lvl = re.sub(r'[\\/*?:"<>|]', '_', lvl['name'])
                fname = f"{safe_repo_name} L{lvl['order']}-{safe_lvl}.pgn"
                with open(os.path.join(repo_dir, fname), "w", encoding="utf-8") as f: f.write(pgn)
                exported.append(fname)
            progress.setValue(i + 1)
        if not progress.wasCanceled():
            self._create_export_readme(repo_dir, repo_name, levels, exported)
            QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), tr_ui("repo_settings.dlg_export_full_done", "Repertoire exportiert."))
            try: os.startfile(os.path.abspath(repo_dir))
            except: pass

    def _create_export_readme(self, repo_dir, repo_name, levels, files):
        info = self.backend.get_repertoire_info()
        color = "Weiß" if self.backend.get_repertoire_color() == 'w' else "Schwarz"
        date = datetime.datetime.now().strftime("%d.%m.%Y")
        content = f"# {repo_name}\n\n## Details\n- Farbe: {color}\n- Datum: {date}\n\n## Levels\n"
        for l in levels: content += f"- L{l['order']}: {l['name']}\n"
        with open(os.path.join(repo_dir, "README.md"), "w", encoding="utf-8") as f: f.write(content)

    def run_structure_repair(self): DiagnosticDialog(self.backend, self).exec(); self.refresh_info()
    def run_variation_name_repair(self):
        self.backend.reset_and_repair_variation_names()
        QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), tr_ui("repo_settings.dlg_variation_names_recalculated", "Variantennamen wurden erfolgreich neu berechnet."))
    def browse_engine_path(self):
        p, _ = QFileDialog.getOpenFileName(self, "Engine", "", "*.exe")
        if p: self.txt_engine_path.setText(p); self.main_window.config["engine_path"] = p; self.main_window.save_config()

    def start_analysis(self):
        if hasattr(self, 'w_eng') and self.w_eng is not None and self.w_eng.isRunning():
            self.l_eng_status.setText(tr_ui("repo_settings.dlg_engine_stopping", "Engine-Analyse wird gestoppt..."))
            if hasattr(self, 'btn_start_eng') and self.btn_start_eng is not None:
                self.btn_start_eng.setEnabled(False)
                self.btn_start_eng.setText(tr_ui("repo_settings.btn_stopping_scan", "⏳ Stoppe..."))
            self.w_eng.cancel()
            return

        ep = self.txt_engine_path.text()
        if not ep or not os.path.exists(ep):
            QMessageBox.warning(self, tr_ui("repo_settings.dlg_engine_missing_title", "Engine fehlt"), tr_ui("repo_settings.dlg_engine_missing_msg", "Bitte konfiguriere zuerst einen gültigen Engine-Pfad."))
            return

        self.w_eng = AnalysisThread(self.backend.active_repo_name, self.s_d.value(), int(self.c_threads.currentText()), ep)
        self.pb_eng.setRange(0, 100)
        self.pb_eng.setValue(0)
        self.w_eng.progress_signal.connect(self.pb_eng.setValue)
        
        def on_finished(success, message):
            try:
                if not sip.isdeleted(self):
                    if hasattr(self, 'btn_start_eng') and self.btn_start_eng is not None:
                        self.btn_start_eng.setEnabled(True)
                        self.btn_start_eng.setText(tr_ui("repo_settings.btn_start_scan", "🚀 Engine-Scan starten"))
                        self.btn_start_eng.setStyleSheet("")
                    self.l_eng_status.setText(message)
                    if success:
                        QMessageBox.information(self, tr_ui("repo_settings.dlg_engine_done_title", "Engine-Analyse fertig"), message)
                    else:
                        if "abgebrochen" in message.lower() or "canceled" in message.lower() or "cancelled" in message.lower() or "stopp" in message.lower():
                            QMessageBox.information(self, tr_ui("repo_settings.dlg_engine_stopped_title", "Engine-Analyse gestoppt"), message)
                        else:
                            QMessageBox.warning(self, tr_ui("repo_settings.dlg_engine_error_title", "Engine-Analyse Fehler"), message)
            except: pass
            
        self.w_eng.finished_signal.connect(on_finished)
        self.w_eng.start()

        if hasattr(self, 'btn_start_eng') and self.btn_start_eng is not None:
            self.btn_start_eng.setEnabled(True)
            self.btn_start_eng.setText(tr_ui("repo_settings.btn_stop_scan", "🛑 Engine-Scan stoppen"))
            self.btn_start_eng.setStyleSheet(f"background-color: {COLORS['error_red']}; color: white; font-weight: bold;")

        self.l_eng_status.setText(tr_ui("repo_settings.dlg_engine_running", "Engine Analyse läuft..."))

    def on_token_changed(self, text): self.main_window.config["lichess_token"] = text; self.main_window.save_config()

    def start_fetch(self):
        if hasattr(self, 'w_lich') and self.w_lich is not None and self.w_lich.isRunning():
            self.l_lich_status.setText(tr_ui("repo_settings.dlg_lichess_stopping", "Lichess Import wird gestoppt..."))
            if hasattr(self, 'btn_fetch') and self.btn_fetch is not None:
                self.btn_fetch.setEnabled(False)
                self.btn_fetch.setText(tr_ui("repo_settings.btn_stopping_fetch", "⏳ Stoppe..."))
            self.w_lich.cancel()
            return

        # Use repertoire-specific Elo category instead of global config
        target_elo_display = self.combo_repertoire_elo.currentText()
        target_elo = get_elo_internal(target_elo_display)
        self.w_lich = LichessImportThread(self.backend.active_repo_name, target_elo)
        self.pb_lich.setRange(0, 100)
        self.pb_lich.setValue(0)
        self.w_lich.progress_signal.connect(self.pb_lich.setValue)
        
        def on_finished(success, message):
            try:
                if not sip.isdeleted(self):
                    if hasattr(self, 'btn_fetch') and self.btn_fetch is not None:
                        self.btn_fetch.setEnabled(True)
                        self.btn_fetch.setText(tr_ui("repo_settings.btn_fetch", "📡 Daten laden && Scores berechnen"))
                        self.btn_fetch.setStyleSheet("")
                    self.l_lich_status.setText(message)
                    if success:
                        QMessageBox.information(self, tr_ui("repo_settings.dlg_lichess_done_title", "Lichess Import fertig"), message)
                    else:
                        if "abgebrochen" in message.lower() or "canceled" in message.lower() or "cancelled" in message.lower() or "stopp" in message.lower():
                            QMessageBox.information(self, tr_ui("repo_settings.dlg_lichess_stopped_title", "Lichess Import gestoppt"), message)
                        else:
                            QMessageBox.warning(self, tr_ui("repo_settings.dlg_lichess_error_title", "Lichess Import Fehler"), message)
            except: pass
                
        self.w_lich.finished_signal.connect(on_finished)
        self.w_lich.start()

        if hasattr(self, 'btn_fetch') and self.btn_fetch is not None:
            self.btn_fetch.setEnabled(True)
            self.btn_fetch.setText(tr_ui("repo_settings.btn_stop_fetch", "🛑 Import stoppen"))
            self.btn_fetch.setStyleSheet(f"background-color: {COLORS['error_red']}; color: white; font-weight: bold;")

        self.l_lich_status.setText(tr_ui("repo_settings.dlg_lichess_running", "Lichess Daten werden geladen..."))


    def delete_lichess_action(self):
        from PyQt6.QtWidgets import QMessageBox
        target_elo_display = self.combo_repertoire_elo.currentText()
        target_elo = get_elo_internal(target_elo_display)
        ans = QMessageBox.question(self, tr_ui("repo_settings.dlg_lichess_delete_title", "Löschen"), tr_ui("repo_settings.dlg_lichess_delete_msg", "Sollen alle Lichess-Daten für '{elo}' wirklich gelöscht werden?", elo=target_elo_display))
        if ans == QMessageBox.StandardButton.Yes:
            from opening_fenix.core.db.database import DatabaseManager
            from opening_fenix.core.db.models import LichessData
            from opening_fenix.core.utils import get_repertoire_db_path
            
            db_path = get_repertoire_db_path(self.backend.active_repo_name)
            db = DatabaseManager(db_path)
            try:
                session = db.get_session()
                count = session.query(LichessData).filter(LichessData.elo_range == target_elo).delete(synchronize_session=False)
                session.commit()
                session.close()
                db.close()
                QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_lichess_deleted", "{count} Einträge für '{elo}' gelöscht.", count=count, elo=target_elo_display))
                self.refresh_info()
            except Exception as e:
                QMessageBox.critical(self, tr_ui("repo_settings.dlg_error", "Fehler"), tr_ui("repo_settings.dlg_lichess_delete_error", "Löschen fehlgeschlagen: {error}", error=e))

    
    def wipe_other_lichess_data_action(self):
        """Deletes Lichess data from the database for all Elo categories except the current one."""
        target_elo_display = self.combo_repertoire_elo.currentText()
        target_elo = get_elo_internal(target_elo_display)
        confirm = QMessageBox.question(self, tr_ui("repo_settings.dlg_wipe_lichess_title", "Bereinigen"), 
            tr_ui("repo_settings.dlg_wipe_lichess_msg", "Möchtest du wirklich alle Lichess-Daten löschen, die NICHT für '{elo}' sind?\nDies spart Speicherplatz.", elo=target_elo_display),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                db_path = get_repertoire_db_path(self.backend.active_repo_name)
                from opening_fenix.core.db.database import DatabaseManager
                from opening_fenix.core.db.models import LichessData
                db = DatabaseManager(db_path)
                session = db.get_session()
                count = session.query(LichessData).filter(LichessData.elo_range != target_elo).delete(synchronize_session=False)
                session.commit()
                session.close()
                db.close()
                QMessageBox.information(self, tr_ui("repo_settings.dlg_success", "Erfolg"), tr_ui("repo_settings.dlg_wipe_lichess_done", "Bereinigung abgeschlossen. {count} Einträge wurden gelöscht.", count=count))
            except Exception as e:
                QMessageBox.critical(self, tr_ui("repo_settings.dlg_error", "Fehler"), tr_ui("repo_settings.dlg_wipe_lichess_error", "Bereinigung fehlgeschlagen: {error}", error=e))

    def on_stats_ready(self, row, status, coverage, elo):
        # Update Analysis Status
        it_ana = QTableWidgetItem(status)
        it_ana.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.main_table.setItem(row, 3, it_ana)
        
        # Update Coverage
        it_cov = QTableWidgetItem(f"{coverage:.1f}%")
        it_cov.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.main_table.setItem(row, 4, it_cov)
        
        # Update Prio Elo (which is "Laden..." initially)
        it_elo = QTableWidgetItem(get_elo_display(elo))
        it_elo.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.main_table.setItem(row, 2, it_elo)

    def start_centralized_maintenance(self):
        if hasattr(self, 'm_thread') and self.m_thread is not None and self.m_thread.isRunning():
            self.lbl_m_overall.setText(tr_ui("repo_settings.dlg_maintenance_stopping", "Wartung wird gestoppt..."))
            if hasattr(self, 'btn_m_start') and self.btn_m_start is not None:
                self.btn_m_start.setEnabled(False)
                self.btn_m_start.setText(tr_ui("repo_settings.btn_stopping_batch", "⏳ Stoppe..."))
            self.m_thread.cancel()
            return

        # Implementation of centralized maintenance batch
        import multiprocessing
        configs = []
        for row in range(self.main_table.rowCount()):
            cb_item = self.main_table.cellWidget(row, 0)
            if cb_item and cb_item.isChecked():
                repo_name = self.main_table.item(row, 1).text()
                prio_elo_display = self.main_table.item(row, 2).text().split(" [")[0] # Strip potential coverage info
                prio_elo = get_elo_internal(prio_elo_display)
                configs.append({'name': repo_name, 'elo': prio_elo})
        
        if not configs:
            QMessageBox.warning(self, tr_ui("repo_settings.dlg_maintenance_title", "Wartung"), tr_ui("repo_settings.dlg_select_at_least_one_repo", "Bitte wähle mindestens ein Repertoire aus."))
            return

        tasks = {
            'engine': self.chk_m_engine.isChecked(), 
            'lichess': self.chk_m_lichess.isChecked(), 
            'cleanup': self.chk_m_cleanup_lichess.isChecked(),
            'stats': self.chk_m_stats.isChecked()
        }
        
        settings = {
            'depth': self.spin_m_depth.value(), 
            'threads': self.spin_m_threads.value(), 
            'path': self.main_window.config.get("engine_path", "")
        }
        
        self.m_thread = MaintenanceThread(configs, tasks, settings)
        self.pb_m_overall.setRange(0, len(configs))
        self.pb_m_overall.setValue(0)
        self.lbl_m_overall.setText(f"Starte Wartung für {len(configs)} Repertoires...")
        
        self.m_thread.overall_progress_signal.connect(self.on_m_overall_progress)
        self.m_thread.repo_status_signal.connect(self.on_m_repo_status)
        self.m_thread.finished_signal.connect(self.on_m_finished)
        self.m_thread.start()

        if hasattr(self, 'btn_m_start') and self.btn_m_start is not None:
            self.btn_m_start.setEnabled(True)
            self.btn_m_start.setText(tr_ui("repo_settings.btn_stop_batch", "🛑 Wartungs-Batch stoppen"))
            self.btn_m_start.setStyleSheet(f"background-color: {COLORS['error_red']}; color: white; font-weight: bold;")

    def on_m_overall_progress(self, current, total, name):
        if sip.isdeleted(self) or not hasattr(self, "pb_m_overall"): return
        self.pb_m_overall.setRange(0, total)
        self.pb_m_overall.setValue(current)
        self.lbl_m_overall.setText(f"Gesamtfortschritt ({current}/{total}): {name} abgeschlossen")

    def on_m_repo_status(self, name, task, prog, status):
        if sip.isdeleted(self) or not hasattr(self, "main_table"): return
        for row in range(self.main_table.rowCount()):
            name_item = self.main_table.item(row, 1)
            if name_item and name_item.text() == name:
                pb = self.main_table.cellWidget(row, 5)
                if isinstance(pb, QProgressBar):
                    pb.setValue(prog)
                    # Translate internal task names for UI
                    task_display = {
                        'engine': 'Analyse',
                        'lichess': 'Lichess',
                        'cleanup': 'Cleanup',
                        'stats': 'Statistiken'
                    }.get(task, task)
                    pb.setFormat(f"{task_display}: %p% ({status})")
                break

    def on_m_finished(self, success, message):
        if sip.isdeleted(self): return
        if hasattr(self, 'btn_m_start') and self.btn_m_start is not None:
            self.btn_m_start.setEnabled(True)
            self.btn_m_start.setText(tr_ui("repo_settings.btn_start_batch", "🚀 Wartungs-Batch starten"))
            self.btn_m_start.setStyleSheet("")
        self.lbl_m_overall.setText(f"Wartung beendet: {message}")
        if success:
            QMessageBox.information(self, tr_ui("repo_settings.dlg_maintenance_center_title", "Wartung Center"), tr_ui("repo_settings.dlg_batch_completed_success", "Die Stapelverarbeitung wurde erfolgreich abgeschlossen."))
        else:
            if "abgebrochen" in message.lower() or "canceled" in message.lower() or "cancelled" in message.lower() or "stopp" in message.lower():
                QMessageBox.information(self, tr_ui("repo_settings.dlg_maintenance_center_title", "Wartung Center"), tr_ui("repo_settings.dlg_maintenance_stopped", "Wartung gestoppt: {message}", message=message))
            else:
                QMessageBox.warning(self, tr_ui("repo_settings.dlg_maintenance_center_title", "Wartung Center"), tr_ui("repo_settings.dlg_maintenance_ended_with_errors", "Wartung beendet mit Fehlern:\n{message}", message=message))
        self.refresh_info()

    def _select_all_maintenance_repos(self, checked):
        for row in range(self.main_table.rowCount()):
            cb_item = self.main_table.cellWidget(row, 0)
            if cb_item: cb_item.setChecked(checked)

    def _refresh_maintenance_repo_list(self):
        self.main_table.setRowCount(0)
        from opening_fenix.core.services.maintenance_service import list_all_repertoires
        all_repos = list_all_repertoires()
        self.main_table.setRowCount(len(all_repos))
        
        worker_data = []
        for row, r in enumerate(all_repos):
            # Checkbox
            cb = QCheckBox(); cb.setChecked(True)
            self.main_table.setCellWidget(row, 0, cb)
            
            # Name
            it_name = QTableWidgetItem(r['name'])
            it_name.setFlags(Qt.ItemFlag.ItemIsEnabled) # No selection
            self.main_table.setItem(row, 1, it_name)
            
            # Prio Elo
            it_elo = QTableWidgetItem(get_elo_display(r['elo']))
            it_elo.setFlags(Qt.ItemFlag.ItemIsEnabled) # No selection
            self.main_table.setItem(row, 2, it_elo)
            
            # Placeholders
            it_ana = QTableWidgetItem(tr_ui("repo_settings.status_loading", "Laden..."))
            it_ana.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.main_table.setItem(row, 3, it_ana)
            
            it_cov = QTableWidgetItem(tr_ui("repo_settings.status_loading", "Laden..."))
            it_cov.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.main_table.setItem(row, 4, it_cov)

            pb = QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(0)
            pb.setTextVisible(True)
            pb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pb.setFormat("Wartend...")
            pb.setStyleSheet("""
                QProgressBar {
                    border: 1px solid rgba(0,0,0,0.1);
                    border-radius: 4px;
                    background: rgba(0,0,0,0.05);
                    text-align: center;
                    color: #2c3e50;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background-color: #2ecc71;
                    border-radius: 3px;
                }
            """)
            self.main_table.setCellWidget(row, 5, pb)
            
            worker_data.append({'row': row, 'name': r['name']})

        # Start stats background worker
        self.stats_worker = RepertoireStatsWorker(worker_data)
        self.stats_worker.stats_ready.connect(self.on_stats_ready)
        self.stats_worker.start()
    def run_lichess_orphan_cleanup(self):
        count = self.backend.cleanup_orphaned_lichess_data()
        if count > 0:
            QMessageBox.information(self, tr_ui("repo_settings.dlg_orphan_cleanup_title", "Bereinigung fertig"), tr_ui("repo_settings.dlg_orphan_cleanup_done", "Erfolgreich {count} verwaiste Lichess-Einträge gelöscht.", count=count))
        else:
            QMessageBox.information(self, tr_ui("repo_settings.dlg_orphan_cleanup_title", "Bereinigung fertig"), tr_ui("repo_settings.dlg_orphan_cleanup_empty", "Keine verwaisten Lichess-Daten gefunden."))
        self.refresh_info()

    def closeEvent(self, event):
        """Clean up background threads and timers before closing."""
        if self.loading_timer:
            self.loading_timer.stop()

        workers = [
            getattr(self, 'stats_worker', None),
            getattr(self, 'w_eng', None),
            getattr(self, 'w_lich', None),
            getattr(self, 'm_thread', None),
            getattr(self, 'stats_loader', None)
        ]
        
        for w in workers:
            if w and w.isRunning():
                try: w.disconnect()
                except: pass
                
                if hasattr(w, 'stop'): w.stop()
                if hasattr(w, 'cancel'): w.cancel()
                w.requestInterruption()
                w.wait()
                    
        super().closeEvent(event)
