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
