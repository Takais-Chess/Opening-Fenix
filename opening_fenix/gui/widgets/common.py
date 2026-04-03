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
