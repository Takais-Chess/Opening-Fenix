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

def test_outsine_easing_and_distance_scaling(board_widget):
    """Verify that square-root distance scaling scales durations accurately and OutSine easing is computed."""
    board_widget.target_fps = 60
    board_widget.update_animation_metrics(200)
    
    # 1. Short move: e2e3 (dist = 1) -> should be shorter duration (~183.3ms = 11 frames at 60Hz)
    move_short = chess.Move.from_uci('e2e3')
    piece = board_widget.board.piece_at(chess.E2)
    board_widget.start_piece_slide(piece, chess.E2, chess.E3, move_short)
    dur_short = board_widget.anim_duration
    board_widget.abort_piece_slide()
    
    # 2. Medium move: e2e4 (dist = 2) -> matches baseline (~200ms = 12 frames at 60Hz)
    move_med = chess.Move.from_uci('e2e4')
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move_med)
    dur_med = board_widget.anim_duration
    board_widget.abort_piece_slide()
    
    # 3. Long move: a1a8 (dist = 7) -> longer duration (~250ms = 15 frames at 60Hz)
    move_long = chess.Move.from_uci('a1a8')
    rook = board_widget.board.piece_at(chess.A1)
    board_widget.start_piece_slide(rook, chess.A1, chess.A8, move_long)
    dur_long = board_widget.anim_duration
    
    assert dur_short < dur_med < dur_long
    assert dur_med == 200.0
    
    # Check OutSine easing calculation at 50% elapsed time
    board_widget._anim_start_time = time.perf_counter() - (dur_long / 2000.0) # 50% elapsed
    board_widget._on_precise_anim_tick()
    # OutSine at t=0.5 is sin(pi/4) = sqrt(2)/2 ~= 0.7071
    assert 0.69 < board_widget.animating_piece_data['progress'] < 0.72
    board_widget.abort_piece_slide()

def test_gc_suspension_lifecycle(board_widget):
    """Verify that Python cyclic GC is suspended during piece slide and restored upon completion/abort."""
    import gc
    gc.enable()
    assert gc.isenabled() is True

    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)

    # 1. Start slide -> GC should be disabled
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget.is_animating is True
    assert board_widget._gc_disabled_for_anim is True
    assert gc.isenabled() is False

    # 2. Finish slide -> GC should be re-enabled
    board_widget._on_animation_finished()
    assert board_widget.is_animating is False
    assert board_widget._gc_disabled_for_anim is False
    assert gc.isenabled() is True

    # 3. Abort slide -> GC should be re-enabled
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert gc.isenabled() is False
    board_widget.abort_piece_slide()
    assert board_widget.is_animating is False
    assert board_widget._gc_disabled_for_anim is False
    assert gc.isenabled() is True
