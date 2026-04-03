import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtTest import QTest
import chess
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget

@pytest.fixture
def board_widget(qapp):
    """Fixture for ChessBoardWidget."""
    widget = ChessBoardWidget()
    widget.show()
    return widget

def test_board_square_from_pos(board_widget):
    """Test getting square from mouse position."""
    # Assuming standard 800x800-ish size, middle of the board should be middle squares
    # We need to consider offsets and padding
    side, sq_size, x_off, y_off = board_widget.get_metrics()
    
    # Square e2 center
    file, rank = chess.E2 % 8, chess.E2 // 8
    # In non-flipped: row = 7 - rank
    row = 7 - rank
    col = file
    
    px = x_off + (col + 0.5) * sq_size
    py = y_off + (row + 0.5) * sq_size
    
    sq = board_widget.get_square_from_pos(QPointF(px, py))
    assert sq == chess.E2

def test_board_arrows(board_widget):
    """Test arrow attributes (hint_arrow, explorer_arrows)."""
    move = chess.Move(chess.E2, chess.E4)
    
    # 1. Hint arrow
    board_widget.hint_arrow = move
    assert board_widget.hint_arrow == move
    
    # 2. Explorer arrows
    board_widget.explorer_arrows = [(move, "blue")]
    assert len(board_widget.explorer_arrows) == 1
    assert board_widget.explorer_arrows[0][0] == move
    
    # 3. Clear
    board_widget.set_fen(chess.STARTING_FEN)
    assert board_widget.hint_arrow is None
    assert len(board_widget.explorer_arrows) == 0

def test_board_drag_state(board_widget):
    """Test internal drag state (mocking mouse events)."""
    # Start dragging e2
    board_widget.drag_start_square = chess.E2
    board_widget.dragging_piece = chess.Piece(chess.PAWN, chess.WHITE)
    board_widget.mouse_pos = QPoint(100, 100)
    board_widget.update()
    
    assert board_widget.dragging_piece.color == chess.WHITE
    
    # Stop dragging
    board_widget.dragging_piece = None
    board_widget.drag_start_square = None
    board_widget.update()
    assert board_widget.dragging_piece is None

def test_board_theme(board_widget):
    """Test theme switching."""
    from opening_fenix.gui.widgets.board_widget import THEMES
    board_widget.set_theme("Grün (Lichess)")
    assert board_widget.light_color == THEMES["Grün (Lichess)"][0]
    assert board_widget.dark_color == THEMES["Grün (Lichess)"][1]
