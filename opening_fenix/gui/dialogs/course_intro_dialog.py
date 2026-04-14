from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextBrowser, QGraphicsDropShadowEffect, QWidget, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon
import os

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon
from opening_fenix.core.data_tools import get_base_path

class CourseIntroDialog(QDialog):
    """
    A premium onboarding dialog that appears when a user opens a repertoire
    for the first time (i.e. no moves learned yet).
    """
    def __init__(self, parent=None, repertoire_info=None):
        super().__init__(parent)
        self.repertoire_info = repertoire_info or {}
        
        # Premium Frameless Window
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setMinimumSize(scale(700), scale(600))
        
        set_consistent_icon(self)
        self.init_ui()
        
    def init_ui(self):
        # Main background container with glass effect
        container = QWidget(self)
        container.setObjectName("Container")
        container.setStyleSheet(f"""
            QWidget#Container {{
                background-color: {COLORS['beige']};
                border: 2px solid {COLORS['glass_border']};
                border-radius: {scale(20)}px;
            }}
        """)
        
        # Add strong drop shadow to make it pop
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 10)
        container.setGraphicsEffect(shadow)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        main_layout.addWidget(container)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(scale(30), scale(15), scale(30), scale(30))
        layout.setSpacing(scale(20))
        
        # --- CLOSE BUTTON ROW ---
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        
        btn_close = QPushButton("✕")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setFixedSize(scale(30), scale(30))
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['light_text']};
                font-size: {scale(20)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: {COLORS['burnt_orange']};
            }}
        """)
        btn_close.clicked.connect(self.reject)
        close_layout.addWidget(btn_close)
        layout.addLayout(close_layout)
        
        # --- HEADER ---
        repo_name = self.repertoire_info.get("name", "Dein neues Repertoire")
        lbl_welcome = QLabel("Willkommen bei")
        lbl_welcome.setStyleSheet(f"color: {COLORS['light_text']}; font-size: {scale(18)}px; font-weight: bold;")
        lbl_welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl_title = QLabel(repo_name)
        lbl_title.setStyleSheet(f"""
            color: {COLORS['burnt_orange']}; 
            font-size: {scale(32)}px; 
            font-weight: 900; 
            margin-bottom: {scale(10)}px;
        """)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setWordWrap(True)
        
        layout.addWidget(lbl_welcome)
        layout.addWidget(lbl_title)
        
        # --- LEVEL STATS CARDS ---
        level_details = self.repertoire_info.get("level_details", [])
        
        # We use a horizontal layout inside a scroll area so it doesn't squish if there are many levels
        stats_scroll = QScrollArea()
        stats_scroll.setWidgetResizable(True)
        stats_scroll.setFrameShape(QFrame.Shape.NoFrame)
        stats_scroll.setStyleSheet("background: transparent;")
        stats_scroll.setMaximumHeight(scale(150))
        
        # Hide scrollbar but allow scrolling
        stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        stats_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        stats_widget = QWidget()
        stats_layout = QHBoxLayout(stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(scale(15))
        stats_layout.addStretch() # align center
        
        for lvl in level_details:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['glass_bg']};
                    border: 1px solid {COLORS['glass_border']};
                    border-radius: {scale(12)}px;
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(scale(15), scale(12), scale(15), scale(12))
            
            lbl_name = QLabel(lvl['name'])
            lbl_name.setStyleSheet(f"background: transparent; border: none; padding: 2px; color: {COLORS['burnt_orange']}; font-weight: bold; font-size: {scale(14)}px;")
            lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_name.setWordWrap(True)
            
            lbl_moves = QLabel(f"♟️ {lvl['moves']} Züge")
            lbl_moves.setStyleSheet(f"background: transparent; border: none; padding: 2px; color: {COLORS['brown_text']}; font-size: {scale(13)}px; font-weight: bold;")
            lbl_moves.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            lbl_elo = QLabel(f"🎓 Ziel-Elo: {lvl['target_elo']}")
            lbl_elo.setStyleSheet(f"background: transparent; border: none; padding: 2px; color: {COLORS['light_text']}; font-size: {scale(12)}px;")
            lbl_elo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            card_layout.addWidget(lbl_name)
            card_layout.addWidget(lbl_moves)
            card_layout.addWidget(lbl_elo)
            
            stats_layout.addWidget(card)
            
        stats_layout.addStretch() # align left
        stats_scroll.setWidget(stats_widget)
        
        # Optionally allow scroll gesture since scrollbar is hidden
        from PyQt6.QtWidgets import QScroller
        QScroller.grabGesture(stats_scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

        layout.addWidget(stats_scroll)
        
        # --- DESCRIPTION ---
        description = self.repertoire_info.get("description", "")
        if not description:
            description = "Dieses Repertoire wurde noch nicht mit einer Beschreibung versehen.<br><br><i>Tipp: Du kannst im Creator unter 'Repertoire-Einstellungen' eine Beschreibung hinzufügen!</i>"
        
        txt_desc = QTextBrowser()
        txt_desc.setHtml(f"<div style='font-size: {scale(10)}px; line-height: 1.6; color: {COLORS['brown_text']};'>{description}</div>")
        txt_desc.setStyleSheet(f"""
            QTextBrowser {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(15)}px;
                padding: {scale(15)}px;
            }}
        """)
        layout.addWidget(txt_desc, 1)
        
        # --- BUTTON ---
        btn_start = QPushButton("JETZT LERNEN")
        btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_start.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(25)}px;
                font-size: {scale(18)}px;
                font-weight: bold;
                padding: {scale(15)}px {scale(40)}px;
                margin-top: {scale(10)}px;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
                border: 2px solid rgba(255, 255, 255, 0.5);
            }}
            QPushButton:pressed {{
                background-color: #ba4a00;
            }}
        """)
        btn_start.clicked.connect(self.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_start)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
    def mousePressEvent(self, event):
        # Allow dragging the frameless window
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        # Allow dragging the frameless window
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_pos'):
            self.move(self.pos() + event.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = event.globalPosition().toPoint()
            event.accept()
