import pytest
import chess
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QWidget
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES


def test_board_dpi_scaling_geometry(qtbot):
    """Verify that board dimensions and square size calculate consistently across various DPI factors."""
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    board.resize(600, 600)

    side, sq_size, x_off, y_off = board.get_metrics()
    assert side > 0
    assert sq_size == side / 8.0
    assert x_off == float(board.padding)
    assert y_off == float(board.padding)


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0, 2.5])
def test_board_pixmap_cache_at_various_dprs(qtbot, monkeypatch, dpr):
    """Test that piece pixmap cache scales and generates crisp pixmaps for fractional and integer DPRs."""
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    
    # Mock devicePixelRatioF
    monkeypatch.setattr(board, "devicePixelRatioF", lambda: dpr)
    
    square_size = 64.0
    board._update_pixmap_cache(square_size)
    
    expected_scaled_size = int(square_size * dpr)
    assert board._last_scaled_size == expected_scaled_size
    assert len(board.piece_pixmaps) > 0
    for key, pix in board.piece_pixmaps.items():
        assert pix.devicePixelRatio() == dpr


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_board_render_paint_event_across_dprs(qtbot, monkeypatch, dpr):
    """Test full paint event execution onto an offscreen canvas with fractional DPRs in idle, drag, and anim states."""
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    board.resize(550, 500)
    monkeypatch.setattr(board, "devicePixelRatioF", lambda: dpr)

    # 1. Idle state render
    pixmap = QPixmap(int(board.width() * dpr), int(board.height() * dpr))
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    side, square_size, x_offset, y_offset = board.get_metrics()
    board._update_pixmap_cache(square_size)
    painter.translate(x_offset, y_offset)
    board._paint_board_base(painter, square_size)
    board._paint_pieces(painter, square_size)
    board._paint_arrows(painter, square_size)
    painter.end()

    # 2. Animation state render
    piece = chess.Piece(chess.PAWN, chess.WHITE)
    move = chess.Move.from_uci("e2e4")
    board.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board.is_animating is True
    
    # Render animation frame
    painter = QPainter(pixmap)
    painter.translate(x_offset, y_offset)
    board._paint_board_base(painter, square_size)
    board._paint_pieces(painter, square_size, skip_square=chess.E2)
    board._paint_arrows(painter, square_size)
    board.draw_piece(painter, piece, 4.0, 5.0, square_size)
    painter.end()

    # Finish animation
    board.abort_piece_slide()
    assert board.is_animating is False


@pytest.mark.parametrize("width,height", [
    (800, 600),   # Wide
    (600, 800),   # Tall
    (600, 600),   # Square
    (400, 400),   # Minimum
])
def test_board_metrics_aspect_ratios(qtbot, width, height):
    """Ensure get_metrics returns bounded, symmetric coordinates for different window aspect ratios."""
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    board.resize(width, height)
    
    side, sq_size, x_off, y_off = board.get_metrics()
    assert side > 0
    assert sq_size > 0
    assert x_off >= 0
    assert y_off >= 0
    
    actual_w = board.width()
    actual_h = board.height()
    if actual_h >= actual_w:
        assert side == actual_w - board.padding * 2
        assert x_off == float(board.padding)
    else:
        assert side == actual_h - board.padding * 2
        assert x_off == float(actual_w - board.padding - side)


def test_board_animation_idle_coordinate_invariance(qtbot):
    """Verify that square coordinates and metrics are 100% identical during animation vs after animation."""
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    board.resize(500, 500)
    
    metrics_before = board.get_metrics()
    
    piece = chess.Piece(chess.KNIGHT, chess.WHITE)
    move = chess.Move.from_uci("g1f3")
    board.start_piece_slide(piece, chess.G1, chess.F3, move)
    
    metrics_during = board.get_metrics()
    assert metrics_before == metrics_during
    
    board._on_animation_finished()
    metrics_after = board.get_metrics()
    assert metrics_during == metrics_after


@pytest.mark.parametrize("theme_name", list(THEMES.keys()))
def test_board_themes_and_flipping_with_dpi(qtbot, monkeypatch, theme_name):
    """Test switching themes and flipping orientation under simulated 125% High-DPI."""
    board = ChessBoardWidget()
    qtbot.addWidget(board)
    board.resize(500, 500)
    monkeypatch.setattr(board, "devicePixelRatioF", lambda: 1.25)
    
    board.set_theme(theme_name)
    assert board.light_color == THEMES[theme_name][0]
    assert board.dark_color == THEMES[theme_name][1]
    
    board.flipped = True
    side, sq_size, x_off, y_off = board.get_metrics()
    board._update_pixmap_cache(sq_size)
    assert len(board.piece_pixmaps) > 0
