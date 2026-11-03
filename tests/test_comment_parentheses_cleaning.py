import pytest
import json
from opening_fenix.core.utils import (
    strip_outer_parentheses_single,
    clean_outer_parentheses_from_text,
    clean_comment_parentheses,
    clean_comment_text,
    combine_comments,
    get_multilingual_comment_dict
)
from opening_fenix.core.services.course_import_service import sanitize_comment_variations
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Position
from opening_fenix.creator.creator_window import CreatorBackend


def test_strip_outer_parentheses_single():
    # Simple enclosing parens
    assert strip_outer_parentheses_single("(Hello world)") == "Hello world"
    assert strip_outer_parentheses_single("((Double enclosed))") == "Double enclosed"
    assert strip_outer_parentheses_single("(((Triple enclosed)))") == "Triple enclosed"

    # Preserves in-sentence parenthetical notes
    s_in_sentence = "White is better (threatening d5), but Black has resources."
    assert strip_outer_parentheses_single(s_in_sentence) == s_in_sentence

    # Preserves multiple disjoint parenthetical blocks
    s_disjoint = "(Kasparov 1985) and (Karpov 1984)"
    assert strip_outer_parentheses_single(s_disjoint) == s_disjoint

    # Preserves inner parentheses when peeling outer envelope
    s_nested = "(Developing the knight (historically main line) is solid)"
    assert strip_outer_parentheses_single(s_nested) == "Developing the knight (historically main line) is solid"

    # Preserves ChessBase [%cal ...] and [%csl ...] tags
    s_tags = "[%cal Rd1d4][%csl Rd2,Gd3,Rd4] (Developing the knight has to be the most logical move.)"
    cleaned_tags = strip_outer_parentheses_single(s_tags)
    assert "[%cal Rd1d4][%csl Rd2,Gd3,Rd4]" in cleaned_tags
    assert "Developing the knight has to be the most logical move." in cleaned_tags
    assert "(" not in cleaned_tags and ")" not in cleaned_tags


def test_clean_outer_parentheses_from_text():
    # User's Image 1 case (merged segments with ' | ')
    t1 = "(Developing the knight has to be the most logical move.) | 9. Bb3, but after we castle White is fine."
    assert clean_outer_parentheses_from_text(t1) == "Developing the knight has to be the most logical move. | 9. Bb3, but after we castle White is fine."

    # User's Image 2 case (entire comment)
    t2 = "(For 10.h3 see the relevant chapter, and)"
    assert clean_outer_parentheses_from_text(t2) == "For 10.h3 see the relevant chapter, and"

    # Multi-paragraph comments
    t3 = "(First paragraph of commentary.)\n\n(Second paragraph of commentary.)"
    assert clean_outer_parentheses_from_text(t3) == "First paragraph of commentary.\n\nSecond paragraph of commentary."

    # Unwrapped paragraph with inline notes untouched
    t4 = "Standard move. (Better was 5.Nf3)\n\nEnd of note."
    assert clean_outer_parentheses_from_text(t4) == t4


def test_clean_comment_parentheses_multilingual():
    # Plain text comment
    res, changed = clean_comment_parentheses("(Plain comment)")
    assert changed is True
    assert res == "Plain comment"

    # Multilingual JSON comment
    raw_json = json.dumps({"en": "(English note)", "de": "(Deutsche Notiz)", "es": "Sin parentesis"})
    res_json, changed_json = clean_comment_parentheses(raw_json)
    assert changed_json is True
    data = json.loads(res_json)
    assert data["en"] == "English note"
    assert data["de"] == "Deutsche Notiz"
    assert data["es"] == "Sin parentesis"

    # Unchanged comment
    res_un, changed_un = clean_comment_parentheses("White is slightly better (+=).")
    assert changed_un is False
    assert res_un == "White is slightly better (+=)."


def test_clean_comment_text_and_combine_comments():
    raw_incoming = "(For 10.h3 see the relevant chapter, and)"
    cleaned = clean_comment_text(raw_incoming)
    assert cleaned == "For 10.h3 see the relevant chapter, and"

    # Combined comments
    c1 = "(First chapter comment)"
    c2 = "Second chapter comment"
    combined = combine_comments(c1, c2, default_lang="en")
    c_dict = get_multilingual_comment_dict(combined, default_lang="en")
    assert "First chapter comment | Second chapter comment" in c_dict.get("en", "")


def test_sanitize_comment_variations_course_import():
    # Test that pre-sanitizer for course imports no longer wraps converted comments in redundant parentheses
    pgn_fragment = "({Developing the knight is standard} 9.h3!?)"
    sanitized = sanitize_comment_variations(pgn_fragment)
    assert "{ (" not in sanitized
    assert "Developing the knight is standard" in sanitized


def test_clean_parentheses_in_repo_backend(tmp_path):
    db_file = tmp_path / "test_repo.db"
    db = DatabaseManager(str(db_file))
    session = db.get_session()

    # Insert test positions with different comment formats
    p1 = Position(id=1, fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1", comment="(1. e4 is the best by test.)")
    p2 = Position(id=2, fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", comment=json.dumps({"en": "(Open game with 1...e5)", "de": "(Offenes Spiel)"}))
    p3 = Position(id=3, fen="rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", comment="Sicilian Defense (2...c5 is aggressive)")
    session.add_all([p1, p2, p3])
    session.commit()

    backend = CreatorBackend()
    backend.session = session

    cleaned_count = backend.clean_parentheses_in_repo()
    assert cleaned_count == 2  # p1 and p2 cleaned, p3 untouched

    # Verify positions in DB
    refreshed_p1 = session.query(Position).filter_by(id=1).first()
    assert refreshed_p1.comment == "1. e4 is the best by test."

    refreshed_p2 = session.query(Position).filter_by(id=2).first()
    p2_data = json.loads(refreshed_p2.comment)
    assert p2_data["en"] == "Open game with 1...e5"
    assert p2_data["de"] == "Offenes Spiel"

    refreshed_p3 = session.query(Position).filter_by(id=3).first()
    assert refreshed_p3.comment == "Sicilian Defense (2...c5 is aggressive)"

    session.close()
    db.close()
