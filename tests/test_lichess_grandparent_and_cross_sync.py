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


def test_parent_protection_and_three_move_skip_in_run_lichess_import(mock_user_dir, sample_repertoire):
    """
    Tests that:
    1. A position whose incoming move has games is NEVER skipped, even if earlier moves had 0 games.
    2. A position whose lead-up has 3 consecutive evaluated 0-game moves IS skipped without network request.
    3. Self-healing automatically purges stale empty records if their parent move has >0 games.
    """
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # Clear any previous sample data
    session.query(Move).delete()
    session.query(Position).delete()
    session.query(LichessData).delete()
    session.commit()

    # Line 1: Normal line where p3 -> p4 has games (m4)
    # p0 -> (e4) -> p1 -> (e5) -> p2 -> (Nf3) -> p3 -> (Nc6) -> p4
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    p0 = Position(fen=start_fen)
    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    p2 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    p3 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2")
    p4 = Position(fen="r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")

    # Line 2: 3-move 0-game sideline branching off p1:
    # p1 -> (a7a6, 0 games) -> p_rare1 -> (h2h4, 0 games) -> p_rare2 -> (b7b6, 0 games) -> p_rare3 (should be skipped!)
    p_rare1 = Position(fen="rnbqkbnr/1ppppppp/p7/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    p_rare2 = Position(fen="rnbqkbnr/1ppppppp/p7/8/4P2P/8/PPPP1PP1/RNBQKBNR b KQkq - 0 2")
    p_rare3 = Position(fen="rnbqkbnr/2pppppp/pp6/8/4P2P/8/PPPP1PP1/RNBQKBNR w KQkq - 0 3")

    session.add_all([p0, p1, p2, p3, p4, p_rare1, p_rare2, p_rare3])
    session.commit()

    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e7e5", san="e5")
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="g1f3", san="Nf3")
    m4 = Move(from_position_id=p3.id, to_position_id=p4.id, uci="b8c6", san="Nc6")

    # Sideline moves
    mr1 = Move(from_position_id=p1.id, to_position_id=p_rare1.id, uci="a7a6", san="a6")
    mr2 = Move(from_position_id=p_rare1.id, to_position_id=p_rare2.id, uci="h2h4", san="h4")
    mr3 = Move(from_position_id=p_rare2.id, to_position_id=p_rare3.id, uci="b7b6", san="b6")

    session.add_all([m1, m2, m3, m4, mr1, mr2, mr3])
    session.commit()

    # Pre-populate Lichess data:
    # p0 has 1,000,000 games
    # p1 has e7e5 (500,000 games) and a7a6 is NOT played (0 games)
    ld0 = LichessData(fen=p0.fen, elo_range="high", moves_json=json.dumps({"e2e4": {"total": 1000000}}))
    ld1 = LichessData(fen=p1.fen, elo_range="high", moves_json=json.dumps({"e7e5": {"total": 500000}}))
    # p_rare1 and p_rare2 both evaluated with 0 games
    ld_r1 = LichessData(fen=p_rare1.fen, elo_range="high", moves_json=json.dumps({}))
    ld_r2 = LichessData(fen=p_rare2.fen, elo_range="high", moves_json=json.dumps({}))
    # p3 has 17 games for b8c6 (move m4 into p4)
    ld3 = LichessData(fen=p3.fen, elo_range="high", moves_json=json.dumps({"b8c6": {"total": 17}}))

    # Stale empty data for p4 to test self-healing!
    # Even though p4 has an empty record, p3's move m4 has 17 games,
    # so self-healing should purge this stale record and fetch real data for p4.
    ld4_stale = LichessData(fen=p4.fen, elo_range="high", moves_json=json.dumps({}))

    session.add_all([ld0, ld1, ld_r1, ld_r2, ld3, ld4_stale])
    session.commit()

    session.close()
    db.close()

    network_requests = []

    def mock_get(url, headers):
        network_requests.append(url)
        # Mock returns moves from p4 (e.g. f1c4)
        return json.dumps({
            "moves": [{"uci": "f1c4", "white": 10, "draws": 5, "black": 2}]
        }).encode("utf-8")

    with patch("time.sleep"), \
         patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get):

        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True

    # Check results in DB
    db = DatabaseManager(db_path)
    session = db.get_session()

    ld4 = session.query(LichessData).filter_by(fen=p4.fen, elo_range="high").first()
    ld_r3 = session.query(LichessData).filter_by(fen=p_rare3.fen, elo_range="high").first()

    # 1. Self-healing & Parent Protection: p4's incoming move m4 had 17 games!
    # Self-healing purged ld4_stale, and p4 was queried over network.
    assert ld4 is not None
    assert "f1c4" in ld4.moves_json
    assert any(p4.fen in urllib.parse.unquote_plus(req) for req in network_requests)

    # 2. 3-Move Lead-Up Skip: p_rare3 has 3 consecutive 0-game moves (mr1, mr2, mr3).
    # Therefore p_rare3 MUST BE SKIPPED without making any network request!
    assert ld_r3 is not None
    assert ld_r3.moves_json == "{}"
    assert not any(p_rare3.fen in urllib.parse.unquote_plus(req) for req in network_requests)

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


