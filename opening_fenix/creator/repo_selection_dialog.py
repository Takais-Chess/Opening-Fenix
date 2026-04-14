import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget, QGridLayout, 
    QPushButton, QHBoxLayout, QApplication
)
from PyQt6.QtCore import Qt, QSize

from opening_fenix.core.services.repertoire_core_service import RepertoireService
from opening_fenix.gui.styles import get_login_dialog_style, COLORS, set_consistent_icon
from opening_fenix.gui.scaling import scale

class RepoSelectionButton(QPushButton):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.repo_name = name
        self.setFixedHeight(scale(50))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.4);
                color: {COLORS['brown_text']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(15)}px;
                font-size: {scale(16)}px;
                font-weight: bold;
                padding: {scale(2)}px {scale(10)}px;
            }}

            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.8);
                border: 2px solid {COLORS['burnt_orange']};
                color: {COLORS['burnt_orange']};
            }}
            
            QPushButton:pressed {{
                background-color: {COLORS['burnt_orange']};
                color: white;
            }}
        """)

class RepoSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle("Repertoire laden")
        self.setMinimumSize(scale(600), scale(500))
        self.selected_repo = None
        
        self.setStyleSheet(get_login_dialog_style())
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(40), scale(40), scale(40), scale(40))
        layout.setSpacing(scale(10))

        lbl_title = QLabel("Repertoire laden")
        lbl_title.setObjectName("LoginTitle")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_sub = QLabel("Wähle ein Repertoire zum Bearbeiten aus:")
        lbl_sub.setObjectName("LoginSubtitle")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_sub)
        
        layout.addSpacing(scale(25))

        # Scroll Area Container
        self.grid_container = QWidget()
        self.grid_container.setObjectName("ProfileGridContainer")
        self.grid_container.setStyleSheet(f"""
            #ProfileGridContainer {{
                background-color: rgba(255, 255, 255, 0.2);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(20)}px;
            }}
        """)
        container_layout = QVBoxLayout(self.grid_container)
        container_layout.setContentsMargins(scale(15), scale(15), scale(15), scale(15))

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(scale(15))
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        repo_names = RepertoireService().get_all_repertoires()
        row = 0
        if not repo_names:
            lbl_empty = QLabel("Keine Repertoires gefunden.")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("font-style: italic; color: #666;")
            self.grid_layout.addWidget(lbl_empty, 0, 0)
        else:
            col = 0
            for name in sorted(repo_names):
                btn = RepoSelectionButton(name)
                btn.clicked.connect(lambda checked, n=name: self.on_repo_selected(n))
                self.grid_layout.addWidget(btn, row, col)
                col += 1
                if col > 1: # 2 columns
                    col = 0
                    row += 1
                        
        self.grid_layout.setRowStretch(row + 1, 1)
        self.scroll_area.setWidget(scroll_content)
        container_layout.addWidget(self.scroll_area)
        layout.addWidget(self.grid_container, 1)
        
        layout.addSpacing(scale(25))

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        self.btn_cancel = QPushButton("Abbrechen")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setFixedWidth(scale(150))
        self.btn_cancel.setFixedHeight(scale(45))
        self.btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(self.btn_cancel)
        h_btns.addStretch()
        layout.addLayout(h_btns)

    def on_repo_selected(self, name):
        self.selected_repo = name
        self.accept()
