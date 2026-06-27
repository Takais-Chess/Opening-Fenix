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
    QTableWidgetItem, QFileDialog, QAbstractItemView
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

class SingleRepoStatsWorker(QThread):
    stats_ready = pyqtSignal(dict)
    
    def __init__(self, backend):
        super().__init__()
        self.repo_name = backend.active_repo_name
        
    def run(self):
        temp_backend = None
        try:
            from opening_fenix.creator.creator_window import CreatorBackend
            if self.isInterruptionRequested():
                return
            temp_backend = CreatorBackend(is_test=True)
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
        self.setWindowTitle("Datenbank Diagnose")
        self.setMinimumWidth(scale(500))
        self.backend = backend
        self.setStyleSheet(get_bw_glass_style())
        self.init_ui()
        self.run_diagnostic()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(15))
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        self.lbl_info = QLabel("Überprüfe Repertoire-Struktur...")
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(self.lbl_info)
        
        self.txt_results = QTextEdit()
        self.txt_results.setReadOnly(True)
        self.txt_results.setStyleSheet("background-color: white; border-radius: 8px; border: 1px solid rgba(0,0,0,0.1); padding: 10px;")
        layout.addWidget(self.txt_results)
        
        h_btn = QHBoxLayout()
        self.btn_repair = QPushButton("🔧 Probleme beheben")
        self.btn_repair.setProperty("class", "Primary")
        self.btn_repair.clicked.connect(self.repair)
        self.btn_repair.setEnabled(False)
        self.btn_repair.setVisible(False)
        
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.accept)
        
        h_btn.addStretch()
        h_btn.addWidget(btn_close)
        h_btn.addWidget(self.btn_repair)
        layout.addLayout(h_btn)

    def run_diagnostic(self):
        self.issues = self.backend.run_diagnostic()
        msg = "<h3 style='margin-bottom: 10px;'>Diagnose-Ergebnis:</h3>"
        
        has_issues = False
        
        # Schema
        if self.issues['schema']:
            msg += f"<p style='color: #e74c3c;'><b>⚠️ Veraltetes Datenbankschema</b><br>Fehlende Spalten: {', '.join(self.issues['schema'])}</p>"
            has_issues = True
        else:
            msg += "<p style='color: #27ae60;'><b>✅ Datenbankschema</b><br>Das Schema ist aktuell.</p>"
            
        # Gaps
        if self.issues['gaps'] > 0:
            msg += f"<p style='color: #e74c3c;'><b>⚠️ Zug-Lücken</b><br>{self.issues['gaps']} fehlende Repertoire-Links gefunden.</p>"
            has_issues = True
        else:
            msg += "<p style='color: #27ae60;'><b>✅ Zug-Kette</b><br>Keine Lücken gefunden.</p>"
            
        # Duplicates
        if self.issues['duplicates'] > 0:
            msg += f"<p style='color: #e74c3c;'><b>⚠️ FEN-Duplikate</b><br>{self.issues['duplicates']} doppelte Stellungen gefunden.</p>"
            has_issues = True
        else:
            msg += "<p style='color: #27ae60;'><b>✅ Eindeutigkeit</b><br>Keine FEN-Duplikate gefunden.</p>"
            
        # Orphans
        if self.issues.get('orphans', 0) > 0:
            msg += f"<p style='color: #f39c12;'><b>ℹ️ Isolierte Stellungen</b><br>{self.issues['orphans']} Stellungen sind nicht erreichbar.</p>"
        else:
            msg += "<p style='color: #27ae60;'><b>✅ Erreichbarkeit</b><br>Alle Stellungen sind verknüpft.</p>"

        # Lichess Orphans
        if self.issues.get('orphaned_lichess', 0) > 0:
            msg += f"<p style='color: #e67e22;'><b>⚠️ Verwaiste Lichess-Daten</b><br>{self.issues['orphaned_lichess']} Cache-Einträge ohne zugehörige Stellung gefunden.</p>"
            has_issues = True
        else:
            msg += "<p style='color: #27ae60;'><b>✅ Lichess-Cache</b><br>Keine verwaisten Daten gefunden.</p>"
            
        self.txt_results.setHtml(msg)
        
        if has_issues:
            self.lbl_info.setText("Probleme identified! 🛠️")
            self.btn_repair.setEnabled(True)
            self.btn_repair.setVisible(True)
        else:
            self.lbl_info.setText("Alles gesund! ✨")
            self.btn_repair.setVisible(False)

    def repair(self):
        self.btn_repair.setEnabled(False)
        self.lbl_info.setText("Repariere Datenbank... ⌛")
        QApplication.processEvents()
        
        self.backend.repair_diagnostic_issues()
        
        self.txt_results.append("<br><hr><br><p style='color: #27ae60; font-weight: bold;'>Reparatur erfolgreich abgeschlossen!</p>")
        self.txt_results.append("<p>Alle identifizierten Löcher wurden gestopft und Duplikate bereinigt.</p>")
        self.lbl_info.setText("Reparatur fertig! ✅")
        if hasattr(self.parent(), 'refresh_info'):
            self.parent().refresh_info()


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
        self.lbl_name.setStyleSheet("font-weight: 600; font-size: 14px; color: #34495e;")
        layout.addWidget(self.lbl_name, 0, 1)
        
        lbl_elo_h = QLabel("Prio Elo:")
        lbl_elo_h.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        lbl_elo_h.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_elo_h, 0, 2)

        self.lbl_elo_val = QLabel(current_elo)
        self.lbl_elo_val.setFixedWidth(scale(70))
        self.lbl_elo_val.setStyleSheet("font-weight: bold; color: #2980b9; font-size: 13px; background: rgba(41, 128, 185, 0.05); border-radius: 4px; padding: 2px;")
        self.lbl_elo_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_elo_val, 0, 3)
        
        self.lbl_status = QLabel("Bereit")
        self.lbl_status.setStyleSheet("color: #95a5a6; font-size: 11px; font-style: italic;")
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
        self.setWindowTitle("Repertoire Einstellungen")
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
            ("📊 Repertoire-Daten", "Stammdaten und Level"),
            ("🎨 Design & Audio", "Optik und Sound"),
            ("📥 Import & Export", "Datentransfer"),
            ("🛠️ Repertoire-Werkzeuge", "Wartung & Analyse"),
            ("🚜 Wartung Center", "Stapelverarbeitung")
        ]
        
        for title, sub in sidebar_items:
            item = QListWidgetItem(title)
            self.sidebar.addItem(item)
            
        main_layout.addWidget(self.sidebar)

        # Content Area
        self.pages = QStackedWidget()
        
        # Initialize Pages
        self.page_gen = QWidget(); self.init_page_general(self.page_gen)
        self.page_design = QWidget(); self.init_page_design(self.page_design)
        self.page_imex = QWidget(); self.init_page_imex(self.page_imex)
        self.page_tools = QWidget(); self.init_page_tools(self.page_tools)
        self.page_maintenance = QWidget(); self.init_page_maintenance(self.page_maintenance)
        
        self.pages.addWidget(self.page_gen)
        self.pages.addWidget(self.page_design)
        self.pages.addWidget(self.page_imex)
        self.pages.addWidget(self.page_tools)
        self.pages.addWidget(self.page_maintenance)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
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
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # 📋 Repertoire Identität
        g_info = QGroupBox("📋 Repertoire Identität")
        v_info = QVBoxLayout(g_info)
        v_info.setSpacing(scale(15))
        v_info.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        
        # Name Row
        h_name_row = QHBoxLayout()
        lbl_name_h = QLabel("Name:")
        lbl_name_h.setStyleSheet("font-size: 14px; font-weight: 500; color: #555;")
        lbl_name_h.setFixedWidth(scale(120))
        
        self.l_n = QLabel()
        self.l_n.setStyleSheet("font-weight: bold; font-size: 16px; color: #2c3e50;")
        
        btn_rename = QPushButton("✎ Umbenennen")
        btn_rename.setFixedWidth(scale(140))
        btn_rename.clicked.connect(self.rename_repertoire)
        
        h_name_row.addWidget(lbl_name_h)
        h_name_row.addWidget(self.l_n)
        h_name_row.addStretch()
        h_name_row.addWidget(btn_rename)
        v_info.addLayout(h_name_row)

        # Description Row
        h_desc_row = QHBoxLayout()
        lbl_desc_h = QLabel("Beschreibung:")
        lbl_desc_h.setStyleSheet("font-size: 14px; font-weight: 500; color: #555;")
        lbl_desc_h.setFixedWidth(scale(120))
        lbl_desc_h.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        self.txt_description = QPlainTextEdit()
        self.txt_description.setPlaceholderText("Beschreibe dein Repertoire hier...")
        self.txt_description.setMinimumHeight(scale(140))
        self.txt_description.setMaximumHeight(scale(200))
        self.txt_description.textChanged.connect(self.save_description)
        
        h_desc_row.addWidget(lbl_desc_h)
        h_desc_row.addWidget(self.txt_description)
        v_info.addLayout(h_desc_row)

        # Elo Row
        # Elo Row
        h_elo_row = QHBoxLayout()
        lbl_elo_h = QLabel("Prio score ELO:")
        lbl_elo_h.setStyleSheet("font-size: 14px; font-weight: 500; color: #555;")
        lbl_elo_h.setFixedWidth(scale(120))
        
        self.combo_repertoire_elo = NoWheelComboBox()
        self.combo_repertoire_elo.addItems(list(ELO_DISPLAY_MAP.values()))
        self.combo_repertoire_elo.setFixedWidth(scale(200))
        self.combo_repertoire_elo.currentTextChanged.connect(self.save_repertoire_elo)
        
        h_elo_row.addWidget(lbl_elo_h)
        h_elo_row.addWidget(self.combo_repertoire_elo)
        h_elo_row.addStretch()
        v_info.addLayout(h_elo_row)
        
        # Color Row
        h_color_row = QHBoxLayout()
        lbl_color_h = QLabel("Deine Farbe:")
        lbl_color_h.setStyleSheet("font-size: 14px; font-weight: 500; color: #555;")
        lbl_color_h.setFixedWidth(scale(120))
        
        self.combo_repertoire_color = NoWheelComboBox()
        self.combo_repertoire_color.addItem("Weiß", "w")
        self.combo_repertoire_color.addItem("Schwarz", "b")
        self.combo_repertoire_color.setFixedWidth(scale(140))
        self.combo_repertoire_color.currentTextChanged.connect(self.save_repertoire_color)
        
        h_color_row.addWidget(lbl_color_h)
        h_color_row.addWidget(self.combo_repertoire_color)
        h_color_row.addStretch()
        v_info.addLayout(h_color_row)
        
        # Analysis Status Row
        h_ana_row = QHBoxLayout()
        lbl_ana_h = QLabel("Analyse-Status:")
        lbl_ana_h.setStyleSheet("font-size: 14px; font-weight: 500; color: #555;")
        lbl_ana_h.setFixedWidth(scale(120))
        self.lbl_ana_status = QLabel("-")
        self.lbl_ana_status.setStyleSheet("font-weight: 600; color: #2c3e50;")
        h_ana_row.addWidget(lbl_ana_h)
        h_ana_row.addWidget(self.lbl_ana_status)
        h_ana_row.addStretch()
        v_info.addLayout(h_ana_row)

        # DB Coverage Row
        h_cov_row = QHBoxLayout()
        lbl_cov_h = QLabel("Prio. Score Datenbank Elo:")
        lbl_cov_h.setStyleSheet("font-size: 14px; font-weight: 500; color: #555;")
        lbl_cov_h.setFixedWidth(scale(120))
        self.lbl_db_cov = QLabel("-")
        self.lbl_db_cov.setStyleSheet("font-weight: 600; color: #2c3e50;")
        h_cov_row.addWidget(lbl_cov_h)
        h_cov_row.addWidget(self.lbl_db_cov)
        h_cov_row.addStretch()
        v_info.addLayout(h_cov_row)
        
        layout.addWidget(g_info)
        
        layout.addWidget(g_info)

        # 📈 Level-Struktur
        g_levels = QGroupBox("📈 Level-Struktur")
        v_levels = QVBoxLayout(g_levels)
        
        self.tbl_levels = QTableWidget()
        self.tbl_levels.setColumnCount(3)
        self.tbl_levels.setHorizontalHeaderLabels(["Lvl", "Bezeichnung", "Ziel-Elo (Trainer)"])
        self.tbl_levels.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_levels.setMinimumHeight(scale(180))
        self.tbl_levels.verticalHeader().setVisible(False)
        self.tbl_levels.verticalHeader().setDefaultSectionSize(scale(45))
        self.tbl_levels.itemDoubleClicked.connect(self.rename_level)
        v_levels.addWidget(self.tbl_levels)
        
        h_lvl_btns = QHBoxLayout()
        btn_add_lvl = QPushButton("➕ Level hinzufügen")
        btn_add_lvl.clicked.connect(self.add_level)
        h_lvl_btns.addWidget(btn_add_lvl)
        h_lvl_btns.addStretch()
        v_levels.addLayout(h_lvl_btns)
        
        layout.addWidget(g_levels)

        # ⚠️ Gefahrenzone
        g_danger = QGroupBox("⚠️ Gefahrenzone")
        v_danger = QVBoxLayout(g_danger)
        btn_delete = QPushButton("🗑️ Repertoire unwiderruflich löschen")
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
        g_ui = QGroupBox("🎨 Oberfläche")
        f_ui = QFormLayout(g_ui)
        self.combo_theme = QComboBox()
        for t in THEMES.keys(): self.combo_theme.addItem(t)
        current_theme = self.main_window.config.get("theme", "Blau (Turnier)")
        idx = self.combo_theme.findText(current_theme)
        if idx >= 0: self.combo_theme.setCurrentIndex(idx)
        self.combo_theme.currentTextChanged.connect(self.change_board_theme)
        f_ui.addRow("Schachbrett Design:", self.combo_theme)
        layout.addWidget(g_ui)

        # 🔊 Sound & Sprache
        g_sound = QGroupBox("🔊 Sound & Sprache")
        f_sound = QFormLayout(g_sound)
        
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        try:
            vol_val = int(self.main_window.config.get("master_volume", 100))
        except (ValueError, TypeError):
            vol_val = 100
        self.slider_vol.setValue(vol_val)
        self.slider_vol.valueChanged.connect(self.change_volume)
        f_sound.addRow("Lautstärke:", self.slider_vol)
        
        self.combo_not = QComboBox()
        self.combo_not.addItem("Standard (English)", "en")
        self.combo_not.addItem("Deutsch (S,D,L,K,T)", "de")
        curr_not = self.main_window.config.get("notation_language", "en")
        idx_not = self.combo_not.findData(curr_not)
        if idx_not >= 0: self.combo_not.setCurrentIndex(idx_not)
        self.combo_not.currentIndexChanged.connect(self.change_notation_language)
        f_sound.addRow("Notation-Sprache:", self.combo_not)
        
        layout.addWidget(g_sound)

        # 🧱 Tab-Konfiguration
        g_tabs = QGroupBox("🧱 Tab-Konfiguration (Sichtbarkeit)")
        v_tabs = QVBoxLayout(g_tabs)
        lbl_tab_info = QLabel("Wähle aus, welche Tabs in der Creator-Ansicht (unten rechts) angezeigt werden sollen:")
        lbl_tab_info.setWordWrap(True)
        lbl_tab_info.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 10px;")
        v_tabs.addWidget(lbl_tab_info)
        
        active_tabs = self.main_window.config.get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
        self.chk_details = QCheckBox("📋 Details (Position-Infos)")
        self.chk_analysis = QCheckBox("🧠 Analyse (Engine && Lichess)")
        self.chk_transpositions = QCheckBox("🔄 Transpositionen (Varianten-Überschneidungen)")
        self.chk_holes = QCheckBox("🕳️ Such Modus (Repertoire-Lücken)")
        self.chk_kontrolle = QCheckBox("✅ Kontrolle (Variation Filtering)")
        
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
        g_import = QGroupBox("📥 Import-Möglichkeiten")
        v_import = QVBoxLayout(g_import)
        h_pgn = QHBoxLayout()
        
        pgn_tip = "Importiert Züge in das gewählte Level. Existierende Kommentare werden ergänzt (nicht überschrieben). Züge, die bereits vorhanden sind, behalten ihr Level bei (keine Duplikate)."
        
        btn_paste = QPushButton("📋 PGN Text einfügen")
        btn_paste.setToolTip(pgn_tip)
        btn_paste.clicked.connect(self.paste_pgn_dialog)
        
        btn_file = QPushButton("📄 PGN Datei auswählen")
        btn_file.setToolTip(pgn_tip)
        btn_file.clicked.connect(self.import_pgn_file_dialog)
        
        h_pgn.addWidget(btn_paste)
        h_pgn.addWidget(btn_file)
        v_import.addLayout(h_pgn)
        layout.addWidget(g_import)

        # 📤 Export && Management
        g_export = QGroupBox("📤 Export && Management")
        v_export = QVBoxLayout(g_export)
        
        h_manage = QHBoxLayout()
        btn_simple_export = QPushButton("📤 Export (PGN/DB)")
        btn_simple_export.clicked.connect(self.export_repertoire)
        
        btn_copy_repo = QPushButton("👯 Gesamten Kurs kopieren")
        btn_copy_repo.setToolTip("Erstellt eine vollständige 1:1 Kopie dieses Repertoires unter einem neuen Namen.")
        btn_copy_repo.clicked.connect(self.copy_repertoire_action)
        
        h_manage.addWidget(btn_simple_export)
        h_manage.addWidget(btn_copy_repo)
        v_export.addLayout(h_manage)
        
        v_export.addSpacing(scale(15))
        btn_full_export = QPushButton("🚀 Gesamter Kurs für Teilen vorbereiten")
        btn_full_export.setToolTip("Exportiert jedes Level als einzelne PGN-Datei, erstellt eine README-Übersicht und öffnet den Ordner zur Weitergabe.")
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

        # 1. 🔍 Diagnose && Instandhaltung
        g_diag = QGroupBox("🔍 Diagnose && Instandhaltung")
        v_diag = QVBoxLayout(g_diag)
        btn_diag = QPushButton("🔎 Datenbank-Diagnose && Reparatur")
        btn_diag.clicked.connect(self.run_structure_repair)
        btn_names = QPushButton("🏷️ Variantennamen neu berechnen")
        btn_names.clicked.connect(self.run_variation_name_repair)
        
        self.btn_wipe_lichess = QPushButton("🗑️ Lichess Datenbank Daten Löschen für alle Elos außer [...]")
        self.btn_wipe_lichess.clicked.connect(self.wipe_other_lichess_data_action)
        self.btn_wipe_lichess.setStyleSheet("color: #e67e22; font-weight: 500;")

        btn_cleanup_lichess = QPushButton("🧹 Verwaiste Lichess-Daten bereinigen")
        btn_cleanup_lichess.clicked.connect(self.run_lichess_orphan_cleanup)
        btn_cleanup_lichess.setToolTip("Entfernt Lichess-Explorer-Daten für Stellungen, die nicht mehr in deinem Repertoire existieren.")

        v_diag.addWidget(btn_diag)
        v_diag.addWidget(btn_names)
        v_diag.addWidget(self.btn_wipe_lichess)
        v_diag.addWidget(btn_cleanup_lichess)
        layout.addWidget(g_diag)

        # 2. 🧹 Kommentare Bereinigen
        g_clean = QGroupBox("🧹 Kommentare Bereinigen")
        v_clean = QVBoxLayout(g_clean)
        btn_dedupe = QPushButton("🔄 Doppelte Texte in Kommentaren entfernen")
        btn_dedupe.clicked.connect(self.clean_comments)
        btn_brackets = QPushButton("❌ Text in [eckigen Klammern] löschen")
        btn_brackets.clicked.connect(self.clean_brackets)
        v_clean.addWidget(btn_dedupe)
        v_clean.addWidget(btn_brackets)
        layout.addWidget(g_clean)

        # 3. 🤖 Engine Analyse
        g_engine = QGroupBox("🤖 Alternativ gute Züge berechnen mit Engine Analyse des gesamten Reperotires")
        f_engine = QFormLayout(g_engine)
        self.txt_engine_path = QLineEdit()
        self.txt_engine_path.setText(self.main_window.config.get("engine_path", ""))
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(scale(30))
        btn_browse.clicked.connect(self.browse_engine_path)
        h_path = QHBoxLayout(); h_path.addWidget(self.txt_engine_path); h_path.addWidget(btn_browse)
        f_engine.addRow("Engine Pfad:", h_path)
        
        # Defaults: 18 depth and 25% CPU Threads
        self.s_d = NoWheelSpinBox(); self.s_d.setRange(10, 50); self.s_d.setValue(18)
        self.c_threads = NoWheelComboBox()
        cpu_count = multiprocessing.cpu_count()
        for i in range(1, cpu_count + 1): self.c_threads.addItem(str(i))
        default_threads = max(1, int(cpu_count * 0.25))
        self.c_threads.setCurrentText(str(default_threads))
        f_engine.addRow("Suchtiefe:", self.s_d)
        f_engine.addRow("Threads:", self.c_threads)
        
        btn_start_eng = QPushButton("🚀 Engine-Scan starten")
        btn_start_eng.clicked.connect(self.start_analysis)
        f_engine.addRow("", btn_start_eng)
        self.pb_eng = QProgressBar(); self.l_eng_status = QLabel("Bereit")
        v_eng_prog = QVBoxLayout()
        v_eng_prog.addWidget(self.l_eng_status); v_eng_prog.addWidget(self.pb_eng)
        f_engine.addRow("Fortschritt:", v_eng_prog)
        layout.addWidget(g_engine)

        # 4. 🌐 Lichess Datenbank Daten herunterladen und Prio scores berechnen lassen
        g_lichess = QGroupBox("🌐 Lichess Datenbank Daten herunterladen und Prio scores berechnen lassen")
        v_lich = QVBoxLayout(g_lichess)
        f_token = QFormLayout()
        
        h_token_row = QHBoxLayout()
        self.txt_lichess_token = QLineEdit()
        self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_lichess_token.setText(self.main_window.config.get("lichess_token", ""))
        self.txt_lichess_token.textChanged.connect(self.on_token_changed)
        
        btn_toggle_token = QPushButton("👁️")
        btn_toggle_token.setFixedWidth(scale(35))
        btn_toggle_token.setCheckable(True)
        btn_toggle_token.toggled.connect(lambda checked: self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        
        h_token_row.addWidget(self.txt_lichess_token)
        h_token_row.addWidget(btn_toggle_token)
        f_token.addRow("API-Token:", h_token_row)
        
        # Elo Selection (Read-only / display based on settings)
        self.lbl_lichess_target_elo = QLabel("Ziel-Elo: -")
        self.lbl_lichess_target_elo.setStyleSheet("font-weight: bold; color: #2980b9; background: rgba(41, 128, 185, 0.1); border-radius: 4px; padding: 5px;")
        f_token.addRow("Import-Fokus:", self.lbl_lichess_target_elo)
        v_lich.addLayout(f_token)
        
        h_fetch = QHBoxLayout()
        btn_fetch = QPushButton("📡 Daten laden && Scores berechnen")
        btn_fetch.clicked.connect(self.start_fetch)
        btn_delete_l = QPushButton("🗑️ Daten für diese Elo löschen")
        btn_delete_l.clicked.connect(self.delete_lichess_action)
        h_fetch.addWidget(btn_fetch); h_fetch.addWidget(btn_delete_l)
        v_lich.addLayout(h_fetch)
        self.pb_lich = QProgressBar(); self.l_lich_status = QLabel("Warte auf Start...")
        v_lich.addWidget(self.l_lich_status); v_lich.addWidget(self.pb_lich)
        layout.addWidget(g_lichess)

        # 5. ⚡ Prio basiertes Leveling
        g_prio = QGroupBox("⚡ Alle Züge basierend auf dem Prio Score auf ein Level niedrigere Level setzten")
        v_prio = QVBoxLayout(g_prio)
        f_prio = QFormLayout()
        self.spin_prio_threshold = QSpinBox(); self.spin_prio_threshold.setRange(1, 100); self.spin_prio_threshold.setSuffix(" %"); self.spin_prio_threshold.setValue(10)
        self.combo_prio_target = QComboBox()
        f_prio.addRow("Schwellenwert (Prio > X):", self.spin_prio_threshold)
        f_prio.addRow("Ziel-Level:", self.combo_prio_target)
        v_prio.addLayout(f_prio)
        h_prio_btns = QHBoxLayout()
        self.btn_prio_preview = QPushButton("🔍 Auswirkung prüfen"); self.btn_prio_preview.clicked.connect(self.preview_priority_level)
        self.btn_prio_apply = QPushButton("🚀 Level anpassen"); self.btn_prio_apply.setProperty("class", "Primary"); self.btn_prio_apply.clicked.connect(self.apply_priority_level)
        h_prio_btns.addWidget(self.btn_prio_preview); h_prio_btns.addWidget(self.btn_prio_apply)
        v_prio.addLayout(h_prio_btns)
        layout.addWidget(g_prio)

        # 6. 🏗️ Globale Zuweisungen
        g_global = QGroupBox("🏗️ Alle Züge auf ein gewisses Level setzen")
        v_global = QVBoxLayout(g_global)
        h_global = QHBoxLayout()
        self.combo_global_level = QComboBox()
        btn_global_apply = QPushButton("Alle Züge auf dieses Level setzen")
        btn_global_apply.clicked.connect(self.global_move_all_level)
        h_global.addWidget(self.combo_global_level); h_global.addWidget(btn_global_apply)
        v_global.addLayout(h_global)
        layout.addWidget(g_global)

        layout.addStretch()

    def init_page_maintenance(self, page):
        layout = QVBoxLayout(page)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        # 🚜 Wartungs-Center (Batch)
        g_main = QGroupBox("🚜 Wartungs-Center (Batch)")
        v_main = QVBoxLayout(g_main)
        v_main.setSpacing(scale(15))
        v_main.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        # --- Section 1: Repertoires ---
        lbl_batch = QLabel("1. Wähle Repertoires aus, die verarbeitet werden sollen:")
        lbl_batch.setStyleSheet("font-weight: bold; color: #444;")
        v_main.addWidget(lbl_batch)
        
        self.main_table = QTableWidget()
        self.main_table.setColumnCount(6)
        self.main_table.setHorizontalHeaderLabels([
            "", "Repertoire Name", "Prio Elo", "Analyse-Status", "Datenbank-Coverage", "Fortschritt"
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
        btn_all = QPushButton("Alle")
        btn_none = QPushButton("Keine")
        btn_all.clicked.connect(lambda: self._select_all_maintenance_repos(True))
        btn_none.clicked.connect(lambda: self._select_all_maintenance_repos(False))
        h_ctrl.addWidget(btn_all); h_ctrl.addWidget(btn_none); h_ctrl.addStretch()
        v_main.addLayout(h_ctrl)
        
        # --- Section 2: Tasks ---
        v_main.addSpacing(scale(10))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken); line.setStyleSheet("background-color: rgba(0,0,0,0.05);")
        v_main.addWidget(line)
        v_main.addSpacing(scale(10))

        lbl_tasks = QLabel("2. Aufgaben auswählen && konfigurieren:")
        lbl_tasks.setStyleSheet("font-weight: bold; color: #444;")
        v_main.addWidget(lbl_tasks)

        f_conf = QFormLayout()
        self.chk_m_engine = QCheckBox("Engine Analyse (Alternativen)")
        self.chk_m_engine.setChecked(True)
        self.chk_m_lichess = QCheckBox("Lichess Import (Trend-Daten)")
        self.chk_m_lichess.setChecked(True)
        self.chk_m_cleanup_lichess = QCheckBox("Verwaiste Lichess-Daten bereinigen")
        self.chk_m_cleanup_lichess.setChecked(True)
        self.chk_m_stats = QCheckBox("Statistiken && Prioritäten berechnen")
        self.chk_m_stats.setChecked(True)
        
        v_tasks = QVBoxLayout()
        v_tasks.addWidget(self.chk_m_engine)
        v_tasks.addWidget(self.chk_m_lichess)
        v_tasks.addWidget(self.chk_m_cleanup_lichess)
        v_tasks.addWidget(self.chk_m_stats)
        f_conf.addRow("Aufgaben:", v_tasks)
        
        self.spin_m_depth = QSpinBox()
        self.spin_m_depth.setRange(10, 40)
        try:
            depth_val = int(self.main_window.config.get("engine_depth", 20))
        except (ValueError, TypeError):
            depth_val = 20
        self.spin_m_depth.setValue(depth_val)
        f_conf.addRow("Engine Tiefe:", self.spin_m_depth)
        
        self.spin_m_threads = QSpinBox()
        self.spin_m_threads.setRange(1, multiprocessing.cpu_count())
        self.spin_m_threads.setValue(max(1, multiprocessing.cpu_count() - 1))
        f_conf.addRow("Engine Threads:", self.spin_m_threads)
        v_main.addLayout(f_conf)
        
        # --- Section 3: Execution ---
        v_main.addSpacing(scale(15))
        self.btn_m_start = QPushButton("🚀 Wartungs-Batch starten")
        self.btn_m_start.setProperty("class", "Primary")
        self.btn_m_start.setMinimumHeight(scale(50))
        self.btn_m_start.clicked.connect(self.start_centralized_maintenance)
        v_main.addWidget(self.btn_m_start)
        
        self.pb_m_overall = QProgressBar(); self.lbl_m_overall = QLabel("Bereit")
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
        val, ok = QInputDialog.getInt(self, "Globales Elo", "Ziel-Elo für ALLE Level setzen:", 1500, 800, 4000)
        if ok and self.backend:
            levels = self.backend.get_repertoire_levels()
            for lvl in levels:
                self.backend.update_level_elo(lvl['order'], val)
            self.refresh_info()
            QMessageBox.information(self, "Erfolg", f"Alle Level wurden auf {val} Elo gesetzt.")

    def delete_level(self):
        levels = self.backend.get_repertoire_levels()
        if not levels: return
        last = levels[-1]
        
        reply = QMessageBox.question(self, "Level löschen", 
            f"Möchtest du das Level '{last['name']}' wirklich löschen?\n\nACHTUNG: Züge in diesem Level werden NICHT gelöscht, behalten aber ihre Level-Nummer (was zu Inkonsistenzen führen kann).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            # Backend usually needs a specific method. Let's assume we can delete by order or name.
            # If backend doesn't have it, we manually delete from session.
            try:
                lvl_obj = self.backend.session.query(RepertoireLevel).filter_by(order=last['order']).first()
                if lvl_obj:
                    self.backend.session.delete(lvl_obj)
                    self.backend.session.commit()
                    self.refresh_info()
            except Exception as e:
                QMessageBox.critical(self, "Fehler", str(e))

    def preview_priority_level(self):
        threshold = self.spin_prio_threshold.value()
        target_lvl = self.combo_prio_target.currentData()
        if not target_lvl: return
        
        impact = self.backend.get_priority_level_impact(threshold, target_lvl)
        QMessageBox.information(self, "Vorschau", f"Bei einer Priorität > {threshold}% würden {impact} Züge in das Level {target_lvl} verschoben werden.")

    def apply_priority_level(self):
        threshold = self.spin_prio_threshold.value()
        target_lvl = self.combo_prio_target.currentData()
        if not target_lvl: return
        
        impact = self.backend.get_priority_level_impact(threshold, target_lvl)
        if impact == 0:
            QMessageBox.information(self, "Info", "Keine Züge gefunden, die dem Kriterium entsprechen.")
            return
            
        reply = QMessageBox.question(self, "Anwenden", f"{impact} Züge werden auf Level {target_lvl} gesetzt. Fortfahren?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            modified = self.backend.apply_priority_level_update(threshold, target_lvl)
            self.refresh_info()
            QMessageBox.information(self, "Fertig", f"{modified} Züge wurden aktualisiert.")

    def clean_comments(self):
        n = self.backend.deduplicate_comments_in_repo()
        QMessageBox.information(self, "Bereinigung", f"Fertig! In {n} Stellungen wurden doppelte Kommentar-Texte entfernt.")

    def clean_brackets(self):
        n = self.backend.clean_brackets_in_repo()
        QMessageBox.information(self, "Bereinigung", f"Fertig! In {n} Stellungen wurde Text in [eckigen Klammern] gelöscht.")

    def global_move_all_level(self):
        target_lvl = self.combo_global_level.currentData()
        if not target_lvl: return
        
        reply = QMessageBox.question(self, "Globale Zuweisung", 
            f"Möchtest du wirklich ALLE Züge des Repertoires auf Level {target_lvl} setzen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            n = self.backend.move_all_to_level(target_lvl)
            self.refresh_info()
            QMessageBox.information(self, "Erfolg", f"{n} Züge wurden auf Level {target_lvl} gesetzt.")

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

    def rename_repertoire(self):
        old_name = self.backend.active_repo_name
        new_name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name für das Repertoire:", QLineEdit.EchoMode.Normal, old_name)
        if ok and new_name and new_name != old_name:
            # Use the new robust renaming logic (filesystem + profiles)
            if hasattr(self.backend, "rename_repertoire"):
                success, msg = self.backend.rename_repertoire(old_name, new_name)
                if success:
                    QMessageBox.information(self, "Erfolg", msg)
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
                    QMessageBox.warning(self, "Fehler", msg)
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
            new_name, ok = QInputDialog.getText(self, "Level Umbenennen", "Neuer Name für dieses Level:", QLineEdit.EchoMode.Normal, old_name)
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
            self.lbl_ana_status.setText("Laden.")
            self.lbl_db_cov.setText("Laden.")
        else:
            self.lbl_ana_status.setText(info.get('depth', '-'))
            cov = info.get("coverage_pct", 0)
            elo_display = get_elo_display(info.get('elo', 'N/A'))
            self.lbl_db_cov.setText(f"{elo_display} [{cov:.1f}% Abdeckung]")
        
        # Sync Lichess UI
        elo_display = get_elo_display(elo)
        if hasattr(self, 'lbl_lichess_target_elo'):
            self.lbl_lichess_target_elo.setText(f"Ziel-Elo: {elo_display}")
        if hasattr(self, 'btn_wipe_lichess'):
            self.btn_wipe_lichess.setText(f"🗑️ Lichess Datenbank Daten Löschen für alle Elos außer [{elo_display}]")

        # Refresh Table
        self.tbl_levels.setRowCount(0)
        levels = self.backend.get_repertoire_levels()
        
        # Tools Level Combos
        self.combo_prio_target.clear()
        self.combo_global_level.clear()

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
            
            spin = NoWheelSpinBox()
            spin.setRange(800, 4000)
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setStyleSheet("QSpinBox { border: none; background: transparent; font-size: 16px; font-weight: 500; } QSpinBox:focus { background: rgba(0,0,0,0.05); }")
            spin.setValue(lvl.get('target_elo', 1500))
            spin.setMinimumHeight(scale(40))
            spin.valueChanged.connect(lambda val, lo=lvl['order']: self.backend.update_level_elo(lo, val))
            self.tbl_levels.setCellWidget(idx, 2, spin)
            
        # self._refresh_maintenance_repo_list()  <-- Lazy loaded now!



    def delete_repertoire_action(self):
        if QMessageBox.warning(self, "Löschen", "Repertoire wirklich unwiderruflich löschen?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
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
                p = QProgressDialog("Exportiere...", "Abbrechen", 0, 0, self)
                pgn = self.backend.export_pgn(start, transpos_mode, lambda c: p.setValue(c) or p.wasCanceled(), max_l, language=lang)
                if pgn:
                    path, _ = QFileDialog.getSaveFileName(self, "Export Speichern", f"{self.backend.active_repo_name}.pgn", "PGN Dateien (*.pgn)")
                    if path:
                        with open(path, "w", encoding="utf-8") as f: f.write(pgn)
                        QMessageBox.information(self, "Erfolg", "Export abgeschlossen.")
            else:
                path, _ = QFileDialog.getSaveFileName(self, "Export Speichern", f"{self.backend.active_repo_name}.db", "SQLite Datenbank (*.db)")
                if path:
                    s, m = self.backend.export_db(path, start)
                    (QMessageBox.information if s else QMessageBox.warning)(self, "Ergebnis", m)

    def copy_repertoire_action(self):
        """Duplicates the current repertoire folder and its database."""
        old_name = self.backend.active_repo_name
        if not old_name: return
        
        new_name, ok = QInputDialog.getText(self, "Kurs kopieren", "Name für die Kopie:", QLineEdit.EchoMode.Normal, f"{old_name} - Kopie")
        if not (ok and new_name and new_name != old_name): return
        
        # Validate name
        if any(c in new_name for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Ungültiger Name", "Der Name enthält ungültige Zeichen.")
            return

        import shutil
        from opening_fenix.core.utils import get_repertoire_dir
        
        old_dir = get_repertoire_dir(old_name)
        new_dir = os.path.join(os.path.dirname(old_dir), new_name)
        
        if os.path.exists(new_dir):
            QMessageBox.warning(self, "Fehler", "Ein Repertoire mit diesem Namen existiert bereits.")
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

            QMessageBox.information(self, "Erfolg", f"Repertoire wurde als '{new_name}' kopiert.\nDu kannst es jetzt über das Hauptmenü laden.")
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Kopieren", str(e))

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
        lang_sel, ok = QInputDialog.getItem(self, "Sprache", "Notation für Export:", ["Standard (English)", "Deutsch"], 0, False)
        if not ok: return
        lang = "de" if lang_sel == "Deutsch" else "en"
        progress = QProgressDialog("Exportiere...", "Abbrechen", 0, len(levels), self)
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
            QMessageBox.information(self, "Fertig", "Repertoire exportiert.")
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
    def run_variation_name_repair(self): self.backend.reset_and_repair_variation_names()
    def browse_engine_path(self):
        p, _ = QFileDialog.getOpenFileName(self, "Engine", "", "*.exe")
        if p: self.txt_engine_path.setText(p); self.main_window.config["engine_path"] = p; self.main_window.save_config()

    def start_analysis(self):
        ep = self.txt_engine_path.text()
        if not ep or not os.path.exists(ep):
            QMessageBox.warning(self, "Engine fehlt", "Bitte konfiguriere zuerst einen gültigen Engine-Pfad.")
            return

        self.w_eng = AnalysisThread(self.backend.active_repo_name, self.s_d.value(), int(self.c_threads.currentText()), ep)
        self.pb_eng.setRange(0, 100)
        self.pb_eng.setValue(0)
        self.w_eng.progress_signal.connect(self.pb_eng.setValue)
        
        def on_finished(success, message):
            try:
                if not sip.isdeleted(self):
                    self.l_eng_status.setText(message)
                    if success:
                        QMessageBox.information(self, "Engine-Analyse fertig", message)
                    else:
                        QMessageBox.warning(self, "Engine-Analyse Fehler", message)
            except: pass
            
        self.w_eng.finished_signal.connect(on_finished)
        self.w_eng.start()
        self.l_eng_status.setText("Engine Analyse läuft...")

    def on_token_changed(self, text): self.main_window.config["lichess_token"] = text; self.main_window.save_config()

    def start_fetch(self):
        # Use repertoire-specific Elo category instead of global config
        target_elo_display = self.combo_repertoire_elo.currentText()
        target_elo = get_elo_internal(target_elo_display)
        self.w_lich = LichessImportThread(self.backend.active_repo_name, target_elo)
        self.pb_lich.setRange(0, 100)
        self.pb_lich.setValue(0)
        self.w_lich.progress_signal.connect(self.pb_lich.setValue)
        
        def on_finished(success, message):
            self.l_lich_status.setText(message)
            if success:
                QMessageBox.information(self, "Lichess Import fertig", message)
            else:
                QMessageBox.warning(self, "Lichess Import Fehler", message)
                
        self.w_lich.finished_signal.connect(on_finished)
        self.w_lich.start()
        self.l_lich_status.setText("Lichess Daten werden geladen...")


    def delete_lichess_action(self):
        from PyQt6.QtWidgets import QMessageBox
        target_elo_display = self.combo_repertoire_elo.currentText()
        target_elo = get_elo_internal(target_elo_display)
        ans = QMessageBox.question(self, "Löschen", f"Sollen alle Lichess-Daten für '{target_elo_display}' wirklich gelöscht werden?")
        if ans == QMessageBox.StandardButton.Yes:
            from opening_fenix.core.db.database import DatabaseManager
            from opening_fenix.core.db.models import LichessData
            from opening_fenix.core.utils import get_repertoire_db_path
            
            db_path = get_repertoire_db_path(self.backend.active_repo_name)
            db = DatabaseManager(db_path)
            try:
                session = db.get_session()
                # Delete only for current Elo focus
                count = session.query(LichessData).filter(LichessData.elo_range == target_elo).delete(synchronize_session=False)
                session.commit()
                session.close()
                db.close()
                QMessageBox.information(self, "Erfolg", f"{count} Einträge für '{target_elo_display}' gelöscht.")
                self.refresh_info()
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Löschen fehlgeschlagen: {e}")

    
    def wipe_other_lichess_data_action(self):
        """Deletes Lichess data from the database for all Elo categories except the current one."""
        target_elo_display = self.combo_repertoire_elo.currentText()
        target_elo = get_elo_internal(target_elo_display)
        confirm = QMessageBox.question(self, "Bereinigen", 
            f"Möchtest du wirklich alle Lichess-Daten löschen, die NICHT für '{target_elo_display}' sind?\nDies spart Speicherplatz.",
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
                QMessageBox.information(self, "Erfolg", f"Bereinigung abgeschlossen. {count} Einträge wurden gelöscht.")
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Bereinigung fehlgeschlagen: {e}")

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
            QMessageBox.warning(self, "Wartung", "Bitte wähle mindestens ein Repertoire aus.")
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
        self.lbl_m_overall.setText(f"Wartung beendet: {message}")
        if success:
            QMessageBox.information(self, "Wartung Center", "Die Stapelverarbeitung wurde erfolgreich abgeschlossen.")
        else:
            QMessageBox.warning(self, "Wartung Center", f"Wartung beendet mit Fehlern:\n{message}")
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
            it_ana = QTableWidgetItem("Laden...")
            it_ana.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.main_table.setItem(row, 3, it_ana)
            
            it_cov = QTableWidgetItem("Laden...")
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
            QMessageBox.information(self, "Bereinigung fertig", f"Erfolgreich {count} verwaiste Lichess-Einträge gelöscht.")
        else:
            QMessageBox.information(self, "Bereinigung fertig", "Keine verwaisten Lichess-Daten gefunden.")
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
