import chess
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
from PyQt6 import sip

from opening_fenix.core.db.models import Position, Move, TrainingData
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    win = MainWindow("TestUser")
    yield win
    win.close()
    if not sip.isdeleted(win):
        win.deleteLater()
    qapp.processEvents()


def _make_history():
    b = chess.Board()
    moves = ["e4", "e5", "Nf3", "Nc6", "Bb5"]
    history = []
    for san in moves:
        m = b.parse_san(san)
        b.push(m)
        history.append({"san": san, "uci": m.uci(), "fen": b.fen()})
    return history


def test_leadup_default_settings(training_manager):
    assert training_manager.get_setting("leadup_skip_mode") == "leitner_box"
    assert training_manager.get_setting("leadup_target_box") == 3
    assert training_manager.get_setting("leadup_session_limit") == 3
    assert training_manager.get_setting("leadup_show_once_per_session") is True
    assert training_manager.get_setting("leadup_new_moves_mode") == "always_from_start"
    assert training_manager.get_setting("leadup_skip_style") == "instant"


def test_leitner_box_mode_and_once_per_session_toggle(training_manager, repertoire_manager, sample_repertoire):
    repertoire_manager.set_active_repertoire("Test Repo")
    history = _make_history()
    # White repertoire: player moves are index 0 (e4), 2 (Nf3), 4 (Bb5)
    b = chess.Board()
    start_fen = b.fen()
    b.push_san("e4")
    b.push_san("e5")
    fen_before_nf3 = b.fen()
    b.push_san("Nf3")
    b.push_san("Nc6")
    fen_before_bb5 = b.fen()

    training_manager.set_setting("leadup_skip_mode", "leitner_box")
    training_manager.set_setting("leadup_target_box", 3)
    training_manager.set_setting("leadup_show_once_per_session", False)

    # Box 2 is below target 3 -> should NOT skip
    for fen, uci in [(start_fen, "e2e4"), (fen_before_nf3, "g1f3"), (fen_before_bb5, "f1b5")]:
        training_manager.user_session.add(
            TrainingData(repertoire_name="Test Repo", fen=fen, move_uci=uci, box=2)
        )
    training_manager.user_session.commit()
    training_manager._td_cache = None

    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history) is False

    # Upgrade all lead-up moves to Box 3 -> should skip immediately when show_once=False
    training_manager.user_session.query(TrainingData).update({TrainingData.box: 3})
    training_manager.user_session.commit()
    training_manager._td_cache = None
    training_manager.reset_session_variation_counts()

    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history) is True

    # With show_once=True -> first view in session plays intro (False), second view skips (True)
    training_manager.set_setting("leadup_show_once_per_session", True)
    training_manager.reset_session_variation_counts()
    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history) is False
    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history) is True


def test_once_per_session_and_session_count_modes(training_manager, repertoire_manager, sample_repertoire):
    repertoire_manager.set_active_repertoire("Test Repo")
    history = _make_history()

    training_manager.set_setting("leadup_skip_mode", "once_per_session")
    training_manager.set_setting("leadup_show_once_per_session", False)
    training_manager.reset_session_variation_counts()

    assert training_manager.should_skip_leadup_animation("Sicilian", history) is False
    assert training_manager.should_skip_leadup_animation("Sicilian", history) is True
    assert training_manager.should_skip_leadup_animation("Sicilian", history) is True

    training_manager.set_setting("leadup_skip_mode", "session_count")
    training_manager.set_setting("leadup_session_limit", 3)
    training_manager.reset_session_variation_counts()

    assert training_manager.should_skip_leadup_animation("Sicilian", history) is False
    assert training_manager.should_skip_leadup_animation("Sicilian", history) is False
    assert training_manager.should_skip_leadup_animation("Sicilian", history) is False
    assert training_manager.should_skip_leadup_animation("Sicilian", history) is True


def test_new_moves_mode_behavior(training_manager, repertoire_manager, sample_repertoire):
    repertoire_manager.set_active_repertoire("Test Repo")
    history = _make_history()

    training_manager.set_setting("leadup_skip_mode", "always")
    training_manager.set_setting("leadup_show_once_per_session", False)

    training_manager.set_setting("leadup_new_moves_mode", "always_from_start")
    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history, training_mode="new") is False

    training_manager.set_setting("leadup_new_moves_mode", "always_skip")
    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history, training_mode="new") is True

    training_manager.set_setting("leadup_new_moves_mode", "follow_review")
    assert training_manager.should_skip_leadup_animation("Ruy Lopez", history, training_mode="new") is True


