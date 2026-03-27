import pytest
from opening_fenix.core.models import RepertoireMove, Move, Position
from sqlalchemy import text

def test_ab_toggle_training_filter(mock_user_dir, repertoire_manager, training_manager):
    session = repertoire_manager.repo_session
    
    # 1. Setup: Start Position -> e4 (A) or d4 (B)
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    d4_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPPP1PPP/RNBQKBNR b KQkq -"
    
    # Ensure p1 (start) exists
    p_start = session.query(Position).filter_by(fen=start_fen).first()
    
    # Add d4 position
    p_d4 = Position(fen=d4_fen)
    session.add(p_d4)
    session.flush()
    
    # Moves
    m_e4 = session.query(Move).filter_by(from_position_id=p_start.id, uci="e2e4").first()
    # Note: e4 is already in sample_repertoire from conftest
    
    m_d4 = Move(from_position_id=p_start.id, to_position_id=p_d4.id, uci="d2d4", san="d4", priority_score=0.5)
    session.add(m_d4)
    session.flush()
    
    # Add d4 to repertoire
    rm_d4 = RepertoireMove(move_id=m_d4.id, level=1)
    session.add(rm_d4)
    session.commit()
    
    # Refresh training manager
    training_manager.on_repertoire_changed()
    
    # Initially both should be in stats (as "new" moves)
    new_c, due_c, dist = training_manager.get_stats()
    # Total moves from white should be 2 (e4 and d4)
    assert new_c == 2
    
    # 2. Mark d4 as inactive (this should fail initially if column is missing)
    try:
        rm_d4.is_active = False
        session.commit()
    except Exception as e:
        pytest.fail(f"Could not set is_active on RepertoireMove: {e}")
    
    training_manager.on_repertoire_changed()
    
    # Only e4 should be active now
    new_c, due_c, dist = training_manager.get_stats()
    assert new_c == 1
    
def test_ab_toggle_descendant_filter(mock_user_dir, repertoire_manager, training_manager):
    session = repertoire_manager.repo_session
    
    # Setup: Start -> e4 -> e5 -> Nf3
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    e5_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    nf3_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"
    
    p_start = session.query(Position).filter_by(fen=start_fen).first()
    p_e4 = session.query(Position).filter_by(fen=e4_fen).first()
    p_e5 = session.query(Position).filter_by(fen=e5_fen).first()
    
    p_nf3 = Position(fen=nf3_fen)
    session.add(p_nf3)
    session.flush()
    
    m_e4 = session.query(Move).filter_by(from_position_id=p_start.id, uci="e2e4").first()
    m_e5 = session.query(Move).filter_by(from_position_id=p_e4.id, uci="e7e5").first()
    
    m_nf3 = Move(from_position_id=p_e5.id, to_position_id=p_nf3.id, uci="g1f3", san="Nf3", priority_score=1.0)
    session.add(m_nf3)
    session.flush()
    
    # Repertoire: e4 and Nf3
    rm_e4 = session.query(RepertoireMove).filter_by(move_id=m_e4.id).first()
    rm_nf3 = RepertoireMove(move_id=m_nf3.id, level=1)
    session.add(rm_nf3)
    session.commit()
    
    training_manager.on_repertoire_changed()
    
    # Both e4 and Nf3 should be in stats
    new_c, _, _ = training_manager.get_stats()
    assert new_c == 2
    
    # Mark e4 as inactive. Nf3 (descendant) should also be filtered out.
    rm_e4.is_active = False
    session.commit()
    
    training_manager.on_repertoire_changed()
    new_c, _, _ = training_manager.get_stats()
    assert new_c == 0
