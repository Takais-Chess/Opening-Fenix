import pytest
from opening_fenix.core.utils import (
    get_multilingual_variation_dict,
    parse_variation_name,
    format_multilingual_variation,
)


def test_get_multilingual_variation_dict_plain():
    d = get_multilingual_variation_dict("Spanische Partie", default_lang="de")
    assert d == {"de": "Spanische Partie"}

    d_en = get_multilingual_variation_dict("Ruy Lopez", default_lang="en")
    assert d_en == {"en": "Ruy Lopez"}

    assert get_multilingual_variation_dict("") == {}
    assert get_multilingual_variation_dict(None) == {}


def test_get_multilingual_variation_dict_json():
    raw = '{"de": "Spanische Partie", "en": "Ruy Lopez"}'
    d = get_multilingual_variation_dict(raw)
    assert d == {"de": "Spanische Partie", "en": "Ruy Lopez"}


def test_parse_variation_name():
    # Plain text returns plain text regardless of language
    assert parse_variation_name("Königsindisch", lang="de") == "Königsindisch"
    assert parse_variation_name("Königsindisch", lang="en") == "Königsindisch"

    # Multilingual JSON
    raw = '{"de": "Spanisch", "en": "Ruy Lopez"}'
    assert parse_variation_name(raw, lang="de") == "Spanisch"
    assert parse_variation_name(raw, lang="en") == "Ruy Lopez"
    assert parse_variation_name(raw, lang="auto", default_lang="de") == "Spanisch"
    assert parse_variation_name(raw, lang="auto", default_lang="en") == "Ruy Lopez"

    # Fallback when requested language missing
    raw_de_only = '{"de": "Berliner Verteidigung"}'
    assert parse_variation_name(raw_de_only, lang="en", default_lang="de") == "Berliner Verteidigung"

    # All languages
    raw_both = '{"de": "Drache", "en": "Dragon"}'
    assert parse_variation_name(raw_both, lang="all") == "[DE] Drache / [EN] Dragon"

    # Empty
    assert parse_variation_name("") == ""
    assert parse_variation_name(None) == ""


def test_format_multilingual_variation():
    # Empty
    assert format_multilingual_variation({}) == ""

    # Single language DE returns plain text
    assert format_multilingual_variation({"de": "Französisch"}) == "Französisch"

    # Multiple languages preserve both keys in JSON
    res_same = format_multilingual_variation({"de": "Najdorf", "en": "Najdorf"})
    assert '"de": "Najdorf"' in res_same
    assert '"en": "Najdorf"' in res_same

    # Multiple distinct languages return JSON
    res = format_multilingual_variation({"de": "Spanisch", "en": "Ruy Lopez"})
    assert '"de": "Spanisch"' in res
    assert '"en": "Ruy Lopez"' in res


def test_matches_variation_name():
    from opening_fenix.core.utils import matches_variation_name

    assert matches_variation_name("Ruy Lopez", "Ruy Lopez") is True
    assert matches_variation_name("ruy lopez", "Ruy Lopez") is True
    assert matches_variation_name("French Defense", "Ruy Lopez") is False
    assert matches_variation_name(None, "Ruy Lopez") is False
    assert matches_variation_name("Ruy Lopez", None) is False

    raw_json = '{"de": "Spanische Partie", "en": "Ruy Lopez"}'
    assert matches_variation_name(raw_json, "Spanische Partie") is True
    assert matches_variation_name(raw_json, "spanische partie") is True
    assert matches_variation_name(raw_json, "Ruy Lopez") is True
    assert matches_variation_name(raw_json, "ruy lopez") is True
    assert matches_variation_name(raw_json, "Sicilian") is False


def test_multilingual_variation_structure_and_filter(tmp_path):
    import sqlite3
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base, Position, Move
    from opening_fenix.core.services.tree_navigation_service import TreeNavigationService

    db_path = str(tmp_path / "test_multi_var.db")
    db_mgr = DatabaseManager(db_path, base=Base)
    session = db_mgr.get_session()

    # Root position
    p_root = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    session.add(p_root)
    session.flush()

    # 1. e4 with multilingual variation
    p_e4 = Position(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        variation_1='{"de": "Königsbauernspiel", "en": "King Pawn Game"}',
        variation_2='{"de": "Offene Spiele", "en": "Open Games"}'
    )
    session.add(p_e4)
    session.flush()

    m1 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4", priority_score=1.0)
    session.add(m1)
    session.commit()

    nav = TreeNavigationService(session)

    # 1. Structure localized to German
    struct_de = nav.get_variation_structure(lang="de")
    assert "Königsbauernspiel" in struct_de
    assert "Offene Spiele" in struct_de["Königsbauernspiel"]

    # 2. Structure localized to English
    struct_en = nav.get_variation_structure(lang="en")
    assert "King Pawn Game" in struct_en
    assert "Open Games" in struct_en["King Pawn Game"]

    # 3. Filter info works for both languages
    filter_de = nav.get_variation_filter_info("Königsbauernspiel")
    assert p_e4.id in filter_de["roots"]
    assert p_root.id in filter_de["lead_up"]

    filter_en = nav.get_variation_filter_info("King Pawn Game")
    assert p_e4.id in filter_en["roots"]
    assert p_root.id in filter_en["lead_up"]

    # 4. Entry point FEN works for both languages
    fen_de = nav.get_variation_entry_point_fen("Königsbauernspiel")
    assert fen_de == p_e4.fen
    fen_en = nav.get_variation_entry_point_fen("King Pawn Game")
    assert fen_en == p_e4.fen

    session.close()
    db_mgr.close()


