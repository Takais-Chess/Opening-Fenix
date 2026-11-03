import pytest
from unittest.mock import MagicMock
from opening_fenix.core.utils import (
    extract_eval_symbol,
    strip_eval_symbol,
    has_meaningful_comment,
    get_lang_display_label,
    get_repertoire_comment_stats,
    translate_chess_comment,
    EVAL_SYMBOLS
)


def test_extract_and_strip_eval_symbols():
    # Standalone symbols
    for s in EVAL_SYMBOLS:
        assert extract_eval_symbol(s) == s
        assert strip_eval_symbol(s) == ""
        assert has_meaningful_comment(s) is False

    # ASCII variants
    assert extract_eval_symbol("+-") == "+−"
    assert extract_eval_symbol("-+") == "−+"
    assert strip_eval_symbol("+-") == ""
    assert strip_eval_symbol("-+") == ""

    # Multi-line comment ending with eval symbol
    note = "White has a comfortable position.\n="
    assert extract_eval_symbol(note) == "="
    assert strip_eval_symbol(note) == "White has a comfortable position."
    assert has_meaningful_comment(note) is True

    # Multi-line comment ending with symbol and spaces
    note_space = "Schwarz steht aktiv.\n∓   "
    assert extract_eval_symbol(note_space) == "∓"
    assert strip_eval_symbol(note_space) == "Schwarz steht aktiv."
    assert has_meaningful_comment(note_space) is True

    # Same-line trailing symbol
    trailing = "Unclear play ∞"
    assert extract_eval_symbol(trailing) == "∞"
    assert strip_eval_symbol(trailing) == "Unclear play"
    assert has_meaningful_comment(trailing) is True

    # With ChessBase arrows / highlights
    with_tags = "[%csl Gc4] [%cal Gc2c4] ="
    assert extract_eval_symbol(with_tags) == "="
    assert has_meaningful_comment(with_tags) is False

    with_tags_and_text = "[%csl Gc4] Strong outpost on c4\n⩲"
    assert extract_eval_symbol(with_tags_and_text) == "⩲"
    assert has_meaningful_comment(with_tags_and_text) is True


def test_has_meaningful_comment_filter():
    assert has_meaningful_comment("") is False
    assert has_meaningful_comment("   ") is False
    assert has_meaningful_comment("=") is False
    assert has_meaningful_comment("±") is False
    assert has_meaningful_comment("[%csl Ge4]") is False
    assert has_meaningful_comment("[%csl Ge4] [%cal Gg1f3]") is False
    assert has_meaningful_comment("[%csl Ge4] =") is False
    assert has_meaningful_comment("Gut für Weiß") is True
    assert has_meaningful_comment("Good move") is True


def test_get_lang_display_label():
    assert "EN" in get_lang_display_label("en")
    assert "DE" in get_lang_display_label("de")
    assert "ES" in get_lang_display_label("es")
    assert "FR" in get_lang_display_label("fr")
    assert "CUSTOM" in get_lang_display_label("custom")


def test_get_repertoire_comment_stats_ignores_pure_eval_symbols():
    mock_session = MagicMock()
    mock_query = mock_session.query.return_value
    mock_filter = mock_query.filter.return_value

    comments = [
        ('{"en": "Great move\\n=", "de": "="}',),
        ('{"en": "=", "de": "="}',),
        ('{"en": "Solid defense", "de": "Solide Verteidigung\\n="}',)
    ]
    mock_filter.all.return_value = comments

    stats = get_repertoire_comment_stats(mock_session)
    assert "2 EN" in stats
    assert "1 DE" in stats


def test_translate_chess_comment_mocked(monkeypatch):
    def mock_urlopen(req, timeout=6.0):
        class MockResp:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return b'[[["Wei\\u00df steht gut.", "White is good.", null, null, 1]], null, "en"]'
        return MockResp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = translate_chess_comment("[%csl Ge4] [%cal Gg1f3] White is good.\n⩲", src_lang="en", tgt_lang="de")
    assert "[%csl Ge4] [%cal Gg1f3]" in res
    assert "Weiß steht gut." in res
    assert res.endswith("⩲")


def test_creator_window_symbol_and_compact_dual_mode(qapp, monkeypatch):
    monkeypatch.setattr("opening_fenix.creator.creator_window.CreatorBackend", MagicMock())
    monkeypatch.setattr("opening_fenix.creator.creator_window.EngineThread", MagicMock())
    monkeypatch.setattr(
        "opening_fenix.creator.creator_window.CreatorWindow.new_repertoire_dialog",
        lambda self: None
    )
    monkeypatch.setattr(
        "opening_fenix.creator.creator_window.CreatorWindow.load_repertoire_dialog",
        lambda self: None
    )

    from opening_fenix.creator.creator_window import CreatorWindow
    win = CreatorWindow()

    # 1. Test symbol toggling
    win.current_position_comments = {"en": "Some English comment", "de": "Deutscher Kommentar"}
    win.toggle_symbol("=")
    assert "=\n" in win.current_position_comments["en"] or win.current_position_comments["en"].endswith("=")
    assert "=\n" in win.current_position_comments["de"] or win.current_position_comments["de"].endswith("=")
    assert win.get_current_position_eval_symbol() == "="

    # Toggle off
    win.toggle_symbol("=")
    assert "=" not in win.current_position_comments["en"]
    assert "=" not in win.current_position_comments["de"]
    assert win.get_current_position_eval_symbol() is None

    # 2. Test Compact Dual Translation Mode
    win.enable_dual_comment_mode("en", "de")
    assert win.dual_comment_mode is True
    assert not win.dual_bridge_bar.isHidden()
    assert not win.txt_c_dual.isHidden()
    assert win.btn_auto_translate.text() == "⚡ Übersetzen"
    assert win.btn_copy_source.text() == "📋 Kopieren"
    assert win.lbl_dual_pair.text() == "EN ➜ DE"

    # Type in source and target
    win.txt_c.setPlainText("New English text")
    win.txt_c_dual.setPlainText("Neuer deutscher Text")
    win.on_details_changed()

    assert "New English text" in win.current_position_comments["en"]
    assert "Neuer deutscher Text" in win.current_position_comments["de"]

    # Test copy from source to dual
    win.txt_c.setPlainText("Copied text")
    win.txt_c_dual.setPlainText("")
    win.copy_source_comment_to_dual()
    assert win.txt_c_dual.toPlainText() == "Copied text"

    # 3. Test Auto-Translate with QThread mock
    def mock_translate(text, src_lang="en", tgt_lang="de", timeout=6.0):
        return "Übersetzter Text"

    monkeypatch.setattr("opening_fenix.core.utils.translate_chess_comment", mock_translate)
    win.txt_c.setPlainText("Source to translate")
    win.txt_c_dual.setPlainText("")
    win.auto_translate_comment()

    # Wait for thread to finish
    win.translation_thread.wait(2000)
    qapp.processEvents()

    assert win.txt_c_dual.toPlainText() == "Übersetzter Text"
    assert win.btn_auto_translate.isEnabled() is True
    assert win.btn_auto_translate.text() == "⚡ Übersetzen"

    # Disable dual mode
    win.disable_dual_comment_mode()
    assert win.dual_comment_mode is False
    assert win.dual_bridge_bar.isHidden()
    assert win.txt_c_dual.isHidden()

    win.close()
