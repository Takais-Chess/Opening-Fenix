import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget, QGridLayout, 
    QPushButton, QHBoxLayout, QApplication
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QFont

from opening_fenix.core.services.repertoire_core_service import RepertoireService
from opening_fenix.gui.styles import get_login_dialog_style, COLORS, set_consistent_icon
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui

def get_repertoire_cover_path(name):
    from opening_fenix.core.data_tools import get_user_dir
    repo_base = os.path.join(get_user_dir(), "repertoires")
    
    # Try normal path
    normal_dir = os.path.join(repo_base, name)
    # Try test path
    test_dir = os.path.join(repo_base, "test", name)
    
    for folder in (normal_dir, test_dir):
        if os.path.isdir(folder):
            try:
                for f in os.listdir(folder):
                    f_lower = f.lower()
                    if f_lower.startswith("cover."):
                        ext = f_lower.split(".")[-1]
                        if ext in ("png", "jpg", "jpeg"):
                            return os.path.join(folder, f)
            except Exception:
                pass
    return None

class RepoSelectionButton(QPushButton):
    def __init__(self, name, parent=None):
        super().__init__("", parent)
        self.repo_name = name
        self.setFixedSize(scale(160), scale(200))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
            }}

            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.8);
                border: 2px solid {COLORS['burnt_orange']};
            }}
            
            QPushButton:pressed {{
                background-color: rgba(211, 84, 0, 0.1);
                border: 2px solid {COLORS['burnt_orange']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(10), scale(10), scale(10), scale(10))
        layout.setSpacing(scale(6))
        
        self.lbl_image = QLabel()
        self.lbl_image.setFixedSize(scale(140), scale(140))
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        cover_path = get_repertoire_cover_path(name)
        if cover_path:
            pix = QPixmap(cover_path)
            self.lbl_image.setPixmap(pix.scaled(
                self.lbl_image.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            ))
            self.lbl_image.setStyleSheet(f"border-radius: {scale(8)}px; border: none;")
        else:
            self.lbl_image.setStyleSheet(f"""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 rgba(211, 84, 0, 0.3), 
                    stop:1 rgba(211, 84, 0, 0.05));
                border-radius: {scale(8)}px;
                border: 1px dashed rgba(211, 84, 0, 0.3);
            """)
            self.lbl_image.setText("♟")
            self.lbl_image.setFont(QFont("Segoe UI", 36))
            
        layout.addWidget(self.lbl_image)
        
        self.lbl_title = QLabel(name)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_title.setStyleSheet(f"font-size: {scale(12)}px; font-weight: bold; color: {COLORS['brown_text']}; border: none; background: transparent;")
        layout.addWidget(self.lbl_title)

class RepoSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("repo_selection.window_title", "Repertoire laden"))
        self.setMinimumSize(scale(800), scale(680))
        self.selected_repo = None
        
        self.setStyleSheet(get_login_dialog_style())
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        layout.setSpacing(scale(10))

        # Title bar with centered text and a close button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addSpacing(scale(40)) # Spacer to compensate for close button width and center the title
        
        lbl_title = QLabel(tr_ui("repo_selection.title", "Repertoire laden"))
        lbl_title.setObjectName("LoginTitle")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(lbl_title, 1)
        
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(scale(40), scale(30))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {COLORS['brown_text']};
                font-size: {scale(16)}px;
                font-weight: bold;
                border-radius: {scale(4)}px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['burnt_orange']};
                color: white;
            }}
        """)
        self.btn_close.clicked.connect(self.close_dialog_or_app)
        header_layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignTop)
        
        layout.addLayout(header_layout)

        lbl_sub = QLabel(tr_ui("repo_selection.subtitle", "Wähle ein Repertoire zum Bearbeiten aus:"))
        lbl_sub.setObjectName("LoginSubtitle")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_sub)
        
        layout.addSpacing(scale(15))

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
            lbl_empty = QLabel(tr_ui("repo_selection.empty", "Keine Repertoires gefunden."))
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
                if col > 3: # 4 columns
                    col = 0
                    row += 1
                        
        self.grid_layout.setRowStretch(row + 1, 1)
        self.scroll_area.setWidget(scroll_content)
        container_layout.addWidget(self.scroll_area)
        layout.addWidget(self.grid_container, 1)
        
        layout.addSpacing(scale(15))

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        self.btn_cancel = QPushButton(tr_ui("repo_selection.btn_cancel", "Abbrechen"))
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

    def close_dialog_or_app(self):
        # If no active repertoire is loaded in the parent CreatorWindow, exit the entire app
        parent = self.parent()
        if parent and hasattr(parent, "backend") and not parent.backend.active_repo_name:
            QApplication.quit()
        else:
            self.reject()
