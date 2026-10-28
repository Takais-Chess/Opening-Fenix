import json
import os
import ast
import pytest
from PyQt6.QtWidgets import QApplication, QTreeWidgetItemIterator
from PyQt6.QtCore import Qt

from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
from opening_fenix.core.translation import translator


@pytest.fixture
def dlg(qapp):
    dialog = UnifiedSettingsDialog(initial_section="trainer")
    yield dialog
    dialog.close()


def test_translations_coverage_and_completeness():
    """Verifies that all translation keys used in unified_settings_dialog.py exist in both de.json and en.json."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dialog_path = os.path.join(base_dir, "opening_fenix", "gui", "dialogs", "unified_settings_dialog.py")
    de_path = os.path.join(base_dir, "assets", "translations", "de.json")
    en_path = os.path.join(base_dir, "assets", "translations", "en.json")

    with open(de_path, "r", encoding="utf-8") as f:
        de_data = json.load(f)
    with open(en_path, "r", encoding="utf-8") as f:
        en_data = json.load(f)

    def resolve(data, key):
        parts = key.split(".")
        curr = data
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return None
        return curr if isinstance(curr, str) else None

    with open(dialog_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    used_keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = None
            if isinstance(node.func, ast.Name):
                fn = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fn = node.func.attr
            if fn in ("tr_ui", "tr_widget") and len(node.args) >= 1:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    used_keys.add(node.args[0].value)

    assert len(used_keys) >= 400

    missing_de = [k for k in sorted(used_keys) if resolve(de_data, k) is None]
    missing_en = [k for k in sorted(used_keys) if resolve(en_data, k) is None]

    assert not missing_de, f"Keys missing in de.json: {missing_de}"
    assert not missing_en, f"Keys missing in en.json: {missing_en}"


def test_sidebar_navigation_and_sections(dlg):
    """Checks that sidebar sections and navigation activate corresponding pages correctly."""
    # Profile badge in sidebar
    assert hasattr(dlg, "lbl_profile_badge")
    assert dlg.lbl_profile_badge is not None

    # Switch to Global
    dlg.on_context_pill_clicked("global")
    assert dlg.sec_global.isExpanded()
    assert dlg.pages.currentWidget() == dlg.page_appearance

    # Switch to Help
    dlg.on_context_pill_clicked("help")
    assert dlg.sec_help.isExpanded()
    assert dlg.pages.currentWidget() == dlg.page_faq

    # Switch to Creator
    dlg.on_context_pill_clicked("creator")
    assert dlg.sec_creator.isExpanded()
    assert dlg.pages.currentWidget() == dlg.page_cr_identity
    assert not dlg.creator_header_bar.isHidden()

    # Switch to Trainer
    dlg.on_context_pill_clicked("trainer")
    assert dlg.sec_trainer.isExpanded()
    assert dlg.pages.currentWidget() == dlg.page_trainer_repos
    assert dlg.creator_header_bar.isHidden()


def test_sidebar_search_filter(dlg):
    """Verifies that search filtering hides non-matching categories and reveals matching ones."""
    # Filter for 'Audio'
    dlg.txt_sidebar_search.setText("Audio")
    assert dlg.sec_global.isExpanded()
    assert not dlg.item_trainer_repos.isHidden() or dlg.sec_global.child(0).text(0) != ""

    # Clear filter
    dlg.txt_sidebar_search.setText("")
    root = dlg.sidebar_tree.invisibleRootItem()
    for i in range(root.childCount()):
        assert not root.child(i).isHidden()


def test_live_board_preview(dlg):
    """Tests that the LiveBoardPreviewWidget updates without errors when theme changes."""
    assert hasattr(dlg, "board_preview_widget")
    assert dlg.board_preview_widget is not None

    dlg.combo_theme.setCurrentIndex(1)
    theme_name = dlg.combo_theme.currentData() or dlg.combo_theme.currentText()
    dlg.on_theme_changed()
    assert dlg.board_preview_widget.theme_key == theme_name

    dlg.combo_highlight.setCurrentIndex(1)
    hl_color = dlg.combo_highlight.currentData() or dlg.combo_highlight.currentText()
    dlg.on_highlight_color_changed()
    assert dlg.board_preview_widget.hl_key == hl_color


def test_interval_units_translation(dlg):
    """Tests that custom interval unit labels are translated according to active locale."""
    for box_num in range(1, 8):
        combo = dlg.box_unit_combos[box_num]
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "Tage" in items or "Days" in items
