import os
import pytest
from unittest.mock import patch
from PyQt6.QtWidgets import QMessageBox, QApplication
from opening_fenix.creator.creator_window import CreatorWindow
from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir
from opening_fenix.core.services.repertoire_service import RepertoireService


def _create_test_repo(repo_name, mock_user_dir):
    from opening_fenix.core.db.models import Base, Position, Move, RepertoireMove, RepertoireLevel
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import initialize_repertoire_assets
    
    repo_dir = get_repertoire_dir(repo_name, is_test=False)
    initialize_repertoire_assets(repo_dir)
    db_path = get_repertoire_db_path(repo_name, is_test=False)
    db = DatabaseManager(db_path, base=Base)
    session = db.get_session()
    
    lvl = RepertoireLevel(name="Level 1", order=1)
    session.add(lvl)
    
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    p = Position(fen=start_fen)
    session.add(p)
    session.flush()
    
    m = Move(from_position_id=p.id, to_position_id=p.id, uci="e2e4", san="e4")
    session.add(m)
    session.flush()
    
    rm = RepertoireMove(move_id=m.id, level=1)
    session.add(rm)
    session.commit()
    session.close()
    db.close()
    return repo_name


def test_delete_active_repertoire_via_creator_action(mock_user_dir, qapp):
    """Test that deleting a repertoire while active in Creator cleanly switches to the remaining course."""
    _create_test_repo("AlphaCourse", mock_user_dir)
    _create_test_repo("BetaCourse", mock_user_dir)
    
    cw = CreatorWindow(repertoire_name="AlphaCourse")
    qapp.processEvents()
    
    assert cw.active_repo_name == "AlphaCourse"
    assert cw.backend.active_repo_name == "AlphaCourse"
    alpha_dir = get_repertoire_dir("AlphaCourse", is_test=False)
    assert os.path.exists(alpha_dir)
    
    # Delete active course AlphaCourse
    succ, msg = cw.delete_repertoire_action("AlphaCourse")
    qapp.processEvents()
    
    assert succ is True
    assert not os.path.exists(alpha_dir)
    # CreatorWindow should automatically switch to the remaining BetaCourse
    assert cw.active_repo_name == "BetaCourse"
    assert cw.backend.active_repo_name == "BetaCourse"
    
    # Simulate closing settings dialog - ensure AlphaCourse is NOT resurrected
    cw._on_settings_closed()
    qapp.processEvents()
    assert not os.path.exists(alpha_dir)
    assert cw.active_repo_name == "BetaCourse"
    
    cw.close()


def test_delete_active_repertoire_via_settings_dialog(mock_user_dir, qapp):
    """Test deleting the active course from UnifiedSettingsDialog."""
    _create_test_repo("FirstRepo", mock_user_dir)
    _create_test_repo("SecondRepo", mock_user_dir)
    
    cw = CreatorWindow(repertoire_name="FirstRepo")
    qapp.processEvents()
    
    dialog = UnifiedSettingsDialog(parent=cw, backend=cw.backend, initial_section="creator")
    qapp.processEvents()
    
    first_dir = get_repertoire_dir("FirstRepo", is_test=False)
    assert os.path.exists(first_dir)
    
    # Make sure dropdown is on FirstRepo
    idx = dialog.combo_active_repo.findData("FirstRepo")
    if idx >= 0:
        dialog.combo_active_repo.setCurrentIndex(idx)
        qapp.processEvents()
    
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
        dialog.delete_creator_repertoire()
        qapp.processEvents()
        
    assert not os.path.exists(first_dir)
    assert cw.active_repo_name == "SecondRepo"
    
    # Close dialog and check that FirstRepo is not resurrected
    dialog.close()
    cw._on_settings_closed()
    qapp.processEvents()
    assert not os.path.exists(first_dir)
    
    dialog.deleteLater()
    cw.close()
