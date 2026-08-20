import pytest
import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, Base
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.services.tree_navigation_service import TreeNavigationService

@pytest.fixture
def nav_session(mock_user_dir):
    from opening_fenix.core.utils import get_repertoire_db_path
    db_path = get_repertoire_db_path("NavTestRepo")
    db = DatabaseManager(db_path, base=Base)
    session = db.get_session()
    
    # Create positions
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    e5_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    nf3_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"
    
    def norm(f): return " ".join(f.split()[:4])
    
    p1 = Position(fen=norm(start_fen))
    p2 = Position(fen=norm(e4_fen), variation_1="King's Pawn")
    p3 = Position(fen=norm(e5_fen), variation_1="King's Pawn", variation_2="Open Game")
    p4 = Position(fen=norm(nf3_fen), variation_1="King's Pawn", variation_2="Open Game", variation_3="Main Line")
    
    session.add_all([p1, p2, p3, p4])
    session.flush()
    
    m1 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4", priority_score=1.0)
    m2 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="e7e5", san="e5", priority_score=1.0)
    m3 = Move(from_position_id=p3.id, to_position_id=p4.id, uci="g1f3", san="Nf3", priority_score=0.8)
    session.add_all([m1, m2, m3])
    session.flush()
    
    session.add(RepertoireMove(move_id=m1.id, level=1))
    session.add(RepertoireMove(move_id=m2.id, level=1))
    session.add(RepertoireMove(move_id=m3.id, level=1))
    session.commit()
    
    yield session, (p1, p2, p3, p4), (m1, m2, m3)
    session.close()
    db.close()

def test_tree_nav_history_recursive(nav_session):
    session, positions, moves = nav_session
    service = TreeNavigationService(session)
    
    history = service.get_history_for_move_recursive(moves[2].id)
    assert len(history) == 3
    assert [h['san'] for h in history] == ["e4", "e5", "Nf3"]
    
    # Test with variation name filter
    var_history = service.get_history_for_move_recursive(moves[2].id, variation_name="Open Game")
    assert len(var_history) == 3

def test_tree_nav_absolute_ancestor(nav_session):
    session, positions, moves = nav_session
    service = TreeNavigationService(session)
    
    root_fen = service.get_absolute_ancestor_fen(moves[2].id)
    assert root_fen is not None
    assert "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR" in root_fen

def test_tree_nav_variation_structure_and_roots(nav_session):
    session, positions, moves = nav_session
    service = TreeNavigationService(session)
    
    roots = service.get_variation_roots("Open Game")
    assert len(roots) > 0
    
    struct = service.get_variation_structure()
    assert "King's Pawn" in struct
    assert "Open Game" in struct["King's Pawn"]
