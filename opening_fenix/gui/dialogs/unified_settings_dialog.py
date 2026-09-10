import os
import re
import json
import datetime
import multiprocessing
from typing import Optional, Dict, Any

from PyQt6 import sip
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QFormLayout, QComboBox, 
    QLabel, QScrollArea, QFrame, QGroupBox, QSpinBox, QDoubleSpinBox, 
    QPushButton, QCheckBox, QProgressBar, QSlider, QLineEdit, QFileDialog, 
    QMessageBox, QStackedWidget, QTextEdit, QPlainTextEdit, QGridLayout, 
    QApplication, QAbstractButton, QSizePolicy, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QTableWidget, QTableWidgetItem, QProgressDialog, QRadioButton,
    QInputDialog
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread, QEvent
from PyQt6.QtGui import QIcon, QFont, QPixmap, QPainter, QPainterPath, QColor, QBrush
from PyQt6.QtCore import QRectF

from opening_fenix.core.version import APP_VERSION
from opening_fenix.core.data_tools import (
    get_base_path, get_user_dir, get_default_user_dir, get_custom_data_dir, 
    set_custom_data_dir, migrate_user_data, get_meta, set_meta,
    copy_repertoire_comments
)
from opening_fenix.core.utils import (
    get_repertoire_db_path, get_repertoire_dir, get_elo_display, get_elo_internal,
    get_repertoire_comment_stats, ELO_DISPLAY_MAP,
    get_last_active_profile_name, is_free_training_profile
)
from opening_fenix.core.translation import tr_ui, tr_widget, translator, escape_mnemonic
from opening_fenix.core.services.repertoire_core_service import (
    RepertoireService, fetch_repertoire_info, fetch_repertoire_levels
)
from opening_fenix.core.services.backup_service import (
    create_repertoire_backup, list_repertoire_backups, restore_repertoire_from_backup
)
from opening_fenix.core.services.maintenance_service import list_all_repertoires
from opening_fenix.core.services.update_service import (
    UpdateCheckWorker, get_config_dict, save_config_dict,
    get_last_update_check_time, update_signals
)
from opening_fenix.core.threads import (
    AnalysisThread, LichessImportThread, MaintenanceThread, RepertoireStatsWorker
)
from opening_fenix.gui.widgets.board_widget import THEMES, HIGHLIGHT_COLORS
from opening_fenix.gui.widgets.common import AutoAdjustButton
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
from opening_fenix.gui.styles import COLORS, get_bw_glass_style, set_consistent_icon
from opening_fenix.gui.scaling import scale


# ─── Common Helper Widgets ──────────────────────────────────────────────────

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

class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(scale(44), scale(22))
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        brush_color = QColor("#111111") if self.isChecked() else QColor("#d1d1d6")
        painter.setBrush(QBrush(brush_color))
        painter.setPen(Qt.PenStyle.NoPen)
        
        rect = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2.0
        painter.drawRoundedRect(rect, radius, radius)
        
        knob_color = QColor("white")
        painter.setBrush(QBrush(knob_color))
        
        margin = scale(2)
        knob_size = self.height() - (margin * 2)
        x = self.width() - knob_size - margin if self.isChecked() else margin
        knob_rect = QRectF(x, margin, knob_size, knob_size)
        painter.drawEllipse(knob_rect)


class TrainerRepoStatsWorker(QThread):
    stats_ready = pyqtSignal(dict)

    def __init__(self, main_window, repo_name):
        super().__init__()
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
            try: session.close()
            except Exception: pass
            try: db_manager.close()
            except Exception: pass


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
        
        self.levels_elo_map = {}

        self.elo_row = QWidget()
        self.elo_layout = QHBoxLayout(self.elo_row)
        self.elo_layout.setContentsMargins(0, 0, 0, 0)
        self.elo_layout.setSpacing(scale(8))
        
        self.lbl_elo = QLabel("🎓 1500 Elo")
        self.lbl_elo.setObjectName("RepoElo")
        self.lbl_elo.setStyleSheet(f"font-size: {scale(13)}px;")
        self.elo_layout.addWidget(self.lbl_elo)
        
        self.btn_toggle = ToggleSwitch()
        self.btn_toggle.setChecked(self.is_active)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle_active)
        self.elo_layout.addWidget(self.btn_toggle)
        self.elo_layout.addStretch()
        self.info_layout.addWidget(self.elo_row)
        
        self.combo_level = NoWheelComboBox()
        self.combo_level.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_level.setMinimumWidth(scale(120))
        self.combo_level.setFixedHeight(scale(35))
        self.populate_levels()
        self.lbl_elo.setText(f"🎓 {self.get_selected_level_elo()} Elo")
        self.combo_level.currentIndexChanged.connect(self.on_level_changed)
        self.info_layout.addWidget(self.combo_level)
        
        self.layout.addWidget(self.info_widget, 1)
        
        self.lbl_elo.setVisible(self.is_active)
        self.combo_level.setVisible(self.is_active)
        
        if self.is_active:
            self.setMinimumHeight(scale(130))
            self.setMaximumHeight(scale(160))
        else:
            self.setMinimumHeight(scale(64))
            self.setMaximumHeight(scale(75))

    def get_selected_level_elo(self):
        level = self.combo_level.currentData() if hasattr(self, 'combo_level') else None
        if level is None and self.main_window and hasattr(self.main_window, 'training_manager'):
            level = self.main_window.training_manager.get_active_level(self.repo_name)
        if hasattr(self, 'levels_elo_map') and level in self.levels_elo_map:
            return self.levels_elo_map[level]
        return 1500

    def populate_levels(self):
        from opening_fenix.core.db.database import DatabaseManager
        self.levels_elo_map = {}
        db_path = get_repertoire_db_path(self.repo_name)
        if not os.path.exists(db_path):
            return
        db_manager = DatabaseManager(db_path)
        session = db_manager.get_session()
        try:
            levels = fetch_repertoire_levels(session)
            active_lvl = 1
            if self.main_window and hasattr(self.main_window, 'training_manager'):
                active_lvl = self.main_window.training_manager.get_active_level(self.repo_name)

            self.combo_level.blockSignals(True)
            self.combo_level.clear()
            for lvl in levels:
                lvl_order = lvl['order']
                self.levels_elo_map[lvl_order] = int(lvl.get('target_elo') or 1500)
                self.combo_level.addItem(f"Lvl {lvl_order}: {lvl['name']}", lvl_order)
            
            idx = self.combo_level.findData(active_lvl)
            if idx != -1: self.combo_level.setCurrentIndex(idx)
            self.combo_level.blockSignals(False)
        finally:
            session.close()
            db_manager.close()

    def toggle_active(self):
        self.is_active = not self.is_active
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
        
        if self.main_window and hasattr(self.main_window, 'training_manager'):
            self.main_window.training_manager.set_repo_visibility(self.repo_name, self.is_active)
            if hasattr(self.main_window, 'refresh_repertoire_buttons'):
                self.main_window.refresh_repertoire_buttons()
        self.update_style()
        self.clicked.emit()
        self.parent_dlg.refresh_trainer_repertoire_cards()

    def on_level_changed(self):
        level = self.combo_level.currentData()
        if level is not None and self.main_window and hasattr(self.main_window, 'training_manager'):
            self.main_window.training_manager.set_active_level(level, self.repo_name)
            self.lbl_elo.setText(f"🎓 {self.get_selected_level_elo()} Elo")

    def update_style(self):
        is_selected = (hasattr(self.parent_dlg, "selected_trainer_repo") and self.parent_dlg.selected_trainer_repo == self.repo_name)
        if self.is_active:
            bg = "white"
            border = "2px solid #3e2723" if is_selected else "1px solid rgba(0, 0, 0, 0.12)"
            cover_bg = "white"
            text_color = "#111111"
        else:
            bg = "rgba(0,0,0,0.03)"
            border = "2px dashed #3e2723" if is_selected else "1px solid rgba(0, 0, 0, 0.08)"
            cover_bg = "transparent"
            text_color = "#555555"

        if hasattr(self, 'lbl_cover'):
            self.lbl_cover.setStyleSheet(f"border: 1px solid rgba(0, 0, 0, 0.1); border-radius: {scale(6)}px; background: {cover_bg};")
        if hasattr(self, 'info_widget'):
            self.info_widget.setStyleSheet("background: transparent;")
        if hasattr(self, 'elo_row'):
            self.elo_row.setStyleSheet("background: transparent;")

        self.setStyleSheet(f"""
            RepertoireConfigCard {{
                background-color: {bg};
                border: {border};
                border-radius: {scale(12)}px;
            }}
            RepertoireConfigCard QWidget {{
                background: transparent;
            }}
            QLabel#RepoName {{ 
                color: {text_color};
                font-weight: 700;
                background: transparent;
            }}
            QLabel#RepoElo {{ 
                color: #555555;
                background: transparent;
            }}
            QComboBox {{
                background-color: #fbfbfb;
                color: #111111;
                border: 1px solid rgba(0, 0, 0, 0.14);
                border-radius: {scale(8)}px;
                padding-left: {scale(10)}px;
                padding-right: {scale(26)}px;
                font-weight: 500;
            }}
        """)

    def mousePressEvent(self, event):
        child = self.childAt(event.position().toPoint())
        if child and (child == self.combo_level or self.combo_level.isAncestorOf(child) or child == self.btn_toggle):
            super().mousePressEvent(event)
            return
        
        self.parent_dlg.selected_trainer_repo = self.repo_name
        self.parent_dlg.on_trainer_repo_selected(self.repo_name)
        self.parent_dlg.update_trainer_card_selection_highlights()
        self.clicked.emit()
        super().mousePressEvent(event)


# ─── Diagnostic & Delete Level Dialogs (Preserved from RepoSettingsDialog) ─

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
        self.btn_repair = QPushButton(tr_widget("repo_settings.btn_repair_issues", "🔧 Probleme beheben"))
        self.btn_repair.setProperty("class", "Primary")
        self.btn_repair.clicked.connect(self.repair)
        self.btn_repair.setEnabled(False)
        self.btn_repair.setVisible(False)
        
        btn_close = QPushButton(tr_widget("repo_settings.btn_close", "Schließen"))
        btn_close.clicked.connect(self.accept)
        
        h_btn.addStretch()
        h_btn.addWidget(btn_close)
        h_btn.addWidget(self.btn_repair)
        layout.addLayout(h_btn)

    def run_diagnostic(self):
        self.issues = self.backend.run_diagnostic()
        msg = tr_ui("repo_settings.diag_result_title", "<h3 style='margin-bottom: 10px;'>Diagnose-Ergebnis:</h3>")
        has_issues = False
        
        if self.issues['schema']:
            msg += tr_ui("repo_settings.diag_schema_outdated", "<p style='color: #e74c3c;'><b>⚠️ Veraltetes Datenbankschema</b><br>Fehlende Spalten: {cols}</p>", cols=', '.join(self.issues['schema']))
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_schema_ok", "<p style='color: #27ae60;'><b>✅ Datenbankschema</b><br>Das Schema ist aktuell.</p>")
            
        if self.issues['gaps'] > 0:
            msg += tr_ui("repo_settings.diag_gaps_warn", "<p style='color: #e74c3c;'><b>⚠️ Zug-Lücken</b><br>{count} fehlende Repertoire-Links gefunden.</p>", count=self.issues['gaps'])
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_gaps_ok", "<p style='color: #27ae60;'><b>✅ Zug-Kette</b><br>Keine Lücken gefunden.</p>")
            
        if self.issues['duplicates'] > 0:
            msg += tr_ui("repo_settings.diag_dups_warn", "<p style='color: #e74c3c;'><b>⚠️ FEN-Duplikate</b><br>{count} doppelte Stellungen gefunden.</p>", count=self.issues['duplicates'])
            has_issues = True
        else:
            msg += tr_ui("repo_settings.diag_dups_ok", "<p style='color: #27ae60;'><b>✅ Eindeutigkeit</b><br>Keine FEN-Duplikate gefunden.</p>")
            
        if self.issues.get('orphans', 0) > 0:
            msg += tr_ui("repo_settings.diag_orphans_info", "<p style='color: #f39c12;'><b>ℹ️ Isolierte Stellungen</b><br>{count} Stellungen sind nicht erreichbar.</p>", count=self.issues['orphans'])
        else:
            msg += tr_ui("repo_settings.diag_orphans_ok", "<p style='color: #27ae60;'><b>✅ Erreichbarkeit</b><br>Alle Stellungen sind verknüpft.</p>")

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
        self.lbl_info.setText(tr_ui("repo_settings.diag_repair_finished", "Reparatur fertig! ✅"))
        if hasattr(self.parent(), 'refresh_creator_info'):
            self.parent().refresh_creator_info()


class DeleteLevelDialog(QDialog):
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
        layout.addWidget(lbl_prompt)

        form = QFormLayout()
        form.setSpacing(scale(10))
        self.combo_del = NoWheelComboBox()
        for lvl in self.levels:
            self.combo_del.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])

        if self.default_del_order:
            idx = self.combo_del.findData(self.default_del_order)
            if idx >= 0: self.combo_del.setCurrentIndex(idx)

        form.addRow(tr_ui("repo_settings.delete_level_select_del", "Zu löschendes Level:"), self.combo_del)

        self.g_mode = QGroupBox(tr_widget("repo_settings.delete_level_mode_group", "Aktion für enthaltene Züge:"))
        v_mode = QVBoxLayout(self.g_mode)
        self.radio_reassign = QRadioButton(tr_widget("repo_settings.delete_level_mode_reassign", "Züge in ein anderes Level verschieben"))
        self.radio_delete_moves = QRadioButton(tr_widget("repo_settings.delete_level_mode_delete_moves", "Alle Züge in diesem Level unwiderruflich löschen"))
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
        btn_cancel = QPushButton(tr_widget("login.cancel", "Abbrechen"))
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(tr_widget("repo_settings.btn_delete_level", "🗑️ Level löschen"))
        btn_ok.setProperty("class", "Danger")
        btn_ok.clicked.connect(self.accept)
        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(btn_ok)
        layout.addLayout(h_btn)

    def _on_mode_toggled(self):
        self.combo_target.setEnabled(not self.radio_delete_moves.isChecked())

    def _update_target_combo(self):
        self.combo_target.clear()
        del_order = self.combo_del.currentData()
        max_order = max((lvl['order'] for lvl in self.levels), default=0)
        is_highest = (del_order == max_order)
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


class _SidebarItemCompat:
    def __init__(self, text):
        self._text = text
    def text(self):
        return self._text

class _SidebarCompat(QWidget):
    def __init__(self, dialog, is_creator=False):
        super().__init__(dialog)
        self.setObjectName("Sidebar")
        self.dialog = dialog
        self.is_creator = is_creator
        if is_creator:
            self._items = [
                _SidebarItemCompat("📋 Repertoire Identität"),
                _SidebarItemCompat("🎨 Design & Tabs"),
                _SidebarItemCompat("📥 Import & Export"),
                _SidebarItemCompat("🧠 Analyse & Engine"),
                _SidebarItemCompat("🔧 Tools & Filter"),
                _SidebarItemCompat("🚜 Batch Wartungs-Center"),
                _SidebarItemCompat("🔄 Software-Updates")
            ]
        else:
            self._items = [
                _SidebarItemCompat("🎨 Darstellung & Audio"),
                _SidebarItemCompat("🎯 Trainings-Verhalten"),
                _SidebarItemCompat("📂 Repertoire-Konfiguration"),
                _SidebarItemCompat("🔄 Software-Updates"),
                _SidebarItemCompat("❓ FAQ")
            ]
        self.hide()

    def count(self):
        return len(self._items)

    def item(self, idx):
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return _SidebarItemCompat("")

    def currentRow(self):
        return self.dialog.pages.currentIndex() if hasattr(self.dialog, 'pages') else 0

    def setCurrentRow(self, row):
        if hasattr(self.dialog, 'pages') and 0 <= row < self.dialog.pages.count():
            self.dialog.pages.setCurrentIndex(row)
        if hasattr(self.dialog, 'main_scroll') and self.dialog.main_scroll:
            self.dialog.main_scroll.verticalScrollBar().setValue(0)


# ─── Unified Settings Dialog ────────────────────────────────────────────────

TRAINER_SETTINGS_KEYS = {
    "interval_preset",
    "custom_intervals",
    "alternate_move_policy",
    "queue_priority_order",
    "max_new_cards_per_day",
    "max_reviews_per_session",
    "enforce_limit_after_variation",
    "auto_delay"
}


