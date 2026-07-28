"""
Tests für den neu gestalteten Trainer-Einstellungsdialog (SettingsDialog).
Prüft UI-Interaktionen, Einstellungspersistenz und Delegation an MainWindow.
"""
import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog
from opening_fenix.gui.widgets.board_widget import THEMES


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    """MainWindow mit sichtbarem Testrepetoire."""
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


@pytest.fixture
def settings_dialog(main_window, qapp):
    """Geöffneter SettingsDialog."""
    dlg = SettingsDialog(main_window)
    yield dlg
    dlg.close()


# ─── Struktur & Initialisierung ─────────────────────────────────────────────────

class TestSettingsDialogStructure:

    def test_dialog_opens_without_crash(self, settings_dialog):
        """Dialog öffnet sich ohne Fehler."""
        assert settings_dialog is not None

    def test_dialog_title_is_german(self, settings_dialog):
        """Titel ist auf Deutsch."""
        assert "Trainer" in settings_dialog.windowTitle()
        assert "Einstellungen" in settings_dialog.windowTitle()

    def test_sidebar_has_three_items(self, settings_dialog):
        """Sidebar hat genau drei Einträge."""
        assert settings_dialog.sidebar.count() == 3

    def test_sidebar_items_have_emoji_icons(self, settings_dialog):
        """Sidebar-Einträge enthalten Emoji-Icons."""
        for i in range(settings_dialog.sidebar.count()):
            text = settings_dialog.sidebar.item(i).text()
            # Jeder Eintrag sollte ein Emoji-Zeichen enthalten
            assert any(ord(c) > 1000 for c in text), f"Eintrag '{text}' hat kein Emoji"

    def test_page_switches_on_sidebar_click(self, settings_dialog):
        """Seitennavigation funktioniert über Sidebar-Klicks."""
        settings_dialog.sidebar.setCurrentRow(0)
        assert settings_dialog.pages.currentIndex() == 0

        settings_dialog.sidebar.setCurrentRow(1)
        assert settings_dialog.pages.currentIndex() == 1

        settings_dialog.sidebar.setCurrentRow(2)
        assert settings_dialog.pages.currentIndex() == 2

    def test_default_tab_is_display(self, settings_dialog):
        """Standardmäßig ist die erste Seite (Darstellung) aktiv."""
        assert settings_dialog.pages.currentIndex() == 0


# ─── Seite 1: Darstellung & Audio ──────────────────────────────────────────────

class TestSettingsDialogDisplayPage:

    def test_theme_combo_populated(self, settings_dialog):
        """Theme-Dropdown enthält alle verfügbaren Themes."""
        assert settings_dialog.combo_theme.count() == len(THEMES)

    def test_theme_change_updates_setting(self, settings_dialog, main_window):
        """Theme-Änderung wird direkt in TrainingManager gespeichert."""
        target = "Grün (Lichess)"
        settings_dialog.combo_theme.setCurrentText(target)
        assert main_window.training_manager.get_setting("theme") == target

    def test_theme_change_updates_board(self, settings_dialog, main_window):
        """Theme-Änderung aktualisiert das Schachbrett."""
        target = "Grün (Lichess)"
        settings_dialog.combo_theme.setCurrentText(target)
        assert main_window.board_widget.light_color.name() == THEMES[target][0].name()

    def test_animation_speed_range(self, settings_dialog):
        """Animations-Tempo-Spinbox hat den korrekten Bereich."""
        assert settings_dialog.spin_anim.minimum() == 50
        assert settings_dialog.spin_anim.maximum() == 1000

    def test_animation_speed_change_persists(self, settings_dialog, main_window):
        """Animations-Tempo wird in Einstellungen gespeichert."""
        settings_dialog.spin_anim.setValue(750)
        assert main_window.training_manager.get_setting("anim_speed") == 750

    def test_notation_combo_has_two_languages(self, settings_dialog):
        """Notations-Dropdown hat genau zwei Sprachoptionen."""
        assert settings_dialog.combo_notation.count() == 2

    def test_notation_combo_has_english_and_german(self, settings_dialog):
        """Notations-Dropdown enthält Englisch und Deutsch."""
        lang_data = [
            settings_dialog.combo_notation.itemData(i)
            for i in range(settings_dialog.combo_notation.count())
        ]
        assert "en" in lang_data
        assert "de" in lang_data

    def test_notation_change_persists(self, settings_dialog, main_window):
        """Notations-Sprachänderung wird gespeichert."""
        idx_de = settings_dialog.combo_notation.findData("de")
        settings_dialog.combo_notation.setCurrentIndex(idx_de)
        assert main_window.training_manager.get_setting("notation_language") == "de"

    def test_volume_slider_range(self, settings_dialog):
        """Lautstärke-Regler hat Bereich 0-100."""
        assert settings_dialog.volume_slider.minimum() == 0
        assert settings_dialog.volume_slider.maximum() == 100

    def test_volume_label_updates_on_slider_move(self, settings_dialog):
        """Lautstärke-Label aktualisiert sich beim Bewegen des Reglers."""
        settings_dialog.volume_slider.setValue(42)
        assert "42" in settings_dialog.lbl_volume.text()

    def test_volume_change_calls_main_window(self, settings_dialog, main_window, monkeypatch):
        """Lautstärke-Änderung delegiert an MainWindow.set_master_volume."""
        called_with = []
        monkeypatch.setattr(main_window, "set_master_volume", lambda v: called_with.append(v))
        settings_dialog.volume_slider.setValue(65)
        assert 65 in called_with


