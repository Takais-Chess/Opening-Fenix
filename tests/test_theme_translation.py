import pytest
from opening_fenix.core.translation import translator, tr_ui
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES, THEME_FALLBACKS
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog

def test_theme_translation_strings():
    """Verify that theme translation keys exist for both DE and EN."""
    translator.load_language("de")
    assert tr_ui("themes.Dunkel (Modern)") == "Dunkel (Modern)"
    assert tr_ui("themes.Grün (Lichess)") == "Grün (Lichess)"
    assert tr_ui("themes.Braun (Klassisch)") == "Braun (Klassisch)"
    assert tr_ui("themes.Blau (Turnier)") == "Blau (Turnier)"
    assert tr_ui("themes.Grau (Neutral)") == "Grau (Neutral)"
    assert tr_ui("themes.Icy Sea") == "Icy Sea"

    translator.load_language("en")
    assert tr_ui("themes.Dunkel (Modern)") == "Dark (Modern)"
    assert tr_ui("themes.Grün (Lichess)") == "Green (Lichess)"
    assert tr_ui("themes.Braun (Klassisch)") == "Brown (Classic)"
    assert tr_ui("themes.Blau (Turnier)") == "Blue (Tournament)"
    assert tr_ui("themes.Grau (Neutral)") == "Grey (Neutral)"
    assert tr_ui("themes.Icy Sea") == "Icy Sea"

    # Reset back to German
    translator.load_language("de")

def test_board_widget_theme_fallbacks(qapp):
    """Verify ChessBoardWidget.set_theme accepts translated theme fallback names."""
    board = ChessBoardWidget()
    
    # German internal key
    board.set_theme("Grün (Lichess)")
    assert board.light_color == THEMES["Grün (Lichess)"][0]
    
    # English fallback name
    board.set_theme("Green (Lichess)")
    assert board.light_color == THEMES["Grün (Lichess)"][0]

    board.set_theme("Dark (Modern)")
    assert board.light_color == THEMES["Dunkel (Modern)"][0]

from opening_fenix.gui.main_window import MainWindow

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

def test_settings_dialog_theme_combo_translation(main_window, qapp):
    """Verify SettingsDialog displays translated theme names when UI language is English."""
    translator.load_language("en")
    try:
        dlg = SettingsDialog(main_window)
        # Check that translated item texts appear in combo box
        items = [dlg.combo_theme.itemText(i) for i in range(dlg.combo_theme.count())]
        assert "Dark (Modern)" in items
        assert "Blue (Tournament)" in items
        assert "Green (Lichess)" in items

        # Change index to 'Dark (Modern)'
        dark_idx = items.index("Dark (Modern)")
        dlg.combo_theme.setCurrentIndex(dark_idx)

        # Internal setting should be saved as internal key "Dunkel (Modern)"
        assert main_window.training_manager.get_setting("theme") == "Dunkel (Modern)"
        assert main_window.board_widget.light_color == THEMES["Dunkel (Modern)"][0]
        dlg.close()
    finally:
        translator.load_language("de")
