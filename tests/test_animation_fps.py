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


def test_high_refresh_display_low_fps_warning_not_capped_at_70(board_widget):
    """Verify that on a 144Hz display, dropping to ~80 FPS triggers a warning (no 70 FPS cap)."""
    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)

    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    board_widget.target_fps = 144

    # 16 frames in 200ms = 80 FPS (< 144 * 0.75 = 108 FPS)
    board_widget._anim_start_time = time.perf_counter() - 0.200
    board_widget._anim_frame_times = [board_widget._anim_start_time + (i * 0.012) for i in range(16)]

    with patch('opening_fenix.gui.widgets.board_widget.logger.warning') as mock_warn:
        board_widget._on_animation_finished()
        mock_warn.assert_called_once()
        assert 'Target: 144Hz' in mock_warn.call_args[0][0]


def test_single_frame_stutter_triggers_warning(board_widget):
    """Verify that a severe single-frame hitch (>45ms gap) triggers a warning even if average FPS is acceptable."""
    move = chess.Move.from_uci('e2e4')
    piece = board_widget.board.piece_at(chess.E2)

    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    board_widget.target_fps = 60

    # 12 frames in 200ms (60 FPS average), but with a 70ms freeze on the first frame
    start_t = time.perf_counter() - 0.200
    board_widget._anim_start_time = start_t
    board_widget._anim_frame_times = [start_t + 0.070 + (i * 0.010) for i in range(12)]

    with patch('opening_fenix.gui.widgets.board_widget.logger.warning') as mock_warn:
        board_widget._on_animation_finished()
        mock_warn.assert_called_once()
        assert 'MaxGap:' in mock_warn.call_args[0][0]


def test_gc_stays_disabled_across_chained_multi_move_sequence(board_widget):
    """Verify that GC stays disabled across chained moves and is re-enabled after the final move."""
    import gc
    gc.enable()

    m1 = chess.Move.from_uci('e2e4')
    m2 = chess.Move.from_uci('e7e5')
    p1 = board_widget.board.piece_at(chess.E2)
    gc_states_during_chain = []

    def on_first_finished():
        board_widget.piece_slide_finished.disconnect(on_first_finished)
        gc_states_during_chain.append(gc.isenabled())
        p2 = board_widget.board.piece_at(chess.E7)
        board_widget.start_piece_slide(p2, chess.E7, chess.E5, m2)

    board_widget.piece_slide_finished.connect(on_first_finished)
    board_widget.start_piece_slide(p1, chess.E2, chess.E4, m1)
    assert gc.isenabled() is False

    # Finishing m1 chains immediately into m2; GC must stay disabled throughout
    board_widget._on_animation_finished()
    assert gc_states_during_chain == [False]
    assert board_widget.is_animating is True
    assert gc.isenabled() is False

    # Finishing m2 ends the sequence; GC is now re-enabled
    board_widget._on_animation_finished()
    assert board_widget.is_animating is False
    assert gc.isenabled() is True


def test_castling_staggered_rook_animation(board_widget):
    """Verify that castling animates both king and rook, with rook starting at 25% and both finishing at 100%."""
    board_widget.set_fen("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
    move = chess.Move.from_uci("e1g1")
    king = board_widget.board.piece_at(chess.E1)

    board_widget.start_piece_slide(king, chess.E1, chess.G1, move, duration_override=200.0)
    data = board_widget.animating_piece_data
    assert data is not None
    assert data['from_square'] == chess.E1
    assert data['to_square'] == chess.G1
    assert data['rook_from_square'] == chess.H1
    assert data['rook_to_square'] == chess.F1
    assert data['rook_progress'] == 0.0

    # At 20% elapsed time (before 25% threshold): king moves, rook stays at 0.0
    board_widget._anim_start_time = time.perf_counter() - 0.040
    board_widget._on_precise_anim_tick()
    assert board_widget.animating_piece_data['progress'] > 0.30
    assert board_widget.animating_piece_data['rook_progress'] == 0.0

    # At 62.5% elapsed time (halfway through rook's 25%..100% window -> rook_raw = 0.5):
    board_widget._anim_start_time = time.perf_counter() - 0.125
    board_widget._on_precise_anim_tick()
    assert board_widget.animating_piece_data['progress'] > 0.80
    assert 0.69 < board_widget.animating_piece_data['rook_progress'] < 0.72

    # At 100% elapsed time: both finish together
    board_widget._anim_start_time = time.perf_counter() - 0.205
    board_widget._on_precise_anim_tick()
    assert board_widget.is_animating is False
    assert board_widget.board.piece_at(chess.G1) == chess.Piece(chess.KING, chess.WHITE)
    assert board_widget.board.piece_at(chess.F1) == chess.Piece(chess.ROOK, chess.WHITE)


def test_dirty_rect_updates_during_animation(board_widget):
    """Verify intermediate animation ticks request tight dirty-rect repaints instead of full-widget repaints."""
    from PyQt6.QtCore import QRect

    board_widget.debug_anim = False
    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move, duration_override=200.0)

    update_calls = []
    orig_update = board_widget.update

    def spy_update(*args):
        update_calls.append(args)
        return orig_update(*args)

    with patch.object(board_widget, "update", side_effect=spy_update):
        board_widget._anim_start_time = time.perf_counter() - 0.080
        board_widget._on_precise_anim_tick()

    assert len(update_calls) == 1
    assert len(update_calls[0]) == 1
    dirty = update_calls[0][0]
    assert isinstance(dirty, QRect)
    assert not dirty.isEmpty()
    assert dirty.width() < board_widget.width()
    assert dirty.height() < board_widget.height()
    board_widget.abort_piece_slide()


def test_squares_pixmap_cache_and_snapshot_buffer_reuse(board_widget):
    """Verify checkerboard QPixmap is cached across moves and snapshot QPixmap buffer is reused."""
    m1 = chess.Move.from_uci("e2e4")
    p1 = board_widget.board.piece_at(chess.E2)
    board_widget.start_piece_slide(p1, chess.E2, chess.E4, m1)
    sq_pm_1 = board_widget._squares_pixmap
    buf_1 = board_widget._snapshot_buffer
    assert sq_pm_1 is not None
    assert buf_1 is not None
    board_widget._on_animation_finished()

    m2 = chess.Move.from_uci("e7e5")
    p2 = board_widget.board.piece_at(chess.E7)
    board_widget.start_piece_slide(p2, chess.E7, chess.E5, m2)
    assert board_widget._squares_pixmap is sq_pm_1
    assert board_widget._snapshot_buffer is buf_1
    board_widget._on_animation_finished()

    # Theme change must invalidate the cached checkerboard layer
    board_widget.set_theme("Grün")
    assert board_widget._squares_pixmap is None


