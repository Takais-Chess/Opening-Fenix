import json
import os
import sqlite3
import zipfile
from unittest.mock import MagicMock

import chess
import pytest
from PyQt6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.models import LichessData, Metadata, Move, Position, RepertoireLevel, RepertoireMove
from opening_fenix.core.services.backup_service import (
    export_portable_backup_zip,
    import_repertoire_from_external_zip,
    validate_backup_zip,
)
from opening_fenix.core.services.course_import_service import (
    extract_pgns_from_zip,
    is_repertoire_backup_zip,
)
from opening_fenix.core.services.hole_finder_service import (
    find_repertoire_holes,
    find_unanswered_moves,
    get_lichess_data_coverage,
)
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir
from opening_fenix.creator.creator_window import CreatorBackend, CreatorWindow
from opening_fenix.gui.dialogs.course_import_dialog import CourseImportDialog
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget
from opening_fenix.gui.widgets.common import extract_dropped_files


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _clean_fen(fen: str) -> str:
    return " ".join(fen.strip().split()[:4])


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


# ─── 1. Click Anywhere on Chessboard to Start Training ──────────────────────


def test_board_click_to_start_emits_and_skips_selection(qapp):
    bw = ChessBoardWidget()
    bw.resize(480, 480)
    clicks = []
    moves = []
    bw.board_clicked.connect(lambda: clicks.append(True))
    bw.move_executed.connect(moves.append)

    # Disabled by default -> normal click selects e2 without emitting board_clicked
    _, sq_size, x_off, y_off = bw.get_metrics()
    e2_pos = QPointF(x_off + 4.5 * sq_size, y_off + 6.5 * sq_size)
    empty_pos = QPointF(x_off + 0.5 * sq_size, y_off + 3.5 * sq_size)
    margin_pos = QPointF(4.0, 4.0)

    _mouse_press(bw, e2_pos)
    _mouse_release(bw, e2_pos)
    assert clicks == []
    assert bw.selected_square == chess.E2

    # Enable click-to-start -> clicking a piece, an empty square, or board margin emits board_clicked
    bw.set_click_to_start_enabled(True)
    assert bw.cursor().shape() == Qt.CursorShape.PointingHandCursor

    for pos in (e2_pos, empty_pos, margin_pos):
        _mouse_press(bw, pos)
        _mouse_release(bw, pos)

    assert len(clicks) == 3
    assert bw.selected_square is None
    assert bw.dragging_piece is None
    assert moves == []

    # When animating, clicking skips animation instead of emitting board_clicked
    bw.is_animating = True
    bw.animating_piece_data = {"move": chess.Move.from_uci("e2e4")}
    _mouse_press(bw, empty_pos)
    assert len(clicks) == 3

    bw.set_click_to_start_enabled(False)
    assert bw.cursor().shape() == Qt.CursorShape.ArrowCursor


# ─── 2. Creator Back-Button Return-Move Marking ───────────────────────────────


def _build_branching_repo(user_dir: str, repo_name: str, is_test: bool = True):
    db_path = get_repertoire_db_path(repo_name, is_test=is_test)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    dbm = DatabaseManager(db_path)
    sess = dbm.get_session()
    try:
        sess.add(Metadata(key="color", value="w"))
        sess.add(RepertoireLevel(order=1, name="Level 1"))

        b0 = chess.Board()
        b_e4 = chess.Board()
        b_e4.push_san("e4")
        b_d4 = chess.Board()
        b_d4.push_san("d4")
        b_e5 = b_e4.copy()
        b_e5.push_san("e5")

        p0 = Position(fen=_clean_fen(b0.fen()))
        p_e4 = Position(fen=_clean_fen(b_e4.fen()), variation_1="King Pawn")
        p_d4 = Position(fen=_clean_fen(b_d4.fen()), variation_1="Queen Pawn")
        p_e5 = Position(fen=_clean_fen(b_e5.fen()), variation_1="King Pawn")
        sess.add_all([p0, p_e4, p_d4, p_e5])
        sess.flush()

        m_e4 = Move(from_position_id=p0.id, to_position_id=p_e4.id, uci="e2e4", san="e4", priority_score=0.40)
        m_d4 = Move(from_position_id=p0.id, to_position_id=p_d4.id, uci="d2d4", san="d4", priority_score=0.60)
        m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5", priority_score=0.50)
        sess.add_all([m_e4, m_d4, m_e5])
        sess.flush()

        sess.add_all([
            RepertoireMove(move_id=m_e4.id, level=1, is_active=True),
            RepertoireMove(move_id=m_d4.id, level=1, is_active=True),
            RepertoireMove(move_id=m_e5.id, level=1, is_active=True),
        ])
        sess.commit()
    finally:
        sess.close()
        dbm.close()


