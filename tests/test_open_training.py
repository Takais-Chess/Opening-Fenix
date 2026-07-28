import pytest
from PyQt6.QtWidgets import QApplication
from opening_fenix.core.services.training_service import TrainingManager
from opening_fenix.core.utils import is_free_training_profile
from opening_fenix.gui.dialogs.open_training_dialog import OpenTrainingSetupDialog

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_is_free_training_profile():
    assert is_free_training_profile("Freies Training") is True
    assert is_free_training_profile("Open Training") is True
    assert is_free_training_profile("NormalProfile") is False
    assert is_free_training_profile(None) is False


def test_free_training_active_level_default(repertoire_manager):
    service = TrainingManager(profile_name="Freies Training", repertoire_manager=repertoire_manager)
    assert service.get_active_level("TestRepo") == 999
    service.close()


def test_free_training_active_level_custom(repertoire_manager):
    service = TrainingManager(profile_name="Freies Training", repertoire_manager=repertoire_manager)
    service.set_active_level(2, "TestRepo")
    assert service.get_active_level("TestRepo") == 2
    service.close()


def test_register_success_duplicate_free_training(repertoire_manager):
    service = TrainingManager(profile_name="Freies Training", repertoire_manager=repertoire_manager)
    all_moves = repertoire_manager.core.get_all_moves()
    if all_moves:
        m_id = all_moves[0].id
        service.register_success(m_id, True)
        # Registering success for the same move again must not fail with IntegrityError
        service.register_success(m_id, True)
    service.close()


def test_open_training_line_continuation(repertoire_manager):
    service = TrainingManager(profile_name="Freies Training", repertoire_manager=repertoire_manager)
    first_move, _ = service.get_next_move(mode='due')
    if first_move:
        service.register_success(first_move.id, True)
        next_move, path = service.get_next_move(
            mode='due',
            last_move_obj=first_move,
            last_was_success=True,
            only_continuation=True
        )
        if next_move:
            assert next_move.id != first_move.id
    service.close()


def test_open_training_setup_dialog_init(qapp, repertoire_manager):
    class MockMainWindow:
        def __init__(self, rm):
            self.repertoire_manager = rm
            self.training_manager = TrainingManager(profile_name="Freies Training", repertoire_manager=rm)
            self.active_variation_filter = None

    mock_mw = MockMainWindow(repertoire_manager)
    dlg = OpenTrainingSetupDialog(mock_mw)

    assert dlg.windowTitle() == "Freies Training" or dlg.windowTitle() == "Open Training"
    assert dlg.combo_repo is not None
    assert dlg.combo_level is not None
    assert dlg.combo_variation is not None
    assert dlg.combo_comment_lang is not None

    repo, level, variation, comment_lang = dlg.get_selections()
    assert level == 999 or isinstance(level, int)
    assert comment_lang in ("auto", "en", "de")
