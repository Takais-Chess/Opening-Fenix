"""
Unit tests for SpellCheckService and PyQt6 SpellCheckHighlighter.
"""

import os
import pytest
from PyQt6.QtWidgets import QPlainTextEdit, QMenu
from PyQt6.QtGui import QTextCharFormat, QContextMenuEvent
from PyQt6.QtCore import QPoint

from opening_fenix.core.spellcheck_service import get_spellcheck_service, SpellCheckService
from opening_fenix.gui.widgets.spell_text_edit import attach_spell_check, SpellCheckHighlighter


@pytest.fixture
def spell_service(tmp_path):
    """Provides a fresh SpellCheckService isolated with a temporary user dictionary."""
    svc = SpellCheckService()
    svc._user_dict_path = str(tmp_path / "user_dictionary.txt")
    svc._user_dictionary = set()
    svc._ignored_words = set()
    svc.set_enabled(True)
    return svc


def test_spellcheck_valid_german_words(spell_service):
    assert spell_service.is_word_valid("Hallo", "de") is True
    assert spell_service.is_word_valid("Schach", "de") is True
    assert spell_service.is_word_valid("Eröffnung", "de") is True
    assert spell_service.is_word_valid("Königsflügel", "de") is True
    assert spell_service.is_word_valid("Turmendspiel", "de") is True


def test_spellcheck_invalid_german_words(spell_service):
    assert spell_service.is_word_valid("Spil", "de") is False
    assert spell_service.is_word_valid("Fehla", "de") is False
    assert spell_service.is_word_valid("Xyzqwerasdf", "de") is False


def test_spellcheck_english_words(spell_service):
    assert spell_service.is_word_valid("Hello", "en") is True
    assert spell_service.is_word_valid("bishop", "en") is True
    assert spell_service.is_word_valid("endgame", "en") is True
    assert spell_service.is_word_valid("Xyzqwerasdf", "en") is False


def test_chess_san_notation_not_flagged(spell_service):
    """Algebraic chess moves in English and German must never be flagged as typos."""
    san_moves = [
        # Pawn moves
        "e4", "d5", "exd5", "e8=Q", "axb8=N+", "f7#",
        # English pieces
        "Nf3", "Bxc6", "Rad1", "Qh5+", "Qxf7#", "Nbd7",
        # German pieces
        "Sf3", "Lxc6", "Tad1", "Dh5+", "Dxf7#", "Sbd7",
        # Castling
        "O-O", "O-O-O", "0-0", "0-0-0",
        # Move numbers and annotations
        "1.", "1...", "14.", "h4?!", "g5!?"
    ]
    for move in san_moves:
        assert spell_service.is_word_valid(move, "de") is True, f"SAN move '{move}' should be valid"
        assert spell_service.is_word_valid(move, "en") is True, f"SAN move '{move}' should be valid in en"


def test_chess_vocabulary_not_flagged(spell_service):
    """Special chess terms, openings and famous players must be recognized."""
    terms = [
        "Fianchetto", "Zugzwang", "Zwischenzug", "Najdorf", "Caro-Kann",
        "Kasparov", "Carlsen", "Grünfeld", "Nimzowitsch", "Sveshnikov"
    ]
    for term in terms:
        assert spell_service.is_word_valid(term, "de") is True, f"Chess term '{term}' should be valid"


def test_suggestions_ranking_and_casing(spell_service):
    """Suggestions should place high-frequency correct words first and preserve case."""
    suggestions_capitalized = spell_service.get_suggestions("Spil", "de")
    assert len(suggestions_capitalized) > 0
    assert "Spiel" in suggestions_capitalized
    assert suggestions_capitalized[0] == "Spiel"

    suggestions_lower = spell_service.get_suggestions("spil", "de")
    assert len(suggestions_lower) > 0
    assert "spiel" in suggestions_lower
    assert suggestions_lower[0] == "spiel"