def test_creator_back_navigation_marks_return_move(qapp, mock_user_dir, monkeypatch):
    repo_name = "NavBackTest"
    _build_branching_repo(mock_user_dir, repo_name)

    monkeypatch.setattr("opening_fenix.creator.creator_window.EngineThread", MagicMock())
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.check_for_updates", lambda self: None)
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.trigger_lichess_lockout_check", lambda self, manual=False: None)
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.check_for_creator_onboarding", lambda self: None)

    win = CreatorWindow(repertoire_name=repo_name, is_test=True)
    try:
        # 1. Navigate to position after 1. e4 (whose parent has d4 sorted at row 0 and e4 at row 1)
        b_e4 = chess.Board()
        b_e4.push_san("e4")
        win.set_board_to_fen(b_e4.fen())
        assert win.tree_widget.topLevelItemCount() == 1  # only e5

        # Click Back button -> returns to start and MUST highlight e4 (not d4!)
        win.on_back_button_clicked()
        cur = win.tree_widget.currentItem()
        assert cur is not None
        assert cur.data(0, Qt.ItemDataRole.UserRole) == "e2e4"
        assert cur.isSelected() is True
        assert win._pending_back_select_uci is None

        # 2. Multi-parent / go_back() fallback (e.g. pressing Left arrow from 1. e4 e5)
        b_e5 = b_e4.copy()
        b_e5.push_san("e5")
        win.set_board_to_fen(b_e5.fen())
        win.go_back()
        cur2 = win.tree_widget.currentItem()
        assert cur2 is not None
        assert cur2.data(0, Qt.ItemDataRole.UserRole) == "e7e5"
        assert cur2.isSelected() is True
    finally:
        win.close()
        DatabaseManager.close_all_for_directory(mock_user_dir)


# ─── 3. Hole Finder Data Coverage Warning & Filters ─────────────────────────


def _setup_varied_repo_for_holes(user_dir: str, repo_name: str):
    db_path = get_repertoire_db_path(repo_name)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    dbm = DatabaseManager(db_path)
    sess = dbm.get_session()
    try:
        sess.add(Metadata(key="color", value="w"))
        sess.add(RepertoireLevel(order=1, name="Level 1"))

        b0 = chess.Board()
        b_e4 = chess.Board(); b_e4.push_san("e4")
        b_e5 = b_e4.copy(); b_e5.push_san("e5")
        b_nf3 = b_e5.copy(); b_nf3.push_san("Nf3")       # ply 3 (Italian branch)
        b_c5 = b_e4.copy(); b_c5.push_san("c5")          # ply 2 (Sicilian branch)
        b_nf3_s = b_c5.copy(); b_nf3_s.push_san("Nf3")   # ply 3 (Sicilian branch)
        b_d6 = b_nf3_s.copy(); b_d6.push_san("d6")       # ply 4 (Sicilian branch, unanswered for White)
        b_d5 = b_e4.copy(); b_d5.push_san("d5")          # ply 2 (Scandinavian branch, unanswered for White)

        p0 = Position(fen=_clean_fen(b0.fen()))
        p_e4 = Position(fen=_clean_fen(b_e4.fen()))
        p_e5 = Position(fen=_clean_fen(b_e5.fen()), variation_1="Italian", cached_v1="Italian")
        p_nf3 = Position(fen=_clean_fen(b_nf3.fen()), variation_1="Italian", cached_v1="Italian")
        p_c5 = Position(fen=_clean_fen(b_c5.fen()), variation_1="Sicilian", cached_v1="Sicilian")
        p_nf3_s = Position(fen=_clean_fen(b_nf3_s.fen()), variation_1="Sicilian", cached_v1="Sicilian")
        p_d6 = Position(fen=_clean_fen(b_d6.fen()), variation_1="Sicilian", cached_v1="Sicilian")
        p_d5 = Position(fen=_clean_fen(b_d5.fen()), variation_1="Scandinavian", cached_v1="Scandinavian")

        sess.add_all([p0, p_e4, p_e5, p_nf3, p_c5, p_nf3_s, p_d6, p_d5])
        sess.flush()

        moves = [
            Move(from_position_id=p0.id, to_position_id=p_e4.id, uci="e2e4", san="e4"),
            Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5"),
            Move(from_position_id=p_e5.id, to_position_id=p_nf3.id, uci="g1f3", san="Nf3"),
            Move(from_position_id=p_e4.id, to_position_id=p_c5.id, uci="c7c5", san="c5"),
            Move(from_position_id=p_c5.id, to_position_id=p_nf3_s.id, uci="g1f3", san="Nf3"),
            Move(from_position_id=p_nf3_s.id, to_position_id=p_d6.id, uci="d7d6", san="d6"),
            Move(from_position_id=p_e4.id, to_position_id=p_d5.id, uci="d7d5", san="d5"),
        ]
        sess.add_all(moves)
        sess.flush()
        for m in moves:
            sess.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
        sess.commit()

        fens = {
            "start": _clean_fen(b0.fen()),
            "e4": _clean_fen(b_e4.fen()),
            "nf3": _clean_fen(b_nf3.fen()),
            "nf3_s": _clean_fen(b_nf3_s.fen()),
            "d6": _clean_fen(b_d6.fen()),
        }
        return dbm, fens
    except Exception:
        sess.close()
        dbm.close()
        raise


