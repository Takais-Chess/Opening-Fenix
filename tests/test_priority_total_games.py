from opening_fenix.core.utils import get_repertoire_db_path
import pytest
import os
import json
import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.services.priority_service import calculate_priority_scores, calculate_local_priority_scores

def test_priority_total_games_logic(mock_user_dir):
    repo_name = "test_total_games"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # 1. Setup metadata (color = white)
    session.add(Metadata(key="color", value="w"))
    
    # 2. Setup positions
    # Start -> e4 (User) -> e5 (Opponent)
    #               |-> c5 (Opponent)
    start_board = chess.Board()
    start_fen = " ".join(start_board.fen().split(" ")[:4])
    
    e4_board = chess.Board()
    e4_board.push_san("e4")
    e4_fen = " ".join(e4_board.fen().split(" ")[:4])
    
    e5_board = e4_board.copy()
    e5_board.push_san("e5")
    e5_fen = " ".join(e5_board.fen().split(" ")[:4])
    
    c5_board = e4_board.copy()
    c5_board.push_san("c5")
    c5_fen = " ".join(c5_board.fen().split(" ")[:4])
    
    p_start = Position(fen=start_fen)
    p_e4 = Position(fen=e4_fen)
    p_e5 = Position(fen=e5_fen)
    p_c5 = Position(fen=c5_fen)
    session.add_all([p_start, p_e4, p_e5, p_c5])
    session.flush()
    
    # Moves
    m_e4 = Move(from_position_id=p_start.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5")
    m_c5 = Move(from_position_id=p_e4.id, to_position_id=p_c5.id, uci="c7c5", san="c5")
    session.add_all([m_e4, m_e5, m_c5])
    session.flush()
    
    # Repertoire
    rm_e4 = RepertoireMove(move_id=m_e4.id, is_active=True)
    rm_e5 = RepertoireMove(move_id=m_e5.id, is_active=True)
    rm_c5 = RepertoireMove(move_id=m_c5.id, is_active=True)
    session.add_all([rm_e4, rm_e5, rm_c5])
    session.commit()
    
    # 3. Setup Lichess Data for e4 position (Opponent Turn)
    # e5 has 600 games, c5 has 300 games, and d5 (NOT in DB) has 100 games.
    # Total games = 1000.
    moves_json = {
        "e7e5": {"total": 600},
        "c7c5": {"total": 300},
        "d7d5": {"total": 100}
    }
    ld = LichessData(fen=e4_fen, elo_range="high", moves_json=json.dumps(moves_json))
    session.add(ld)
    session.commit()
    
    # 4. Calculate
    success, msg = calculate_priority_scores(repo_name, "high")
    assert success, msg
    
    session.expire_all()
    # Check probabilities
    # User turn (Start -> e4): split equally (here only 1 move) -> 1.0
    db_m_e4 = session.get(Move, m_e4.id)
    assert db_m_e4.priority_score == 1.0
    
    # Opponent turn (e4 -> e5, c5):
    # total_from_lichess = 1000. no rare moves. effective_total = 1000.
    # e5 share = 600 / 1000 = 0.6. Prio = 1.0 * 0.6 = 0.6
    # c5 share = 300 / 1000 = 0.3. Prio = 1.0 * 0.3 = 0.3
    db_m_e5 = session.get(Move, m_e5.id)
    db_m_c5 = session.get(Move, m_c5.id)
    
    assert db_m_e5.priority_score == pytest.approx(0.6)
    assert db_m_c5.priority_score == pytest.approx(0.3)
    
    # 5. Test "1 Game" Rule + User Color Change
    # Let's make user black to test opponent turn at start.
    session.query(Metadata).filter_by(key="color").update({"value": "b"})
    session.commit()
    
    # Setup rare move: e5 -> f4
    f4_board = e5_board.copy()
    f4_board.push_san("f4")
    f4_fen = " ".join(f4_board.fen().split(" ")[:4])
    p_f4 = Position(fen=f4_fen)
    session.add(p_f4)
    session.flush()
    m_f4 = Move(from_position_id=p_e5.id, to_position_id=p_f4.id, uci="f2f4", san="f4")
    session.add(m_f4)
    session.flush()
    rm_f4 = RepertoireMove(move_id=m_f4.id, is_active=True)
    session.add(rm_f4)
    session.commit()
    
    # Start position Lichess data: e4=90, d4=10. Total=100.
    session.add(LichessData(fen=start_fen, elo_range="high", moves_json=json.dumps({"e2e4": {"total": 90}, "d2d4": {"total": 10}})))
    session.commit()
    
    # Pos e5 Lichess data: empty (None).
    # All moves from e5 (only f4) become rare moves.
    
    success, msg = calculate_priority_scores(repo_name, "high")
    assert success
    session.expire_all()
    
    # start (Opponent): e4=0.9
    db_m_e4 = session.get(Move, m_e4.id)
    assert db_m_e4.priority_score == pytest.approx(0.9)
    
    # e4 (User): e5=0.45 (User turn, equal split among e5 and c5)
    db_m_e5 = session.get(Move, m_e5.id)
    assert db_m_e5.priority_score == pytest.approx(0.45)
    
    # e5 (Opponent): f4=1.0 share relative to e5's probability (=0.45).
    # Effective total = 0 + 1(rare) = 1.
    db_m_f4 = session.get(Move, m_f4.id)
    assert db_m_f4.priority_score == pytest.approx(0.45)

    # 6. Test local calculation
    # Change e4 stats and recalculate locally from start.
    session.query(LichessData).filter_by(fen=start_fen).update({"moves_json": json.dumps({"e2e4": {"total": 50}, "d2d4": {"total": 50}})})
    session.commit()
    
    # Recalculate from start position
    success, msg = calculate_local_priority_scores(session, p_start.id, "high")
    assert success
    session.commit()
    session.expire_all()
    
    # e4 share should now be 50 / 100 = 0.5
    db_m_e4 = session.get(Move, m_e4.id)
    assert db_m_e4.priority_score == pytest.approx(0.5)
    
    session.close()
    db.close()

def test_priority_islands_have_zero_priority(mock_user_dir):
    repo_name = "test_priority_islands"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # 1. Setup metadata (color = white)
    session.add(Metadata(key="color", value="w"))
    
    # 2. Setup positions
    start_board = chess.Board()
    start_fen = " ".join(start_board.fen().split(" ")[:4])
    
    e4_board = chess.Board()
    e4_board.push_san("e4")
    e4_fen = " ".join(e4_board.fen().split(" ")[:4])
    
    p_start = Position(fen=start_fen)
    p_e4 = Position(fen=e4_fen)
    
    # Island position (completely disconnected from start position)
    island_board = chess.Board("r1bqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    # Make a move to get a distinct FEN
    island_board.push_san("d4")
    island_fen = " ".join(island_board.fen().split(" ")[:4])
    island_to_board = island_board.copy()
    island_to_board.push_san("d5")
    island_to_fen = " ".join(island_to_board.fen().split(" ")[:4])
    
    p_island_from = Position(fen=island_fen)
    p_island_to = Position(fen=island_to_fen)
    
    session.add_all([p_start, p_e4, p_island_from, p_island_to])
    session.flush()
    
    # Moves
    m_e4 = Move(from_position_id=p_start.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_island_d5 = Move(from_position_id=p_island_from.id, to_position_id=p_island_to.id, uci="d7d5", san="d5")
    session.add_all([m_e4, m_island_d5])
    session.flush()
    
    # Repertoire moves
    rm_e4 = RepertoireMove(move_id=m_e4.id, is_active=True)
    rm_island_d5 = RepertoireMove(move_id=m_island_d5.id, is_active=True)
    session.add_all([rm_e4, rm_island_d5])
    session.commit()
    
    # 3. Calculate priority scores
    success, msg = calculate_priority_scores(repo_name, "high")
    assert success, msg
    
    session.expire_all()
    
    # Start -> e4 move should have priority score 1.0 (100%)
    db_m_e4 = session.get(Move, m_e4.id)
    assert db_m_e4.priority_score == 1.0
    
    # Island move should have priority score 0.0 (0%) because it's an unreachable island
    db_m_island_d5 = session.get(Move, m_island_d5.id)
    assert db_m_island_d5.priority_score == 0.0
    
    session.close()
    db.close()