def test_exact_bug_and_self_healing_scenario(mock_user_dir, sample_repertoire):
    """
    Directly reproduces the user's reported bug:
    Grandparent (Pos 11846) has 0 games.
    Parent (Pos 11847) has 9 games for move Qe7.
    Child (Pos 11848) was previously marked as {} by the old bug.
    Verifies that running run_lichess_import heals Pos 11848 and queries Lichess.
    """
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    session.query(Move).delete()
    session.query(Position).delete()
    session.query(LichessData).delete()
    session.commit()

    # Grandparent -> Parent -> Child
    gp_fen = "r1bqkb1r/pppp1ppp/2n5/4p3/2B2P2/2P5/PPP3PP/R1BQK1NR w KQkq -"
    parent_fen = "r1bqkb1r/pppp1ppp/2n5/4p3/2B2P2/2P2N2/PPP3PP/R1BQK2R b KQkq -"
    child_fen = "r1b1kb1r/ppppqppp/2n5/4p3/2B2P2/2P2N2/PPP3PP/R1BQK2R w KQkq -"

    p_gp = Position(fen=gp_fen)
    p_parent = Position(fen=parent_fen)
    p_child = Position(fen=child_fen)

    session.add_all([p_gp, p_parent, p_child])
    session.commit()

    m_gp = Move(from_position_id=p_gp.id, to_position_id=p_parent.id, uci="g1f3", san="Nf3")
    m_parent = Move(from_position_id=p_parent.id, to_position_id=p_child.id, uci="d8e7", san="Qe7")
    session.add_all([m_gp, m_parent])
    session.commit()

    # Grandparent had 0 games
    ld_gp = LichessData(fen=p_gp.fen, elo_range="high", moves_json=json.dumps({}))
    # Parent had 9 games for Qe7!
    ld_parent = LichessData(fen=p_parent.fen, elo_range="high", moves_json=json.dumps({
        "d8e7": {"white": 0, "draws": 1, "black": 8, "total": 9}
    }))
    # Child was falsely saved with {} by old bug
    ld_child_stale = LichessData(fen=p_child.fen, elo_range="high", moves_json=json.dumps({}))

    session.add_all([ld_gp, ld_parent, ld_child_stale])
    session.commit()
    session.close()
    db.close()

    network_requests = []

    def mock_get(url, headers):
        network_requests.append(url)
        return json.dumps({
            "moves": [
                {"uci": "d1e2", "white": 0, "draws": 0, "black": 4},
                {"uci": "f4e5", "white": 0, "draws": 0, "black": 2}
            ]
        }).encode("utf-8")

    with patch("time.sleep"), \
         patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get):

        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True

    # Verify that child_fen was queried and updated!
    db = DatabaseManager(db_path)
    session = db.get_session()
    ld_child = session.query(LichessData).filter_by(fen=p_child.fen, elo_range="high").first()

    assert ld_child is not None
    assert ld_child.moves_json != "{}"
    assert "d1e2" in ld_child.moves_json
    assert any(p_child.fen in urllib.parse.unquote_plus(req) for req in network_requests)

    session.close()
    db.close()


