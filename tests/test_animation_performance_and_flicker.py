import pytest
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QImage, QColor
from PyQt6.QtCore import Qt, QPointF
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def board_widget(qapp):
    widget = ChessBoardWidget()
    widget.resize(755, 755)
    widget.show()
    yield widget
    widget.close()


def render_widget_to_image(widget, dpr=None):
    """Renders the current widget state to a QImage with pixel-perfect DPI backing store."""
    if dpr is None:
        dpr = widget.devicePixelRatioF()
    w_px = max(1, round(widget.width() * dpr))
    h_px = max(1, round(widget.height() * dpr))
    img = QImage(w_px, h_px, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(widget.palette().window().color())

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    # Paint onto the offscreen target using widget's paintEvent logic
    side, square_size, x_offset, y_offset = widget.get_metrics()
    widget._update_pixmap_cache(square_size)

    is_anim = widget.is_animating and widget.animating_piece_data

    if is_anim and widget._board_snapshot is not None:
        painter.drawPixmap(0, 0, widget._board_snapshot)
        painter.translate(x_offset, y_offset)
        widget._paint_coordinates(painter, square_size)
        d = widget.animating_piece_data
        p = d['progress']
        cur_col = d['start_col'] + (d['end_col'] - d['start_col']) * p
        cur_row = d['start_row'] + (d['end_row'] - d['start_row']) * p
        widget.draw_piece(painter, d['piece'], cur_col, cur_row, square_size)
    else:
        skip_square = widget.animating_piece_data['from_square'] if is_anim else None
        painter.translate(x_offset, y_offset)
        widget._paint_board_base(painter, square_size)
        widget._paint_pieces(painter, square_size, skip_square=skip_square)
        widget._paint_circles(painter, square_size)
        widget._paint_arrows(painter, square_size)

    painter.end()
    return img


def count_image_diffs(img1, img2, tolerance=3):
    """
    Compares two QImages pixel by pixel and returns total differing pixel count.
    Allows tolerance (default 3 / ~1%) for sub-pixel alpha premultiplication rounding on antialiased edges.
    """
    assert img1.size() == img2.size()
    try:
        import numpy as np
        img1_c = img1.convertToFormat(QImage.Format.Format_ARGB32)
        img2_c = img2.convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img1_c.width(), img1_c.height()
        ptr1 = img1_c.bits()
        ptr1.setsize(img1_c.sizeInBytes())
        ptr2 = img2_c.bits()
        ptr2.setsize(img2_c.sizeInBytes())
        a1 = np.frombuffer(ptr1, dtype=np.uint8).reshape((h, w, 4))[:, :, :3].astype(np.int16)
        a2 = np.frombuffer(ptr2, dtype=np.uint8).reshape((h, w, 4))[:, :, :3].astype(np.int16)
        max_c_diff = np.abs(a1 - a2).max(axis=2)
        ys, xs = np.where(max_c_diff > tolerance)
        diff_coords = list(zip(xs.tolist(), ys.tolist()))
        return len(diff_coords), diff_coords
    except ImportError:
        diffs = 0
        diff_coords = []
        for y in range(img1.height()):
            for x in range(img1.width()):
                c1 = img1.pixelColor(x, y)
                c2 = img2.pixelColor(x, y)
                if max(abs(c1.red() - c2.red()), abs(c1.green() - c2.green()), abs(c1.blue() - c2.blue())) > tolerance:
                    diffs += 1
                    diff_coords.append((x, y))
        return diffs, diff_coords


def test_zero_flicker_at_animation_start(board_widget):
    """
    Verify that entering animation mode (progress = 0.0) produces 0 differing pixels
    compared to the idle board. Proves the board does not flicker or shift positions when a slide starts.
    """
    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)

    # 1. Capture idle state (with move set as last_move so highlight is aligned)
    board_widget.last_move = move
    img_idle = render_widget_to_image(board_widget)

    # 2. Start animation and capture Frame at progress = 0.0
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget.is_animating is True
    assert board_widget._board_snapshot is not None
    board_widget.animating_piece_data['progress'] = 0.0
    img_anim_start = render_widget_to_image(board_widget)

    diffs, _ = count_image_diffs(img_idle, img_anim_start)
    assert diffs == 0, f"Expected 0 diff pixels at animation start, got {diffs}"
    board_widget.abort_piece_slide()


