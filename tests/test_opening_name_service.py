import pytest
from opening_fenix.core.services.opening_name_service import (
    load_openings_database,
    clean_fen,
    get_suggested_variation_names,
)


def test_load_openings_database():
    db = load_openings_database()
    assert isinstance(db, dict)
    assert len(db) > 3000


def test_get_suggested_variation_names_exact():
    # 1. e4 c5 (Sicilian Defense)
    # FEN after 1. e4 c5: rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2
    fen_sicilian = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6"
    
    sug_de = get_suggested_variation_names(fen_sicilian, lang="de")
    assert sug_de is not None
    assert sug_de["eco"] == "B20"
    assert "Sizilianisch" in sug_de["v1"]

    sug_en = get_suggested_variation_names(fen_sicilian, lang="en")
    assert sug_en is not None
    assert sug_en["v1"] == "Sicilian Defense"


def test_get_suggested_variation_names_no_ancestor_leak():
    # A position after 1. e4 c5 2. Nf3 (or deeper moves not in DB as a new opening)
    # Suggestions should ONLY trigger on the exact starting position, not on subsequent moves!
    fen_sicilian = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6"
    fen_deep = "8/8/8/8/8/8/8/4K2k w - - 0 1"
    
    sug = get_suggested_variation_names(fen_deep, lang="en", ancestor_fens=[fen_sicilian])
    assert sug is None


def test_get_suggested_variation_names_unknown():
    res = get_suggested_variation_names("8/8/8/8/8/8/8/4K2k w - -")
    assert res is None


def test_creator_variation_suggestions(creator_window, qapp):
    # Position after 1. e4 c5 (Sicilian Defense)
    fen_sicilian = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2"
    creator_window.active_comment_lang = "de"
    creator_window.set_board_to_fen(fen_sicilian)
    creator_window.i_v1.setText("")
    creator_window.i_v2.setText("")
    creator_window.i_v3.setText("")
    creator_window.current_position_inherited_variations = {1: {}, 2: {}, 3: {}}
    creator_window._update_variation_suggestions(fen_sicilian)
    qapp.processEvents()

    # Only the first empty slot (v1) should have a visible button
    assert creator_window.btn_suggest_v1.isVisible()
    assert not creator_window.btn_suggest_v2.isVisible()
    assert not creator_window.btn_suggest_v3.isVisible()
    assert "Sizilianisch" in creator_window.btn_suggest_v1.toolTip()

    # Apply suggestion
    creator_window.apply_suggested_variation_name(1)
    qapp.processEvents()
    assert "Sizilianisch" in creator_window.i_v1.text()

    # Once named, the button should immediately hide itself
    creator_window._update_variation_suggestions(fen_sicilian)
    qapp.processEvents()
    assert not creator_window.btn_suggest_v1.isVisible()

    # Test unknown / subsequent position hides all buttons
    fen_unknown = "8/8/8/8/8/8/8/4K2k w - - 0 1"
    creator_window._update_variation_suggestions(fen_unknown)
    qapp.processEvents()
    assert not creator_window.btn_suggest_v1.isVisible()
    assert not creator_window.btn_suggest_v2.isVisible()
    assert not creator_window.btn_suggest_v3.isVisible()


def test_creator_subvariation_and_already_named_line(creator_window, qapp):
    import chess
    b = chess.Board()
    for m in ['e4', 'c5', 'Nf3', 'd6', 'd4', 'cxd4', 'Nxd4', 'Nf6', 'Nc3', 'g6']:
        b.push_san(m)
    fen_dragon = b.fen()

    # Case 1: Slot 1 is already named ("Sizilianische Verteidigung"), Slot 2 is empty
    creator_window.active_comment_lang = "de"
    creator_window.set_board_to_fen(fen_dragon)
    creator_window.i_v1.setText("Sizilianische Verteidigung")
    creator_window.i_v2.setText("")
    creator_window.i_v3.setText("")
    creator_window.current_position_inherited_variations = {1: {}, 2: {}, 3: {}}
    creator_window._update_variation_suggestions(fen_dragon)
    qapp.processEvents()

    # Slot 1 already has a name -> btn_suggest_v1 hidden
    assert not creator_window.btn_suggest_v1.isVisible()
    # Slot 2 is empty -> btn_suggest_v2 visible with Drachenvariante
    assert creator_window.btn_suggest_v2.isVisible()
    assert not creator_window.btn_suggest_v3.isVisible()
    assert "Drache" in creator_window.btn_suggest_v2.toolTip()

    # Case 2: Line already has names (like in user screenshot: v1='Sizilianischer Drache', v2='Klassisches System')
    creator_window.i_v1.setText("Sizilianischer Drache")
    creator_window.i_v2.setText("Klassisches System")
    creator_window.i_v3.setText("")
    creator_window._update_variation_suggestions(fen_dragon)
    qapp.processEvents()

    # Both v1 and v2 already named, and Dragon is already in the line -> NO buttons visible!
    assert not creator_window.btn_suggest_v1.isVisible()
    assert not creator_window.btn_suggest_v2.isVisible()
    assert not creator_window.btn_suggest_v3.isVisible()


