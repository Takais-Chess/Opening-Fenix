import pytest
import chess
import json
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.services.hole_finder_service import (
    find_repertoire_holes, find_priority_mismatches, find_level_mismatches,
    find_repertoire_transpositions, run_hole_finder_task
)


def clean_fen(fen):
    return " ".join(fen.split(" ")[:4])

@pytest.fixture
def backend(mock_user_dir, sample_repertoire):
    be = CreatorBackend()
    be.load_repertoire(sample_repertoire)
    yield be
    if be.session:
        be.session.close()
    if be.db_manager:
        be.db_manager.close()

def test_user_holes_no_move(backend):
    # Clear existing moves from start to simulate "hole" for White
    backend.session.query(RepertoireMove).delete()
    backend.session.commit()
    
    start_fen = clean_fen(chess.STARTING_FEN)
    
    # Lichess: e4 (70%), d4 (30%)
    ld_start = LichessData(fen=start_fen, elo_range="high", moves_json=json.dumps({
        "e2e4": {"san": "e4", "total": 700},
        "d2d4": {"san": "d4", "total": 300}
    }))
    backend.session.add(ld_start)
    backend.session.commit()
    
    # Scan with 10% threshold. Both e4 and d4 should be holes.
    holes = find_repertoire_holes(backend.session, 0.1, "high")

    assert any(h['move_san'] == 'e4' and h['type'] == 'user' for h in holes)
    assert any(h['move_san'] == 'd4' and h['type'] == 'user' for h in holes)

def test_opponent_holes(backend):
    # Repertoire: start -> e4 (covered in sample_repertoire)
    # Opponent turn at e4: Lichess says e5 (50%), c5 (50%)
    # Repertoire has NO response to e5 or c5.
    
    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    ld_e4 = LichessData(fen=e4_fen, elo_range="high", moves_json=json.dumps({
        "e7e5": {"san": "e5", "total": 500},
        "c7c5": {"san": "c5", "total": 500}
    }))
    backend.session.add(ld_e4)
    backend.session.commit()
    
    # Scan from start (threshold 10%)
    # Prob(e4) = 1.0 (User plays it)
    # Prob(e5 at e4) = 1.0 * 0.5 = 0.5 -> Hole.
    holes = find_repertoire_holes(backend.session, 0.1, "high")

    
    assert any(h['move_san'] == 'e5' and h['type'] == 'opponent' for h in holes)
    assert any(h['move_san'] == 'c5' and h['type'] == 'opponent' for h in holes)

def test_hole_exemption(backend):
    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    ld_e4 = LichessData(fen=e4_fen, elo_range="high", moves_json=json.dumps({
        "e7e5": {"san": "e5", "total": 1000}
    }))
    backend.session.add(ld_e4)
    backend.session.commit()
    
    # Check hole exists
    holes = find_repertoire_holes(backend.session, 0.01, "high")

    assert any(h['move_san'] == 'e5' for h in holes)
    
    # Mark the POSITION (e4) as exempt
    backend.set_position_hole_exempt(e4_fen, True)
    
    # Check hole is gone
    holes = find_repertoire_holes(backend.session, 0.01, "high")

    assert not any(h['move_san'] == 'e5' for h in holes)
    
    # Reset
    count = backend.reset_hole_exemptions()
    assert count == 1
    assert backend.reset_hole_exemptions() == 0
    holes = find_repertoire_holes(backend.session, 0.01, "high")

    assert any(h['move_san'] == 'e5' for h in holes)

def test_deep_propagation(backend):
    # start -> e4 -> e5 (User turn at e5)
    # Reach prob for e5 position = 1.0 * 0.5 = 0.5 (if e4->e5 by opponent is 50%)
    
    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    e5_fen = clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    
    # 1. We must make e4 -> e5 a RepertoireMove so the BFS continues to e5_fen
    e4_pos = backend.session.query(Position).filter(Position.fen.like(e4_fen + "%")).first()
    e5_move = backend.session.query(Move).filter_by(from_position_id=e4_pos.id, uci="e7e5").first()
    rm_e5 = RepertoireMove(move_id=e5_move.id, level=1)
    backend.session.add(rm_e5)
    backend.session.commit()

    # Lichess at start: e4 (100%)
    ld_start = LichessData(fen=clean_fen(chess.STARTING_FEN), elo_range="high", moves_json=json.dumps({
        "e2e4": {"san": "e4", "total": 1000}
    }))
    
    # Lichess at e4 (opponent): e5 (50%), c5 (50%)
    ld_e4 = LichessData(fen=e4_fen, elo_range="high", moves_json=json.dumps({
        "e7e5": {"san": "e5", "total": 500},
        "c7c5": {"san": "c5", "total": 500}
    }))
    
    # Now at e5 (User turn), User has NO move. 
    # Reach prob for e5 position = 1.0 (start) * 1.0 (e4) * 0.5 (e5) = 0.5.
    
    backend.session.add_all([ld_start, ld_e4])
    backend.session.commit()
    
    holes = find_repertoire_holes(backend.session, 0.1, "high")

    # Hole at e5 position (User side) - Identified as a gap
    assert any(h['fen'] == e5_fen and h['type'] == 'repertoire_gap' for h in holes)
    # Also hole at e4 position (Opponent side - move c5)
    assert any(h['move_san'] == 'c5' and h['type'] == 'opponent' for h in holes)
