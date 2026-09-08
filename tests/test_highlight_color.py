import pytest
from PyQt6.QtGui import QColor
from opening_fenix.core.translation import translator, tr_ui
from opening_fenix.gui.widgets.board_widget import (
    ChessBoardWidget, HIGHLIGHT_COLORS, HIGHLIGHT_COLOR_FALLBACKS
)
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog
from opening_fenix.gui.main_window import MainWindow


def test_highlight_color_translation_strings():
    """Verify that highlight color translation keys exist for both DE and EN."""
    translator.load_language("de")
    assert tr_ui("settings.highlight_color") == "Farbe Zug-Hervorhebung:"
    assert tr_ui("highlight_colors.Gelb (Standard)") == "Gelb (Standard)"
    assert tr_ui("highlight_colors.Grün") == "Grün"
    assert tr_ui("highlight_colors.Blau") == "Blau"
    assert tr_ui("highlight_colors.Orange") == "Orange"
    assert tr_ui("highlight_colors.Burnt Orange") == "Burnt Orange"
    assert tr_ui("highlight_colors.Rot") == "Rot"
    assert tr_ui("highlight_colors.Lila") == "Lila"
    assert tr_ui("highlight_colors.Türkis") == "Türkis"

    translator.load_language("en")
    assert tr_ui("settings.highlight_color") == "Move Highlight Color:"
    assert tr_ui("highlight_colors.Gelb (Standard)") == "Yellow (Default)"
    assert tr_ui("highlight_colors.Grün") == "Green"
    assert tr_ui("highlight_colors.Blau") == "Blue"
    assert tr_ui("highlight_colors.Orange") == "Orange"
    assert tr_ui("highlight_colors.Burnt Orange") == "Burnt Orange"
    assert tr_ui("highlight_colors.Rot") == "Red"
    assert tr_ui("highlight_colors.Lila") == "Purple"
    assert tr_ui("highlight_colors.Türkis") == "Turquoise"

    # Reset back to German
    translator.load_language("de")


def test_board_widget_highlight_colors_and_fallbacks(qapp):
    """Verify ChessBoardWidget.set_highlight_color accepts internal keys, fallbacks, QColors, and hex."""
    board = ChessBoardWidget()

    # Default is Yellow
    assert board.highlight_color == HIGHLIGHT_COLORS["Gelb (Standard)"]

    # German internal key
    board.set_highlight_color("Grün")
    assert board.highlight_color == HIGHLIGHT_COLORS["Grün"]

    board.set_highlight_color("Burnt Orange")
    assert board.highlight_color == HIGHLIGHT_COLORS["Burnt Orange"]

    # English fallback name
    board.set_highlight_color("Amber")
    assert board.highlight_color == HIGHLIGHT_COLORS["Burnt Orange"]

    board.set_highlight_color("Bernstein")
    assert board.highlight_color == HIGHLIGHT_COLORS["Burnt Orange"]

    board.set_highlight_color("Blue")
    assert board.highlight_color == HIGHLIGHT_COLORS["Blau"]

    board.set_highlight_color("Yellow (Default)")
    assert board.highlight_color == HIGHLIGHT_COLORS["Gelb (Standard)"]

    board.set_highlight_color("Purple")
    assert board.highlight_color == HIGHLIGHT_COLORS["Lila"]

    # Direct QColor
    custom_color = QColor(100, 150, 200, 120)
    board.set_highlight_color(custom_color)
    assert board.highlight_color == custom_color

    # Hex string
    board.set_highlight_color("#123456")
    assert board.highlight_color == QColor("#123456")

    # Unknown string falls back to default Yellow
    board.set_highlight_color("unknown_color")
    assert board.highlight_color == HIGHLIGHT_COLORS["Gelb (Standard)"]


@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    profile_name = "TestUser"
    from opening_fenix.core.training import TrainingManager
    from opening_fenix.core.repertoire import RepertoireManager
    rm = RepertoireManager(profile_name=profile_name)
    tm = TrainingManager(profile_name=profile_name, repertoire_manager=rm)
    tm.set_repo_visibility(sample_repertoire, True)
    tm.close()
    rm.close()

    win = MainWindow(profile_name)
    win.show()
    yield win
    win.close()


def test_settings_dialog_highlight_combo_translation(main_window, qapp):
    """Verify SettingsDialog displays translated highlight color names when UI language is English."""
    translator.load_language("en")
    try:
        dlg = SettingsDialog(main_window)
        assert hasattr(dlg, "combo_highlight")
        items = [dlg.combo_highlight.itemText(i) for i in range(dlg.combo_highlight.count())]
        assert "Yellow (Default)" in items
        assert "Green" in items
        assert "Blue" in items
        assert "Orange" in items
        assert "Burnt Orange" in items
        assert "Red" in items
        assert "Purple" in items
        assert "Turquoise" in items

        # Select 'Blue' in the combo box
        blue_idx = items.index("Blue")
        dlg.combo_highlight.setCurrentIndex(blue_idx)

        # Internal setting should be saved as internal key "Blau"
        assert main_window.training_manager.get_setting("highlight_color") == "Blau"
        assert main_window.board_widget.highlight_color == HIGHLIGHT_COLORS["Blau"]
        dlg.close()
    finally:
        translator.load_language("de")
