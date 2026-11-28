import pytest
from PyQt6.QtWidgets import QWidget, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt, QPoint, QRect
from unittest.mock import MagicMock
import importlib
from opening_fenix.gui.widgets.tour_overlay import GuidedTourOverlay
import opening_fenix.gui.main_window as mw_mod
from opening_fenix.gui.main_window import MainWindow

@pytest.fixture
def parent_widget(qtbot):
    widget = QWidget()
    widget.setFixedSize(800, 600)
    qtbot.addWidget(widget)
    widget.show()
    return widget

@pytest.fixture
def tour_overlay(qtbot, parent_widget):
    tour = GuidedTourOverlay(parent_widget)
    # Give it valid geometry
    tour.setGeometry(parent_widget.rect())
    return tour

def test_tour_steps_navigation(qtbot, tour_overlay):
    # Setup some widgets to highlight
    w1 = QPushButton("Btn1", tour_overlay.parent())
    w1.move(100, 100)
    w1.show()
    
    tour_overlay.add_step(None, "Welcome", "Hello World")
    tour_overlay.add_step(w1, "Button Step", "Click this")
    
    tour_overlay.start_tour()
    assert tour_overlay.isVisible()
    assert tour_overlay.current_step == 0
    assert "Welcome" in tour_overlay.lbl_title.text()
    assert tour_overlay.btn_next.text() == "WEITER →"
    
    # Click Next
    qtbot.mouseClick(tour_overlay.btn_next, Qt.MouseButton.LeftButton)
    assert tour_overlay.current_step == 1
    assert "Button Step" in tour_overlay.lbl_title.text()
    assert "FERTIG ✓" in tour_overlay.btn_next.text()
    
    # Finished signal
    with qtbot.waitSignal(tour_overlay.finished, timeout=1000):
        qtbot.mouseClick(tour_overlay.btn_next, Qt.MouseButton.LeftButton)
    
    assert not tour_overlay.isVisible()

def test_tour_positioning_center(qtbot, tour_overlay):
    tour_overlay.add_step(None, "Global", "Center me")
    tour_overlay.start_tour()
    
    card_rect = tour_overlay.desc_card.geometry()
    parent_rect = tour_overlay.parent().rect()
    
    # Check if centered horizontally
    expected_x = (parent_rect.width() - card_rect.width()) // 2
    assert abs(card_rect.x() - expected_x) <= 2

def test_tour_positioning_widget(qtbot, tour_overlay):
    # Move widget to bottom to force the card to appear ABOVE
    w_bottom = QPushButton("Bottom", tour_overlay.parent())
    w_bottom.setGeometry(100, 500, 100, 50)
    w_bottom.show()
    
    tour_overlay.add_step(w_bottom, "Bottom Step", "Testing placement")
    tour_overlay.start_tour()
    
    card_rect = tour_overlay.desc_card.geometry()
    target_rect = tour_overlay.target_rect
    
    # Card should be above target if target is at bottom
    assert card_rect.bottom() < target_rect.top()

def test_tour_skip_button(qtbot, tour_overlay):
    w1 = QPushButton("Btn1", tour_overlay.parent())
    w1.show()
    
    tour_overlay.add_step(None, "Step 1", "Description 1")
    tour_overlay.add_step(w1, "Step 2", "Description 2")
    tour_overlay.add_step(None, "Step 3", "Description 3")
    
    tour_overlay.start_tour()
    assert tour_overlay.isVisible()
    assert tour_overlay.current_step == 0
    assert tour_overlay.btn_skip.isVisible()
    
    # Click Skip button
    with qtbot.waitSignal(tour_overlay.finished, timeout=1000):
        qtbot.mouseClick(tour_overlay.btn_skip, Qt.MouseButton.LeftButton)
        
    assert not tour_overlay.isVisible()

def test_check_for_onboarding_logic(qtbot, monkeypatch, tmp_path):
    """Verify check_for_onboarding triggers tour when not shown, and suppresses when already shown."""
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    
    # conftest mocks check_for_onboarding with a lambda. Reload or restore original method:
    import inspect
    # Re-extract real check_for_onboarding from source
    real_func = getattr(mw_mod.MainWindow, "_real_check_for_onboarding", None)
    if real_func is None:
        # Reload module cleanly to get unbound original function
        temp_mod = importlib.import_module("opening_fenix.gui.main_window")
        importlib.reload(temp_mod)
        real_func = temp_mod.MainWindow.check_for_onboarding
    
    mw = MainWindow.__new__(MainWindow)
    mw.profile_name = "TestProfile"
    mw.training_manager = MagicMock()
    mw.start_guided_tour = MagicMock()
    
    # When guide_shown is None or False -> tour must start
    mw.training_manager.get_setting.return_value = None
    real_func(mw)
    mw.start_guided_tour.assert_called_once()
    
    # When guide_shown is True -> tour must not start
    mw.start_guided_tour.reset_mock()
    mw.training_manager.get_setting.return_value = True
    real_func(mw)
    mw.start_guided_tour.assert_not_called()
    
    # Free training profile -> tour must not start
    mw.start_guided_tour.reset_mock()
    mw.profile_name = "Freies Training"
    mw.training_manager.get_setting.return_value = None
    real_func(mw)
    mw.start_guided_tour.assert_not_called()


