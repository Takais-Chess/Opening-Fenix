import pytest
import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.services.tree_navigation_service import TreeNavigationService
from opening_fenix.core.db.database import DatabaseManager

@pytest.fixture
def tree_service(mock_user_dir):
    db_path = ":memory:"
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Create test data
    # Root (Start)
    p0 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -")
    session.add(p0)
    session.flush()
    
    # 1. e4
    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    session.add(p1)
    session.flush()
    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4", priority_score=1.0)
    session.add(m1)
    
    # 1... e5
    p2 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    session.add(p2)
    session.flush()
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e7e5", san="e5", priority_score=1.0)
    session.add(m2)
    
    # Tag p2 with variation
    p2.variation_1 = "Open Games"
    p2.variation_2 = "Italian Game"
    
    session.commit()
    service = TreeNavigationService(session)
    yield service
    session.close()
    db.close()

def test_get_history_for_move_recursive(tree_service):
    # Find move e7e5 (m2)
    m2 = tree_service.repo_session.query(Move).filter_by(uci="e7e5").one()
    history = tree_service.get_history_for_move_recursive(m2.id)
    
    # Should have 2 moves: e4 and e5
    assert len(history) == 2
    assert history[0]['san'] == "e4"
    assert history[1]['san'] == "e5"

def test_get_absolute_ancestor_fen(tree_service):
    m2 = tree_service.repo_session.query(Move).filter_by(uci="e7e5").one()
    ancestor_fen = tree_service.get_absolute_ancestor_fen(m2.id)
    
    # Should be the starting position
    assert "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR" in ancestor_fen

def test_get_variation_structure(tree_service):
    struct = tree_service.get_variation_structure()
    assert "Open Games" in struct
    assert "Italian Game" in struct["Open Games"]

def test_variation_filter_info(tree_service):
    # Test "Open Games"
    info = tree_service.get_variation_filter_info("Open Games")
    assert len(info['roots']) == 1
    # Lead up should include p0 and p1 IDs
    # Verify the root is p2
    p2 = tree_service.repo_session.query(Position).filter_by(variation_1="Open Games").one()
    assert p2.id in info['roots']

def test_get_variation_entry_point_fen(tree_service):
    fen = tree_service.get_variation_entry_point_fen("Open Games")
    assert "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR" in fen

def test_ancestor_variation_inheritance(tree_service):
    # Add a child of p2 (e5) without explicit tags
    p3 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq -")
    tree_service.repo_session.add(p3)
    tree_service.repo_session.flush()
    p2 = tree_service.repo_session.query(Position).filter_by(variation_1="Open Games").one()
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="b1c3", san="Nc3")
    tree_service.repo_session.add(m3)
    tree_service.repo_session.commit()
    
    v1 = tree_service._find_ancestor_variation(p3.id, 1)
    assert v1 == "Open Games"
    
    v2 = tree_service._find_ancestor_variation(p3.id, 2)
    assert v2 == "Italian Game"
