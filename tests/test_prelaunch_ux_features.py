import datetime
import json
import os
import zipfile
from unittest.mock import MagicMock, patch

import chess
import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from opening_fenix.core.db.models import Base, Move, Position, RepertoireLevel, TrainingData, UserBase
from opening_fenix.core.services.repertoire_service import RepertoireManager
from opening_fenix.core.services.training_service import TrainingManager
from opening_fenix.gui.dialogs.bug_report_dialog import (
    BUG_REPORT_ENDPOINT,
    BugReportDialog,
    export_diagnostics_zip,
    sanitize_config_for_diagnostics,
    sanitize_log_text,
    submit_bug_report,
)
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, PromotionPickerPopup
from opening_fenix.gui.widgets.title_bar import CustomTitleBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _square_center_pos(board_widget: ChessBoardWidget, sq: int) -> QPointF:
    _, square_size, x_offset, y_offset = board_widget.get_metrics()
    f = chess.square_file(sq)
    r = chess.square_rank(sq)
    col = 7 - f if board_widget.flipped else f
    row = r if board_widget.flipped else 7 - r
    return QPointF(x_offset + (col + 0.5) * square_size, y_offset + (row + 0.5) * square_size)


def _mouse_press(widget, pos: QPointF, button=Qt.MouseButton.LeftButton):
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        pos,
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(ev)


def _mouse_release(widget, pos: QPointF, button=Qt.MouseButton.LeftButton):
    ev = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        pos,
        pos,
        button,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(ev)


# ─── 1. Click-to-Move & Legal-Move Dots ─────────────────────────────────────


def test_click_to_move_select_and_execute(qapp):
    bw = ChessBoardWidget()
    bw.resize(480, 480)
    emitted = []
    bw.move_executed.connect(emitted.append)

    e2_pos = _square_center_pos(bw, chess.E2)
    e4_pos = _square_center_pos(bw, chess.E4)

    # Click e2 -> selects e2
    _mouse_press(bw, e2_pos)
    _mouse_release(bw, e2_pos)
    assert bw.selected_square == chess.E2
    assert emitted == []

    # Click e4 -> executes e2e4 and clears selection
    _mouse_press(bw, e4_pos)
    _mouse_release(bw, e4_pos)
    assert emitted == [chess.Move.from_uci("e2e4")]
    assert bw.selected_square is None


def test_click_to_move_toggle_switch_and_deselect(qapp):
    bw = ChessBoardWidget()
    bw.resize(480, 480)
    emitted = []
    bw.move_executed.connect(emitted.append)

    e2_pos = _square_center_pos(bw, chess.E2)
    d2_pos = _square_center_pos(bw, chess.D2)
    e5_pos = _square_center_pos(bw, chess.E5)

    # Select e2
    _mouse_press(bw, e2_pos)
    _mouse_release(bw, e2_pos)
    assert bw.selected_square == chess.E2

    # Clicking e2 again toggles selection off
    _mouse_press(bw, e2_pos)
    _mouse_release(bw, e2_pos)
    assert bw.selected_square is None

    # Select e2, then click d2 -> switches selection to d2
    _mouse_press(bw, e2_pos)
    _mouse_release(bw, e2_pos)
    _mouse_press(bw, d2_pos)
    _mouse_release(bw, d2_pos)
    assert bw.selected_square == chess.D2

    # Click illegal square e5 -> deselects without emitting a move
    _mouse_press(bw, e5_pos)
    _mouse_release(bw, e5_pos)
    assert bw.selected_square is None
    assert emitted == []


def test_drag_and_drop_still_works(qapp):
    bw = ChessBoardWidget()
    bw.resize(480, 480)
    emitted = []
    bw.move_executed.connect(emitted.append)

    e2_pos = _square_center_pos(bw, chess.E2)
    e4_pos = _square_center_pos(bw, chess.E4)

    _mouse_press(bw, e2_pos)
    _mouse_release(bw, e4_pos)
    assert emitted == [chess.Move.from_uci("e2e4")]
    assert bw.selected_square is None


def test_show_legal_moves_toggle_and_paint(qapp):
    bw = ChessBoardWidget()
    bw.resize(480, 480)
    assert bw.show_legal_moves is True

    bw.selected_square = chess.E2
    bw.grab()  # Renders paintEvent with legal move dots ON

    bw.set_show_legal_moves(False)
    assert bw.show_legal_moves is False
    bw.grab()  # Renders paintEvent with legal move dots OFF

    bw.set_show_legal_moves(True)
    assert bw.show_legal_moves is True


# ─── 2. Underpromotion Picker ───────────────────────────────────────────────