def test_transposition_handling(backend):
    # Two paths to the same FEN: 
    # Path A: 1. d4 Nf6 2. c4
    # Path B: 1. c4 Nf6 2. d4
    
    start_fen = clean_fen(chess.STARTING_FEN)
    d4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -")
    c4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq -")
    nf6_fen = clean_fen("rnbqkb1r/pppppppp/5n2/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -") # after 1. d4 Nf6 or 1. c4 Nf6
    p_fen = clean_fen("rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR w KQkq -") # after 1. d4 Nf6 2. c4
    
    # Actually, 1. d4 Nf6 2. c4 leads to p_fen
    # 1. c4 Nf6 2. d4 also leads to p_fen
    
    # 1. Ensure positions exist
    p_start = backend.session.query(Position).filter(Position.fen.like(start_fen + "%")).first()
    p_d4 = Position(fen=d4_fen); p_c4 = Position(fen=c4_fen)
    p_nf6 = Position(fen=nf6_fen); p_coll = Position(fen=p_fen)
    backend.session.add_all([p_d4, p_c4, p_nf6, p_coll])
    backend.session.flush()
    
    # 2. Add moves
    # start -> d4, start -> c4
    m_d4 = Move(from_position_id=p_start.id, to_position_id=p_d4.id, uci="d2d4", san="d4")
    m_c4 = Move(from_position_id=p_start.id, to_position_id=p_c4.id, uci="c2c4", san="c4")
    # d4 -> Nf6, c4 -> Nf6
    m_nf6_d4 = Move(from_position_id=p_d4.id, to_position_id=p_nf6.id, uci="g8f6", san="Nf6")
    m_nf6_c4 = Move(from_position_id=p_c4.id, to_position_id=p_nf6.id, uci="g8f6", san="Nf6")
    # nf6 -> d4, nf6 -> c4
    m_d4_nf6 = Move(from_position_id=p_nf6.id, to_position_id=p_coll.id, uci="d2d4", san="d4")
    m_c4_nf6 = Move(from_position_id=p_nf6.id, to_position_id=p_coll.id, uci="c2c4", san="c4")
    
    backend.session.add_all([m_d4, m_c4, m_nf6_d4, m_nf6_c4, m_d4_nf6, m_c4_nf6])
    backend.session.flush()
    
    # 3. Make them RepertoireMoves
    for m in [m_d4, m_c4, m_nf6_d4, m_nf6_c4, m_d4_nf6, m_c4_nf6]:
        backend.session.add(RepertoireMove(move_id=m.id, level=1))
    
    # 4. Lichess Data (Paths A & B)
    # At p_coll (1. d4 Nf6 2. c4 or 1. c4 Nf6 2. d4), we have a hole for Black 'e6'
    backend.session.add_all([
        LichessData(fen=start_fen, elo_range="high", moves_json=json.dumps({"d2d4": {"san": "d4", "total": 500}, "c2c4": {"san": "c4", "total": 500}})),
        LichessData(fen=d4_fen, elo_range="high", moves_json=json.dumps({"g8f6": {"san": "Nf6", "total": 1000}})),
        LichessData(fen=c4_fen, elo_range="high", moves_json=json.dumps({"g8f6": {"san": "Nf6", "total": 1000}})),
        LichessData(fen=nf6_fen, elo_range="high", moves_json=json.dumps({"d2d4": {"san": "d4", "total": 500}, "c2c4": {"san": "c4", "total": 500}})),
        LichessData(fen=p_fen, elo_range="high", moves_json=json.dumps({"e7e6": {"san": "e6", "total": 1000}}))
    ])
    backend.session.commit()
    
    holes = find_repertoire_holes(backend.session, 0.01, "high")

    
    # P_fen (p_coll) is reached via both paths.
    # It should report a hole at p_fen. 
    # NOTE: Since we have Lichess data AND no repertoire moves at this leaf, 
    # it might report both a 'repertoire_gap' and a 'user' hole. 
    p_holes = [h for h in holes if h['fen'].startswith(p_fen)]
    assert len(p_holes) >= 1
    assert any(h['move_san'] == 'e6' for h in p_holes)

def test_find_priority_mismatches(backend):
    # Setup: 1.e4 is in RepertoireLevel 1.
    # It has priority_score 1.0 (100%) in sample_repertoire fixture.
    
    # Scan for Level 1 with 50% threshold -> Should find 1.e4
    mismatches = find_priority_mismatches(backend.session, 1, 50)

    assert len(mismatches) == 1
    assert mismatches[0]['move_san'] == 'e4'
    assert mismatches[0]['type'] == 'priority_check'
    assert "Start" in mismatches[0]['path']
    
    # Scan for Level 1 with 150% threshold -> Should find nothing
    mismatches = find_priority_mismatches(backend.session, 1, 150)

    assert len(mismatches) == 0
    
    # Scan for Level 2 (which doesn't exist/no moves) -> Should find nothing
    mismatches = find_priority_mismatches(backend.session, 2, 10)


def test_hole_finder_uses_san_dynamic(backend):
    """Verify that hole finder calculates SAN if not present in LichessData."""
    start_fen = clean_fen(chess.STARTING_FEN)
    
    # Lichess data with NO 'san' field, only UCI
    ld_start = LichessData(fen=start_fen, elo_range="high", moves_json=json.dumps({
        "e2e4": {"total": 1000} # Missing 'san'
    }))
    backend.session.add(ld_start)
    backend.session.commit()
    
    # Scan – should find e4 as a hole for User (since start has no rep moves by default in some tests)
    # We ensure no rep moves exist at start
    backend.session.query(RepertoireMove).delete()
    backend.session.commit()
    
    holes = find_repertoire_holes(backend.session, 1.0, "high") # 1% threshold
    
    # Find the 'e4' hole. 
    # It might be found as a 'repertoire_gap' (move_san='—') or a 'user' hole (move_san='e4').
    assert any(h['fen'] == start_fen and h['move_san'] == "e4" for h in holes)

def get_or_create_pos(session, fen):
    p = session.query(Position).filter(Position.fen.like(fen + "%")).first()
    if not p:
        p = Position(fen=fen)
        session.add(p)
        session.flush()
    return p

