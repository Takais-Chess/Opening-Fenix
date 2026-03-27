import os
import sys
import math
import time
import chess
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QIcon, QPixmap, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QPoint, QTimer, QPointF
from PyQt6.QtSvg import QSvgRenderer
from opening_fenix.core.data_tools import get_base_path

THEMES = {
    "Dunkel (Modern)": (QColor("#71717a"), QColor("#3f3f46")),
    "Grün (Lichess)": (QColor(240, 217, 181), QColor(118, 150, 86)),
    "Braun (Klassisch)": (QColor(240, 217, 181), QColor(181, 136, 99)),
    "Blau (Turnier)": (QColor(232, 235, 239), QColor(125, 135, 150)),
    "Grau (Neutral)": (QColor(240, 240, 240), QColor(160, 160, 160)),
    "Icy Sea": (QColor(211, 220, 227), QColor(108, 166, 192))
}

class ChessBoardWidget(QWidget):
    move_executed = pyqtSignal(chess.Move)
    piece_slide_finished = pyqtSignal()
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.board = chess.Board()
        self.flipped = False
        self.padding = 25 # Space for notation labels
        self.pieces = {}
        self.piece_pixmaps = {} 
        self._last_scaled_size = 0
        self.load_pieces()
        self.light_color, self.dark_color = THEMES["Blau (Turnier)"]
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.dragging_piece = None
        self.drag_start_square = None
        self.mouse_pos = QPoint()
        self.is_animating = False
        self.last_move = None
        self.hint_arrow = None
        self.solution_arrow = None
        self.explorer_arrows = [] 
        self.animating_piece_data = None  
        self.slide_timer = QTimer(self)
        self.slide_timer.timeout.connect(self._animate_piece_frame) 

    def get_metrics(self):
        side = max(0, min(self.width(), self.height()) - self.padding * 2)
        square_size = side / 8.0
        x_offset = (self.width() - side) / 2
        y_offset = (self.height() - side) / 2
        return side, square_size, x_offset, y_offset

    def set_theme(self, theme_name):
        if theme_name in THEMES:
            self.light_color, self.dark_color = THEMES[theme_name]
        else:
            self.light_color, self.dark_color = THEMES["Blau (Turnier)"]
        self.update()

    def load_pieces(self):
        pieces = ['P', 'N', 'B', 'R', 'Q', 'K']
        colors = ['w', 'b']
        assets_path = os.path.join(get_base_path(), "assets", "pieces")
        for c in colors:
            for p in pieces:
                filename = f"{c}{p}.svg"
                path = os.path.join(assets_path, filename)
                if os.path.exists(path):
                    self.pieces[f"{c}{p}"] = QSvgRenderer(path)
        self.piece_pixmaps = {} 
        self._last_scaled_size = 0

    def _update_pixmap_cache(self, square_size):
        dpr = self.devicePixelRatioF()
        scaled_size = int(square_size * dpr)
        if scaled_size == self._last_scaled_size: return
        self._last_scaled_size = scaled_size
        self.piece_pixmaps = {}
        for key, renderer in self.pieces.items():
            pixmap = QPixmap(scaled_size, scaled_size)
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            renderer.render(painter, QRectF(0, 0, square_size, square_size))
            painter.end()
            self.piece_pixmaps[key] = pixmap

    def set_fen(self, fen):
        self.board.set_fen(fen)
        self.last_move = None
        self.hint_arrow = None
        self.solution_arrow = None
        self.explorer_arrows = []
        self.update() 

    def get_square_from_pos(self, pos):
        side, square_size, x_offset, y_offset = self.get_metrics()
        x = pos.x() - x_offset
        y = pos.y() - y_offset
        if x < 0 or x >= side or y < 0 or y >= side: return None
        col = int(x / square_size)
        row = int(y / square_size)
        rank = row if self.flipped else 7 - row
        file = 7 - col if self.flipped else col
        return chess.square(file, rank)

    def mousePressEvent(self, event):
        if self.is_animating:
            if self.animating_piece_data:
                self.slide_timer.stop()
                move = self.animating_piece_data['move']
                self.board.push(move)
                self.last_move = move
                self.animating_piece_data = None
                self.is_animating = False
                self.piece_slide_finished.emit()
                self.update()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            square = self.get_square_from_pos(event.position())
            if square is not None:
                piece = self.board.piece_at(square)
                if piece and piece.color == self.board.turn:
                    self.dragging_piece = piece
                    self.drag_start_square = square
                    self.mouse_pos = event.position().toPoint()
                    self.update()

    def mouseMoveEvent(self, event):
        if self.dragging_piece:
            self.mouse_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging_piece:
            end_square = self.get_square_from_pos(event.position())
            if end_square is not None and self.drag_start_square is not None:
                move = None
                if self.dragging_piece.piece_type == chess.KING:
                    target = self.board.piece_at(end_square)
                    if target and target.color == self.dragging_piece.color and target.piece_type == chess.ROOK:
                        for cand in self.board.legal_moves:
                            if self.board.is_castling(cand):
                                if chess.square_file(end_square) > chess.square_file(self.drag_start_square):
                                    if self.board.is_kingside_castling(cand): move = cand; break
                                elif chess.square_file(end_square) < chess.square_file(self.drag_start_square):
                                    if self.board.is_queenside_castling(cand): move = cand; break
                if move is None:
                    is_promo = (self.dragging_piece.piece_type == chess.PAWN and (chess.square_rank(end_square) in [0, 7]))
                    promotion = chess.QUEEN if is_promo else None
                    move = chess.Move(self.drag_start_square, end_square, promotion=promotion)
                if move in self.board.legal_moves: self.move_executed.emit(move)
            self.dragging_piece = None
            self.drag_start_square = None
            self.update()

    def _draw_arrow(self, painter, start, end, color, square_size):
        f1, r1 = chess.square_file(start), chess.square_rank(start)
        f2, r2 = chess.square_file(end), chess.square_rank(end)
        if self.flipped: r1=r1; c1=7-f1; r2=r2; c2=7-f2
        else: r1=7-r1; c1=f1; r2=7-r2; c2=f2
        x1, y1 = (c1 + 0.5) * square_size, (r1 + 0.5) * square_size
        x2, y2 = (c2 + 0.5) * square_size, (r2 + 0.5) * square_size
        dx, dy = x2 - x1, y2 - y1
        length = math.sqrt(dx*dx + dy*dy)
        if length > 0:
            angle = math.atan2(dy, dx)
            # Modern Design: Tapered shaft and sharp, small arrowhead
            head_len = square_size * 0.4
            head_width = square_size * 0.35
            shaft_start_width = square_size * 0.08 # Thin tail
            shaft_end_width = square_size * 0.15   # Tapered to head
            
            # 1. Calculate the base of the arrowhead (where shaft ends)
            x_head_base, y_head_base = x2 - (head_len * 0.8) * math.cos(angle), y2 - (head_len * 0.8) * math.sin(angle)
            
            # 2. Draw Tapered Shaft using a Polygon for premium look
            perp_angle = angle + math.pi / 2
            
            # Define 4 points for the shaft polygon
            p1 = QPointF(x1 + (shaft_start_width/2) * math.cos(perp_angle), y1 + (shaft_start_width/2) * math.sin(perp_angle))
            p2 = QPointF(x1 - (shaft_start_width/2) * math.cos(perp_angle), y1 - (shaft_start_width/2) * math.sin(perp_angle))
            p3 = QPointF(x_head_base - (shaft_end_width/2) * math.cos(perp_angle), y_head_base - (shaft_end_width/2) * math.sin(perp_angle))
            p4 = QPointF(x_head_base + (shaft_end_width/2) * math.cos(perp_angle), y_head_base + (shaft_end_width/2) * math.sin(perp_angle))
            
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([p1, p2, p3, p4]))
            
            # 3. Draw Sharper Arrowhead
            arrow_p1 = QPointF(x2 - head_len * math.cos(angle - math.pi/7), y2 - head_len * math.sin(angle - math.pi/7))
            arrow_p2 = QPointF(x2 - head_len * math.cos(angle + math.pi/7), y2 - head_len * math.sin(angle + math.pi/7))
            
            # Offset the head slightly back for better alignment
            # (Calculated by drawing from x2,y2)
            painter.drawPolygon(QPolygonF([QPointF(x2, y2), arrow_p1, arrow_p2]))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        side, square_size, x_offset, y_offset = self.get_metrics()
        painter.translate(x_offset, y_offset)
        
        self._update_pixmap_cache(square_size)
        
        # 1. Draw Squares
        for row in range(8):
            for col in range(8):
                color = self.light_color if (row + col) % 2 == 0 else self.dark_color
                painter.setBrush(QBrush(color)); painter.setPen(Qt.PenStyle.NoPen); painter.drawRect(QRectF(col * square_size, row * square_size, square_size, square_size))
        
        # 2. Draw Coordinates
        painter.setPen(QColor("#4b4b4b")) # Subtle dark gray
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(9, int(square_size / 5.5)))
        painter.setFont(font)
        
        for i in range(8):
            # Rank numbers (1-8) on the left
            rank_num = i + 1 if self.flipped else 8 - i
            rank_rect = QRectF(-self.padding, i * square_size, self.padding - 5, square_size)
            painter.drawText(rank_rect, Qt.AlignmentFlag.AlignCenter, str(rank_num))
            
            # File letters (a-h) on the bottom
            file_char = chr(ord('h') - i if self.flipped else ord('a') + i)
            file_rect = QRectF(i * square_size, 8 * square_size, square_size, self.padding)
            painter.drawText(file_rect, Qt.AlignmentFlag.AlignCenter, file_char)

        if self.last_move:
            painter.setBrush(QBrush(QColor(255, 255, 0, 100)))
            for sq in [self.last_move.from_square, self.last_move.to_square]:
                f, r = chess.square_file(sq), chess.square_rank(sq)
                rd, cd = (r if self.flipped else 7 - r), (7 - f if self.flipped else f)
                painter.drawRect(QRectF(cd * square_size, rd * square_size, square_size, square_size))
        
        for row in range(8):
            for col in range(8):
                rank, file = (row if self.flipped else 7 - row), (7 - col if self.flipped else col)
                sq = chess.square(file, rank)
                if self.animating_piece_data and sq == self.animating_piece_data['from_square']: continue
                if self.drag_start_square == sq and self.dragging_piece: continue 
                piece = self.board.piece_at(sq)
                if piece: self.draw_piece(painter, piece, col, row, square_size)
        
        if self.animating_piece_data:
            d = self.animating_piece_data; p = d['progress']
            cur_col, cur_row = d['start_col'] + (d['end_col'] - d['start_col']) * p, d['start_row'] + (d['end_row'] - d['start_row']) * p
            self.draw_piece(painter, d['piece'], cur_col, cur_row, square_size)
        
        if self.dragging_piece:
            mx, my = self.mouse_pos.x() - x_offset, self.mouse_pos.y() - y_offset
            target_rect = QRectF(mx - square_size/2, my - square_size/2, square_size, square_size)
            key = f"{'w' if self.dragging_piece.color == chess.WHITE else 'b'}{self.dragging_piece.symbol().upper()}"
            if key in self.piece_pixmaps: painter.drawPixmap(target_rect.toRect(), self.piece_pixmaps[key])

        if self.hint_arrow: self._draw_arrow(painter, self.hint_arrow.from_square, self.hint_arrow.to_square, QColor(20, 60, 150, 120), square_size)
        if self.solution_arrow: self._draw_arrow(painter, self.solution_arrow.from_square, self.solution_arrow.to_square, QColor(20, 60, 150, 120), square_size)
        for move, color in self.explorer_arrows: self._draw_arrow(painter, move.from_square, move.to_square, color, square_size)

    def start_piece_slide(self, piece, from_square, to_square, move):
        ff, fr = chess.square_file(from_square), chess.square_rank(from_square)
        tf, tr = chess.square_file(to_square), chess.square_rank(to_square)
        if self.flipped: sc, sr, ec, er = 7 - ff, fr, 7 - tf, tr
        else: sc, sr, ec, er = ff, 7 - fr, tf, 7 - tr
        anim_speed = 300
        if self.main_window and hasattr(self.main_window, 'training_manager'): anim_speed = self.main_window.training_manager.get_setting("anim_speed") or 300
        self.animating_piece_data = {'piece': piece, 'from_square': from_square, 'to_square': to_square, 'start_col': sc, 'start_row': sr, 'end_col': ec, 'end_row': er, 'progress': 0.0, 'move': move, 'start_time': time.time(), 'duration': anim_speed / 1000.0}
        self.is_animating = True
        self.slide_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.slide_timer.start(10) # 100 FPS for maximum smoothness
        self.update() 

    def abort_piece_slide(self):
        """Immediately stops any ongoing animation and clears animation data."""
        if self.is_animating:
            self.slide_timer.stop()
            self.is_animating = False
            self.animating_piece_data = None
            self.update()

    def _animate_piece_frame(self):
        if not self.animating_piece_data: self.slide_timer.stop(); return
        d = self.animating_piece_data; t = min(1.0, (time.time() - d['start_time']) / d['duration']) if d['duration'] > 0 else 1.0
        d['progress'] = 2 * t * t if t < 0.5 else -1 + (4 - 2 * t) * t
        if t >= 1.0:
            d['progress'] = 1.0; self.slide_timer.stop(); self.is_animating = False
            self.board.push(d['move']); self.last_move = d['move']; self.animating_piece_data = None; self.piece_slide_finished.emit() 
        self.update()

    def draw_piece(self, painter, piece, col, row, size):
        key = f"{ 'w' if piece.color == chess.WHITE else 'b' }{piece.symbol().upper()}"
        if key in self.piece_pixmaps:
            target_rect = QRectF(col * size, row * size, size, size)
            painter.drawPixmap(target_rect, self.piece_pixmaps[key], QRectF(self.piece_pixmaps[key].rect()))