def test_user_dictionary_addition(spell_service):
    """Adding a custom word persists it and marks it valid."""
    word = "NeuerSchachVariantenName"
    assert spell_service.is_word_valid(word, "de") is False
    
    spell_service.add_to_user_dictionary(word)
    assert spell_service.is_word_valid(word, "de") is True

    # Check file was written
    assert os.path.exists(spell_service._get_user_dict_path())
    with open(spell_service._get_user_dict_path(), "r", encoding="utf-8") as f:
        saved_content = f.read()
    assert word.lower() in saved_content


def test_ignore_word_session(spell_service):
    """Ignoring a word marks it valid in memory without modifying the user dictionary file."""
    word = "TemporaeresWort"
    assert spell_service.is_word_valid(word, "de") is False
    
    spell_service.ignore_word(word)
    assert spell_service.is_word_valid(word, "de") is True
    assert spell_service.is_word_ignored(word) is True


def test_disable_spellcheck(spell_service):
    """When disabled, all words pass validation."""
    assert spell_service.is_word_valid("Xyzfoobartypos", "de") is False
    spell_service.set_enabled(False)
    assert spell_service.is_word_valid("Xyzfoobartypos", "de") is True


def test_extract_words_with_spans():
    text = "Nach 1. e4 e5 spielt Weiß Sf3. (Sehr gut!) [Quelle](http://test.com)"
    words = SpellCheckService.extract_words_with_spans(text)
    extracted = [w for w, s, e in words]
    assert "Nach" in extracted
    assert "e4" in extracted
    assert "e5" in extracted
    assert "spielt" in extracted
    assert "Weiß" in extracted
    assert "Sf3" in extracted
    assert "Sehr" in extracted
    assert "gut" in extracted


def test_defensive_types(spell_service):
    """Service methods should gracefully handle non-string / bool arguments without crashing."""
    # Should not raise AttributeError when passed boolean or None
    spell_service.add_to_user_dictionary(False)
    spell_service.add_to_user_dictionary(None)
    spell_service.ignore_word(False)
    spell_service.ignore_word(None)
    assert spell_service.is_word_ignored(False) is False
    assert spell_service.is_word_valid(False) is True
    assert spell_service.get_suggestions(False) == []


def test_spell_highlighter_qt(qtbot):
    """Test QPlainTextEdit integration with SpellCheckHighlighter."""
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    highlighter = attach_spell_check(edit, get_lang_fn=lambda: "de")
    assert highlighter is not None
    assert hasattr(edit, "_spell_highlighter")

    edit.setPlainText("Das ist ein Test mit Spil und e4.")
    # Verify no crash during block highlighting
    highlighter.rehighlight()


def test_context_menu_action_slots_do_not_crash_on_boolean_trigger(qtbot, tmp_path):
    """
    QAction.triggered emits triggered(bool checked = False).
    Ensure clicking 'Add to Dictionary', 'Ignore', and suggestion actions
    does not crash when receiving the boolean argument.
    """
    svc = get_spellcheck_service()
    svc._user_dict_path = str(tmp_path / "user_dict_qt.txt")
    svc.set_enabled(True)

    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("FalschesWortZumHinzufuegen")
    highlighter = attach_spell_check(edit, get_lang_fn=lambda: "de")

    action_triggered = []

    def mock_exec(self, *args, **kwargs):
        for act in self.actions():
            txt = act.text().lower()
            if "hinzufügen" in txt or "dictionary" in txt:
                # Trigger the action while the menu is still active in exec()
                act.triggered.emit(False)
                action_triggered.append(act.text())
                break
        return None

    # Trigger custom_context_menu_event
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 10))

    orig_exec = QMenu.exec
    QMenu.exec = mock_exec
    try:
        edit.contextMenuEvent(event)
    finally:
        QMenu.exec = orig_exec

    assert len(action_triggered) > 0, "Add to dictionary action should have been found and triggered"
    assert svc.is_word_valid("FalschesWortZumHinzufuegen", "de") is True
