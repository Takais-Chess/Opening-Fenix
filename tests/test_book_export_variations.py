import os
import sqlite3
import pytest

from opening_fenix.core.services.book_export_service import (
    discover_chapters,
    flatten_subtree,
    generate_variation_index,
    build_book_html,
    export_repertoire_book
)


@pytest.fixture
def var_hierarchy_db(tmp_path):
    """Creates a database with deep variation hierarchy (variation_1, variation_2, variation_3)."""
    db_path = str(tmp_path / "var_test.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Deep Variation Test')")
    cur.execute("INSERT INTO metadata VALUES ('color', 'b')")

    cur.execute("CREATE TABLE repertoire_levels (id INTEGER PRIMARY KEY, name VARCHAR, `order` INTEGER, target_elo INTEGER)")
    cur.execute("INSERT INTO repertoire_levels VALUES (1, 'Level 1', 1, 1500)")

    cur.execute("""
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY,
            fen VARCHAR,
            comment VARCHAR,
            variation_1 VARCHAR,
            variation_2 VARCHAR,
            variation_3 VARCHAR
        )
    """)
    cur.execute("""
        CREATE TABLE moves (
            id INTEGER PRIMARY KEY,
            from_position_id INTEGER,
            to_position_id INTEGER,
            uci VARCHAR,
            san VARCHAR,
            priority_score FLOAT
        )
    """)
    cur.execute("""
        CREATE TABLE repertoire_moves (
            id INTEGER PRIMARY KEY,
            move_id INTEGER,
            level INTEGER,
            is_active BOOLEAN
        )
    """)

    # 1. Ausgangsstellung
    cur.execute("INSERT INTO positions VALUES (1, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -', '', '', '', '')")
    # 2. 1.e4
    cur.execute("INSERT INTO positions VALUES (2, 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -', '', '', '', '')")
    # 3. 1...e5
    cur.execute("INSERT INTO positions VALUES (3, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -', '', '', '', '')")
    # 4. 2.Nf3
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -', '', '', '', '')")
    # 5. 2...Nc6
    cur.execute("INSERT INTO positions VALUES (5, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -', '', '', '', '')")
    # 6. 3.Bb5 (Ruy Lopez - raw variation_1)
    cur.execute("INSERT INTO positions VALUES (6, 'r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', 'Ruy Lopez', '', '')")
    # 7. 3...a6
    cur.execute("INSERT INTO positions VALUES (7, 'r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', '', '', '', '')")
    # 8. 4.Bxc6 (Exchange Spanish - variation_2)
    cur.execute("INSERT INTO positions VALUES (8, 'r1bqkbnr/1ppp1ppp/p1B5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', '', 'Exchange Spanish', '')")
    # 9. 4...dxc6
    cur.execute("INSERT INTO positions VALUES (9, 'r1bqkbnr/1pp2ppp/p1p5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', 'Das Läuferpaar aufgegeben', '', '', '')")
    # 10. 4.Ba4 (Mainline Berlin/Morphy - variation_2 & variation_3)
    cur.execute("INSERT INTO positions VALUES (10, 'r1bqkbnr/1ppp1ppp/p1n5/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', '', 'Morphy Defense', 'Columbus Variation')")

    # Moves
    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'g1f3', 'Nf3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'b8c6', 'Nc6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (5, 5, 6, 'f1b5', 'Bb5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (6, 6, 7, 'a7a6', 'a6', 100.0)")
    # Main: 4.Ba4 (pos 10)
    cur.execute("INSERT INTO moves VALUES (7, 7, 10, 'b5a4', 'Ba4', 100.0)")
    # Sideline: 4.Bxc6 (pos 8) -> 4...dxc6 (pos 9)
    cur.execute("INSERT INTO moves VALUES (8, 7, 8, 'b5c6', 'Bxc6', 90.0)")
    cur.execute("INSERT INTO moves VALUES (9, 8, 9, 'd7c6', 'dxc6', 90.0)")

    for m_id in range(1, 10):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (m_id, m_id))

    conn.commit()
    conn.close()
    return db_path