def test_find_level_mismatches_basic(backend):
    """Verify that level increases on User moves are flagged as mismatches."""
    session = backend.session
    # Setup Color: White
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="w"))
    session.commit()
    
    # Repertoire Path:
    # 1. e4 (User, Level 1)
    # 1... e5 (Opponent, Level 1)
    # 2. Nf3 (User, Level 2) <-- VIOLATION
    
    # FENs
    root_fen = clean_fen(chess.STARTING_FEN)
    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    e5_fen = clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    nf3_fen = clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -")
    
    # 1. Ensure Positions exist
    p_root = get_or_create_pos(session, root_fen)
    p_e4 = get_or_create_pos(session, e4_fen)
    p_e5 = get_or_create_pos(session, e5_fen)
    p_nf3 = get_or_create_pos(session, nf3_fen)
    
    # 2. Add Moves (Avoid duplicates if possible)
    def add_move_if_not_exists(f, t, u, s):
        m = session.query(Move).filter_by(from_position_id=f, to_position_id=t, uci=u).first()
        if not m:
            m = Move(from_position_id=f, to_position_id=t, uci=u, san=s)
            session.add(m)
            session.flush()
        return m

    m_e4 = add_move_if_not_exists(p_root.id, p_e4.id, "e2e4", "e4")
    m_e5 = add_move_if_not_exists(p_e4.id, p_e5.id, "e7e5", "e5")
    m_nf3 = add_move_if_not_exists(p_e5.id, p_nf3.id, "g1f3", "Nf3")
    
    # 3. Add RepertoireMoves with levels
    session.query(RepertoireMove).delete() # Clear existing to be sure
    session.add(RepertoireMove(move_id=m_e4.id, level=1))
    session.add(RepertoireMove(move_id=m_e5.id, level=1))
    session.add(RepertoireMove(move_id=m_nf3.id, level=2)) # Transition 1 -> 2 on User move
    session.commit()
    
    # Run Level Check
    results = find_level_mismatches(session)
    
    # Assertions
    assert len(results) >= 1 # Might be more if sample repo has other stuff, but at least ours
    assert any(r['move_san'] == "Nf3" for r in results)
    m = next(r for r in results if r['move_san'] == "Nf3")
    assert m['type'] == "level_mismatch"
    assert m['fen'] == e5_fen

def test_find_level_mismatches_opponent_ok(backend):
    """Verify that level increases on Opponent moves are NOT flagged."""
    session = backend.session
    # Setup Color: White
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="w"))
    session.commit()
    
    # Repertoire Path:
    # 1. e4 (User, Level 1)
    # 1... e5 (Opponent, Level 2) <-- This is OK!
    
    root_fen = clean_fen(chess.STARTING_FEN)
    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    e5_fen = clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    
    p_root = get_or_create_pos(session, root_fen)
    p_e4 = get_or_create_pos(session, e4_fen)
    p_e5 = get_or_create_pos(session, e5_fen)
    
    def add_move_if_not_exists(f, t, u, s):
        m = session.query(Move).filter_by(from_position_id=f, to_position_id=t, uci=u).first()
        if not m:
            m = Move(from_position_id=f, to_position_id=t, uci=u, san=s)
            session.add(m)
            session.flush()
        return m

    m_e4 = add_move_if_not_exists(p_root.id, p_e4.id, "e2e4", "e4")
    m_e5 = add_move_if_not_exists(p_e4.id, p_e5.id, "e7e5", "e5")
    
    session.query(RepertoireMove).delete() # Clear existing to be sure
    session.add(RepertoireMove(move_id=m_e4.id, level=1))
    session.add(RepertoireMove(move_id=m_e5.id, level=2)) # Increase on Opponent move
    session.commit()
    
    results = find_level_mismatches(session)
    
    # We only care that there are NO level mismatches here.
    # (There might be a gap reported because the test line ends, which is OK)
    mismatches = [r for r in results if r['type'] == 'level_mismatch']
    assert len(mismatches) == 0

def test_find_level_mismatches_alternate_moves(backend):
    """Verify that a level increase is NOT flagged if a lower or equal level move exists."""
    session = backend.session
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="w"))
    session.commit()
    
    # Path: 1. e4 (L1) -> 1... e5 (L1) -> 2. Nf3 (L1) AND 2. d4 (L2)
    p_root = get_or_create_pos(session, clean_fen(chess.STARTING_FEN))
    p_e4 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"))
    p_e5 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"))
    p_nf3 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"))
    p_d4 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppp1ppp/8/4p3/3PP3/8/PPP2PPP/RNBQKBNR b KQkq -"))
    
    def add_move_if_not_exists(f, t, u, s):
        m = session.query(Move).filter_by(from_position_id=f, to_position_id=t, uci=u).first()
        if not m:
            m = Move(from_position_id=f, to_position_id=t, uci=u, san=s)
            session.add(m)
            session.flush()
        return m

    m_e4 = add_move_if_not_exists(p_root.id, p_e4.id, "e2e4", "e4")
    m_e5 = add_move_if_not_exists(p_e4.id, p_e5.id, "e7e5", "e5")
    m_nf3 = add_move_if_not_exists(p_e5.id, p_nf3.id, "g1f3", "Nf3")
    m_d4 = add_move_if_not_exists(p_e5.id, p_d4.id, "d2d4", "d4")
    
    session.query(RepertoireMove).delete()
    session.add(RepertoireMove(move_id=m_e4.id, level=1))
    session.add(RepertoireMove(move_id=m_e5.id, level=1))
    session.add(RepertoireMove(move_id=m_nf3.id, level=1)) # Correct level move exists
    session.add(RepertoireMove(move_id=m_d4.id, level=2))  # Sideline at higher level
    session.commit()
    
    results = find_level_mismatches(session)
    
    # Should NOT have any level mismatches because Nf3 (L1) satisfies the Level 1 path
    assert not any(r['type'] == 'level_mismatch' for r in results)

def test_find_level_mismatches_gap(backend):
    """Verify that a position where it's our turn but we have no moves is flagged as a gap."""
    session = backend.session
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="w"))
    session.commit()
    
    # Path: 1. e4 (L1) -> 1... e5 (Opponant L1) -> (User turns, no move)
    p_root = get_or_create_pos(session, clean_fen(chess.STARTING_FEN))
    p_e4 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"))
    p_e5 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"))
    
    def add_move_if_not_exists(f, t, u, s):
        m = session.query(Move).filter_by(from_position_id=f, to_position_id=t, uci=u).first()
        if not m:
            m = Move(from_position_id=f, to_position_id=t, uci=u, san=s)
            session.add(m)
            session.flush()
        return m

    m_e4 = add_move_if_not_exists(p_root.id, p_e4.id, "e2e4", "e4")
    m_e5 = add_move_if_not_exists(p_e4.id, p_e5.id, "e7e5", "e5")
    
    session.query(RepertoireMove).delete()
    session.add(RepertoireMove(move_id=m_e4.id, level=1))
    session.add(RepertoireMove(move_id=m_e5.id, level=1))
    session.commit()
    
    # We call find_repertoire_holes because gap detection was moved there for consistency.
    results = find_repertoire_holes(session, 1.0, "high")
    
    assert any(r['type'] == 'repertoire_gap' and r['fen'].startswith(p_e5.fen) for r in results)

