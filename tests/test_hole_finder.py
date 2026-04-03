import pytest
import chess
import json
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove, LichessData

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
    holes = backend.find_repertoire_holes(0.1, "high")
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
    holes = backend.find_repertoire_holes(0.1, "high")
    
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
    holes = backend.find_repertoire_holes(0.01, "high")
    assert any(h['move_san'] == 'e5' for h in holes)
    
    # Mark the POSITION (e4) as exempt
    backend.set_position_hole_exempt(e4_fen, True)
    
    # Check hole is gone
    holes = backend.find_repertoire_holes(0.01, "high")
    assert not any(h['move_san'] == 'e5' for h in holes)
    
    # Reset
    backend.reset_hole_exemptions()
    holes = backend.find_repertoire_holes(0.01, "high")
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
    
    holes = backend.find_repertoire_holes(0.1, "high")
    # Hole at e5 position (User side)
    assert any(h['fen'] == e5_fen and h['type'] == 'user' for h in holes)
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
    
    holes = backend.find_repertoire_holes(0.01, "high")
    
    # P_fen (p_coll) isreached via both paths.
    # It should report the hole 'e6' at p_fen EXACTLY ONCE.
    p_holes = [h for h in holes if h['fen'].startswith(p_fen)]
    assert len(p_holes) == 1
    assert p_holes[0]['move_san'] == 'e6'
