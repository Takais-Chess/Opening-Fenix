import pytest
from PyQt6.QtWidgets import QWidget, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt, QPoint, QRect
from opening_fenix.gui.widgets.tour_overlay import GuidedTourOverlay

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



