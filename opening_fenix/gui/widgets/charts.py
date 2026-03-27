from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
from PyQt6.QtCore import Qt, QRectF

class PieChartWidget(QWidget):
    def __init__(self, parent=None, show_text=True):
        super().__init__(parent)
        self.show_text = show_text
        self.setMinimumSize(30, 30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.data = {}

    def update_stats(self, new_c, due_c, done_dist):
        self.data = {
            "new": new_c,
            "due": due_c,
            "learned": sum(done_dist.values())
        }
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        x_offset = (self.width() - side) / 2
        y_offset = (self.height() - side) / 2
        
        outer_rect = QRectF(x_offset, y_offset, side, side)
        thickness = side * 0.20 # Slightly thicker for small icons
        
        pen_track = QPen(QColor("#e0e0e0"), thickness)
        pen_track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_track)
        painter.drawArc(outer_rect.adjusted(thickness/2, thickness/2, -thickness/2, -thickness/2), 0, 360 * 16)

        total = sum(self.data.values())
        if total == 0: return

        start_angle = 90 * 16
        
        # New (Grey)
        new_angle = (self.data.get("new", 0) / total) * 360
        if new_angle > 0:
            pen = QPen(QColor("#a1a1aa"), thickness) 
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(outer_rect.adjusted(thickness/2, thickness/2, -thickness/2, -thickness/2), int(start_angle), int(new_angle * 16))
            start_angle += new_angle * 16
        
        # Due (Amber)
        due_angle = (self.data.get("due", 0) / total) * 360
        if due_angle > 0:
            pen = QPen(QColor("#f59e0b"), thickness)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(outer_rect.adjusted(thickness/2, thickness/2, -thickness/2, -thickness/2), int(start_angle), int(due_angle * 16))
            start_angle += due_angle * 16
        
        # Learned (Green)
        learned_angle = 360 - new_angle - due_angle
        if learned_angle > 0:
            pen = QPen(QColor("#2e7d32"), thickness)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(outer_rect.adjusted(thickness/2, thickness/2, -thickness/2, -thickness/2), int(start_angle), int(learned_angle * 16))

        if self.show_text:
            due_count = self.data.get("due", 0)
            font = painter.font()
            font.setPointSize(int(side * 0.35) if side < 100 else int(side * 0.25))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#f59e0b")) 
            painter.drawText(outer_rect, Qt.AlignmentFlag.AlignCenter, str(due_count))

            if side >= 100:
                font.setPointSize(int(side * 0.08))
                font.setBold(False)
                painter.setFont(font)
                painter.setPen(QColor("#a1a1aa")) 
                neu_rect = QRectF(outer_rect); neu_rect.translate(0, side * 0.25)
                painter.drawText(neu_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"Neu: {self.data.get('new', 0)}")
                painter.setPen(QColor("#2e7d32")) 
                gelernt_rect = QRectF(outer_rect); gelernt_rect.translate(0, side * 0.40)
                painter.drawText(gelernt_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"Gelernt: {self.data.get('learned', 0)}")