def test_hole_finder_coverage_warning_and_filters(mock_user_dir):
    repo_name = "HoleFilterRepo"
    dbm, fens = _setup_varied_repo_for_holes(mock_user_dir, repo_name)
    sess = dbm.get_session()
    try:
        # 1. Zero Lichess data -> 0% coverage
        cov0 = get_lichess_data_coverage(sess, elo_range="high")
        assert cov0["total_positions"] == 8
        assert cov0["covered_positions"] == 0
        assert cov0["coverage_pct"] == 0.0
        assert cov0["has_requested_elo"] is False

        # 2. Add Lichess data only at 'mid' for 2 positions -> fallback & partial coverage
        sess.add_all([
            LichessData(fen=fens["e4"], elo_range="mid", moves_json=json.dumps({
                "e7e5": {"san": "e5", "total": 500},
                "c7c5": {"san": "c5", "total": 500},
            })),
            LichessData(fen=fens["nf3"], elo_range="mid", moves_json=json.dumps({
                "b8c6": {"san": "Nc6", "total": 900},
            })),
        ])
        sess.commit()
        cov_fb = get_lichess_data_coverage(sess, elo_range="high")
        assert cov_fb["has_requested_elo"] is False
        assert cov_fb["effective_elo"] == "mid"
        assert cov_fb["covered_positions"] == 2
        assert cov_fb["coverage_pct"] < 50.0

        # 3. Add high-elo data for e4, nf3 (ply 3 -> hole ply 4: Nc6), nf3_s (ply 3 -> hole ply 4: Nc6_s / e6)
        sess.add_all([
            LichessData(fen=fens["e4"], elo_range="high", moves_json=json.dumps({
                "e7e5": {"san": "e5", "total": 500},
                "c7c5": {"san": "c5", "total": 400},
                "e7e6": {"san": "e6", "total": 100},  # ply 2 hole (root->e4->e6)
            })),
            LichessData(fen=fens["nf3"], elo_range="high", moves_json=json.dumps({
                "b8c6": {"san": "Nc6", "total": 900},  # ply 4 hole in Italian
            })),
            LichessData(fen=fens["nf3_s"], elo_range="high", moves_json=json.dumps({
                "d7d6": {"san": "d6", "total": 600},
                "e7e6": {"san": "e6", "total": 400},   # ply 4 hole in Sicilian
            })),
        ])
        sess.commit()

        # Unfiltered finds holes at ply 2 (e6 after e4) AND ply 4 (Nc6 in Italian, e6 in Sicilian)
        all_holes = find_repertoire_holes(sess, 1.0, "high", include_user_gaps=False)
        sans_all = {(h["move_san"], h["ply_depth"]) for h in all_holes}
        assert ("e6", 1) in sans_all
        assert ("Nc6", 3) in sans_all
        assert ("e6", 3) in sans_all

        # Max ply = 2 excludes ply 4 holes (d=3 -> move ply 4 > 2) while keeping ply 2 hole (d=1 -> move ply 2 <= 2)
        shallow_holes = find_repertoire_holes(sess, 1.0, "high", include_user_gaps=False, max_ply=2)
        assert {h["move_san"] for h in shallow_holes} == {"e6"}

        # Variation filter = ("Italian", None) keeps reach_probs intact and returns ONLY Italian holes
        italian_holes = find_repertoire_holes(
            sess, 1.0, "high", include_user_gaps=False, variation_filter=("Italian", None)
        )
        assert len(italian_holes) == 1
        assert italian_holes[0]["move_san"] == "Nc6"

        # Unanswered moves: p_d5 is at d=2 (Scandinavian), p_d6 is at d=4 (Sicilian)
        unanswered_all = find_unanswered_moves(sess)
        assert len(unanswered_all) == 2

        unanswered_sicilian = find_unanswered_moves(sess, variation_filter=("Sicilian", None))
        assert len(unanswered_sicilian) == 1
        assert unanswered_sicilian[0]["last_move_san"] == "d6"

        unanswered_ply2 = find_unanswered_moves(sess, max_ply=2)
        assert len(unanswered_ply2) == 1
        assert unanswered_ply2[0]["last_move_san"] == "d5"
    finally:
        sess.close()
        dbm.close()


