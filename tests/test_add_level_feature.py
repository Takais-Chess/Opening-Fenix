import pytest
from unittest.mock import patch
from PyQt6.QtWidgets import QDialog
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.db.models import RepertoireLevel, RepertoireMove, Move, Position
from opening_fenix.gui.dialogs.unified_settings_dialog import AddLevelDialog, UnifiedSettingsDialog


@pytest.fixture
def populated_backend(mock_user_dir, sample_repertoire):
    """
    CreatorBackend with 2 levels:
    - Level 1: 'Level B' with a move (level=1)
    - Level 2: 'Level C' with a move (level=2)
    """
    backend = CreatorBackend()
    backend.load_repertoire(sample_repertoire)
    session = backend.session

    # Level 1 already exists from sample_repertoire, rename it to 'Level B'
    lvl1 = session.query(RepertoireLevel).filter_by(order=1).first()
    lvl1.name = "Level B"
    lvl1.target_elo = 1400

    # Add Level 2 'Level C'
    lvl2 = RepertoireLevel(name="Level C", order=2, target_elo=1700)
    session.add(lvl2)
    session.flush()

    # Move 1 is in Level 1 (from sample_repertoire). Add Move 2 in Level 2.
    m2 = session.query(Move).filter_by(uci="e7e5").first()
    rm2 = RepertoireMove(move_id=m2.id, level=2)
    session.add(rm2)
    session.commit()
    backend.clear_cache()

    yield backend
    if backend.session:
        backend.session.close()


class TestAddLevelBackendLogic:
    def test_add_level_at_beginning_with_take_moves(self, populated_backend):
        """
        When adding Level 1 'Level A' with take_moves=True:
        - Level 1 'Level A' takes the moves from previous Level 1 'Level B'
        - Previous Level 1 'Level B' is shifted to Level 2 and is empty (0 moves)
        - Previous Level 2 'Level C' is shifted to Level 3 and keeps its moves (level=3)
        """
        success, msg = populated_backend.add_repertoire_level(
            name="Level A",
            idx=1,
            target_elo=1200,
            take_moves=True
        )
        assert success is True

        levels = populated_backend.get_repertoire_levels()
        assert len(levels) == 3
        assert levels[0]["name"] == "Level A" and levels[0]["order"] == 1 and levels[0]["target_elo"] == 1200
        assert levels[1]["name"] == "Level B" and levels[1]["order"] == 2
        assert levels[2]["name"] == "Level C" and levels[2]["order"] == 3

        # Moves check
        session = populated_backend.session
        moves_lvl1 = session.query(RepertoireMove).filter_by(level=1).all()
        moves_lvl2 = session.query(RepertoireMove).filter_by(level=2).all()
        moves_lvl3 = session.query(RepertoireMove).filter_by(level=3).all()

        # Level 1 has the move that previously belonged to Level 1 'Level B'
        assert len(moves_lvl1) == 1
        # Level 2 (shifted Level B) has 0 moves
        assert len(moves_lvl2) == 0
        # Level 3 (shifted Level C) has the move that previously belonged to Level 2
        assert len(moves_lvl3) == 1

    def test_add_level_at_beginning_without_take_moves(self, populated_backend):
        """
        When adding Level 1 'Level A' with take_moves=False:
        - Level 1 'Level A' starts empty (0 moves)
        - Previous Level 1 'Level B' moves to Level 2 and keeps its moves (level=2)
        - Previous Level 2 'Level C' moves to Level 3 and keeps its moves (level=3)
        """
        success, msg = populated_backend.add_repertoire_level(
            name="Level A",
            idx=1,
            target_elo=1200,
            take_moves=False
        )
        assert success is True

        levels = populated_backend.get_repertoire_levels()
        assert len(levels) == 3
        assert levels[0]["name"] == "Level A" and levels[0]["order"] == 1
        assert levels[1]["name"] == "Level B" and levels[1]["order"] == 2
        assert levels[2]["name"] == "Level C" and levels[2]["order"] == 3

        session = populated_backend.session
        moves_lvl1 = session.query(RepertoireMove).filter_by(level=1).all()
        moves_lvl2 = session.query(RepertoireMove).filter_by(level=2).all()
        moves_lvl3 = session.query(RepertoireMove).filter_by(level=3).all()

        assert len(moves_lvl1) == 0
        assert len(moves_lvl2) == 1
        assert len(moves_lvl3) == 1

    def test_add_level_intermediate_with_take_moves(self, populated_backend):
        """
        Insert at position 2 when levels are 1 and 2:
        - Level 1 stays Level 1 with its moves unchanged.
        - New Level 2 takes moves of previous Level 2.
        - Previous Level 2 shifts to Level 3 and has 0 moves.
        """
        success, _ = populated_backend.add_repertoire_level(
            name="Level Intermediate",
            idx=2,
            target_elo=1550,
            take_moves=True
        )
        assert success is True

        levels = populated_backend.get_repertoire_levels()
        assert len(levels) == 3
        assert levels[0]["order"] == 1 and levels[0]["name"] == "Level B"
        assert levels[1]["order"] == 2 and levels[1]["name"] == "Level Intermediate"
        assert levels[2]["order"] == 3 and levels[2]["name"] == "Level C"

        session = populated_backend.session
        moves_lvl1 = session.query(RepertoireMove).filter_by(level=1).all()
        moves_lvl2 = session.query(RepertoireMove).filter_by(level=2).all()
        moves_lvl3 = session.query(RepertoireMove).filter_by(level=3).all()

        assert len(moves_lvl1) == 1
        assert len(moves_lvl2) == 1
        assert len(moves_lvl3) == 0

    def test_add_level_at_end(self, populated_backend):
        """
        Append at the end:
        - Appends with order = max_order + 1.
        - Starts empty.
        - Existing moves unaffected.
        """
        success, _ = populated_backend.add_repertoire_level(
            name="Level D",
            idx=None,
            target_elo=2000
        )
        assert success is True

        levels = populated_backend.get_repertoire_levels()
        assert len(levels) == 3
        assert levels[2]["name"] == "Level D" and levels[2]["order"] == 3

        session = populated_backend.session
        assert session.query(RepertoireMove).filter_by(level=3).count() == 0
        assert session.query(RepertoireMove).filter_by(level=1).count() == 1
        assert session.query(RepertoireMove).filter_by(level=2).count() == 1


