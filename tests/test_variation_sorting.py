import pytest
from opening_fenix.core.services.tree_navigation_service import TreeNavigationService
from opening_fenix.core.models import Position, Move

def test_variation_sorting_by_priority(mock_user_dir, repertoire_manager):
    session = repertoire_manager.repo_session
    service = TreeNavigationService(session)
    
    # Clear existing data for a clean test
    session.query(Move).delete()
    session.query(Position).delete()
    session.commit()
    
    # Create test positions with different variations and priorities
    # Prio 1.0 (Highest)
    p_high = Position(fen="high", variation_1="Main Line", variation_2="Top Choice", cached_v1="Main Line")
    # Prio 0.5 (Mid)
    p_mid = Position(fen="mid", variation_1="Side Line", variation_2="Second Choice", cached_v1="Side Line")
    # Prio 0.1 (Low)
    p_low = Position(fen="low", variation_1="Main Line", variation_2="Rare Choice", cached_v1="Main Line")
    # Prio 2.0 (Highest priority but "Sonstiges")
    p_misc = Position(fen="misc", variation_1=None, variation_2="Sub of None", cached_v1=None)
    
    session.add_all([p_high, p_mid, p_low, p_misc])
    session.flush()
    
    # Add moves with different priorities
    m_high = Move(from_position_id=100, to_position_id=p_high.id, uci="h", san="h", priority_score=1.0)
    m_mid = Move(from_position_id=101, to_position_id=p_mid.id, uci="m", san="m", priority_score=0.5)
    m_low = Move(from_position_id=102, to_position_id=p_low.id, uci="l", san="l", priority_score=0.1)
    m_misc = Move(from_position_id=103, to_position_id=p_misc.id, uci="mi", san="mi", priority_score=2.0)
    
    session.add_all([m_high, m_mid, m_low, m_misc])
    session.commit()
    
    structure = service.get_variation_structure()
    
    # Expected order: "Main Line" (1.0), "Side Line" (0.5), "Sonstiges" (2.0 but forced to bottom)
    v1_keys = list(structure.keys())
    assert v1_keys[0] == "Main Line"
    assert v1_keys[1] == "Side Line"
    assert v1_keys[2] == "Sonstiges"
    
    assert structure["Main Line"][0] == "Top Choice"
    assert structure["Main Line"][1] == "Rare Choice"
    
    assert structure["Side Line"][0] == "Second Choice"