# ─── 4. ZIP PGN Extraction, Portable Backup Export/Import & Drag-and-Drop ──


def test_extract_pgns_from_zip_and_zipslip_protection(tmp_path):
    good_zip = tmp_path / "course.zip"
    with zipfile.ZipFile(good_zip, "w") as zf:
        zf.writestr("chapters/ch1.pgn", '[Event "Ch1"]\n1. e4 e5 *\n')
        zf.writestr("ch2.PGN", '[Event "Ch2"]\n1. d4 d5 *\n')
        zf.writestr("__MACOSX/chapters/._ch1.pgn", "junk")
        zf.writestr("._ch2.pgn", "junk")
        zf.writestr("readme.txt", "ignore me")

    assert is_repertoire_backup_zip(str(good_zip)) is False

    out_dir = tmp_path / "extracted"
    extracted = extract_pgns_from_zip(str(good_zip), str(out_dir))
    assert len(extracted) == 2
    assert all(p.lower().endswith(".pgn") for p in extracted)
    assert not any("__MACOSX" in p or os.path.basename(p).startswith("._") for p in extracted)

    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../../outside.pgn", "1. e4 *")

    with pytest.raises(ValueError, match="Unsafe path"):
        extract_pgns_from_zip(str(evil_zip), str(tmp_path / "out_evil"))


