import pytest
import json
import os
import sqlite3
import datetime
import urllib.parse
from unittest.mock import MagicMock, patch
from opening_fenix.core.services.lichess_service import (
    run_lichess_import,
    compute_position_grandparents,
    sync_lichess_data_from_other_repertoires
)
from opening_fenix.core.db.models import Position, Move, LichessData, Base
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir


def test_schema_migration_adds_fetched_at(tmp_path):
    """Verify that opening an older DB without fetched_at automatically migrates it."""
    db_file = str(tmp_path / "legacy_repo.db")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    # Create legacy schema without fetched_at
    cursor.execute("""
        CREATE TABLE lichess_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fen TEXT NOT NULL,
            elo_range TEXT NOT NULL,
            moves_json TEXT NOT NULL
        )
    """)
    cursor.execute("INSERT INTO lichess_data (fen, elo_range, moves_json) VALUES ('fen1', 'high', '{}')")
    conn.commit()
    conn.close()

    # Now open with DatabaseManager, which calls _migrate_schema
    db = DatabaseManager(db_file)
    session = db.get_session()
    
    # Check that fetched_at column was created
    with db.engine.connect() as check_conn:
        from sqlalchemy import text
        res = check_conn.execute(text("PRAGMA table_info(lichess_data)"))
        cols = [r[1] for r in res.fetchall()]
        assert "fetched_at" in cols
        
    # Verify existing data is preserved
    row = session.query(LichessData).filter_by(fen='fen1').first()
    assert row is not None
    assert row.elo_range == 'high'
    session.close()
    db.close()


def test_compute_position_grandparents_simple_and_transposition(mock_user_dir, sample_repertoire):
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # Create a 4-ply line: P0 -> P1 -> P2 -> P3
    p0 = Position(fen="root_fen")
    p1 = Position(fen="p1_fen")
    p2 = Position(fen="p2_fen")
    p3 = Position(fen="p3_fen")
    # Transposition parent: P1_alt -> P2_alt -> P3
    p1_alt = Position(fen="p1_alt_fen")
    p2_alt = Position(fen="p2_alt_fen")

    session.add_all([p0, p1, p2, p3, p1_alt, p2_alt])
    session.commit()

    # Moves for line 1
    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e7e5", san="e5")
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="g1f3", san="Nf3")

    # Moves for line 2 (transposing into p3)
    m1_alt = Move(from_position_id=p0.id, to_position_id=p1_alt.id, uci="g1f3", san="Nf3")
    m2_alt = Move(from_position_id=p1_alt.id, to_position_id=p2_alt.id, uci="e7e5", san="e5")
    m3_alt = Move(from_position_id=p2_alt.id, to_position_id=p3.id, uci="e2e4", san="e4")

    session.add_all([m1, m2, m3, m1_alt, m2_alt, m3_alt])
    session.commit()

    gps, id_to_fen = compute_position_grandparents(session)

    # Root p0 has no grandparents
    assert p0.id not in gps
    # p1 has no grandparents
    assert p1.id not in gps
    # p2's grandparent is p0
    assert gps.get(p2.id) == {p0.id}
    # p3 has TWO grandparents due to transposition: p1 and p1_alt!
    assert gps.get(p3.id) == {p1.id, p1_alt.id}

    session.close()
    db.close()


