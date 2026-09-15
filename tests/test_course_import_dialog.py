import os
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget, QComboBox

from opening_fenix.gui.dialogs.course_import_dialog import CourseImportDialog

@pytest.fixture
def temp_pgn(tmp_path):
    pgn_content = """
[Event "Sicilian Repertoire"]
[White "Intro"]
[Black "Introduction"]
[Result "*"]
1. e4 *

[Event "Sicilian Repertoire"]
[White "Basics"]
[Black "Quickstarter Guide"]
[Result "*"]
1. e4 c5 2. Nf3 d6 *

[Event "Sicilian Repertoire"]
[White "Dragon Line"]
[Black "Chapter 1: Dragon"]
[Result "*"]
1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 g6 *

[Event "Sicilian Repertoire"]
[White "Puzzle"]
[Black "Training Exercises"]
[FEN "r1bqkb1r/pp2pppp/3p4/1P2nP2/5B2/2N5/1PP3PP/R2QKB1R w KQkq - 0 13"]
[Result "*"]
1. Bxe5 dxe5 *
"""
    file_path = os.path.join(tmp_path, "Sicilian Course.pgn")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(pgn_content)
    return file_path

def test_course_import_dialog_initialization(qtbot):
    dlg = CourseImportDialog()
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() != ""
    assert dlg.name_input.text() == ""
    assert dlg.btn_import.isEnabled() is False

def test_course_import_dialog_load_file(qtbot, temp_pgn):
    dlg = CourseImportDialog(initial_pgn_path=temp_pgn)
    qtbot.addWidget(dlg)

    assert dlg.name_input.text() == "Sicilian Course"
    assert dlg.btn_import.isEnabled() is True
    assert dlg.val_l1.text() in ("1 Partie", "1 game")
    assert dlg.val_l2.text() in ("1 Partie", "1 game")
    assert dlg.val_mot.text() in ("0 Partien", "0 games")
    assert dlg.val_tac.text() in ("1 Puzzle", "1 puzzle")
    assert dlg.val_intro.text() in ("1 Partie", "1 game")

    # Verify tree details top-level chapters
    assert dlg.tree_details.topLevelItemCount() == 4
    from PyQt6.QtWidgets import QAbstractItemView
    assert dlg.tree_details.selectionMode() == QAbstractItemView.SelectionMode.NoSelection

    # Verify top-level item and child items
    ch_0 = dlg.tree_details.topLevelItem(0)
    assert ch_0 is not None
    assert ch_0.childCount() == 1
    child_0 = ch_0.child(0)
    assert child_0 is not None
    assert "↳" in child_0.text(0)

    # Verify dropdown uses chevron icon
    combo = dlg.tree_details.itemWidget(ch_0, 2)
    assert combo is not None
    assert "chevron_down.svg" in combo.styleSheet()

    # Toggle details tree
    dlg.toggle_details_tree()
    assert not dlg.tree_details.isHidden()
    assert not dlg.btn_expand_all.isHidden()
    assert not dlg.btn_collapse_all.isHidden()

    # Test line-level override to Typical Motives
    from opening_fenix.core.services.course_import_service import CATEGORY_MOTIVES
    game_combo = dlg.tree_details.itemWidget(child_0, 2)
    assert game_combo is not None
    m_idx = game_combo.findData(CATEGORY_MOTIVES)
    assert m_idx >= 0
    game_combo.setCurrentIndex(m_idx)

    # Verify badge updated!
    assert dlg.val_mot.text() in ("1 Partie", "1 game")

