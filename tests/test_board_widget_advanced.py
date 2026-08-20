import pytest
import chess
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor

from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES

def test_board_widget_orientation_and_flip(qtbot):
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    
    assert board.flipped is False
    board.flipped = True
    assert board.flipped is True
    board.flipped = False
    assert board.flipped is False

def test_board_widget_arrows_and_last_move(qtbot):
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    
    # Last move
    move = chess.Move.from_uci("e2e4")
    board.last_move = move
    assert board.last_move == move
    
    # Hint arrow
    board.hint_arrow = (chess.E2, chess.E4)
    assert board.hint_arrow == (chess.E2, chess.E4)
    
    # Solution arrow
    board.solution_arrow = (chess.E7, chess.E5)
    assert board.solution_arrow == (chess.E7, chess.E5)
    
    # Explorer arrows
    board.explorer_arrows = [(chess.G1, chess.F3, "Nf3", 100, 55.0)]
    assert len(board.explorer_arrows) == 1

def test_board_widget_themes(qtbot):
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    
    for theme_name, (light, dark) in THEMES.items():
        board.light_color = light
        board.dark_color = dark
        assert board.light_color == light
        assert board.dark_color == dark

def test_board_widget_animation_lifecycle(qtbot):
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    
    piece = chess.Piece(chess.PAWN, chess.WHITE)
    move = chess.Move.from_uci("e2e4")
    
    board.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board.is_animating is True
    assert board.animating_piece_data is not None
    
    board.abort_piece_slide()
    assert board.is_animating is False
    assert board.animating_piece_data is None

def test_board_widget_screen_refresh_rate(qtbot):
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    
    hz = board.get_screen_refresh_rate()
    assert 30 <= hz <= 240

def test_board_widget_metrics(qtbot):
    board = ChessBoardWidget()
    board.resize(600, 600)
    qtbot.addWidget(board)
    
    side, square_size, x_offset, y_offset = board.get_metrics()
    assert side > 0
    assert square_size > 0