def test_underpromotion_picker_drag_and_click(qapp):
    bw = ChessBoardWidget()
    bw.resize(480, 480)
    bw.board.set_fen("8/P6k/8/8/8/8/8/4K3 w - - 0 1")
    emitted = []
    bw.move_executed.connect(emitted.append)

    a7_pos = _square_center_pos(bw, chess.A7)
    a8_pos = _square_center_pos(bw, chess.A8)

    # Drag a7 -> a8 opens promotion picker instead of auto-queening
    _mouse_press(bw, a7_pos)
    _mouse_release(bw, a8_pos)
    assert emitted == []
    assert isinstance(bw._promotion_popup, PromotionPickerPopup)

    # Choose Knight underpromotion
    bw._promotion_popup.piece_buttons[chess.KNIGHT].click()
    assert emitted == [chess.Move.from_uci("a7a8n")]

    # Click-to-move a7 -> a8 also opens promotion picker -> choose Rook
    emitted.clear()
    _mouse_press(bw, a7_pos)
    _mouse_release(bw, a7_pos)
    assert bw.selected_square == chess.A7
    _mouse_press(bw, a8_pos)
    # Popup opens cleanly on release rather than mid-press to avoid Win32 capture conflicts
    assert bw._promotion_popup is None
    _mouse_release(bw, a8_pos)
    assert isinstance(bw._promotion_popup, PromotionPickerPopup)
    bw._promotion_popup.piece_buttons[chess.ROOK].click()
    assert emitted == [chess.Move.from_uci("a7a8r")]


def test_underpromotion_picker_hover_tracking_and_mouse_pick(qapp):
    from PyQt6.QtCore import QEvent, QObject, QPointF
    from PyQt6.QtGui import QMouseEvent

    bw = ChessBoardWidget()
    bw.resize(480, 480)
    bw.board.set_fen("8/P6k/8/8/8/8/8/4K3 w - - 0 1")
    emitted = []
    bw.move_executed.connect(emitted.append)

    a7_pos = _square_center_pos(bw, chess.A7)
    a8_pos = _square_center_pos(bw, chess.A8)

    _mouse_press(bw, a7_pos)
    _mouse_release(bw, a8_pos)
    popup = bw._promotion_popup
    assert isinstance(popup, PromotionPickerPopup)
    assert popup.hasMouseTracking() is True
    assert popup.testAttribute(Qt.WidgetAttribute.WA_Hover) is True
    qapp.processEvents()

    def _move_popup(pt_f: QPointF):
        ev = QMouseEvent(
            QEvent.Type.MouseMove,
            pt_f,
            popup.mapToGlobal(pt_f.toPoint()).toPointF(),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        qapp.sendEvent(popup, ev)

    # Hover each piece sequentially: strictly one piece hovered at a time
    for pt in (chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP):
        center = popup.piece_buttons[pt].geometry().center().toPointF()
        _move_popup(center)
        hovered = [p for p, h in popup.piece_buttons.items() if h.underMouse()]
        assert hovered == [pt]

    # Moving within the same piece must not trigger extra repaints
    paint_count = [0]

    class _PaintCounter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Paint:
                paint_count[0] += 1
            return False

    counter = _PaintCounter()
    popup.installEventFilter(counter)
    qapp.processEvents()
    paint_count[0] = 0
    bishop_rect = popup.piece_buttons[chess.BISHOP].geometry()
    for dx in range(-8, 9, 2):
        _move_popup(QPointF(bishop_rect.center().x() + dx, bishop_rect.center().y()))
    qapp.processEvents()
    assert paint_count[0] == 0

    # Moving to the popup margin or outside clears hover immediately
    _move_popup(QPointF(0.0, 0.0))
    assert popup._hovered_index == -1
    _move_popup(QPointF(-20.0, -20.0))
    assert popup._hovered_index == -1

    # Press on Queen, drag off to Knight, release -> must NOT select
    q_center = popup.piece_buttons[chess.QUEEN].geometry().center().toPointF()
    n_center = popup.piece_buttons[chess.KNIGHT].geometry().center().toPointF()
    _mouse_press(popup, q_center)
    _mouse_release(popup, n_center)
    assert emitted == []

    # Press and release on Bishop -> emits a7a8b
    b_center = popup.piece_buttons[chess.BISHOP].geometry().center().toPointF()
    _mouse_press(popup, b_center)
    _mouse_release(popup, b_center)
    assert emitted == [chess.Move.from_uci("a7a8b")]


# ─── 3. Title-Bar Bug Report Button & Diagnostics Export ────────────────────


def test_title_bar_bug_report_button_presence(qapp):
    tb_default = CustomTitleBar(title="Test")
    assert tb_default.btn_bug_report is not None
    assert tb_default.btn_bug_report.objectName() == "BugReportTitleButton"
    assert tb_default.btn_bug_report.focusPolicy() == Qt.FocusPolicy.NoFocus

    tb_hidden = CustomTitleBar(title="Test", show_bug_report=False)
    assert tb_hidden.btn_bug_report is None


def test_diagnostics_sanitization_and_zip_export(qapp, tmp_path):
    raw_cfg = {
        "theme": "Braun (Klassisch)",
        "show_legal_moves": True,
        "lichess_api_token": "lip_SuperSecretToken123456",
        "nested": {"api_key": "my_secret_key", "safe_flag": 42},
    }
    safe = sanitize_config_for_diagnostics(raw_cfg)
    assert safe["theme"] == "Braun (Klassisch)"
    assert safe["show_legal_moves"] is True
    assert safe["lichess_api_token"] == "[REDACTED]"
    assert safe["nested"]["api_key"] == "[REDACTED]"
    assert safe["nested"]["safe_flag"] == 42

    scrubbed_log = sanitize_log_text(
        "INFO auth=Bearer abcdef123456789 token=lip_LiveSecret999999 ok"
    )
    assert "abcdef123456789" not in scrubbed_log
    assert "LiveSecret999999" not in scrubbed_log
    assert "[REDACTED]" in scrubbed_log

    # Write a fake app.log in tmp_path and export diagnostics ZIP
    fake_log = tmp_path / "app.log"
    fake_log.write_text("2026-11-25 INFO Startup lip_SecretTokenABC123\n", encoding="utf-8")
    out_zip = tmp_path / "diag.zip"

    with patch("opening_fenix.gui.dialogs.bug_report_dialog.get_user_dir", return_value=str(tmp_path)), \
         patch("opening_fenix.gui.dialogs.bug_report_dialog.get_config_dict", return_value=raw_cfg):
        export_diagnostics_zip(str(out_zip), user_description="Board froze after castle")

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip, "r") as zf:
        names = set(zf.namelist())
        assert {"system_info.json", "config_sanitized.json", "user_report.txt", "app_log_tail.txt"} <= names

        sys_info = json.loads(zf.read("system_info.json").decode("utf-8"))
        assert "app_version" in sys_info
        assert "os" in sys_info

        cfg_dump = zf.read("config_sanitized.json").decode("utf-8")
        assert "SuperSecretToken123456" not in cfg_dump
        assert "[REDACTED]" in cfg_dump

        log_dump = zf.read("app_log_tail.txt").decode("utf-8")
        assert "SecretTokenABC123" not in log_dump
        assert "lip_[REDACTED]" in log_dump

        report_txt = zf.read("user_report.txt").decode("utf-8")
        assert "Board froze after castle" in report_txt

    # Dialog constructs cleanly with 1-click send + fallback buttons
    dlg = BugReportDialog()
    assert dlg.btn_send is not None
    assert dlg.btn_export is not None
    assert dlg.btn_github is not None
    assert dlg.btn_discord is not None
    assert dlg.chk_include_diag.isChecked() is True
    dlg.close()


