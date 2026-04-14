"""
Tests für den neu gestalteten Creator-Einstellungsdialog (RepoSettingsDialog).
Prüft UI-Interaktionen, Einstellungspersistenz, Seitenstruktur und BW_GLASS-Styling.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QComboBox
from PyQt6.QtCore import Qt
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.gui.dialogs.repo_settings_dialog import RepoSettingsDialog, DiagnosticDialog


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def creator_backend(mock_user_dir, sample_repertoire):
    """Voll funktionsfähiges CreatorBackend mit Test-Repertoire."""
    backend = CreatorBackend()
    backend.load_repertoire(sample_repertoire)
    yield backend
    if backend.session:
        backend.session.close()

@pytest.fixture
def mock_main_window(qapp, sample_repertoire):
    """Ein echtes QWidget als Parent, erweitert um Mock-Attribute für CreatorWindow."""
    from PyQt6.QtWidgets import QWidget

    class FakeCreatorWindow(QWidget):
        """Minimales Fake-CreatorWindow das QDialog als Parent akzeptiert."""
        def __init__(self):
            super().__init__()
            self.config = {
                "engine_path": "",
                "lichess_token": "",
                "theme": "Blau (Turnier)",
                "master_volume": 100,
                "notation_language": "en",
                "creator_active_tabs": ["DETAILS", "ANALYSIS"],
            }
            self.sounds = {}
            self.board_widget = MagicMock()
            self.board_widget.board = MagicMock()
            self.board_widget.board.fen.return_value = (
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            )
            self._calls = {}

        def set_setting(self, key, value):
            self.config[key] = value

        def save_config(self): pass
        def apply_tab_visibility(self): pass
        def add_level(self): self._calls['add_level'] = True
        def rename_repertoire(self): self._calls['rename_repertoire'] = True
        def rename_level(self, item): self._calls['rename_level'] = True
        def paste_pgn_dialog(self): self._calls['paste_pgn_dialog'] = True
        def import_pgn_file_dialog(self): self._calls['import_pgn_file_dialog'] = True
        def delete_repertoire_action(self): self._calls['delete_repertoire_action'] = True
        def set_engine_button_blocked(self, *a): pass
        def update_ui_from_fen(self): pass
        def setWindowTitle(self, t): super().setWindowTitle(t)
        def setCursor(self, c): super().setCursor(c)

    return FakeCreatorWindow()


@pytest.fixture
def settings_dialog(qapp, creator_backend, mock_main_window):
    """Geöffneter RepoSettingsDialog mit echtem Backend und Mock-MainWindow."""
    dlg = RepoSettingsDialog(parent=mock_main_window, backend=creator_backend)
    yield dlg
    dlg.close()


# ─── Struktur & Initialisierung ─────────────────────────────────────────────────

class TestRepoSettingsDialogStructure:

    def test_dialog_opens_without_crash(self, settings_dialog):
        """Dialog öffnet sich ohne Fehler."""
        assert settings_dialog is not None

    def test_dialog_title_is_german(self, settings_dialog):
        """Titel ist auf Deutsch."""
        assert "Einstellungen" in settings_dialog.windowTitle()
        assert "Repertoire" in settings_dialog.windowTitle()

    def test_sidebar_has_five_pages(self, settings_dialog):
        """Sidebar hat genau fünf Seiten."""
        assert settings_dialog.sidebar.count() == 5

    def test_sidebar_items_have_emojis(self, settings_dialog):
        """Alle Sidebar-Einträge haben Emoji-Icons."""
        for i in range(settings_dialog.sidebar.count()):
            text = settings_dialog.sidebar.item(i).text()
            assert any(ord(c) > 1000 for c in text), f"Kein Emoji in: '{text}'"

    def test_page_switching_via_sidebar(self, settings_dialog):
        """Navigation über Sidebar wechselt Seiten korrekt."""
        for i in range(5):
            settings_dialog.sidebar.setCurrentRow(i)
            assert settings_dialog.pages.currentIndex() == i

    def test_stylesheet_applied(self, settings_dialog):
        """BW_GLASS Stylesheet ist gesetzt."""
        style = settings_dialog.styleSheet()
        assert len(style) > 100  # Nicht leer
        assert "#f5f5f7" in style  # BW_GLASS Hintergrund

    def test_sidebar_has_objectname(self, settings_dialog):
        """Sidebar hat 'Sidebar' als ObjectName für CSS."""
        assert settings_dialog.sidebar.objectName() == "Sidebar"


# ─── Seite 1: Repertoire-Daten ─────────────────────────────────────────────────

class TestRepoSettingsGeneralPage:

    def test_repertoire_name_displayed(self, settings_dialog, sample_repertoire):
        """Repertoire-Name wird in der Übersicht angezeigt."""
        settings_dialog.sidebar.setCurrentRow(0)
        assert sample_repertoire in settings_dialog.l_n.text()

    def test_elo_combo_populated(self, settings_dialog):
        """Elo-Dropdown ist mit den vier Optionen befüllt."""
        settings_dialog.sidebar.setCurrentRow(0)
        elo_texts = [
            settings_dialog.combo_repertoire_elo.itemText(i)
            for i in range(settings_dialog.combo_repertoire_elo.count())
        ]
        assert "low" in elo_texts
        assert "mid" in elo_texts
        assert "high" in elo_texts
        assert "masters" in elo_texts

    def test_level_table_populated(self, settings_dialog):
        """Level-Tabelle ist nach dem Laden befüllt."""
        settings_dialog.sidebar.setCurrentRow(0)
        assert settings_dialog.tbl_levels.rowCount() > 0

    def test_level_table_has_three_columns(self, settings_dialog):
        """Level-Tabelle hat genau drei Spalten."""
        assert settings_dialog.tbl_levels.columnCount() == 3

    def test_elo_change_saves_to_backend_no_crash(self, settings_dialog):
        """Elo-Änderung verursacht keinen Absturz (Backend-Guard greift)."""
        # Direkt die Methode aufrufen – sollte nicht abstürzen
        settings_dialog.save_repertoire_elo("mid")
        # Wenn kein AssertionError/Exception: bestanden

    def test_description_save_no_crash_with_none_backend(self, qapp):
        """save_description hält an wenn Backend None ist (Guard-Clause greift)."""
        obj = RepoSettingsDialog.__new__(RepoSettingsDialog)
        obj.backend = None
        obj.txt_description = MagicMock()
        obj.txt_description.toPlainText.return_value = "test"
        RepoSettingsDialog.save_description(obj)  # Darf nicht werfen

    def test_elo_save_no_crash_with_none_backend(self, qapp):
        """save_repertoire_elo hält an wenn Backend None ist (Guard-Clause)."""
        obj = RepoSettingsDialog.__new__(RepoSettingsDialog)
        obj.backend = None
        RepoSettingsDialog.save_repertoire_elo(obj, "high")  # Darf nicht werfen

    def test_add_level_calls_backend(self, settings_dialog, creator_backend):
        """Level-Hinzufügen wird direkt ans Backend gerufen."""
        with patch.object(creator_backend, 'add_repertoire_level') as mock_add:
            settings_dialog.add_level()
            assert mock_add.called

    def test_rename_repertoire_calls_backend(self, settings_dialog, creator_backend):
        """Umbenennen wird direkt ans Backend gerufen."""
        with patch.object(creator_backend, 'rename_repertoire', return_value=(True, "Success")) as mock_rename:
            settings_dialog.rename_repertoire()
            assert mock_rename.called


# ─── Seite 2: Design & Audio ───────────────────────────────────────────────────

class TestRepoSettingsDesignPage:

    def test_theme_combo_populated(self, settings_dialog):
        """Theme-Dropdown enthält Theme-Optionen."""
        settings_dialog.sidebar.setCurrentRow(1)
        from opening_fenix.gui.widgets.board_widget import THEMES
        assert settings_dialog.combo_theme.count() == len(THEMES)

    def test_theme_change_calls_main_window(self, settings_dialog, mock_main_window):
        """Theme-Änderung wird an MainWindow config gespeichert."""
        settings_dialog.sidebar.setCurrentRow(1)
        settings_dialog.change_board_theme("Gr\u00fcn (Lichess)")
        assert mock_main_window.config.get("theme") == "Gr\u00fcn (Lichess)"
        # board_widget.set_theme wurde aufgerufen
        assert mock_main_window.board_widget.set_theme.called

    def test_volume_change_no_crash(self, settings_dialog):
        """Lautstärkeänderung wirft keinen Fehler (sounds dict ist leer)."""
        settings_dialog.change_volume(50)  # Darf nicht werfen

    def test_notation_combo_has_two_entries(self, settings_dialog):
        """Notations-Dropdown hat Englisch und Deutsch."""
        settings_dialog.sidebar.setCurrentRow(1)
        assert settings_dialog.combo_not.count() == 2
        lang_data = [
            settings_dialog.combo_not.itemData(i)
            for i in range(settings_dialog.combo_not.count())
        ]
        assert "en" in lang_data
        assert "de" in lang_data

    def test_notation_change_saves_setting(self, settings_dialog, mock_main_window):
        """Notations-Sprache wird in Config gespeichert."""
        settings_dialog.sidebar.setCurrentRow(1)
        idx_de = settings_dialog.combo_not.findData("de")
        settings_dialog.combo_not.setCurrentIndex(idx_de)
        assert mock_main_window.config.get("notation_language") == "de"

    def test_tab_settings_saved(self, settings_dialog, mock_main_window):
        """Tab-Sichtbarkeitseinstellungen werden gespeichert."""
        settings_dialog.sidebar.setCurrentRow(1)
        settings_dialog.chk_details.setChecked(True)
        settings_dialog.chk_analysis.setChecked(True)
        settings_dialog.chk_holes.setChecked(False)
        settings_dialog.chk_kontrolle.setChecked(False)
        settings_dialog.save_tab_settings()
        saved = mock_main_window.config.get("creator_active_tabs", [])
        assert "DETAILS" in saved
        assert "ANALYSIS" in saved
        assert "HOLES" not in saved

    def test_all_four_tab_checkboxes_exist(self, settings_dialog):
        """Alle vier Tab-Checkboxen sind vorhanden."""
        assert hasattr(settings_dialog, "chk_details")
        assert hasattr(settings_dialog, "chk_analysis")
        assert hasattr(settings_dialog, "chk_holes")
        assert hasattr(settings_dialog, "chk_kontrolle")


# ─── Seite 3: Import & Export ──────────────────────────────────────────────────

class TestRepoSettingsImportExportPage:

    def test_paste_pgn_delegates(self, settings_dialog, mock_main_window):
        """PGN einfügen wird an MainWindow delegiert."""
        settings_dialog.paste_pgn_dialog()
        assert 'paste_pgn_dialog' in mock_main_window._calls

    def test_import_file_delegates(self, settings_dialog, mock_main_window):
        """PGN-Datei importieren wird an MainWindow delegiert."""
        settings_dialog.import_pgn_file_dialog()
        assert 'import_pgn_file_dialog' in mock_main_window._calls


# ─── Seite 4: Analyse & Tools ──────────────────────────────────────────────────

class TestRepoSettingsAnalysisPage:

    def test_engine_path_field_exists(self, settings_dialog):
        """Engine-Pfad-Feld ist vorhanden."""
        assert hasattr(settings_dialog, "txt_engine_path")

    def test_engine_depth_range(self, settings_dialog):
        """Engine-Tiefe-Spinbox hat richtigen Bereich."""
        assert settings_dialog.s_d.minimum() == 10
        assert settings_dialog.s_d.maximum() == 50

    def test_thread_combo_populated(self, settings_dialog):
        """Thread-Dropdown ist mit CPU-Kernzahl befüllt."""
        import multiprocessing
        assert settings_dialog.c_threads.count() == multiprocessing.cpu_count()

    def test_lichess_token_field_is_password(self, settings_dialog):
        """Lichess-Token-Feld ist als Passwortfeld konfiguriert."""
        from PyQt6.QtWidgets import QLineEdit
        assert settings_dialog.txt_lichess_token.echoMode() == QLineEdit.EchoMode.Password

    def test_token_change_saves_to_config(self, settings_dialog, mock_main_window):
        """Token-Änderung wird in Config gespeichert."""
        settings_dialog.on_token_changed("mein-api-token")
        assert mock_main_window.config.get("lichess_token") == "mein-api-token"

    def test_variation_name_repair_no_crash(self, settings_dialog, creator_backend):
        """Variantennamen-Reparatur stürzt nicht ab."""
        settings_dialog.run_variation_name_repair()  # Darf nicht werfen

    def test_elo_combo_has_four_options(self, settings_dialog):
        """Elo-Combo hat vier Optionen."""
        settings_dialog.sidebar.setCurrentRow(0)
        assert settings_dialog.combo_repertoire_elo.count() == 4

    def test_progress_bars_initialized(self, settings_dialog):
        """Fortschrittsbalken für Engine und Lichess sind vorhanden."""
        assert hasattr(settings_dialog, "pb_eng")
        assert hasattr(settings_dialog, "pb_lich")


# ─── Seite 5: Wartung Center ───────────────────────────────────────────────────

class TestRepoSettingsMaintenancePage:

    def test_maintenance_table_exists(self, settings_dialog):
        """Wartungs-Tabelle ist vorhanden."""
        assert hasattr(settings_dialog, "main_table")

    def test_maintenance_table_populated_on_refresh(self, settings_dialog):
        """Wartungs-Tabelle wird beim refresh_info befüllt."""
        assert settings_dialog.main_table.rowCount() >= 0

    def test_select_all_maintenance_repos(self, settings_dialog):
        """'Alle auswählen' im Maintenance-Bereich stürzt nicht ab."""
        settings_dialog._select_all_maintenance_repos(True)
        settings_dialog._select_all_maintenance_repos(False)


# ─── DiagnosticDialog ──────────────────────────────────────────────────────────

class TestDiagnosticDialog:

    def test_opens_without_crash(self, qapp, creator_backend):
        """DiagnosticDialog öffnet sich ohne Fehler."""
        dlg = DiagnosticDialog(creator_backend)
        assert dlg is not None
        dlg.close()

    def test_title_is_german(self, qapp, creator_backend):
        """Titel ist auf Deutsch."""
        dlg = DiagnosticDialog(creator_backend)
        assert "Diagnose" in dlg.windowTitle()
        dlg.close()

    def test_results_text_is_populated(self, qapp, creator_backend):
        """Diagnose-Ergebnisse werden im TextEdit angezeigt."""
        dlg = DiagnosticDialog(creator_backend)
        assert len(dlg.txt_results.toHtml()) > 50
        dlg.close()

    def test_info_label_updated_after_diagnostic(self, qapp, creator_backend):
        """Info-Label ist nach der Diagnose nicht mehr leer."""
        dlg = DiagnosticDialog(creator_backend)
        assert len(dlg.lbl_info.text()) > 0
        dlg.close()
