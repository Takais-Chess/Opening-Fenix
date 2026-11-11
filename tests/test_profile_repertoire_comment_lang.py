import pytest
import sqlite3
import json
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import UserBase, UserRepertoireSettings, Position, Metadata, Base
from opening_fenix.core.services.repertoire_core_service import (
    get_repertoire_comment_languages_fast,
    invalidate_repertoire_comment_languages_cache,
    _comment_languages_cache
)
from opening_fenix.core.services.training_service import TrainingManager
from opening_fenix.core.utils import parse_comment


def test_user_repertoire_settings_comment_language(tmp_path):
    """Test that UserRepertoireSettings stores and migrates comment_language."""
    db_file = str(tmp_path / "test_profile.db")
    db = DatabaseManager(db_file, base=UserBase)
    session = db.get_session()

    # Create new settings with comment_language
    urs = UserRepertoireSettings(repertoire_name="French Defense", active_level=2, comment_language="en")
    session.add(urs)
    session.commit()

    loaded = session.query(UserRepertoireSettings).filter_by(repertoire_name="French Defense").first()
    assert loaded is not None
    assert loaded.comment_language == "en"

    # Test default value
    urs_default = UserRepertoireSettings(repertoire_name="Caro-Kann")
    session.add(urs_default)
    session.commit()

    loaded_default = session.query(UserRepertoireSettings).filter_by(repertoire_name="Caro-Kann").first()
    assert loaded_default.comment_language == "auto"

    session.close()
    db.close()


def test_training_service_comment_language(tmp_path):
    """Test get_comment_language and set_comment_language on TrainingService."""
    db_file = str(tmp_path / "ts_profile.db")
    db = DatabaseManager(db_file, base=UserBase)

    ts = TrainingManager("TestProfile", None)
    ts.user_session = db.get_session()

    # Initial lookup returns 'auto'
    assert ts.get_comment_language("Sicilian") == "auto"

    # Set language to German
    ts.set_comment_language("de", "Sicilian")
    assert ts.get_comment_language("Sicilian") == "de"

    # Change to English
    ts.set_comment_language("en", "Sicilian")
    assert ts.get_comment_language("Sicilian") == "en"

    ts.user_session.close()
    db.close()


def test_get_repertoire_comment_languages_fast(tmp_path, monkeypatch):
    """Test low-CPU-cost lookup of available languages in a repertoire."""
    db_file = str(tmp_path / "repo_german_only.db")
    monkeypatch.setattr("opening_fenix.core.services.repertoire_core_service.get_repertoire_db_path", lambda name: db_file)

    # 1. Create a DB with only German comments
    db = DatabaseManager(db_file, base=Base)
    session = db.get_session()
    session.add(Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1", comment="Solider Königsbauernzug."))
    session.commit()
    session.close()
    db.close()

    invalidate_repertoire_comment_languages_cache("repo_german_only")
    langs = get_repertoire_comment_languages_fast("repo_german_only")
    assert langs == ["de"]

    # Verify it wrote to metadata table for zero CPU next time
    with sqlite3.connect(db_file) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM metadata WHERE key = 'available_comment_languages'")
        row = c.fetchone()
        assert row is not None
        assert json.loads(row[0]) == ["de"]

    # 2. Add English comment to make it multilingual
    db = DatabaseManager(db_file, base=Base)
    session = db.get_session()
    session.add(Position(
        fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1",
        comment=json.dumps({"en": "Queen's pawn opening.", "de": "Damenbauern-Eröffnung."})
    ))
    # Clear metadata cache entry so it recomputes
    session.query(Metadata).filter_by(key="available_comment_languages").delete()
    session.commit()
    session.close()
    db.close()

    invalidate_repertoire_comment_languages_cache("repo_german_only")
    langs_multi = get_repertoire_comment_languages_fast("repo_german_only")
    assert sorted(langs_multi) == ["de", "en"]


def test_parse_comment_no_cross_language_fallback():
    """Verify that comments strictly show only the selected language."""
    multi_comment = json.dumps({"de": "Guter Springerzug.", "en": "Good knight move."})
    de_only = json.dumps({"de": "Nur auf Deutsch vorhanden."})
    en_only = json.dumps({"en": "Only available in English."})

    # When target is German:
    assert parse_comment(multi_comment, "de") == "Guter Springerzug."
    assert parse_comment(de_only, "de") == "Nur auf Deutsch vorhanden."
    assert parse_comment(en_only, "de") == ""  # NO FALLBACK to English!

    # When target is English:
    assert parse_comment(multi_comment, "en") == "Good knight move."
    assert parse_comment(en_only, "en") == "Only available in English."
    assert parse_comment(de_only, "en") == ""  # NO FALLBACK to German!

    # When requesting an unsupported language (e.g., Spanish):
    assert parse_comment(multi_comment, "es") == ""


def test_parse_comment_all_languages():
    """Verify that 'all' comment language returns all available translations formatted."""
    multi_comment = json.dumps({"de": "Guter Springerzug.", "en": "Good knight move."})
    de_only = json.dumps({"de": "Nur auf Deutsch vorhanden."})
    en_only = json.dumps({"en": "Only available in English."})
    plain = "Klassischer Zug."
    pgn_tagged = "[:de] Text DE [:en] Text EN"

    # Multi: returns [DE] first, then [EN]
    parsed_multi = parse_comment(multi_comment, "all")
    assert "[DE] Guter Springerzug." in parsed_multi
    assert "[EN] Good knight move." in parsed_multi
    lines = parsed_multi.split("\n")
    assert lines[0] == "[DE] Guter Springerzug."
    assert lines[1] == "[EN] Good knight move."

    # Single-language in JSON
    assert parse_comment(de_only, "all") == "[DE] Nur auf Deutsch vorhanden."
    assert parse_comment(en_only, "all") == "[EN] Only available in English."

    # Plain text comment
    assert parse_comment(plain, "all") == "Klassischer Zug."

    # PGN tagged
    parsed_pgn = parse_comment(pgn_tagged, "all")
    assert "[DE] Text DE" in parsed_pgn
    assert "[EN] Text EN" in parsed_pgn


def test_training_service_comment_language_all(tmp_path):
    """Test setting and getting 'all' language in TrainingService."""
    db_file = str(tmp_path / "ts_profile_all.db")
    db = DatabaseManager(db_file, base=UserBase)

    ts = TrainingManager("TestProfile", None)
    ts.user_session = db.get_session()

    ts.set_comment_language("all", "French Defense")
    assert ts.get_comment_language("French Defense") == "all"

    ts.user_session.close()
    db.close()