def test_grandparent_skip_in_run_lichess_import(mock_user_dir, sample_repertoire):
    """
    Tests that a position whose ALL grandparents have 0 games is skipped
    without making network requests, and saved with moves_json = '{}'.
    Also tests that if ONE grandparent has games (transposition), it is NOT skipped.
    """
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # Clear any previous sample data
    session.query(Move).delete()
    session.query(Position).delete()
    session.query(LichessData).delete()
    session.commit()

    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    p0 = Position(fen=start_fen)
    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    p2 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    p3 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2")
    p4 = Position(fen="r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")

    session.add_all([p0, p1, p2, p3, p4])
    session.commit()

    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e7e5", san="e5")
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="g1f3", san="Nf3")
    m4 = Move(from_position_id=p3.id, to_position_id=p4.id, uci="b8c6", san="Nc6")
    session.add_all([m1, m2, m3, m4])
    session.commit()

    # Pre-populate Lichess data:
    # p0 has 1,000,000 games
    # p1 has 500,000 games
    # p2 has 0 games! (Grandparent of p4 is p2!)
    ld0 = LichessData(fen=p0.fen, elo_range="high", moves_json=json.dumps({"e2e4": {"total": 1000000}}))
    ld1 = LichessData(fen=p1.fen, elo_range="high", moves_json=json.dumps({"e7e5": {"total": 500000}}))
    ld2 = LichessData(fen=p2.fen, elo_range="high", moves_json=json.dumps({})) # 0 games!
    session.add_all([ld0, ld1, ld2])
    session.commit()

    session.close()
    db.close()

    # Track URLs requested
    network_requests = []

    def mock_get(url, headers):
        network_requests.append(url)
        return json.dumps({
            "moves": [{"uci": "b8c6", "white": 10, "draws": 5, "black": 2}]
        }).encode("utf-8")

    with patch("time.sleep"), \
         patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get):

        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True

    # Check results in DB
    db = DatabaseManager(db_path)
    session = db.get_session()

    ld3 = session.query(LichessData).filter_by(fen=p3.fen, elo_range="high").first()
    ld4 = session.query(LichessData).filter_by(fen=p4.fen, elo_range="high").first()

    # p3 was queried over network (its grandparent is p1 which has 500,000 games)
    assert ld3 is not None
    assert any(p3.fen in urllib.parse.unquote_plus(req) for req in network_requests)

    # p4 has grandparent p2, which has 0 games!
    # Therefore p4 MUST BE SKIPPED without network request!
    assert ld4 is not None
    assert ld4.moves_json == "{}"
    # Verify NO network request was made for p4!
    assert not any(p4.fen in urllib.parse.unquote_plus(req) for req in network_requests)

    session.close()
    db.close()


def test_sync_lichess_data_from_other_repertoires_with_date_filter(mock_user_dir):
    """
    Tests cross-course data synchronization:
    - Repertoire A needs data for fen_shared.
    - Repertoire B has fen_shared (fetched 10 days ago).
    - Repertoire C has fen_old (fetched 300 days ago).
    - Syncing with max_age_days=180 should import fen_shared, but ignore fen_old.
    """
    for rname in ["RepoA", "RepoB", "RepoC"]:
        r_dir = get_repertoire_dir(rname)
        os.makedirs(r_dir, exist_ok=True)

    dbA_path = get_repertoire_db_path("RepoA")
    dbB_path = get_repertoire_db_path("RepoB")
    dbC_path = get_repertoire_db_path("RepoC")

    # Target RepoA has positions fen_shared and fen_old
    dbA = DatabaseManager(dbA_path)
    sA = dbA.get_session()
    sA.add(Position(fen="fen_shared"))
    sA.add(Position(fen="fen_old"))
    sA.commit()

    # Source RepoB has fen_shared with recent date (10 days ago)
    recent_date = datetime.datetime.now() - datetime.timedelta(days=10)
    dbB = DatabaseManager(dbB_path)
    sB = dbB.get_session()
    sB.add(LichessData(
        fen="fen_shared",
        elo_range="high",
        moves_json=json.dumps({"e2e4": {"total": 500}}),
        fetched_at=recent_date
    ))
    sB.commit()
    sB.close()
    dbB.close()

    # Source RepoC has fen_old with old date (300 days ago)
    old_date = datetime.datetime.now() - datetime.timedelta(days=300)
    dbC = DatabaseManager(dbC_path)
    sC = dbC.get_session()
    sC.add(LichessData(
        fen="fen_old",
        elo_range="high",
        moves_json=json.dumps({"d2d4": {"total": 200}}),
        fetched_at=old_date
    ))
    sC.commit()
    sC.close()
    dbC.close()

    # Now run sync for RepoA with max_age_days = 180
    copied = sync_lichess_data_from_other_repertoires(
        target_session=sA,
        current_repo_name="RepoA",
        elo_category="high",
        max_age_days=180
    )

    assert copied == 1
    # fen_shared should now be in RepoA
    item_shared = sA.query(LichessData).filter_by(fen="fen_shared", elo_range="high").first()
    assert item_shared is not None
    assert "e2e4" in item_shared.moves_json

    # fen_old should NOT be in RepoA because it's 300 days old (> 180 days)
    item_old = sA.query(LichessData).filter_by(fen="fen_old", elo_range="high").first()
    assert item_old is None

    sA.close()
    dbA.close()
