from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QCheckBox
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS
from opening_fenix.core.translation import tr_ui
from opening_fenix.gui.dialogs.unified_settings_dialog import (
    UnifiedSettingsDialog,
    NoWheelComboBox,
    NoWheelSpinBox,
    NoWheelDoubleSpinBox,
    NoWheelSlider,
    DiagnosticDialog,
    DeleteLevelDialog
)
from opening_fenix.core.data_tools import get_user_dir
from opening_fenix.core.threads import AnalysisThread, LichessImportThread


class MaintenanceRepoWidget(QWidget):
    """Compatibility widget for maintenance repo rows."""
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
        self.lbl_elo_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_elo_val, 0, 3)
        
        self.lbl_status = QLabel(tr_ui("repo_settings.status_ready", "Bereit"))
        self.lbl_status.setFixedWidth(scale(140))
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_status, 0, 4)
        
        layout.setColumnStretch(1, 1)

    def mousePressEvent(self, event):
        self.chk.setChecked(not self.chk.isChecked())
        super().mousePressEvent(event)

    def is_checked(self): return self.chk.isChecked()
    def set_checked(self, checked): self.chk.setChecked(checked)
    def get_config(self): return {'name': self.name, 'elo': self.lbl_elo_val.text()}


class RepoSettingsDialog(UnifiedSettingsDialog):
    """
    Backwards-compatible RepoSettingsDialog routing to UnifiedSettingsDialog in Creator mode.
    """
    def __init__(self, parent=None, backend=None):
        super().__init__(parent=parent, backend=backend, initial_section="creator")
        self.setWindowTitle(tr_ui("repo_settings.title", "Repertoire-Einstellungen – Opening Fenix"))
