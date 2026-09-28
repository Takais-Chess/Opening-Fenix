import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch

sys.path.append(os.getcwd())

from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Base, RepertoireMove, Move, Position, RepertoireLevel
from opening_fenix.core.db.database import DatabaseManager


def test_bulk_impact_multi_level():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        backend = CreatorBackend()
        backend.db_manager = DatabaseManager(db_path, base=Base)
        backend.session = backend.db_manager.get_session()
        Base.metadata.create_all(backend.db_manager.engine)

        # Levels
        rl1 = RepertoireLevel(name="Basics", order=1)
        rl2 = RepertoireLevel(name="Intermediate", order=2)
        rl3 = RepertoireLevel(name="Deep Lines", order=3)
        backend.session.add_all([rl1, rl2, rl3])

        # Positions & Moves
        p1 = Position(fen="pos1")
        p2 = Position(fen="pos2")
        backend.session.add_all([p1, p2])
        backend.session.flush()

        # Add 2 moves to level 1, 3 moves to level 2, 1 move to level 3
        m_list = []
        for i in range(6):
            m = Move(from_position_id=p1.id, to_position_id=p2.id, uci=f"e2e{i}", san=f"e{i}")
            m_list.append(m)
        backend.session.add_all(m_list)
        backend.session.flush()

        # Moves: 0, 1 -> lvl 1; 2, 3, 4 -> lvl 2; 5 -> lvl 3
        backend.session.add(RepertoireMove(move_id=m_list[0].id, level=1))
        backend.session.add(RepertoireMove(move_id=m_list[1].id, level=1))
        backend.session.add(RepertoireMove(move_id=m_list[2].id, level=2))
        backend.session.add(RepertoireMove(move_id=m_list[3].id, level=2))
        backend.session.add(RepertoireMove(move_id=m_list[4].id, level=2))
        backend.session.add(RepertoireMove(move_id=m_list[5].id, level=3))
        backend.session.commit()

        # Target level 1
        impact1 = backend.get_move_all_to_level_impact(1)
        assert impact1['total_moves'] == 6
        assert impact1['target_level'] == 1
        assert impact1['target_level_name'] == "Basics"
        assert impact1['moves_unchanged'] == 2
        assert impact1['moves_changing'] == 4
        assert len(impact1['distribution']) == 3
        assert impact1['distribution'][0]['count'] == 2 and impact1['distribution'][0]['is_target'] is True
        assert impact1['distribution'][1]['count'] == 3 and impact1['distribution'][1]['is_target'] is False
        assert impact1['distribution'][2]['count'] == 1 and impact1['distribution'][2]['is_target'] is False

        # Target level 2
        impact2 = backend.get_move_all_to_level_impact(2)
        assert impact2['total_moves'] == 6
        assert impact2['moves_unchanged'] == 3
        assert impact2['moves_changing'] == 3

        # Apply move all to level 1
        updated = backend.move_all_to_level(1)
        assert updated == 6

        # Check post-move impact
        impact_post = backend.get_move_all_to_level_impact(1)
        assert impact_post['total_moves'] == 6
        assert impact_post['moves_unchanged'] == 6
        assert impact_post['moves_changing'] == 0

    finally:
        if backend.session: backend.session.close()
        if backend.db_manager: backend.db_manager.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_dialog_creator_tools_widgets(qtbot):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog

    app = QApplication.instance() or QApplication([])

    mock_backend = MagicMock()
    mock_backend.active_repo_name = "Test Repo"
    mock_backend.get_repertoire_info.return_value = {"name": "Test Repo", "description": "", "color": "white"}
    mock_backend.get_meta.side_effect = lambda k, d="": "high" if k == "elo" else (d or "")
    mock_backend.get_repertoire_levels.return_value = [
        {"name": "Basics", "order": 1, "target_elo": 1500},
        {"name": "Intermediate", "order": 2, "target_elo": 1800}
    ]
    mock_backend.get_priority_level_impact.return_value = 5
    mock_backend.get_move_all_to_level_impact.return_value = {
        'total_moves': 10,
        'target_level': 1,
        'target_level_name': 'Basics',
        'distribution': [
            {'order': 1, 'name': 'Basics', 'count': 4, 'is_target': True},
            {'order': 2, 'name': 'Intermediate', 'count': 6, 'is_target': False}
        ],
        'moves_changing': 6,
        'moves_unchanged': 4
    }
    mock_backend.move_all_to_level.return_value = 10
    mock_backend.apply_priority_level_update.return_value = 5

    with patch('opening_fenix.gui.dialogs.unified_settings_dialog.get_repertoire_db_path', return_value="dummy.db"), \
         patch('os.path.exists', return_value=True):
        dlg = UnifiedSettingsDialog(backend=mock_backend, initial_section="creator")
        qtbot.addWidget(dlg)

    # Check widgets exist
    assert hasattr(dlg, 'spin_prio_threshold')
    assert dlg.spin_prio_threshold.suffix() == " %"
    assert hasattr(dlg, 'combo_prio_target')
    assert hasattr(dlg, 'combo_global_level')

    # Test prio preview
    with patch.object(QMessageBox, 'information') as mock_info:
        dlg._preview_prio_level_impact()
        assert mock_info.called

    # Test global preview
    with patch.object(QMessageBox, 'information') as mock_info:
        dlg._preview_global_move_impact()
        assert mock_info.called

    # Test global apply cancel
    with patch.object(QMessageBox, 'exec') as mock_exec:
        dlg._apply_global_move_assignment()
        assert mock_exec.called
