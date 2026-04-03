import pytest
from PyQt6.QtWidgets import QDialog
from opening_fenix.gui.dialogs.login_dialog import LoginDialog
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
from opening_fenix.creator.creator_window import CreatorBackend

@pytest.fixture
def creator_backend(mock_user_dir, sample_repertoire):
    """Fixture for CreatorBackend."""
    backend = CreatorBackend()
    backend.load_repertoire(sample_repertoire)
    return backend

def test_login_dialog_basic(qapp):
    """Test LoginDialog initialization and state."""
    dialog = LoginDialog()
    assert dialog.windowTitle() == "Opening Fenix - Login"
    # Basic button checks
    assert dialog.btn_creator is not None
    assert dialog.btn_new is not None

def test_export_dialog_init(qapp, creator_backend):
    """Test ExportDialog initialization."""
    dialog = ExportDialog(creator_backend)
    assert dialog.windowTitle() == "Exportieren"
    # Test PGN radio button (r_pgn is in the bg_fmt button group)
    assert dialog.r_pgn.isChecked()
    
    # Test transposition combo
    assert dialog.combo_transpos.count() == 3
    dialog.combo_transpos.setCurrentIndex(0)
    assert dialog.combo_transpos.currentIndex() == 0
    
    # Test level combo (should be populated from backend)
    # Our sample_repertoire from conftest has 'Initial Setup' level
    assert dialog.combo_level.count() > 0
