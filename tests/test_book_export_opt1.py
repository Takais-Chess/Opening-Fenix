import os
import sqlite3
import pytest
from opening_fenix.core.services.book_export_service import export_repertoire_book, flatten_subtree

def test_option1_sideline_and_inline_transposition(tmp_path):
    # Tests Option 1:
    # 1) White sideline + Black reply merge into heading: e.g. A) 3.d4 exd4
    # 2) Transpositions render inline with move: e.g. <span class="transposition-inline">*(↳ Zugumstellung...)*</span>
    # 3) Pass 2 embeds exact page numbers if available
    db_path = str(tmp_path / "opt1_repo.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Opt1 Test')")
    cur.execute("INSERT INTO metadata VALUES ('color', 'b')")
    cur.execute("CREATE TABLE repertoire_levels (id INTEGER PRIMARY KEY, name VARCHAR, `order` INTEGER, target_elo INTEGER)")
    cur.execute("INSERT INTO repertoire_levels VALUES (1, 'Level 1', 1, 1500)")
    cur.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, fen VARCHAR, comment VARCHAR, variation_1 VARCHAR)")
    cur.execute("CREATE TABLE moves (id INTEGER PRIMARY KEY, from_position_id INTEGER, to_position_id INTEGER, uci VARCHAR, san VARCHAR, priority_score FLOAT)")
    cur.execute("CREATE TABLE repertoire_moves (id INTEGER PRIMARY KEY, move_id INTEGER, level INTEGER, is_active BOOLEAN)")

    # Pos 1: start
    cur.execute("INSERT INTO positions VALUES (1, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -', '', '')")
    # Pos 2: after 1.e4
    cur.execute("INSERT INTO positions VALUES (2, 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -', '', '')")
    # Pos 3: after 1...e5
    cur.execute("INSERT INTO positions VALUES (3, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -', '', '')")
    # Main line: 2.Bc4 (pos 4) -> 2...Nf6 (pos 5) -> 3.d3 (pos 6)
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR b KQkq -', '', '2.Bc4')")
    cur.execute("INSERT INTO positions VALUES (5, 'rnbqkbnr/pppp1ppp/5n2/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (6, 'rnbqkbnr/pppp1ppp/5n2/4p3/2B1P3/3P4/PPP2PPP/RNBQK1NR b KQkq -', 'Main line', '')")

    # Sideline: 3.d4 (pos 7) -> 3...exd4 (pos 8) -> 4.Nf3 (pos 9) -> 4...Nc6 (pos 100 -> transposes to target pos 100)
    cur.execute("INSERT INTO positions VALUES (7, 'rnbqkbnr/pppp1ppp/5n2/4p3/2BPP3/8/PPP2PPP/RNBQK1NR b KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (8, 'rnbqkbnr/pppp1ppp/5n2/8/2BpP3/8/PPP2PPP/RNBQK1NR w KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (9, 'rnbqkbnr/pppp1ppp/5n2/8/2BpP3/5N2/PPP2PPP/RNBQK2R b KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (100, 'r1bqkb1r/pppp1ppp/2n2n2/8/2BpP3/5N2/PPP2PPP/RNBQK2R w KQkq -', 'Target in Italian', '3.Bc4')")

    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'f1c4', 'Bc4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'g8f6', 'Nf6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (5, 5, 6, 'd2d3', 'd3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (6, 5, 7, 'd2d4', 'd4', 80.0)") # Sideline
    cur.execute("INSERT INTO moves VALUES (7, 7, 8, 'e5d4', 'exd4', 80.0)") # Reply
    cur.execute("INSERT INTO moves VALUES (8, 8, 9, 'g1f3', 'Nf3', 80.0)")
    cur.execute("INSERT INTO moves VALUES (9, 9, 100, 'b8c6', 'Nc6', 80.0)") # Transposition

    for i in range(1, 10):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (i, i))
    conn.commit()
    conn.close()

    out_html = str(tmp_path / "opt1_book.html")
    res = export_repertoire_book(
        db_path=db_path,
        output_path=out_html,
        output_format="html",
        level=1,
        language="de"
    )
    with open(res, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Sideline heading combines 3.d4 and reply exd4
    assert "<span class='moves'>3.d4 exd4</span>" in html or "3.d4 exd4" in html

    # 2. Transposition class and inline element exists
    assert "transposition-inline" in html

def test_page_map_passed_to_flatten_subtree(tmp_path):
    db_path = str(tmp_path / "page_map_repo.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Page Map Test')")
    cur.execute("INSERT INTO metadata VALUES ('color', 'b')")
    cur.execute("CREATE TABLE repertoire_levels (id INTEGER PRIMARY KEY, name VARCHAR, `order` INTEGER, target_elo INTEGER)")
    cur.execute("INSERT INTO repertoire_levels VALUES (1, 'Level 1', 1, 1500)")
    cur.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, fen VARCHAR, comment VARCHAR, variation_1 VARCHAR)")
    cur.execute("CREATE TABLE moves (id INTEGER PRIMARY KEY, from_position_id INTEGER, to_position_id INTEGER, uci VARCHAR, san VARCHAR, priority_score FLOAT)")
    cur.execute("CREATE TABLE repertoire_moves (id INTEGER PRIMARY KEY, move_id INTEGER, level INTEGER, is_active BOOLEAN)")

    cur.execute("INSERT INTO positions VALUES (1, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (2, 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (3, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (5, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -', '', '')")

    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'g1f3', 'Nf3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'b8c6', 'Nc6', 100.0)")

    for i in range(1, 5):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (i, i))
    conn.commit()

    visited = {
        5: {"chap_idx": 2, "chap_title": "Italian Game", "san_path": "1.e4 e5 2.Nf3 Nc6"}
    }
    page_map = {2: 42}

    html = flatten_subtree(
        conn=conn,
        start_pos_id=3,
        start_move_num=2,
        is_white_turn=True,
        color='b',
        level=1,
        language="de",
        visited_positions=visited,
        chap_idx=1,
        chap_title="Spanish Game",
        page_map=page_map
    )
    conn.close()

    # Should contain inline transposition with page 42 (S. 42)
    assert "S. 42" in html
    assert "transposition-inline" in html
