from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QWidget, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon

class FAQItem(QFrame):
    def __init__(self, question, answer, parent=None):
        super().__init__(parent)
        self.setObjectName("FAQItem")
        self.setStyleSheet(f"""
            QFrame#FAQItem {{
                background-color: {COLORS['glass_bg']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
                padding: {scale(15)}px;
                margin-bottom: {scale(15)}px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(8))
        
        lbl_q = QLabel(f"Q: {question}")
        lbl_q.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-weight: bold; font-size: {scale(16)}px;")
        lbl_q.setWordWrap(True)
        
        lbl_a = QLabel(f"A: {answer}")
        lbl_a.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(14)}px; line-height: 1.4;")
        lbl_a.setWordWrap(True)
        
        layout.addWidget(lbl_q)
        layout.addWidget(lbl_a)

class FAQDialog(QDialog):
    """
    A stylized dialog showing typical questions and answers about the app.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Häufig gestellte Fragen (FAQ)")
        self.setMinimumSize(scale(650), scale(550))
        set_consistent_icon(self)
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))
        layout.setSpacing(scale(20))
        
        # Header
        lbl_title = QLabel("Häufig gestellte Fragen")
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(28)}px; font-weight: 900;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        # Scroll Area for FAQ Items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, scale(15), 0)
        
        # --- DATA ---
        faqs = [
            (
                "Wie soll ich mein Training gestalten?",
                "Ich empfehle immer, zuerst die fälligen Züge zu üben und falls danach noch Zeit ist, ein paar Varianten auf einen Schlag zu lernen (ca. 20–50 Züge) und diese direkt zu üben.\n\nDiesem Muster ein paar Mal pro Woche folgen, bis das Repertoire sitzt, und danach alle paar Wochen die fälligen Züge erledigen."
            ),
            (
                "Wie soll ich reagieren, wenn ich einen Zug falsch habe?",
                "Denke kurz darüber nach, warum der Zug falsch ist, und schaue dann mithilfe des Lichess-Buttons nach, warum dein gewählter Zug schlecht ist."
            ),
            (
                "Wie ändere ich das Trainingslevel und wann soll ich das machen?",
                "Das Level kannst du in den Einstellungen des Trainers bei der Repertoire-Auswahl ändern. Man sollte das Level erhöhen, sobald das vorherige Level sitzt und auch die eigene Elo die Ziel-Elo für dieses Repertoire-Level überschritten hat."
            )
        ]
        
        for q, a in faqs:
            content_layout.addWidget(FAQItem(q, a))
            
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Close Button
        btn_close = QPushButton("VERSTANDEN")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(20)}px;
                font-weight: bold;
                padding: {scale(12)}px {scale(30)}px;
            }}
            QPushButton:hover {{ background-color: #e67e22; }}
        """)
        btn_close.clicked.connect(self.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Apply basic fusion background
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['beige']}; }}")