def test_find_level_mismatches_strict_transposition(backend):
    """Verify that transpositions flag a jump if the LOWEST incoming path doesn't justify the level."""
    session = backend.session
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="w"))
    session.commit()

    # Path 1: Root -> P (L1)
    # Path 2: Root -> P (L2)
    # User Move from P: P -> Q (L2)
    # Under STRICT logic, this IS a violation because the L1 path reaches P but has no L1 move.

    p_root = get_or_create_pos(session, clean_fen(chess.STARTING_FEN))
    p_p = get_or_create_pos(session, "rnbqkbnr/ppp1pppp/8/3p4/8/8/PPPPPPPP/RNBQKBNR w KQkq -") 
    p_q = get_or_create_pos(session, "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    
    m_a = Move(from_position_id=p_root.id, to_position_id=p_p.id, uci="d2d4", san="d4")
    m_b = Move(from_position_id=p_root.id, to_position_id=p_p.id, uci="c2c4", san="c4")
    m_c = Move(from_position_id=p_p.id, to_position_id=p_q.id, uci="e2e4", san="e4")
    session.add_all([m_a, m_b, m_c])
    session.flush()
    
    session.query(RepertoireMove).delete()
    session.add(RepertoireMove(move_id=m_a.id, level=1))
    session.add(RepertoireMove(move_id=m_b.id, level=2))
    session.add(RepertoireMove(move_id=m_c.id, level=2))
    session.commit()
    
    results = find_level_mismatches(session)
    # Should HAVE a level mismatch because the L1 path (m_a) doesn't justify the L2 move (m_c)
    assert any(r['type'] == 'level_mismatch' and r['move_san'] == 'e4' for r in results)

def test_find_level_mismatches_diagnostics(backend):
    """Verify that level transitions include from_level and to_level info."""
    session = backend.session
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="w"))
    session.commit()
    
    # Path: 1. e4 (L1) -> 1... e5 (L1) -> 2. Nf3 (L2) 
    # This should be a Level 1 -> Level 2 transition.
    
    root_fen = clean_fen(chess.STARTING_FEN)
    p_root = get_or_create_pos(session, root_fen)
    p_e4 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"))
    p_e5 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"))
    p_nf3 = get_or_create_pos(session, clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"))
    
    def add_move_if_not_exists(f, t, u, s):
        m = session.query(Move).filter_by(from_position_id=f, to_position_id=t, uci=u).first()
        if not m:
            m = Move(from_position_id=f, to_position_id=t, uci=u, san=s)
            session.add(m)
            session.flush()
        return m

    m_1 = add_move_if_not_exists(p_root.id, p_e4.id, "e2e4", "e4")
    m_2 = add_move_if_not_exists(p_e4.id, p_e5.id, "e7e5", "e5")
    m_3 = add_move_if_not_exists(p_e5.id, p_nf3.id, "g1f3", "Nf3")
    
    session.query(RepertoireMove).delete()
    session.add(RepertoireMove(move_id=m_1.id, level=1))
    session.add(RepertoireMove(move_id=m_2.id, level=1))
    session.add(RepertoireMove(move_id=m_3.id, level=2)) # L1 -> L2!
    session.commit()
    
    results = find_level_mismatches(session)
    mm = next(r for r in results if r['move_san'] == "Nf3")
    assert mm['from_level'] == 1
    assert mm['to_level'] == 2


def test_find_repertoire_transpositions_1move(backend):
    """
    Test 1-move Opponent transposition detection:
    Repertoire for White:
    Branch 1: 1. e4 e5 2. Nf3
    Branch 2: 1. e4 Nf6
    From position after 1. e4 (Black to move), Black move 1... e5 transposes to Branch 1!
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    session.add(Metadata(key="color", value="w"))

    # Root
    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    # After 1. e4 (Black to move)
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    # Branch 1: 1... e5 -> 2. Nf3
    p_e5 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Open Game")
    p_nf3 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="2. Nf3")
    # Branch 2: 1... Nf6 (Alekhine)
    p_nf6 = Position(fen=clean_fen("rnbqkb1r/pppppppp/5n2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Alekhine")

    session.add_all([p_root, p_e4, p_e5, p_nf3, p_nf6])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5")
    m_nf3 = Move(from_position_id=p_e5.id, to_position_id=p_nf3.id, uci="g1f3", san="Nf3")

    m_nf6 = Move(from_position_id=p_e4.id, to_position_id=p_nf6.id, uci="g8f6", san="Nf6")

    session.add_all([m_e4, m_e5, m_nf3, m_nf6])
    session.flush()

    for m in [m_e4, m_e5, m_nf3, m_nf6]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    transpositions = find_repertoire_transpositions(session)

    # From p_e4 (after 1. e4), opponent move 1... e5 is already covered.
    # But if we remove m_e5 from active repertoire and leave p_e5 as a destination reachable via another path:
    session.query(RepertoireMove).filter_by(move_id=m_e5.id).delete()
    session.commit()

    transpositions = find_repertoire_transpositions(session)
    match = [t for t in transpositions if t['fen'] == clean_fen(p_e4.fen) and t['move_san'] == 'e5']
    assert len(match) == 1
    t = match[0]
    assert t['depth'] == 1
    assert t['type'] == 'transposition_1'
    assert t['target_fen'] == clean_fen(p_e5.fen)
    assert t['quality_label'] == "—"


def test_find_repertoire_transpositions_2moves(backend):
    """
    Test 2-move Opponent-then-User transposition detection:
    Branch 1: 1. e4 c5 2. Nf3 d6 3. d4 (Open Sicilian)
    Branch 2: 1. e4 e6 (French)
    From 1. e4 (Black to move), Black plays 1... c5, then White plays 2. Nf3, transposing to Branch 1!
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    # Branch 1 (Sicilian)
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian", good_moves=json.dumps(["g1f3"]))
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")
    # Branch 2 (French)
    p_fre_e6 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="French")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3, p_fre_e6])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e6 = Move(from_position_id=p_e4.id, to_position_id=p_fre_e6.id, uci="e7e6", san="e6")

    # In branch 1, 1... c5 -> 2. Nf3
    m_c5 = Move(from_position_id=p_e4.id, to_position_id=p_sic_c5.id, uci="c7c5", san="c5")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_e6, m_c5, m_nf3])
    session.flush()

    # Active moves in repertoire: e4, e6, and 2. Nf3 (from c5)
    # Notice: m_c5 is NOT linked from p_e4 (so 1... c5 is unlinked from p_e4!)
    for m in [m_e4, m_e6, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    transpositions = find_repertoire_transpositions(session)

    # From p_e4 (Black to move): Opponent plays 1... c5, User plays 2. Nf3 -> transposes to p_sic_nf3!
    match = [t for t in transpositions if t['fen'] == clean_fen(p_e4.fen) and t['depth'] == 2 and 'c5' in t['move_san'] and 'Nf3' in t['move_san']]
    assert len(match) == 1
    t = match[0]
    assert t['type'] == 'transposition_2'
    assert t['target_fen'] == clean_fen(p_sic_nf3.fen)
    assert t['quality'] == 'ausgezeichnet'
    assert "🟢" in t['quality_label']


def test_transposition_quality_filter(backend):
    """
    Test quality classification based on user move soundness.
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian", good_moves=json.dumps(["g1f3"]))
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")
    p_fre_e6 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="French")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3, p_fre_e6])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e6 = Move(from_position_id=p_e4.id, to_position_id=p_fre_e6.id, uci="e7e6", san="e6")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_e6, m_nf3])
    session.flush()

    for m in [m_e4, m_e6, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    transpositions = find_repertoire_transpositions(session)
    match = [t for t in transpositions if t['fen'] == clean_fen(p_e4.fen) and t['depth'] == 2 and 'c5' in t['move_san']]
    assert len(match) == 1
    assert match[0]['quality'] == 'ausgezeichnet'
    assert "🟢" in match[0]['quality_label']


def test_transposition_limit_cap_15(backend):
    """
    Verify that the search ends cleanly when reaching an explicit max_transpositions limit.
    """
    session = backend.session
    transpositions = find_repertoire_transpositions(session, max_transpositions=15)
    assert len(transpositions) <= 15


def test_inactive_move_not_suggested_as_transposition(backend):
    """
    Verify that moves marked as is_active=False are NOT proposed as new transpositions.
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_e5 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="1... e5")

    session.add_all([p_root, p_e4, p_e5])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5")

    session.add_all([m_e4, m_e5])
    session.flush()

    # m_e4 is active, but m_e5 is INACTIVE (user deactivated it)
    session.add(RepertoireMove(move_id=m_e4.id, level=1, is_active=True))
    session.add(RepertoireMove(move_id=m_e5.id, level=1, is_active=False))
    session.commit()

    transpositions = find_repertoire_transpositions(session)
    # The inactive move e7e5 should NOT be suggested as a transposition
    e5_transpos = [t for t in transpositions if t['fen'] == clean_fen(p_e4.fen) and 'e5' in t['move_san']]
    assert len(e5_transpos) == 0