def test_zero_flicker_at_animation_finish_non_capture(board_widget):
    """
    Verify that concluding animation mode at progress = 1.0 produces 0 differing pixels
    compared to post-push idle state for non-captures.
    """
    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)

    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    board_widget.animating_piece_data['progress'] = 1.0
    img_anim_end = render_widget_to_image(board_widget)

    # Conclude animation (pushes move to board, transitions back to idle direct render)
    board_widget._on_animation_finished()
    assert board_widget.is_animating is False
    assert board_widget._board_snapshot is None
    img_idle_after = render_widget_to_image(board_widget)

    diffs, _ = count_image_diffs(img_anim_end, img_idle_after)
    assert diffs == 0, f"Expected 0 diff pixels at animation end, got {diffs}"


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_zero_flicker_across_high_dpi_scales(board_widget, monkeypatch, dpr):
    """
    Verify 0 pixel difference across integer and fractional High-DPI scaling factors.
    Guarantees no 1px edge strip or subpixel shifting on Windows 125%/150% scaling.
    """
    monkeypatch.setattr(board_widget, "devicePixelRatioF", lambda: dpr)

    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)

    board_widget.last_move = move
    img_idle = render_widget_to_image(board_widget, dpr=dpr)

    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    board_widget.animating_piece_data['progress'] = 0.0
    img_anim = render_widget_to_image(board_widget, dpr=dpr)

    diffs, _ = count_image_diffs(img_idle, img_anim)
    assert diffs == 0, f"DPR {dpr}: Expected 0 diff pixels, got {diffs}"
    board_widget.abort_piece_slide()


