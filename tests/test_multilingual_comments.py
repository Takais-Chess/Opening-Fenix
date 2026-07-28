import pytest
from opening_fenix.core.utils import (
    get_multilingual_comment_dict,
    parse_comment,
    format_multilingual_comment,
    parse_pgn_tagged_comment,
    combine_comments
)

def test_parse_plain_text_comment():
    comment = "Solider Zug im Zentrum."
    assert parse_comment(comment, "de") == "Solider Zug im Zentrum."
    assert parse_comment(comment, "en") == "Solider Zug im Zentrum."
    assert get_multilingual_comment_dict(comment) == {"de": "Solider Zug im Zentrum."}

def test_parse_json_multilingual_comment():
    raw_json = '{"de": "Weiß kontrolliert d4.", "en": "White controls d4."}'
    assert parse_comment(raw_json, "de") == "Weiß kontrolliert d4."
    assert parse_comment(raw_json, "en") == "White controls d4."
    # Test fallback to English if requested language is unavailable
    assert parse_comment(raw_json, "fr") == "White controls d4."

def test_format_multilingual_comment():
    data = {"de": "Guter Zug", "en": "Good move"}
    formatted = format_multilingual_comment(data)
    assert '"de": "Guter Zug"' in formatted
    assert '"en": "Good move"' in formatted

    single = {"de": "Einziger Zug"}
    assert format_multilingual_comment(single) == "Einziger Zug"

def test_parse_pgn_tagged_comment():
    pgn_comment = "[:de] Kontrolliert das Zentrum. [:en] Controls the center."
    parsed = parse_pgn_tagged_comment(pgn_comment)
    assert parsed == {"de": "Kontrolliert das Zentrum.", "en": "Controls the center."}

def test_combine_comments():
    existing = '{"de": "Erster Kommentar"}'
    new_pgn = "[:en] Second comment"
    combined = combine_comments(existing, new_pgn)
    
    dict_res = get_multilingual_comment_dict(combined)
    assert dict_res.get("de") == "Erster Kommentar"
    assert dict_res.get("en") == "Second comment"

def test_combine_plain_comments():
    combined = combine_comments("Kommentar A", "Kommentar B")
    assert "Kommentar A | Kommentar B" in parse_comment(combined, "de")

def test_creator_language_button_highlight(creator_window, qapp):
    """Test switching languages and verifying highlight behavior when current language comment is empty."""
    creator_window.current_position_comments = {"de": "Deutscher Kommentar"}
    creator_window.active_comment_lang = "en"
    creator_window.update_comment_lang_button_style()
    
    btn = creator_window.btn_lang_comment
    assert "🌐 EN" in btn.text()
    # Should highlight in burnt orange because 'en' is empty but 'DE' exists
    assert "burnt_orange" in btn.styleSheet() or "e67e22" in btn.styleSheet()
    
    # Switch back to DE
    creator_window.switch_comment_lang("de")
    assert "🌐 DE" in btn.text()
    assert creator_window.txt_c.toPlainText() == "Deutscher Kommentar"

def test_combine_comments_with_target_lang():
    """Test target_lang parameter when combining plain comments."""
    res_en = combine_comments("", "English plain comment", default_lang="en")
    dict_en = get_multilingual_comment_dict(res_en, default_lang="en")
    assert dict_en.get("en") == "English plain comment"
    assert dict_en.get("de") is None