def test_submit_bug_report_worker_payload_and_errors(tmp_path):
    fake_log = tmp_path / "app.log"
    fake_log.write_text("INFO token=lip_ShouldNotLeak123\n", encoding="utf-8")
    raw_cfg = {"theme": "Grün", "lichess_api_token": "lip_ConfigSecret999"}

    mock_ok = MagicMock(status_code=200, ok=True)
    mock_ok.json.return_value = {"ok": True}

    with patch("opening_fenix.gui.dialogs.bug_report_dialog.get_user_dir", return_value=str(tmp_path)), \
         patch("opening_fenix.gui.dialogs.bug_report_dialog.get_config_dict", return_value=raw_cfg), \
         patch("opening_fenix.gui.dialogs.bug_report_dialog.requests.post", return_value=mock_ok) as post_mock:
        ok, err = submit_bug_report("Pawn disappeared on promotion", include_diagnostics=True)
        assert ok is True
        assert err == ""
        assert post_mock.call_count == 1
        call_args, call_kwargs = post_mock.call_args
        assert call_args[0] == BUG_REPORT_ENDPOINT
        assert call_kwargs["data"]["description"] == "Pawn disappeared on promotion"
        assert "file" in call_kwargs["files"]
        _fname, zip_bytes, mime = call_kwargs["files"]["file"]
        assert mime == "application/zip"
        assert b"ShouldNotLeak123" not in zip_bytes
        assert b"ConfigSecret999" not in zip_bytes

    mock_429 = MagicMock(status_code=429, ok=False)
    with patch("opening_fenix.gui.dialogs.bug_report_dialog.requests.post", return_value=mock_429):
        ok, err = submit_bug_report("Another report", include_diagnostics=False)
        assert ok is False
        assert err != ""