def test_cascading_multi_ply_self_healing(mock_user_dir, sample_repertoire):
    """
    Verifies that when an entire variation (p1 -> p2 -> p3) was falsely saved as {}
    by the old bug, a SINGLE run_lichess_import run dynamically unblocks and queries
    all chained positions as moves with >0 games are discovered.
    """
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    session.query(Move).delete()
    session.query(Position).delete()
    session.query(LichessData).delete()
    session.commit()

    # Chain: p0 (root) -> p1 -> p2 -> p3
    f0 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3" # 1.e4
    f1 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6" # 1...e5
    f2 = "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq f3" # 2.f4
    f3 = "rnbqkbnr/pppp1ppp/8/8/4Pp2/8/PPPP2PP/RNBQKBNR w KQkq -" # 2...exf4

    p0 = Position(fen=f0)
    p1 = Position(fen=f1)
    p2 = Position(fen=f2)
    p3 = Position(fen=f3)
    session.add_all([p0, p1, p2, p3])
    session.commit()

    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e7e5", san="e5")
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="f2f4", san="f4")
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="e5f4", san="exf4")
    session.add_all([m1, m2, m3])
    session.commit()

    # Root p0 has games for e7e5 (50 games)
    ld0 = LichessData(fen=p0.fen, elo_range="high", moves_json=json.dumps({
        "e7e5": {"white": 20, "draws": 10, "black": 20, "total": 50}
    }))
    # All downstream positions p1, p2, p3 were falsely saved with {} by earlier bug
    ld1_stale = LichessData(fen=p1.fen, elo_range="high", moves_json=json.dumps({}))
    ld2_stale = LichessData(fen=p2.fen, elo_range="high", moves_json=json.dumps({}))
    ld3_stale = LichessData(fen=p3.fen, elo_range="high", moves_json=json.dumps({}))

    session.add_all([ld0, ld1_stale, ld2_stale, ld3_stale])
    session.commit()
    session.close()
    db.close()

    network_requests = []

    def mock_get(url, headers):
        unquoted = urllib.parse.unquote_plus(url)
        network_requests.append(unquoted)
        if f1 in unquoted:
            return json.dumps({
                "moves": [{"uci": "f2f4", "white": 10, "draws": 5, "black": 5}]
            }).encode("utf-8")
        elif f2 in unquoted:
            return json.dumps({
                "moves": [{"uci": "e5f4", "white": 8, "draws": 2, "black": 10}]
            }).encode("utf-8")
        elif f3 in unquoted:
            return json.dumps({
                "moves": [{"uci": "g1f3", "white": 12, "draws": 4, "black": 4}]
            }).encode("utf-8")
        return json.dumps({"moves": []}).encode("utf-8")

    with patch("time.sleep"), \
         patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get):

        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True

    # Verify that in a SINGLE run, ALL THREE positions p1, p2, p3 were queried and populated!
    db = DatabaseManager(db_path)
    session = db.get_session()

    res1 = session.query(LichessData).filter_by(fen=p1.fen, elo_range="high").first()
    res2 = session.query(LichessData).filter_by(fen=p2.fen, elo_range="high").first()
    res3 = session.query(LichessData).filter_by(fen=p3.fen, elo_range="high").first()

    assert res1 is not None and "f2f4" in res1.moves_json
    assert res2 is not None and "e5f4" in res2.moves_json
    assert res3 is not None and "g1f3" in res3.moves_json

    # All three must have been requested over network
    assert any(f1 in r for r in network_requests)
    assert any(f2 in r for r in network_requests)
    assert any(f3 in r for r in network_requests)

    session.close()
    db.close()


