import pytest
import chess
import json
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.services.hole_finder_service import find_repertoire_holes, find_priority_mismatches, find_level_mismatches


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
    backend.reset_hole_exemptions()
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