def test_transposition_backward_cycle_filtered(backend):
    """
    Verify that transpositions leading to a shallower/ancestor position are filtered out.
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_e5 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="1... e5")
    p_nf3 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="2. Nf3")

    session.add_all([p_root, p_e4, p_e5, p_nf3])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5")
    m_nf3 = Move(from_position_id=p_e5.id, to_position_id=p_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_e5, m_nf3])
    session.flush()

    for m in [m_e4, m_e5, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    transpositions = find_repertoire_transpositions(session)
    # Target positions must not be shallower than the starting position
    for t in transpositions:
        if t['fen'] == clean_fen(p_nf3.fen):
            assert t['target_fen'] != clean_fen(p_root.fen)
            assert t['target_fen'] != clean_fen(p_e4.fen)


def test_2move_transposition_off_repertoire_intermediate(backend):
    """
    Verify that a 2-move transposition is detected even when the intermediate
    position (opponent's move) is not yet visited/cached in the repertoire.
    Line 1 (Philidor): 1. e4 e5 2. Nf3 d6 3. d4 Nf6 4. Nc3
    Line 2 (Pirc): 1. e4 d6 2. d4 Nf6 3. Nc3 g6
    From Pirc after 3. Nc3, Black plays 3... e5, White plays 4. Nf3 -> transposes to Philidor!
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    session.add(Metadata(key="color", value="w"))

    def add_line(moves):
        b = chess.Board()
        prev_pos = session.query(Position).filter_by(fen=clean_fen(b.fen())).first()
        if not prev_pos:
            prev_pos = Position(fen=clean_fen(b.fen()))
            session.add(prev_pos)
            session.commit()
        for m_san in moves:
            m = b.parse_san(m_san)
            b.push(m)
            fen = clean_fen(b.fen())
            pos = session.query(Position).filter_by(fen=fen).first()
            if not pos:
                pos = Position(fen=fen)
                session.add(pos)
                session.commit()
            move_obj = session.query(Move).filter_by(from_position_id=prev_pos.id, uci=m.uci()).first()
            if not move_obj:
                move_obj = Move(from_position_id=prev_pos.id, to_position_id=pos.id, uci=m.uci(), san=m_san)
                session.add(move_obj)
                session.commit()
            rm = session.query(RepertoireMove).filter_by(move_id=move_obj.id).first()
            if not rm:
                rm = RepertoireMove(move_id=move_obj.id, is_active=True)
                session.add(rm)
                session.commit()
            prev_pos = pos

    line1 = ['e4', 'e5', 'Nf3', 'd6', 'd4', 'Nf6', 'Nc3']
    line2 = ['e4', 'd6', 'd4', 'Nf6', 'Nc3', 'g6']
    add_line(line1)
    add_line(line2)

    transpositions = find_repertoire_transpositions(session)
    e5_nf3_transpos = [t for t in transpositions if t['depth'] == 2 and 'e5' in t['move_san'] and 'Nf3' in t['move_san']]
    assert len(e5_nf3_transpos) >= 1
    t = e5_nf3_transpos[0]
    assert t['type'] == 'transposition_2'
    assert '🟢' in t['quality_label']


def test_2move_transposition_depth25_best_move_accepted(backend):
    """
    When engine analysis runs at depth 25 and the user's transposition move is the best move,
    it must be awarded '🟢 Ausgezeichnet'.
    """
    from unittest.mock import MagicMock
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian")
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")
    p_fre_e6 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="French")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3, p_fre_e6])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e6 = Move(from_position_id=p_e4.id, to_position_id=p_fre_e6.id, uci="e7e6", san="e6")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_e6, m_nf3])
    session.flush()
    for m in [m_e4, m_e6, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    # Mock engine that confirms g1f3 (Nf3) is the #1 best move at depth 25
    mock_engine = MagicMock()
    mock_engine.analyse.return_value = {"pv": [chess.Move.from_uci("g1f3")]}

    transpositions = find_repertoire_transpositions(session, engine=mock_engine)
    match = [t for t in transpositions if t['depth'] == 2 and 'c5' in t['move_san'] and 'Nf3' in t['move_san']]
    assert len(match) == 1
    assert match[0]['quality'] == 'ausgezeichnet'
    assert '🟢' in match[0]['quality_label']
    assert mock_engine.analyse.called


def test_2move_transposition_depth25_not_best_move_rejected(backend):
    """
    When the opponent makes a move and the user's transposition move is NOT the best move
    (e.g. an alternative move like d2d4 is better to punish opponent mistake),
    the suboptimal transposition move must be REJECTED and not recommended.
    """
    from unittest.mock import MagicMock
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian")
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")
    p_fre_e6 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="French")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3, p_fre_e6])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e6 = Move(from_position_id=p_e4.id, to_position_id=p_fre_e6.id, uci="e7e6", san="e6")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_e6, m_nf3])
    session.flush()
    for m in [m_e4, m_e6, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    # Mock engine that says d2d4 is the #1 best move (NOT g1f3)
    mock_engine = MagicMock()
    mock_engine.analyse.return_value = {"pv": [chess.Move.from_uci("d2d4")]}

    transpositions = find_repertoire_transpositions(session, engine=mock_engine)
    match = [t for t in transpositions if t['depth'] == 2 and 'c5' in t['move_san'] and 'Nf3' in t['move_san']]
    # Must be empty because g1f3 was not the best move!
    assert len(match) == 0
    assert mock_engine.analyse.called


def test_transposition_streaming_callback(backend):
    """
    Verify that item_callback is invoked incrementally for every found transposition.
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian")
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_nf3])
    session.flush()
    for m in [m_e4, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    emitted_items = []
    def on_item(item):
        emitted_items.append(item)

    transpositions = find_repertoire_transpositions(session, item_callback=on_item)
    assert len(emitted_items) == len(transpositions)
    assert len(emitted_items) >= 1


def test_engine_cache_service(tmp_path):
    """Verify that EngineCacheService saves, persists across instances, and updates depth-25 evaluations."""
    from opening_fenix.core.services.engine_cache_service import EngineCacheService

    db_file = str(tmp_path / "test_engine_cache.db")
    service1 = EngineCacheService(db_path=db_file)

    test_fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    assert service1.get_best_move(test_fen, min_depth=25) is None

    # Save depth 25 best move
    service1.set_best_move(test_fen, 25, "g1f3")
    assert service1.get_best_move(test_fen, min_depth=25) == "g1f3"

    # Verify a new service instance reading the same DB file sees the cached evaluation
    service2 = EngineCacheService(db_path=db_file)
    assert service2.get_best_move(test_fen, min_depth=25) == "g1f3"
    # Querying for depth 30 should return None since cached depth is 25
    assert service2.get_best_move(test_fen, min_depth=30) is None


def test_transposition_uses_persistent_cache(backend, monkeypatch, tmp_path):
    """
    Verify that find_repertoire_transpositions uses the persistent cache
    and does NOT need to call the engine if the position is already cached.
    """
    from opening_fenix.core.services.engine_cache_service import EngineCacheService
    cache_db = str(tmp_path / "eval_cache.db")
    cache_svc = EngineCacheService(db_path=cache_db)

    # Monkeypatch EngineCacheService default path to use temporary DB
    monkeypatch.setattr(
        "opening_fenix.core.services.engine_cache_service.get_engine_cache_db_path",
        lambda *args, **kwargs: cache_db
    )

    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian")
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")
    session.add_all([m_e4, m_nf3])
    session.flush()

    for m in [m_e4, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    # Pre-populate cache for the intermediate Sicilian position (after 1... c5)
    inter_fen = clean_fen(p_sic_c5.fen)
    cache_svc.set_best_move(inter_fen, 25, "g1f3")

    # Mock engine that raises an error if analyse is called
    class StrictMockEngine:
        def analyse(self, *args, **kwargs):
            raise AssertionError("Engine should NOT be called because position is cached!")

    mock_engine = StrictMockEngine()

    # Run transposition finder with mock engine - it should read from cache and NOT call engine
    transpositions = find_repertoire_transpositions(session, engine=mock_engine, cache_service=cache_svc)

    match = [t for t in transpositions if t['fen'] == clean_fen(p_e4.fen) and t['depth'] == 2]
    assert len(match) == 1
    assert match[0]['quality'] == 'ausgezeichnet'
    assert "🟢" in match[0]['quality_label']


def test_2move_transposition_skips_if_intermediate_in_repertoire(backend):
    """
    Verify that if an opponent move m1 lands on a position that is ALREADY in the active repertoire
    (reachable from root via another line), it is suggested as a 1-move transposition,
    and is NOT suggested as a 2-move transposition (which would redundantly re-suggest our own move m2
    that already exists in the repertoire).
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="b"))

    # Line 1: 1. d4 e6 2. c4 d5
    # Root -> 1. d4 -> 1... e6 -> 2. c4 -> 2... d5
    b1 = chess.Board()
    p_root = Position(fen=clean_fen(b1.fen()))
    b1.push_san("d4")
    p_d4 = Position(fen=clean_fen(b1.fen()))
    b1.push_san("e6")
    p_d4_e6 = Position(fen=clean_fen(b1.fen()))
    b1.push_san("c4")
    p_d4_e6_c4 = Position(fen=clean_fen(b1.fen()))
    b1.push_san("d5")
    p_d5 = Position(fen=clean_fen(b1.fen()))

    # Line 2: 1. c4 e6
    # From 1. c4 e6, opponent (White) can play 2. d4.
    # 1. c4 e6 2. d4 reaches the exact same position as Line 1 (1. d4 e6 2. c4)!
    b2 = chess.Board()
    b2.push_san("c4")
    p_c4 = Position(fen=clean_fen(b2.fen()))
    b2.push_san("e6")
    p_c4_e6 = Position(fen=clean_fen(b2.fen()))

    session.add_all([p_root, p_d4, p_d4_e6, p_d4_e6_c4, p_d5, p_c4, p_c4_e6])
    session.flush()

    m_d4 = Move(from_position_id=p_root.id, to_position_id=p_d4.id, uci="d2d4", san="d4")
    m_e6_line1 = Move(from_position_id=p_d4.id, to_position_id=p_d4_e6.id, uci="e7e6", san="e6")
    m_c4_line1 = Move(from_position_id=p_d4_e6.id, to_position_id=p_d4_e6_c4.id, uci="c2c4", san="c4")
    m_d5 = Move(from_position_id=p_d4_e6_c4.id, to_position_id=p_d5.id, uci="d7d5", san="d5")

    m_c4_line2 = Move(from_position_id=p_root.id, to_position_id=p_c4.id, uci="c2c4", san="c4")
    m_e6_line2 = Move(from_position_id=p_c4.id, to_position_id=p_c4_e6.id, uci="e7e6", san="e6")

    session.add_all([m_d4, m_e6_line1, m_c4_line1, m_d5, m_c4_line2, m_e6_line2])
    session.flush()

    for m in [m_d4, m_e6_line1, m_c4_line1, m_d5, m_c4_line2, m_e6_line2]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    # From p_c4_e6 (after 1. c4 e6, White to move):
    # Opponent playing 2. d4 lands on p_d4_e6_c4, which is ALREADY in reachable_fens (via Line 1)!
    # Pass 1 should suggest 1-move transposition: 2. d4.
    # Pass 2 MUST NOT suggest 2-move transposition: 2. d4 2... d5 (because 2... d5 is already in Line 1!)
    transpositions = find_repertoire_transpositions(session)

    d4_1move = [t for t in transpositions if t['fen'] == clean_fen(p_c4_e6.fen) and t['depth'] == 1 and t['move_san'] == 'd4']
    assert len(d4_1move) == 1

    d4_2move = [t for t in transpositions if t['fen'] == clean_fen(p_c4_e6.fen) and t['depth'] == 2 and 'd4' in t['move_san']]
    assert len(d4_2move) == 0


