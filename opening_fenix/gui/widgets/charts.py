from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap
from PyQt6.QtCore import Qt, QRectF
from opening_fenix.gui.scaling import scale

_COL_TRACK = QColor("#e0e0e0")
_COL_NEW = QColor("#a1a1aa")
_COL_DUE = QColor("#f59e0b")
_COL_LEARNED = QColor("#2e7d32")


class PieChartWidget(QWidget):

    def __init__(self, parent=None, show_text=True):
        super().__init__(parent)
        self.show_text = show_text
        self.setMinimumSize(scale(30), scale(30))

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.data = {}
        self._cached_pixmap = None
        self._cached_key = None

    def update_stats(self, new_c, due_c, done_dist):
        self.data = {
            "new": new_c,
            "due": due_c,
            "learned": sum(done_dist.values())
        }
        self._cached_key = None
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        dpr = self.devicePixelRatioF()
        new_c = self.data.get("new", 0)
        due_c = self.data.get("due", 0)
        learned_c = self.data.get("learned", 0)
        cache_key = (w, h, round(dpr, 4), new_c, due_c, learned_c, self.show_text, self.font().key())

        if self._cached_key != cache_key or self._cached_pixmap is None:
            pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)

            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            side = min(w, h)
            x_offset = (w - side) / 2
            y_offset = (h - side) / 2
            outer_rect = QRectF(x_offset, y_offset, side, side)
            thickness = side * 0.20
            arc_rect = outer_rect.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)

            pen_track = QPen(_COL_TRACK, thickness)
            pen_track.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen_track)
            p.drawArc(arc_rect, 0, 360 * 16)

            total = new_c + due_c + learned_c
            if total > 0:
                start_angle = 90 * 16
                new_angle = (new_c / total) * 360
                if new_angle > 0:
                    pen = QPen(_COL_NEW, thickness)
                    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                    p.setPen(pen)
                    p.drawArc(arc_rect, int(start_angle), int(new_angle * 16))
                    start_angle += new_angle * 16

                due_angle = (due_c / total) * 360
                if due_angle > 0:
                    pen = QPen(_COL_DUE, thickness)
                    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                    p.setPen(pen)
                    p.drawArc(arc_rect, int(start_angle), int(due_angle * 16))
                    start_angle += due_angle * 16

                learned_angle = 360 - new_angle - due_angle
                if learned_angle > 0:
                    pen = QPen(_COL_LEARNED, thickness)
                    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                    p.setPen(pen)
                    p.drawArc(arc_rect, int(start_angle), int(learned_angle * 16))

                if self.show_text:
                    due_str = str(due_c)
                    char_count = len(due_str)
                    if char_count <= 2:
                        font_factor = 0.25
                    elif char_count == 3:
                        font_factor = 0.21
                    elif char_count == 4:
                        font_factor = 0.17
                    else:
                        font_factor = 0.13

                    font = p.font()
                    font.setPointSize(int(side * 0.35) if side < 100 else int(side * font_factor))
                    font.setBold(True)
                    p.setFont(font)
                    p.setPen(_COL_DUE)
                    p.drawText(outer_rect, Qt.AlignmentFlag.AlignCenter, due_str)

                    if side >= 100:
                        font.setPointSize(int(side * 0.08))
                        font.setBold(False)
                        p.setFont(font)
                        p.setPen(_COL_NEW)
                        neu_rect = QRectF(outer_rect)
                        neu_rect.translate(0, side * 0.25)
                        p.drawText(neu_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"Neu: {new_c}")
                        p.setPen(_COL_LEARNED)
                        gelernt_rect = QRectF(outer_rect)
                        gelernt_rect.translate(0, side * 0.40)
                        p.drawText(gelernt_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"Gelernt: {learned_c}")

            p.end()
            self._cached_pixmap = pm
            self._cached_key = cache_key

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cached_pixmap)
