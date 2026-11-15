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


def test_sideline_start_diagram_rules(tmp_path):
    """
    Verifies the rule for sideline starts:
    - If sideline start has comments and next move does NOT show a diagram -> show diagram at sideline start.
    - If sideline start has comments and next move DOES show a diagram -> do NOT duplicate diagram.
    """
    db_path = str(tmp_path / "sideline_rules.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Sideline Rules')")
    cur.execute("INSERT INTO metadata VALUES ('color', 'b')")
    cur.execute("CREATE TABLE repertoire_levels (id INTEGER PRIMARY KEY, name VARCHAR, `order` INTEGER, target_elo INTEGER)")
    cur.execute("INSERT INTO repertoire_levels VALUES (1, 'Level 1', 1, 1500)")
    cur.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, fen VARCHAR, comment VARCHAR, variation_1 VARCHAR, variation_2 VARCHAR, variation_3 VARCHAR)")
    cur.execute("CREATE TABLE moves (id INTEGER PRIMARY KEY, from_position_id INTEGER, to_position_id INTEGER, uci VARCHAR, san VARCHAR, priority_score FLOAT)")
    cur.execute("CREATE TABLE repertoire_moves (id INTEGER PRIMARY KEY, move_id INTEGER, level INTEGER, is_active BOOLEAN)")

    # 1. Start -> 2. 1.e4 -> 3. 1...e5 -> 4. 2.Nf3 -> 5. 2...Nc6 -> 6. 3.Bb5 a6 (start of chapter 1)
    cur.execute("INSERT INTO positions VALUES (1, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (2, 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (3, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (5, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (6, 'r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', 'Ruy Lopez', '', '')")
    cur.execute("INSERT INTO positions VALUES (7, 'r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', '', '', '', '')")

    # Main: 4.Ba4 (pos 8) -> 4...Sf6 (pos 9)
    cur.execute("INSERT INTO positions VALUES (8, 'r1bqkbnr/1ppp1ppp/p1n5/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (9, 'r1bqkb1r/1ppp1ppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', 'Main text', '', '', '')")

    # Sideline A (next move HAS drawings): 4.Bxc6 (pos 10) -> 4...dxc6 (pos 11, has comment) -> 5.0-0 (pos 12) -> 5...Qf6 (pos 13, has arrow [%cal Ge8g8])
    cur.execute("INSERT INTO positions VALUES (10, 'r1bqkbnr/1ppp1ppp/p1B5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', '', 'Exchange Spanish', '')")
    cur.execute("INSERT INTO positions VALUES (11, 'r1bqkbnr/1pp2ppp/p1p5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', 'Kommentar zum Damentausch', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (12, 'r1bqkbnr/1pp2ppp/p1p5/4p3/4P3/5N2/PPPP1PPP/RNBQ1RK1 b kq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (13, 'r1b1kbnr/1pp2ppp/p1p2q2/4p3/4P3/5N2/PPPP1PPP/RNBQ1RK1 w kq -', 'Plan mit Rochade [%cal Ge8g8]', '', '', '')")

    # Sideline B (next move does NOT have drawings or leaf): 4.c3 (pos 14) -> 4...d5 (pos 15, has comment) -> 5.exd5 (pos 16) -> 5...Qxd5 (pos 17) -> 6.d4 (pos 18)
    cur.execute("INSERT INTO positions VALUES (14, 'r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/2P2N2/PP1P1PPP/RNBQK2R b KQkq -', '', '', 'Delayed Center', '')")
    cur.execute("INSERT INTO positions VALUES (15, 'r1bqkbnr/1pp2ppp/p1n5/1B1pp3/4P3/2P2N2/PP1P1PPP/RNBQK2R w KQkq -', 'Aktiver Vorstoß im Zentrum', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (16, 'r1bqkbnr/1pp2ppp/p1n5/1B1Pp3/8/2P2N2/PP1P1PPP/RNBQK2R b KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (17, 'r1b1kbnr/1pp2ppp/p1n5/1B1qp3/8/2P2N2/PP1P1PPP/RNBQK2R w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (18, 'r1b1kbnr/1pp2ppp/p1n5/1B1qp3/3P4/2P2N2/PP3PPP/RNBQK2R b KQkq -', 'Folgezug', '', '', '')")

    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'g1f3', 'Nf3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'b8c6', 'Nc6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (5, 5, 6, 'f1b5', 'Bb5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (6, 6, 7, 'a7a6', 'a6', 100.0)")

    # Main
    cur.execute("INSERT INTO moves VALUES (7, 7, 8, 'b5a4', 'Ba4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (8, 8, 9, 'g8f6', 'Nf6', 100.0)")

    # Sideline A (4.Bxc6 dxc6 -> 5.0-0 Qf6 with arrow)
    cur.execute("INSERT INTO moves VALUES (9, 7, 10, 'b5c6', 'Bxc6', 90.0)")
    cur.execute("INSERT INTO moves VALUES (10, 10, 11, 'd7c6', 'dxc6', 90.0)")
    cur.execute("INSERT INTO moves VALUES (11, 11, 12, 'e1g1', '0-0', 90.0)")
    cur.execute("INSERT INTO moves VALUES (12, 12, 13, 'd8f6', 'Qf6', 90.0)")

    # Sideline B (4.c3 d5 -> 5.exd5 Qxd5 -> 6.d4)
    cur.execute("INSERT INTO moves VALUES (13, 7, 14, 'c2c3', 'c3', 80.0)")
    cur.execute("INSERT INTO moves VALUES (14, 14, 15, 'd7d5', 'd5', 80.0)")
    cur.execute("INSERT INTO moves VALUES (15, 15, 16, 'e4d5', 'exd5', 80.0)")
    cur.execute("INSERT INTO moves VALUES (16, 16, 17, 'd8d5', 'Qxd5', 80.0)")
    cur.execute("INSERT INTO moves VALUES (17, 17, 18, 'd2d4', 'd4', 80.0)")

    for m_id in range(1, 18):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (m_id, m_id))
    conn.commit()

    html = flatten_subtree(
        conn=conn,
        start_pos_id=7,
        start_move_num=4,
        is_white_turn=True,
        color='b',
        level=1,
        language="de",
        chap_idx=1,
        chap_title="Ruy Lopez"
    )
    conn.close()

    # Sideline A: next move (5...Qf6) has drawings.
    # Therefore, 4...dxc6 must NOT have a diagram (no duplicate diagram before 5...Qf6)
    assert "Stellung nach 4...dxc6" not in html
    assert "Stellung nach 5...Df6" in html or "Stellung nach 5...Qf6" in html

    # Sideline B: next move (5...Qxd5) has NO drawings and is NOT leaf.
    # Therefore, 4...d5 MUST have the starting diagram!
    assert "Stellung nach 4...d5" in html

