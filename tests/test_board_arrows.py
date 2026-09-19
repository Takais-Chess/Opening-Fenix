import pytest
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtCore import Qt, QPointF
from opening_fenix.gui.widgets.board_widget import (
    ChessBoardWidget, USER_ARROW_COLORS, USER_HIGHLIGHT_COLORS
)


class MockMouseEvent:
    def __init__(self, pos, button, modifiers=Qt.KeyboardModifier.NoModifier):
        self._pos = pos
        self._button = button
        self._modifiers = modifiers

    def position(self):
        return QPointF(self._pos)

    def pos(self):
        return self._pos

    def button(self):
        return self._button

    def buttons(self):
        return self._button

    def modifiers(self):
        return self._modifiers


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def board(qapp):
    widget = ChessBoardWidget()
    widget.resize(800, 800)
    widget.show()
    yield widget
    widget.close()


def _get_square_pos(board, square):
    """Calculates mouse position at the center of a given square."""
    side, sq_size, x_off, y_off = board.get_metrics()
    f = chess.square_file(square)
    r = chess.square_rank(square)
    col = 7 - f if board.flipped else f
    row = r if board.flipped else 7 - r
    return QPointF(x_off + (col + 0.5) * sq_size, y_off + (row + 0.5) * sq_size)


def test_draw_green_arrow_default(board):
    """Test dragging with right mouse button draws a green arrow by default."""
    e2_pos = _get_square_pos(board, chess.E2)
    e4_pos = _get_square_pos(board, chess.E4)

    # Press RMB on e2
    board.mousePressEvent(MockMouseEvent(e2_pos, Qt.MouseButton.RightButton))
    assert board.is_drawing is True
    assert board.drawing_start_sq == chess.E2
    assert board.drawing_color == USER_ARROW_COLORS["green"]

    # Move RMB to e4
    board.mouseMoveEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    assert board.drawing_current_sq == chess.E4

    # Release RMB on e4
    board.mouseReleaseEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    assert board.is_drawing is False
    assert (chess.E2, chess.E4) in board.user_arrows
    assert board.user_arrows[(chess.E2, chess.E4)] == USER_ARROW_COLORS["green"]


def test_toggle_arrow_off(board):
    """Drawing the same arrow again toggles it off."""
    e2_pos = _get_square_pos(board, chess.E2)
    e4_pos = _get_square_pos(board, chess.E4)

    # Draw arrow e2 -> e4
    board.mousePressEvent(MockMouseEvent(e2_pos, Qt.MouseButton.RightButton))
    board.mouseReleaseEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    assert (chess.E2, chess.E4) in board.user_arrows

    # Draw arrow e2 -> e4 again with same color
    board.mousePressEvent(MockMouseEvent(e2_pos, Qt.MouseButton.RightButton))
    board.mouseReleaseEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    assert (chess.E2, chess.E4) not in board.user_arrows