def test_main_window_smart_leadup_instant_and_turbo(main_window, training_manager, repertoire_manager):
    session = repertoire_manager.repo_session
    repertoire_manager.set_active_repertoire("Test Repo")

    b = chess.Board()
    p_start = session.query(Position).filter_by(fen=b.fen()).first() or Position(fen=b.fen())
    if not p_start.id:
        session.add(p_start)
        session.flush()

    b.push_san("e4")
    p1 = Position(fen=b.fen())
    session.add(p1)
    session.flush()

    b.push_san("e5")
    p2 = Position(fen=b.fen(), variation_1="King's Pawn")
    session.add(p2)
    session.flush()
    entry_fen = p2.fen

    b.push_san("Nf3")
    p3 = Position(fen=b.fen(), cached_v1="King's Pawn")
    session.add(p3)
    session.flush()
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="g1f3", san="Nf3")
    session.add(m3)

    b.push_san("Nc6")
    p4 = Position(fen=b.fen(), cached_v1="King's Pawn")
    session.add(p4)
    session.flush()
    m4 = Move(from_position_id=p3.id, to_position_id=p4.id, uci="b8c6", san="Nc6")
    session.add(m4)
    session.commit()

    history = [
        {"san": "e4", "uci": "e2e4", "fen": p1.fen},
        {"san": "e5", "uci": "e7e5", "fen": entry_fen},
        {"san": "Nf3", "uci": "g1f3", "fen": p3.fen},
        {"san": "Nc6", "uci": "b8c6", "fen": p4.fen},
    ]

    main_window.active_variation_filter = None
    main_window.training_mode = "due"
    main_window.current_move_obj = m4
    main_window.training_manager.set_setting("leadup_skip_mode", "always")
    main_window.training_manager.set_setting("leadup_show_once_per_session", False)
    main_window.training_manager.set_setting("leadup_skip_style", "instant")

    # 1. Instant Jump: resets to entry_fen and only animates Nf3
    with patch.object(main_window.repertoire_manager, "get_history_for_move", return_value=history), \
         patch.object(main_window.repertoire_manager, "get_variation_entry_point_fen", return_value=entry_fen):
        main_window.board_widget.board.set_fen("8/8/8/8/8/8/8/8 w - -")
        orig_set_fen = main_window.board_widget.set_fen
        main_window.board_widget.set_fen = MagicMock(side_effect=orig_set_fen)

        main_window.start_animation(None)

        main_window.board_widget.set_fen.assert_called_with(entry_fen)
        assert main_window.animation_moves == []
        assert main_window.board_widget.is_animating is True
        assert main_window.board_widget.animating_piece_data["move"].uci() == "g1f3"
        main_window.skip_all_animations()

    # 2. Turbo Slide: plays from start with duration_override=45 for lead-up moves
    main_window.training_manager.set_setting("leadup_skip_style", "turbo")
    with patch.object(main_window.repertoire_manager, "get_history_for_move", return_value=history), \
         patch.object(main_window.repertoire_manager, "get_variation_entry_point_fen", return_value=entry_fen):
        main_window.board_widget.board.set_fen("8/8/8/8/8/8/8/8 w - -")
        main_window.start_animation(None)

        # e4 and e5 are lead-up (2 moves); e4 was popped immediately, so 1 turbo move remains
        assert main_window._turbo_leadup_remaining == 1
        assert main_window.board_widget.anim_duration == 45
        main_window.skip_all_animations()


def test_settings_dialog_leadup_ui(main_window, qapp):
    dlg = UnifiedSettingsDialog(main_window)
    assert hasattr(dlg, "combo_leadup_mode")
    assert hasattr(dlg, "spin_leadup_box")
    assert hasattr(dlg, "spin_leadup_session_limit")
    assert hasattr(dlg, "chk_leadup_once_per_session")
    assert hasattr(dlg, "combo_leadup_new_moves")
    assert hasattr(dlg, "combo_leadup_style")

    idx = dlg.combo_leadup_mode.findData("session_count")
    dlg.combo_leadup_mode.setCurrentIndex(idx)
    assert main_window.training_manager.get_setting("leadup_skip_mode") == "session_count"
    assert dlg.spin_leadup_session_limit.isEnabled() is True
    assert dlg.spin_leadup_box.isEnabled() is False

    dlg.spin_leadup_session_limit.setValue(7)
    assert main_window.training_manager.get_setting("leadup_session_limit") == 7

    dlg.chk_leadup_once_per_session.setChecked(False)
    assert main_window.training_manager.get_setting("leadup_show_once_per_session") is False

    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()