def test_no_translation_and_deep_variation_names(var_hierarchy_db, tmp_path):
    conn = sqlite3.connect(var_hierarchy_db)

    # 1. Discover Chapters: Should NOT translate "Ruy Lopez" to German "Spanische Partie"
    chapters = discover_chapters(conn, color='b', level=1, language='de')
    assert len(chapters) == 1
    assert chapters[0]["title"] == "Ruy Lopez"  # NOT "Spanische Partie (Ruy Lopez)"
    assert "Exchange Spanish" in chapters[0]["subvars"]
    assert "Morphy Defense" in chapters[0]["subvars"] or "Columbus Variation" in chapters[0]["subvars"]

    # 2. Flatten subtree:
    # Sideline heading should contain "Exchange Spanish":
    content_html = flatten_subtree(
        conn=conn,
        start_pos_id=chapters[0]["start_pos_id"],
        start_move_num=chapters[0]["start_move_num"],
        is_white_turn=chapters[0]["is_white_turn"],
        color='b',
        level=1,
        language="de",
        chap_idx=1,
        chap_title=chapters[0]["title"],
        chap_prefix=chapters[0]["san_prefix"]
    )

    # Sideline Option 1 heading should include the variation name!
    assert "Exchange Spanish" in content_html
    assert "variation-name" in content_html

    # Main line should contain Morphy Defense / Columbus Variation
    assert "Morphy Defense" in content_html or "Columbus Variation" in content_html
    assert "mainline-variation-heading" in content_html

    # 3. Varianten-Index: Should include variation names
    var_index_html, var_count = generate_variation_index(
        conn=conn,
        chapters=chapters,
        color='b',
        level=1,
        language="de"
    )
    assert "Exchange Spanish" in var_index_html
    assert "index-varname" in var_index_html

    # 4. Full Book HTML: Table of contents must list the subvariations
    metadata = {"name": "Deep Variation Test", "color": "b"}
    full_html = build_book_html(
        metadata,
        chapters,
        language="de",
        variation_index_html=var_index_html,
        variation_count=var_count
    )
    assert "toc-subvar-row" in full_html
    assert "Exchange Spanish" in full_html
    conn.close()


def test_multilingual_json_variation_names(tmp_path):
    """Verifies that JSON multilingual variation strings are resolved according to chosen language."""
    db_path = str(tmp_path / "multilingual_test.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Multilingual Book')")
    cur.execute("INSERT INTO metadata VALUES ('color', 'b')")

    cur.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, fen VARCHAR, comment VARCHAR, variation_1 VARCHAR, variation_2 VARCHAR, variation_3 VARCHAR)")
    cur.execute("CREATE TABLE moves (id INTEGER PRIMARY KEY, from_position_id INTEGER, to_position_id INTEGER, uci VARCHAR, san VARCHAR, priority_score FLOAT)")
    cur.execute("CREATE TABLE repertoire_moves (id INTEGER PRIMARY KEY, move_id INTEGER, level INTEGER, is_active BOOLEAN)")

    # 1. Start -> 2. 1.e4 -> 3. 1...e5 -> 4. 2.Nf3 -> 5. 2...Nc6 -> 6. 3.Bb5 (multilingual variation_1)
    cur.execute("INSERT INTO positions VALUES (1, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (2, 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (3, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (5, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (6, 'r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', '{\"en\": \"Ruy Lopez\", \"de\": \"Spanisch\"}', '', '')")
    cur.execute("INSERT INTO positions VALUES (7, 'r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', '', '', '', '')")
    cur.execute("INSERT INTO positions VALUES (8, 'r1bqkbnr/1ppp1ppp/p1B5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', '', '', '{\"en\": \"Exchange Variation\", \"de\": \"Abtausch-Spanisch\"}', '')")

    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'g1f3', 'Nf3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'b8c6', 'Nc6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (5, 5, 6, 'f1b5', 'Bb5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (6, 6, 7, 'a7a6', 'a6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (7, 7, 8, 'b5c6', 'Bxc6', 90.0)")

    for m_id in range(1, 8):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (m_id, m_id))

    conn.commit()

    # German export test
    chapters_de = discover_chapters(conn, color='b', language='de')
    assert len(chapters_de) == 1
    assert chapters_de[0]["title"] == "Spanisch"
    assert "Abtausch-Spanisch" in chapters_de[0]["subvars"]

    var_idx_de, _ = generate_variation_index(conn, chapters=chapters_de, color='b', language='de')
    assert "Abtausch-Spanisch" in var_idx_de
    assert "Exchange Variation" not in var_idx_de
    assert '{"en":' not in var_idx_de

    html_de = build_book_html({"name": "Test", "color": "b"}, chapters_de, language="de", variation_index_html=var_idx_de)
    assert "Spanisch" in html_de
    assert "Abtausch-Spanisch" in html_de
    assert '{"en": "Ruy Lopez"' not in html_de

    # English export test
    chapters_en = discover_chapters(conn, color='b', language='en')
    assert len(chapters_en) == 1
    assert chapters_en[0]["title"] == "Ruy Lopez"
    assert "Exchange Variation" in chapters_en[0]["subvars"]

    var_idx_en, _ = generate_variation_index(conn, chapters=chapters_en, color='b', language='en')
    assert "Exchange Variation" in var_idx_en
    assert "Abtausch-Spanisch" not in var_idx_en
    assert '{"en":' not in var_idx_en

    html_en = build_book_html({"name": "Test", "color": "b"}, chapters_en, language="en", variation_index_html=var_idx_en)
    assert "Ruy Lopez" in html_en
    assert "Exchange Variation" in html_en
    assert '{"en": "Ruy Lopez"' not in html_en

    conn.close()

