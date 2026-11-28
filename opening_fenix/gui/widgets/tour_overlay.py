from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGraphicsDropShadowEffect, QSizePolicy
from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, pyqtSignal, QPropertyAnimation, QEasingCurve
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
        self._path_cache_key = None
        self._cached_bg_path = None
        self._cached_hole_rect = None
        
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
        layout.setSpacing(scale(10))
        
        self.lbl_title = QLabel("Titel")
        self.lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(20)}px; font-weight: bold;")
        self.lbl_title.setWordWrap(True)
        
        self.lbl_text = QLabel("Beschreibung...")
        self.lbl_text.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(15)}px;")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setOpenExternalLinks(True)
        self.lbl_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.lbl_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

        self.btn_action = QPushButton("")
        self.btn_action.setObjectName("TourActionBtn")
        self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_action.setVisible(False)
        self._apply_action_button_style(completed=False)
        self.btn_action.clicked.connect(self._on_action_clicked)
        
        # Footer with Buttons
        footer = QHBoxLayout()
        footer.setSpacing(scale(8))
        
        self.lbl_step = QLabel("1 / 5")
        self.lbl_step.setStyleSheet(f"color: {COLORS['light_text']}; font-size: {scale(12)}px;")
        
        self.btn_skip = QPushButton(tr_ui("tour.btn_skip", "Überspringen"))
        self.btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['light_text']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(15)}px;
                font-size: {scale(12)}px;
                font-weight: bold;
                padding: {scale(7)}px {scale(12)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 0, 0, 0.05);
                color: {COLORS['burnt_orange']};
                border-color: {COLORS['burnt_orange']};
            }}
        """)
        self.btn_skip.clicked.connect(self.skip)

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
        footer.addWidget(self.btn_skip)
        footer.addWidget(self.btn_next)
        
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_text, 1)
        layout.addWidget(self.btn_action)
        layout.addLayout(footer)

    def _apply_action_button_style(self, completed=False):
        if completed:
            self.btn_action.setStyleSheet(f"""
                QPushButton#TourActionBtn {{
                    background-color: #e8f8f0;
                    color: #1e8449;
                    border: 1.5px solid #27ae60;
                    border-radius: {scale(10)}px;
                    font-size: {scale(13)}px;
                    font-weight: bold;
                    padding: {scale(9)}px {scale(14)}px;
                }}
            """)
        else:
            self.btn_action.setStyleSheet(f"""
                QPushButton#TourActionBtn {{
                    background-color: #34495e;
                    color: white;
                    border: none;
                    border-radius: {scale(10)}px;
                    font-size: {scale(13)}px;
                    font-weight: bold;
                    padding: {scale(9)}px {scale(14)}px;
                }}
                QPushButton#TourActionBtn:hover {{ background-color: #2c3e50; }}
                QPushButton#TourActionBtn:pressed {{ background-color: #1f2d3a; }}
            """)

    def add_step(self, widget, title, text, action_text=None, action_callback=None, action_done_text=None):
        """Adds a step to the tour. widget can be None for a global welcome."""
        self.steps.append({
            'widget': widget,
            'title': title,
            'text': text,
            'action_text': action_text,
            'action_callback': action_callback,
            'action_done_text': action_done_text,
            'action_done': False,
        })

    def _on_action_clicked(self):
        if not self.steps or self.current_step < 0 or self.current_step >= len(self.steps):
            return
        step = self.steps[self.current_step]
        cb = step.get('action_callback')
        if callable(cb):
            res = cb()
            if res is True:
                step['action_done'] = True
                self.update_step()
        if self.isVisible():
            self.raise_()

    def start_tour(self):
        if not self.steps: 
            return
        if self.parent():
            try:
                self.parent().removeEventFilter(self)
                self.parent().installEventFilter(self)
            except Exception:
                pass
        self.current_step = 0
        self.show()
        self.raise_()
        self.update_step()
        self.btn_next.setFocus()

    def update_step(self):
        if not self.steps or self.current_step < 0 or self.current_step >= len(self.steps):
            return
        step = self.steps[self.current_step]
        self.lbl_title.setText(step['title'])
        self.lbl_text.setText(step['text'])
        self.lbl_step.setText(f"{self.current_step + 1} / {len(self.steps)}")
        
        self.btn_skip.setText(tr_ui("tour.btn_skip", "Überspringen"))
        if self.current_step == len(self.steps) - 1:
            self.btn_next.setText(tr_ui("tour.btn_finish", "FERTIG ✓"))
            self.btn_skip.setVisible(False)
        else:
            self.btn_next.setText(tr_ui("tour.btn_next", "WEITER →"))
            self.btn_skip.setVisible(True)

        action_text = step.get('action_text')
        if action_text:
            is_done = bool(step.get('action_done'))
            label = (step.get('action_done_text') or action_text) if is_done else action_text
            self.btn_action.setText(label)
            self.btn_action.setEnabled(not is_done)
            self._apply_action_button_style(completed=is_done)
            self.btn_action.setVisible(True)
        else:
            self.btn_action.setVisible(False)
            
        # Force layout update and compute exact wrapped heights so the last line is never clipped
        content_w = self.desc_card.width() - scale(40) - 4  # Account for 20px margins + 2px frame border per side
        self.lbl_title.setFixedWidth(content_w)
        self.lbl_text.setFixedWidth(content_w)
        self.lbl_title.setMinimumHeight(0)
        self.lbl_text.setMinimumHeight(0)
        self.lbl_title.updateGeometry()
        self.lbl_text.updateGeometry()

        title_h = self.lbl_title.heightForWidth(content_w)
        text_h = self.lbl_text.heightForWidth(content_w)
        if title_h > 0:
            self.lbl_title.setMinimumHeight(title_h + scale(2))
        if text_h > 0:
            self.lbl_text.setMinimumHeight(text_h + scale(6))

        self.desc_card.layout().invalidate()
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

    def _detach_event_filter(self):
        if self.parent():
            try:
                self.parent().removeEventFilter(self)
            except Exception:
                pass

    def advance(self):
        self.current_step += 1
        if self.current_step >= len(self.steps):
            self.hide()
            self._detach_event_filter()
            self.finished.emit()
            return
        self.update_step()

    def skip(self):
        """Immediately finishes the tour without viewing remaining steps."""
        self.hide()
        self._detach_event_filter()
        self.finished.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        target_key = (self.target_rect.x(), self.target_rect.y(), self.target_rect.width(), self.target_rect.height()) if self.target_rect else None
        cache_key = (rect.width(), rect.height(), target_key)
        if self._path_cache_key != cache_key or self._cached_bg_path is None:
            full_path = QPainterPath()
            full_path.addRect(QRectF(rect))
            if self.target_rect:
                padding = scale(5)
                hole_rect = QRectF(self.target_rect).adjusted(-padding, -padding, padding, padding)
                hole_path = QPainterPath()
                hole_path.addRoundedRect(hole_rect, scale(12), scale(12))
                self._cached_bg_path = full_path.subtracted(hole_path)
                self._cached_hole_rect = hole_rect
            else:
                self._cached_bg_path = full_path
                self._cached_hole_rect = None
            self._path_cache_key = cache_key

        painter.fillPath(self._cached_bg_path, QBrush(QColor(0, 0, 0, 160)))
        if self._cached_hole_rect is not None:
            painter.setPen(QPen(QColor(COLORS['burnt_orange']), scale(3)))
            painter.drawRoundedRect(self._cached_hole_rect, scale(12), scale(12))

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        # Reposition if parent resizes
        if obj == self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self.update_step()
        return super().eventFilter(obj, event)
