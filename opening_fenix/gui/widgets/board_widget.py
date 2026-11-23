import os
import sys
import math
import time
import ctypes
import gc
import chess

def _set_winmm_timer_period(enable: bool) -> None:
    """Acquires or releases 1ms Windows kernel timer resolution strictly around active animations."""
    if sys.platform != "win32":
        return
    try:
        if enable:
            ctypes.windll.winmm.timeBeginPeriod(1)
        else:
            ctypes.windll.winmm.timeEndPeriod(1)
    except Exception:
        pass

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QIcon, QPixmap, QFont
from PyQt6.QtCore import Qt, QRect, QRectF, pyqtSignal, QPoint, QTimer, QPointF, QSize, QVariantAnimation, QEasingCurve
from PyQt6.QtSvg import QSvgRenderer
from opening_fenix.core.data_tools import get_base_path
from opening_fenix.core.logger import logger
from opening_fenix.gui.scaling import scale

# Fast O(1) lookup table for piece pixmap keys (avoids string allocations in 144Hz animation paint loop)
PIECE_KEY_MAP = {}
for _pt in range(1, 7):
    _sym = chess.PIECE_SYMBOLS[_pt].upper()
    PIECE_KEY_MAP[(_pt, True)] = f"w{_sym}"
    PIECE_KEY_MAP[(_pt, False)] = f"b{_sym}"


def normalize_text_encoding(text: str) -> str:
    """Repairs recursive CP1252/latin1 double/triple encoding mojibake (e.g. GrÃ¼n -> Grün)."""
    if not isinstance(text, str):
        return text
    for _ in range(3):
        try:
            fixed = text.encode("cp1252").decode("utf-8")
            if fixed != text:
                text = fixed
            else:
                break
        except (UnicodeEncodeError, UnicodeDecodeError):
            try:
                fixed = text.encode("latin1").decode("utf-8")
                if fixed != text:
                    text = fixed
                else:
                    break
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
    return text


THEMES = {
    "Dunkel (Modern)": (QColor("#71717a"), QColor("#3f3f46")),
    "Grün": (QColor(240, 217, 181), QColor(118, 150, 86)),
    "Braun (Klassisch)": (QColor(240, 217, 181), QColor(181, 136, 99)),
    "Blau (Turnier)": (QColor(232, 235, 239), QColor(125, 135, 150)),
    "Grau (Neutral)": (QColor(240, 240, 240), QColor(160, 160, 160)),
    "Icy Sea": (QColor(211, 220, 227), QColor(108, 166, 192))
}

THEME_FALLBACKS = {
    "Dark (Modern)": "Dunkel (Modern)",
    "Grün (Lichess)": "Grün",
    "Green (Lichess)": "Grün",
    "Green": "Grün",
    "Brown (Classic)": "Braun (Klassisch)",
    "Blue (Tournament)": "Blau (Turnier)",
    "Grey (Neutral)": "Grau (Neutral)",
    "GrÃ¼n": "Grün",
    "Gr\u00c3\u0192\u00c2\u00bcn": "Grün",
    "Gr\u00c3\u00bcn": "Grün",
}

HIGHLIGHT_COLORS = {
    "Gelb (Standard)": QColor(255, 255, 0, 100),
    "Grün": QColor(34, 197, 94, 110),
    "Blau": QColor(59, 130, 246, 110),
    "Orange": QColor(249, 115, 22, 110),
    "Burnt Orange": QColor(245, 158, 11, 110),
    "Rot": QColor(239, 68, 68, 110),
    "Lila": QColor(168, 85, 247, 110),
    "Türkis": QColor(6, 182, 212, 110),
}

HIGHLIGHT_COLOR_FALLBACKS = {
    "Yellow (Default)": "Gelb (Standard)",
    "Yellow": "Gelb (Standard)",
    "Green": "Grün",
    "Blue": "Blau",
    "Orange": "Orange",
    "Burnt Orange": "Burnt Orange",
    "Amber": "Burnt Orange",
    "Bernstein": "Burnt Orange",
    "Rostorange": "Burnt Orange",
    "Red": "Rot",
    "Purple": "Lila",
    "Turquoise": "Türkis",
    "Cyan": "Türkis",
    "GrÃ¼n": "Grün",
    "Gr\u00c3\u0192\u00c2\u00bcn": "Grün",
    "Gr\u00c3\u00bcn": "Grün",
    "TÃ¼rkis": "Türkis",
    "T\u00c3\u0192\u00c2\u00bcrkis": "Türkis",
    "T\u00c3\u00bcrkis": "Türkis",
}

# ChessBase standard arrow and highlight colors
USER_ARROW_COLORS = {
    "green": QColor(34, 197, 94, 210),   # Default RMB
    "red": QColor(239, 68, 68, 210),     # Alt + RMB
    "yellow": QColor(245, 158, 11, 220), # Ctrl + RMB
    "blue": QColor(59, 130, 246, 210),   # Shift + RMB
    "orange": QColor(249, 115, 22, 210), # Ctrl+Alt / Shift+Alt + RMB
}

USER_HIGHLIGHT_COLORS = {
    "green": QColor(34, 197, 94, 220),
    "red": QColor(239, 68, 68, 220),
    "yellow": QColor(245, 158, 11, 230),
    "blue": QColor(59, 130, 246, 220),
    "orange": QColor(249, 115, 22, 220),
}