def test_portable_backup_export_validate_and_external_import(tmp_path, monkeypatch):
    user_dir = tmp_path / "user_data"
    user_dir.mkdir()
    monkeypatch.setattr("opening_fenix.core.services.backup_service.get_user_dir", lambda: str(user_dir))
    monkeypatch.setattr("opening_fenix.core.services.backup_service.get_custom_data_dir", lambda: None)
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(user_dir))
    monkeypatch.setattr("opening_fenix.core.utils.get_custom_data_dir", lambda: None)

    src_repo = "SourceCourse"
    src_dir = get_repertoire_dir(src_repo)
    os.makedirs(os.path.join(src_dir, "model_games"), exist_ok=True)
    with open(os.path.join(src_dir, "model_games", "gm.pgn"), "w", encoding="utf-8") as f:
        f.write('[Event "GM Game"]\n1. e4 e5 *\n')

    src_db = get_repertoire_db_path(src_repo)
    dbm = DatabaseManager(src_db)
    sess = dbm.get_session()
    try:
        sess.add(Metadata(key="color", value="w"))
        sess.add(RepertoireLevel(order=1, name="Level 1"))
        p0 = Position(fen=_clean_fen(chess.STARTING_FEN), comment=json.dumps({"en": "Start note"}))
        b = chess.Board(); b.push_san("e4")
        p1 = Position(fen=_clean_fen(b.fen()))
        sess.add_all([p0, p1])
        sess.flush()
        mv = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
        sess.add(mv)
        sess.flush()
        sess.add(RepertoireMove(move_id=mv.id, level=1, is_active=True))
        sess.commit()
    finally:
        sess.close()
        dbm.close()

    portable_zip = tmp_path / "portable_export.zip"
    assert export_portable_backup_zip(src_repo, str(portable_zip)) is True
    assert portable_zip.exists()
    assert is_repertoire_backup_zip(str(portable_zip)) is True

    ok_val, err_val, info = validate_backup_zip(str(portable_zip))
    assert ok_val is True
    assert err_val == ""
    assert info["repertoire_name"] == src_repo
    assert info["total_moves"] == 1
    assert info["en_comments"] == 1

    # Import into a brand new repertoire name
    ok_new, err_new = import_repertoire_from_external_zip(str(portable_zip), "ImportedCopy", overwrite=False)
    assert ok_new is True
    assert err_new == ""
    assert os.path.exists(get_repertoire_db_path("ImportedCopy"))
    assert os.path.exists(os.path.join(get_repertoire_dir("ImportedCopy"), "model_games", "gm.pgn"))

    # Importing again without overwrite must refuse cleanly
    ok_dup, err_dup = import_repertoire_from_external_zip(str(portable_zip), "ImportedCopy", overwrite=False)
    assert ok_dup is False
    assert err_dup == "exists"

    # Overwriting should succeed and preserve valid DB
    ok_ovr, err_ovr = import_repertoire_from_external_zip(str(portable_zip), "ImportedCopy", overwrite=True)
    assert ok_ovr is True
    assert err_ovr == ""

    # Invalid ZIP rejected cleanly
    bad_zip = tmp_path / "not_a_backup.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("random.txt", "hello")
    ok_bad, err_bad, _ = validate_backup_zip(str(bad_zip))
    assert ok_bad is False
    assert err_bad != ""

    DatabaseManager.close_all_for_directory(str(user_dir))


def test_drag_and_drop_mime_filter_and_course_import_zip(qapp, tmp_path):
    pgn_file = tmp_path / "line.pgn"
    pgn_file.write_text('[Event "Test Line"]\n[White "1. e4 e5"]\n[Black "Intro"]\n1. e4 e5 *\n', encoding="utf-8")
    zip_file = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.write(pgn_file, arcname="line.pgn")
    ignored_file = tmp_path / "notes.txt"
    ignored_file.write_text("ignore", encoding="utf-8")

    mime = QMimeData()
    mime.setUrls([
        QUrl.fromLocalFile(str(pgn_file)),
        QUrl.fromLocalFile(str(zip_file)),
        QUrl.fromLocalFile(str(ignored_file)),
    ])
    dropped = extract_dropped_files(mime, (".pgn", ".zip"))
    assert dropped == [str(pgn_file), str(zip_file)]

    dlg = CourseImportDialog()
    assert dlg.acceptDrops() is True
    dlg.load_files([str(zip_file)], sync=True)
    assert len(dlg.selected_paths) == 1
    assert dlg.selected_paths[0].lower().endswith(".pgn")
    assert len(dlg._temp_zip_dirs) == 1
    tmp_dir_created = dlg._temp_zip_dirs[0]
    assert os.path.isdir(tmp_dir_created)

    dlg.close()
    assert not os.path.exists(tmp_dir_created)


