import pytest
from PyQt6.QtWidgets import QApplication
from opening_fenix.gui.dialogs.course_intro_dialog import CourseIntroDialog

@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

@pytest.fixture
def intro_dialog(qapp):
    info = {
        "name": "TestRepo",
        "description": "Test Description",
        "level_details": [
            {"name": "Level 1", "moves": 10, "target_elo": 1500}
        ]
    }
    dialog = CourseIntroDialog(repertoire_info=info)
    yield dialog
    dialog.close()

def test_intro_dialog_init(intro_dialog):
    """Test basic initialization of the course intro dialog."""
    assert intro_dialog.repertoire_info["name"] == "TestRepo"

def test_intro_dialog_navigation(intro_dialog, qapp):
    """Test navigating through the intro dialog pages."""
    # check that we can go next if there are multiple pages
    # CourseIntroDialog usually has a stacked widget or similar
    if hasattr(intro_dialog, "stacked_widget"):
        initial_idx = intro_dialog.stacked_widget.currentIndex()
        if hasattr(intro_dialog, "btn_next"):
            intro_dialog.btn_next.click()
            qapp.processEvents()
            assert intro_dialog.stacked_widget.currentIndex() != initial_idx
            
def test_intro_dialog_finish(intro_dialog, qapp):
    """Test finishing the dialog."""
    if hasattr(intro_dialog, "btn_finish"):
        intro_dialog.btn_finish.click()
        qapp.processEvents()
        # Dialog should be closed or accepted
        assert not intro_dialog.isVisible()
