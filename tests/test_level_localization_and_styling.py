import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QSpinBox
from opening_fenix.core.translation import translator, tr_ui
from opening_fenix.core.utils import get_repertoire_comment_stats
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.gui.dialogs.unified_settings_dialog import CenteredSpinBoxCell, NoWheelSpinBox
from opening_fenix.core.db.models import RepertoireLevel

def test_centered_spinbox_cell_delegation(qapp):
    spin = NoWheelSpinBox()
    spin.setRange(800, 4000)
    spin.setValue(1500)
    cell = CenteredSpinBoxCell(spin)

    assert cell.value() == 1500
    cell.setValue(1850)
    assert spin.value() == 1850
    assert cell.value() == 1850
    assert cell.singleStep() == spin.singleStep()

def test_comment_stats_localization():
    translator.load_language("de")
    de_stats = get_repertoire_comment_stats(None)
    assert de_stats == "Keine Kommentare"

    translator.load_language("en")
    en_stats = get_repertoire_comment_stats(None)
    assert en_stats == "No comments"

def test_seed_default_levels_localization():
    translator.load_language("en")
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire("TestEnSeed")
    levels = backend.get_repertoire_levels()
    names = [lvl["name"] for lvl in levels]
    assert names == ["Basics", "Deep Theory", "Reference and Explanations"]
    backend.close()

def test_seed_default_levels_migration_de_to_en():
    translator.load_language("de")
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire("TestMigrate")
    levels = backend.get_repertoire_levels()
    assert [lvl["name"] for lvl in levels] == ["Grundlagen", "Tiefe Theorie", "Nachschlagewerk und Erklärungen"]
    backend.close()

    # Now load the same repertoire with English active -> should auto-migrate default level names
    translator.load_language("en")
    backend_en = CreatorBackend(is_test=True)
    backend_en.load_repertoire("TestMigrate")
    levels_en = backend_en.get_repertoire_levels()
    assert [lvl["name"] for lvl in levels_en] == ["Basics", "Deep Theory", "Reference and Explanations"]
    backend_en.close()

    # Reset back to German for test hygiene
    translator.load_language("de")
