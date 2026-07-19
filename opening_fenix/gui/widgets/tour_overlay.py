from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGraphicsDropShadowEffect, QSizePolicy
from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QRegion, QFont, QPainterPath

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS
from opening_fenix.core.translation import tr_ui

class GuidedTourOverlay(QWidget):
    """
    A full-screen overlay that highlights specific widgets (spotlight)
    and shows an explanation description box.
    """
    finished = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Ensure it covers the whole parent
        if parent:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        
        self.steps = []
        self.current_step = 0
        self.target_rect = None
        
        self.init_ui()
        self.hide()

    def init_ui(self):
        # Description Card (The box showing the text)
        self.desc_card = QFrame(self)
        self.desc_card.setObjectName("TourDescCard")
        self.desc_card.setFixedWidth(scale(380))
        # Remove fixed height to allow dynamic growth
        self.desc_card.setStyleSheet(f"""
            QFrame#TourDescCard {{
                background-color: {COLORS['beige']};
                border: 2px solid {COLORS['burnt_orange']};
                border-radius: {scale(15)}px;
            }}
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 100))
        self.desc_card.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self.desc_card)
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        
        self.lbl_title = QLabel("Titel")
        self.lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(20)}px; font-weight: bold;")
        self.lbl_title.setWordWrap(True)
        
        self.lbl_text = QLabel("Beschreibung...")
        self.lbl_text.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(15)}px;")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        
        # Footer with Buttons
        footer = QHBoxLayout()
        
        self.lbl_step = QLabel("1 / 5")
        self.lbl_step.setStyleSheet(f"color: {COLORS['light_text']}; font-size: {scale(12)}px;")
        
        self.btn_next = QPushButton(tr_ui("tour.btn_next", "WEITER →"))
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(15)}px;
                font-weight: bold;
                padding: {scale(8)}px {scale(20)}px;
            }}
            QPushButton:hover {{ background-color: #e67e22; }}
        """)
        self.btn_next.clicked.connect(self.advance)
        
        footer.addWidget(self.lbl_step)
        footer.addStretch()
        footer.addWidget(self.btn_next)
        
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_text, 1)
        layout.addLayout(footer)

    def add_step(self, widget, title, text):
        """Adds a step to the tour. widget can be None for a global welcome."""
        self.steps.append({'widget': widget, 'title': title, 'text': text})

    def start_tour(self):
        if not self.steps: 
            return
        self.current_step = 0
        self.show()
        self.update_step()

    def update_step(self):
        if not self.steps or self.current_step < 0 or self.current_step >= len(self.steps):
            return
        step = self.steps[self.current_step]
        self.lbl_title.setText(step['title'])
        self.lbl_text.setText(step['text'])
        self.lbl_step.setText(f"{self.current_step + 1} / {len(self.steps)}")
        
        if self.current_step == len(self.steps) - 1:
            self.btn_next.setText(tr_ui("tour.btn_finish", "FERTIG ✓"))
        else:
            self.btn_next.setText(tr_ui("tour.btn_next", "WEITER →"))
            
        # Force layout update and resize to fit content before positioning
        self.lbl_title.setFixedWidth(self.desc_card.width() - scale(40)) # Account for margins
        self.lbl_text.setFixedWidth(self.desc_card.width() - scale(40))
        
        self.desc_card.layout().activate()
        self.desc_card.adjustSize()
        
        widget = step['widget']
        if widget:
            # Map widget rect to overlay coordinates
            global_pos = widget.mapToGlobal(QPoint(0, 0))
            local_pos = self.mapFromGlobal(global_pos)
            self.target_rect = QRect(local_pos.x(), local_pos.y(), widget.width(), widget.height())
            
            # Position description card near the target
            self.position_desc_card()
        else:
            self.target_rect = None
            # Center in screen
            self.desc_card.move(
                (self.width() - self.desc_card.width()) // 2,
                (self.height() - self.desc_card.height()) // 2
            )
            
        self.update()

    def position_desc_card(self):
        # Heuristic: Place card below if space, otherwise above, or to the side
        card_w, card_h = self.desc_card.width(), self.desc_card.height()
        target = self.target_rect
        
        # Try below
        new_x = target.center().x() - (card_w // 2)
        new_y = target.bottom() + scale(20)
        
        # Clamp X to screen
        new_x = max(scale(20), min(new_x, self.width() - card_w - scale(20)))
        
        # If below is out of screen, try above
        if new_y + card_h > self.height() - scale(40):
            new_y = target.top() - card_h - scale(20)
            
        # Final safety clamp for Y
        new_y = max(scale(20), min(new_y, self.height() - card_h - scale(20)))
            
        self.desc_card.move(round(new_x), round(new_y))

    def advance(self):
        self.current_step += 1
        if self.current_step >= len(self.steps):
            self.hide()
            self.finished.emit()
            return
        self.update_step()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Create a path for the whole overlay
        full_path = QPainterPath()
        full_path.addRect(QRectF(self.rect()))
        
        # If we have a target, subtract it from the full path to create a hole
        if self.target_rect:
            padding = scale(5)
            hole_rect = QRectF(self.target_rect).adjusted(-padding, -padding, padding, padding)
            hole_path = QPainterPath()
            hole_path.addRoundedRect(hole_rect, scale(12), scale(12))
            
            # Combine paths: full overlay minus the hole
            final_path = full_path.subtracted(hole_path)
            
            # 1. Draw the dimmed overlay (the area with the hole)
            painter.fillPath(final_path, QBrush(QColor(0, 0, 0, 160)))
            
            # 2. Draw a highlight border around the hole
            painter.setPen(QPen(QColor(COLORS['burnt_orange']), scale(3)))
            painter.drawRoundedRect(hole_rect, scale(12), scale(12))
        else:
            # No target, just dim everything
            painter.fillPath(full_path, QBrush(QColor(0, 0, 0, 160)))

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        # Reposition if parent resizes
        if obj == self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self.update_step()
        return super().eventFilter(obj, event)

from PyQt6.QtCore import QRectF