def test_creator_back_menu_highlights_incoming_transposition_move(qapp, mock_user_dir, monkeypatch):
    from opening_fenix.core.translation import translator

    repo_name = "TransposMenuTest"
    db_path = get_repertoire_db_path(repo_name, is_test=True)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    dbm = DatabaseManager(db_path)
    sess = dbm.get_session()
    try:
        sess.add(Metadata(key="color", value="w"))
        sess.add(RepertoireLevel(order=1, name="Level 1"))

        # Order A: 1. d4 d5 2. Nc3 Nf6
        b0 = chess.Board()
        b_d4 = chess.Board(); b_d4.push_san("d4")
        b_d5 = b_d4.copy(); b_d5.push_san("d5")
        b_d5_nc3 = b_d5.copy(); b_d5_nc3.push_san("Nc3")
        b_end = b_d5_nc3.copy(); b_end.push_san("Nf6")

        # Order B: 1. d4 Nf6 2. Nc3 d5 -> same b_end!
        b_nf6 = b_d4.copy(); b_nf6.push_san("Nf6")
        b_nf6_nc3 = b_nf6.copy(); b_nf6_nc3.push_san("Nc3")

        p0 = Position(fen=_clean_fen(b0.fen()))
        p_d4 = Position(fen=_clean_fen(b_d4.fen()))
        p_d5 = Position(fen=_clean_fen(b_d5.fen()))
        p_d5_nc3 = Position(fen=_clean_fen(b_d5_nc3.fen()))
        p_nf6 = Position(fen=_clean_fen(b_nf6.fen()))
        p_nf6_nc3 = Position(fen=_clean_fen(b_nf6_nc3.fen()))
        p_end = Position(fen=_clean_fen(b_end.fen()))
        sess.add_all([p0, p_d4, p_d5, p_d5_nc3, p_nf6, p_nf6_nc3, p_end])
        sess.flush()

        moves = [
            Move(from_position_id=p0.id, to_position_id=p_d4.id, uci="d2d4", san="d4"),
            Move(from_position_id=p_d4.id, to_position_id=p_d5.id, uci="d7d5", san="d5"),
            Move(from_position_id=p_d5.id, to_position_id=p_d5_nc3.id, uci="b1c3", san="Nc3"),
            Move(from_position_id=p_d5_nc3.id, to_position_id=p_end.id, uci="g8f6", san="Nf6"),
            Move(from_position_id=p_d4.id, to_position_id=p_nf6.id, uci="g8f6", san="Nf6"),
            Move(from_position_id=p_nf6.id, to_position_id=p_nf6_nc3.id, uci="b1c3", san="Nc3"),
            Move(from_position_id=p_nf6_nc3.id, to_position_id=p_end.id, uci="d7d5", san="d5"),
        ]
        sess.add_all(moves)
        sess.flush()
        for m in moves:
            sess.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
        sess.commit()
    finally:
        sess.close()
        dbm.close()

    monkeypatch.setattr("opening_fenix.creator.creator_window.EngineThread", MagicMock())
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.check_for_updates", lambda self: None)
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.trigger_lichess_lockout_check", lambda self, manual=False: None)
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorWindow.check_for_creator_onboarding", lambda self: None)

    prev_lang = translator.current_lang
    win = CreatorWindow(repertoire_name=repo_name, is_test=True)
    try:
        translator.load_language("en")
        win.config["notation_language"] = "en"

        # Play 1. d4 d5 2. Nc3 Nf6 onto the board
        win.board_widget.board = b_end.copy(stack=True)
        win.update_ui_from_fen()

        parents = win.backend.get_parent_moves_for_fen(win.board_widget.board.fen())
        assert {p["move_san"] for p in parents} == {"d5", "Nf6"}

        # Force reverse order to ensure active incoming move (Nf6) is still placed first
        reversed_parents = sorted(parents, key=lambda p: 0 if p["move_san"] == "d5" else 1)
        menu = win._build_back_parents_menu(reversed_parents)
        actions = menu.actions()
        assert len(actions) == 2

        assert actions[0].data() == "current"
        assert "✓" in actions[0].text()
        assert "Nf6" in actions[0].text()
        assert "current" in actions[0].text().lower()
        assert actions[0].font().bold() is True
        assert menu.defaultAction() == actions[0]

        assert "✓" not in actions[1].text()
        assert "Move from: d5" in actions[1].text()
        assert actions[1].font().bold() is False

        # Triggering the active incoming move pops Nf6 and highlights g8f6 in Candidate Moves
        actions[0].trigger()
        assert _clean_fen(win.board_widget.board.fen()) == _clean_fen(b_d5_nc3.fen())
        cur = win.tree_widget.currentItem()
        assert cur is not None
        assert cur.data(0, Qt.ItemDataRole.UserRole) == "g8f6"
        assert cur.isSelected() is True
    finally:
        translator.load_language(prev_lang)
        win.close()
        DatabaseManager.close_all_for_directory(mock_user_dir)
