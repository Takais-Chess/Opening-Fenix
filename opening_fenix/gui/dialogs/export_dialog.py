from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup,
    QCheckBox, QComboBox, QLabel, QPushButton, QGroupBox, QFormLayout,
    QFrame, QMessageBox
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
        self.setMinimumWidth(scale(560))
        self.result_data = None
        self.current_estimation = None

        self.backend = backend
        self.setStyleSheet(get_export_dialog_style())
        self.init_ui(parent)
        self.update_estimation()

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
        
        # Connect format change to toggle options visibility and update estimation
        self.r_pgn.toggled.connect(self.toggle_options)
        self.r_pgn.toggled.connect(self.update_estimation)
        
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
        self.r_all.toggled.connect(self.update_estimation)
        self.r_curr.toggled.connect(self.update_estimation)
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
        self.combo_transpos.currentIndexChanged.connect(self.update_estimation)
        l_opt.addRow(tr_ui("export.transpos_label", "Transpositionen:"), self.combo_transpos)

        # Estimation & Warning Banner Card
        self.banner_est = QFrame()
        self.banner_est.setObjectName("ExportEstimationBanner")
        l_banner = QVBoxLayout(self.banner_est)
        l_banner.setContentsMargins(scale(12), scale(10), scale(12), scale(10))
        l_banner.setSpacing(scale(4))

        self.lbl_est_title = QLabel()
        self.lbl_est_title.setWordWrap(True)
        self.lbl_est_body = QLabel()
        self.lbl_est_body.setWordWrap(True)

        l_banner.addWidget(self.lbl_est_title)
        l_banner.addWidget(self.lbl_est_body)
        l_opt.addRow(self.banner_est)
        
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
        if self.backend and hasattr(self.backend, "get_repertoire_levels"):
            try:
                self.level_data = self.backend.get_repertoire_levels()
            except Exception:
                self.level_data = []
        
        for lvl in self.level_data:
            self.combo_level.addItem(tr_ui("export.limit_level", "Level {num} ({name})", num=lvl['order'], name=lvl['name']), userData=lvl['order'])
            
        self.combo_level.setEnabled(False)
        self.chk_limit.toggled.connect(self.combo_level.setEnabled)
        self.chk_limit.toggled.connect(self.update_estimation)
        self.combo_level.currentIndexChanged.connect(self.update_estimation)
        
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

    def get_start_fen(self):
        if self.r_curr.isChecked() and self.backend:
            win = getattr(self.backend, "window", None)
            if win and hasattr(win, "board_widget") and hasattr(win.board_widget, "board"):
                return win.board_widget.board.fen()
        return None

    def update_estimation(self):
        if not self.r_pgn.isChecked() or not self.backend or not hasattr(self.backend, "estimate_pgn_export"):
            self.banner_est.setVisible(False)
            return

        self.banner_est.setVisible(True)
        start = self.get_start_fen()
        transpos_mode = self.combo_transpos.currentIndex()
        max_l = self.combo_level.currentData() if self.chk_limit.isChecked() else None

        try:
            self.current_estimation = self.backend.estimate_pgn_export(
                start=start,
                transpos_mode=transpos_mode,
                max_l=max_l
            )
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.warning(f"ExportDialog: estimation failed: {e}")
            self.banner_est.setVisible(False)
            return

        est = self.current_estimation
        risk = est.get("risk_level", "safe")
        moves = f"{est.get('estimated_moves', 0):,}"
        cuts = f"{est.get('transposition_cuts', 0):,}"
        size_mb = f"{est.get('estimated_size_mb', 0.0):.1f}"
        ratio = f"{est.get('expansion_factor', 1.0):.1f}"

        if risk == "critical":
            self.banner_est.setStyleSheet(f"""
                #ExportEstimationBanner {{
                    background-color: rgba(220, 38, 38, 0.12);
                    border: 1px solid rgba(220, 38, 38, 0.5);
                    border-radius: {scale(8)}px;
                }}
            """)
            self.lbl_est_title.setStyleSheet(f"font-weight: bold; color: #b91c1c; font-size: {scale(13)}px;")
            self.lbl_est_body.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(12)}px; line-height: 140%;")
            self.lbl_est_title.setText("⚠️ " + tr_ui("export.est_warn_critical_title", "Achtung: Extrem große PGN durch Transpositionen!"))
            self.lbl_est_body.setText(tr_ui(
                "export.est_warn_critical_body",
                "Durch ungekürzte Transpositionen wächst die PGN auf ca. {moves} Züge (~{size_mb} MB, {ratio}x Vergrößerung).\n• Export-Dauer: Mehrere Minuten\n• Externe Programme (Lichess, ChessBase) können bei dieser Dateigröße einfrieren oder die PGN ablehnen.\n• Empfehlung: 'Abschneiden (Mit Zugfolge-Kommentar)' wählen.",
                moves=moves, size_mb=size_mb, ratio=ratio
            ))
            self.lbl_est_body.setVisible(True)
        elif risk == "moderate":
            self.banner_est.setStyleSheet(f"""
                #ExportEstimationBanner {{
                    background-color: rgba(217, 119, 6, 0.1);
                    border: 1px solid rgba(217, 119, 6, 0.4);
                    border-radius: {scale(8)}px;
                }}
            """)
            self.lbl_est_title.setStyleSheet(f"font-weight: bold; color: #d97706; font-size: {scale(13)}px;")
            self.lbl_est_title.setText("ℹ️ " + tr_ui(
                "export.est_warn_moderate",
                "Hinweis: Durch Transpositionen wächst die PGN auf ca. {moves} Züge (~{size_mb} MB, {ratio}x Vergrößerung).",
                moves=moves, size_mb=size_mb, ratio=ratio
            ))
            self.lbl_est_body.setVisible(False)
        else:
            self.banner_est.setStyleSheet(f"""
                #ExportEstimationBanner {{
                    background-color: rgba(46, 125, 50, 0.08);
                    border: 1px solid rgba(46, 125, 50, 0.3);
                    border-radius: {scale(8)}px;
                }}
            """)
            self.lbl_est_title.setStyleSheet(f"font-weight: normal; color: #2e7d32; font-size: {scale(12)}px;")
            if est.get("transposition_cuts", 0) > 0:
                text = "✓ " + tr_ui(
                    "export.est_info",
                    "Geschätzte Größe: ~{size_mb} MB ({moves} Züge • {cuts} Transpositionen gekürzt)",
                    size_mb=size_mb, moves=moves, cuts=cuts
                )
            else:
                text = "✓ " + tr_ui(
                    "export.est_info_no_cuts",
                    "Geschätzte Größe: ~{size_mb} MB ({moves} Züge)",
                    size_mb=size_mb, moves=moves
                )
            self.lbl_est_title.setText(text)
            self.lbl_est_body.setVisible(False)

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
        est = getattr(self, "current_estimation", None)

        # Confirmation dialog for critical PGN export
        if fmt == "pgn" and transpos_mode == 0 and est and est.get("risk_level") == "critical":
            moves = f"{est.get('estimated_moves', 0):,}"
            size_mb = f"{est.get('estimated_size_mb', 0.0):.1f}"
            ratio = f"{est.get('expansion_factor', 1.0):.1f}"
            ret = QMessageBox.warning(
                self,
                tr_ui("export.confirm_huge_title", "Sehr große PGN-Datei exportieren?"),
                tr_ui(
                    "export.confirm_huge_text",
                    "Die PGN wird durch ungekürzte Transpositionen auf ca. {moves} Züge (~{size_mb} MB, {ratio}x Vergrößerung) expandiert.\n\nDer Export kann mehrere Minuten dauern und externe Programme überlasten.\n\nMöchten Sie wirklich fortfahren?",
                    moves=moves, size_mb=size_mb, ratio=ratio
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        
        self.result_data = (fmt, scope, transpos_mode, max_l, lang, est)
        self.accept()