def test_lichess_import_idempotent_restart_no_false_purges(mock_user_dir, sample_repertoire):
    """
    Regression test for the issue where restarting a completed Lichess import
    falsely purged valid 0-game positions on every restart.
    Verifies that restarting an import after completion makes 0 network requests
    and immediately reports that all positions are up to date.
    """
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    session.query(Move).delete()
    session.query(Position).delete()
    session.query(LichessData).delete()
    session.commit()

    # 1.e4 c5 2.a3 b6 3.h4 4.c5
    # p0: 1000 games
    # p1: 500 games
    # p2: 10 games for 2.a3
    # p3: 10 games on Lichess (moves: b8c6, e7e6), but b7b6 was never played (0 games)
    # p4: 0 games on Lichess
    # p5: 0 games on Lichess
    # p6: 3 consecutive 0-game moves lead-up -> skipped under 3-ply rule!
    fens = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "rnbqkbnr/pp1ppppp/8/2p5/4P3/P7/1PPP1PPP/RNBQKBNR b KQkq -",
        "rnbqkbnr/p2ppppp/1p6/2p5/4P3/P7/1PPP1PPP/RNBQKBNR w KQkq -",
        "rnbqkbnr/p2ppppp/1p6/2p5/4P2P/P7/1PPP1PP1/RNBQKBNR b KQkq -",
        "rnbqkbnr/3ppppp/1pp5/2p5/4P2P/P7/1PPP1PP1/RNBQKBNR w KQkq -"
    ]
    positions = [Position(fen=f) for f in fens]
    session.add_all(positions)
    session.commit()

    moves = [
        Move(from_position_id=positions[0].id, to_position_id=positions[1].id, uci="e2e4", san="e4"),
        Move(from_position_id=positions[1].id, to_position_id=positions[2].id, uci="c7c5", san="c5"),
        Move(from_position_id=positions[2].id, to_position_id=positions[3].id, uci="a2a3", san="a3"),
        Move(from_position_id=positions[3].id, to_position_id=positions[4].id, uci="b7b6", san="b6"),
        Move(from_position_id=positions[4].id, to_position_id=positions[5].id, uci="h2h4", san="h4"),
        Move(from_position_id=positions[5].id, to_position_id=positions[6].id, uci="c6c5", san="c6")
    ]
    session.add_all(moves)
    session.commit()
    session.close()
    db.close()

    network_requests = []

    def mock_get(url, headers):
        unquoted = urllib.parse.unquote_plus(url)
        network_requests.append(unquoted)
        if fens[0] in unquoted:
            return json.dumps({"moves": [{"uci": "e2e4", "white": 500, "draws": 200, "black": 300, "total": 1000}]}).encode()
        if fens[1] in unquoted:
            return json.dumps({"moves": [{"uci": "c7c5", "white": 250, "draws": 100, "black": 150, "total": 500}]}).encode()
        if fens[2] in unquoted:
            return json.dumps({"moves": [{"uci": "a2a3", "white": 5, "draws": 2, "black": 3, "total": 10}]}).encode()
        if fens[3] in unquoted:
            return json.dumps({"moves": [
                {"uci": "b8c6", "white": 3, "draws": 1, "black": 2, "total": 6},
                {"uci": "e7e6", "white": 2, "draws": 1, "black": 1, "total": 4}
            ]}).encode()
        return json.dumps({"moves": []}).encode()

    with patch("time.sleep"), \
         patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get):

        # RUN 1: Full initial import
        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True
        assert len(network_requests) == 6  # 0 to 5 queried, 6 skipped

        # RUN 2: Immediate restart must be idempotent!
        network_requests.clear()
        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True
        assert "bereits Lichess-Daten" in msg
        assert len(network_requests) == 0, f"Expected 0 requests on restart, got {len(network_requests)}"

        # RUN 3: Another restart must also do 0 queries
        network_requests.clear()
        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True
        assert "bereits Lichess-Daten" in msg
        assert len(network_requests) == 0


