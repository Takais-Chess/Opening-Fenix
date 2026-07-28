from PyQt6.QtWidgets import QTextBrowser, QFrame, QSizePolicy
from PyQt6.QtCore import Qt, QSize

class ZoomableTextBrowser(QTextBrowser):
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoomIn()
            else:
                self.zoomOut()
            event.accept()
        else:
            super().wheelEvent(event)

class AspectRatioFrame(QFrame):
    """
    A frame that maintains a square aspect ratio based on its height.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        # Allow expanding in both directions
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_size()

    def adjust_size(self):
        # We no longer force a fixed width here. 
        # The ChessBoardWidget inside already handles its own square aspect ratio
        # during painting, and forcing a fixed width on the container breaks 
        # responsiveness in splitters (causing the right panel to be cut off).
        pass
            
    def sizeHint(self):
        # Default size hint
        return QSize(600, 600)


from PyQt6.QtWidgets import QPushButton, QStyleOptionButton, QStyle
from PyQt6.QtGui import QPainter, QFontMetrics, QFont, QPalette
from opening_fenix.gui.scaling import scale


class AutoAdjustButton(QPushButton):
    """
    A QPushButton subclass that automatically wraps text into multiple rows
    and dynamically resizes font size based on available button space.
    """
    def __init__(self, text="", parent=None):
        super().__init__("", parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if text:
            self.setText(text)

    def setText(self, text: str):
        text_str = str(text) if text is not None else ""
        self._full_text = text_str
        super().setText("")  # Keep standard text empty so paintEvent paints background without single-line clipped text
        self.setToolTip(text_str)
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._full_text

    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        if self._full_text:
            fm = QFontMetrics(self.font())
            text_size = fm.size(0, self._full_text)
            sh.setWidth(max(sh.width(), text_size.width() + scale(24)))
            sh.setHeight(max(sh.height(), scale(38)))
        return sh

    def minimumSizeHint(self) -> QSize:
        sh = super().minimumSizeHint()
        sh.setHeight(max(sh.height(), scale(36)))
        return sh

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event):
        # 1. Paint button background, border, hover states, focus rectangle via QSS / QStyle
        super().paintEvent(event)

        if not self._full_text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)

        padding_x = scale(6)
        padding_y = scale(4)
        avail_rect = rect.adjusted(padding_x, padding_y, -padding_x, -padding_y)
        if avail_rect.width() <= 0 or avail_rect.height() <= 0:
            return

        base_font = self.font()
        font_size = base_font.pointSize()
        is_pixel = False
        if font_size <= 0:
            font_size = base_font.pixelSize()
            is_pixel = True

        if font_size <= 0:
            font_size = 11

        max_size = font_size
        min_size = 6

        current_size = max_size
        text_flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter

        while current_size >= min_size:
            test_font = QFont(base_font)
            if is_pixel:
                test_font.setPixelSize(current_size)
            else:
                test_font.setPointSize(current_size)

            fm = QFontMetrics(test_font)
            bound_rect = fm.boundingRect(
                0, 0, avail_rect.width(), 10000,
                int(text_flags), self._full_text
            )

            if bound_rect.height() <= avail_rect.height() and bound_rect.width() <= avail_rect.width():
                break

            current_size -= 1

        chosen_font = QFont(base_font)
        if is_pixel:
            chosen_font.setPixelSize(max(current_size, min_size))
        else:
            chosen_font.setPointSize(max(current_size, min_size))

        painter.setFont(chosen_font)

        # Get current text color based on button state (disabled, hovered, normal)
        color = option.palette.buttonText().color()
        if not self.isEnabled():
            color = option.palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
        painter.setPen(color)

        painter.drawText(avail_rect, int(text_flags), self._full_text)

