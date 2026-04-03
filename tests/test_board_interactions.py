import pytest
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, QPoint, QPointF
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def board_widget(qapp):
    """Fixture for ChessBoardWidget."""
    widget = ChessBoardWidget()
    widget.resize(800, 800)
    widget.show()
    yield widget
    widget.close()

def test_square_detection(board_widget):
    """Test converting mouse positions to chess squares."""
    # Ensure standard orientation
    board_widget.flipped = False
    
    # Square a1 (bottom-left area of the board)
    # side, square_size, x_offset, y_offset = self.get_metrics()
    # Let's use a specific point
    side, sq_size, x_off, y_off = board_widget.get_metrics()
    
    # Coordinate a1 is bottom left
    # x = x_off + 0.5 * sq_size, y = y_off + 7.5 * sq_size
    a1_pos = QPointF(x_off + 0.5 * sq_size, y_off + 7.5 * sq_size).toPoint()
    assert board_widget.get_square_from_pos(a1_pos) == chess.A1
    
    # Coordinate h8 is top right
    h8_pos = QPointF(x_off + 7.5 * sq_size, y_off + 0.5 * sq_size).toPoint()
    assert board_widget.get_square_from_pos(h8_pos) == chess.H8
    
    # Test flipped board
    board_widget.flipped = True
    assert board_widget.get_square_from_pos(a1_pos) == chess.H8
    assert board_widget.get_square_from_pos(h8_pos) == chess.A1

def test_piece_dragging_successful_move(board_widget):
    """Test dragging a piece to make a legal move."""
    side, sq_size, x_off, y_off = board_widget.get_metrics()
    
    # Start square e2
    e2_pos = QPointF(x_off + 4.5 * sq_size, y_off + 6.5 * sq_size).toPoint()
    # End square e4
    e4_pos = QPointF(x_off + 4.5 * sq_size, y_off + 4.5 * sq_size).toPoint()
    
    # Mock signals
    moves = []
    board_widget.move_executed.connect(lambda m: moves.append(m))
    
    # Mouse press on e2
    board_widget.mousePressEvent(TestEvent(e2_pos, Qt.MouseButton.LeftButton))
    assert board_widget.dragging_piece is not None
    assert board_widget.drag_start_square == chess.E2
    
    # Mouse move to e4
    board_widget.mouseMoveEvent(TestEvent(e4_pos, Qt.MouseButton.LeftButton))
    assert board_widget.mouse_pos == e4_pos
    
    # Mouse release on e4
    board_widget.mouseReleaseEvent(TestEvent(e4_pos, Qt.MouseButton.LeftButton))
    assert board_widget.dragging_piece is None
    
    assert len(moves) == 1
    assert moves[0].uci() == "e2e4"

def test_piece_dragging_invalid_move(board_widget):
    """Test dragging a piece to an illegal square."""
    side, sq_size, x_off, y_off = board_widget.get_metrics()
    
    # Start square e2
    e2_pos = QPointF(x_off + 4.5 * sq_size, y_off + 6.5 * sq_size).toPoint()
    # End square e5 (illegal move for e2 pawn in first turn)
    e5_pos = QPointF(x_off + 4.5 * sq_size, y_off + 3.5 * sq_size).toPoint()
    
    moves = []
    board_widget.move_executed.connect(lambda m: moves.append(m))
    
    board_widget.mousePressEvent(TestEvent(e2_pos, Qt.MouseButton.LeftButton))
    board_widget.mouseReleaseEvent(TestEvent(e5_pos, Qt.MouseButton.LeftButton))
    
    assert len(moves) == 0

def test_animation_lifecycle(board_widget, qapp):
    """Test that piece animations start and finish correctly."""
    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)
    
    finished = False
    board_widget.piece_slide_finished.connect(lambda: setattr(pytest, "finished", True))
    pytest.finished = False
    
    # Start animation
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget.is_animating is True
    assert board_widget.animating_piece_data['move'] == move
    
    # Fast-forward animation (or stop it)
    board_widget.move_anim.stop()
    board_widget._on_animation_finished()
    
    assert board_widget.is_animating is False
    assert board_widget.board.piece_at(chess.E4) == piece
    assert pytest.finished is True

def test_abort_animation(board_widget):
    """Test that animations can be aborted."""
    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)
    
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget.is_animating is True
    
    board_widget.abort_piece_slide()
    assert board_widget.is_animating is False
    assert board_widget.animating_piece_data is None

def test_theme_and_fen(board_widget):
    """Test setting theme and FEN."""
    board_widget.set_theme("Grün (Lichess)")
    assert board_widget.light_color.name() == THEMES["Grün (Lichess)"][0].name()
    
    new_fen = "rnbqkbnr/pppppp1p/8/6p1/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    board_widget.set_fen(new_fen)
    # The board fen might include move counters (0 1), so use startswith
    assert board_widget.board.fen().startswith(new_fen)
    assert board_widget.last_move is None # Reset on set_fen

def test_arrows_properties(board_widget):
    """Test setting and clearing arrow properties."""
    # Hint arrow
    move = chess.Move.from_uci("e2e4")
    board_widget.hint_arrow = move
    assert board_widget.hint_arrow == move
    
    # Explorer arrows
    color = QColor("red")
    board_widget.explorer_arrows = [(move, color)]
    assert len(board_widget.explorer_arrows) == 1
    assert board_widget.explorer_arrows[0][0] == move
    
    # Clearing
    board_widget.set_fen(chess.STARTING_FEN)
    assert board_widget.hint_arrow is None
    assert len(board_widget.explorer_arrows) == 0

class TestEvent:
    """Helper to mock QMouseEvent for PyQt6."""
    def __init__(self, pos, button):
        self._pos = pos
        self._button = button
    def position(self): return QPointF(self._pos)
    def pos(self): return self._pos
    def button(self): return self._button
    def buttons(self): return self._button
