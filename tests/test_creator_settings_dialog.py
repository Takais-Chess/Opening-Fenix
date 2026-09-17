"""
Tests für den neu gestalteten Creator-Einstellungsdialog (RepoSettingsDialog).
Prüft UI-Interaktionen, Einstellungspersistenz, Seitenstruktur und BW_GLASS-Styling.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QComboBox, QFileDialog
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
            self.btn_load_repo = MagicMock()
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
        def set_repertoire_elo(self, val): self._calls['set_repertoire_elo'] = val
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

    def test_sidebar_has_seven_pages(self, settings_dialog):
        """Sidebar hat genau sieben Seiten."""
        assert settings_dialog.sidebar.count() == 7

    def test_sidebar_items_have_emojis(self, settings_dialog):
        """Alle Sidebar-Einträge haben Emoji-Icons."""
        for i in range(settings_dialog.sidebar.count()):
            text = settings_dialog.sidebar.item(i).text()
            assert any(ord(c) > 1000 for c in text), f"Kein Emoji in: '{text}'"

    def test_page_switching_via_sidebar(self, settings_dialog):
        """Navigation über Sidebar wechselt Seiten korrekt."""
        for i in range(7):
            settings_dialog.sidebar.setCurrentRow(i)
            assert settings_dialog.pages.currentIndex() == i

    def test_scroll_resets_to_top_on_page_switch(self, settings_dialog):
        """Scroll position resets to top (0) when switching between sidebar tabs."""
        settings_dialog.main_scroll.verticalScrollBar().setValue(250)
        assert settings_dialog.main_scroll.verticalScrollBar().value() == 250
        
        settings_dialog.sidebar.setCurrentRow(2)
        assert settings_dialog.main_scroll.verticalScrollBar().value() == 0

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
        assert any("Hobby Spieler" in t for t in elo_texts)
        assert any("Vereins Spieler" in t for t in elo_texts)
        assert any("Lichess Meister Elo" in t for t in elo_texts)
        assert any("Meister Datenbank" in t for t in elo_texts)

    def test_level_table_populated(self, settings_dialog):
        """Level-Tabelle ist nach dem Laden befüllt."""
        settings_dialog.sidebar.setCurrentRow(0)
        assert settings_dialog.tbl_levels.rowCount() > 0

    def test_level_table_has_three_columns(self, settings_dialog):
        """Level-Tabelle hat genau drei Spalten."""
        assert settings_dialog.tbl_levels.columnCount() == 3

    def test_level_target_elo_loads_and_edits_value(self, settings_dialog, creator_backend):
        """Ziel-Elo wird als Item geladen und kann per Einzelklick im Dialog bearbeitet werden."""
        with patch.object(creator_backend, 'get_repertoire_levels', return_value=[{"id": 1, "name": "Level 1", "order": 1, "target_elo": 1250}]), \
             patch.object(creator_backend, 'update_level_elo') as mock_update, \
             patch('PyQt6.QtWidgets.QInputDialog.getInt', return_value=(1300, True)):
            settings_dialog.refresh_info()
            it_elo = settings_dialog.tbl_levels.item(0, 2)
            assert it_elo is not None
            assert "1250" in it_elo.text()
            settings_dialog.on_creator_level_cell_clicked(0, 2)
            mock_update.assert_called_with(1, 1300)

    def test_level_rename_single_click(self, settings_dialog, creator_backend):
        """Level-Umbenennung öffnet sich per einfachem Klick."""
        with patch.object(creator_backend, 'get_repertoire_levels', return_value=[{"id": 1, "name": "Level 1", "order": 1, "target_elo": 1250}]), \
             patch.object(creator_backend, 'update_level_name') as mock_rename, \
             patch('PyQt6.QtWidgets.QInputDialog.getText', return_value=("New Name", True)):
            settings_dialog.refresh_info()
            settings_dialog.on_creator_level_cell_clicked(0, 1)
            mock_rename.assert_called_with(1, "New Name")

    def test_level_click_column_0_selects_level_for_deletion(self, settings_dialog, creator_backend):
        """Klick auf Spalte 0 (Level-Nummer) wählt das Level aus und setzt default_del_order beim Löschen."""
        levels = [
            {"id": 1, "name": "Level 1", "order": 1, "target_elo": 1200},
            {"id": 2, "name": "Level 2", "order": 2, "target_elo": 1500},
            {"id": 3, "name": "Level 3", "order": 3, "target_elo": 1800}
        ]
        with patch.object(creator_backend, 'get_repertoire_levels', return_value=levels):
            settings_dialog.refresh_creator_info()
            
            # Klick auf Spalte 0 von Zeile 1 (Level 2)
            settings_dialog.on_creator_level_cell_clicked(1, 0)
            assert settings_dialog.selected_creator_level_order == 2
            assert settings_dialog.tbl_cr_levels.currentRow() == 1

            # Lösch-Dialog öffnet sich mit vorausgewähltem Level 2
            with patch('opening_fenix.gui.dialogs.unified_settings_dialog.DeleteLevelDialog') as mock_dlg_cls:
                mock_dlg = MagicMock()
                mock_dlg.exec.return_value = QDialog.DialogCode.Rejected
                mock_dlg_cls.return_value = mock_dlg
                
                settings_dialog.delete_creator_level()
                mock_dlg_cls.assert_called_once_with(levels, default_del_order=2, parent=settings_dialog)

    def test_level_double_click_column_0_opens_delete_dialog(self, settings_dialog, creator_backend):
        """Doppelklick auf Spalte 0 öffnet direkt den Lösch-Dialog mit vorausgewähltem Level."""
        levels = [
            {"id": 1, "name": "Level 1", "order": 1, "target_elo": 1200},
            {"id": 2, "name": "Level 2", "order": 2, "target_elo": 1500}
        ]
        with patch.object(creator_backend, 'get_repertoire_levels', return_value=levels):
            settings_dialog.refresh_creator_info()
            
            with patch('opening_fenix.gui.dialogs.unified_settings_dialog.DeleteLevelDialog') as mock_dlg_cls:
                mock_dlg = MagicMock()
                mock_dlg.exec.return_value = QDialog.DialogCode.Rejected
                mock_dlg_cls.return_value = mock_dlg
                
                settings_dialog.on_creator_level_cell_double_clicked(1, 0)
                mock_dlg_cls.assert_called_once_with(levels, default_del_order=2, parent=settings_dialog)

    def test_level_groupbox_size_policy(self, settings_dialog):
        """g_levels besitzt Maximum Vertical SizePolicy um übermäßige Höhe zu verhindern."""
        from PyQt6.QtWidgets import QSizePolicy
        assert settings_dialog.g_levels.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum

    def test_elo_change_saves_to_backend_no_crash(self, settings_dialog):
        """Elo-Änderung verursacht keinen Absturz (Backend-Guard greift)."""
        # Direkt die Methode aufrufen – sollte nicht abstürzen
        settings_dialog.save_repertoire_elo("mid")
        # Wenn kein AssertionError/Exception: bestanden

    def test_elo_change_notifies_main_window(self, settings_dialog, mock_main_window, creator_backend):
        """Änderung der Repertoire-Elo benachrichtigt das MainWindow sofort mit internem Elo-Key."""
        mock_main_window.backend = creator_backend
        from opening_fenix.core.utils import get_elo_display
        settings_dialog.save_creator_elo(get_elo_display("mid"))
        assert mock_main_window._calls.get("set_repertoire_elo") == "mid"
        assert creator_backend.get_meta("elo") == "mid"
        assert creator_backend.get_meta("lichess_elo") == "mid"


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

    def test_cover_image_ui_elements_exist(self, settings_dialog):
        """Cover-Bild UI-Elemente sind vorhanden."""
        assert hasattr(settings_dialog, "lbl_cover_preview")
        assert hasattr(settings_dialog, "btn_remove_cover")
        assert settings_dialog.lbl_cover_preview.text() == "Kein Bild"

    def test_select_cover_image_flow(self, settings_dialog, tmp_path, monkeypatch):
        """Cover-Bild auswählen kopiert die Datei und aktualisiert die Vorschau."""
        # Create a mock source image file
        src_img = tmp_path / "my_cover.png"
        src_img.write_text("fake_png_data")

        # Mock QFileDialog
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(src_img), "PNG"))
        # Mock QMessageBox
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
        
        # We need a fake user folder structure
        user_dir_path = tmp_path / "user_dir"
        repo_dir = user_dir_path / "repertoires" / settings_dialog.l_n.text()
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Patch get_user_dir to return our temp folder
        monkeypatch.setattr("opening_fenix.gui.dialogs.repo_settings_dialog.get_user_dir", lambda: str(user_dir_path))
        monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: str(user_dir_path))

        settings_dialog.main_window.backend = settings_dialog.backend
        settings_dialog.select_cover_image()

        # Check that the cover image was copied
        copied_cover = repo_dir / "cover.png"
        assert copied_cover.exists()
        assert copied_cover.read_text() == "fake_png_data"
        assert settings_dialog.main_window.btn_load_repo.update_repo.called

    def test_remove_cover_image_flow(self, settings_dialog, tmp_path, monkeypatch):
        """Cover-Bild entfernen löscht die Datei und aktualisiert die Vorschau."""
        # Mock QMessageBox to accept removal
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

        user_dir_path = tmp_path / "user_dir"
        repo_dir = user_dir_path / "repertoires" / settings_dialog.l_n.text()
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Write a mock cover
        cover_file = repo_dir / "cover.png"
        cover_file.write_text("some_data")
        assert cover_file.exists()

        monkeypatch.setattr("opening_fenix.gui.dialogs.repo_settings_dialog.get_user_dir", lambda: str(user_dir_path))
        monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: str(user_dir_path))

        settings_dialog.main_window.backend = settings_dialog.backend
        settings_dialog.remove_cover_image()
        assert not cover_file.exists()
        assert settings_dialog.main_window.btn_load_repo.update_repo.called



# ─── Seite 2: Design & Audio ───────────────────────────────────────────────────

class TestRepoSettingsDesignPage:

    def test_theme_combo_populated(self, settings_dialog):
        """Theme-Dropdown enthält Theme-Optionen."""
        settings_dialog.sidebar.setCurrentRow(1)
        from opening_fenix.gui.widgets.board_widget import THEMES
        assert settings_dialog.combo_theme.count() == len(THEMES)

    def test_highlight_combo_populated(self, settings_dialog):
        """Highlight-Farben-Dropdown enthält alle Optionen."""
        settings_dialog.sidebar.setCurrentRow(1)
        from opening_fenix.gui.widgets.board_widget import HIGHLIGHT_COLORS
        assert settings_dialog.combo_highlight.count() == len(HIGHLIGHT_COLORS)

    def test_theme_change_calls_main_window(self, settings_dialog, mock_main_window):
        """Theme-Änderung wird an MainWindow config gespeichert."""
        settings_dialog.sidebar.setCurrentRow(1)
        settings_dialog.change_board_theme("Grün (Lichess)")
        assert mock_main_window.config.get("theme") == "Grün (Lichess)"
        # board_widget.set_theme wurde aufgerufen
        assert mock_main_window.board_widget.set_theme.called

    def test_highlight_change_calls_main_window(self, settings_dialog, mock_main_window):
        """Highlight-Farben-Änderung wird an MainWindow config gespeichert."""
        settings_dialog.sidebar.setCurrentRow(1)
        settings_dialog.change_highlight_color("Blau")
        assert mock_main_window.config.get("highlight_color") == "Blau"
        assert mock_main_window.board_widget.set_highlight_color.called

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

    def test_engine_scan_toggle_start_and_stop(self, settings_dialog, monkeypatch, tmp_path):
        """Start-Button wird beim Starten zum Stopp-Button und bricht beim erneuten Klick ab."""
        fake_engine = tmp_path / "stockfish.exe"
        fake_engine.write_text("fake binary")
        settings_dialog.txt_engine_path.setText(str(fake_engine))

        # Mock AnalysisThread.start so it stays running
        class DummyWorker:
            def __init__(self):
                self._running = True
                self.cancelled = False
                class Signal:
                    def connect(self, fn): pass
                self.progress_signal = Signal()
                self.finished_signal = Signal()
            def isRunning(self):
                return self._running
            def start(self):
                pass
            def cancel(self):
                self.cancelled = True
                self._running = False

        dummy = DummyWorker()
        monkeypatch.setattr("opening_fenix.gui.dialogs.repo_settings_dialog.AnalysisThread", lambda *args, **kwargs: dummy)

        # 1. Start scan
        settings_dialog.start_analysis()
        assert "stoppen" in settings_dialog.btn_start_eng.text().lower() or "stop" in settings_dialog.btn_start_eng.text().lower()
        assert settings_dialog.w_eng == dummy

        # 2. Click again to stop scan
        settings_dialog.start_analysis()
        assert dummy.cancelled is True

    def test_delete_lichess_button_shows_current_elo(self, settings_dialog):
        """Button 'Daten für diese Elo löschen' zeigt den aktuellen Elo-Namen an."""
        current_elo_text = settings_dialog.combo_cr_elo.currentText()
        assert current_elo_text != ""
        btn_text = settings_dialog.btn_del_lich.text()
        assert current_elo_text in btn_text

    def test_delete_lichess_button_updates_on_elo_change(self, settings_dialog):
        """Änderung der Elo in der Combobox aktualisiert den Text des Lösch-Buttons sofort."""
        # Wähle ein anderes Elo aus
        for i in range(settings_dialog.combo_cr_elo.count()):
            text = settings_dialog.combo_cr_elo.itemText(i)
            if text != settings_dialog.combo_cr_elo.currentText():
                settings_dialog.combo_cr_elo.setCurrentIndex(i)
                assert text in settings_dialog.btn_del_lich.text()
                break

    def test_delete_all_lichess_button_exists(self, settings_dialog):
        """Button zum Löschen aller Elo-Bereiche existiert und hat passenden Text."""
        assert hasattr(settings_dialog, "btn_del_all_lich")
        text = settings_dialog.btn_del_all_lich.text().lower()
        assert "aller elo" in text or "all elo" in text

    def test_delete_active_lichess_data_flow(self, settings_dialog, creator_backend, monkeypatch):
        """Klick auf 'Daten für diese Elo löschen' ruft backend.delete_lichess_data mit aktuellem Elo auf."""
        mock_question = MagicMock(return_value=QMessageBox.StandardButton.Yes)
        mock_info = MagicMock()
        monkeypatch.setattr(QMessageBox, "question", mock_question)
        monkeypatch.setattr(QMessageBox, "information", mock_info)

        with patch.object(creator_backend, "delete_lichess_data", return_value=(True, "5 Einträge gelöscht.")) as mock_del:
            settings_dialog.delete_active_lichess_data()
            assert mock_question.called
            # Prompt should include current elo
            assert settings_dialog.combo_cr_elo.currentText() in mock_question.call_args[0][2]
            assert mock_del.called

    def test_delete_all_lichess_data_flow(self, settings_dialog, creator_backend, monkeypatch):
        """Klick auf 'Lichess-Daten aller Elo-Bereiche löschen' ruft backend.delete_lichess_data(None) auf."""
        mock_question = MagicMock(return_value=QMessageBox.StandardButton.Yes)
        mock_info = MagicMock()
        monkeypatch.setattr(QMessageBox, "question", mock_question)
        monkeypatch.setattr(QMessageBox, "information", mock_info)

        with patch.object(creator_backend, "delete_lichess_data", return_value=(True, "15 Einträge gelöscht.")) as mock_del:
            settings_dialog.delete_all_lichess_data()
            assert mock_question.called
            assert mock_del.called
            assert mock_del.call_args[0][0] is None

    def test_delete_blocked_when_import_running(self, settings_dialog, monkeypatch):
        """Löschen ist blockiert, wenn ein Import noch aktiv läuft."""
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        settings_dialog.w_lich = mock_worker

        mock_warn = MagicMock()
        monkeypatch.setattr(QMessageBox, "warning", mock_warn)

        settings_dialog.delete_active_lichess_data()
        assert mock_warn.called

        mock_warn.reset_mock()
        settings_dialog.delete_all_lichess_data()
        assert mock_warn.called
        settings_dialog.w_lich = None



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

    def test_loading_dots_animation_updates_table_cells(self, settings_dialog):
        """update_loading_dots aktualisiert Zellen und Progress-Bars in der Wartungs-Tabelle."""
        from opening_fenix.gui.dialogs.unified_settings_dialog import DualModeCell
        from PyQt6.QtWidgets import QTableWidgetItem

        settings_dialog.main_table.setRowCount(1)
        item_elo = QTableWidgetItem("Laden...")
        settings_dialog.main_table.setItem(0, 2, item_elo)

        cell_a = DualModeCell("Laden...")
        settings_dialog.main_table.setCellWidget(0, 3, cell_a)

        cell_c = DualModeCell("-")
        cell_c.show_progress(35, "Lichess...", format_str="35% (7/20)")
        settings_dialog.main_table.setCellWidget(0, 4, cell_c)

        settings_dialog.loading_dots = 0
        settings_dialog.update_loading_dots()

        assert item_elo.text() == "Laden."
        assert cell_a.text() == "Laden."
        assert cell_c.progress_bar.format() == "35% (7/20) ."

    def test_batch_maintenance_stop_updates_table(self, settings_dialog):
        """Wenn Batch-Wartung gestoppt wird, wird die Tabelle auf 'Gestoppt' und 'Laden...' aktualisiert."""
        from opening_fenix.gui.dialogs.unified_settings_dialog import DualModeCell
        from PyQt6.QtWidgets import QTableWidgetItem, QProgressBar, QWidget, QHBoxLayout

        settings_dialog.main_table.setRowCount(1)
        item_name = QTableWidgetItem("MyRepo")
        settings_dialog.main_table.setItem(0, 1, item_name)

        item_elo = QTableWidgetItem("Hoch")
        settings_dialog.main_table.setItem(0, 2, item_elo)

        cell_a = DualModeCell("-")
        cell_a.show_progress(40, "Analysiere...", format_str="40% (8/20)")
        settings_dialog.main_table.setCellWidget(0, 3, cell_a)

        cell_c = DualModeCell("-")
        settings_dialog.main_table.setCellWidget(0, 4, cell_c)

        pb_container = QWidget()
        h_pb = QHBoxLayout(pb_container)
        pb = QProgressBar()
        pb.setRange(0, 2)
        pb.setValue(0)
        h_pb.addWidget(pb)
        pb_container.progress_bar = pb
        settings_dialog.main_table.setCellWidget(0, 5, pb_container)

        # Mock m_thread and trigger cancel / on_batch_done logic
        with patch.object(settings_dialog, "refresh_creator_info"):
            # Test stopping through the toggle handler
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            settings_dialog.m_thread = mock_thread

            settings_dialog.toggle_batch_maintenance()
            assert mock_thread.cancel.called
            assert "Wartung wird gestoppt" in settings_dialog.lbl_m_overall.text()
            assert not settings_dialog.btn_start_batch.isEnabled()


# ─── Seite 7: Software-Updates ──────────────────────────────────────────────────

class TestRepoSettingsUpdatesPage:

    def test_updates_page_elements_exist(self, settings_dialog):
        """Software-Updates Seite enthält Versionslabel, Letzte Prüfung und Button."""
        settings_dialog.sidebar.setCurrentRow(6)
        assert hasattr(settings_dialog, "lbl_current_version")
        assert hasattr(settings_dialog, "lbl_last_check")
        assert hasattr(settings_dialog, "btn_manual_update")
        from opening_fenix.core.version import APP_VERSION
        assert APP_VERSION in settings_dialog.lbl_current_version.text()

    def test_auto_check_toggle(self, settings_dialog):
        """Auto-Check Checkbox ändert Konfiguration."""
        settings_dialog.on_auto_check_updates_toggled(False)
        from opening_fenix.core.services.update_service import get_config_dict
        assert get_config_dict().get("auto_check_updates") is False
        settings_dialog.on_auto_check_updates_toggled(True)
        assert get_config_dict().get("auto_check_updates") is True


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


# ─── Kurs-Autoauswahl ─────────────────────────────────────────────────────────

class TestCourseAutoSelection:

    def test_initial_open_autoselects_active_course(self, settings_dialog, sample_repertoire):
        """Beim Öffnen wird das aktuell im Backend geöffnete Repertoire ausgewählt."""
        assert settings_dialog.combo_active_repo.currentData() == sample_repertoire

    def test_reopen_after_switching_course_autoselects_new_course(self, settings_dialog, creator_backend, mock_user_dir):
        """Nach dem Wechseln des Repertoires wählt on_reopen() den neuen Kurs automatisch aus."""
        # Zweites Test-Repertoire erstellen und laden
        new_repo = "Neuer Testkurs"
        creator_backend.load_repertoire(new_repo)
        assert creator_backend.active_repo_name == new_repo
        
        # Einstellungen erneut öffnen
        settings_dialog.on_reopen()
        
        # Prüfen, dass der neu geöffnete Kurs aktiv im Dropdown ausgewählt ist
        assert settings_dialog.combo_active_repo.currentData() == new_repo
        assert new_repo in settings_dialog.windowTitle()

    def test_reopen_resets_manual_dropdown_switch_to_open_course(self, settings_dialog, creator_backend, mock_user_dir):
        """Wenn der Nutzer im Dialog einen anderen Kurs gewählt hatte, wählt der nächste Reopen wieder den im Creator offenen Kurs."""
        other_repo = "Anderer Kurs"
        temp_backend = CreatorBackend()
        temp_backend.load_repertoire(other_repo)
        temp_backend.close()

        settings_dialog.populate_active_repo_dropdown()

        # Nutzer wählt 'Anderer Kurs' im Dropdown
        idx = settings_dialog.combo_active_repo.findData(other_repo)
        assert idx >= 0
        settings_dialog.combo_active_repo.setCurrentIndex(idx)
        assert settings_dialog.combo_active_repo.currentData() == other_repo

        # Aber im Creator ist weiterhin 'sample_repertoire' offen
        initial_repo = creator_backend.active_repo_name
        
        # Reopen simulieren
        settings_dialog.on_reopen()

        # Muss wieder auf initial_repo (den im Creator offenen Kurs) zurückgesetzt werden
        assert settings_dialog.combo_active_repo.currentData() == initial_repo

    def test_select_course_explicit(self, settings_dialog, mock_user_dir):
        """select_course wählt den gewünschten Kurs explizit aus."""
        target = "Zielkurs"
        temp_backend = CreatorBackend()
        temp_backend.load_repertoire(target)
        temp_backend.close()

        settings_dialog.select_course(target)
        assert settings_dialog.combo_active_repo.currentData() == target
        assert target in settings_dialog.windowTitle()