# ─── 4. Mouse-Slip Undo (SRS Snapshot & Restore) ────────────────────────────


def _setup_training_env(tmp_path):
    repo_db = str(tmp_path / "test_repo.db")
    user_db = str(tmp_path / "test_user.db")

    repo_engine = create_engine(f"sqlite:///{repo_db}")
    user_engine = create_engine(f"sqlite:///{user_db}")
    Base.metadata.create_all(repo_engine)
    UserBase.metadata.create_all(user_engine)
    repo_session = sessionmaker(bind=repo_engine)()
    user_session = sessionmaker(bind=user_engine)()

    lvl = RepertoireLevel(name="Level 1", order=1)
    repo_session.add(lvl)
    repo_session.flush()

    pos_start = Position(fen=chess.STARTING_FEN)
    board = chess.Board()
    board.push_uci("e2e4")
    pos_e4 = Position(fen=board.fen())
    repo_session.add_all([pos_start, pos_e4])
    repo_session.flush()

    mv = Move(
        from_position_id=pos_start.id,
        to_position_id=pos_e4.id,
        uci="e2e4",
        san="e4",
    )
    repo_session.add(mv)
    repo_session.commit()

    rm = MagicMock()
    rm.session = repo_session
    rm.repo_session = repo_session
    rm.active_repertoire_name = "TestRepo"

    tm = TrainingManager.__new__(TrainingManager)
    tm.repertoire_manager = rm
    tm.user_session = user_session
    tm.profile_name = "TestUser"
    tm._td_cache = None
    tm._norm_td_cache = None
    tm._pos_cache = None
    tm._move_by_id_cache = None
    tm._forward_moves_cache = None
    tm._move_by_fen_uci_cache = None
    tm._rep_move_cache = None
    tm._moves_by_level = None
    tm._cached_elo = None
    tm._last_stats_cache = None
    tm._has_pending_commit = False
    tm._settings_dirty = False
    tm.settings_cache = {}
    tm.get_setting = lambda k, default=None: tm.settings_cache.get(k, default)
    tm.save_settings = lambda: None
    tm.update_rating = lambda *a, **kw: None
    tm._get_rating_settings = lambda: None
    tm.record_new_card_trained = lambda **kw: None

    return tm, user_session, mv


def test_mouse_slip_undo_restores_existing_box(tmp_path):
    tm, user_session, mv = _setup_training_env(tmp_path)

    prev_due = datetime.datetime(2026, 12, 10, 12, 0, 0)
    prev_review = datetime.datetime(2026, 11, 20, 10, 0, 0)
    td = TrainingData(
        repertoire_name="TestRepo",
        fen=chess.STARTING_FEN,
        move_uci="e2e4",
        box=5,
        streak=4,
        next_due=prev_due,
        last_review=prev_review,
    )
    user_session.add(td)
    user_session.commit()

    snap = tm.capture_move_snapshot(mv.id)
    assert snap["existed"] is True
    assert snap["box"] == 5
    assert snap["streak"] == 4

    # Simulate mistake -> drops to Box 1, streak 0
    tm.register_success(mv.id, False, defer_commit=False)
    td_after_fail = user_session.query(TrainingData).filter_by(move_uci="e2e4").first()
    assert td_after_fail.box == 1
    assert td_after_fail.streak == 0

    # Undo mouse-slip -> restores Box 5, streak 4, exact next_due & last_review
    assert tm.restore_move_snapshot(snap, defer_commit=False) is True
    td_restored = user_session.query(TrainingData).filter_by(move_uci="e2e4").first()
    assert td_restored.box == 5
    assert td_restored.streak == 4
    assert td_restored.next_due == prev_due
    assert td_restored.last_review == prev_review


def test_mouse_slip_undo_removes_brand_new_entry(tmp_path):
    tm, user_session, mv = _setup_training_env(tmp_path)

    assert tm.is_move_new(mv.id) is True
    snap = tm.capture_move_snapshot(mv.id)
    assert snap["existed"] is False

    # Mistake creates a Box 1 TrainingData row
    tm.register_success(mv.id, False, defer_commit=False)
    assert user_session.query(TrainingData).filter_by(move_uci="e2e4").count() == 1
    assert tm.is_move_new(mv.id) is False

    # Undo mouse-slip deletes the newly created row and restores "new" status
    assert tm.restore_move_snapshot(snap, defer_commit=False) is True
    assert user_session.query(TrainingData).filter_by(move_uci="e2e4").count() == 0
    assert tm.is_move_new(mv.id) is True