class ChessBoardWidget(QWidget):
    move_executed = pyqtSignal(chess.Move)
    piece_slide_finished = pyqtSignal()
    skip_all_animations_requested = pyqtSignal()
    drawings_changed = pyqtSignal()
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.board = chess.Board()
        self.flipped = False
        self.padding = scale(26) # Space for notation labels
        self.pieces = {}

        self.piece_pixmaps = {} 
        self._last_scaled_size = 0
        self.load_pieces()
        self.light_color, self.dark_color = THEMES["Braun (Klassisch)"]
        self.highlight_color = HIGHLIGHT_COLORS["Gelb (Standard)"]
        self._light_brush = QBrush(self.light_color)
        self._dark_brush = QBrush(self.dark_color)
        self._highlight_brush = QBrush(self.highlight_color)
        self.setMinimumSize(scale(400), scale(400))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.dragging_piece = None
        self.drag_start_square = None
        self.mouse_pos = QPointF()
        self.is_animating = False
        self.last_move = None
        self.hint_arrow = None
        self.solution_arrow = None
        self.explorer_arrows = [] 
        self.animating_piece_data = None

        # ChessBase-style user drawings (interactive arrows & square highlights)
        self.user_arrows = {}       # (from_sq, to_sq) -> QColor
        self.user_highlights = {}   # sq -> QColor
        self.is_drawing = False
        self.drawing_start_sq = None
        self.drawing_current_sq = None
        self.drawing_color = None
        self.drawing_highlight_color = None  
        
        # New QVariantAnimation for premium, smooth piece slides
        self.move_anim = QVariantAnimation(self)
        self.move_anim.valueChanged.connect(self._on_animation_frame)
        self.move_anim.finished.connect(self._on_animation_finished)
        self.move_anim.setEasingCurve(QEasingCurve.Type.OutSine)
        
        # High-Precision Animation Driver matching monitor refresh rate
        self.precise_anim_timer = QTimer(self)
        self.precise_anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.precise_anim_timer.timeout.connect(self._on_precise_anim_tick)

        # Animation Debug & Smoothness Options
        self.debug_anim = False  # Set False to disable debug overlay and FPS console logs
        self.enable_piece_lift = False  # Set False for Lichess-style flat 2D slide (no 1.15 scale jitter)
        self._anim_start_time = 0.0
        self._anim_frame_times = []
        self._anim_setup_ms = 0.0
        self._inter_move_ms = 0.0
        self._last_slide_end_time = 0.0
        self._last_anim_stats = None
        self._last_configured_anim_speed = None
        self._duration_lut = {}
        self._gc_disabled_for_anim = False
        self._winmm_timer_active = False
        self._snapshot_skip_sq = None
        self._coord_color = QColor("#4b4b4b")
        self._coord_font_cache = None
        self._board_snapshot = None
        self._snapshot_buffer = None
        self._snapshot_flipped = None
        self._snapshot_size = None
        self._squares_pixmap = None
        self._squares_pixmap_key = None
        self._last_anim_dirty_rect = None
        self._last_drag_dirty_rect = None
        self._needs_full_board_paint = True
        self._is_resizing = False
        self._resize_settle_timer = QTimer(self)
        self._resize_settle_timer.setSingleShot(True)
        self._resize_settle_timer.setInterval(90)
        self._resize_settle_timer.timeout.connect(self._on_resize_settled)
        self.update_animation_metrics()

    def _invalidate_snapshot(self):
        """Invalidates the cached static board snapshot."""
        self._board_snapshot = None
        self._snapshot_skip_sq = None
        self._last_anim_dirty_rect = None

    def _on_resize_settled(self):
        """Re-rasterizes crisp SVG piece pixmaps once interactive resizing pauses."""
        self._is_resizing = False
        _, square_size, _, _ = self.get_metrics()
        self._update_pixmap_cache(square_size)
        self._invalidate_snapshot()
        self._needs_full_board_paint = True
        self.update()

    def resizeEvent(self, event):
        self._invalidate_snapshot()
        self._squares_pixmap = None
        self._squares_pixmap_key = None
        self._needs_full_board_paint = True
        if self.piece_pixmaps:
            self._is_resizing = True
            self._resize_settle_timer.start()
        super().resizeEvent(event)

    def update_animation_metrics(self, anim_speed=None, target_fps=None):
        """
        Pre-calculates frame-quantized animation durations and high-precision timer interval.
        Couples animation duration to integer monitor VSync refresh cycles with square-root distance scaling.
        """
        if anim_speed is None:
            tm = getattr(self.main_window, 'training_manager', None) if self.main_window else None
            if tm and hasattr(tm, 'get_setting'):
                anim_speed = tm.get_setting("anim_speed") or 200
            else:
                anim_speed = 200
                
        if target_fps is not None:
            self.target_fps = target_fps
        else:
            self.target_fps = self.get_screen_refresh_rate()
        frame_interval_ms = 1000.0 / float(self.target_fps)
        self.timer_interval = max(1, int(frame_interval_ms))
        self._last_configured_anim_speed = anim_speed

        # Precompute quantized durations for all possible (dx, dy) distances (0..7) on an 8x8 chess board
        self._duration_lut = {}
        for dx in range(8):
            for dy in range(8):
                dist = math.hypot(dx, dy)
                if dist <= 0:
                    dist = 1.0
                # Square-root distance scaling centered on 2-square pawn push (d = 2.0)
                # scale = 0.70 + 0.30 * sqrt(d / 2.0)
                scale_factor = 0.70 + 0.30 * math.sqrt(dist / 2.0)
                raw_dur = float(anim_speed) * scale_factor
                target_frames = max(1, int(round(raw_dur / frame_interval_ms)))
                self._duration_lut[(dx, dy)] = float(target_frames * frame_interval_ms)

        target_frames_base = max(1, int(round(float(anim_speed) / frame_interval_ms)))
        self.anim_duration = float(target_frames_base * frame_interval_ms)

    def get_metrics(self):
        """
        Calculates board dimensions and symmetrically centered coordinates.
        Guarantees equal padding and zero horizontal/vertical bias on all aspect ratios.
        """
        w = self.width()
        h = self.height()
        side = max(0, min(w, h) - self.padding * 2)
        square_size = side / 8.0
        x_offset = float((w - side) / 2.0)
        y_offset = float((h - side) / 2.0)
        return side, square_size, x_offset, y_offset

    def set_theme(self, theme_name):
        if isinstance(theme_name, str):
            theme_name = normalize_text_encoding(theme_name)
        if theme_name in THEMES:
            self.light_color, self.dark_color = THEMES[theme_name]
        elif theme_name in THEME_FALLBACKS:
            self.light_color, self.dark_color = THEMES[THEME_FALLBACKS[theme_name]]
        else:
            self.light_color, self.dark_color = THEMES["Braun (Klassisch)"]
        self._light_brush = QBrush(self.light_color)
        self._dark_brush = QBrush(self.dark_color)
        self._squares_pixmap = None
        self._squares_pixmap_key = None
        self._invalidate_snapshot()
        self._needs_full_board_paint = True
        self.update()

    def set_highlight_color(self, color_name_or_color):
        if isinstance(color_name_or_color, QColor):
            self.highlight_color = color_name_or_color
        else:
            if isinstance(color_name_or_color, str):
                color_name_or_color = normalize_text_encoding(color_name_or_color)
            if color_name_or_color in HIGHLIGHT_COLORS:
                self.highlight_color = HIGHLIGHT_COLORS[color_name_or_color]
            elif color_name_or_color in HIGHLIGHT_COLOR_FALLBACKS:
                self.highlight_color = HIGHLIGHT_COLORS[HIGHLIGHT_COLOR_FALLBACKS[color_name_or_color]]
            elif isinstance(color_name_or_color, str) and color_name_or_color.startswith("#"):
                self.highlight_color = QColor(color_name_or_color)
            else:
                self.highlight_color = HIGHLIGHT_COLORS["Gelb (Standard)"]
        self._highlight_brush = QBrush(self.highlight_color)
        self._invalidate_snapshot()
        self._needs_full_board_paint = True
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
        if getattr(self, '_is_resizing', False) and self.piece_pixmaps:
            return
        dpr = self.devicePixelRatioF()
        scaled_size = int(square_size * dpr)
        if scaled_size <= 0 or scaled_size == self._last_scaled_size:
            return
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
        self.clear_user_drawings()
        self._invalidate_snapshot()
        self._needs_full_board_paint = True
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

    def _get_draw_color_name(self, modifiers):
        """Maps keyboard modifiers to ChessBase standard arrow/highlight colors."""
        has_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        has_alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if (has_ctrl and has_alt) or (has_shift and has_alt):
            return "orange"
        if has_alt:
            return "red"
        if has_ctrl:
            return "yellow"
        if has_shift:
            return "blue"
        return "green"

    def clear_user_drawings(self, emit_signal=True):
        """Clears all user-drawn arrows and square highlights."""
        had_drawings = bool(self.user_arrows or self.user_highlights)
        self.user_arrows.clear()
        self.user_highlights.clear()
        self.is_drawing = False
        self.drawing_start_sq = None
        self.drawing_current_sq = None
        self.drawing_color = None
        self.drawing_highlight_color = None
        self._invalidate_snapshot()
        if had_drawings:
            self._needs_full_board_paint = True
        if had_drawings and emit_signal:
            self.drawings_changed.emit()

    def clear_user_arrows(self):
        """Clears all user-drawn arrows."""
        if self.user_arrows:
            self.user_arrows.clear()
            self._invalidate_snapshot()
            self.update()
            self.drawings_changed.emit()

    def clear_user_highlights(self):
        """Clears all user-drawn square highlights."""
        if self.user_highlights:
            self.user_highlights.clear()
            self._invalidate_snapshot()
            self.update()
            self.drawings_changed.emit()

    def add_user_arrow(self, start_sq, end_sq, color="green"):
        """Programmatically adds or updates an arrow between two squares."""
        col = USER_ARROW_COLORS.get(color, color) if isinstance(color, str) else color
        self.user_arrows[(start_sq, end_sq)] = col
        self._invalidate_snapshot()
        self.update()
        self.drawings_changed.emit()

    def remove_user_arrow(self, start_sq, end_sq):
        """Removes a user-drawn arrow."""
        if (start_sq, end_sq) in self.user_arrows:
            del self.user_arrows[(start_sq, end_sq)]
            self._invalidate_snapshot()
            self.update()
            self.drawings_changed.emit()

    def add_user_highlight(self, sq, color="green"):
        """Programmatically adds or updates a square highlight."""
        col = USER_HIGHLIGHT_COLORS.get(color, color) if isinstance(color, str) else color
        self.user_highlights[sq] = col
        self._invalidate_snapshot()
        self.update()
        self.drawings_changed.emit()

    def remove_user_highlight(self, sq):
        """Removes a user-drawn square highlight."""
        if sq in self.user_highlights:
            del self.user_highlights[sq]
            self._invalidate_snapshot()
            self.update()
            self.drawings_changed.emit()

    def load_user_drawings_from_comment(self, comment_text: str):
        """
        Retroactively extracts [%csl ...] and [%cal ...] tags from a comment string
        (or multilingual JSON string) and displays the arrows and highlights on the board.
        """
        from opening_fenix.core.utils import parse_chessbase_annotations, parse_comment
        resolved = parse_comment(comment_text) if comment_text else ""
        parsed = parse_chessbase_annotations(resolved or comment_text)
        self.user_arrows.clear()
        self.user_highlights.clear()
        for sq, col_name in parsed["highlights"]:
            self.user_highlights[sq] = USER_HIGHLIGHT_COLORS.get(col_name, USER_HIGHLIGHT_COLORS["green"])
        for from_sq, to_sq, col_name in parsed["arrows"]:
            self.user_arrows[(from_sq, to_sq)] = USER_ARROW_COLORS.get(col_name, USER_ARROW_COLORS["green"])
        self._invalidate_snapshot()
        self._needs_full_board_paint = True
        self.update()

    def get_chessbase_annotation_tags(self) -> str:
        """Serializes the current board arrows and highlights into standard [%csl ...] and [%cal ...] tags."""
        from opening_fenix.core.utils import serialize_chessbase_annotations
        return serialize_chessbase_annotations(self.user_arrows, self.user_highlights)

    def mousePressEvent(self, event):
        if self.is_animating:
            self.skip_all_animations_requested.emit()
            if self.is_animating: # Fallback if no skip handler is connected
                if self.animating_piece_data:
                    self.move_anim.stop()
                    self.precise_anim_timer.stop()
                    move = self.animating_piece_data['move']
                    self.board.push(move)
                    self.last_move = move
                    self.animating_piece_data = None
                    self._invalidate_snapshot()
                    self.is_animating = False
                    if getattr(self, '_gc_disabled_for_anim', False):
                        gc.enable()
                        self._gc_disabled_for_anim = False
                    self.piece_slide_finished.emit()
                    self.update()
            # Allow the click to proceed to pick up a piece

        # Right-click: Start drawing arrow / highlight (ChessBase style)
        if event.button() == Qt.MouseButton.RightButton:
            square = self.get_square_from_pos(event.position())
            if square is not None:
                self.is_drawing = True
                self.drawing_start_sq = square
                self.drawing_current_sq = square
                mods = event.modifiers() if hasattr(event, 'modifiers') else Qt.KeyboardModifier.NoModifier
                color_name = self._get_draw_color_name(mods)
                self.drawing_color = USER_ARROW_COLORS[color_name]
                self.drawing_highlight_color = USER_HIGHLIGHT_COLORS[color_name]
                self.update()
            return

        # Left-click: Make move or clear existing drawings
        if event.button() == Qt.MouseButton.LeftButton:
            square = self.get_square_from_pos(event.position())
            # In ChessBase/Lichess: Left-clicking on an empty square or outside clears user drawings
            if self.user_arrows or self.user_highlights:
                if square is None or self.board.piece_at(square) is None:
                    self.clear_user_drawings()
                    self.update()
            if square is not None:
                piece = self.board.piece_at(square)
                if piece and piece.color == self.board.turn:
                    self.dragging_piece = piece
                    self.drag_start_square = square
                    self.mouse_pos = event.position()
                    self._last_drag_dirty_rect = self._get_drag_dirty_rect()
                    self.update()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            square = self.get_square_from_pos(event.position())
            if square != self.drawing_current_sq:
                self.drawing_current_sq = square
                self.update()
            return

        if self.dragging_piece:
            self.mouse_pos = event.position()
            cur_rect = self._get_drag_dirty_rect()
            upd_rect = cur_rect.united(self._last_drag_dirty_rect) if self._last_drag_dirty_rect else cur_rect
            self._last_drag_dirty_rect = cur_rect
            self.update(upd_rect)

    def mouseReleaseEvent(self, event):
        # Right-click release: Finalize arrow or square highlight
        if event.button() == Qt.MouseButton.RightButton and self.is_drawing:
            end_square = self.get_square_from_pos(event.position())
            start_square = self.drawing_start_sq
            changed = False
            if start_square is not None and end_square is not None:
                changed = True
                if start_square == end_square:
                    # Toggle or update square highlight
                    h_col = self.drawing_highlight_color
                    if start_square in self.user_highlights and self.user_highlights[start_square] == h_col:
                        del self.user_highlights[start_square]
                    else:
                        self.user_highlights[start_square] = h_col
                else:
                    # Toggle or update arrow
                    a_col = self.drawing_color
                    arrow_key = (start_square, end_square)
                    if arrow_key in self.user_arrows and self.user_arrows[arrow_key] == a_col:
                        del self.user_arrows[arrow_key]
                    else:
                        self.user_arrows[arrow_key] = a_col
            self.is_drawing = False
            self.drawing_start_sq = None
            self.drawing_current_sq = None
            self.drawing_color = None
            self.drawing_highlight_color = None
            if changed:
                self._invalidate_snapshot()
            self.update()
            if changed:
                self.drawings_changed.emit()
            return

        if self.dragging_piece:
            end_square = self.get_square_from_pos(event.position())
            drag_start = self.drag_start_square
            dragging = self.dragging_piece
            
            # Clear dragging state immediately so any repaint inside the signal handler knows the drag is done
            self.dragging_piece = None
            self.drag_start_square = None
            self._last_drag_dirty_rect = None
            
            if end_square is not None and drag_start is not None:
                move = None
                if dragging.piece_type == chess.KING:
                    target = self.board.piece_at(end_square)
                    if target and target.color == dragging.color and target.piece_type == chess.ROOK:
                        for cand in self.board.legal_moves:
                            if self.board.is_castling(cand):
                                if chess.square_file(end_square) > chess.square_file(drag_start):
                                    if self.board.is_kingside_castling(cand): move = cand; break
                                elif chess.square_file(end_square) < chess.square_file(drag_start):
                                    if self.board.is_queenside_castling(cand): move = cand; break
                if move is None:
                    is_promo = (dragging.piece_type == chess.PAWN and (chess.square_rank(end_square) in [0, 7]))
                    promotion = chess.QUEEN if is_promo else None
                    move = chess.Move(drag_start, end_square, promotion=promotion)
                if move in self.board.legal_moves: 
                    self.clear_user_drawings()
                    self.move_executed.emit(move)
            self.update()

    def _draw_arrow(self, painter, start, end, color, square_size):
        f1, r1 = chess.square_file(start), chess.square_rank(start)
        f2, r2 = chess.square_file(end), chess.square_rank(end)
        if self.flipped:
            r1, c1 = r1, 7 - f1
            r2, c2 = r2, 7 - f2
        else:
            r1, c1 = 7 - r1, f1
            r2, c2 = 7 - r2, f2

        x1, y1 = (c1 + 0.5) * square_size, (r1 + 0.5) * square_size
        x2, y2 = (c2 + 0.5) * square_size, (r2 + 0.5) * square_size

        dx, dy = x2 - x1, y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length <= 0:
            return

        angle = math.atan2(dy, dx)
        ux, uy = math.cos(angle), math.sin(angle)
        px, py = -math.sin(angle), math.cos(angle)

        # Offsets & proportions for a sleek, unified arrow geometry
        start_offset = min(square_size * 0.18, length * 0.2)
        tip_offset = min(square_size * 0.1, length * 0.1)

        sx = x1 + ux * start_offset
        sy = y1 + uy * start_offset

        tx = x2 - ux * tip_offset
        ty = y2 - uy * tip_offset

        eff_len = math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2)

        head_len = min(square_size * 0.38, eff_len * 0.45)
        head_width = square_size * 0.36
        shaft_start_width = square_size * 0.11
        shaft_end_width = square_size * 0.15

        hb_x = tx - ux * head_len
        hb_y = ty - uy * head_len

        # Single 7-point polygon to prevent double alpha-blending and overlapping lines
        p1 = QPointF(sx + px * (shaft_start_width / 2), sy + py * (shaft_start_width / 2))
        p2 = QPointF(hb_x + px * (shaft_end_width / 2), hb_y + py * (shaft_end_width / 2))
        p3 = QPointF(hb_x + px * (head_width / 2), hb_y + py * (head_width / 2))
        p4 = QPointF(tx, ty)
        p5 = QPointF(hb_x - px * (head_width / 2), hb_y - py * (head_width / 2))
        p6 = QPointF(hb_x - px * (shaft_end_width / 2), hb_y - py * (shaft_end_width / 2))
        p7 = QPointF(sx - px * (shaft_start_width / 2), sy - py * (shaft_start_width / 2))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(color)

        # Subtle crisp outline matching the arrow color with slightly higher opacity
        outline_alpha = min(255, color.alpha() + 50)
        outline_color = QColor(color.red(), color.green(), color.blue(), outline_alpha)
        painter.setPen(QPen(outline_color, scale(1.2), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))

        painter.drawPolygon(QPolygonF([p1, p2, p3, p4, p5, p6, p7]))
        painter.restore()

    # ──────────────────────────────────────────────────────────────────────
    #   PAINT SYSTEM — Split into static board rendering + animation overlay
    # ──────────────────────────────────────────────────────────────────────

    def _paint_squares(self, painter, square_size):
        """Draws the 8x8 squares and last-move highlight."""
        painter.setPen(Qt.PenStyle.NoPen)
        for row in range(8):
            for col in range(8):
                brush = self._light_brush if (row + col) % 2 == 0 else self._dark_brush
                painter.setBrush(brush)
                painter.drawRect(QRectF(col * square_size, row * square_size, square_size, square_size))

        if self.last_move:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._highlight_brush)
            for sq in [self.last_move.from_square, self.last_move.to_square]:
                f, r = chess.square_file(sq), chess.square_rank(sq)
                rd, cd = (r if self.flipped else 7 - r), (7 - f if self.flipped else f)
                painter.drawRect(QRectF(cd * square_size, rd * square_size, square_size, square_size))

    def _paint_coordinates(self, painter, square_size):
        """Draws coordinates (rank numbers and file letters) with native font antialiasing."""
        painter.setPen(self._coord_color)
        pt_size = max(9, int(square_size / 6.0))
        cache_key = (pt_size, round(square_size, 2), self.flipped, self.padding)
        if getattr(self, '_coord_font_cache', None) is None or self._coord_font_cache[0] != cache_key:
            font = QFont(painter.font())
            font.setBold(True)
            font.setPointSize(pt_size)
            painter.setFont(font)
            fm = painter.fontMetrics()
            baseline_y = 8 * square_size + (self.padding + fm.ascent() - fm.descent()) / 2.0
            ranks = []
            files = []
            for i in range(8):
                rank_str = str(i + 1 if self.flipped else 8 - i)
                rank_rect = QRectF(-self.padding, i * square_size, self.padding - scale(5), square_size)
                ranks.append((rank_rect, rank_str))
                file_char = chr(ord('h') - i if self.flipped else ord('a') + i)
                x_center = (i + 0.5) * square_size - fm.horizontalAdvance(file_char) / 2.0
                files.append((QPointF(x_center, baseline_y), file_char))
            self._coord_font_cache = (cache_key, font, ranks, files)
        else:
            _, font, ranks, files = self._coord_font_cache
            painter.setFont(font)

        for rank_rect, rank_str in ranks:
            painter.drawText(rank_rect, Qt.AlignmentFlag.AlignCenter, rank_str)
        for file_pt, file_char in files:
            painter.drawText(file_pt, file_char)

    def _paint_board_base(self, painter, square_size):
        """Draws squares, last-move highlight, and coordinates."""
        self._paint_squares(painter, square_size)
        self._paint_coordinates(painter, square_size)

    def _draw_circle(self, painter, square, color, square_size):
        """Draws a clean, crisp hollow circle around the square/piece (ChessBase style)."""
        f, r = chess.square_file(square), chess.square_rank(square)
        rd, cd = (r if self.flipped else 7 - r), (7 - f if self.flipped else f)
        center_x = (cd + 0.5) * square_size
        center_y = (rd + 0.5) * square_size
        radius = square_size * 0.41
        pen_width = max(2.5, square_size * 0.055)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(center_x, center_y), radius, radius)
        painter.restore()

    def _paint_circles(self, painter, square_size, include_live_preview=True):
        """Draws circle highlights on marked squares."""
        for sq, color in self.user_highlights.items():
            self._draw_circle(painter, sq, color, square_size)

        # Live preview circle while holding right-click without drag
        if (include_live_preview and self.is_drawing and self.drawing_start_sq is not None 
                and self.drawing_current_sq == self.drawing_start_sq 
                and self.drawing_highlight_color is not None):
            self._draw_circle(painter, self.drawing_start_sq, self.drawing_highlight_color, square_size)

    def _paint_pieces(self, painter, square_size, skip_square=None, skip_squares=None):
        """Draws all pieces, optionally skipping one or more squares (e.g. animating piece origins)."""
        for sq, piece in self.board.piece_map().items():
            if skip_square is not None and sq == skip_square:
                continue
            if skip_squares and sq in skip_squares:
                continue
            if self.drag_start_square == sq and self.dragging_piece:
                continue
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            col = 7 - f if self.flipped else f
            row = r if self.flipped else 7 - r
            self.draw_piece(painter, piece, col, row, square_size)

    def _ensure_squares_pixmap(self, w_px, h_px, dpr, rem_dx_phys, rem_dy_phys, x_offset, y_offset, square_size):
        """Caches the static 8x8 checkerboard squares layer so snapshots avoid 64 rect fills per move."""
        key = (
            w_px, h_px, round(dpr, 4),
            round(rem_dx_phys, 4), round(rem_dy_phys, 4),
            round(x_offset, 4), round(y_offset, 4), round(square_size, 4),
            self.light_color.rgba(), self.dark_color.rgba(),
        )
        if self._squares_pixmap is not None and self._squares_pixmap_key == key:
            return self._squares_pixmap

        sq_pm = QPixmap(w_px, h_px)
        sq_pm.setDevicePixelRatio(dpr)
        sq_pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(sq_pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(rem_dx_phys / dpr + x_offset, rem_dy_phys / dpr + y_offset)
        p.setPen(Qt.PenStyle.NoPen)
        for row in range(8):
            for col in range(8):
                p.setBrush(self._light_brush if (row + col) % 2 == 0 else self._dark_brush)
                p.drawRect(QRectF(col * square_size, row * square_size, square_size, square_size))
        p.end()

        self._squares_pixmap = sq_pm
        self._squares_pixmap_key = key
        return sq_pm

    def _build_board_snapshot(self, rem_dx_phys=None, rem_dy_phys=None):
        """
        Renders the static board elements (squares, last-move highlight,
        stationary pieces, user circles, and arrows) to a high-resolution off-screen QPixmap.
        Eliminates thousands of redundant draw calls per second during piece slide animations.
        Aligns sub-pixel deviceTransform phase (rem_dx_phys, rem_dy_phys) with the parent window
        backing store to guarantee 0-pixel shift/tremble across all widget positions and High-DPI factors.
        """
        if self.width() <= 0 or self.height() <= 0:
            return None
        dpr = self.devicePixelRatioF()
        if rem_dx_phys is None or rem_dy_phys is None:
            win = self.window()
            if win is not None and win is not self:
                pos = self.mapTo(win, QPoint(0, 0))
                dev_dx = pos.x() * dpr
                dev_dy = pos.y() * dpr
                rem_dx_phys = dev_dx - round(dev_dx)
                rem_dy_phys = dev_dy - round(dev_dy)
            else:
                rem_dx_phys = 0.0
                rem_dy_phys = 0.0

        w_px = max(1, round(self.width() * dpr)) + 2
        h_px = max(1, round(self.height() * dpr)) + 2
        buf = self._snapshot_buffer
        if buf is None or buf.width() != w_px or buf.height() != h_px or abs(buf.devicePixelRatio() - dpr) > 1e-4:
            buf = QPixmap(w_px, h_px)
            buf.setDevicePixelRatio(dpr)
            self._snapshot_buffer = buf
        snapshot = buf
        snapshot.fill(Qt.GlobalColor.transparent)

        side, square_size, x_offset, y_offset = self.get_metrics()
        self._update_pixmap_cache(square_size)
        squares_pm = self._ensure_squares_pixmap(
            w_px, h_px, dpr, rem_dx_phys, rem_dy_phys, x_offset, y_offset, square_size
        )

        painter = QPainter(snapshot)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QPointF(0.0, 0.0), squares_pm)

        skip_square = None
        skip_squares = None
        if self.animating_piece_data:
            skip_square = self.animating_piece_data['from_square']
            if 'rook_from_square' in self.animating_piece_data:
                skip_squares = {skip_square, self.animating_piece_data['rook_from_square']}
        elif self.dragging_piece is not None:
            skip_square = self.drag_start_square

        painter.translate(rem_dx_phys / dpr + x_offset, rem_dy_phys / dpr + y_offset)
        if self.last_move:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._highlight_brush)
            for sq in [self.last_move.from_square, self.last_move.to_square]:
                f, r = chess.square_file(sq), chess.square_rank(sq)
                rd, cd = (r if self.flipped else 7 - r), (7 - f if self.flipped else f)
                painter.drawRect(QRectF(cd * square_size, rd * square_size, square_size, square_size))
        self._paint_pieces(painter, square_size, skip_square=skip_square, skip_squares=skip_squares)
        self._paint_circles(painter, square_size, include_live_preview=False)
        self._paint_arrows(painter, square_size, include_live_preview=False)
        painter.end()

        self._snapshot_flipped = self.flipped
        self._snapshot_size = self.size()
        self._snapshot_phase = (round(rem_dx_phys, 4), round(rem_dy_phys, 4))
        self._snapshot_skip_sq = skip_square
        return snapshot

    def _paint_arrows(self, painter, square_size, include_live_preview=True):
        """Draws all arrows (hint, solution, explorer, user)."""
        if self.hint_arrow:
            if isinstance(self.hint_arrow, chess.Move):
                self._draw_arrow(painter, self.hint_arrow.from_square, self.hint_arrow.to_square, QColor(20, 60, 150, 120), square_size)
            elif isinstance(self.hint_arrow, (tuple, list)) and len(self.hint_arrow) >= 2:
                self._draw_arrow(painter, self.hint_arrow[0], self.hint_arrow[1], QColor(20, 60, 150, 120), square_size)
        if self.solution_arrow:
            if isinstance(self.solution_arrow, chess.Move):
                self._draw_arrow(painter, self.solution_arrow.from_square, self.solution_arrow.to_square, QColor(20, 60, 150, 120), square_size)
            elif isinstance(self.solution_arrow, (tuple, list)) and len(self.solution_arrow) >= 2:
                self._draw_arrow(painter, self.solution_arrow[0], self.solution_arrow[1], QColor(20, 60, 150, 120), square_size)
        for item in self.explorer_arrows:
            if isinstance(item, (tuple, list)):
                if len(item) == 2:
                    move_or_from, color_or_to = item
                    if isinstance(move_or_from, chess.Move):
                        c = color_or_to if isinstance(color_or_to, QColor) else QColor(color_or_to)
                        self._draw_arrow(painter, move_or_from.from_square, move_or_from.to_square, c, square_size)
                    else:
                        self._draw_arrow(painter, move_or_from, color_or_to, QColor(59, 130, 246, 180), square_size)
                elif len(item) >= 3:
                    f_sq, t_sq = item[0], item[1]
                    c = item[2] if isinstance(item[2], QColor) else QColor(59, 130, 246, 180)
                    self._draw_arrow(painter, f_sq, t_sq, c, square_size)

        # 4. User-drawn arrows (ChessBase style)
        for (from_sq, to_sq), color in self.user_arrows.items():
            self._draw_arrow(painter, from_sq, to_sq, color, square_size)

        # 5. Live preview arrow while dragging
        if (include_live_preview and self.is_drawing and self.drawing_start_sq is not None 
                and self.drawing_current_sq is not None 
                and self.drawing_start_sq != self.drawing_current_sq 
                and self.drawing_color is not None):
            self._draw_arrow(painter, self.drawing_start_sq, self.drawing_current_sq, self.drawing_color, square_size)

    def _paint_live_drawing_preview(self, painter, square_size):
        """Draws only the active right-click preview circle or arrow over a cached snapshot."""
        if not self.is_drawing or self.drawing_start_sq is None or self.drawing_current_sq is None:
            return
        if self.drawing_current_sq == self.drawing_start_sq:
            if self.drawing_highlight_color is not None:
                self._draw_circle(painter, self.drawing_start_sq, self.drawing_highlight_color, square_size)
        elif self.drawing_color is not None:
            self._draw_arrow(painter, self.drawing_start_sq, self.drawing_current_sq, self.drawing_color, square_size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        side, square_size, x_offset, y_offset = self.get_metrics()
        self._update_pixmap_cache(square_size)
        
        is_drag = self.dragging_piece is not None
        is_anim = bool(self.is_animating and self.animating_piece_data)
        is_draw = bool(self.is_drawing)

        if is_anim or is_drag or is_draw:
            # High-performance 2-draw-call pipeline for animations, piece dragging, and arrow drawing:
            # 1. Blit pre-rendered static board snapshot (squares + stationary pieces + annotations)
            dt = painter.deviceTransform()
            dpr = dt.m11() if dt.m11() > 0 else self.devicePixelRatioF()
            dev_dx, dev_dy = dt.dx(), dt.dy()
            rem_dx_phys = dev_dx - round(dev_dx)
            rem_dy_phys = dev_dy - round(dev_dy)
            phase_key = (round(rem_dx_phys, 4), round(rem_dy_phys, 4))
            expected_skip_sq = (
                self.animating_piece_data['from_square'] if is_anim else (self.drag_start_square if is_drag else None)
            )

            if (self._board_snapshot is None or
                getattr(self, '_snapshot_flipped', None) != self.flipped or
                getattr(self, '_snapshot_size', None) != self.size() or
                getattr(self, '_snapshot_phase', None) != phase_key or
                getattr(self, '_snapshot_skip_sq', None) != expected_skip_sq):
                self._board_snapshot = self._build_board_snapshot(rem_dx_phys, rem_dy_phys)

            if self._board_snapshot is not None:
                painter.drawPixmap(QPointF(-rem_dx_phys / dpr, -rem_dy_phys / dpr), self._board_snapshot)
                clip_rect = event.rect() if event is not None else QRect()
                inner_board_rect = QRect(
                    int(math.ceil(x_offset)) + 1,
                    int(math.ceil(y_offset)) + 1,
                    max(0, int(math.floor(side)) - 2),
                    max(0, int(math.floor(side)) - 2),
                )
                painter.translate(x_offset, y_offset)
                if clip_rect.isEmpty() or not inner_board_rect.contains(clip_rect):
                    self._paint_coordinates(painter, square_size)
                if is_draw:
                    self._paint_live_drawing_preview(painter, square_size)
            else:
                skip_sq_fallback = expected_skip_sq
                skip_squares = {skip_sq_fallback} if skip_sq_fallback is not None else None
                if is_anim and 'rook_from_square' in self.animating_piece_data and skip_squares is not None:
                    skip_squares.add(self.animating_piece_data['rook_from_square'])
                painter.translate(x_offset, y_offset)
                self._paint_board_base(painter, square_size)
                self._paint_pieces(painter, square_size, skip_square=skip_sq_fallback, skip_squares=skip_squares)
                self._paint_circles(painter, square_size)
                self._paint_arrows(painter, square_size)

            # 2. Draw moving piece(s) at interpolated position
            if is_anim:
                self._anim_frame_times.append(time.perf_counter())
                d = self.animating_piece_data
                p = d['progress']
                cur_col = d['start_col'] + (d['end_col'] - d['start_col']) * p
                cur_row = d['start_row'] + (d['end_row'] - d['start_row']) * p
                lift = math.sin(p * math.pi) if self.enable_piece_lift else 0.0
                scale_factor = 1.0 + (0.15 * lift)
                self.draw_piece(painter, d['piece'], cur_col, cur_row, square_size, scale_factor=scale_factor)

                if 'rook_piece' in d:
                    rp = d.get('rook_progress', 0.0)
                    r_col = d['rook_start_col'] + (d['rook_end_col'] - d['rook_start_col']) * rp
                    r_row = d['rook_start_row'] + (d['rook_end_row'] - d['rook_start_row']) * rp
                    r_lift = math.sin(rp * math.pi) if self.enable_piece_lift else 0.0
                    r_scale = 1.0 + (0.15 * r_lift)
                    self.draw_piece(painter, d['rook_piece'], r_col, r_row, square_size, scale_factor=r_scale)

        else:
            # Fast idle rendering: reuse cached 8x8 checkerboard pixmap instead of 64 rect fills
            dt = painter.deviceTransform()
            dpr = dt.m11() if dt.m11() > 0 else self.devicePixelRatioF()
            dev_dx, dev_dy = dt.dx(), dt.dy()
            rem_dx_phys = dev_dx - round(dev_dx)
            rem_dy_phys = dev_dy - round(dev_dy)
            w_px = max(1, round(self.width() * dpr)) + 2
            h_px = max(1, round(self.height() * dpr)) + 2
            squares_pm = self._ensure_squares_pixmap(
                w_px, h_px, dpr, rem_dx_phys, rem_dy_phys, x_offset, y_offset, square_size
            )
            painter.drawPixmap(QPointF(-rem_dx_phys / dpr, -rem_dy_phys / dpr), squares_pm)
            painter.translate(x_offset, y_offset)
            if self.last_move:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._highlight_brush)
                for sq in [self.last_move.from_square, self.last_move.to_square]:
                    f, r = chess.square_file(sq), chess.square_rank(sq)
                    rd, cd = (r if self.flipped else 7 - r), (7 - f if self.flipped else f)
                    painter.drawRect(QRectF(cd * square_size, rd * square_size, square_size, square_size))
            self._paint_coordinates(painter, square_size)
            self._paint_pieces(painter, square_size, skip_square=None)
            self._paint_circles(painter, square_size)
            self._paint_arrows(painter, square_size)

        if is_drag:
            # Draw dragged piece centered exactly on mouse cursor with sub-pixel float precision
            mx = (self.mouse_pos.x() - x_offset) - square_size / 2.0
            my = (self.mouse_pos.y() - y_offset) - square_size / 2.0
            key = PIECE_KEY_MAP.get((self.dragging_piece.piece_type, self.dragging_piece.color))
            if key and key in self.piece_pixmaps: 
                painter.drawPixmap(QPointF(mx, my), self.piece_pixmaps[key])

        if self.debug_anim:
            painter.resetTransform()
            self._paint_debug_overlay(painter)

        if event is None or (
            event.rect().width() >= max(1, self.width() - 2)
            and event.rect().height() >= max(1, self.height() - 2)
        ):
            self._needs_full_board_paint = False
            self._last_painted_flipped = self.flipped

    def get_screen_refresh_rate(self):
        """
        Detects the exact hardware refresh rate (Hz) of the specific screen 
        where the chessboard widget / window is currently displayed.
        Falls back to primary screen or 60Hz if screen information is unavailable.
        """
        try:
            target_screen = None
            # 1. Check the widget's direct screen
            if hasattr(self, 'screen') and self.screen():
                target_screen = self.screen()
            
            # 2. Check window screen / window handle screen
            if not target_screen:
                win = self.window()
                if win:
                    if hasattr(win, 'screen') and win.screen():
                        target_screen = win.screen()
                    elif hasattr(win, 'windowHandle') and win.windowHandle() and win.windowHandle().screen():
                        target_screen = win.windowHandle().screen()

            # 3. Fallback to primary application screen
            if not target_screen:
                from PyQt6.QtWidgets import QApplication
                target_screen = QApplication.primaryScreen()

            if target_screen and target_screen.refreshRate() > 0:
                rate = float(target_screen.refreshRate())
                if sys.platform == "win32" and rate <= 60.5:
                    drr_rate = self._get_win32_virtual_refresh_rate()
                    if drr_rate and drr_rate > rate:
                        rate = float(drr_rate)
                return min(240, max(30, int(round(rate))))
        except Exception:
            pass
        return 60

    @staticmethod
    def _get_win32_virtual_refresh_rate():
        """
        Queries Windows 11 QueryDisplayConfig with QDC_VIRTUAL_REFRESH_RATE_AWARE (0x40)
        so displays with 'Dynamic Refresh Rate' (60Hz or 120Hz) report their true 120Hz+ target rate
        instead of the 60Hz base divider rate returned to legacy EnumDisplaySettingsW / QScreen.
        """
        if sys.platform != "win32":
            return None
        try:
            from ctypes import wintypes

            class _LUID(ctypes.Structure):
                _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

            class _RATIONAL(ctypes.Structure):
                _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]

            class _2DREGION(ctypes.Structure):
                _fields_ = [("cx", wintypes.UINT), ("cy", wintypes.UINT)]

            class _VIDEO_SIGNAL_INFO(ctypes.Structure):
                _fields_ = [
                    ("pixelRate", ctypes.c_uint64),
                    ("hSyncFreq", _RATIONAL),
                    ("vSyncFreq", _RATIONAL),
                    ("activeSize", _2DREGION),
                    ("totalSize", _2DREGION),
                    ("videoStandard", wintypes.UINT),
                    ("scanLineOrdering", wintypes.UINT),
                ]

            class _PATH_INFO(ctypes.Structure):
                _fields_ = [("raw", ctypes.c_byte * 72)]

            class _MODE_INFO(ctypes.Structure):
                _fields_ = [
                    ("infoType", wintypes.UINT),
                    ("id", wintypes.UINT),
                    ("adapterId", _LUID),
                    ("targetVideoSignalInfo", _VIDEO_SIGNAL_INFO),
                ]

            flags = 0x00000002 | 0x00000040  # QDC_ONLY_ACTIVE_PATHS | QDC_VIRTUAL_REFRESH_RATE_AWARE
            num_paths = wintypes.UINT(0)
            num_modes = wintypes.UINT(0)
            if ctypes.windll.user32.GetDisplayConfigBufferSizes(flags, ctypes.byref(num_paths), ctypes.byref(num_modes)) != 0:
                return None
            paths = (_PATH_INFO * num_paths.value)()
            modes = (_MODE_INFO * num_modes.value)()
            if ctypes.windll.user32.QueryDisplayConfig(flags, ctypes.byref(num_paths), paths, ctypes.byref(num_modes), modes, None) != 0:
                return None
            max_hz = 0.0
            for i in range(num_modes.value):
                if modes[i].infoType == 2:  # DISPLAYCONFIG_MODE_INFO_TYPE_TARGET
                    vs = modes[i].targetVideoSignalInfo.vSyncFreq
                    if vs.Denominator > 0:
                        hz = float(vs.Numerator) / float(vs.Denominator)
                        if 30.0 <= hz <= 360.0 and hz > max_hz:
                            max_hz = hz
            return int(round(max_hz)) if max_hz > 0 else None
        except Exception:
            return None

    def _paint_debug_overlay(self, painter):
        """Draws a sleek debug stats overlay showing FPS, frame count, and timing info."""
        painter.save()
        painter.resetTransform()
        
        text = "ANIM DEBUG | Idle"
        if self.is_animating:
            frames = len(self._anim_frame_times)
            elapsed = (time.perf_counter() - self._anim_start_time) * 1000.0
            fps = (frames / (elapsed / 1000.0)) if elapsed > 0 else 0
            lift_str = "Arcade (+15%)" if self.enable_piece_lift else "Lichess Flat (1.0x)"
            text = f"ANIMATING... | {fps:.1f} FPS ({self.target_fps}Hz Display) | {frames} Frames | {elapsed:.0f} ms | Mode: {lift_str}"
        elif self._last_anim_stats:
            s = self._last_anim_stats
            lift_str = "Arcade (+15%)" if self.enable_piece_lift else "Lichess Flat (1.0x)"
            text = f"LAST MOVE: {s['fps']:.1f} FPS ({self.target_fps}Hz Display) | {s['frames']} Frames in {s['ms']:.0f} ms | Mode: {lift_str}"

        font = painter.font()
        font.setPixelSize(scale(12))
        font.setBold(True)
        painter.setFont(font)
        
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text) + scale(16)
        h = fm.height() + scale(8)
        rect = QRectF(self.width() - w - scale(8), scale(8), w, h)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(rect, 4, 4)
        
        painter.setPen(QColor("#00ffcc") if self.is_animating else QColor("#e0e0e0"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _col_row_widget_rect(self, col: float, row: float, square_size: float, x_offset: float, y_offset: float, pad: int) -> QRect:
        """Converts board (col, row) coordinates into a widget-space dirty rectangle."""
        x = int(math.floor(x_offset + col * square_size)) - pad
        y = int(math.floor(y_offset + row * square_size)) - pad
        sz = int(math.ceil(square_size)) + pad * 2
        return QRect(x, y, sz, sz)

    def _get_anim_dirty_rect(self) -> QRect:
        """Computes the tight widget-space bounding rectangle of currently animating piece(s)."""
        if not self.animating_piece_data:
            return QRect()
        _, square_size, x_offset, y_offset = self.get_metrics()
        d = self.animating_piece_data
        p = d['progress']
        cur_col = d['start_col'] + (d['end_col'] - d['start_col']) * p
        cur_row = d['start_row'] + (d['end_row'] - d['start_row']) * p
        pad = max(6, int(math.ceil(square_size * (0.12 if self.enable_piece_lift else 0.04))))
        rect = self._col_row_widget_rect(cur_col, cur_row, square_size, x_offset, y_offset, pad)
        if 'rook_piece' in d:
            rp = d.get('rook_progress', 0.0)
            r_col = d['rook_start_col'] + (d['rook_end_col'] - d['rook_start_col']) * rp
            r_row = d['rook_start_row'] + (d['rook_end_row'] - d['rook_start_row']) * rp
            rect = rect.united(self._col_row_widget_rect(r_col, r_row, square_size, x_offset, y_offset, pad))
        return rect.intersected(self.rect())

    def _get_drag_dirty_rect(self) -> QRect:
        """Computes the tight widget-space bounding rectangle of the dragged piece."""
        _, square_size, _, _ = self.get_metrics()
        pad = 6
        x = int(math.floor(self.mouse_pos.x() - square_size / 2.0)) - pad
        y = int(math.floor(self.mouse_pos.y() - square_size / 2.0)) - pad
        sz = int(math.ceil(square_size)) + pad * 2
        return QRect(x, y, sz, sz).intersected(self.rect())

    def _square_widget_rect(self, sq: int, pad: int = 6) -> QRect:
        """Computes the widget-space bounding rectangle of a single board square."""
        _, square_size, x_offset, y_offset = self.get_metrics()
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        col = 7 - f if self.flipped else f
        row = r if self.flipped else 7 - r
        return self._col_row_widget_rect(col, row, square_size, x_offset, y_offset, pad).intersected(self.rect())

    def start_piece_slide(self, piece, from_square, to_square, move, duration_override=None):
        slide_call_time = time.perf_counter()
        prev_last_move = self.last_move
        is_castling = bool(move and self.board.is_castling(move))
        king_to_sq = to_square
        rook_data = None

        if is_castling:
            rank = chess.square_rank(from_square)
            is_ks = self.board.is_kingside_castling(move)
            king_to_sq = chess.square(6 if is_ks else 2, rank)
            rook_to_sq = chess.square(5 if is_ks else 3, rank)
            target_p = self.board.piece_at(to_square)
            if target_p and target_p.piece_type == chess.ROOK and target_p.color == piece.color:
                rook_from_sq = to_square
            else:
                rook_from_sq = chess.square(7 if is_ks else 0, rank)
            rook_piece = self.board.piece_at(rook_from_sq) or chess.Piece(chess.ROOK, piece.color)
            rff, rfr = chess.square_file(rook_from_sq), chess.square_rank(rook_from_sq)
            rtf, rtr = chess.square_file(rook_to_sq), chess.square_rank(rook_to_sq)
            if self.flipped:
                rsc, rsr, rec, rer = 7 - rff, rfr, 7 - rtf, rtr
            else:
                rsc, rsr, rec, rer = rff, 7 - rfr, rtf, 7 - rtr
            rook_data = {
                'rook_piece': rook_piece,
                'rook_from_square': rook_from_sq,
                'rook_to_square': rook_to_sq,
                'rook_start_col': rsc,
                'rook_start_row': rsr,
                'rook_end_col': rec,
                'rook_end_row': rer,
                'rook_progress': 0.0,
            }

        ff, fr = chess.square_file(from_square), chess.square_rank(from_square)
        tf, tr = chess.square_file(king_to_sq), chess.square_rank(king_to_sq)
        if self.flipped: sc, sr, ec, er = 7 - ff, fr, 7 - tf, tr
        else: sc, sr, ec, er = ff, 7 - fr, tf, 7 - tr
        
        if not hasattr(self, 'anim_duration') or not hasattr(self, 'timer_interval') or not hasattr(self, '_duration_lut'):
            self.update_animation_metrics()

        # O(1) instant precomputed distance duration lookup
        dx = abs(sc - ec)
        dy = abs(sr - er)
        self.anim_duration = duration_override if duration_override is not None else self._duration_lut.get((dx, dy), self.anim_duration)
            
        self.animating_piece_data = {'piece': piece, 'from_square': from_square, 'to_square': king_to_sq, 'start_col': sc, 'start_row': sr, 'end_col': ec, 'end_row': er, 'progress': 0.0, 'move': move}
        if rook_data:
            self.animating_piece_data.update(rook_data)
        self.last_move = move
        self.is_animating = True

        # Suspend Python cyclic GC and acquire 1ms Win32 timer strictly during active piece slide
        if not getattr(self, '_gc_disabled_for_anim', False):
            gc.disable()
            self._gc_disabled_for_anim = True
        if not getattr(self, '_winmm_timer_active', False):
            _set_winmm_timer_period(True)
            self._winmm_timer_active = True

        self._invalidate_snapshot()
        self._board_snapshot = self._build_board_snapshot()
        self._last_anim_dirty_rect = self._get_anim_dirty_rect()

        # Reset Debug Timing
        self._anim_start_time = time.perf_counter()
        self._anim_setup_ms = (self._anim_start_time - slide_call_time) * 1000.0
        last_end = getattr(self, '_last_slide_end_time', 0.0)
        if last_end > 0 and (self._anim_start_time - last_end) < 0.250:
            self._inter_move_ms = (self._anim_start_time - last_end) * 1000.0
        else:
            self._inter_move_ms = 0.0
        self._anim_frame_times = []
        
        # Configure and start High-Precision Timer matching monitor refresh rate
        self.precise_anim_timer.stop()
        self.move_anim.stop()
        self.precise_anim_timer.start(self.timer_interval)
        if (
            not self.debug_anim
            and not getattr(self, '_needs_full_board_paint', True)
            and getattr(self, '_last_painted_flipped', None) == self.flipped
        ):
            start_rect = QRect(self._last_anim_dirty_rect) if self._last_anim_dirty_rect else QRect()
            for sq in (from_square, king_to_sq):
                start_rect = start_rect.united(self._square_widget_rect(sq))
            if rook_data:
                start_rect = start_rect.united(self._square_widget_rect(rook_data['rook_from_square']))
                start_rect = start_rect.united(self._square_widget_rect(rook_data['rook_to_square']))
            if prev_last_move:
                start_rect = start_rect.united(self._square_widget_rect(prev_last_move.from_square))
                start_rect = start_rect.united(self._square_widget_rect(prev_last_move.to_square))
            if not start_rect.isEmpty():
                self.update(start_rect)
            else:
                self.update()
        else:
            self.update() 

    def hideEvent(self, event):
        self.abort_piece_slide()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.abort_piece_slide()
        super().closeEvent(event)

    def abort_piece_slide(self):
        """Immediately stops any ongoing animation and clears animation data."""
        if self.is_animating:
            self.precise_anim_timer.stop()
            self.move_anim.stop()
            self.is_animating = False
            self.animating_piece_data = None
            self._invalidate_snapshot()
            if getattr(self, '_gc_disabled_for_anim', False):
                gc.enable()
                self._gc_disabled_for_anim = False
            if getattr(self, '_winmm_timer_active', False):
                _set_winmm_timer_period(False)
                self._winmm_timer_active = False
            self.update()

    def _on_animation_frame(self, value=None):
        if self.animating_piece_data:
            if value is not None:
                self.animating_piece_data['progress'] = value
                if 'rook_piece' in self.animating_piece_data:
                    rook_raw = 0.0 if value <= 0.25 else min(1.0, (float(value) - 0.25) / 0.75)
                    self.animating_piece_data['rook_progress'] = math.sin(rook_raw * (math.pi / 2.0))
            self._anim_frame_times.append(time.perf_counter())
            self.update()

    def _on_precise_anim_tick(self):
        if not self.animating_piece_data or not self.is_animating:
            self.precise_anim_timer.stop()
            return
        
        now = time.perf_counter()
        elapsed_ms = (now - self._anim_start_time) * 1000.0
        raw_progress = min(1.0, elapsed_ms / self.anim_duration) if self.anim_duration > 0 else 1.0
        
        # OutSine Easing Curve: f(t) = sin(t * pi / 2)
        eased_progress = math.sin(raw_progress * (math.pi / 2.0))
        
        self.animating_piece_data['progress'] = eased_progress
        if 'rook_piece' in self.animating_piece_data:
            if raw_progress <= 0.25:
                rook_eased = 0.0
            else:
                rook_raw = min(1.0, (raw_progress - 0.25) / 0.75)
                rook_eased = math.sin(rook_raw * (math.pi / 2.0))
            self.animating_piece_data['rook_progress'] = rook_eased

        if raw_progress >= 1.0:
            self.precise_anim_timer.stop()
            self._on_animation_finished()
            return

        if self.debug_anim:
            self.update()
        else:
            cur_rect = self._get_anim_dirty_rect()
            prev_rect = self._last_anim_dirty_rect
            upd_rect = cur_rect.united(prev_rect) if (prev_rect is not None and not prev_rect.isEmpty()) else cur_rect
            self._last_anim_dirty_rect = cur_rect
            if not upd_rect.isEmpty():
                self.update(upd_rect)
            else:
                self.update()

    def _on_animation_finished(self):
        if not self.animating_piece_data: return
        end_time = time.perf_counter()
        self._last_slide_end_time = end_time
        duration_ms = (end_time - self._anim_start_time) * 1000.0
        frame_count = len(self._anim_frame_times)
        avg_fps = (frame_count / (duration_ms / 1000.0)) if duration_ms > 0 else 0.0

        # Compute maximum frame-to-frame gap to catch micro-stutters even when average FPS looks okay
        max_gap_ms = 0.0
        if self._anim_frame_times:
            first_gap = (self._anim_frame_times[0] - self._anim_start_time) * 1000.0
            if first_gap > max_gap_ms:
                max_gap_ms = first_gap
            for i in range(1, len(self._anim_frame_times)):
                gap = (self._anim_frame_times[i] - self._anim_frame_times[i - 1]) * 1000.0
                if gap > max_gap_ms:
                    max_gap_ms = gap
        setup_ms = getattr(self, '_anim_setup_ms', 0.0)
        inter_move_ms = getattr(self, '_inter_move_ms', 0.0)
        
        self._last_anim_stats = {
            "fps": round(avg_fps, 1),
            "frames": frame_count,
            "ms": round(duration_ms, 1),
            "max_gap_ms": round(max_gap_ms, 1),
            "setup_ms": round(setup_ms, 1),
            "inter_move_ms": round(inter_move_ms, 1),
        }
        if self.debug_anim:
            print(
                f"[ANIM DEBUG] Move completed in {duration_ms:.1f}ms | Frames: {frame_count} "
                f"| FPS: {avg_fps:.1f} | MaxGap: {max_gap_ms:.1f}ms | Setup: {setup_ms:.1f}ms"
            )

        # Warn if FPS drops below 75% of target display refresh rate (without artificial 70 FPS cap)
        # or if a severe single-frame hitch / inter-move freeze occurred
        fps_threshold = self.target_fps * 0.75
        gap_threshold_ms = max(45.0, (1000.0 / max(30, self.target_fps)) * 2.5)
        low_fps = (avg_fps < fps_threshold and duration_ms >= 35)
        frame_stutter = (max_gap_ms > gap_threshold_ms and duration_ms >= 35)
        inter_move_stall = (inter_move_ms > 35.0)
        if low_fps or frame_stutter or inter_move_stall:
            logger.warning(
                f"[ANIM PERF] Low animation FPS detected: {avg_fps:.1f} FPS "
                f"(Target: {self.target_fps}Hz, Frames: {frame_count}, Duration: {duration_ms:.1f}ms, "
                f"MaxGap: {max_gap_ms:.1f}ms, Setup: {setup_ms:.1f}ms, InterMove: {inter_move_ms:.1f}ms)"
            )

        d = self.animating_piece_data
        self.is_animating = False
        move = d['move']
        is_cap = self.board.is_capture(move)
        self.board.push(move)
        self.last_move = move
        self.last_move_was_capture = is_cap
        self.animating_piece_data = None
        self._invalidate_snapshot()
        self.clear_user_drawings()
        self.piece_slide_finished.emit()

        # Restore Python cyclic GC only once the entire animation sequence is done
        if not self.is_animating:
            if getattr(self, '_gc_disabled_for_anim', False):
                gc.enable()
                self._gc_disabled_for_anim = False
            if getattr(self, '_winmm_timer_active', False):
                _set_winmm_timer_period(False)
                self._winmm_timer_active = False
            self.update()

    def draw_piece(self, painter, piece, col, row, size, scale_factor=1.0):
        key = PIECE_KEY_MAP.get((piece.piece_type, piece.color))
        if key and key in self.piece_pixmaps:
            pm = self.piece_pixmaps[key]
            if scale_factor == 1.0 and not getattr(self, '_is_resizing', False):
                painter.drawPixmap(QPointF(col * size, row * size), pm)
            else:
                # Center-aligned scaling (also used for smooth live-resize before SVG re-rasterization)
                offset = (size * (scale_factor - 1.0)) / 2.0
                target_rect = QRectF(col * size - offset, row * size - offset, size * scale_factor, size * scale_factor)
                painter.drawPixmap(target_rect, pm, QRectF(pm.rect()))
