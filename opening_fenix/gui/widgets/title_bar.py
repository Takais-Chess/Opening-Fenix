from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QApplication
from PyQt6.QtCore import Qt, QPoint, QRect
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
        self.btn_minimize.setObjectName("MinimizeButton")
        self.btn_minimize.setFixedSize(scale(40), scale(25))
        self.btn_minimize.setStyleSheet(btn_style)

        self.btn_minimize.clicked.connect(self.minimize_window)
        self.layout.addWidget(self.btn_minimize, alignment=Qt.AlignmentFlag.AlignTop)
        
        self.btn_maximize = QPushButton("🗖")
        self.btn_maximize.setObjectName("MaximizeButton")
        self.btn_maximize.setFixedSize(scale(40), scale(25))
        self.btn_maximize.setStyleSheet(btn_style)

        self.btn_maximize.clicked.connect(self.maximize_window)
        self.layout.addWidget(self.btn_maximize, alignment=Qt.AlignmentFlag.AlignTop)
        
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("CloseButton")
        self.btn_close.setFixedSize(scale(40), scale(25))
        self.btn_close.setStyleSheet(btn_style + f"QPushButton:hover {{ background-color: {COLORS['burnt_orange']}; color: white; }}")

        self.btn_close.clicked.connect(self.close_window)
        self.layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignTop)
        
        self.start_pos = None
        self.press_pos = None
        self.is_dragging = False

    def showEvent(self, event):
        super().showEvent(event)
        self.update_maximize_button()

    def update_maximize_button(self):
        if self.parent_window and hasattr(self, 'btn_maximize'):
            if self.parent_window.isMaximized():
                self.btn_maximize.setText("🗗")
            else:
                self.btn_maximize.setText("🗖")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()
            self.press_pos = event.position().toPoint()
            self.is_dragging = True

    def mouseMoveEvent(self, event):
        if not self.is_dragging or self.start_pos is None or self.parent_window is None:
            return

        current_global = event.globalPosition().toPoint()

        # If maximized, restore when dragging down
        if self.parent_window.isMaximized():
            # Determine screen under current cursor
            screen = QApplication.screenAt(current_global) or self.parent_window.screen()
            screen_avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

            grab_ratio = 0.5
            if self.width() > 0 and self.press_pos is not None:
                grab_ratio = max(0.0, min(1.0, self.press_pos.x() / self.width()))

            self.parent_window.showNormal()

            target_w = min(scale(1400), max(800, screen_avail.width() - scale(100)))
            target_h = min(scale(900), max(600, screen_avail.height() - scale(100)))
            self.parent_window.resize(target_w, target_h)

            click_y_offset = self.press_pos.y() if self.press_pos else scale(15)
            new_x = int(current_global.x() - grab_ratio * target_w)
            new_y = int(current_global.y() - click_y_offset)

            # Clamp so title bar stays on screen
            new_x = max(screen_avail.left(), min(new_x, screen_avail.right() - target_w))
            new_y = max(screen_avail.top(), min(new_y, screen_avail.bottom() - target_h))

            self.parent_window.move(new_x, new_y)
            self.start_pos = current_global
            self.update_maximize_button()
            return

        delta = current_global - self.start_pos
        self.parent_window.move(self.parent_window.pos() + delta)
        self.start_pos = current_global

    def mouseReleaseEvent(self, event):
        self.start_pos = None
        self.press_pos = None
        self.is_dragging = False
        
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_window()

    def minimize_window(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def maximize_window(self):
        if self.parent_window:
            if self.parent_window.isMaximized():
                current_screen = QApplication.screenAt(self.parent_window.geometry().center()) or self.parent_window.screen()
                screen_avail = current_screen.availableGeometry() if current_screen else None

                self.parent_window.showNormal()

                # Prevent multi-monitor teleporting back to primary monitor
                if screen_avail and not screen_avail.contains(self.parent_window.geometry().center()):
                    target_w = min(scale(1400), max(800, screen_avail.width() - scale(100)))
                    target_h = min(scale(900), max(600, screen_avail.height() - scale(100)))
                    new_x = screen_avail.left() + (screen_avail.width() - target_w) // 2
                    new_y = screen_avail.top() + (screen_avail.height() - target_h) // 2
                    self.parent_window.setGeometry(new_x, new_y, target_w, target_h)

                self.update_maximize_button()
            else:
                self.parent_window.showMaximized()
                self.update_maximize_button()

    def close_window(self):
        if self.parent_window:
            self.parent_window.close()
