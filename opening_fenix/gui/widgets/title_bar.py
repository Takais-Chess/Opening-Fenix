from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QIcon

from opening_fenix.gui.styles import COLORS
from opening_fenix.gui.scaling import scale


class CustomTitleBar(QWidget):
    def __init__(self, parent=None, title="Opening Fenix"):
        super().__init__(parent)
        self.parent_window = parent
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(scale(10), 0, scale(10), 0)
        self.layout.setSpacing(scale(5))

        
        # We give the title bar a slightly darker beige or semi-transparent background later in QSS
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(scale(35))

        
        # Profile title label removed (Phase 7 top bar polish)
        
        self.layout.addStretch()
        
        btn_style = f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {COLORS['brown_text']};
                font-size: {scale(14)}px;
                font-weight: bold;
                border-radius: {scale(4)}px;
            }}

            QPushButton:hover {{
                background-color: rgba(200, 200, 200, 0.5);
            }}
        """
        
        self.btn_minimize = QPushButton("—")
        self.btn_minimize.setFixedSize(scale(40), scale(25))
        self.btn_minimize.setStyleSheet(btn_style)

        self.btn_minimize.clicked.connect(self.minimize_window)
        self.layout.addWidget(self.btn_minimize, alignment=Qt.AlignmentFlag.AlignTop)
        
        self.btn_maximize = QPushButton("🗖")
        self.btn_maximize.setFixedSize(scale(40), scale(25))
        self.btn_maximize.setStyleSheet(btn_style)

        self.btn_maximize.clicked.connect(self.maximize_window)
        self.layout.addWidget(self.btn_maximize, alignment=Qt.AlignmentFlag.AlignTop)
        
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(scale(40), scale(25))
        self.btn_close.setStyleSheet(btn_style + f"QPushButton:hover {{ background-color: {COLORS['burnt_orange']}; color: white; }}")

        self.btn_close.clicked.connect(self.close_window)
        self.layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignTop)
        
        self.start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos is not None and self.parent_window is not None:
            # If maximized, restore when dragging
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
                # Adjust cursor position to be roughly in the middle of the new title bar
                self.start_pos = QPoint(self.parent_window.width() // 2, event.pos().y())
            
            delta = event.globalPosition().toPoint() - self.start_pos
            self.parent_window.move(self.parent_window.pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.start_pos = None
        
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_window()

    def minimize_window(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def maximize_window(self):
        if self.parent_window:
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
                self.btn_maximize.setText("🗖")
            else:
                self.parent_window.showMaximized()
                self.btn_maximize.setText("🗗")

    def close_window(self):
        if self.parent_window:
            self.parent_window.close()