class UnifiedSettingsDialog(QDialog):
    """
    Central, consolidated settings dialog with a hierarchical, collapsible sidebar navigation.
    Replaces both SettingsDialog (Trainer) and RepoSettingsDialog (Creator).
    """
    def __init__(self, parent=None, backend=None, initial_section: str = "trainer"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        set_consistent_icon(self)
        
        self.main_window = parent
        self.backend = backend
        self._owned_backend = None
        self.initial_section = initial_section
        
        # Determine active profile name
        self.profile_name = "Default"
        if self.main_window:
            if getattr(self.main_window, 'profile_name', None):
                self.profile_name = self.main_window.profile_name
            elif getattr(self.main_window, 'training_manager', None) and getattr(self.main_window.training_manager, 'profile_name', None):
                self.profile_name = self.main_window.training_manager.profile_name
        
        if not self.profile_name or self.profile_name == "Default":
            self.profile_name = get_last_active_profile_name()

        # Load standalone profile settings dictionary if no active training manager is attached
        self.profile_settings = self._load_profile_settings(self.profile_name)

        display_profile = tr_ui("login.free_training", "Freies Training") if is_free_training_profile(self.profile_name) else self.profile_name
        if self.initial_section == "creator":
            repo_name = getattr(self.backend, 'active_repo_name', None) if self.backend else None
            self.setWindowTitle(tr_ui("settings.unified_window_title_creator", "Creator-Einstellungen – Opening Fenix ({repo})", repo=repo_name or "Repertoire"))
        else:
            self.setWindowTitle(tr_ui("settings.unified_window_title_trainer", "Trainer-Einstellungen – Opening Fenix ({profile})", profile=display_profile))
        self.setMinimumSize(scale(1180), scale(760))
        self.resize(scale(1260), scale(820))
        self.setStyleSheet(get_bw_glass_style())
        
        if QApplication.instance():
            QApplication.instance().aboutToQuit.connect(self.reject)
            
        self.maintenance_loaded = False
        self.stats_loader = None
        self.loading_dots = 0
        self.loading_timer = None
        self.selected_trainer_repo = None

        self.init_ui()
        self.navigate_initial_section(self.initial_section)

        # Compatibility aliases for legacy code and test suites
        self.sidebar = _SidebarCompat(self, is_creator=(self.initial_section == "creator"))
        self.card_layout = getattr(self, 'trainer_cards_layout', None)
        self.scroll_cards = getattr(self, 'scroll_trainer_cards', None)
        self.card_container = getattr(self, 'trainer_cards_container', None)
        self.on_repo_selected = self.on_trainer_repo_selected
        self.reset_repo_progress = self.reset_trainer_repo_progress
        self.refresh_repertoire_cards = self.refresh_trainer_repertoire_cards
        self.update_card_selection_highlights = self.update_trainer_card_selection_highlights
        self.rearrange_cards_grid = self.rearrange_trainer_cards_grid
        self.lbl_name = getattr(self, 'lbl_trainer_repo_name', None)
        self.btn_reset = getattr(self, 'btn_reset_trainer_progress', None)
        self.l_n = self.lbl_cr_name
        self.txt_description = self.txt_cr_desc
        self.combo_repertoire_elo = self.combo_cr_elo
        self.combo_repertoire_color = self.combo_cr_color
        self.tbl_levels = self.tbl_cr_levels
        self.g_levels = getattr(self, 'g_cr_levels', None)
        self.lbl_cover_preview = getattr(self, 'lbl_cr_cover_preview', None)
        self.btn_remove_cover = getattr(self, 'btn_rem_cov', None)
        self.slider_vol = self.volume_slider
        self.combo_not = self.combo_notation
        self.s_d = self.spin_scan_depth
        self.c_threads = self.combo_scan_threads
        self.btn_fetch = self.btn_start_lich_fetch
        self.btn_start_eng = self.btn_start_eng_scan
        self.pb_eng = self.pb_scan
        self.l_eng_status = self.lbl_scan_status
        self.refresh_info = self.refresh_creator_info

    @property
    def selected_repo(self):
        return self.selected_trainer_repo

    @selected_repo.setter
    def selected_repo(self, val):
        self.selected_trainer_repo = val

    def on_auto_check_updates_toggled(self, checked: bool):
        cfg = get_config_dict()
        cfg["auto_check_updates"] = checked
        save_config_dict(cfg)
        self.set_setting("auto_check_updates", checked)

    def save_repertoire_elo(self, val=None):
        backend = getattr(self, 'backend', None)
        if not backend or not getattr(backend, 'session', None):
            return
        if val is None and hasattr(self, 'combo_repertoire_elo'):
            val = self.combo_repertoire_elo.currentText()
        if val:
            backend.set_meta("elo", get_elo_internal(val))
            try: backend.session.commit()
            except: pass

    def save_description(self):
        backend = getattr(self, 'backend', None)
        if not backend or not getattr(backend, 'session', None):
            return
        desc = self.txt_description.toPlainText() if hasattr(self, 'txt_description') else ""
        backend.set_meta("description", desc)
        try: backend.session.commit()
        except: pass

    def add_level(self):
        self.add_creator_level()

    def rename_repertoire(self):
        self.rename_active_repertoire()

    def select_cover_image(self):
        self.select_creator_cover()

    def remove_cover_image(self):
        self.remove_creator_cover()

    def change_board_theme(self, theme_name):
        if hasattr(self, 'combo_theme'):
            self.combo_theme.setCurrentText(theme_name)
        self.set_setting("theme", theme_name)
        if self.main_window and hasattr(self.main_window, 'board_widget') and hasattr(self.main_window.board_widget, 'set_theme'):
            self.main_window.board_widget.set_theme(theme_name)

    def change_highlight_color(self, color_name):
        if hasattr(self, 'combo_highlight'):
            self.combo_highlight.setCurrentText(color_name)
        self.set_setting("highlight_color", color_name)
        if self.main_window and hasattr(self.main_window, 'board_widget') and hasattr(self.main_window.board_widget, 'set_highlight_color'):
            self.main_window.board_widget.set_highlight_color(color_name)

    def change_volume(self, val):
        if hasattr(self, 'volume_slider'):
            self.volume_slider.setValue(val)
        self.set_setting("master_volume", val)

    def save_tab_settings(self):
        self.save_creator_tab_settings()

    def paste_pgn_dialog(self):
        if self.main_window and hasattr(self.main_window, 'paste_pgn_dialog'):
            self.main_window.paste_pgn_dialog()

    def import_pgn_file_dialog(self):
        if self.main_window and hasattr(self.main_window, 'import_pgn_file_dialog'):
            self.main_window.import_pgn_file_dialog()

    def on_token_changed(self, token):
        if hasattr(self, 'txt_lichess_token'):
            self.txt_lichess_token.setText(token)
        self.set_setting("lichess_token", token)

    def run_variation_name_repair(self):
        backend = self.ensure_backend_for_active_repo()
        if backend and hasattr(backend, 'reset_and_repair_variation_names'):
            backend.reset_and_repair_variation_names()

    def start_analysis(self):
        self.toggle_engine_scan()

    def _select_all_maintenance_repos(self, checked):
        self._select_all_maintenance(checked)

    def _load_profile_settings(self, profile_name: str) -> dict:
        if not profile_name:
            return {}
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        settings_path = os.path.join(profiles_dir, f"{profile_name}_settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_profile_settings(self, profile_name: str, settings_dict: dict):
        if not profile_name:
            return
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        os.makedirs(profiles_dir, exist_ok=True)
        settings_path = os.path.join(profiles_dir, f"{profile_name}_settings.json")
        try:
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings_dict, f, indent=4)
        except Exception:
            pass

    def get_config(self) -> Dict[str, Any]:
        """Helper to get global config dict."""
        if self.main_window and hasattr(self.main_window, 'config') and isinstance(self.main_window.config, dict):
            return self.main_window.config
        return get_config_dict()

    def save_config(self):
        """Helper to persist global config dict."""
        if self.main_window and hasattr(self.main_window, 'save_config'):
            self.main_window.save_config()
        elif self.main_window and hasattr(self.main_window, 'config') and isinstance(self.main_window.config, dict):
            save_config_dict(self.main_window.config)

    def get_setting(self, key, default=None):
        """Helper to retrieve profile or config setting."""
        if self.main_window and getattr(self.main_window, 'training_manager', None):
            val = self.main_window.training_manager.get_setting(key)
            if val is not None:
                return val
            if self.initial_section == "trainer":
                return default
        elif hasattr(self, 'profile_settings') and isinstance(self.profile_settings, dict):
            if key in TRAINER_SETTINGS_KEYS:
                if key in self.profile_settings and self.profile_settings[key] is not None:
                    return self.profile_settings[key]
                if self.initial_section == "trainer":
                    return default
        return self.get_config().get(key, default)

    def set_setting(self, key, value):
        """Helper to save setting both globally and in current/last active profile."""
        cfg = self.get_config()
        cfg[key] = value
        save_config_dict(cfg)
        if self.main_window and hasattr(self.main_window, 'config') and isinstance(self.main_window.config, dict):
            self.main_window.config[key] = value
        if self.main_window and hasattr(self.main_window, 'save_config'):
            try: self.main_window.save_config()
            except: pass
        if self.main_window and getattr(self.main_window, 'training_manager', None):
            self.main_window.training_manager.set_setting(key, value)
        elif getattr(self, 'profile_name', None):
            if not hasattr(self, 'profile_settings') or self.profile_settings is None:
                self.profile_settings = {}
            if key in TRAINER_SETTINGS_KEYS or not self.main_window or not hasattr(self.main_window, 'config'):
                self.profile_settings[key] = value
                self._save_profile_settings(self.profile_name, self.profile_settings)

        if self.main_window and hasattr(self.main_window, 'set_setting'):
            try: self.main_window.set_setting(key, value)
            except: pass

        if key == "anim_speed" and self.main_window and hasattr(self.main_window, 'board_widget') and self.main_window.board_widget:
            try: self.main_window.board_widget.update_animation_metrics(value)
            except: pass

    # ─── UI Architecture ────────────────────────────────────────────────────

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Sidebar (Hierarchical Navigation using QTreeWidget)
        self.sidebar_tree = QTreeWidget()
        self.sidebar_tree.setHeaderHidden(True)
        self.sidebar_tree.setFixedWidth(scale(315))
        self.sidebar_tree.setObjectName("SidebarTree")
        self.sidebar_tree.setIndentation(scale(14))
        self.sidebar_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sidebar_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_tree.setStyleSheet(f"""
            QTreeWidget#SidebarTree {{
                background-color: #f7f7f9;
                border: none;
                border-right: 1px solid rgba(0, 0, 0, 0.08);
                padding: {scale(8)}px {scale(6)}px;
                outline: none;
            }}
            QTreeWidget#SidebarTree::item {{
                height: {scale(34)}px;
                border-radius: {scale(6)}px;
                padding-left: {scale(6)}px;
                padding-right: {scale(6)}px;
                color: #222222;
                font-weight: 500;
                font-size: {scale(13)}px;
            }}
            QTreeWidget#SidebarTree::item:hover {{
                background-color: rgba(0, 0, 0, 0.04);
            }}
            QTreeWidget#SidebarTree::item:selected {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                font-weight: 600;
            }}
        """)
        self.sidebar_tree.itemClicked.connect(self.on_tree_item_clicked)
        main_layout.addWidget(self.sidebar_tree)

        # 2. Right Content Area (Top Repertoire Bar + Stacked Pages)
        self.content_container = QWidget()
        v_right = QVBoxLayout(self.content_container)
        v_right.setContentsMargins(0, 0, 0, 0)
        v_right.setSpacing(0)

        # Course Selector Bar (Shown only when a Creator tab is selected)
        self.creator_header_bar = QFrame()
        self.creator_header_bar.setStyleSheet("background: #fbfbfb; border-bottom: 1px solid rgba(0,0,0,0.08);")
        h_cr_bar = QHBoxLayout(self.creator_header_bar)
        h_cr_bar.setContentsMargins(scale(24), scale(10), scale(24), scale(10))
        h_cr_bar.setSpacing(scale(12))

        lbl_cr_prompt = QLabel(tr_ui("settings.editing_course_label", "📚 Kurs bearbeiten:"))
        lbl_cr_prompt.setStyleSheet("font-weight: 700; font-size: 14px; color: #333;")
        self.combo_active_repo = NoWheelComboBox()
        self.combo_active_repo.setMinimumWidth(scale(240))
        self.combo_active_repo.setFixedHeight(scale(34))
        self.populate_active_repo_dropdown()
        self.combo_active_repo.currentIndexChanged.connect(self.on_creator_repo_switched)

        h_cr_bar.addWidget(lbl_cr_prompt)
        h_cr_bar.addWidget(self.combo_active_repo)
        h_cr_bar.addStretch()
        self.creator_header_bar.hide()
        v_right.addWidget(self.creator_header_bar)

        # Content Pages Stack
        self.pages = QStackedWidget()
        self.page_item_map = {}

        self.build_all_pages()

        self.main_scroll = QScrollArea()
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.main_scroll.setWidget(self.pages)
        v_right.addWidget(self.main_scroll, 1)

        main_layout.addWidget(self.content_container, 1)

    def populate_active_repo_dropdown(self):
        self.combo_active_repo.blockSignals(True)
        self.combo_active_repo.clear()
        repos = sorted(RepertoireService().get_all_repertoires())
        for r in repos:
            self.combo_active_repo.addItem(r, r)

        curr_active = None
        if self.backend and getattr(self.backend, 'active_repo_name', None):
            curr_active = self.backend.active_repo_name
        elif self.main_window and hasattr(self.main_window, 'repertoire_manager'):
            curr_active = getattr(self.main_window.repertoire_manager, 'active_repertoire_name', None)

        if curr_active and curr_active in repos:
            idx = self.combo_active_repo.findData(curr_active)
            if idx >= 0: self.combo_active_repo.setCurrentIndex(idx)
        elif repos:
            self.combo_active_repo.setCurrentIndex(0)
        self.combo_active_repo.blockSignals(False)

    def ensure_backend_for_active_repo(self):
        repo_name = self.combo_active_repo.currentData()
        if not repo_name:
            return None
        from opening_fenix.creator.creator_window import CreatorBackend
        if self.backend and getattr(self.backend, 'active_repo_name', None) == repo_name:
            return self.backend
        
        if not self.backend:
            if not self._owned_backend:
                self._owned_backend = CreatorBackend()
            self.backend = self._owned_backend
            
        try:
            self.backend.load_repertoire(repo_name)
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Error loading repertoire {repo_name} into backend: {e}")
        return self.backend

    def on_creator_repo_switched(self):
        self.ensure_backend_for_active_repo()
        self.refresh_creator_info()
        self.refresh_backups_list()

    # ─── Sidebar Tree & Navigation ──────────────────────────────────────────

    def build_all_pages(self):
        self.all_registered_pages = []

        # Instantiate all pages
        self.page_appearance = QWidget(); self.init_page_appearance(self.page_appearance)
        self.page_engine = QWidget(); self.init_page_engine_apis(self.page_engine)
        self.page_storage = QWidget(); self.init_page_storage(self.page_storage)
        self.page_updates = QWidget(); self.init_page_updates(self.page_updates)
        self.page_faq = QWidget(); self.init_page_faq(self.page_faq)
        self.page_about = QWidget(); self.init_page_about(self.page_about)
        self.page_trainer_repos = QWidget(); self.init_page_trainer_repos(self.page_trainer_repos)
        self.page_trainer_behavior = QWidget(); self.init_page_trainer_behavior(self.page_trainer_behavior)
        self.page_cr_identity = QWidget(); self.init_page_creator_identity(self.page_cr_identity)
        self.page_cr_alt_moves = QWidget(); self.init_page_creator_alt_moves(self.page_cr_alt_moves)
        self.page_cr_imex = QWidget(); self.init_page_creator_imex(self.page_cr_imex)
        self.page_cr_backups = QWidget(); self.init_page_creator_backups(self.page_cr_backups)
        self.page_cr_tools = QWidget(); self.init_page_creator_tools(self.page_cr_tools)
        self.page_cr_diag = QWidget(); self.init_page_creator_diagnostics(self.page_cr_diag)
        self.page_cr_maintenance = QWidget(); self.init_page_creator_maintenance(self.page_cr_maintenance)

        # Pre-register primary pages to self.pages so legacy indices 0..N match expectations
        if self.initial_section == "creator":
            ordered_primaries = [
                self.page_cr_identity,      # 0: Identity & Levels
                self.page_appearance,       # 1: Design & Tabs
                self.page_cr_imex,          # 2: Import & Export
                self.page_cr_alt_moves,     # 3: Analysis & Engine
                self.page_cr_tools,         # 4: Tools & Filter
                self.page_cr_maintenance,   # 5: Batch Maintenance Center
                self.page_updates           # 6: Software Updates
            ]
        else:
            ordered_primaries = [
                self.page_appearance,       # 0: Appearance
                self.page_trainer_behavior, # 1: Training Behavior
                self.page_trainer_repos,    # 2: Repertoire Configuration
                self.page_updates,          # 3: Software Updates
                self.page_faq               # 4: FAQ
            ]
        for p in ordered_primaries:
            self.pages.addWidget(p)
            self.all_registered_pages.append(p)

        # 1. GLOBAL SETTINGS
        self.sec_global = self.add_section_header(tr_ui("settings.sec_global", "🌐 GLOBALE EINSTELLUNGEN"))
        self.add_nav_item(self.sec_global, tr_ui("settings.nav_appearance", "🎨 Darstellung & Audio"), self.page_appearance)
        self.add_nav_item(self.sec_global, tr_ui("settings.nav_engine_apis", "🤖 Schach-Engine, Lichess APIs & Fairplay"), self.page_engine)
        self.add_nav_item(self.sec_global, tr_ui("settings.nav_storage", "💾 Speicherort & Daten"), self.page_storage)
        self.add_nav_item(self.sec_global, tr_ui("settings.nav_updates", "🔄 Software-Updates"), self.page_updates)

        # 2. HELP & ABOUT (Between Global and Trainer)
        self.sec_help = self.add_section_header(tr_ui("settings.sec_help", "❓ HILFE & ÜBER OPENING-FENIX"))
        self.add_nav_item(self.sec_help, tr_ui("settings.nav_faq", "📖 FAQ"), self.page_faq)
        self.add_nav_item(self.sec_help, tr_ui("settings.nav_about", "ℹ️ Über Opening-Fenix"), self.page_about)

        # 3. TRAINER SETTINGS ("Profile: Felix")
        display_profile = tr_ui("login.free_training", "Freies Training") if is_free_training_profile(self.profile_name) else self.profile_name
        self.sec_trainer = self.add_section_header(tr_ui("settings.sec_trainer", "🎯 TRAINER-EINSTELLUNGEN ({profile})", profile=display_profile))
        self.item_trainer_repos = self.add_nav_item(self.sec_trainer, tr_ui("settings.nav_trainer_repos", "📚 Repertoire-Konfiguration"), self.page_trainer_repos)
        self.add_nav_item(self.sec_trainer, tr_ui("settings.nav_trainer_behavior", "🎯 Trainingsverhalten"), self.page_trainer_behavior)

        # 4. CREATOR (Course Authoring)
        self.sec_creator = self.add_section_header(tr_ui("settings.sec_creator", "🛠️ CREATOR (Kurs-Editor)"))
        self.item_creator_identity = self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_identity", "📋 Repertoire-Identität & Level"), self.page_cr_identity, is_creator=True)
        self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_alt_moves", "🧠 Alternative Züge & Prio-Score"), self.page_cr_alt_moves, is_creator=True)
        self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_imex", "📥 Import & Export"), self.page_cr_imex, is_creator=True)
        self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_backups", "⏮️ Backups & Wiederherstellung"), self.page_cr_backups, is_creator=True)
        self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_tools", "🔧 Verschiedene Werkzeuge"), self.page_cr_tools, is_creator=True)
        self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_diag", "🔍 Datenbank-Diagnose"), self.page_cr_diag, is_creator=True)
        self.add_nav_item(self.sec_creator, tr_ui("settings.nav_creator_maintenance", "🚜 Wartungs-Center (Stapel)"), self.page_cr_maintenance, is_creator=True)

    def add_section_header(self, text: str) -> QTreeWidgetItem:
        header = QTreeWidgetItem(self.sidebar_tree)
        header.setText(0, text)
        header.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = header.font(0)
        font.setBold(True)
        font.setPointSize(scale(10))
        header.setFont(0, font)
        header.setForeground(0, QBrush(QColor("#7f8c8d")))
        header.setSizeHint(0, QSize(0, scale(36)))
        return header

    def add_nav_item(self, parent_header: QTreeWidgetItem, text: str, page_widget: QWidget, is_creator: bool = False) -> QTreeWidgetItem:
        if page_widget not in self.all_registered_pages:
            idx = self.pages.addWidget(page_widget)
            self.all_registered_pages.append(page_widget)
        else:
            idx = self.pages.indexOf(page_widget)
        item = QTreeWidgetItem(parent_header)
        item.setText(0, text)
        item.setData(0, Qt.ItemDataRole.UserRole, idx)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, is_creator)
        return item

    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.pages.setCurrentIndex(idx)
            is_creator = item.data(0, Qt.ItemDataRole.UserRole + 1)
            is_maintenance = (idx == self.pages.indexOf(self.page_cr_maintenance))
            self.creator_header_bar.setVisible(bool(is_creator) and not is_maintenance)
            if is_creator and not is_maintenance:
                self.ensure_backend_for_active_repo()
                self.refresh_creator_info()
            if hasattr(self, 'main_scroll') and self.main_scroll:
                self.main_scroll.verticalScrollBar().setValue(0)
        else:
            item.setExpanded(not item.isExpanded())

    def navigate_initial_section(self, section: str):
        self.sec_global.setExpanded(True)
        self.sec_help.setExpanded(False)
        if section == "creator":
            self.sec_trainer.setExpanded(False)
            self.sec_creator.setExpanded(True)
            self.sidebar_tree.setCurrentItem(self.item_creator_identity)
            self.on_tree_item_clicked(self.item_creator_identity, 0)
        else:
            self.sec_creator.setExpanded(False)
            self.sec_trainer.setExpanded(True)
            self.sidebar_tree.setCurrentItem(self.item_trainer_repos)
            self.on_tree_item_clicked(self.item_trainer_repos, 0)

    # ─── PAGE 1.1: Appearance & Sound (Global) ──────────────────────────────

    def init_page_appearance(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        # 🎨 Optics
        g_design = QGroupBox(tr_widget("settings.optics_title", "🎨 Optik"))
        f_design = QFormLayout(g_design)
        f_design.setSpacing(scale(15))

        self.combo_theme = NoWheelComboBox()
        for t_key in THEMES.keys():
            self.combo_theme.addItem(tr_ui(f"themes.{t_key}", t_key), t_key)
        current_theme = self.get_setting("theme", "Braun (Klassisch)")
        idx = self.combo_theme.findData(current_theme)
        if idx < 0: idx = self.combo_theme.findText(current_theme)
        if idx >= 0: self.combo_theme.setCurrentIndex(idx)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        self.combo_theme.currentTextChanged.connect(self.on_theme_changed)
        f_design.addRow(tr_ui("settings.board_design", "Schachbrett-Design:"), self.combo_theme)

        self.combo_highlight = NoWheelComboBox()
        for hl_key in HIGHLIGHT_COLORS.keys():
            self.combo_highlight.addItem(tr_ui(f"highlight_colors.{hl_key}", hl_key), hl_key)
        current_hl = self.get_setting("highlight_color", "Gelb (Standard)")
        idx_hl = self.combo_highlight.findData(current_hl)
        if idx_hl < 0: idx_hl = self.combo_highlight.findText(current_hl)
        if idx_hl >= 0: self.combo_highlight.setCurrentIndex(idx_hl)
        self.combo_highlight.currentIndexChanged.connect(self.on_highlight_color_changed)
        self.combo_highlight.currentTextChanged.connect(self.on_highlight_color_changed)
        f_design.addRow(tr_ui("settings.highlight_color", "Farbe Zug-Hervorhebung:"), self.combo_highlight)

        self.spin_anim = NoWheelSpinBox()
        self.spin_anim.setRange(50, 1000)
        self.spin_anim.setSingleStep(50)
        self.spin_anim.setSuffix(" ms")
        self.spin_anim.setValue(self.get_setting("anim_speed", 300))
        self.spin_anim.valueChanged.connect(lambda v: self.set_setting("anim_speed", v))
        f_design.addRow(tr_ui("settings.anim_speed", "Animations-Tempo:"), self.spin_anim)

        self.combo_notation = NoWheelComboBox()
        self.combo_notation.addItem(tr_ui("settings.notation_standard", "Standard (English) – K, Q, R, B, N"), "en")
        self.combo_notation.addItem(tr_ui("settings.notation_german", "Deutsch – K, D, T, L, S"), "de")
        curr_not = self.get_setting("notation_language", "en")
        idx_not = self.combo_notation.findData(curr_not)
        if idx_not >= 0: self.combo_notation.setCurrentIndex(idx_not)
        self.combo_notation.currentIndexChanged.connect(self.on_notation_language_changed)
        f_design.addRow(tr_ui("settings.notation_lang_label", "Notation-Sprache:"), self.combo_notation)

        self.combo_ui_lang = NoWheelComboBox()
        self.combo_ui_lang.addItem("Deutsch (DE)", "de")
        self.combo_ui_lang.addItem("English (EN)", "en")
        curr_ui_l = self.get_setting("ui_language", "de")
        idx_ui_l = self.combo_ui_lang.findData(curr_ui_l)
        if idx_ui_l >= 0: self.combo_ui_lang.setCurrentIndex(idx_ui_l)
        self.combo_ui_lang.currentIndexChanged.connect(self.on_ui_language_changed)

        v_lang = QVBoxLayout()
        v_lang.setSpacing(scale(4))
        v_lang.addWidget(self.combo_ui_lang)
        self.lbl_lang_hint = QLabel(tr_ui("settings.ui_lang_hint", "⚠️ Änderung erfordert einen Neustart des Programms."))
        self.lbl_lang_hint.setStyleSheet(f"color: {COLORS.get('text_muted', '#666666')}; font-size: {scale(11)}px;")
        v_lang.addWidget(self.lbl_lang_hint)
        f_design.addRow(tr_ui("settings.ui_lang_label", "Anwendungs-Sprache:"), v_lang)

        layout.addWidget(g_design)

        # 🔊 Sound & Volume
        g_audio = QGroupBox(tr_widget("settings.audio_title", "🔊 Klang & Lautstärke"))
        f_audio = QFormLayout(g_audio)
        f_audio.setSpacing(scale(15))

        self.volume_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.get_setting("master_volume", 100)))
        self.volume_slider.valueChanged.connect(self.on_volume_changed)

        self.lbl_volume = QLabel(f"{self.volume_slider.value()}%")
        self.lbl_volume.setStyleSheet("font-weight: bold; min-width: 40px;")
        h_vol = QHBoxLayout()
        h_vol.addWidget(self.volume_slider)
        h_vol.addWidget(self.lbl_volume)
        f_audio.addRow(tr_ui("settings.volume", "Gesamtlautstärke:"), h_vol)
        layout.addWidget(g_audio)

        # 🧱 Creator Workspace Tab Visibility
        g_tabs = QGroupBox(tr_widget("repo_settings.tab_config_title", "🧱 Creator Tab-Konfiguration"))
        v_tabs = QVBoxLayout(g_tabs)
        lbl_tab_info = QLabel(tr_ui("repo_settings.tab_info", "Wähle aus, welche Tabs in der Creator-Ansicht (unten rechts) angezeigt werden sollen:"))
        lbl_tab_info.setWordWrap(True)
        lbl_tab_info.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 6px;")
        v_tabs.addWidget(lbl_tab_info)

        active_tabs = self.get_config().get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
        self.chk_details = QCheckBox(tr_widget("repo_settings.tab_details", "📋 Details (Position-Infos)"))
        self.chk_analysis = QCheckBox(tr_widget("repo_settings.tab_analysis", "🧠 Analyse (Engine & Lichess)"))
        self.chk_transpositions = QCheckBox(tr_widget("repo_settings.tab_transpositions", "🔄 Transpositionen"))
        self.chk_holes = QCheckBox(tr_widget("repo_settings.tab_search_mode", "🕳️ Such Modus (Lücken)"))
        self.chk_kontrolle = QCheckBox(tr_widget("repo_settings.tab_control", "✅ Kontrolle (Varianten-Filter)"))

        for chk, key in [(self.chk_details, "DETAILS"), (self.chk_analysis, "ANALYSIS"), 
                         (self.chk_transpositions, "TRANSPOSITIONS"),
                         (self.chk_holes, "HOLES"), (self.chk_kontrolle, "KONTROLLE")]:
            chk.setChecked(key in active_tabs)
            chk.toggled.connect(self.save_creator_tab_settings)
            v_tabs.addWidget(chk)
        layout.addWidget(g_tabs)

        layout.addStretch()

    def on_theme_changed(self, *args):
        theme_name = self.combo_theme.currentData() or self.combo_theme.currentText()
        self.set_setting("theme", theme_name)
        if self.main_window and hasattr(self.main_window, 'apply_theme'):
            self.main_window.apply_theme()
        if self.main_window and hasattr(self.main_window, 'board_widget') and hasattr(self.main_window.board_widget, 'set_theme'):
            self.main_window.board_widget.set_theme(theme_name)

    def on_highlight_color_changed(self, *args):
        color_name = self.combo_highlight.currentData() or self.combo_highlight.currentText()
        self.set_setting("highlight_color", color_name)
        if self.main_window and hasattr(self.main_window, 'apply_theme'):
            self.main_window.apply_theme()
        if self.main_window and hasattr(self.main_window, 'board_widget') and hasattr(self.main_window.board_widget, 'set_highlight_color'):
            self.main_window.board_widget.set_highlight_color(color_name)

    def on_volume_changed(self, value):
        self.lbl_volume.setText(f"{value}%")
        self.set_setting("master_volume", value)
        if self.main_window and hasattr(self.main_window, 'set_master_volume'):
            self.main_window.set_master_volume(value)
        elif self.main_window and hasattr(self.main_window, 'sounds'):
            for s in self.main_window.sounds.values(): s.setVolume(value / 100.0)

    def on_notation_language_changed(self, *args):
        lang = self.combo_notation.currentData()
        self.set_setting("notation_language", lang)
        if self.main_window and hasattr(self.main_window, "update_notation_display"):
            self.main_window.update_notation_display()
        for w in QApplication.instance().topLevelWidgets():
            try:
                if hasattr(w, "update_ui_from_fen") and not sip.isdeleted(w):
                    w.update_ui_from_fen()
            except: pass

    def on_ui_language_changed(self, *args):
        new_lang = self.combo_ui_lang.currentData()
        curr_lang = self.get_setting("ui_language", "de")
        if not new_lang or new_lang == curr_lang:
            return

        title = tr_ui("settings.lang_change_title", "Sprachwechsel")
        msg = tr_ui("settings.lang_change_restart_prompt", "Das Ändern der Sprache erfordert einen Neustart des Programms. Möchtest du die Sprache jetzt ändern und das Programm neu starten?")

        reply = QMessageBox.question(
            self,
            title,
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.set_setting("ui_language", new_lang)
            try:
                import os
                import json
                from opening_fenix.core.data_tools import get_user_dir
                config_path = os.path.join(get_user_dir(), "config.json")
                config = {}
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                config["ui_language"] = new_lang
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)
            except Exception as e:
                logger.error(f"Failed to update ui_language in config.json: {e}")

            self.restart_application()
        else:
            self.combo_ui_lang.blockSignals(True)
            idx = self.combo_ui_lang.findData(curr_lang)
            if idx >= 0:
                self.combo_ui_lang.setCurrentIndex(idx)
            self.combo_ui_lang.blockSignals(False)

    def restart_application(self):
        """Restarts the application cleanly."""
        import sys
        import subprocess
        try:
            if getattr(sys, 'frozen', False):
                args = [sys.executable] + sys.argv[1:]
            else:
                args = [sys.executable] + sys.argv
            subprocess.Popen(args)
        except Exception as e:
            logger.error(f"Failed to restart application: {e}")

        app = QApplication.instance()
        if app:
            app.quit()

    def save_creator_tab_settings(self):
        active = []
        if self.chk_details.isChecked(): active.append("DETAILS")
        if self.chk_analysis.isChecked(): active.append("ANALYSIS")
        if self.chk_transpositions.isChecked(): active.append("TRANSPOSITIONS")
        if self.chk_holes.isChecked(): active.append("HOLES")
        if self.chk_kontrolle.isChecked(): active.append("KONTROLLE")
        cfg = self.get_config()
        cfg["creator_active_tabs"] = active
        self.save_config()
        if self.main_window and hasattr(self.main_window, 'apply_tab_visibility'):
            self.main_window.apply_tab_visibility()

    # ─── PAGE 1.2: Chess Engine, Lichess APIs & Fairplay (Global) ───────────

    def init_page_engine_apis(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        # 🤖 Stockfish Engine
        g_engine = QGroupBox(tr_widget("settings.engine_config_title", "🤖 Schach-Engine Konfiguration"))
        f_engine = QFormLayout(g_engine)
        f_engine.setSpacing(scale(14))

        self.txt_engine_path = QLineEdit(self.get_config().get("engine_path", ""))
        self.txt_engine_path.textChanged.connect(lambda t: self.set_setting("engine_path", t))
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(scale(42))
        btn_browse.clicked.connect(self.browse_engine_path)
        h_epath = QHBoxLayout(); h_epath.addWidget(self.txt_engine_path); h_epath.addWidget(btn_browse)
        f_engine.addRow(tr_ui("settings.engine_path", "Engine Pfad (.exe):"), h_epath)

        self.combo_engine_threads = NoWheelComboBox()
        cpu_cnt = multiprocessing.cpu_count()
        for i in range(1, cpu_cnt + 1):
            self.combo_engine_threads.addItem(str(i), i)
        def_threads = self.get_config().get("engine_threads", max(1, int(cpu_cnt * 0.5)))
        idx_th = self.combo_engine_threads.findData(def_threads)
        if idx_th >= 0: self.combo_engine_threads.setCurrentIndex(idx_th)
        self.combo_engine_threads.currentIndexChanged.connect(lambda: self.set_setting("engine_threads", self.combo_engine_threads.currentData()))
        f_engine.addRow(tr_ui("settings.engine_threads", "Standard Threads:"), self.combo_engine_threads)

        self.combo_engine_hash = NoWheelComboBox()
        for h_mb in [64, 128, 256, 512, 1024, 2048, 4096]:
            self.combo_engine_hash.addItem(f"{h_mb} MB", h_mb)
        curr_hash = int(self.get_config().get("engine_hash", 256))
        idx_h = self.combo_engine_hash.findData(curr_hash)
        if idx_h >= 0: self.combo_engine_hash.setCurrentIndex(idx_h)
        self.combo_engine_hash.currentIndexChanged.connect(lambda: self.set_setting("engine_hash", self.combo_engine_hash.currentData()))
        f_engine.addRow(tr_ui("settings.engine_hash", "Hash-Größe (RAM):"), self.combo_engine_hash)

        layout.addWidget(g_engine)

        # 🌐 Lichess API & Fairplay Lockout
        g_lich = QGroupBox(tr_widget("settings.lichess_fairplay_title", "🌐 Lichess API & Fairplay Lockout"))
        v_lich = QVBoxLayout(g_lich)
        v_lich.setSpacing(scale(14))

        f_token = QFormLayout()
        self.txt_lichess_token = QLineEdit(self.get_config().get("lichess_token", ""))
        self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_lichess_token.textChanged.connect(lambda t: self.set_setting("lichess_token", t))
        btn_eye = QPushButton("👁️")
        btn_eye.setFixedWidth(scale(42))
        btn_eye.setCheckable(True)
        btn_eye.toggled.connect(lambda c: self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password))
        h_tok = QHBoxLayout(); h_tok.addWidget(self.txt_lichess_token); h_tok.addWidget(btn_eye)
        f_token.addRow(tr_ui("settings.lichess_token", "Lichess API-Token:"), h_tok)
        v_lich.addLayout(f_token)

        # Fairplay Lockout
        lbl_fairplay = QLabel(tr_ui("settings.fairplay_desc", "<b>Lichess Fairplay Schutz:</b> Blockiert auf Wunsch den Zugriff auf Eröffnungsdaten während du ein gewertetes Spiel auf Lichess spielst, um versehentliche Account-Sperren zu verhindern."))
        lbl_fairplay.setWordWrap(True)
        lbl_fairplay.setStyleSheet("color: #666; font-size: 12px;")
        v_lich.addWidget(lbl_fairplay)

        self.chk_lockout_enabled = QCheckBox(tr_widget("settings.lockout_enabled", "Fairplay Lockout-Schutz aktivieren"))
        self.chk_lockout_enabled.setChecked(self.get_config().get("lichess_lockout_enabled", False))
        self.chk_lockout_enabled.toggled.connect(lambda c: self.set_setting("lichess_lockout_enabled", c))
        v_lich.addWidget(self.chk_lockout_enabled)

        self.chk_lockout_use_token = QCheckBox(tr_widget("settings.lockout_use_token", "Account automatisch über obigen Lichess-Token identifizieren"))
        self.chk_lockout_use_token.setChecked(self.get_config().get("lichess_lockout_use_token", True))
        self.chk_lockout_use_token.toggled.connect(lambda c: self.set_setting("lichess_lockout_use_token", c))
        v_lich.addWidget(self.chk_lockout_use_token)

        f_users = QFormLayout()
        self.txt_lockout_users = QLineEdit(self.get_config().get("lichess_lockout_usernames", ""))
        self.txt_lockout_users.setPlaceholderText(tr_ui("settings.lockout_placeholder", "Benutzername1, Benutzername2"))
        self.txt_lockout_users.textChanged.connect(lambda t: self.set_setting("lichess_lockout_usernames", t))
        f_users.addRow(tr_ui("settings.lockout_usernames", "Zu überwachende Spielernamen:"), self.txt_lockout_users)
        v_lich.addLayout(f_users)

        layout.addWidget(g_lich)
        layout.addStretch()

    def browse_engine_path(self):
        p, _ = QFileDialog.getOpenFileName(self, "Stockfish Engine wählen", "", "*.exe")
        if p:
            self.txt_engine_path.setText(p)
            self.set_setting("engine_path", p)

    # ─── PAGE 1.3: Storage & Data (Global) ──────────────────────────────────

    def init_page_storage(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        g_storage = QGroupBox(tr_widget("settings.storage_title", "📁 Speicherort & Cloud-Synchronisation"))
        v_storage = QVBoxLayout(g_storage)
        v_storage.setSpacing(scale(10))

        lbl_storage_desc = QLabel(tr_ui("settings.storage_desc", "Lege fest, wo deine Repertoires und Trainingsprofile gespeichert werden (z. B. in deinem Google Drive oder OneDrive Ordner für Multi-PC-Synchronisation)."))
        lbl_storage_desc.setWordWrap(True)
        lbl_storage_desc.setStyleSheet("color: #666; font-size: 12px;")
        v_storage.addWidget(lbl_storage_desc)

        h_path = QHBoxLayout()
        self.txt_storage_path = QLineEdit(get_user_dir())
        self.txt_storage_path.setReadOnly(True)
        self.txt_storage_path.setStyleSheet("background: white; border: 1px solid rgba(0, 0, 0, 0.15); border-radius: 6px; padding: 6px 10px; font-weight: 500;")
        h_path.addWidget(self.txt_storage_path, 1)

        self.btn_change_storage = AutoAdjustButton(tr_widget("settings.storage_btn_change", "📁 Ordner ändern..."))
        self.btn_change_storage.clicked.connect(self.change_storage_directory)
        h_path.addWidget(self.btn_change_storage)

        self.btn_reset_storage = AutoAdjustButton(tr_widget("settings.storage_btn_reset", "Standard wiederherstellen"))
        self.btn_reset_storage.clicked.connect(self.reset_storage_directory)
        h_path.addWidget(self.btn_reset_storage)
        v_storage.addLayout(h_path)

        h_open = QHBoxLayout()
        btn_open_repos = AutoAdjustButton(tr_widget("settings.btn_open_repertoires_folder", "📁 Repertoires-Ordner im Explorer öffnen"))
        btn_open_repos.clicked.connect(self.open_repertoires_folder)
        btn_open_profs = AutoAdjustButton(tr_widget("settings.btn_open_profiles_folder", "📁 Profile-Ordner im Explorer öffnen"))
        btn_open_profs.clicked.connect(self.open_profiles_folder)
        h_open.addWidget(btn_open_repos)
        h_open.addWidget(btn_open_profs)
        v_storage.addLayout(h_open)

        layout.addWidget(g_storage)
        layout.addStretch()

    def change_storage_directory(self):
        current = get_user_dir()
        selected_dir = QFileDialog.getExistingDirectory(self, tr_ui("settings.storage_title", "📁 Speicherort wählen"), current)
        if not selected_dir or os.path.abspath(selected_dir.strip()) == os.path.abspath(current):
            return

        selected_dir = os.path.abspath(selected_dir.strip())
        reply = QMessageBox.question(
            self, tr_ui("settings.storage_copy_prompt_title", "Daten übertragen?"),
            tr_ui("settings.storage_copy_prompt_msg", "Möchtest du bestehende Repertoires in das neue Verzeichnis kopieren?\n(Wähle 'Nein', falls dieser Ordner bereits Repertoires enthält.)"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Cancel: return
        if reply == QMessageBox.StandardButton.Yes:
            migrate_user_data(current, selected_dir)

        set_custom_data_dir(selected_dir)
        self.txt_storage_path.setText(get_user_dir())
        self.populate_active_repo_dropdown()
        self.refresh_trainer_repertoire_cards()
        QMessageBox.information(self, tr_ui("settings.storage_success_title", "Speicherort geändert"),
            tr_ui("settings.storage_success_msg", "Speicherort erfolgreich geändert:\n{path}\nBitte starte die Anwendung neu, damit alle Datenbanken aktiv übernommen werden.", path=selected_dir))

    def reset_storage_directory(self):
        if not get_custom_data_dir(): return
        if QMessageBox.question(self, tr_ui("settings.storage_reset_confirm_title", "Standard wiederherstellen?"),
            tr_ui("settings.storage_reset_confirm_msg", "Möchtest du zum Standard-Speicherort zurückkehren?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            set_custom_data_dir(None)
            self.txt_storage_path.setText(get_user_dir())
            self.populate_active_repo_dropdown()
            self.refresh_trainer_repertoire_cards()

    def open_repertoires_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        p = os.path.join(get_user_dir(), "repertoires")
        os.makedirs(p, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def open_profiles_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        p = os.path.join(get_user_dir(), "profiles")
        os.makedirs(p, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    # ─── PAGE 1.4: Software Updates (Global) ────────────────────────────────

    def init_page_updates(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        g_updates = QGroupBox(tr_widget("settings.update_title", "🔄 Software-Updates"))
        v_updates = QVBoxLayout(g_updates)
        v_updates.setSpacing(scale(16))

        h_ver = QHBoxLayout()
        h_ver.addWidget(QLabel(tr_ui("settings.current_version_label", "Installierte Version:")))
        self.lbl_current_version = QLabel(f"v{APP_VERSION}")
        self.lbl_current_version.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {COLORS['burnt_orange']};")
        h_ver.addWidget(self.lbl_current_version)
        h_ver.addStretch()
        v_updates.addLayout(h_ver)

        h_chk = QHBoxLayout()
        h_chk.addWidget(QLabel(tr_ui("settings.last_check_label", "Letzte Prüfung:")))
        self.lbl_last_check = QLabel("-")
        self.lbl_last_check.setStyleSheet("font-weight: bold; color: #333;")
        h_chk.addWidget(self.lbl_last_check)
        h_chk.addStretch()
        v_updates.addLayout(h_chk)

        chk_auto = QCheckBox(tr_widget("settings.auto_check_updates", "Bei Start nach Update suchen"))
        chk_auto.setChecked(self.get_config().get("auto_check_updates", True))
        chk_auto.toggled.connect(lambda c: self.set_setting("auto_check_updates", c))
        v_updates.addWidget(chk_auto)

        h_btn = QHBoxLayout()
        self.btn_manual_update = QPushButton(tr_widget("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen"))
        self.btn_manual_update.clicked.connect(self.run_manual_update_check)
        h_btn.addWidget(self.btn_manual_update)
        h_btn.addStretch()
        v_updates.addLayout(h_btn)

        layout.addWidget(g_updates)
        layout.addStretch()

        try: update_signals.check_completed.connect(self.refresh_update_info)
        except: pass
        self.refresh_update_info()

    def refresh_update_info(self, timestamp=None):
        if not timestamp or not isinstance(timestamp, str):
            timestamp = get_last_update_check_time()
        if hasattr(self, 'lbl_last_check') and self.lbl_last_check:
            self.lbl_last_check.setText(str(timestamp) if timestamp else tr_ui("settings.update_never", "Noch nie"))

    def run_manual_update_check(self):
        self.btn_manual_update.setEnabled(False)
        self.btn_manual_update.setText(tr_widget("settings.checking_updates", "Suche läuft..."))
        self.update_worker = UpdateCheckWorker(manual=True, parent=self)
        self.update_worker.update_found.connect(lambda r: (self.refresh_update_info(), self.btn_manual_update.setEnabled(True), self.btn_manual_update.setText(tr_widget("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen")), UpdateDialog(r, self).exec()))
        self.update_worker.no_update_found.connect(lambda: (self.refresh_update_info(), self.btn_manual_update.setEnabled(True), self.btn_manual_update.setText(tr_widget("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen")), QMessageBox.information(self, tr_ui("settings.no_update_title", "Auf dem neuesten Stand"), tr_ui("settings.no_update_msg", "Du nutzt bereits die aktuellste Version ({version}).", version=APP_VERSION))))
        self.update_worker.check_error.connect(lambda err: (self.refresh_update_info(), self.btn_manual_update.setEnabled(True), self.btn_manual_update.setText(tr_widget("settings.btn_check_updates_now", "🔄 Jetzt nach Updates suchen")), QMessageBox.warning(self, tr_ui("settings.update_error_title", "Fehler bei Update-Prüfung"), str(err))))
        self.update_worker.start()

    # ─── PAGE 2.1 & 2.2: Help & About ───────────────────────────────────────

    def init_page_faq(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        lbl_title = QLabel(tr_ui("settings_faq.title", "Häufig gestellte Fragen (FAQ)"))
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(22)}px; font-weight: 800;")
        layout.addWidget(lbl_title)

        from opening_fenix.gui.dialogs.faq_dialog import FAQItem, get_faq_items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        c_w = QWidget(); c_lay = QVBoxLayout(c_w)
        for q, a in get_faq_items():
            c_lay.addWidget(FAQItem(q, a))
        c_lay.addStretch()
        scroll.setWidget(c_w)
        layout.addWidget(scroll, 1)

    def init_page_about(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        card = QFrame()
        card.setStyleSheet("background: white; border: 1px solid rgba(0,0,0,0.1); border-radius: 12px; padding: 20px;")
        v_card = QVBoxLayout(card)
        v_card.setSpacing(scale(12))

        lbl_h = QLabel(f"Opening Fenix v{APP_VERSION}")
        lbl_h.setStyleSheet(f"font-size: 22px; font-weight: 900; color: {COLORS['burnt_orange']};")
        v_card.addWidget(lbl_h)

        lbl_desc = QLabel("Schach-Eröffnungs-Trainer & Repertoire-Manager mit Leitner Spaced-Repetition System (SRS), Lichess Master-Datenbank und Stockfish-Integration.")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 13px; color: #444;")
        v_card.addWidget(lbl_desc)

        lbl_author = QLabel("Entwickelt von Felix. Open Source & frei für die Community.")
        lbl_author.setStyleSheet("color: #777; font-size: 12px;")
        v_card.addWidget(lbl_author)

        layout.addWidget(card)
        layout.addStretch()

    # ─── PAGE 3.1: Repertoire Configuration (Trainer) ───────────────────────

    def init_page_trainer_repos(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(16))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        # Repertoire-Cards Bereich mit weißem Hintergrund
        g_cards = QGroupBox(tr_widget("settings.repo_selection_title", "📂 Repertoire Auswahl & Status"))
        v_cards = QVBoxLayout(g_cards)
        v_cards.setContentsMargins(scale(12), scale(14), scale(12), scale(14))
        v_cards.setSpacing(0)
        
        self.scroll_trainer_cards = QScrollArea()
        self.scroll_trainer_cards.setWidgetResizable(True)
        self.scroll_trainer_cards.setMaximumHeight(scale(380))
        self.scroll_trainer_cards.setStyleSheet("""
            QScrollArea { border: none; background-color: #ffffff; }
        """)
        self.scroll_trainer_cards.viewport().setObjectName("qt_scrollarea_viewport")
        self.scroll_trainer_cards.viewport().setStyleSheet("#qt_scrollarea_viewport { background-color: #ffffff; border: none; }")
        self.scroll_cards = self.scroll_trainer_cards

        self.trainer_cards_container = QWidget()
        self.trainer_cards_container.setObjectName("TrainerCardsContainer")
        self.trainer_cards_container.setStyleSheet("#TrainerCardsContainer { background-color: #ffffff; }")
        self.trainer_cards_layout = QGridLayout(self.trainer_cards_container)
        self.trainer_cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.trainer_cards_layout.setContentsMargins(scale(4), scale(4), scale(4), scale(4))
        self.trainer_cards_layout.setSpacing(scale(8))
        self.card_layout = self.trainer_cards_layout
        self.card_container = self.trainer_cards_container

        self.scroll_trainer_cards.setWidget(self.trainer_cards_container)
        self.scroll_trainer_cards.installEventFilter(self)
        self.scroll_trainer_cards.viewport().installEventFilter(self)
        v_cards.addWidget(self.scroll_trainer_cards)
        layout.addWidget(g_cards)

        self.refresh_trainer_repertoire_cards()

        # Repertoire Informationen (Vollständige Anzeige mit Cover, Farbe, Elo, Kommentaren, Levels & Beschreibung)
        self.grp_trainer_details = QGroupBox(tr_widget("settings.repo_info_title", "ℹ️ Repertoire Informationen"))
        self.grp_info = self.grp_trainer_details
        info_outer_layout = QVBoxLayout(self.grp_trainer_details)
        info_outer_layout.setContentsMargins(scale(15), scale(15), scale(15), scale(15))
        info_outer_layout.setSpacing(0)

        # Empty State Placeholder
        self.info_empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.info_empty_widget)
        empty_layout.setContentsMargins(scale(10), scale(20), scale(10), scale(20))
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info_empty = QLabel(tr_ui("settings.select_repo_to_show_data", "Wähle ein Repertoire aus, um Daten anzuzeigen"))
        self.lbl_info_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info_empty.setStyleSheet("color: #7f8c8d; font-size: 13px; font-weight: bold; font-style: italic; background: transparent;")
        empty_layout.addWidget(self.lbl_info_empty)
        info_outer_layout.addWidget(self.info_empty_widget)

        # Full Content Widget
        self.info_content_widget = QWidget()
        info_main_layout = QHBoxLayout(self.info_content_widget)
        info_main_layout.setContentsMargins(0, 0, 0, 0)
        info_main_layout.setSpacing(scale(25))

        # Linke Spalte (Cover, Name, Farbe, Meta Pill [Datenbank Elo, Kommentare], Level-Liste)
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

        self.lbl_trainer_repo_name = QLabel("-")
        self.lbl_trainer_repo_name.setWordWrap(True)
        self.lbl_trainer_repo_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_trainer_repo_name.setStyleSheet("font-weight: bold; font-size: 15px;")
        self.lbl_name = self.lbl_trainer_repo_name
        left_col.addWidget(self.lbl_trainer_repo_name)

        self.lbl_color = QLabel("-")
        self.lbl_color.setWordWrap(True)
        self.lbl_color.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_col.addWidget(self.lbl_color)

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

        self.lbl_depth = QLabel("-")
        self.lbl_moves = QLabel("-")
        self.lbl_depth.hide()
        self.lbl_moves.hide()

        info_main_layout.addWidget(left_col_widget, 0)

        # Rechte Spalte (Beschreibung - lesbar und rahmenlos)
        self.txt_trainer_description = QTextEdit()
        self.txt_trainer_description.setReadOnly(True)
        self.txt_trainer_description.setStyleSheet(
            "background: transparent; border: none; padding: 0px; font-size: 14px; color: #2c3e50; line-height: 1.4;"
        )
        self.txt_trainer_description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        info_main_layout.addWidget(self.txt_trainer_description, 1)

        info_outer_layout.addWidget(self.info_content_widget)
        layout.addWidget(self.grp_trainer_details)

        # Gefahrenzone (Separater Kasten für Zurücksetzen des Fortschritts)
        g_danger = QGroupBox(tr_widget("settings.danger_title", "⚠️ Gefahrenzone"))
        v_danger = QVBoxLayout(g_danger)
        lbl_danger = QLabel(tr_ui("settings.danger_desc", "Das Zurücksetzen löscht deinen gesamten Trainingsfortschritt für dieses Repertoire."))
        lbl_danger.setWordWrap(True)
        lbl_danger.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        v_danger.addWidget(lbl_danger)

        self.btn_reset_trainer_progress = QPushButton(tr_widget("settings.danger_btn", "🗑️ Trainingsfortschritt zurücksetzen"))
        self.btn_reset_trainer_progress.setProperty("class", "Danger")
        self.btn_reset_trainer_progress.clicked.connect(self.reset_trainer_repo_progress)
        self.btn_reset = self.btn_reset_trainer_progress
        v_danger.addWidget(self.btn_reset_trainer_progress)
        layout.addWidget(g_danger)

        # Initial-Auswahl: Aktives Repertoire oder None
        active_repo = None
        if self.main_window and hasattr(self.main_window, 'repertoire_manager'):
            active_repo = getattr(self.main_window.repertoire_manager, 'active_repertoire_name', None)
        if active_repo:
            self.on_trainer_repo_selected(active_repo)
        else:
            self.on_trainer_repo_selected(None)

        layout.addStretch()

    def refresh_trainer_repertoire_cards(self):
        while self.trainer_cards_layout.count():
            item = self.trainer_cards_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        repos = RepertoireService().get_all_repertoires()
        active_repos = []
        inactive_repos = []
        for r_name in repos:
            is_active = True
            if self.main_window and hasattr(self.main_window, 'training_manager'):
                is_active = self.main_window.training_manager.is_repo_visible(r_name)
            if is_active:
                active_repos.append(r_name)
            else:
                inactive_repos.append(r_name)
                
        sorted_repos = sorted(active_repos) + sorted(inactive_repos)

        for r_name in sorted_repos:
            is_active = True
            if self.main_window and hasattr(self.main_window, 'training_manager'):
                is_active = self.main_window.training_manager.is_repo_visible(r_name)
            card = RepertoireConfigCard(r_name, is_active, self)
            card.clicked.connect(lambda n=r_name: self.on_trainer_repo_selected(n))
            self.trainer_cards_layout.addWidget(card)

        self._current_cols = -1
        self.rearrange_trainer_cards_grid()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if hasattr(self, "scroll_trainer_cards") and (obj == self.scroll_trainer_cards or obj == self.scroll_trainer_cards.viewport()) and event.type() == QEvent.Type.Resize:
            self.rearrange_trainer_cards_grid()
        elif hasattr(self, "levels_container") and obj == self.levels_container and event.type() == QEvent.Type.Resize:
            self.rearrange_levels_grid()
        return super().eventFilter(obj, event)

    def rearrange_trainer_cards_grid(self):
        if not hasattr(self, "scroll_trainer_cards") or not hasattr(self, "trainer_cards_layout"):
            return
            
        width = self.scroll_trainer_cards.viewport().width()
        if width <= 10:
            return
            
        card_min_width = scale(250)
        spacing = scale(8)
        margins = self.trainer_cards_layout.contentsMargins()
        avail_width = width - (margins.left() + margins.right()) - scale(8)
        
        cols = max(1, avail_width // (card_min_width + spacing))
        
        if hasattr(self, "_current_cols") and self._current_cols == cols:
            return
        self._current_cols = cols
        
        cards = []
        for i in range(self.trainer_cards_layout.count()):
            item = self.trainer_cards_layout.itemAt(i)
            if item and item.widget():
                cards.append(item.widget())
                
        for card in cards:
            self.trainer_cards_layout.removeWidget(card)
            
        for c in range(max(cols, 10)):
            self.trainer_cards_layout.setColumnStretch(c, 1 if c < cols else 0)

        for idx, card in enumerate(cards):
            r = idx // cols
            c = idx % cols
            self.trainer_cards_layout.addWidget(card, r, c)

    def rearrange_levels_grid(self):
        if not hasattr(self, "level_pills") or not self.level_pills or not hasattr(self, "levels_layout"):
            return
        for pill in self.level_pills:
            self.levels_layout.removeWidget(pill)
        for pill in self.level_pills:
            self.levels_layout.addWidget(pill)

    def start_loading_animation(self):
        if not getattr(self, 'loading_timer', None):
            self.loading_timer = QTimer(self)
            self.loading_timer.timeout.connect(self.update_loading_dots)
        self.loading_timer.start(500)
        self.loading_dots = 0

    def update_loading_dots(self):
        self.loading_dots = (getattr(self, 'loading_dots', 0) + 1) % 4
        dots = "." * self.loading_dots
        text = f"Laden{dots}"
        
        labels = [getattr(self, 'lbl_db_info', None), getattr(self, 'lbl_levels', None),
                  getattr(self, 'lbl_cr_ana_status', None), getattr(self, 'lbl_cr_db_cov', None)]
        for lbl in labels:
            if lbl and not sip.isdeleted(lbl) and "Laden" in lbl.text():
                lbl.setText(text)

    def on_trainer_repo_selected(self, repo_name):
        self.selected_trainer_repo = repo_name
        self.selected_repo = repo_name
        if not repo_name:
            if hasattr(self, 'info_empty_widget'): self.info_empty_widget.show()
            if hasattr(self, 'info_content_widget'): self.info_content_widget.hide()
            if hasattr(self, 'btn_reset'): self.btn_reset.setEnabled(False)
            self.update_trainer_card_selection_highlights()
            return

        if hasattr(self, 'info_empty_widget'): self.info_empty_widget.hide()
        if hasattr(self, 'info_content_widget'): self.info_content_widget.show()
        if hasattr(self, 'btn_reset'): self.btn_reset.setEnabled(True)
        self.update_trainer_card_selection_highlights()

        # Stop existing loader if any
        if hasattr(self, "stats_loader") and self.stats_loader and self.stats_loader.isRunning():
            self.stats_loader.requestInterruption()
            self.stats_loader.wait()

        # Fast Load metadata
        from opening_fenix.core.db.database import DatabaseManager
        from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_comment_stats
        from opening_fenix.core.data_tools import get_meta
        from opening_fenix.core.services.repertoire_core_service import fetch_repertoire_info
        
        db_path = get_repertoire_db_path(repo_name)
        db_manager = DatabaseManager(db_path)
        session = db_manager.get_session()
        try:
            info = fetch_repertoire_info(session, repo_name, fast_only=True)
            color = get_meta(session, "color", "w")
            comment_stats_str = get_repertoire_comment_stats(session)
        except Exception:
            info = {"name": repo_name, "description": ""}
            color = 'w'
            comment_stats_str = "Keine Kommentare"
        finally:
            session.close()
            db_manager.close()

        if hasattr(self, 'lbl_trainer_repo_name'):
            self.lbl_trainer_repo_name.setText(info.get("name", repo_name) or repo_name)
        if hasattr(self, 'lbl_name'):
            self.lbl_name.setText(info.get("name", repo_name) or repo_name)

        if hasattr(self, 'lbl_comment_stats'):
            if not comment_stats_str or comment_stats_str == "Keine Kommentare":
                stats_display = tr_ui("settings.no_comments", "Keine Kommentare")
            else:
                stats_display = comment_stats_str
            self.lbl_comment_stats.setText(tr_ui("settings.comments_format", "💬 Kommentare: {stats}", stats=stats_display))
        
        if hasattr(self, 'lbl_color'):
            if color == 'w':
                self.lbl_color.setText(tr_ui("settings.repo_color_white", "Weiß ♟️"))
            else:
                self.lbl_color.setText(tr_ui("settings.repo_color_black", "Schwarz ♟️"))
            self.lbl_color.setStyleSheet(
                f"padding: {scale(4)}px {scale(8)}px; border-radius: {scale(10)}px; background: white; color: #111111; font-size: {scale(11)}px; font-weight: bold; border: 1px solid rgba(0,0,0,0.15);"
            )
            
        if hasattr(self, 'txt_trainer_description'):
            self.txt_trainer_description.setPlainText(info.get("description", "-") or "-")
        if hasattr(self, 'lbl_db_info'):
            self.lbl_db_info.setText(tr_ui("settings.db_loading", "📚 Datenbank: Laden..."))

        # Load cover image
        from opening_fenix.creator.repo_selection_dialog import get_repertoire_cover_path
        if hasattr(self, 'lbl_info_cover'):
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
        if hasattr(self, 'levels_layout'):
            while self.levels_layout.count():
                item = self.levels_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            self.lbl_levels = QLabel(tr_ui("settings.loading_text", "Laden..."))
            self.lbl_levels.setStyleSheet("color: #888; font-size: 12px;")
            self.levels_layout.addWidget(self.lbl_levels)

        # Start animation and worker
        self.start_loading_animation()
        self.stats_loader = TrainerRepoStatsWorker(self.main_window, repo_name)
        self.stats_loader.stats_ready.connect(self.on_trainer_stats_loaded)
        self.stats_loader.start()

    def on_trainer_stats_loaded(self, info):
        if sip.isdeleted(self): return
        if hasattr(self, 'loading_timer') and self.loading_timer: self.loading_timer.stop()
        
        # Update Database Elo rating info
        elo_cat = info.get("elo", "-")
        rating_info = get_elo_display(elo_cat)
        if hasattr(self, 'lbl_db_info'):
            self.lbl_db_info.setText(tr_ui("settings.db_info_format", "📚 Datenbank: {rating_info}", rating_info=rating_info))
        
        # Clear and build levels list as a single combined pill container
        self.level_pills = []
        if hasattr(self, 'levels_layout'):
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

    def update_trainer_card_selection_highlights(self):
        if not hasattr(self, 'trainer_cards_layout'):
            return
        for i in range(self.trainer_cards_layout.count()):
            it = self.trainer_cards_layout.itemAt(i)
            if it and it.widget() and hasattr(it.widget(), 'update_style'):
                it.widget().update_style()

    def reset_trainer_repo_progress(self):
        if not getattr(self, 'selected_trainer_repo', None):
            return
        if QMessageBox.warning(
            self, tr_ui("settings.reset_title", "Fortschritt zurücksetzen"),
            tr_ui("settings.reset_confirm", "Trainingsfortschritt für '{repo_name}' wirklich löschen?\n\nDies kann nicht rückgängig gemacht werden.", repo_name=self.selected_trainer_repo),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            if self.main_window and hasattr(self.main_window, 'training_manager'):
                original_repo = getattr(self.main_window.repertoire_manager, 'active_repertoire_name', None) if hasattr(self.main_window, 'repertoire_manager') else None
                if hasattr(self.main_window, 'repertoire_manager') and hasattr(self.main_window.repertoire_manager, 'set_active_repertoire'):
                    self.main_window.repertoire_manager.set_active_repertoire(self.selected_trainer_repo)
                self.main_window.training_manager.reset_repertoire_progress()
                if original_repo and original_repo != self.selected_trainer_repo and hasattr(self.main_window, 'repertoire_manager') and hasattr(self.main_window.repertoire_manager, 'set_active_repertoire'):
                    self.main_window.repertoire_manager.set_active_repertoire(original_repo)
            QMessageBox.information(self, tr_ui("settings.reset_title", "Fortschritt zurücksetzen"), "Trainingsfortschritt erfolgreich zurückgesetzt.")

    # ─── PAGE 3.2: Training Behavior (Trainer) ──────────────────────────────

    def init_page_trainer_behavior(self, page):
        from opening_fenix.core.services.training_service import DEFAULT_BOX_INTERVALS
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        # 1. Spaced Repetition Intervals
        g_intervals = QGroupBox(tr_widget("settings.intervals_title", "⏳ Wiederholungsintervalle (Spaced Repetition)"))
        v_intervals = QVBoxLayout(g_intervals)
        v_intervals.setSpacing(scale(12))

        f_preset = QFormLayout()
        self.combo_interval_preset = NoWheelComboBox()
        self.combo_interval_preset.addItem(tr_ui("settings.preset_standard", "Standard (Leitner 7-Box)"), "standard")
        self.combo_interval_preset.addItem(tr_ui("settings.preset_relaxed", "Relaxed (Langzeit)"), "relaxed")
        self.combo_interval_preset.addItem(tr_ui("settings.preset_custom", "Benutzerdefiniert"), "custom")
        curr_pr = self.get_setting("interval_preset", "standard")
        idx_pr = self.combo_interval_preset.findData(curr_pr)
        if idx_pr >= 0: self.combo_interval_preset.setCurrentIndex(idx_pr)
        f_preset.addRow(tr_ui("settings.preset_label", "Intervall-Vorlage:"), self.combo_interval_preset)
        v_intervals.addLayout(f_preset)

        # Custom boxes
        self.box_spinboxes = {}
        self.box_unit_combos = {}
        custom_saved = self.get_setting("custom_intervals", {})

        g_boxes = QFrame()
        g_boxes.setStyleSheet("background: rgba(0, 0, 0, 0.02); border-radius: 8px; padding: 6px;")
        grid_boxes = QGridLayout(g_boxes)

        unit_labels = {"minutes": "Minuten", "hours": "Stunden", "days": "Tage", "months": "Monate"}
        for box_num in range(1, 8):
            row = (box_num - 1) // 2
            col_offset = ((box_num - 1) % 2) * 3
            lbl_box = QLabel(f"<b>Box {box_num}:</b>")
            spin_val = NoWheelSpinBox(); spin_val.setRange(1, 999); spin_val.setFixedWidth(scale(75))
            combo_unit = NoWheelComboBox()
            for uk, uv in unit_labels.items(): combo_unit.addItem(uv, uk)
            combo_unit.setFixedWidth(scale(95))

            b_data = custom_saved.get(str(box_num)) or custom_saved.get(box_num)
            if isinstance(b_data, dict): v, u = int(b_data.get("value", 1)), b_data.get("unit", "days")
            else: v, u = DEFAULT_BOX_INTERVALS["standard"].get(box_num, (1, "days"))
            spin_val.setValue(v)
            idx_u = combo_unit.findData(u)
            if idx_u >= 0: combo_unit.setCurrentIndex(idx_u)

            spin_val.valueChanged.connect(self.on_custom_intervals_changed)
            combo_unit.currentIndexChanged.connect(self.on_custom_intervals_changed)
            self.box_spinboxes[box_num] = spin_val
            self.box_unit_combos[box_num] = combo_unit

            grid_boxes.addWidget(lbl_box, row, col_offset)
            grid_boxes.addWidget(spin_val, row, col_offset + 1)
            grid_boxes.addWidget(combo_unit, row, col_offset + 2)

        v_intervals.addWidget(g_boxes)
        self.combo_interval_preset.currentIndexChanged.connect(self.on_interval_preset_changed)
        self.update_interval_inputs_state()
        layout.addWidget(g_intervals)

        # 2. Alternative Good Moves & Queue Priority
        g_alt = QGroupBox(tr_widget("settings.alt_moves_title", "🔀 Alternative Züge & Priorität"))
        f_alt = QFormLayout(g_alt)
        f_alt.setSpacing(scale(12))

        self.combo_alt_policy = NoWheelComboBox()
        self.combo_alt_policy.addItem(tr_ui("settings.alt_no_penalty", "Keine Auswirkung [Empfohlen]"), "no_penalty")
        self.combo_alt_policy.addItem(tr_ui("settings.alt_keep_box", "Box nicht erhöhen"), "keep_box")
        self.combo_alt_policy.addItem(tr_ui("settings.alt_mistake", "Als Fehler werten (Zurück auf Box 1)"), "mistake")
        curr_alt = self.get_setting("alternate_move_policy", "no_penalty")
        idx_a = self.combo_alt_policy.findData(curr_alt)
        if idx_a >= 0: self.combo_alt_policy.setCurrentIndex(idx_a)
        self.combo_alt_policy.currentIndexChanged.connect(lambda: self.set_setting("alternate_move_policy", self.combo_alt_policy.currentData()))
        f_alt.addRow(tr_ui("settings.alt_moves_label", "Verhalten bei alternativen Zügen:"), self.combo_alt_policy)

        self.combo_prio_order = NoWheelComboBox()
        self.combo_prio_order.addItem(tr_ui("settings.prio_box_first", "Niedrigste Box zuerst"), "box_first")
        self.combo_prio_order.addItem(tr_ui("settings.prio_priority_first", "Repertoire-Priorität zuerst"), "priority_first")
        curr_prio = self.get_setting("queue_priority_order", "box_first")
        idx_p = self.combo_prio_order.findData(curr_prio)
        if idx_p >= 0: self.combo_prio_order.setCurrentIndex(idx_p)
        self.combo_prio_order.currentIndexChanged.connect(lambda: self.set_setting("queue_priority_order", self.combo_prio_order.currentData()))
        f_alt.addRow(tr_ui("settings.prio_order_label", "Testkarten-Reihenfolge:"), self.combo_prio_order)
        layout.addWidget(g_alt)

        # 3. Limits & Auto-advance
        g_limits = QGroupBox(tr_widget("settings.limits_title", "🛑 Tages-Limits & Ablauf"))
        f_limits = QFormLayout(g_limits)
        f_limits.setSpacing(scale(12))

        self.spin_max_new = NoWheelSpinBox()
        self.spin_max_new.setRange(0, 500)
        self.spin_max_new.setSpecialValueText(tr_ui("settings.unlimited", "Unbegrenzt"))
        self.spin_max_new.setValue(int(self.get_setting("max_new_cards_per_day", 0)))
        self.spin_max_new.valueChanged.connect(lambda v: self.set_setting("max_new_cards_per_day", v))
        f_limits.addRow(tr_ui("settings.max_new_label", "Max. neue Züge pro Tag:"), self.spin_max_new)

        self.spin_max_reviews = NoWheelSpinBox()
        self.spin_max_reviews.setRange(0, 500)
        self.spin_max_reviews.setSpecialValueText(tr_ui("settings.unlimited", "Unbegrenzt"))
        self.spin_max_reviews.setValue(int(self.get_setting("max_reviews_per_session", 0)))
        self.spin_max_reviews.valueChanged.connect(lambda v: self.set_setting("max_reviews_per_session", v))
        f_limits.addRow(tr_ui("settings.max_reviews_label", "Max. Wiederholungen pro Session:"), self.spin_max_reviews)

        self.chk_limit_after_var = QCheckBox(tr_widget("settings.chk_limit_after_var", "Limits erst nach Abschluss der aktuellen Variante anwenden"))
        chk_val = self.get_setting("enforce_limit_after_variation", True)
        self.chk_limit_after_var.setChecked(bool(chk_val))
        self.chk_limit_after_var.toggled.connect(lambda c: self.set_setting("enforce_limit_after_variation", c))
        f_limits.addRow("", self.chk_limit_after_var)

        self.spin_delay = NoWheelSpinBox()
        self.spin_delay.setRange(0, 2000)
        self.spin_delay.setSingleStep(50)
        self.spin_delay.setSuffix(" ms")
        self.spin_delay.setValue(int(self.get_setting("auto_delay", 0)))
        self.spin_delay.valueChanged.connect(lambda v: self.set_setting("auto_delay", v))
        f_limits.addRow(tr_ui("settings.auto_delay", "Verzögerung Auto-Weiter:"), self.spin_delay)

        layout.addWidget(g_limits)
        layout.addStretch()

    def on_interval_preset_changed(self):
        from opening_fenix.core.services.training_service import DEFAULT_BOX_INTERVALS
        preset = self.combo_interval_preset.currentData()
        self.set_setting("interval_preset", preset)
        if preset in DEFAULT_BOX_INTERVALS:
            def_dict = DEFAULT_BOX_INTERVALS[preset]
            for box_num in range(1, 8):
                if box_num in def_dict:
                    val, unit = def_dict[box_num]
                    spin = self.box_spinboxes.get(box_num)
                    combo = self.box_unit_combos.get(box_num)
                    if spin and combo:
                        spin.blockSignals(True); combo.blockSignals(True)
                        spin.setValue(val)
                        u_idx = combo.findData(unit)
                        if u_idx >= 0: combo.setCurrentIndex(u_idx)
                        spin.blockSignals(False); combo.blockSignals(False)
        self.update_interval_inputs_state()

    def update_interval_inputs_state(self):
        is_custom = (self.combo_interval_preset.currentData() == "custom")
        for spin in self.box_spinboxes.values(): spin.setEnabled(is_custom)
        for combo in self.box_unit_combos.values(): combo.setEnabled(is_custom)

    def on_custom_intervals_changed(self):
        if self.combo_interval_preset.currentData() != "custom": return
        custom_data = {}
        for box_num in range(1, 8):
            spin = self.box_spinboxes.get(box_num)
            combo = self.box_unit_combos.get(box_num)
            if spin and combo:
                custom_data[str(box_num)] = {"value": spin.value(), "unit": combo.currentData()}
        self.set_setting("custom_intervals", custom_data)

    # ─── PAGE 4.1: Repertoire Identity & Levels (Creator) ───────────────────

    def init_page_creator_identity(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(16))
        layout.setContentsMargins(scale(24), scale(24), scale(24), scale(24))

        # Identity Card
        g_id = QGroupBox(tr_widget("repo_settings.identity_title", "📋 Repertoire Identität"))
        v_id = QVBoxLayout(g_id)
        v_id.setSpacing(scale(12))

        # Header Row (Title & Rename Button)
        card_header = QFrame()
        card_header.setStyleSheet("background: white; border: 1px solid rgba(0,0,0,0.1); border-radius: 8px; padding: 8px;")
        h_hdr = QHBoxLayout(card_header)
        self.lbl_cr_header_icon = QLabel("🏆")
        self.lbl_cr_header_icon.setFixedSize(scale(44), scale(44))
        self.lbl_cr_name = QLabel("-")
        self.lbl_cr_name.setStyleSheet(f"font-weight: 900; font-size: {scale(18)}px; color: {COLORS['burnt_orange']};")
        btn_rename = QPushButton(tr_widget("repo_settings.btn_rename", "✎ Umbenennen"))
        btn_rename.clicked.connect(self.rename_active_repertoire)
        h_hdr.addWidget(self.lbl_cr_header_icon)
        h_hdr.addWidget(self.lbl_cr_name, 1)
        h_hdr.addWidget(btn_rename)
        v_id.addWidget(card_header)

        # Meta Grid (2x3)
        grid_meta = QGridLayout()
        grid_meta.setSpacing(scale(10))

        self.combo_cr_elo = NoWheelComboBox()
        self.combo_cr_elo.addItems([get_elo_display(k) for k in ELO_DISPLAY_MAP.keys()])
        self.combo_cr_elo.currentTextChanged.connect(self.save_creator_elo)

        self.combo_cr_color = NoWheelComboBox()
        self.combo_cr_color.addItem(tr_ui("repo_settings.color_white", "♔ Weiß"), "w")
        self.combo_cr_color.addItem(tr_ui("repo_settings.color_black", "♚ Schwarz"), "b")
        self.combo_cr_color.currentIndexChanged.connect(self.save_creator_color)

        self.lbl_cr_ana_status = QLabel("-")
        self.lbl_cr_ana_status.setStyleSheet("font-weight: bold; color: #333;")
        self.lbl_cr_db_cov = QLabel("-")
        self.lbl_cr_db_cov.setStyleSheet("font-weight: bold; color: #333;")

        self.combo_cr_comment_lang = NoWheelComboBox()
        self.combo_cr_comment_lang.addItem(tr_ui("repo_settings.comment_lang_auto", "Automatisch"), "auto")
        self.combo_cr_comment_lang.addItem(tr_ui("repo_settings.comment_lang_de", "🇩🇪 Deutsch"), "de")
        self.combo_cr_comment_lang.addItem(tr_ui("repo_settings.comment_lang_en", "🇬🇧 English"), "en")
        self.combo_cr_comment_lang.currentIndexChanged.connect(self.save_creator_comment_lang)

        self.lbl_cr_comment_stats = QLabel("-")
        self.lbl_cr_comment_stats.setStyleSheet("font-weight: bold; color: #333;")

        grid_meta.addWidget(QLabel(tr_ui("repo_settings.label_prio_elo", "🎯 Prio Score ELO:")), 0, 0); grid_meta.addWidget(self.combo_cr_elo, 0, 1)
        grid_meta.addWidget(QLabel(tr_ui("repo_settings.label_color", "🎨 Deine Farbe:")), 0, 2); grid_meta.addWidget(self.combo_cr_color, 0, 3)
        grid_meta.addWidget(QLabel(tr_ui("repo_settings.label_analysis_status", "🔍 Analyse-Status:")), 1, 0); grid_meta.addWidget(self.lbl_cr_ana_status, 1, 1)
        grid_meta.addWidget(QLabel(tr_ui("repo_settings.label_db_coverage", "🎯 Positionen mit Prio-Score:")), 1, 2); grid_meta.addWidget(self.lbl_cr_db_cov, 1, 3)
        grid_meta.addWidget(QLabel(tr_ui("repo_settings.label_comment_lang", "💬 Kommentar-Sprache:")), 2, 0); grid_meta.addWidget(self.combo_cr_comment_lang, 2, 1)
        grid_meta.addWidget(QLabel(tr_ui("repo_settings.label_comment_stats", "💬 Kommentare im Kurs:")), 2, 2); grid_meta.addWidget(self.lbl_cr_comment_stats, 2, 3)
        v_id.addLayout(grid_meta)

        # Description
        self.txt_cr_desc = QPlainTextEdit()
        self.txt_cr_desc.setPlaceholderText(tr_ui("repo_settings.description_placeholder", "Beschreibe dein Repertoire hier..."))
        self.txt_cr_desc.setMaximumHeight(scale(80))
        self.txt_cr_desc.textChanged.connect(self.save_creator_description)
        v_id.addWidget(QLabel(tr_ui("repo_settings.label_description", "📝 Beschreibung:")))
        v_id.addWidget(self.txt_cr_desc)

        # Cover Image
        h_cov = QHBoxLayout()
        self.lbl_cr_cover_preview = QLabel(tr_ui("repo_settings.no_image", "Kein Bild"))
        self.lbl_cr_cover_preview.setFixedSize(scale(56), scale(56))
        self.lbl_cr_cover_preview.setStyleSheet("border: 1px dashed #ccc; border-radius: 6px; background: #fff;")
        self.lbl_cr_cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_sel_cov = QPushButton(tr_widget("repo_settings.btn_select_image", "Bild wählen...")); btn_sel_cov.clicked.connect(self.select_creator_cover)
        self.btn_rem_cov = QPushButton(tr_widget("repo_settings.btn_remove", "Entfernen")); self.btn_rem_cov.clicked.connect(self.remove_creator_cover)
        h_cov.addWidget(QLabel(tr_ui("repo_settings.label_cover_image", "🖼️ Cover-Bild:")))
        h_cov.addWidget(self.lbl_cr_cover_preview)
        h_cov.addWidget(btn_sel_cov)
        h_cov.addWidget(self.btn_rem_cov)
        h_cov.addStretch()
        v_id.addLayout(h_cov)
        layout.addWidget(g_id)

        # 📈 Level-Struktur (Merged into this page as requested)
        self.g_cr_levels = QGroupBox(tr_widget("repo_settings.levels_title", "📈 Level-Struktur"))
        self.g_cr_levels.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.g_levels = self.g_cr_levels
        v_lvl = QVBoxLayout(self.g_cr_levels)
        v_lvl.setSpacing(scale(10))

        self.tbl_cr_levels = QTableWidget()
        self.tbl_cr_levels.setColumnCount(3)
        self.tbl_cr_levels.setHorizontalHeaderLabels([
            tr_ui("repo_settings.header_lvl", "Lvl"),
            tr_ui("repo_settings.header_name", "Bezeichnung"),
            tr_ui("repo_settings.header_target_elo", "Ziel-Elo (Trainer)")
        ])
        self.tbl_cr_levels.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_cr_levels.verticalHeader().setVisible(False)
        self.tbl_cr_levels.verticalHeader().setDefaultSectionSize(scale(42))
        self.tbl_cr_levels.setMinimumHeight(scale(160))
        self.tbl_cr_levels.itemDoubleClicked.connect(self.rename_creator_level)
        v_lvl.addWidget(self.tbl_cr_levels)

        h_lvl_btns = QHBoxLayout()
        btn_add_lvl = QPushButton(tr_widget("repo_settings.btn_add_level", "➕ Level hinzufügen"))
        btn_add_lvl.clicked.connect(self.add_creator_level)
        btn_del_lvl = QPushButton(tr_widget("repo_settings.btn_delete_level", "🗑️ Level löschen"))
        btn_del_lvl.clicked.connect(self.delete_creator_level)
        h_lvl_btns.addWidget(btn_add_lvl)
        h_lvl_btns.addWidget(btn_del_lvl)
        h_lvl_btns.addStretch()
        v_lvl.addLayout(h_lvl_btns)
        layout.addWidget(self.g_cr_levels)

        # Danger Zone: Delete Repertoire Permanently
        g_danger = QGroupBox(tr_widget("repo_settings.danger_zone_title", "⚠️ Gefahrenzone"))
        v_danger = QVBoxLayout(g_danger)
        btn_del_repo = QPushButton(tr_widget("repo_settings.btn_delete_repertoire", "🗑️ Repertoire unwiderruflich löschen"))
        btn_del_repo.setProperty("class", "Danger")
        btn_del_repo.clicked.connect(self.delete_creator_repertoire)
        v_danger.addWidget(btn_del_repo)
        layout.addWidget(g_danger)

        layout.addStretch()

    def refresh_creator_info(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend: return
        
        info = backend.get_repertoire_info(fast_only=True)
        r_name = info.get('name') or backend.active_repo_name or "-"
        self.lbl_cr_name.setText(r_name)
        
        self.txt_cr_desc.blockSignals(True)
        self.txt_cr_desc.setPlainText(info.get('description', '') or '')
        self.txt_cr_desc.blockSignals(False)

        elo = backend.get_meta("elo", "high").lower()
        self.combo_cr_elo.blockSignals(True)
        self.combo_cr_elo.setCurrentText(get_elo_display(elo))
        self.combo_cr_elo.blockSignals(False)

        color = backend.get_meta("color", "w")
        self.combo_cr_color.blockSignals(True)
        idx_col = self.combo_cr_color.findData(color)
        if idx_col >= 0: self.combo_cr_color.setCurrentIndex(idx_col)
        self.combo_cr_color.blockSignals(False)

        comment_lang = backend.get_meta("comment_language", "auto")
        self.combo_cr_comment_lang.blockSignals(True)
        idx_cl = self.combo_cr_comment_lang.findData(comment_lang)
        if idx_cl >= 0: self.combo_cr_comment_lang.setCurrentIndex(idx_cl)
        self.combo_cr_comment_lang.blockSignals(False)

        if getattr(backend, 'session', None):
            self.lbl_cr_comment_stats.setText(get_repertoire_comment_stats(backend.session))

        # Levels Table
        levels = backend.get_repertoire_levels()
        self.tbl_cr_levels.setRowCount(0)
        
        if hasattr(self, 'combo_prio_target'):
            self.combo_prio_target.clear()
            self.combo_global_level.clear()
            self.combo_prune_target_level.clear()
            self.combo_prune_target_level.addItem("Alle Level", None)

        for idx, lvl in enumerate(levels):
            self.tbl_cr_levels.insertRow(idx)
            it_ord = QTableWidgetItem(str(lvl['order']))
            it_ord.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_cr_levels.setItem(idx, 0, it_ord)

            it_nm = QTableWidgetItem(lvl['name'])
            it_nm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_cr_levels.setItem(idx, 1, it_nm)

            spin = NoWheelSpinBox()
            spin.setRange(800, 4000); spin.setSingleStep(50)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setValue(int(lvl.get('target_elo') or 1500))
            spin.valueChanged.connect(lambda val, lo=lvl['order']: backend.update_level_elo(lo, val))
            self.tbl_cr_levels.setCellWidget(idx, 2, spin)
            self.tbl_cr_levels.setRowHeight(idx, scale(42))

            if hasattr(self, 'combo_prio_target'):
                self.combo_prio_target.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
                self.combo_global_level.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])
                self.combo_prune_target_level.addItem(f"Lvl {lvl['order']}: {lvl['name']}", lvl['order'])

        self._update_levels_table_height()

        # Update extra info rows (Analyse-Status & Positionen mit Prio-Score)
        if hasattr(self, 'lbl_cr_ana_status') and hasattr(self, 'lbl_cr_db_cov') and backend.active_repo_name:
            if hasattr(self, 'creator_stats_loader') and self.creator_stats_loader and self.creator_stats_loader.isRunning():
                try:
                    self.creator_stats_loader.requestInterruption()
                    self.creator_stats_loader.wait(200)
                except: pass

            self.lbl_cr_ana_status.setText(tr_ui("repo_settings.status_loading", "Laden..."))
            self.lbl_cr_db_cov.setText(tr_ui("repo_settings.status_loading", "Laden..."))
            self.start_loading_animation()

            self.creator_stats_loader = TrainerRepoStatsWorker(self.main_window, backend.active_repo_name)
            self.creator_stats_loader.stats_ready.connect(self.on_creator_stats_loaded)
            self.creator_stats_loader.start()

        # Cover Preview
        self.update_creator_cover_preview(r_name)

    def _update_levels_table_height(self):
        if not hasattr(self, "tbl_cr_levels"): return
        self.tbl_cr_levels.verticalHeader().setDefaultSectionSize(scale(42))
        header_h = self.tbl_cr_levels.horizontalHeader().height()
        if header_h <= 0:
            header_h = scale(38)
        row_cnt = self.tbl_cr_levels.rowCount()
        rows_h = 0
        for i in range(row_cnt):
            r_h = self.tbl_cr_levels.rowHeight(i)
            rows_h += r_h if r_h > 0 else scale(42)
        total_h = header_h + rows_h + scale(8)
        self.tbl_cr_levels.setFixedHeight(max(scale(160), total_h))

    def on_creator_stats_loaded(self, info):
        if sip.isdeleted(self): return
        if hasattr(self, 'lbl_cr_ana_status') and not sip.isdeleted(self.lbl_cr_ana_status):
            self.lbl_cr_ana_status.setText(info.get('depth', '-'))

        if hasattr(self, 'lbl_cr_db_cov') and not sip.isdeleted(self.lbl_cr_db_cov):
            cov = info.get("coverage_pct", 0)
            covered = info.get("covered_pos", 0)
            total = info.get("total_pos", 0)
            from opening_fenix.core.translation import translator
            if translator.current_lang == "en":
                cov_str = f"{covered:,} / {total:,} ({cov:.1f}%)"
            else:
                cov_str = f"{covered:,} / {total:,} ({cov:.1f}%)".replace(",", ".")
            self.lbl_cr_db_cov.setText(cov_str)

    def update_creator_cover_preview(self, name):
        from opening_fenix.gui.dialogs import repo_settings_dialog
        u_dir = getattr(repo_settings_dialog, 'get_user_dir', get_user_dir)()
        cover_path = os.path.join(u_dir, "repertoires", name, "cover.png")
        if not os.path.exists(cover_path):
            from opening_fenix.creator.repo_selection_dialog import get_repertoire_cover_path
            cover_path = get_repertoire_cover_path(name)
        if cover_path and os.path.exists(cover_path):
            pix = QPixmap(cover_path).scaled(scale(56), scale(56), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.lbl_cr_cover_preview.setPixmap(pix)
            self.btn_rem_cov.setEnabled(True)
        else:
            self.lbl_cr_cover_preview.clear()
            self.lbl_cr_cover_preview.setText("Kein Bild")
            self.btn_rem_cov.setEnabled(False)

    def rename_active_repertoire(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend: return
        old_name = backend.active_repo_name
        new_name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name für das Repertoire:", QLineEdit.EchoMode.Normal, old_name)
        if ok and new_name and new_name != old_name:
            if hasattr(backend, "rename_repertoire"):
                succ, msg = backend.rename_repertoire(old_name, new_name)
                if succ:
                    self.populate_active_repo_dropdown()
                    idx = self.combo_active_repo.findData(new_name)
                    if idx >= 0: self.combo_active_repo.setCurrentIndex(idx)
                    self.refresh_creator_info()
                else: QMessageBox.warning(self, "Fehler", msg)

    def save_creator_elo(self, val):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not getattr(backend, 'session', None): return
        backend.set_meta("elo", get_elo_internal(val))
        backend.set_meta("lichess_elo", get_elo_internal(val))
        try:
            backend.session.commit()
        except:
            pass
        self.refresh_creator_info()

    def save_creator_color(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not getattr(backend, 'session', None): return
        backend.set_meta("color", self.combo_cr_color.currentData())
        backend.session.commit()

    def save_creator_comment_lang(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not getattr(backend, 'session', None): return
        backend.set_meta("comment_language", self.combo_cr_comment_lang.currentData())
        backend.session.commit()

    def save_creator_description(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not getattr(backend, 'session', None): return
        backend.set_meta("description", self.txt_cr_desc.toPlainText())
        backend.session.commit()

    def select_creator_cover(self):
        import shutil
        name = self.combo_active_repo.currentData() if hasattr(self, 'combo_active_repo') else None
        if not name and hasattr(self, 'l_n'):
            name = self.l_n.text()
        if not name or name == "-": return
        f_path, _ = QFileDialog.getOpenFileName(self, "Cover-Bild auswählen", "", "Bilder (*.png *.jpg *.jpeg)")
        if not f_path: return
        from opening_fenix.gui.dialogs import repo_settings_dialog
        u_dir = getattr(repo_settings_dialog, 'get_user_dir', get_user_dir)()
        repo_dir = os.path.join(u_dir, "repertoires", name)
        os.makedirs(repo_dir, exist_ok=True)
        ext = f_path.lower().split(".")[-1]
        if ext not in ("png", "jpg", "jpeg"): ext = "png"
        for f in os.listdir(repo_dir):
            if f.lower().startswith("cover."):
                try: os.remove(os.path.join(repo_dir, f))
                except: pass
        shutil.copy(f_path, os.path.join(repo_dir, f"cover.{ext}"))
        self.update_creator_cover_preview(name)

    def remove_creator_cover(self):
        name = self.combo_active_repo.currentData() if hasattr(self, 'combo_active_repo') else None
        if not name and hasattr(self, 'l_n'):
            name = self.l_n.text()
        if not name or name == "-": return
        from opening_fenix.gui.dialogs import repo_settings_dialog
        u_dir = getattr(repo_settings_dialog, 'get_user_dir', get_user_dir)()
        repo_dir = os.path.join(u_dir, "repertoires", name)
        if os.path.exists(repo_dir):
            for f in os.listdir(repo_dir):
                if f.lower().startswith("cover."):
                    try: os.remove(os.path.join(repo_dir, f))
                    except: pass
        self.update_creator_cover_preview(name)

    def add_creator_level(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend: return
        name, ok = QInputDialog.getText(self, "Level hinzufügen", "Name des neuen Levels:")
        if ok and name:
            backend.add_repertoire_level(name)
            self.refresh_creator_info()

    def rename_creator_level(self, item):
        if item.column() != 1: return
        backend = self.ensure_backend_for_active_repo()
        if not backend: return
        lvl_ord = int(self.tbl_cr_levels.item(item.row(), 0).text())
        new_name, ok = QInputDialog.getText(self, "Level Umbenennen", "Neuer Name für dieses Level:", QLineEdit.EchoMode.Normal, item.text())
        if ok and new_name and new_name != item.text():
            backend.update_level_name(lvl_ord, new_name)
            self.refresh_creator_info()

    def delete_creator_level(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend: return
        levels = backend.get_repertoire_levels()
        if len(levels) <= 1:
            QMessageBox.warning(self, "Fehler", "Mindestens 1 Level ist erforderlich.")
            return
        dlg = DeleteLevelDialog(levels, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            del_ord, target_ord, delete_moves = dlg.get_selection()
            if del_ord:
                backend.delete_repertoire_level(del_ord, target_level_order=target_ord, delete_moves=delete_moves)
                self.refresh_creator_info()

    def delete_creator_repertoire(self):
        name = self.combo_active_repo.currentData()
        if not name: return
        if QMessageBox.warning(self, "Löschen", f"Möchtest du '{name}' wirklich unwiderruflich löschen?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.main_window and hasattr(self.main_window, 'delete_repertoire_action'):
                self.main_window.delete_repertoire_action()
            self.populate_active_repo_dropdown()
            self.refresh_creator_info()

    # ─── PAGE 4.2: Alternate Good Moves and Prio Score (Creator) ────────────

    def init_page_creator_alt_moves(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        # 🤖 Engine Analysis
        g_eng = QGroupBox(tr_widget("repo_settings.engine_scan_title", "🤖 Engine-Analyse (Alternativ gute Züge)"))
        v_eng = QVBoxLayout(g_eng)
        lbl_eng_desc = QLabel(tr_ui("repo_settings.engine_scan_desc", "Berechne alternativ spielbare Züge für das gesamte Repertoire mit Stockfish."))
        lbl_eng_desc.setWordWrap(True)
        lbl_eng_desc.setStyleSheet("color: #666; font-size: 12px;")
        v_eng.addWidget(lbl_eng_desc)

        f_eng = QFormLayout()
        self.spin_scan_depth = NoWheelSpinBox(); self.spin_scan_depth.setRange(10, 50); self.spin_scan_depth.setValue(18)
        self.combo_scan_threads = NoWheelComboBox()
        for i in range(1, multiprocessing.cpu_count() + 1): self.combo_scan_threads.addItem(str(i))
        self.combo_scan_threads.setCurrentText(str(max(1, int(multiprocessing.cpu_count() * 0.25))))
        f_eng.addRow(tr_ui("repo_settings.search_depth_label", "Suchtiefe:"), self.spin_scan_depth)
        f_eng.addRow(tr_ui("repo_settings.threads_label", "Threads:"), self.combo_scan_threads)
        v_eng.addLayout(f_eng)

        self.btn_start_eng_scan = QPushButton(tr_widget("repo_settings.btn_start_scan", "🚀 Engine-Scan starten"))
        self.btn_start_eng_scan.clicked.connect(self.toggle_engine_scan)
        v_eng.addWidget(self.btn_start_eng_scan)

        self.pb_scan = QProgressBar()
        self.lbl_scan_status = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        v_eng.addWidget(self.lbl_scan_status)
        v_eng.addWidget(self.pb_scan)
        layout.addWidget(g_eng)

        # 🌐 Lichess DB & Priority Scores
        g_lich = QGroupBox(tr_widget("repo_settings.lichess_scan_title", "🌐 Lichess-Datenbank & Prio Scores"))
        v_lich = QVBoxLayout(g_lich)
        lbl_lich_desc = QLabel(tr_ui("repo_settings.lichess_scan_desc", "Lichess-Datenbank herunterladen und Popularitäts-/Prio-Scores berechnen lassen."))
        lbl_lich_desc.setWordWrap(True)
        lbl_lich_desc.setStyleSheet("color: #666; font-size: 12px;")
        v_lich.addWidget(lbl_lich_desc)

        h_fetch = QHBoxLayout()
        self.btn_start_lich_fetch = QPushButton(tr_widget("repo_settings.btn_fetch", "📡 Daten laden & Scores berechnen"))
        self.btn_start_lich_fetch.clicked.connect(self.toggle_lichess_fetch)
        btn_del_lich = QPushButton(tr_widget("repo_settings.btn_delete_lichess", "🗑️ Daten für diese Elo löschen"))
        btn_del_lich.clicked.connect(self.delete_active_lichess_data)
        h_fetch.addWidget(self.btn_start_lich_fetch)
        h_fetch.addWidget(btn_del_lich)
        v_lich.addLayout(h_fetch)

        self.pb_lich = QProgressBar()
        self.lbl_lich_status = QLabel(tr_ui("repo_settings.status_waiting", "Warte auf Start..."))
        v_lich.addWidget(self.lbl_lich_status)
        v_lich.addWidget(self.pb_lich)
        layout.addWidget(g_lich)

        layout.addStretch()

    def toggle_engine_scan(self):
        if hasattr(self, 'w_eng') and self.w_eng and self.w_eng.isRunning():
            self.lbl_scan_status.setText("Engine-Analyse wird gestoppt...")
            self.btn_start_eng_scan.setEnabled(False)
            self.w_eng.cancel()
            return

        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        ep = self.get_config().get("engine_path", "")
        if not ep or not os.path.exists(ep):
            QMessageBox.warning(self, "Engine fehlt", "Bitte konfiguriere zuerst einen gültigen Engine-Pfad unter 'Global Settings -> Chess Engine'.")
            return

        from opening_fenix.gui.dialogs import repo_settings_dialog
        thread_cls = getattr(repo_settings_dialog, 'AnalysisThread', AnalysisThread)
        self.w_eng = thread_cls(backend.active_repo_name, self.spin_scan_depth.value(), int(self.combo_scan_threads.currentText()), ep)
        self.pb_scan.setValue(0)
        self.w_eng.progress_signal.connect(self.pb_scan.setValue)
        
        def on_done(success, message):
            self.btn_start_eng_scan.setEnabled(True)
            self.btn_start_eng_scan.setText(tr_widget("repo_settings.btn_start_scan", "🚀 Engine-Scan starten"))
            self.lbl_scan_status.setText(message)
            self.refresh_creator_info()
            
        self.w_eng.finished_signal.connect(on_done)
        self.w_eng.start()
        self.btn_start_eng_scan.setText(tr_widget("repo_settings.btn_stop_scan", "🛑 Engine-Scan stoppen"))
        self.lbl_scan_status.setText("Engine Analyse läuft...")

    def toggle_lichess_fetch(self):
        if hasattr(self, 'w_lich') and self.w_lich and self.w_lich.isRunning():
            self.lbl_lich_status.setText("Lichess Import wird gestoppt...")
            self.btn_start_lich_fetch.setEnabled(False)
            self.w_lich.cancel()
            return

        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        target_elo = get_elo_internal(self.combo_cr_elo.currentText())
        self.w_lich = LichessImportThread(backend.active_repo_name, target_elo)
        self.pb_lich.setValue(0)
        self.w_lich.progress_signal.connect(self.pb_lich.setValue)
        if hasattr(self.w_lich, 'status_signal'):
            self.w_lich.status_signal.connect(self.lbl_lich_status.setText)
            
        def on_done(success, message):
            self.btn_start_lich_fetch.setEnabled(True)
            self.btn_start_lich_fetch.setText(tr_widget("repo_settings.btn_fetch", "📡 Daten laden & Scores berechnen"))
            self.lbl_lich_status.setText(message)
            self.refresh_creator_info()
            
        self.w_lich.finished_signal.connect(on_done)
        self.w_lich.start()
        self.btn_start_lich_fetch.setText(tr_widget("repo_settings.btn_stop_fetch", "🛑 Import stoppen"))
        self.lbl_lich_status.setText("Lichess Daten werden geladen...")

    def delete_active_lichess_data(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        elo_display = self.combo_cr_elo.currentText()
        if QMessageBox.question(self, "Löschen", f"Lichess-Daten für '{elo_display}' wirklich löschen?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            from opening_fenix.core.db.database import DatabaseManager
            from opening_fenix.core.db.models import LichessData
            db = DatabaseManager(get_repertoire_db_path(backend.active_repo_name))
            sess = db.get_session()
            cnt = sess.query(LichessData).filter(LichessData.elo_range == get_elo_internal(elo_display)).delete()
            sess.commit(); sess.close(); db.close()
            QMessageBox.information(self, "Erfolg", f"{cnt} Lichess-Einträge gelöscht.")
            self.refresh_creator_info()

    # ─── PAGE 4.3: Import & Export (Creator) ────────────────────────────────

    def init_page_creator_imex(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        g_imp = QGroupBox(tr_widget("repo_settings.import_title", "📥 Import"))
        v_imp = QVBoxLayout(g_imp)
        h_imp = QHBoxLayout()
        btn_paste = QPushButton(tr_widget("repo_settings.btn_paste_pgn", "📋 PGN Text einfügen"))
        btn_paste.clicked.connect(lambda: self.main_window.paste_pgn_dialog() if self.main_window and hasattr(self.main_window, 'paste_pgn_dialog') else None)
        btn_file = QPushButton(tr_widget("repo_settings.btn_select_pgn_file", "📄 PGN Datei auswählen"))
        btn_file.clicked.connect(lambda: self.main_window.import_pgn_file_dialog() if self.main_window and hasattr(self.main_window, 'import_pgn_file_dialog') else None)
        h_imp.addWidget(btn_paste); h_imp.addWidget(btn_file)
        v_imp.addLayout(h_imp)
        layout.addWidget(g_imp)

        g_exp = QGroupBox(tr_widget("repo_settings.export_management_title", "📤 Export & Management"))
        v_exp = QVBoxLayout(g_exp)
        h_exp = QHBoxLayout()
        btn_export = QPushButton(tr_widget("repo_settings.btn_export_simple", "📤 Export (PGN/DB)"))
        btn_export.clicked.connect(self.export_repertoire_dialog)
        btn_copy = QPushButton(tr_widget("repo_settings.btn_copy_course", "👯 Gesamten Kurs kopieren"))
        btn_copy.clicked.connect(self.copy_active_course)
        h_exp.addWidget(btn_export); h_exp.addWidget(btn_copy)
        v_exp.addLayout(h_exp)

        btn_share = QPushButton(tr_widget("repo_settings.btn_prepare_share", "🚀 Gesamter Kurs für Teilen vorbereiten"))
        btn_share.setProperty("class", "Primary")
        btn_share.clicked.connect(self.prepare_course_share)
        v_exp.addWidget(btn_share)
        layout.addWidget(g_exp)

        layout.addStretch()

    def export_repertoire_dialog(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend: return
        d = ExportDialog(backend, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            fmt, scope, transpos, max_l, lang = d.result_data
            if fmt == "pgn":
                p = QProgressDialog("Exportiere...", "Abbrechen", 0, 0, self)
                pgn = backend.export_pgn(None, transpos, lambda c: p.setValue(c) or p.wasCanceled(), max_l, language=lang)
                if pgn:
                    path, _ = QFileDialog.getSaveFileName(self, "Export Speichern", f"{backend.active_repo_name}.pgn", "PGN (*.pgn)")
                    if path:
                        with open(path, "w", encoding="utf-8") as f: f.write(pgn)
                        QMessageBox.information(self, "Erfolg", "PGN erfolgreich exportiert.")

    def copy_active_course(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        old_name = backend.active_repo_name
        new_name, ok = QInputDialog.getText(self, "Kurs kopieren", "Name für die Kopie:", QLineEdit.EchoMode.Normal, f"{old_name} - Kopie")
        if not (ok and new_name and new_name != old_name): return
        import shutil
        old_dir = get_repertoire_dir(old_name)
        new_dir = os.path.join(os.path.dirname(old_dir), new_name)
        try:
            shutil.copytree(old_dir, new_dir)
            old_db = os.path.join(new_dir, f"{old_name}.db")
            new_db = os.path.join(new_dir, f"{new_name}.db")
            if os.path.exists(old_db): os.rename(old_db, new_db)
            self.populate_active_repo_dropdown()
            QMessageBox.information(self, "Erfolg", f"Kurs wurde als '{new_name}' kopiert.")
        except Exception as e: QMessageBox.critical(self, "Fehler", str(e))

    def prepare_course_share(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        levels = backend.get_repertoire_levels()
        repo_dir = get_repertoire_dir(backend.active_repo_name)
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', backend.active_repo_name)
        for lvl in levels:
            pgn = backend.export_pgn(max_l=lvl['order'], transpos_mode=2, language="en")
            if pgn:
                safe_lvl = re.sub(r'[\\/*?:"<>|]', '_', lvl['name'])
                with open(os.path.join(repo_dir, f"{safe_name} L{lvl['order']}-{safe_lvl}.pgn"), "w", encoding="utf-8") as f:
                    f.write(pgn)
        QMessageBox.information(self, "Fertig", "Alle Level wurden als separate PGNs exportiert.")
        try: os.startfile(os.path.abspath(repo_dir))
        except: pass

    # ─── PAGE 4.4: Backups & Restore (Creator) ──────────────────────────────

    def init_page_creator_backups(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(16))
        layout.setContentsMargins(scale(24), scale(24), scale(24), scale(24))

        h_bar = QHBoxLayout()
        btn_now = QPushButton(tr_widget("repo_settings.btn_create_backup_now", "📸 Manuelles Backup jetzt erstellen"))
        btn_now.setProperty("class", "Primary")
        btn_now.clicked.connect(self.create_manual_backup)
        h_bar.addWidget(btn_now); h_bar.addStretch()
        layout.addLayout(h_bar)

        self.tbl_backups = QTableWidget()
        self.tbl_backups.setColumnCount(4)
        self.tbl_backups.setHorizontalHeaderLabels([
            tr_ui("repo_settings.col_backup_date", "Datum & Uhrzeit"),
            tr_ui("repo_settings.col_backup_details", "Details"),
            tr_ui("repo_settings.col_backup_size", "Größe"),
            tr_ui("repo_settings.col_backup_action", "Aktion")
        ])
        self.tbl_backups.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_backups.verticalHeader().setVisible(False)
        layout.addWidget(self.tbl_backups)

    def ensure_backend_for_active_repo(self):
        if self.backend and getattr(self.backend, 'active_repo_name', None):
            return self.backend
        if self.main_window and getattr(self.main_window, 'backend', None):
            return self.main_window.backend
        repo_name = getattr(self, 'selected_trainer_repo', None) or getattr(self, 'cr_active_repo_name', None)
        if not repo_name and self.backend:
            repo_name = getattr(self.backend, 'active_repo_name', None)
        if repo_name:
            if not self._owned_backend or getattr(self._owned_backend, 'active_repo_name', None) != repo_name:
                from opening_fenix.creator.creator_window import CreatorBackend
                self._owned_backend = CreatorBackend()
                self._owned_backend.load_repertoire(repo_name)
            return self._owned_backend
        return None

    def refresh_backups_list(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name or not hasattr(self, 'tbl_backups'): return
        backups = list_repertoire_backups(backend.active_repo_name)
        self.tbl_backups.setRowCount(len(backups))
        for row, b in enumerate(backups):
            dt_str = b["created_at"].strftime("%d.%m.%Y %H:%M:%S")
            size_mb = f"{b['size_bytes'] / (1024 * 1024):.2f} MB"
            self.tbl_backups.setItem(row, 0, QTableWidgetItem(dt_str))
            self.tbl_backups.setItem(row, 1, QTableWidgetItem(f"{b.get('total_moves', 0)} Züge"))
            self.tbl_backups.setItem(row, 2, QTableWidgetItem(size_mb))

            btn_rest = QPushButton("⏮️ Restore")
            btn_rest.clicked.connect(lambda _, p=b["path"], d=dt_str: self.restore_backup(p, d))
            self.tbl_backups.setCellWidget(row, 3, btn_rest)

    def create_manual_backup(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        create_repertoire_backup(backend.active_repo_name, trigger_type="manual")
        self.refresh_backups_list()
        QMessageBox.information(self, "Backup", "Manuelles Backup erfolgreich gespeichert!")

    create_manual_backup_now = create_manual_backup

    def restore_backup(self, path, dt_str):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        if QMessageBox.question(self, "Restore", f"Repertoire auf Stand {dt_str} zurücksetzen?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            restore_repertoire_from_backup(backend.active_repo_name, path)
            self.refresh_creator_info()
            self.refresh_backups_list()
            QMessageBox.information(self, "Erfolg", "Repertoire wiederhergestellt.")

    # ─── PAGE 4.5: Different Tools (Creator) ────────────────────────────────

    def init_page_creator_tools(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        # 🧹 Comments Cleaning & Translation
        g_clean = QGroupBox(tr_widget("repo_settings.tools_comments_title", "🧹 Kommentare bereinigen & übersetzen"))
        v_clean = QVBoxLayout(g_clean)
        btn_dedupe = QPushButton(tr_widget("repo_settings.btn_dedupe", "🔄 Doppelte Texte in Kommentaren entfernen"))
        btn_dedupe.clicked.connect(lambda: QMessageBox.information(self, tr_ui("repo_settings.dlg_cleanup_title", "Bereinigung"), f"{self.ensure_backend_for_active_repo().deduplicate_comments_in_repo()} Kommentare bereinigt."))
        btn_brackets = QPushButton(tr_widget("repo_settings.btn_brackets", "❌ Text in [eckigen Klammern] löschen"))
        btn_brackets.clicked.connect(lambda: QMessageBox.information(self, tr_ui("repo_settings.dlg_cleanup_title", "Bereinigung"), f"{self.ensure_backend_for_active_repo().clean_brackets_in_repo()} Kommentare bereinigt."))
        btn_trans = QPushButton(tr_widget("repo_settings.btn_transfer_comments", "🌐 Kommentare übertragen..."))
        btn_trans.clicked.connect(self.open_transfer_dialog)
        v_clean.addWidget(btn_dedupe); v_clean.addWidget(btn_brackets); v_clean.addWidget(btn_trans)
        layout.addWidget(g_clean)

        # ⚡ Priority Leveling & Global Moves
        g_prio = QGroupBox(tr_widget("repo_settings.tools_prio_title", "⚡ Prio-Leveling & Massen-Zuweisung"))
        v_prio = QVBoxLayout(g_prio)
        f_prio = QFormLayout()
        self.spin_prio_threshold = NoWheelSpinBox(); self.spin_prio_threshold.setRange(1, 100); self.spin_prio_threshold.setValue(10)
        self.combo_prio_target = NoWheelComboBox()
        f_prio.addRow(tr_ui("repo_settings.prio_threshold_label", "Schwellenwert (Prio > X%):"), self.spin_prio_threshold)
        f_prio.addRow(tr_ui("repo_settings.target_level_label", "Ziel-Level:"), self.combo_prio_target)
        v_prio.addLayout(f_prio)

        h_prio = QHBoxLayout()
        btn_p_prev = AutoAdjustButton(tr_widget("repo_settings.btn_prio_preview", "🔍 Vorschau"))
        btn_p_prev.clicked.connect(lambda: QMessageBox.information(self, tr_ui("repo_settings.dlg_preview_title", "Vorschau"), f"{self.ensure_backend_for_active_repo().get_priority_level_impact(self.spin_prio_threshold.value(), self.combo_prio_target.currentData())} Züge betroffen."))
        btn_p_app = AutoAdjustButton(tr_widget("repo_settings.btn_prio_apply", "🚀 Level anpassen"))
        btn_p_app.setProperty("class", "Primary")
        btn_p_app.clicked.connect(lambda: (self.ensure_backend_for_active_repo().apply_priority_level_update(self.spin_prio_threshold.value(), self.combo_prio_target.currentData()), self.refresh_creator_info(), QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), "Level angepasst.")))
        h_prio.addWidget(btn_p_prev); h_prio.addWidget(btn_p_app)
        v_prio.addLayout(h_prio)

        h_glob = QHBoxLayout()
        self.combo_global_level = NoWheelComboBox()
        btn_glob = AutoAdjustButton(tr_widget("repo_settings.btn_global_apply", "Alle Züge auf dieses Level setzen"))
        btn_glob.clicked.connect(lambda: (self.ensure_backend_for_active_repo().move_all_to_level(self.combo_global_level.currentData()), self.refresh_creator_info(), QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), "Alle Züge verschoben.")))
        h_glob.addWidget(self.combo_global_level); h_glob.addWidget(btn_glob)
        v_prio.addLayout(h_glob)
        layout.addWidget(g_prio)

        # 🗑️ Mass Prune
        g_prune = QGroupBox(tr_widget("repo_settings.tools_prune_title", "🗑️ Massen-Löschung nach Popularität"))
        v_prune = QVBoxLayout(g_prune)
        f_prune = QFormLayout()
        self.spin_prune_threshold = NoWheelSpinBox(); self.spin_prune_threshold.setRange(1, 90); self.spin_prune_threshold.setValue(5)
        self.combo_prune_target_level = NoWheelComboBox()
        f_prune.addRow(tr_ui("repo_settings.prune_threshold_label", "Prio < X%:"), self.spin_prune_threshold)
        f_prune.addRow(tr_ui("repo_settings.prune_target_level_label", "Fokus Level:"), self.combo_prune_target_level)
        v_prune.addLayout(f_prune)

        h_prune = QHBoxLayout()
        btn_pr_prev = AutoAdjustButton(tr_widget("repo_settings.btn_prune_preview", "🔍 Vorschau"))
        btn_pr_prev.clicked.connect(lambda: QMessageBox.information(self, tr_ui("repo_settings.dlg_preview_title", "Vorschau"), f"{self.ensure_backend_for_active_repo().get_low_popularity_prune_impact(self.spin_prune_threshold.value(), self.combo_prune_target_level.currentData())[0]} Züge werden gelöscht."))
        btn_pr_app = AutoAdjustButton(tr_widget("repo_settings.btn_prune_apply", "🗑️ Züge löschen"))
        btn_pr_app.setProperty("class", "Danger")
        btn_pr_app.clicked.connect(lambda: (self.ensure_backend_for_active_repo().apply_low_popularity_prune(self.spin_prune_threshold.value(), self.combo_prune_target_level.currentData()), self.refresh_creator_info(), QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), "Züge gelöscht.")))
        h_prune.addWidget(btn_pr_prev); h_prune.addWidget(btn_pr_app)
        v_prune.addLayout(h_prune)
        layout.addWidget(g_prune)

        layout.addStretch()

    def open_transfer_dialog(self):
        backend = self.ensure_backend_for_active_repo()
        if not backend or not backend.active_repo_name: return
        dlg = QDialog(self); dlg.setWindowTitle(tr_ui("repo_settings.dlg_transfer_title", "Kommentare übertragen"))
        v = QVBoxLayout(dlg)
        f = QFormLayout()
        c_s = NoWheelComboBox(); c_s.addItems(["DE", "EN", "ES", "FR", "IT", "RU"]); c_s.setCurrentText("DE")
        c_t = NoWheelComboBox(); c_t.addItems(["EN", "DE", "ES", "FR", "IT", "RU"]); c_t.setCurrentText("EN")
        f.addRow(tr_ui("repo_settings.dlg_transfer_source", "Quelle:"), c_s); f.addRow(tr_ui("repo_settings.dlg_transfer_target", "Ziel:"), c_t)
        v.addLayout(f)
        chk_o = QCheckBox(tr_widget("repo_settings.dlg_transfer_overwrite", "Überschreiben")); v.addWidget(chk_o)
        chk_r = QCheckBox(tr_widget("repo_settings.dlg_transfer_move", "Verschieben")); v.addWidget(chk_r)
        btn = QPushButton(tr_widget("repo_settings.dlg_transfer_btn", "Übertragen")); btn.setProperty("class", "Primary")
        btn.clicked.connect(lambda: (copy_repertoire_comments(backend.active_repo_name, c_s.currentText().lower(), c_t.currentText().lower(), chk_o.isChecked(), chk_r.isChecked()), dlg.accept(), self.refresh_creator_info(), QMessageBox.information(self, "Erfolg", "Kommentare übertragen.")))
        v.addWidget(btn); dlg.exec()

    # ─── PAGE 4.6: Database Diagnostics (Creator) ───────────────────────────

    def init_page_creator_diagnostics(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        g_diag = QGroupBox(tr_widget("repo_settings.diag_full_title", "🔍 Datenbank-Diagnose & Reparatur"))
        v_diag = QVBoxLayout(g_diag)
        v_diag.setSpacing(scale(12))

        btn_run_diag = QPushButton(tr_widget("repo_settings.btn_run_full_diag", "🔎 Datenbank-Diagnose & Reparatur ausführen"))
        btn_run_diag.clicked.connect(lambda: (DiagnosticDialog(self.ensure_backend_for_active_repo(), self).exec(), self.refresh_creator_info()))
        v_diag.addWidget(btn_run_diag)

        btn_var_names = QPushButton(tr_widget("repo_settings.btn_recalc_var_names", "🏷️ Variantennamen neu berechnen"))
        btn_var_names.clicked.connect(lambda: (self.ensure_backend_for_active_repo().reset_and_repair_variation_names(), QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), "Variantennamen neu berechnet.")))
        v_diag.addWidget(btn_var_names)

        btn_orphans = QPushButton(tr_widget("repo_settings.btn_clean_orphans", "🧹 Verwaiste Lichess-Daten bereinigen"))
        btn_orphans.clicked.connect(lambda: QMessageBox.information(self, tr_ui("repo_settings.dlg_done", "Fertig"), f"{self.ensure_backend_for_active_repo().cleanup_orphaned_lichess_data()} verwaiste Einträge gelöscht."))
        v_diag.addWidget(btn_orphans)

        layout.addWidget(g_diag)
        layout.addStretch()

    # ─── PAGE 4.7: Batch Maintenance Center (Creator) ───────────────────────

    def init_page_creator_maintenance(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))

        g_main = QGroupBox(tr_widget("repo_settings.maintenance_center_title", "🚜 Wartungs-Center (Stapelverarbeitung)"))
        v_main = QVBoxLayout(g_main)
        v_main.setSpacing(scale(14))

        self.main_table = QTableWidget()
        self.main_table.setColumnCount(6)
        self.main_table.setHorizontalHeaderLabels(["", tr_ui("repo_settings.col_repertoire", "Repertoire"), tr_ui("repo_settings.col_prio_elo", "Prio Elo"), tr_ui("repo_settings.col_analysis", "Analyse"), tr_ui("repo_settings.col_coverage", "Coverage"), tr_ui("repo_settings.col_progress", "Fortschritt")])
        self.main_table.verticalHeader().setVisible(False)
        self.main_table.setMinimumHeight(scale(200))
        self.main_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_main.addWidget(self.main_table)

        h_ctrl = QHBoxLayout()
        btn_all = QPushButton(tr_widget("repo_settings.btn_all", "Alle")); btn_none = QPushButton(tr_widget("repo_settings.btn_none", "Keine"))
        btn_all.clicked.connect(lambda: self._select_all_maintenance(True))
        btn_none.clicked.connect(lambda: self._select_all_maintenance(False))
        h_ctrl.addWidget(btn_all); h_ctrl.addWidget(btn_none); h_ctrl.addStretch()
        v_main.addLayout(h_ctrl)

        f_tasks = QFormLayout()
        self.chk_m_engine = QCheckBox(tr_widget("repo_settings.task_engine", "Engine Analyse")); self.chk_m_engine.setChecked(True)
        self.chk_m_lichess = QCheckBox(tr_widget("repo_settings.task_lichess", "Lichess Import")); self.chk_m_lichess.setChecked(True)
        self.chk_m_cleanup = QCheckBox(tr_widget("repo_settings.task_cleanup_lichess", "Verwaiste Daten bereinigen")); self.chk_m_cleanup.setChecked(True)
        self.chk_m_stats = QCheckBox(tr_widget("repo_settings.task_stats", "Prioritäten berechnen")); self.chk_m_stats.setChecked(True)
        f_tasks.addRow(tr_ui("repo_settings.tasks_label", "Aufgaben:"), self.chk_m_engine)
        f_tasks.addRow("", self.chk_m_lichess)
        f_tasks.addRow("", self.chk_m_cleanup)
        f_tasks.addRow("", self.chk_m_stats)
        v_main.addLayout(f_tasks)

        self.btn_start_batch = QPushButton(tr_widget("repo_settings.btn_start_batch_run", "🚀 Wartungs-Batch starten"))
        self.btn_start_batch.setProperty("class", "Primary")
        self.btn_start_batch.clicked.connect(self.toggle_batch_maintenance)
        v_main.addWidget(self.btn_start_batch)

        self.pb_m_overall = QProgressBar()
        self.lbl_m_overall = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        v_main.addWidget(self.lbl_m_overall); v_main.addWidget(self.pb_m_overall)

        layout.addWidget(g_main)
        layout.addStretch()
        self.refresh_maintenance_table()

    def _select_all_maintenance(self, checked):
        for r in range(self.main_table.rowCount()):
            cb = self.main_table.cellWidget(r, 0)
            if cb: cb.setChecked(checked)

    def refresh_maintenance_table(self, start_stats_worker=False):
        all_repos = list_all_repertoires()
        self.main_table.setRowCount(len(all_repos))
        worker_data = []
        for row, r in enumerate(all_repos):
            cb = QCheckBox(); cb.setChecked(True)
            self.main_table.setCellWidget(row, 0, cb)
            self.main_table.setItem(row, 1, QTableWidgetItem(r['name']))
            self.main_table.setItem(row, 2, QTableWidgetItem(get_elo_display(r['elo'])))
            self.main_table.setItem(row, 3, QTableWidgetItem("Bereit"))
            self.main_table.setItem(row, 4, QTableWidgetItem("-"))
            pb = QProgressBar(); pb.setValue(0); pb.setTextVisible(True)
            self.main_table.setCellWidget(row, 5, pb)
            worker_data.append({'row': row, 'name': r['name']})

        if start_stats_worker:
            self.stats_worker = RepertoireStatsWorker(worker_data)
            self.stats_worker.stats_ready.connect(lambda row, status, cov, elo: (
                self.main_table.setItem(row, 3, QTableWidgetItem(status)),
                self.main_table.setItem(row, 4, QTableWidgetItem(f"{cov:.1f}%"))
            ))
            self.stats_worker.start()

    def toggle_batch_maintenance(self):
        if hasattr(self, 'm_thread') and self.m_thread and self.m_thread.isRunning():
            self.lbl_m_overall.setText("Wartung wird gestoppt...")
            self.btn_start_batch.setEnabled(False)
            self.m_thread.cancel()
            return

        configs = []
        for r in range(self.main_table.rowCount()):
            cb = self.main_table.cellWidget(r, 0)
            if cb and cb.isChecked():
                nm = self.main_table.item(r, 1).text()
                elo_d = self.main_table.item(r, 2).text()
                configs.append({'name': nm, 'elo': get_elo_internal(elo_d)})

        if not configs:
            QMessageBox.warning(self, "Wartung", "Bitte mindestens ein Repertoire wählen.")
            return

        tasks = {'engine': self.chk_m_engine.isChecked(), 'lichess': self.chk_m_lichess.isChecked(),
                 'cleanup': self.chk_m_cleanup.isChecked(), 'stats': self.chk_m_stats.isChecked()}
        settings = {'depth': 18, 'threads': 2, 'path': self.get_config().get("engine_path", "")}

        self.m_thread = MaintenanceThread(configs, tasks, settings)
        self.pb_m_overall.setRange(0, len(configs))
        self.pb_m_overall.setValue(0)
        self.lbl_m_overall.setText(f"Starte Wartung für {len(configs)} Repertoires...")
        self.m_thread.overall_progress_signal.connect(lambda c, t, n: (self.pb_m_overall.setValue(c), self.lbl_m_overall.setText(f"Fortschritt ({c}/{t}): {n}")))
        
        def on_batch_done(success, message):
            self.btn_start_batch.setEnabled(True)
            self.btn_start_batch.setText("🚀 Wartungs-Batch starten")
            self.lbl_m_overall.setText(f"Fertig: {message}")
            self.refresh_creator_info()
            
        self.m_thread.finished_signal.connect(on_batch_done)
        self.m_thread.start()
        self.btn_start_batch.setText("🛑 Wartungs-Batch stoppen")

    # ─── Cleanup ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        workers = [getattr(self, 'stats_loader', None), getattr(self, 'creator_stats_loader', None),
                   getattr(self, 'stats_worker', None), getattr(self, 'w_eng', None),
                   getattr(self, 'w_lich', None), getattr(self, 'm_thread', None),
                   getattr(self, 'update_worker', None)]
        for w in workers:
            if w and w.isRunning():
                try: w.disconnect()
                except: pass
                if hasattr(w, 'cancel'): w.cancel()
                w.requestInterruption()
                if not w.wait(200):
                    try: w.terminate()
                    except: pass
                    
        if hasattr(self, "loading_timer") and self.loading_timer:
            try: self.loading_timer.stop()
            except: pass

        if self._owned_backend:
            try: self._owned_backend.close()
            except: pass
        super().closeEvent(event)