def test_color_modifiers(board):
    """Test Alt (Red), Ctrl (Yellow), Shift (Blue), and Ctrl+Alt (Orange) arrows."""
    d2_pos = _get_square_pos(board, chess.D2)
    d4_pos = _get_square_pos(board, chess.D4)

    # Red with Alt
    board.mousePressEvent(MockMouseEvent(d2_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.AltModifier))
    assert board.drawing_color == USER_ARROW_COLORS["red"]
    board.mouseReleaseEvent(MockMouseEvent(d4_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.AltModifier))
    assert board.user_arrows[(chess.D2, chess.D4)] == USER_ARROW_COLORS["red"]

    # Yellow with Ctrl on c2->c4
    c2_pos = _get_square_pos(board, chess.C2)
    c4_pos = _get_square_pos(board, chess.C4)
    board.mousePressEvent(MockMouseEvent(c2_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ControlModifier))
    assert board.drawing_color == USER_ARROW_COLORS["yellow"]
    board.mouseReleaseEvent(MockMouseEvent(c4_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ControlModifier))
    assert board.user_arrows[(chess.C2, chess.C4)] == USER_ARROW_COLORS["yellow"]

    # Blue with Shift on b2->b4
    b2_pos = _get_square_pos(board, chess.B2)
    b4_pos = _get_square_pos(board, chess.B4)
    board.mousePressEvent(MockMouseEvent(b2_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ShiftModifier))
    assert board.drawing_color == USER_ARROW_COLORS["blue"]
    board.mouseReleaseEvent(MockMouseEvent(b4_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ShiftModifier))
    assert board.user_arrows[(chess.B2, chess.B4)] == USER_ARROW_COLORS["blue"]

    # Orange with Ctrl+Alt on g1->f3
    g1_pos = _get_square_pos(board, chess.G1)
    f3_pos = _get_square_pos(board, chess.F3)
    board.mousePressEvent(MockMouseEvent(g1_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
    assert board.drawing_color == USER_ARROW_COLORS["orange"]
    board.mouseReleaseEvent(MockMouseEvent(f3_pos, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
    assert board.user_arrows[(chess.G1, chess.F3)] == USER_ARROW_COLORS["orange"]


def test_square_highlight_and_toggle(board):
    """Right-clicking a single square toggles square highlight."""
    e4_pos = _get_square_pos(board, chess.E4)

    # Click on e4 (start == end)
    board.mousePressEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    board.mouseReleaseEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    assert chess.E4 in board.user_highlights
    assert board.user_highlights[chess.E4] == USER_HIGHLIGHT_COLORS["green"]

    # Click on e4 again toggles it off
    board.mousePressEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    board.mouseReleaseEvent(MockMouseEvent(e4_pos, Qt.MouseButton.RightButton))
    assert chess.E4 not in board.user_highlights


def test_clear_drawings_on_left_click(board):
    """Left-clicking on empty board clears all user drawings."""
    board.add_user_arrow(chess.E2, chess.E4, "green")
    board.add_user_highlight(chess.D5, "red")
    assert len(board.user_arrows) == 1
    assert len(board.user_highlights) == 1

    # Left-click on empty square e4
    e4_pos = _get_square_pos(board, chess.E4)
    board.mousePressEvent(MockMouseEvent(e4_pos, Qt.MouseButton.LeftButton))
    assert len(board.user_arrows) == 0
    assert len(board.user_highlights) == 0


def test_clear_drawings_on_set_fen_and_move(board):
    """Drawings clear when set_fen is called or legal move is made."""
    board.add_user_arrow(chess.E2, chess.E4)
    assert len(board.user_arrows) == 1

    # set_fen clears drawings
    board.set_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    assert len(board.user_arrows) == 0

    # Draw arrow again
    board.set_fen(chess.STARTING_FEN)
    board.add_user_arrow(chess.E2, chess.E4)
    assert len(board.user_arrows) == 1

    # Execute move e2->e4 via drag
    e2_pos = _get_square_pos(board, chess.E2)
    e4_pos = _get_square_pos(board, chess.E4)
    board.mousePressEvent(MockMouseEvent(e2_pos, Qt.MouseButton.LeftButton))
    board.mouseReleaseEvent(MockMouseEvent(e4_pos, Qt.MouseButton.LeftButton))
    assert len(board.user_arrows) == 0


def test_public_api_methods(board):
    """Test programmatic API methods."""
    board.add_user_arrow(chess.E2, chess.E4, "yellow")
    assert board.user_arrows[(chess.E2, chess.E4)] == USER_ARROW_COLORS["yellow"]

    board.remove_user_arrow(chess.E2, chess.E4)
    assert (chess.E2, chess.E4) not in board.user_arrows

    board.add_user_highlight(chess.E4, "blue")
    assert board.user_highlights[chess.E4] == USER_HIGHLIGHT_COLORS["blue"]

    board.remove_user_highlight(chess.E4)
    assert chess.E4 not in board.user_highlights

    board.add_user_arrow(chess.C1, chess.F4, "red")
    board.add_user_highlight(chess.D4, "orange")
    board.clear_user_drawings()
    assert len(board.user_arrows) == 0
    assert len(board.user_highlights) == 0


def test_render_paint_event_with_drawings(board):
    """Verify that paintEvent renders without exceptions with active arrows and highlights."""
    board.add_user_arrow(chess.E2, chess.E4, "green")
    board.add_user_arrow(chess.G1, chess.F3, "yellow")
    board.add_user_highlight(chess.D5, "red")
    board.add_user_highlight(chess.E4, "blue")

    # Force repaint
    pixmap = QPixmap(board.size())
    painter = QPainter(pixmap)
    board.render(painter)
    painter.end()

    # Flip board and repaint
    board.flipped = True
    pixmap2 = QPixmap(board.size())
    painter2 = QPainter(pixmap2)
    board.render(painter2)
    painter2.end()
