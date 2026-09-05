import time
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QGraphicsDropShadowEffect, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath, QFont

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS
from opening_fenix.core.translation import tr_ui


class HoldProgressButton(QPushButton):
    """
    A button that requires being held down continuously for a specified duration
    (default 5.0 seconds) to trigger its action, with visual progress feedback.
    """
    hold_completed = pyqtSignal()

    def __init__(self, text: str = "", hold_duration_sec: float = 5.0, parent=None):
        super().__init__(text, parent)
        self.base_text = text
        self.hold_duration = hold_duration_sec
        self.press_start_time = None
        self.progress = 0.0  # 0.0 to 1.0

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(30)  # ~33 fps
        self.update_timer.timeout.connect(self._on_timer_tick)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(scale(44))
        self.setMinimumWidth(scale(240))
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(60, 60, 65, 0.9);
                color: #e0e0e0;
                border: 1px solid rgba(200, 200, 200, 0.25);
                border-radius: {scale(8)}px;
                font-size: {scale(13)}px;
                font-weight: bold;
                padding: {scale(8)}px {scale(16)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(80, 80, 85, 0.95);
                border-color: rgba(255, 165, 0, 0.6);
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_start_time = time.time()
            self.progress = 0.0
            self.update_timer.start()
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._reset_hold()
        super().mouseReleaseEvent(event)

    def _reset_hold(self):
        self.update_timer.stop()
        self.press_start_time = None
        self.progress = 0.0
        self.setText(self.base_text)
        self.update()

    def _on_timer_tick(self):
        if self.press_start_time is None:
            self._reset_hold()
            return

        elapsed = time.time() - self.press_start_time
        remaining = max(0.0, self.hold_duration - elapsed)
        self.progress = min(1.0, elapsed / self.hold_duration)

        countdown_text = tr_ui(
            "lockout.hold_countdown", 
            "Gedrückt halten... ({seconds:.1f}s)", 
            seconds=remaining
        )
        self.setText(countdown_text)
        self.update()

        if self.progress >= 1.0:
            self.update_timer.stop()
            self.press_start_time = None
            self.progress = 0.0
            self.setText(self.base_text)
            self.update()
            self.hold_completed.emit()

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.progress > 0.0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            fill_width = self.width() * self.progress
            fill_rect = QRectF(0, 0, fill_width, float(self.height()))

            path = QPainterPath()
            radius = scale(8)
            path.addRoundedRect(fill_rect, radius, radius)

            # Warm amber/orange progress overlay
            brush = QBrush(QColor(230, 126, 34, 140))
            painter.fillPath(path, brush)

            # Re-draw the centered text on top of the fill
            painter.setPen(QColor(255, 255, 255))
            font = self.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
            painter.end()


class LichessLockoutOverlay(QWidget):
    """
    A modal overlay that covers the CreatorWindow whenever a live game
    is detected on Lichess for monitored player(s).
    """
    recheck_requested = pyqtSignal()
    open_settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.current_game_ids = {}
        self.playing_users = []

        if parent:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

        self.init_ui()
        self.hide()

    def eventFilter(self, obj, event):
        if obj == self.parent() and event.type() == event.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, event)

    def init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Center Card
        self.card = QFrame(self)
        self.card.setObjectName("LockoutCard")
        self.card.setFixedWidth(scale(560))
        self.card.setStyleSheet(f"""
            QFrame#LockoutCard {{
                background-color: rgba(24, 24, 28, 0.96);
                border: 2px solid {COLORS['burnt_orange']};
                border-radius: {scale(18)}px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(35)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(scale(35), scale(35), scale(35), scale(35))
        card_layout.setSpacing(scale(18))

        # 🔒 Header
        self.lbl_title = QLabel(tr_ui("lockout.title", "🔒 Fair Play Lockout"))
        self.lbl_title.setStyleSheet(f"""
            color: {COLORS['burnt_orange']};
            font-size: {scale(24)}px;
            font-weight: bold;
        """)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.lbl_title)

        # Subtitle: Lichess-Partie aktiv
        self.lbl_subtitle = QLabel(tr_ui("lockout.subtitle", "Lichess-Partie aktiv"))
        self.lbl_subtitle.setStyleSheet(f"""
            color: #ffffff;
            font-size: {scale(16)}px;
            font-weight: bold;
        """)
        self.lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.lbl_subtitle)

        # Explanation Text
        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet(f"""
            color: #b0b0b8;
            font-size: {scale(13)}px;
            line-height: 1.4;
        """)
        self.lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.lbl_desc)

        # Live Game Link Button
        self.btn_open_game = QPushButton(tr_ui("lockout.btn_open_game", "🌐 Partie auf Lichess öffnen"))
        self.btn_open_game.setFixedHeight(scale(38))
        self.btn_open_game.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_game.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(41, 128, 185, 0.25);
                color: #5dade2;
                border: 1px solid rgba(93, 173, 226, 0.4);
                border-radius: {scale(8)}px;
                font-size: {scale(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(41, 128, 185, 0.45);
                color: #ffffff;
            }}
        """)
        self.btn_open_game.clicked.connect(self._on_open_game_clicked)
        card_layout.addWidget(self.btn_open_game)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); max-height: 1px;")
        card_layout.addWidget(divider)

        # Status feedback label (for when recheck is performed)
        self.lbl_status_feedback = QLabel("")
        self.lbl_status_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status_feedback.setWordWrap(True)
        self.lbl_status_feedback.setStyleSheet(f"font-size: {scale(12)}px; font-weight: bold;")
        self.lbl_status_feedback.hide()
        card_layout.addWidget(self.lbl_status_feedback)

        # Action Buttons Layout
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(scale(10))

        # 1. Re-check Button
        self.btn_recheck = QPushButton(tr_ui("lockout.btn_recheck", "🔄 Prüfen, ob Partie beendet ist"))
        self.btn_recheck.setFixedHeight(scale(44))
        self.btn_recheck.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_recheck.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: #ffffff;
                border: none;
                border-radius: {scale(8)}px;
                font-size: {scale(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
            QPushButton:disabled {{
                background-color: #555555;
                color: #888888;
            }}
        """)
        self.btn_recheck.clicked.connect(self._on_recheck_clicked)
        actions_layout.addWidget(self.btn_recheck)

        # 2. Emergency Settings Bypass Button (5-second hold)
        self.btn_settings = HoldProgressButton(
            text=tr_ui("lockout.btn_settings", "⚙️ Einstellungen ändern (5s halten)"),
            hold_duration_sec=5.0
        )
        self.btn_settings.hold_completed.connect(self._on_settings_hold_completed)
        actions_layout.addWidget(self.btn_settings)

        card_layout.addLayout(actions_layout)
        root_layout.addWidget(self.card)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 10, 15, 220))
        painter.end()

    def show_lockout(self, playing_users: list, game_ids: dict):
        """Displays the lockout overlay with details about the detected game(s)."""
        self.playing_users = playing_users or []
        self.current_game_ids = game_ids or {}

        users_str = ", ".join(self.playing_users) if self.playing_users else tr_ui("lockout.unknown_user", "Unbekannt")
        desc_text = tr_ui(
            "lockout.desc",
            "Eine laufende Lichess-Partie wurde erkannt für:<br><b>{users}</b><br><br>"
            "Der Repertoire Creator ist während der Partie gesperrt, "
            "um versehentliche Unterstützung zu verhindern und Fairplay zu gewährleisten.",
            users=users_str
        )
        self.lbl_desc.setText(desc_text)

        first_game_id = next(iter(self.current_game_ids.values()), None)
        if first_game_id:
            self.btn_open_game.show()
        else:
            self.btn_open_game.hide()

        self.lbl_status_feedback.hide()
        self.btn_recheck.setEnabled(True)
        self.btn_recheck.setText(tr_ui("lockout.btn_recheck", "🔄 Prüfen, ob Partie beendet ist"))

        if self.parent():
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()

    def unlock(self):
        """Unlocks and hides the overlay."""
        self.hide()

    def set_checking_state(self, checking: bool):
        if checking:
            self.btn_recheck.setEnabled(False)
            self.btn_recheck.setText(tr_ui("lockout.checking", "⏳ Prüfe Lichess-Status..."))
        else:
            self.btn_recheck.setEnabled(True)
            self.btn_recheck.setText(tr_ui("lockout.btn_recheck", "🔄 Prüfen, ob Partie beendet ist"))

    def show_feedback(self, text: str, is_error: bool = False):
        self.lbl_status_feedback.setText(text)
        color = "#e74c3c" if is_error else "#f39c12"
        self.lbl_status_feedback.setStyleSheet(f"color: {color}; font-size: {scale(12)}px; font-weight: bold;")
        self.lbl_status_feedback.show()

    def _on_recheck_clicked(self):
        self.set_checking_state(True)
        self.recheck_requested.emit()

    def _on_settings_hold_completed(self):
        self.open_settings_requested.emit()

    def _on_open_game_clicked(self):
        first_game_id = next(iter(self.current_game_ids.values()), None)
        if first_game_id:
            webbrowser.open(f"https://lichess.org/{first_game_id}")
