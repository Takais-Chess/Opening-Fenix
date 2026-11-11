import os
import pytest
import sqlite3
import chess

from opening_fenix.core.services.book_export_service import (
    discover_chapters,
    render_board_svg,
    export_repertoire_book,
    find_headless_browser
)
from opening_fenix.gui.dialogs.export_dialog import ExportDialog


@pytest.fixture
def sample_repo_db(tmp_path):
    """Creates a minimal SQLite repertoire database for testing book export."""
    db_path = str(tmp_path / "test_book_repo.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Test Repertoire')")
    cur.execute("INSERT INTO metadata VALUES ('color', 'b')")

    cur.execute("CREATE TABLE repertoire_levels (id INTEGER PRIMARY KEY, name VARCHAR, `order` INTEGER, target_elo INTEGER)")
    cur.execute("INSERT INTO repertoire_levels VALUES (1, 'Grundlagen', 1, 1500)")

    cur.execute("""
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY,
            fen VARCHAR,
            comment VARCHAR,
            variation_1 VARCHAR
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

    # 1. Root: starting position
    cur.execute("INSERT INTO positions VALUES (1, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -', '', '')")
    # 2. 1.e4
    cur.execute("INSERT INTO positions VALUES (2, 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -', '', '')")
    # 3. 1...e5
    cur.execute("INSERT INTO positions VALUES (3, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -', 'Zentrum besetzen', '')")
    # 4. 2.Nf3
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -', '', '')")
    # 5. 2...Nc6
    cur.execute("INSERT INTO positions VALUES (5, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -', '', '')")
    # 6. 3.Bb5 (Ruy Lopez)
    cur.execute("INSERT INTO positions VALUES (6, 'r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', 'Spanische Partie', 'Ruy Lopez')")

    # Moves
    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'g1f3', 'Nf3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'b8c6', 'Nc6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (5, 5, 6, 'f1b5', 'Bb5', 100.0)")

    for m_id in range(1, 6):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (m_id, m_id))

    conn.commit()
    conn.close()
    return db_path


def test_render_board_svg():
    fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -"
    anno = {
        "arrows": [(chess.E7, chess.E5, "green")],
        "highlights": [(chess.B5, "red")]
    }
    svg = render_board_svg(fen, anno, color='b', caption="Test Diagram", size=180)
    assert "<svg" in svg
    assert "Test Diagram" in svg
    # Ink saver white margin should be used
    assert "#ffffff" in svg


def test_export_repertoire_book_html(sample_repo_db, tmp_path):
    out_html = str(tmp_path / "book.html")
    res = export_repertoire_book(
        db_path=sample_repo_db,
        output_path=out_html,
        output_format="html",
        level=1,
        language="de"
    )
    assert os.path.isfile(res)
    assert os.path.getsize(res) > 0
    with open(res, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Test Repertoire" in html
    assert "Inhaltsverzeichnis" in html
    assert "two-columns" in html


def test_export_dialog_book_option(qtbot, complex_backend):
    dialog = ExportDialog(complex_backend)
    qtbot.addWidget(dialog)
    dialog.show()

    # Initial state: PGN selected
    assert dialog.r_pgn.isChecked()
    assert not dialog.g_opt.isHidden()
    assert dialog.g_book_opt.isHidden()

    # Select Book format
    dialog.r_book.setChecked(True)
    assert not dialog.g_book_opt.isHidden()
    assert dialog.g_opt.isHidden()
    assert dialog.g_scope.isHidden()

    # Trigger accept
    dialog.on_accept()
    assert dialog.result_data is not None
    fmt, scope, transpos, max_l, lang, extra = dialog.result_data
    assert fmt == "book"
    assert "book_format" in extra


def test_transposition_detection_and_cutting(tmp_path):
    db_path = str(tmp_path / "transpos_repo.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    cur.execute("INSERT INTO metadata VALUES ('name', 'Transposition Test')")
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
    # Path A: 2.Nf3 (pos 4) -> 2...Nc6 (pos 5) -> 3.Bc4 (pos 8) -> 3...Bc5 (pos 9)
    cur.execute("INSERT INTO positions VALUES (4, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -', '', 'Nf3')")
    cur.execute("INSERT INTO positions VALUES (5, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (8, 'r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq -', 'Italienische Partie Tabia', '3.Bc4')")
    cur.execute("INSERT INTO positions VALUES (9, 'r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq -', 'Schwarzer Laeufer entwickelt', '')")
    # Path B: 2.Nc3 (pos 6) -> 2...Nc6 (pos 7) -> 3.Nf3 (pos 10) -> 3...Nf6 (pos 11) -> 4.Bc4 (transposes to pos 8!)
    cur.execute("INSERT INTO positions VALUES (6, 'rnbqkbnr/pppp1ppp/8/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq -', '', 'The Vienna')")
    cur.execute("INSERT INTO positions VALUES (7, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (10, 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R b KQkq -', '', '')")
    cur.execute("INSERT INTO positions VALUES (11, 'r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq -', '', '')")

    cur.execute("INSERT INTO moves VALUES (1, 1, 2, 'e2e4', 'e4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (2, 2, 3, 'e7e5', 'e5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (3, 3, 4, 'g1f3', 'Nf3', 100.0)")
    cur.execute("INSERT INTO moves VALUES (4, 4, 5, 'b8c6', 'Nc6', 100.0)")
    cur.execute("INSERT INTO moves VALUES (5, 5, 8, 'f1c4', 'Bc4', 100.0)")
    cur.execute("INSERT INTO moves VALUES (6, 8, 9, 'f8c5', 'Bc5', 100.0)")
    cur.execute("INSERT INTO moves VALUES (7, 3, 6, 'b1c3', 'Nc3', 90.0)")
    cur.execute("INSERT INTO moves VALUES (8, 6, 7, 'b8c6', 'Nc6', 90.0)")
    cur.execute("INSERT INTO moves VALUES (9, 7, 5, 'g1f3', 'Nf3', 90.0)") # Transposes to pos 5!

    for i in range(1, 10):
        cur.execute("INSERT INTO repertoire_moves VALUES (?, ?, 1, 1)", (i, i))
    conn.commit()
    conn.close()

    out_html = str(tmp_path / "transpos_book.html")
    res = export_repertoire_book(
        db_path=db_path,
        output_path=out_html,
        output_format="html",
        level=1,
        language="de"
    )
    assert os.path.isfile(res)
    with open(res, "r", encoding="utf-8") as f:
        html = f.read()

    # Transposition note should be present
    assert "transposition-note" in html
    assert "Zugumstellung" in html

    # The comment on pos 9 ('Schwarzer Laeufer entwickelt') should appear exactly once in the book, not duplicated!
    assert html.count("Schwarzer Laeufer entwickelt") == 1

    # Varianten-Index should be present at the end
    assert 'id="variation-index"' in html
    assert 'href="#variation-index"' in html
    assert "index-row" in html
    assert "index-dots" in html


def test_export_repertoire_book_locked_file(sample_repo_db, tmp_path):
    out_pdf = str(tmp_path / "locked_book.pdf")
    with open(out_pdf, "w") as f:
        f.write("existing")

    import sys
    if sys.platform == "win32":
        import ctypes
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        OPEN_EXISTING = 3
        handle = ctypes.windll.kernel32.CreateFileW(out_pdf, GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, 0, None)
        try:
            with pytest.raises(RuntimeError, match="schreibgeschützt"):
                export_repertoire_book(
                    db_path=sample_repo_db,
                    output_path=out_pdf,
                    output_format="pdf",
                    level=1,
                    language="de"
                )
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        os.chmod(out_pdf, 0o444)
        try:
            with pytest.raises(RuntimeError, match="schreibgeschützt"):
                export_repertoire_book(
                    db_path=sample_repo_db,
                    output_path=out_pdf,
                    output_format="pdf",
                    level=1,
                    language="de"
                )
        finally:
            os.chmod(out_pdf, 0o666)


def test_export_repertoire_book_with_apostrophe_in_path(sample_repo_db, tmp_path):
    sub = tmp_path / "Gawain's 1.e4 e5"
    sub.mkdir(parents=True, exist_ok=True)
    out_pdf = str(sub / "Gawain's 1.e4 e5 - Lehrbuch.pdf")

    final_path = export_repertoire_book(
        db_path=sample_repo_db,
        output_path=out_pdf,
        output_format="pdf",
        level=1,
        language="de"
    )
    assert os.path.isfile(final_path)
    assert os.path.getsize(final_path) > 0
    assert "Gawain's" in final_path