def test_repo_selection_has_import_course_button(qtbot):
    from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog
    with patch("opening_fenix.creator.repo_selection_dialog.RepertoireService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.get_all_repertoires.return_value = ["Repo1"]
        dlg = RepoSelectionDialog()
        qtbot.addWidget(dlg)
        assert hasattr(dlg, "btn_import_course")
        assert not dlg.btn_import_course.isHidden()

def test_course_import_dialog_expand_collapse_and_click(qtbot, temp_pgn):
    dlg = CourseImportDialog(initial_pgn_path=temp_pgn)
    qtbot.addWidget(dlg)
    dlg.toggle_details_tree()

    # Verify expanded state
    assert not dlg.tree_details.isHidden()
    assert not dlg.btn_expand_all.isHidden()
    assert not dlg.btn_collapse_all.isHidden()
    assert not dlg.lbl_details_hint.isHidden()

    ch_0 = dlg.tree_details.topLevelItem(0)
    assert not ch_0.isExpanded()

    # Click column 0 to expand
    dlg.on_tree_item_clicked(ch_0, 0)
    assert ch_0.isExpanded()

    # Verify child widget is visible
    child_0 = ch_0.child(0)
    w = dlg.tree_details.itemWidget(child_0, 2)
    assert w is not None
    assert not w.isHidden()

    # Click column 0 again to collapse
    dlg.on_tree_item_clicked(ch_0, 0)
    assert not ch_0.isExpanded()

    # Re-expand and verify child widget still exists and is visible
    dlg.on_tree_item_clicked(ch_0, 0)
    assert ch_0.isExpanded()
    w_after = dlg.tree_details.itemWidget(child_0, 2)
    assert w_after is not None
    assert not w_after.isHidden()

    # Collapse tree and verify all details elements are completely hidden
    dlg.toggle_details_tree()
    assert dlg.tree_details.isHidden()
    assert dlg.btn_expand_all.isHidden()
    assert dlg.btn_collapse_all.isHidden()
    assert dlg.lbl_details_hint.isHidden()


def test_chapter_lines_dialog_search_and_bulk_assign(qtbot, temp_pgn):
    from opening_fenix.gui.dialogs.course_import_dialog import ChapterLinesDialog
    from opening_fenix.core.services.course_import_service import analyze_course_pgns, CATEGORY_MOTIVES

    res = analyze_course_pgns([temp_pgn])
    ch_dragon = next(c for c in res.chapters if "Dragon" in c.name)
    assert len(ch_dragon.games) == 1

    sub_dlg = ChapterLinesDialog(ch_dragon, ch_dragon.target_type, {})
    qtbot.addWidget(sub_dlg)

    # Test search filter
    sub_dlg.search_input.setText("Dragon")
    assert not sub_dlg.table.isRowHidden(0)

    sub_dlg.search_input.setText("NonExistentVariation")
    assert sub_dlg.table.isRowHidden(0)

    sub_dlg.search_input.setText("")
    assert not sub_dlg.table.isRowHidden(0)

    # Test select all and bulk assign
    sub_dlg.on_select_all()
    item_chk = sub_dlg.table.item(0, 0)
    assert item_chk.checkState() == Qt.CheckState.Checked

    idx = sub_dlg.bulk_combo.findData(CATEGORY_MOTIVES)
    assert idx >= 0
    sub_dlg.bulk_combo.setCurrentIndex(idx)
    sub_dlg.on_apply_bulk()

    # Verify line target changed
    assert sub_dlg.game_targets[ch_dragon.games[0].game_id] == CATEGORY_MOTIVES

    # Accept changes
    sub_dlg.on_accept_changes()
    assert sub_dlg.result_targets[ch_dragon.games[0].game_id] == CATEGORY_MOTIVES

def test_chapter_mixed_categories_badge(qtbot, tmp_path):
    from opening_fenix.core.services.course_import_service import CATEGORY_LEVEL_1, CATEGORY_MOTIVES

    pgn = """[Event "Test"]
[White "Var 1"]
[Black "Chapter One"]
[Result "*"]
1. e4 *

[Event "Test"]
[White "Var 2"]
[Black "Chapter One"]
[Result "*"]
1. d4 *
"""
    p = os.path.join(tmp_path, "mixed_test.pgn")
    with open(p, "w", encoding="utf-8") as f:
        f.write(pgn)

    dlg = CourseImportDialog(initial_pgn_path=p)
    qtbot.addWidget(dlg)

    ch_item = dlg.tree_details.topLevelItem(0)
    assert ch_item is not None
    assert hasattr(ch_item, "_lbl_mixed")

    # Initially both lines are in Level 2 -> Not mixed
    assert ch_item._lbl_mixed.isHidden()

    # Override 1 line to Motives -> Mixed badge should appear
    game_0 = dlg.analysis_result.chapters[0].games[0]
    dlg.on_game_target_changed(game_0.game_id, CATEGORY_MOTIVES)
    assert not ch_item._lbl_mixed.isHidden()
    assert "🎨" in ch_item._lbl_mixed.text()
    assert "💡 1" in ch_item._lbl_mixed.text()
    assert "📚 1" in ch_item._lbl_mixed.text()

    # Override the second line to Motives as well -> Uniform again, mixed badge hidden!
    game_1 = dlg.analysis_result.chapters[0].games[1]
    dlg.on_game_target_changed(game_1.game_id, CATEGORY_MOTIVES)
    assert ch_item._lbl_mixed.isHidden()

def test_course_import_dialog_lichess_elo(qtbot, temp_pgn):
    dlg = CourseImportDialog(initial_pgn_path=temp_pgn)
    qtbot.addWidget(dlg)

    # Check that elo_combo exists and contains the expected rating options
    assert hasattr(dlg, "elo_combo")
    all_data = [dlg.elo_combo.itemData(i) for i in range(dlg.elo_combo.count())]
    assert "low" in all_data
    assert "mid" in all_data
    assert "high" in all_data
    assert "masters" in all_data

    # Default should be "high"
    assert dlg.elo_combo.currentData() == "high"

    # Select "mid"
    idx_mid = dlg.elo_combo.findData("mid")
    assert idx_mid >= 0
    dlg.elo_combo.setCurrentIndex(idx_mid)
    assert dlg.elo_combo.currentData() == "mid"

    # Test that on_start_import passes elo to the CourseImportPlan
    with patch("opening_fenix.gui.dialogs.course_import_dialog.CourseImportThread") as mock_thread_cls:
        mock_thread_instance = MagicMock()
        mock_thread_cls.return_value = mock_thread_instance

        dlg.on_start_import()

        assert mock_thread_cls.called
        plan_arg = mock_thread_cls.call_args[0][0]
        assert plan_arg.elo == "mid"

def test_course_import_dialog_bottom_visibility_and_experimental_badge(qtbot, temp_pgn):
    dlg = CourseImportDialog()
    qtbot.addWidget(dlg)

    # Initially, bottom container and import button must be hidden
    assert dlg.bottom_container.isHidden() is True
    assert dlg.btn_import.isHidden() is True

    # Experimental badge must be visible and contain experimental text
    assert hasattr(dlg, "badge_experimental")
    assert "Experiment" in dlg.badge_experimental.text()

    # Initial subtitle must be explanatory, contain Tiefe Theorie, and not Haupttheorie
    sub_text = dlg.lbl_sub.text()
    assert "Tiefe Theorie" in sub_text or "Deep Theory" in sub_text
    assert "Haupttheorie" not in sub_text
    assert "Quickstarter" in sub_text

    # Ampersand button test: no solitary '&' that causes Qt mnemonic underscore bug
    btn_text = dlg.btn_toggle_details.text()
    assert "&&" in btn_text
    assert " & " not in btn_text

    # Now load file: bottom container and import button become visible
    dlg.load_files([temp_pgn])
    assert dlg.bottom_container.isHidden() is False
    assert dlg.btn_import.isHidden() is False
    assert dlg.btn_import.isEnabled() is True

    # Check button text after loading still escapes ampersand
    btn_text_loaded = dlg.btn_toggle_details.text()
    assert "&&" in btn_text_loaded
    assert " & " not in btn_text_loaded

def test_course_import_dialog_taskbar_close_handling(qtbot):
    from PyQt6.QtWidgets import QMainWindow
    import sys
    parent_win = QMainWindow()
    qtbot.addWidget(parent_win)
    parent_win.show()

    dlg = CourseImportDialog(parent_win)
    qtbot.addWidget(dlg)

    # Test thread cancel cleanup
    mock_thread = MagicMock()
    mock_thread.isRunning.return_value = True
    dlg.import_thread = mock_thread

    # Call _handle_taskbar_close
    dlg._handle_taskbar_close()

    assert mock_thread.requestInterruption.called
    assert dlg.result() == 0  # Rejected




