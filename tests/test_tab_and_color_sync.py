"""
Tests for tab synchronization, persistent migration, mojibake auto-repair,
and settings propagation between profiles and global config.
"""
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtCore import Qt
from opening_fenix.gui.widgets.board_widget import (
    ChessBoardWidget, normalize_text_encoding, THEMES, HIGHLIGHT_COLORS
)
from opening_fenix.gui.dialogs.unified_settings_dialog import (
    UnifiedSettingsDialog, TRAINER_SETTINGS_KEYS
)
from opening_fenix.gui.dialogs.repo_settings_dialog import RepoSettingsDialog


def test_normalize_text_encoding():
    """Verify recursive mojibake repair functions correctly."""
    assert normalize_text_encoding("Grün") == "Grün"
    assert normalize_text_encoding("GrÃ¼n") == "Grün"
    assert normalize_text_encoding("Gr\u00c3\u0192\u00c2\u00bcn") == "Grün"
    assert normalize_text_encoding("Türkis") == "Türkis"
    assert normalize_text_encoding("TÃ¼rkis") == "Türkis"
    assert normalize_text_encoding("T\u00c3\u0192\u00c2\u00bcrkis") == "Türkis"
    assert normalize_text_encoding("Gelb (Standard)") == "Gelb (Standard)"


def test_board_widget_mojibake_tolerance(qapp):
    """Verify ChessBoardWidget handles mojibake in theme and highlight color gracefully."""
    board = ChessBoardWidget()
    
    # Mojibake theme
    board.set_theme("Gr\u00c3\u0192\u00c2\u00bcn")
    assert board.light_color == THEMES["Grün"][0]
    assert board.dark_color == THEMES["Grün"][1]
    
    # Mojibake highlight color
    board.set_highlight_color("Gr\u00c3\u0192\u00c2\u00bcn")
    assert board.highlight_color == HIGHLIGHT_COLORS["Grün"]
    
    board.set_highlight_color("TÃ¼rkis")
    assert board.highlight_color == HIGHLIGHT_COLORS["Türkis"]


def test_trainer_settings_keys_contains_appearance():
    """Verify that theme and highlight_color are synchronized with profiles."""
    assert "theme" in TRAINER_SETTINGS_KEYS
    assert "highlight_color" in TRAINER_SETTINGS_KEYS
    assert "anim_speed" in TRAINER_SETTINGS_KEYS
    assert "master_volume" in TRAINER_SETTINGS_KEYS


def test_creator_tab_migration_respects_user_choice(temp_dir, monkeypatch):
    """
    Verify that once transpositions_tab_migrated is set, CreatorWindow
    does not forcefully re-add TRANSPOSITIONS if the user hid it.
    """
    import os
    import json
    from opening_fenix.creator.creator_window import CreatorWindow

    monkeypatch.setattr("opening_fenix.creator.creator_window.get_user_dir", lambda: temp_dir)
    monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: temp_dir)
    monkeypatch.setattr("opening_fenix.core.services.update_service.get_user_dir", lambda: temp_dir)

    cfg_path = os.path.join(temp_dir, "config.json")
    initial_cfg = {
        "creator_active_tabs": ["DETAILS", "ANALYSIS"],
        "transpositions_tab_migrated": True
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(initial_cfg, f)

    # Initializing CreatorWindow in test mode without repertoire
    cw = CreatorWindow(is_test=True)
    try:
        # TRANSPOSITIONS should NOT have been re-added because migrated is True
        assert "TRANSPOSITIONS" not in cw.config["creator_active_tabs"]
    finally:
        cw.close()


def test_repo_settings_dialog_sync_on_reopen(qapp, temp_dir, monkeypatch):
    """
    Verify that sync_creator_tab_checkboxes() updates checkbox states
    when the cached dialog is re-opened.
    """
    monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: temp_dir)
    monkeypatch.setattr("opening_fenix.core.services.update_service.get_user_dir", lambda: temp_dir)

    class FakeCreatorWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.config = {
                "creator_active_tabs": ["DETAILS", "ANALYSIS"],
                "theme": "Blau (Turnier)",
                "highlight_color": "Blau"
            }
        def get_setting(self, key, default=None):
            return self.config.get(key, default)
        def set_setting(self, key, val):
            self.config[key] = val
        def save_config(self):
            pass
        def apply_tab_visibility(self):
            pass

    parent = FakeCreatorWindow()
    dlg = RepoSettingsDialog(parent=parent)
    try:
        # Initially, chk_transpositions should be False
        assert not dlg.chk_transpositions.isChecked()

        # Simulate dynamic addition of TRANSPOSITIONS in parent window
        parent.config["creator_active_tabs"] = ["DETAILS", "ANALYSIS", "TRANSPOSITIONS"]

        # Call on_reopen
        dlg.on_reopen()

        # Now chk_transpositions should be True!
        assert dlg.chk_transpositions.isChecked()
    finally:
        dlg.close()