def test_lichess_import_masters_fallback_for_deep_positions(mock_user_dir, sample_repertoire):
    """
    Verifies that for positions at depth >= 50 (move 26+), run_lichess_import with elo_category='high'
    automatically routes requests to explorer.lichess.org/masters to bypass the 25-move cap.
    Also verifies that existing empty records for move 26 with active incoming moves are purged and fetched.
    """
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    session.query(Move).delete()
    session.query(Position).delete()
    session.query(LichessData).delete()
    session.commit()

    # Create a 3-position chain at move 25 Black (depth 49) -> move 26 White (depth 50) -> move 26 Black (depth 51)
    fen_p49 = "5k2/p1r5/2pR2pb/4pp2/2B5/5P2/PPP3P1/1K6 b - - 0 25"
    fen_p50 = "8/p1r3k1/2pR2pb/4pp2/2B5/5P2/PPP3P1/1K6 w - - 0 26"
    fen_p51 = "8/p1r3k1/2pR2pb/4pp2/1PB5/5P2/P1P3P1/1K6 b - - 0 26"

    pos49 = Position(fen=fen_p49)
    pos50 = Position(fen=fen_p50)
    pos51 = Position(fen=fen_p51)
    session.add_all([pos49, pos50, pos51])
    session.commit()

    m49 = Move(from_position_id=pos49.id, to_position_id=pos50.id, uci="f8g7", san="Kg7")
    m50 = Move(from_position_id=pos50.id, to_position_id=pos51.id, uci="b2b4", san="b4")
    session.add_all([m49, m50])
    session.commit()

    # Pre-populate pos49 with 10 games for f8g7, and pos50/pos51 with stale empty {}
    session.add_all([
        LichessData(fen=fen_p49, elo_range="high", moves_json=json.dumps({"f8g7": {"white": 4, "draws": 2, "black": 4, "total": 10}})),
        LichessData(fen=fen_p50, elo_range="high", moves_json=json.dumps({})),
        LichessData(fen=fen_p51, elo_range="high", moves_json=json.dumps({}))
    ])
    session.commit()

    network_requests = []
    def mock_get(url, headers):
        unquoted = urllib.parse.unquote_plus(url)
        network_requests.append(unquoted)
        if fen_p50 in unquoted:
            assert "explorer.lichess.org/masters" in unquoted
            return json.dumps({"moves": [{"uci": "b2b4", "white": 10, "draws": 5, "black": 4, "total": 19}]}).encode()
        if fen_p51 in unquoted:
            assert "explorer.lichess.org/masters" in unquoted
            return json.dumps({"moves": [{"uci": "h6f4", "white": 8, "draws": 4, "black": 3, "total": 15}]}).encode()
        return json.dumps({"moves": []}).encode()

    with patch("time.sleep"), \
         patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get):

        success, msg = run_lichess_import(sample_repertoire, "high")
        assert success is True

    # Check that pos50 and pos51 were both queried using masters and updated
    ld50 = session.query(LichessData).filter_by(fen=fen_p50, elo_range="high").first()
    assert ld50 is not None
    data50 = json.loads(ld50.moves_json)
    assert "b2b4" in data50
    assert data50["b2b4"]["total"] == 19

    ld51 = session.query(LichessData).filter_by(fen=fen_p51, elo_range="high").first()
    assert ld51 is not None
    data51 = json.loads(ld51.moves_json)
    assert "h6f4" in data51
    assert data51["h6f4"]["total"] == 15

    # Check network requests used masters
    assert len(network_requests) == 2
    for req in network_requests:
        assert "explorer.lichess.org/masters" in req