def test_castling_uci_covered_in_transpositions(backend):
    """
    Verifies that if a castling move is in the repertoire (even if stored with Chess960 UCI e1h1),
    it is correctly recognized as covered and NOT suggested as a transposition.
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()

    # Color = Black
    session.query(Metadata).filter_by(key="color").delete()
    session.add(Metadata(key="color", value="b"))

    # Create root
    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    session.add(p_root)
    session.flush()

    # White plays e4, c5, Nf3, d6, Bc4, Nf6, then O-O
    b = chess.Board()
    for san in ["e4", "c5", "Nf3", "d6", "Bc4", "Nf6"]:
        b.push_san(san)
    fen_before_castle = clean_fen(b.fen())

    p_before = Position(fen=fen_before_castle)
    b.push_san("O-O")
    fen_after_castle = clean_fen(b.fen())
    p_after = Position(fen=fen_after_castle)

    session.add_all([p_before, p_after])
    session.flush()

    # Store castling move with Chess960 UCI 'e1h1'
    m_castle = Move(from_position_id=p_before.id, to_position_id=p_after.id, uci="e1h1", san="O-O")
    session.add(m_castle)
    session.flush()
    session.add(RepertoireMove(move_id=m_castle.id, level=1, is_active=True))

    # Link root to p_before so p_before is reachable in BFS
    m_link = Move(from_position_id=p_root.id, to_position_id=p_before.id, uci="e2e4", san="e4")
    session.add(m_link)
    session.flush()
    session.add(RepertoireMove(move_id=m_link.id, level=1, is_active=True))
    session.commit()

    transpositions = find_repertoire_transpositions(session)
    # White castling (O-O) must NOT be suggested as a transposition because it is already in the repertoire!
    castle_suggestions = [
        t for t in transpositions
        if t['fen'] == fen_before_castle and t['move_san'] == 'O-O'
    ]
    assert len(castle_suggestions) == 0


def test_repair_castling_ucis(backend):
    """
    Verifies that repair_castling_ucis correctly normalizes Chess960 castling UCIs
    (e1h1, e8h8, e1a1, e8a8) to standard chess UCIs (e1g1, e8g8, e1c1, e8c8).
    """
    from opening_fenix.core.services.repair_service import repair_castling_ucis

    session = backend.session
    p1 = Position(fen="r1bqkb1r/pppp1ppp/2n5/2nBP3/3p4/5N2/PPP2PPP/RNBQK2R w KQkq -")
    p2 = Position(fen="r1bqkb1r/pppp1ppp/2n5/2nBP3/3p4/5N2/PPP2PPP/RNBQ1RK1 b kq -")
    session.add_all([p1, p2])
    session.flush()

    # Move stored as e1h1
    m = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e1h1", san="O-O")
    session.add(m)
    session.flush()
    session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    repaired = repair_castling_ucis(session)
    assert repaired == 1

    session.refresh(m)
    assert m.uci == "e1g1"
    assert m.san == "O-O"


def test_find_repertoire_transpositions_custom_depth(backend):
    """Test that find_repertoire_transpositions queries engine/cache with custom depth and returns ply_depth."""
    session = backend.session
    class MockEngine:
        def __init__(self):
            self.last_depth = None
        def analyse(self, board, limit):
            self.last_depth = limit.depth
            import chess
            return {"pv": [chess.Move.from_uci("g1f3")]}

    mock_eng = MockEngine()
    results = find_repertoire_transpositions(session, engine=mock_eng, depth=18)
    assert isinstance(results, list)
    for r in results:
        assert "ply_depth" in r


def test_transposition_potential_prio_score_calculation(backend):
    """Test that potential priority score is calculated accurately for 1-move and 2-move transpositions."""
    session = backend.session
    
    # Path A: 1. d4 Nf6 2. c4
    # Path B: 1. c4 (opponent can play Nf6 which transposes into Path A)
    # Let's populate LichessData for c4 position with Nf6 having 40% frequency (400 / 1000 games)
    c4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq -")
    ld_c4 = LichessData(fen=c4_fen, elo_range="high", moves_json=json.dumps({
        "g8f6": {"san": "Nf6", "total": 400},
        "e7e5": {"san": "e5", "total": 600}
    }))
    session.add(ld_c4)
    session.commit()

    results = find_repertoire_transpositions(session, elo_range="high")
    assert isinstance(results, list)
    for item in results:
        assert "priority_score" in item
        assert "popularity" in item
        assert item["popularity"] == pytest.approx(item["priority_score"] * 100.0)
        if item.get("move_san") == "Nf6" and item.get("fen") == c4_fen:
            # 1.0 (start) * 1.0 (c4) * 0.40 (Nf6) = 0.40 (40%)
            assert item["priority_score"] == pytest.approx(0.40)
            assert item["popularity"] == pytest.approx(40.0)


def test_transposition_filters_underpromotion_and_captured_promotions(backend):
    """
    Test that underpromotions (e.g. exf8=R+, exf8=N) and promotions where the promoted piece
    is immediately captured (e.g. exf8=Q+ Kxf8) are filtered out from transposition results.
    """
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="b"))

    # Position 1 (White to move): White can play exf8=Q+, exf8=R+, exf8=N+
    board = chess.Board("5rk1/4Pppp/8/8/8/8/8/4K3 w - - 0 1")
    p_orig = Position(fen=clean_fen(board.fen()))
    
    # Target position after Kxf8 (e.g. White played exf8=something, Black played Kxf8)
    board_after = chess.Board("5k2/5ppp/8/8/8/8/8/4K3 w - - 0 2")
    p_target = Position(fen=clean_fen(board_after.fen()))

    # Repertoire move from root leading here, target position is active in repertoire
    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    session.add_all([p_orig, p_target, p_root])
    session.flush()

    m_to_orig = Move(from_position_id=p_root.id, to_position_id=p_orig.id, uci="e2e4", san="e4")
    m_to_target = Move(from_position_id=p_root.id, to_position_id=p_target.id, uci="d2d4", san="d4")
    session.add_all([m_to_orig, m_to_target])
    session.flush()
    session.add(RepertoireMove(move_id=m_to_orig.id, level=1, is_active=True))
    session.add(RepertoireMove(move_id=m_to_target.id, level=1, is_active=True))
    session.commit()

    results = find_repertoire_transpositions(session)
    # Underpromotions and promotions captured on the next move must be filtered out
    promotion_results = [
        r for r in results
        if "=" in r.get("move_san", "") or any(u.endswith(("q", "r", "b", "n")) for u in r.get("path_ucis", []))
    ]
    assert len(promotion_results) == 0


def test_2move_transposition_within_10cp_accepted(backend):
    """
    When the user's transposition move is not the #1 move, but is within 10 centipawns
    of the best move, it must be accepted with quality 'solide'.
    """
    from unittest.mock import MagicMock
    session = backend.session
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    session.add(Metadata(key="color", value="w"))

    p_root = Position(fen=clean_fen(chess.STARTING_FEN))
    p_e4 = Position(fen=clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"), variation_1="1. e4")
    p_sic_c5 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="Sicilian")
    p_sic_nf3 = Position(fen=clean_fen("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"), variation_1="Sicilian 2.Nf3")
    p_fre_e6 = Position(fen=clean_fen("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"), variation_1="French")

    session.add_all([p_root, p_e4, p_sic_c5, p_sic_nf3, p_fre_e6])
    session.flush()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e6 = Move(from_position_id=p_e4.id, to_position_id=p_fre_e6.id, uci="e7e6", san="e6")
    m_nf3 = Move(from_position_id=p_sic_c5.id, to_position_id=p_sic_nf3.id, uci="g1f3", san="Nf3")

    session.add_all([m_e4, m_e6, m_nf3])
    session.flush()
    for m in [m_e4, m_e6, m_nf3]:
        session.add(RepertoireMove(move_id=m.id, level=1, is_active=True))
    session.commit()

    # Mock engine:
    # 1. Main analysis returns best_uci = "d2d4" with score = 40 cp
    # 2. root_moves analysis for g1f3 returns score = 32 cp (loss = 8 cp <= 10 cp)
    mock_engine = MagicMock()
    class MockScore:
        def __init__(self, cp):
            self.cp = cp
        @property
        def relative(self):
            return self
        def score(self, mate_score=10000):
            return self.cp

    def fake_analyse(board, limit, root_moves=None, **kwargs):
        if root_moves and any(m.uci() == "g1f3" for m in root_moves):
            return {"score": MockScore(32), "pv": [chess.Move.from_uci("g1f3")]}
        return {"score": MockScore(40), "pv": [chess.Move.from_uci("d2d4")]}

    mock_engine.analyse.side_effect = fake_analyse

    transpositions = find_repertoire_transpositions(session, engine=mock_engine)
    match = [t for t in transpositions if t['depth'] == 2 and 'c5' in t['move_san'] and 'Nf3' in t['move_san']]
    assert len(match) == 1
    assert match[0]['quality'] == 'solide'
    assert '🟡' in match[0]['quality_label']