class TestAddLevelDialogUI:
    def test_dialog_initialization(self, qapp):
        levels = [
            {"order": 1, "name": "Basic", "target_elo": 1300},
            {"order": 2, "name": "Deep Theory", "target_elo": 1700}
        ]
        dlg = AddLevelDialog(levels=levels, default_order=1)

        # Name field empty, button disabled
        assert dlg.txt_name.text() == ""
        assert not dlg.btn_ok.isEnabled()

        # Position combo options: 1 (start), 2 (before Deep Theory), 3 (at end)
        assert dlg.combo_pos.count() == 3
        assert dlg.combo_pos.itemData(0) == 1
        assert dlg.combo_pos.itemData(1) == 2
        assert dlg.combo_pos.itemData(2) == 3

        # Default order 1 was requested
        assert dlg.combo_pos.currentData() == 1
        assert not dlg.g_moves.isHidden()
        assert dlg.radio_take_moves.isChecked()
        assert dlg.lbl_end_note.isHidden()

        dlg.close()

    def test_dialog_typing_updates_preview_and_button(self, qapp):
        levels = [
            {"order": 1, "name": "Basic", "target_elo": 1300},
            {"order": 2, "name": "Deep Theory", "target_elo": 1700}
        ]
        dlg = AddLevelDialog(levels=levels, default_order=1)

        dlg.txt_name.setText("Starter")
        assert dlg.btn_ok.isEnabled()

        # Preview table should have 3 rows
        assert dlg.tbl_preview.rowCount() == 3
        # Row 0 is the new level
        assert dlg.tbl_preview.item(0, 0).text() == "1"
        assert dlg.tbl_preview.item(0, 1).text() == "Starter"
        assert "Neu" in dlg.tbl_preview.item(0, 3).text()

        # Row 1 is shifted Basic (empty because take_moves=True)
        assert dlg.tbl_preview.item(1, 0).text() == "2"
        assert dlg.tbl_preview.item(1, 1).text() == "Basic"
        assert "leer" in dlg.tbl_preview.item(1, 3).text()

        # Row 2 is shifted Deep Theory
        assert dlg.tbl_preview.item(2, 0).text() == "3"
        assert dlg.tbl_preview.item(2, 1).text() == "Deep Theory"

        dlg.close()

    def test_dialog_toggle_radio_keep_moves(self, qapp):
        levels = [
            {"order": 1, "name": "Basic", "target_elo": 1300},
            {"order": 2, "name": "Deep Theory", "target_elo": 1700}
        ]
        dlg = AddLevelDialog(levels=levels, default_order=1)
        dlg.txt_name.setText("Starter")

        # Select keep moves instead
        dlg.radio_keep_moves.setChecked(True)
        assert dlg.tbl_preview.item(0, 3).text() == "⭐ Neu (leer)"
        assert dlg.tbl_preview.item(1, 3).text() == "Verschoben (Züge behalten)"

        name, pos, elo, take_moves = dlg.get_data()
        assert name == "Starter"
        assert pos == 1
        assert take_moves is False

        dlg.close()

    def test_dialog_select_end_position(self, qapp):
        levels = [
            {"order": 1, "name": "Basic", "target_elo": 1300},
            {"order": 2, "name": "Deep Theory", "target_elo": 1700}
        ]
        dlg = AddLevelDialog(levels=levels)
        dlg.txt_name.setText("Master Level")
        dlg.combo_pos.setCurrentIndex(2) # Position 3 (End)

        assert not dlg.lbl_end_note.isHidden()
        assert dlg.radio_take_moves.isHidden()
        assert dlg.radio_keep_moves.isHidden()

        assert dlg.tbl_preview.item(0, 1).text() == "Basic"
        assert dlg.tbl_preview.item(0, 3).text() == "Unverändert"
        assert dlg.tbl_preview.item(2, 1).text() == "Master Level"
        assert dlg.tbl_preview.item(2, 3).text() == "⭐ Neu (leer)"

        name, pos, elo, take_moves = dlg.get_data()
        assert name == "Master Level"
        assert pos == 3
        assert take_moves is False

        dlg.close()
