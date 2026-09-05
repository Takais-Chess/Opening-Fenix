import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QGridLayout, QLabel, QScrollArea,
    QPushButton, QHBoxLayout
)
from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import get_bw_glass_style, set_consistent_icon
from opening_fenix.core.translation import tr_ui
from opening_fenix.gui.dialogs.unified_settings_dialog import (
    UnifiedSettingsDialog,
    NoWheelComboBox,
    NoWheelSpinBox,
    NoWheelDoubleSpinBox,
    NoWheelSlider,
    ToggleSwitch,
    RepertoireConfigCard
)


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
        self.setWindowTitle(tr_ui("settings.load_repertoire_title", "Repertoire Laden"))
        self.setMinimumSize(scale(520), scale(420))
        self.selected_repo = None
        self.setStyleSheet(get_bw_glass_style())
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(20))
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        lbl_title = QLabel(tr_ui("settings.select_repertoire_label", "Repertoire auswählen"))
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #111111; margin-bottom: 5px;")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(tr_ui("settings.select_repertoire_sub", "Klicke auf ein Repertoire, um es zu laden."))
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
        b_cancel = QPushButton(tr_ui("login.cancel", "Abbrechen"))
        b_cancel.clicked.connect(self.reject)
        h_btn.addStretch()
        h_btn.addWidget(b_cancel)
        layout.addLayout(h_btn)

    def on_repo_click(self, name):
        self.selected_repo = name
        self.accept()


class SettingsDialog(UnifiedSettingsDialog):
    """
    Backwards-compatible SettingsDialog routing to UnifiedSettingsDialog in Trainer mode.
    """
    def __init__(self, main_window):
        super().__init__(parent=main_window, initial_section="trainer")
        self.setWindowTitle(f"Trainer-Einstellungen – Opening Fenix ({self.profile_name})")