def test_tour_action_button_visibility_and_completion(qtbot, tour_overlay):
    """Action button appears only on action steps, triggers callback, and marks completed when callback returns True."""
    calls = []

    def _on_action():
        calls.append("clicked")
        return True

    tour_overlay.add_step(None, "Step 0", "Plain step before")
    tour_overlay.add_step(
        None,
        "Step 1",
        "Action step description",
        action_text="Set up Token",
        action_callback=_on_action,
        action_done_text="Token Saved",
    )
    tour_overlay.add_step(None, "Step 2", "Plain step after")

    tour_overlay.start_tour()
    assert tour_overlay.current_step == 0
    assert not tour_overlay.btn_action.isVisible()

    qtbot.mouseClick(tour_overlay.btn_next, Qt.MouseButton.LeftButton)
    assert tour_overlay.current_step == 1
    assert tour_overlay.btn_action.isVisible()
    assert tour_overlay.btn_action.isEnabled()
    assert tour_overlay.btn_action.text() == "Set up Token"

    qtbot.mouseClick(tour_overlay.btn_action, Qt.MouseButton.LeftButton)
    assert calls == ["clicked"]
    assert tour_overlay.btn_action.text() == "Token Saved"
    assert not tour_overlay.btn_action.isEnabled()

    qtbot.mouseClick(tour_overlay.btn_next, Qt.MouseButton.LeftButton)
    assert tour_overlay.current_step == 2
    assert not tour_overlay.btn_action.isVisible()


def test_lichess_token_tour_step_conditional(qtbot, parent_widget, tmp_path, monkeypatch):
    """Lichess token step is added to the tour only when no valid Lichess API token is configured."""
    import json
    import opening_fenix.gui.dialogs.lichess_token_dialog as ltd_mod
    from PyQt6.QtWidgets import QDialog

    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.core.services.update_service.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.gui.dialogs.lichess_token_dialog.get_user_dir", lambda: str(tmp_path))

    # Case 1: No config.json -> step is added and action opens LichessTokenDialog
    tour1 = GuidedTourOverlay(parent_widget)
    tour1.setGeometry(parent_widget.rect())
    added = ltd_mod.add_lichess_token_tour_step_if_missing(tour1, parent_widget)
    assert added is True
    assert len(tour1.steps) == 1
    assert tour1.steps[0]["action_text"]

    class StubTokenDialog:
        def __init__(self, parent=None, current_token=None, allow_skip=False):
            assert allow_skip is True
            self.skip_chosen = False

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_token(self):
            return "lip_validtoken12345"

    monkeypatch.setattr(ltd_mod, "LichessTokenDialog", StubTokenDialog)
    tour1.start_tour()
    assert tour1.btn_action.isVisible()
    assert tour1.btn_action.isEnabled()
    qtbot.mouseClick(tour1.btn_action, Qt.MouseButton.LeftButton)
    assert not tour1.btn_action.isEnabled()

    # Case 2: Valid token already configured in config.json -> step is omitted
    with open(tmp_path / "config.json", "w", encoding="utf-8") as f:
        json.dump({"lichess_token": "lip_existingtoken12345"}, f)

    tour2 = GuidedTourOverlay(parent_widget)
    tour2.setGeometry(parent_widget.rect())
    added2 = ltd_mod.add_lichess_token_tour_step_if_missing(tour2, parent_widget)
    assert added2 is False
    assert len(tour2.steps) == 0


def test_main_window_empty_repertoire_and_tour_lichess_step(qapp, mock_user_dir, monkeypatch):
    """MainWindow opens cleanly with a single empty repertoire and adds Lichess token step to tour only when missing."""
    import os
    import json
    from opening_fenix.core.services.repertoire_core_service import (
        create_empty_repertoire,
        invalidate_all_repertoires_cache,
    )
    from opening_fenix.core.models import DatabaseManager, UserBase, UserRepertoireSettings

    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.setattr("opening_fenix.core.services.update_service.get_user_dir", lambda: mock_user_dir)
    monkeypatch.setattr("opening_fenix.gui.dialogs.lichess_token_dialog.get_user_dir", lambda: mock_user_dir)
    monkeypatch.setattr("opening_fenix.gui.main_window.MainWindow.play_sound", lambda *args: None)

    invalidate_all_repertoires_cache()
    repo_name = create_empty_repertoire("EmptySoloRepo", "b")

    profile_db = DatabaseManager(os.path.join(mock_user_dir, "profiles", "EmptyUser.db"), base=UserBase)
    sess = profile_db.get_session()
    try:
        sess.add(UserRepertoireSettings(repertoire_name=repo_name, active_level=1))
        sess.commit()
    finally:
        sess.close()
        profile_db.close()

    win = MainWindow(profile_name="EmptyUser")
    try:
        assert win.repertoire_manager.active_repertoire_name == repo_name
        assert win.board_widget.flipped is True

        # No config.json -> tour includes Lichess API token setup step at the end
        win.start_guided_tour()
        assert any(step.get("action_text") for step in win.tour.steps)
        assert win.tour.steps[-1].get("action_text") is not None
        win.tour.hide()
        win.tour._detach_event_filter()

        # Valid token present -> tour omits Lichess API token step
        with open(os.path.join(mock_user_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"lichess_token": "lip_existingtoken12345"}, f)

        win.start_guided_tour()
        assert not any(step.get("action_text") for step in win.tour.steps)
        win.tour.hide()
        win.tour._detach_event_filter()
    finally:
        win.close()


