from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup,
    QCheckBox, QComboBox, QLabel, QPushButton, QGroupBox, QFormLayout
)
from PyQt6.QtCore import Qt
from opening_fenix.gui.styles import get_export_dialog_style, COLORS, set_consistent_icon
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui



class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class ExportDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("export.window_title", "Exportieren"))
        self.setMinimumWidth(scale(350))
        self.result_data = None

        self.backend = backend
        self.setStyleSheet(get_export_dialog_style())
        self.init_ui(parent)

    def init_ui(self, parent):
        layout = QVBoxLayout(self)
        
        
        lbl_title = QLabel(tr_ui("export.title", "Repertoire Exportieren"))
        lbl_title.setStyleSheet(f"font-size: {scale(20)}px; font-weight: bold; color: {COLORS['brown_text']}; margin-bottom: {scale(10)}px;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(lbl_title)

        # Format Selection
        g_fmt = QGroupBox(tr_ui("export.format_group", "1. Format"))
        l_fmt = QVBoxLayout(g_fmt)
        l_fmt.setSpacing(scale(10))
        self.bg_fmt = QButtonGroup(self)

        self.r_pgn = QRadioButton(tr_ui("export.format_pgn", "PGN (Textdatei für andere Programme)"))
        self.r_db = QRadioButton(tr_ui("export.format_db", "Datenbank (.db Datei für Backup)"))
        self.r_pgn.setChecked(True)
        self.bg_fmt.addButton(self.r_pgn, 1)
        self.bg_fmt.addButton(self.r_db, 2)
        l_fmt.addWidget(self.r_pgn)
        l_fmt.addWidget(self.r_db)
        
        # Connect format change to toggle options visibility
        self.r_pgn.toggled.connect(self.toggle_options)
        
        layout.addWidget(g_fmt)

        # Scope Selection
        g_scope = QGroupBox(tr_ui("export.scope_group", "2. Umfang"))
        l_scope = QVBoxLayout(g_scope)
        l_scope.setSpacing(scale(10))
        self.bg_scope = QButtonGroup(self)

        self.r_all = QRadioButton(tr_ui("export.scope_all", "Ganzes Repertoire"))
        self.r_curr = QRadioButton(tr_ui("export.scope_current", "Nur ab aktueller Position auf dem Brett"))
        self.r_all.setChecked(True)
        self.bg_scope.addButton(self.r_all, 1)
        self.bg_scope.addButton(self.r_curr, 2)
        l_scope.addWidget(self.r_all)
        l_scope.addWidget(self.r_curr)
        layout.addWidget(g_scope)

        # Options
        self.g_opt = QGroupBox(tr_ui("export.options_group", "3. Zusätzliche PGN Optionen"))
        l_opt = QFormLayout(self.g_opt)
        l_opt.setVerticalSpacing(scale(15))

        
        # Transpositions handling
        self.combo_transpos = NoWheelComboBox()
        self.combo_transpos.addItem(tr_ui("export.transpos_all", "Alle Züge anzeigen (Nicht abschneiden)"))
        self.combo_transpos.addItem(tr_ui("export.transpos_cut", "Abschneiden (Ohne Kommentar)"))
        self.combo_transpos.addItem(tr_ui("export.transpos_cut_comment", "Abschneiden (Mit Zugfolge-Kommentar)"))
        self.combo_transpos.setToolTip(tr_ui("export.transpos_tooltip", "Wie sollen Stellungen behandelt werden, die über verschiedene Zugfolgen erreicht werden?"))
        # Set "Abschneiden (Mit Zugfolge-Kommentar)" as default
        self.combo_transpos.setCurrentIndex(2)
        l_opt.addRow(tr_ui("export.transpos_label", "Transpositionen:"), self.combo_transpos)
        
        # Language Selection
        self.combo_lang = NoWheelComboBox()
        self.combo_lang.addItem(tr_ui("export.lang_en", "Standard (English)"), "en")
        self.combo_lang.addItem(tr_ui("export.lang_de", "Deutsch"), "de")
        self.combo_lang.addItem(tr_ui("export.lang_multilingual", "Mehrsprachig (PGN-Tags)"), "multilingual")
        
        # Default to current profile setting if available
        if parent and hasattr(parent, 'get_notation_lang'):
            lang = parent.get_notation_lang()
            idx = self.combo_lang.findData(lang)
            if idx >= 0: self.combo_lang.setCurrentIndex(idx)
            
        l_opt.addRow(tr_ui("export.lang_label", "Sprache:"), self.combo_lang)
        
        # Level Selection
        self.chk_limit = QCheckBox(tr_ui("export.limit_checkbox", "Nur bis Level exportieren:"))
        self.combo_level = NoWheelComboBox()
        
        # Fetch actual levels from backend
        self.level_data = []
        if self.backend:
            self.level_data = self.backend.get_repertoire_levels()
        
        for lvl in self.level_data:
            self.combo_level.addItem(tr_ui("export.limit_level", "Level {num} ({name})", num=lvl['order'], name=lvl['name']), userData=lvl['order'])
            
        self.combo_level.setEnabled(False)
        self.chk_limit.toggled.connect(self.combo_level.setEnabled)
        
        h_l = QHBoxLayout()
        h_l.addWidget(self.chk_limit)
        h_l.addWidget(self.combo_level)
        h_l.addStretch()
        l_opt.addRow(h_l)
        layout.addWidget(self.g_opt)

        layout.addSpacing(scale(10))

        # Buttons
        h_btn = QHBoxLayout()
        
        b_cancel = QPushButton(tr_ui("export.btn_cancel", "Abbrechen"))
        b_cancel.clicked.connect(self.reject)
        
        b_ok = QPushButton(tr_ui("export.btn_export", "💾 Exportieren"))
        b_ok.setObjectName("PrimaryButton")
        b_ok.clicked.connect(self.on_accept)
        
        h_btn.addStretch()
        h_btn.addWidget(b_cancel)
        h_btn.addWidget(b_ok)
        layout.addLayout(h_btn)
        
        self.toggle_options()

    def toggle_options(self):
        # Only show PGN options if PGN is selected
        self.g_opt.setVisible(self.r_pgn.isChecked())

    def on_accept(self):
        fmt = "pgn" if self.r_pgn.isChecked() else "db"
        scope = "all" if self.r_all.isChecked() else "current"
        
        # Transposition handling mode
        transpos_mode = self.combo_transpos.currentIndex()
        
        max_l = self.combo_level.currentData() if self.chk_limit.isChecked() else None
        lang = self.combo_lang.currentData()
        
        self.result_data = (fmt, scope, transpos_mode, max_l, lang)
        self.accept()
