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
        # Force the width to match the height to keep it square
        h = self.height()
        if h > 0 and self.width() != h:
            self.setFixedWidth(h)
            
    def sizeHint(self):
        # Default size hint
        return QSize(600, 600)
