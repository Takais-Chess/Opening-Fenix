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
        self._cached_font_key = None
        self._cached_font = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if text:
            self.setText(text)

    def setText(self, text: str):
        text_str = str(text) if text is not None else ""
        self._full_text = text_str
        self._cached_font_key = None
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
        text_flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter
        cache_key = (self._full_text, avail_rect.width(), avail_rect.height(), base_font.key())

        if self._cached_font_key == cache_key and self._cached_font is not None:
            chosen_font = self._cached_font
        else:
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
            self._cached_font_key = cache_key
            self._cached_font = chosen_font

        painter.setFont(chosen_font)

        # Get current text color based on button state (disabled, hovered, normal)
        color = option.palette.buttonText().color()
        if not self.isEnabled():
            color = option.palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
        painter.setPen(color)

        painter.drawText(avail_rect, int(text_flags), self._full_text)


def clear_table_safely(table, widget_cols=None) -> None:
    """
    Clears all rows and synchronously detaches/hides any QTableWidget cell widgets
    before scheduling deleteLater().

    Pass ``widget_cols`` (e.g. ``(3,)``) when only specific columns hold cell widgets
    to avoid scanning empty text-only columns.
    """
    rows = table.rowCount()
    cols = table.columnCount()
    if rows > 0 and cols > 0:
        target_cols = tuple(c for c in widget_cols if 0 <= c < cols) if widget_cols is not None else range(cols)
        for r in range(rows):
            for c in target_cols:
                w = table.cellWidget(r, c)
                if w is not None:
                    table.removeCellWidget(r, c)
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
    table.clearContents()
    table.setRowCount(0)

from PyQt6.QtWidgets import QScrollArea, QWidget
from PyQt6.QtGui import QColor, QLinearGradient


class _HorizontalEdgeFadeOverlay(QWidget):
    """Lightweight mouse-transparent edge fade painted only when horizontal overflow exists."""

    def __init__(self, scroll_area: QScrollArea, fade_color: QColor, fade_width: int):
        super().__init__(scroll_area.viewport())
        self._scroll_area = scroll_area
        self._fade_color = QColor(fade_color)
        self._fade_width = fade_width
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, event):
        sb = self._scroll_area.horizontalScrollBar()
        if sb is None or sb.maximum() <= 0:
            return
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        fw = min(self._fade_width, w // 3)
        if fw <= 0:
            return

        show_left = sb.value() > 0
        show_right = sb.value() < sb.maximum()
        if not show_left and not show_right:
            return

        painter = QPainter(self)
        transparent = QColor(self._fade_color.red(), self._fade_color.green(), self._fade_color.blue(), 0)

        if show_left:
            grad_l = QLinearGradient(0, 0, fw, 0)
            grad_l.setColorAt(0.0, self._fade_color)
            grad_l.setColorAt(1.0, transparent)
            painter.fillRect(0, 0, fw, h, grad_l)

        if show_right:
            grad_r = QLinearGradient(w - fw, 0, w, 0)
            grad_r.setColorAt(0.0, transparent)
            grad_r.setColorAt(1.0, self._fade_color)
            painter.fillRect(w - fw, 0, fw, h, grad_r)

        painter.end()


class FadingScrollArea(QScrollArea):
    """QScrollArea with soft left/right gradient fade whenever horizontal tabs overflow."""

    def __init__(self, parent=None, fade_color: QColor = None, fade_width: int = None):
        super().__init__(parent)
        color = fade_color if fade_color is not None else QColor(248, 245, 240, 245)
        fw = fade_width if fade_width is not None else scale(26)
        self._fade_overlay = _HorizontalEdgeFadeOverlay(self, color, fw)
        sb = self.horizontalScrollBar()
        sb.valueChanged.connect(self._fade_overlay.update)
        sb.rangeChanged.connect(self._fade_overlay.update)

    def setWidget(self, widget):
        super().setWidget(widget)
        self._sync_fade_overlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_fade_overlay()

    def _sync_fade_overlay(self):
        vp = self.viewport()
        if vp is not None and self._fade_overlay is not None:
            self._fade_overlay.setGeometry(vp.rect())
            self._fade_overlay.raise_()
            self._fade_overlay.update()

