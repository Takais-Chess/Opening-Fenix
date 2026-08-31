import time
import pytest
import chess
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QPixmap
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget

@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def board_widget(qapp):
    widget = ChessBoardWidget()
    widget.resize(800, 800)
    widget.show()
    yield widget
    widget.close()

def test_unified_rendering_during_animation(board_widget):
    """Verify that the unified rendering pipeline paints correctly during animation and transitions smoothly to idle."""
    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)
    
    # Start animation
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget.is_animating is True
    assert board_widget.animating_piece_data is not None
    assert board_widget.animating_piece_data['from_square'] == chess.E2
    assert board_widget.animating_piece_data['to_square'] == chess.E4
    
    # Trigger paint event while animating
    pixmap = QPixmap(board_widget.size())
    painter = QPainter(pixmap)
    board_widget.paintEvent(None)
    painter.end()
    
    # Advance animation tick
    board_widget._on_precise_anim_tick()
    assert board_widget.animating_piece_data['progress'] > 0.0
    
    # Finish animation - transitions cleanly back to idle state
    board_widget._on_animation_finished()
    assert board_widget.is_animating is False
    assert board_widget.animating_piece_data is None
    assert board_widget.board.piece_at(chess.E4) == piece

def test_animation_fps_stats_calculated(board_widget):
    """Verify that frame times and average FPS stats are tracked and calculated upon finish."""
    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)
    
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    
    # Simulate multiple animation frames
    for i in range(12):
        board_widget._anim_frame_times.append(board_widget._anim_start_time + (i * 0.016))
    
    # Set anim start time to 200ms ago
    board_widget._anim_start_time = time.perf_counter() - 0.200
    
    board_widget._on_animation_finished()
    
    stats = board_widget._last_anim_stats
    assert stats is not None
    assert 'fps' in stats
    assert 'frames' in stats
    assert 'ms' in stats
    assert stats['frames'] >= 12
    assert stats['fps'] > 0

def test_low_fps_warning_triggered(board_widget):
    """Verify that a warning is logged when FPS drops below performance threshold."""
    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)
    
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    board_widget.target_fps = 120
    
    # Simulate slow animation: 2 frames delivered over 300ms (~6.6 FPS)
    board_widget._anim_start_time = time.perf_counter() - 0.300
    board_widget._anim_frame_times = [board_widget._anim_start_time, time.perf_counter()]
    
    with patch('opening_fenix.gui.widgets.board_widget.logger.warning') as mock_warn:
        board_widget._on_animation_finished()
        mock_warn.assert_called_once()
        warning_msg = mock_warn.call_args[0][0]
        assert '[ANIM PERF] Low animation FPS detected' in warning_msg
        assert 'Target: 120Hz' in warning_msg

def test_high_fps_no_warning(board_widget):
    """Verify that no warning is logged when FPS meets or exceeds target threshold."""
    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)
    
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    board_widget.target_fps = 60
    
    # Simulate smooth 60 FPS: 12 frames in 200ms
    board_widget._anim_start_time = time.perf_counter() - 0.200
    board_widget._anim_frame_times = [board_widget._anim_start_time + (i * 0.016) for i in range(12)]
    
    with patch('opening_fenix.gui.widgets.board_widget.logger.warning') as mock_warn:
        board_widget._on_animation_finished()
        mock_warn.assert_not_called()