def test_creator_variation_language_button_switching(creator_window, qapp):
    """Test controlling and editing variation names across languages using the comment language button."""
    cw = creator_window
    # Ensure starting in DE
    cw.switch_comment_lang("de")
    assert cw.active_comment_lang == "de"
    assert "DE" in cw.i_v1.placeholderText()

    # User enters German variation name
    cw.i_v1.setText("Spanische Partie")
    cw.on_details_changed()

    assert cw.current_position_variations[1]["de"] == "Spanische Partie"

    # User switches language to English via comment language button
    cw.switch_comment_lang("en")
    assert cw.active_comment_lang == "en"
    assert "EN" in cw.i_v1.placeholderText()
    # Field for English should currently be empty
    assert cw.i_v1.text() == ""

    # User enters English variation name
    cw.i_v1.setText("Ruy Lopez")
    cw.on_details_changed()

    assert cw.current_position_variations[1]["en"] == "Ruy Lopez"
    assert cw.current_position_variations[1]["de"] == "Spanische Partie"

    # Switch back to German - text should restore to "Spanische Partie"
    cw.switch_comment_lang("de")
    assert cw.active_comment_lang == "de"
    assert cw.i_v1.text() == "Spanische Partie"

    # Switch back to English - text should restore to "Ruy Lopez"
    cw.switch_comment_lang("en")
    assert cw.active_comment_lang == "en"
    assert cw.i_v1.text() == "Ruy Lopez"

    # Save and verify formatted JSON in backend
    cw.save_current_details_now()
    pos_data = cw.backend.get_position_data(cw.board_widget.board.fen())
    assert pos_data is not None
    v1_raw = pos_data.get("variation_1")
    assert '"de": "Spanische Partie"' in v1_raw
    assert '"en": "Ruy Lopez"' in v1_raw


def test_open_training_dialog_variation_language_sync(tmp_path, qapp):
    """Test that OpenTrainingSetupDialog updates variation names when comment language changes."""
    import os
    import json
    from unittest.mock import MagicMock
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base, Position, Move, Metadata
    from opening_fenix.gui.dialogs.open_training_dialog import OpenTrainingSetupDialog, fetch_variation_structure_for_repo

    # Create dummy repo database
    db_file = str(tmp_path / "MultiVarRepo.db")
    db = DatabaseManager(db_file, base=Base)
    session = db.get_session()
    session.add(Metadata(key="comment_language", value="de"))
    session.add(Position(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        variation_1='{"de": "Königsbauer", "en": "King Pawn"}'
    ))
    session.commit()
    session.close()
    db.close()

    # Verify fetch_variation_structure_for_repo with languages
    from unittest.mock import patch
    with patch("opening_fenix.gui.dialogs.open_training_dialog.get_repertoire_db_path", return_value=db_file):
        s_de = fetch_variation_structure_for_repo("MultiVarRepo", lang="de")
        assert "Königsbauer" in s_de

        s_en = fetch_variation_structure_for_repo("MultiVarRepo", lang="en")
        assert "King Pawn" in s_en


def test_copy_and_move_repertoire_variations(tmp_path, monkeypatch):
    """Test copy_repertoire_variations for both copy and move modes."""
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base, Position, Move
    from opening_fenix.core.data_tools import copy_repertoire_variations
    from opening_fenix.core.utils import get_multilingual_variation_dict

    db_file = str(tmp_path / "TransferVarRepo.db")
    monkeypatch.setattr("opening_fenix.core.utils.get_repertoire_db_path", lambda name: db_file)

    db = DatabaseManager(db_file, base=Base)
    session = db.get_session()

    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    p_start = Position(fen=start_fen)
    session.add(p_start)
    session.flush()

    p_e4 = Position(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        variation_1="Königsbauernspiel",
        variation_2="Offene Spiele"
    )
    session.add(p_e4)
    session.flush()

    m = Move(from_position_id=p_start.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    session.add(m)
    session.commit()
    session.close()
    db.close()

    # 1. Test same language error
    ok, msg, count = copy_repertoire_variations("TransferVarRepo", "de", "de")
    assert ok is False
    assert count == 0

    # 2. Test COPY (DE -> EN, overwrite=False, remove_source=False)
    ok, msg, count = copy_repertoire_variations("TransferVarRepo", "de", "en", overwrite=False, remove_source=False)
    assert ok is True
    assert count == 1

    db = DatabaseManager(db_file, base=Base)
    session = db.get_session()
    loaded_pos = session.query(Position).filter_by(fen=p_e4.fen).first()
    v1_dict = get_multilingual_variation_dict(loaded_pos.variation_1)
    assert v1_dict.get("de") == "Königsbauernspiel"
    assert v1_dict.get("en") == "Königsbauernspiel"
    session.close()
    db.close()

    # 3. Test MOVE (DE -> ES, overwrite=True, remove_source=True)
    ok, msg, count = copy_repertoire_variations("TransferVarRepo", "de", "es", overwrite=True, remove_source=True)
    assert ok is True
    assert count == 1

    db = DatabaseManager(db_file, base=Base)
    session = db.get_session()
    loaded_pos2 = session.query(Position).filter_by(fen=p_e4.fen).first()
    v1_dict2 = get_multilingual_variation_dict(loaded_pos2.variation_1)
    assert v1_dict2.get("de") is None  # Source removed
    assert v1_dict2.get("es") == "Königsbauernspiel"
    assert v1_dict2.get("en") == "Königsbauernspiel"
    session.close()
    db.close()
