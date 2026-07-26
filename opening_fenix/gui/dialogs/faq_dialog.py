import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QWidget, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon
from opening_fenix.core.translation import tr_ui

def get_faq_items() -> list[tuple[str, str]]:
    from opening_fenix.core.utils import is_public_version

    faqs = [
        (
            tr_ui("faq.q1", "Wie soll ich mein Training gestalten?"),
            tr_ui("faq.a1", "Ich empfehle immer, zuerst die fälligen Züge zu üben und falls danach noch Zeit ist, ein paar Varianten auf einen Schlag zu lernen (ca. 20–50 Züge) und diese direkt zu üben.\n\nDiesem Muster ein paar Mal pro Woche folgen, bis das Repertoire sitzt, und danach alle paar Wochen die fälligen Züge erledigen.")
        ),
        (
            tr_ui("faq.q2", "Wie soll ich reagieren, wenn ich einen Zug falsch habe?"),
            tr_ui("faq.a2", "Denke kurz darüber nach, warum der Zug falsch ist, und schaue dann mithilfe des Lichess-Buttons nach, warum dein gewählter Zug schlecht ist.")
        ),
        (
            tr_ui("faq.q3", "Wie ändere ich das Trainingslevel und wann soll ich das machen?"),
            tr_ui("faq.a3", "Das Level kannst du in den Einstellungen des Trainers bei der Repertoire-Auswahl ändern. Man sollte das Level erhöhen, sobald das vorherige Level sitzt und auch die eigene Elo die Ziel-Elo für dieses Repertoire-Level überschritten hat.")
        )
    ]

    if is_public_version():
        faqs.append((
            tr_ui("faq.q4", "Möchtest du Fehler melden oder Änderungen am Programm vorschlagen?"),
            tr_ui("faq.a4", "Du kannst das auf diesem Discord tun: https://discord.gg/TevW5Wfkc")
        ))
        faqs.append((
            tr_ui("faq.q5", "Möchtest du mich unterstützen?"),
            tr_ui("faq.a5", "Teile das Programm und wenn du mich mit etwas Geld unterstützen möchtest, kannst du das hier tun: buymeacoffee.com/takais")
        ))

    return faqs

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
        
        formatted_answer = self._format_answer(answer)
        lbl_a = QLabel(f"A: {formatted_answer}")
        lbl_a.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(14)}px; line-height: 1.4;")
        lbl_a.setWordWrap(True)
        lbl_a.setOpenExternalLinks(True)
        
        layout.addWidget(lbl_q)
        layout.addWidget(lbl_a)

    def _format_answer(self, answer: str) -> str:
        url_pattern = re.compile(r'(https?://[^\s]+|buymeacoffee\.com/[^\s]+)')
        def replace_url(match):
            url = match.group(0)
            href = url if url.startswith('http') else f'https://{url}'
            return f'<a href="{href}" style="color: #d35400; text-decoration: underline;">{url}</a>'
            
        escaped = answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        return url_pattern.sub(replace_url, escaped)

class FAQDialog(QDialog):
    """
    A stylized dialog showing typical questions and answers about the app.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(tr_ui("faq.window_title", "Häufig gestellte Fragen (FAQ)"))
        self.setMinimumSize(scale(650), scale(550))
        set_consistent_icon(self)
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))
        layout.setSpacing(scale(20))
        
        # Header
        lbl_title = QLabel(tr_ui("faq.title", "Häufig gestellte Fragen"))
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
        faqs = get_faq_items()
        
        for q, a in faqs:
            content_layout.addWidget(FAQItem(q, a))
            
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Close Button
        btn_close = QPushButton(tr_ui("faq.btn_close", "VERSTANDEN"))
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