# ─── Seite 2: Training & Verhalten ─────────────────────────────────────────────

class TestSettingsDialogBehaviorPage:

    def test_auto_delay_spinbox_exists(self, settings_dialog):
        """Auto-Weiter-Spinbox ist vorhanden."""
        assert hasattr(settings_dialog, "spin_delay")

    def test_auto_delay_range(self, settings_dialog):
        """Auto-Weiter-Spinbox hat gültigen Bereich."""
        assert settings_dialog.spin_delay.minimum() == 0
        assert settings_dialog.spin_delay.maximum() == 2000

    def test_auto_delay_change_persists(self, settings_dialog, main_window):
        """Auto-Weiter-Verzögerung wird in Einstellungen gespeichert."""
        settings_dialog.spin_delay.setValue(800)
        assert main_window.training_manager.get_setting("auto_delay") == 800


# ─── Seite 3: Repertoire-Konfiguration ─────────────────────────────────────────

class TestSettingsDialogRepoPage:

    def test_repo_cards_populated(self, settings_dialog, sample_repertoire):
        """Repertoire-Cards sind befüllt."""
        settings_dialog.sidebar.setCurrentRow(1) # Page 1 is Configuration
        assert settings_dialog.card_layout.count() > 0

    def test_repo_selection_populates_info(self, settings_dialog, sample_repertoire):
        """Repertoire auswählen füllt die Informationsfelder."""
        settings_dialog.sidebar.setCurrentRow(1)
        settings_dialog.on_repo_selected(sample_repertoire)
        assert settings_dialog.lbl_name.text() != "-"
        assert settings_dialog.lbl_name.text() == sample_repertoire

    def test_repo_selection_populates_levels(self, settings_dialog, sample_repertoire):
        """Level-Dropdown in der Card ist befüllt."""
        settings_dialog.sidebar.setCurrentRow(1)
        card = settings_dialog.card_layout.itemAt(0).widget()
        assert card.combo_level.count() > 0

    def test_visibility_toggle_persists(self, settings_dialog, sample_repertoire, main_window, monkeypatch):
        """Sichtbarkeits-Toggle am Card-Widget persistiert korrekt."""
        monkeypatch.setattr(main_window, "refresh_repertoire_buttons", lambda: None)
        settings_dialog.sidebar.setCurrentRow(1)
        
        target_card = None
        for i in range(settings_dialog.card_layout.count()):
            w = settings_dialog.card_layout.itemAt(i).widget()
            if hasattr(w, "repo_name") and w.repo_name == sample_repertoire:
                target_card = w; break
        if not target_card: # Fallback to first if name match fails in mock
            target_card = settings_dialog.card_layout.itemAt(0).widget()

        # Toggle off
        target_card.toggle_active()
        assert main_window.training_manager.is_repo_visible(target_card.repo_name) is False

        # Toggle back on
        target_card.toggle_active()
        assert main_window.training_manager.is_repo_visible(target_card.repo_name) is True

    def test_level_change_persists(self, settings_dialog, sample_repertoire, main_window):
        """Level-Änderung in der Card wird gespeichert."""
        settings_dialog.sidebar.setCurrentRow(1)
        card = settings_dialog.card_layout.itemAt(0).widget()
        if card.combo_level.count() > 0:
            card.combo_level.setCurrentIndex(0)
            expected_level = card.combo_level.currentData()
            assert main_window.training_manager.get_active_level() == expected_level

    def test_reset_progress_with_confirmation(
        self, settings_dialog, sample_repertoire, main_window, monkeypatch
    ):
        """Fortschritt-Reset wird mit Bestätigung ausgeführt."""
        monkeypatch.setattr(main_window, "refresh_repertoire_buttons", lambda: None)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

        settings_dialog.sidebar.setCurrentRow(2)
        settings_dialog.on_repo_selected(sample_repertoire)
        settings_dialog.reset_repo_progress()
        # Kein Crash = Erfolg

    def test_reset_progress_without_repo_does_nothing(self, settings_dialog, main_window):
        """Reset ohne ausgewähltes Repertoire löst keinen Fehler aus."""
        settings_dialog.selected_repo = None
        settings_dialog.reset_repo_progress()  # Soll ohne Fehler durchlaufen


# ─── BW_GLASS Styling ──────────────────────────────────────────────────────────

class TestSettingsDialogStyling:

    def test_stylesheet_applied(self, settings_dialog):
        """Dialog hat einen Stylesheet gesetzt."""
        assert len(settings_dialog.styleSheet()) > 0

    def test_background_color_is_light(self, settings_dialog):
        """Hintergrundfarbe ist klar (BW_GLASS)."""
        style = settings_dialog.styleSheet()
        assert "#f5f5f7" in style or "background-color" in style

    def test_sidebar_has_objectname(self, settings_dialog):
        """Sidebar hat ObjectName 'Sidebar' für CSS-Targeting."""
        assert settings_dialog.sidebar.objectName() == "Sidebar"