def test_capture_transition_contained_to_target_square(board_widget):
    """
    Verify that during a capture, any pixel differences between progress 1.0 and post-push
    are strictly confined to the destination square (d5). No static square, coordinate, or piece
    anywhere else on the board flickers or shifts.
    """
    board_widget.board.set_fen("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    move = chess.Move.from_uci("e4d5")
    piece = board_widget.board.piece_at(chess.E4)

    board_widget.start_piece_slide(piece, chess.E4, chess.D5, move)
    board_widget.animating_piece_data['progress'] = 1.0
    img_anim_1 = render_widget_to_image(board_widget)

    board_widget._on_animation_finished()
    img_after = render_widget_to_image(board_widget)

    diffs, diff_coords = count_image_diffs(img_anim_1, img_after)

    # Calculate bounding box of the d5 square in device pixels
    dpr = board_widget.devicePixelRatioF()
    side, sq_size, x_off, y_off = board_widget.get_metrics()
    # d5 is col 3, row 3 (from top: 7 - rank 4)
    d5_x_min = round((x_off + 3.0 * sq_size) * dpr) - 2
    d5_x_max = round((x_off + 4.0 * sq_size) * dpr) + 2
    d5_y_min = round((y_off + 3.0 * sq_size) * dpr) - 2
    d5_y_max = round((y_off + 4.0 * sq_size) * dpr) + 2

    for x, y in diff_coords:
        assert d5_x_min <= x <= d5_x_max and d5_y_min <= y <= d5_y_max, (
            f"Diff pixel at ({x}, {y}) is outside target square d5 [{d5_x_min}-{d5_x_max}, {d5_y_min}-{d5_y_max}]"
        )


def test_multi_move_sequence_seamless_transitions(board_widget):
    """
    Verify that a sequence of consecutive moves (1. e4 e5 2. Nf3) invalidates and rebuilds
    snapshots correctly without leaving ghost pieces or stale highlights.
    """
    moves = ["e2e4", "e7e5", "g1f3"]

    for uci in moves:
        move = chess.Move.from_uci(uci)
        piece = board_widget.board.piece_at(move.from_square)

        # 1. Start slide
        board_widget.start_piece_slide(piece, move.from_square, move.to_square, move)
        assert board_widget.is_animating is True
        assert board_widget._board_snapshot is not None

        # 2. Verify snapshot skips moving piece
        assert board_widget.animating_piece_data['from_square'] == move.from_square

        # 3. Finish slide
        board_widget._on_animation_finished()
        assert board_widget.is_animating is False
        assert board_widget._board_snapshot is None
        assert board_widget.board.piece_at(move.to_square) == piece

    # Verify final board FEN matches expected position
    assert board_widget.board.piece_at(chess.E4) == chess.Piece(chess.PAWN, chess.WHITE)
    assert board_widget.board.piece_at(chess.E5) == chess.Piece(chess.PAWN, chess.BLACK)
    assert board_widget.board.piece_at(chess.F3) == chess.Piece(chess.KNIGHT, chess.WHITE)


def test_snapshot_invalidation_triggers(board_widget):
    """Verify that all state-mutating actions properly invalidate the cached board snapshot."""
    move = chess.Move.from_uci("e2e4")
    piece = board_widget.board.piece_at(chess.E2)

    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget._board_snapshot is not None

    # Theme change
    board_widget.set_theme("Grün")
    assert board_widget._board_snapshot is None

    # Highlight color change
    board_widget._board_snapshot = board_widget._build_board_snapshot()
    assert board_widget._board_snapshot is not None
    board_widget.set_highlight_color("Blau")
    assert board_widget._board_snapshot is None

    # Annotations / Arrows
    board_widget._board_snapshot = board_widget._build_board_snapshot()
    board_widget.add_user_arrow(chess.E2, chess.E4)
    assert board_widget._board_snapshot is None

    # FEN change
    board_widget._board_snapshot = board_widget._build_board_snapshot()
    board_widget.set_fen(chess.STARTING_FEN)
    assert board_widget._board_snapshot is None

    # Abort
    board_widget.start_piece_slide(piece, chess.E2, chess.E4, move)
    assert board_widget._board_snapshot is not None
    board_widget.abort_piece_slide()
    assert board_widget._board_snapshot is None


def test_zero_board_tremble_in_parent_window_subpixel_offsets(qapp):
    """
    Verify that when ChessBoardWidget is embedded inside a parent QMainWindow at arbitrary
    logical coordinates (producing fractional physical pixel offsets like 12.5px or 63.75px at 1.25x DPI)
    and odd/non-square dimensions (e.g. 848x877), transitioning between idle and animating states
    via real Qt window backing-store rendering (win.grab()) produces 0 differing pixels across the board.
    This directly prevents the 1-pixel vertical/horizontal board tremble at animation start and end.
    """
    from PyQt6.QtWidgets import QMainWindow, QWidget

    win = QMainWindow()
    win.resize(1000, 950)
    container = QWidget(win)
    win.setCentralWidget(container)
    bw = ChessBoardWidget(parent=container)
    win.show()
    QApplication.processEvents()

    move = chess.Move.from_uci("e2e4")
    piece = bw.board.piece_at(chess.E2)

    # Test combinations of child widget positions (0..3 -> 0.0, 0.25, 0.5, 0.75 physical sub-pixel phases at 1.25x DPI)
    # and odd/even heights (754, 755)
    for x_pos, y_pos, w_val, h_val in [
        (10, 0, 754, 754),
        (10, 1, 754, 755),
        (10, 2, 755, 754),
        (10, 3, 755, 755),
    ]:
        bw.setGeometry(x_pos, y_pos, w_val, h_val)
        QApplication.processEvents()

        # 1. Capture real parent window backing store in IDLE state (just before slide)
        bw.last_move = move
        bw.is_animating = False
        bw.update()
        QApplication.processEvents()
        img_idle = win.grab().toImage()

        # 2. Capture real parent window backing store at ANIMATION START (progress = 0.0)
        bw.start_piece_slide(piece, chess.E2, chess.E4, move)
        bw.animating_piece_data["progress"] = 0.0
        bw.precise_anim_timer.stop()
        bw.update()
        QApplication.processEvents()
        img_anim = win.grab().toImage()
        bw.abort_piece_slide()

        diffs, coords = count_image_diffs(img_idle, img_anim, tolerance=3)
        assert diffs == 0, (
            f"Board trembled/shifted at geometry ({x_pos}, {y_pos}, {w_val}, {h_val}): "
            f"{diffs} pixels differed! Sample coords: {coords[:10]}"
        )

    win.close()

