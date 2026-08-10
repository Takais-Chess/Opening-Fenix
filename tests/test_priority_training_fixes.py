import pytest
import chess
import json

from opening_fenix.core.db.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.services.priority_service import calculate_priority_scores, calculate_local_priority_scores
from opening_fenix.core.services.training_service import TrainingManager
from opening_fenix.core.repertoire import RepertoireManager

def test_transposition_priority_accumulation(mock_user_dir):
    repo_name = "test_transposition_prio"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    session.add(Metadata(key="color", value="w"))

    # Positions:
    # Path 1 (Short): Start -> e4 -> e5 -> Nf3 (to P_target)
    # Path 2 (Long):  Start -> c4 -> c5 -> Nf3 (to P_target)
    start_board = chess.Board()
    p_start = Position(fen=" ".join(start_board.fen().split(" ")[:4]))

    # Short path position
    b1 = start_board.copy(); b1.push_san("e4")
    p_e4 = Position(fen=" ".join(b1.fen().split(" ")[:4]))
    b2 = b1.copy(); b2.push_san("e5")
    p_e5 = Position(fen=" ".join(b2.fen().split(" ")[:4]))

    # Long path positions
    b_c4 = start_board.copy(); b_c4.push_san("c4")
    p_c4 = Position(fen=" ".join(b_c4.fen().split(" ")[:4]))
    b_c5 = b_c4.copy(); b_c5.push_san("c5")
    p_c5 = Position(fen=" ".join(b_c5.fen().split(" ")[:4]))

    # Target position reached from both paths
    p_target = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -")
    
    # Position after target
    b_after = chess.Board(p_target.fen); b_after.push_san("Nc6")
    p_after = Position(fen=" ".join(b_after.fen().split(" ")[:4]))

    session.add_all([p_start, p_e4, p_e5, p_c4, p_c5, p_target, p_after])
    session.flush()

    # Moves
    m_e4 = Move(from_position_id=p_start.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5")
    m_nf3_short = Move(from_position_id=p_e5.id, to_position_id=p_target.id, uci="g1f3", san="Nf3")

    m_c4 = Move(from_position_id=p_start.id, to_position_id=p_c4.id, uci="c2c4", san="c4")
    m_c5 = Move(from_position_id=p_c4.id, to_position_id=p_c5.id, uci="c7c5", san="c5")
    m_nf3_long = Move(from_position_id=p_c5.id, to_position_id=p_target.id, uci="g1f3", san="Nf3")

    m_nc6 = Move(from_position_id=p_target.id, to_position_id=p_after.id, uci="b8c6", san="Nc6")

    session.add_all([m_e4, m_e5, m_nf3_short, m_c4, m_c5, m_nf3_long, m_nc6])
    session.flush()

    for m in [m_e4, m_e5, m_nf3_short, m_c4, m_c5, m_nf3_long, m_nc6]:
        session.add(RepertoireMove(move_id=m.id, is_active=True))
    session.commit()

    # Calculate scores
    success, msg = calculate_priority_scores(repo_name, "high")
    assert success, msg

    session.expire_all()
    # At start position, user has 2 moves (e4, c4) -> 0.5 split each
    assert session.get(Move, m_e4.id).priority_score == pytest.approx(0.5)
    assert session.get(Move, m_c4.id).priority_score == pytest.approx(0.5)

    # Opponent turn e5 (100% of branch) -> 0.5. User Nf3 short -> 0.5
    assert session.get(Move, m_nf3_short.id).priority_score == pytest.approx(0.5)
    # Opponent turn c5 (100% of branch) -> 0.5. User Nf3 long -> 0.5
    assert session.get(Move, m_nf3_long.id).priority_score == pytest.approx(0.5)

    # Move out of p_target (Nc6) is opponent turn.
    # Total probability reaching p_target = 0.5 + 0.5 = 1.0!
    # Nc6 should have priority_score = 1.0 (accumulated from BOTH transpositions)!
    assert session.get(Move, m_nc6.id).priority_score == pytest.approx(1.0)

    session.close()
    db.close()

def test_none_priority_score_no_crash(mock_user_dir):
    repo_name = "test_none_prio"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -")
    p2 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    session.add_all([p1, p2])
    session.flush()

    m = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4", priority_score=None)
    session.add(m)
    session.flush()
    session.add(RepertoireMove(move_id=m.id, is_active=True))
    session.commit()

    # Local prio score should not crash with None
    success, msg = calculate_local_priority_scores(session, p1.id, "high")
    assert success, msg

    session.close()
    db.close()

def test_training_mode_new_shallow_tie_breaking(mock_user_dir):
    repo_manager = RepertoireManager()
    repo_name = "test_tie_break"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # Create root move (depth 1) and deep move (depth 2), both priority_score = 0.0
    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    p2 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    p3 = Position(fen="rnbqkbnr/1ppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    p4 = Position(fen="rnbqkbnr/1ppppppp/8/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 2")
    
    session.add_all([p1, p2, p3, p4])
    session.flush()

    # Depth 1 move: e4
    m1 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4", priority_score=0.0)
    # Opponent move
    m2 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="a7a6", san="a6", priority_score=0.0)
    # Depth 2 move: Nf3
    m3 = Move(from_position_id=p3.id, to_position_id=p4.id, uci="g1f3", san="Nf3", priority_score=0.0)

    session.add_all([m1, m2, m3])
    session.flush()
    session.add_all([RepertoireMove(move_id=m1.id, level=1), RepertoireMove(move_id=m3.id, level=1)])
    session.commit()

    repo_manager.set_active_repertoire(repo_name)

    tm = TrainingManager("TestUser", repo_manager)
    
    # In 'new' mode, e4 (depth 1) should be chosen before Nf3 (depth 2) despite equal 0.0 priority
    next_move, _ = tm.get_next_move(mode='new')
    assert next_move is not None
    assert next_move.uci == "e2e4"

    session.close()
    db.close()

def test_cache_invalidation(mock_user_dir):
    repo_manager = RepertoireManager()
    repo_name = "test_cache_inval"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    p2 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    session.add_all([p1, p2])
    session.flush()
    m1 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4", priority_score=0.5)
    session.add(m1)
    session.flush()
    session.add(RepertoireMove(move_id=m1.id, level=1))
    session.commit()

    repo_manager.set_active_repertoire(repo_name)
    repo_manager._ensure_priority_cache()
    assert ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4") in repo_manager.priority_cache

    # Invalidate priority cache
    repo_manager.invalidate_priority_cache()
    assert repo_manager.priority_cache is None

    tm = TrainingManager("TestUser", repo_manager)
    tm._ensure_forward_cache()
    assert tm._forward_moves_cache is not None

    # Invalidate training caches
    tm.invalidate_caches()
    assert tm._forward_moves_cache is None

    session.close()
    db.close()
