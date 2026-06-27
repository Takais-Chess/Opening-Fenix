import pytest
import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.services.repertoire_service import RepertoireManager

@pytest.fixture
def complex_repertoire(repertoire_manager):
    session = repertoire_manager.repo_session
    
    # 1. e4 (v1=Openings)
    p_e4 = session.query(Position).filter(Position.fen.like("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR%")).first()
    p_e4.variation_1 = "Openings"
    
    # 1... e5 (v2=Open Games)
    p_e5 = session.query(Position).filter(Position.fen.like("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR%")).first()
    p_e5.variation_2 = "Open Games"
    
    # Add 2. Nf3
    p_nf3 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 2")
    session.add(p_nf3)
    session.flush()
    
    m_nf3 = Move(from_position_id=p_e5.id, to_position_id=p_nf3.id, uci="g1f3", san="Nf3", priority_score=2.0)
    session.add(m_nf3)
    
    # Add 2... Nc6 (v2=Italian Game)
    p_nc6 = Position(fen="r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 2")
    p_nc6.variation_2 = "Italian Game" # Intentionally leave v1 empty to test inheritance
    session.add(p_nc6)
    session.flush()
    
    m_nc6 = Move(from_position_id=p_nf3.id, to_position_id=p_nc6.id, uci="b8c6", san="Nc6", priority_score=1.5)
    session.add(m_nc6)
    
    session.flush()

    # Mark them as active in repertoire
    rm2 = RepertoireMove(move_id=m_nf3.id, level=1)
    rm3 = RepertoireMove(move_id=m_nc6.id, level=1)
    session.add_all([rm2, rm3])
    
    session.commit()
    
    # Clear caches to ensure we hit the DB
    repertoire_manager._variation_cache = {}
    repertoire_manager._structure_cache = None
    repertoire_manager._move_parent_cache = None
    
    return repertoire_manager

def test_variation_filter_preparation(complex_repertoire):
    # Test _prepare_variation_filter
    filter_data = complex_repertoire._prepare_variation_filter("Open Games")
    assert filter_data is not None
    assert len(filter_data["roots"]) > 0
    # The e4 position should be in lead-up because it leads to e5 (which is the root for "Open Games")
    assert len(filter_data["lead_up"]) > 0 
    
    # Test cache
    filter_data_cached = complex_repertoire._prepare_variation_filter("Open Games")
    assert filter_data_cached is filter_data

def test_variation_structure_inheritance(complex_repertoire):
    # Italian Game should inherit "Openings" from its ancestor e4
    structure = complex_repertoire.get_variation_structure()
    assert "Openings" in structure
    assert "Open Games" in structure["Openings"]
    assert "Italian Game" in structure["Openings"]

def test_history_for_move_complex(complex_repertoire):
    session = complex_repertoire.repo_session
    p_nc6 = session.query(Position).filter(Position.variation_2 == "Italian Game").first()
    move_to_nc6 = session.query(Move).filter_by(to_position_id=p_nc6.id).first()
    
    history = complex_repertoire.get_history_for_move(move_to_nc6)
    # Start -> e4 -> e5 -> Nf3 -> Nc6
    assert len(history) == 4
    assert history[0]['san'] == "e4"
    assert history[1]['san'] == "e5"
    assert history[2]['san'] == "Nf3"
    assert history[3]['san'] == "Nc6"

def test_get_explorer_data_missing_position(complex_repertoire, training_manager):
    # A position that exists in legal moves but not explicitly in DB
    # 1. d4 is not in our test repo
    d4_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1"
    data = complex_repertoire.get_explorer_data_for_fen(d4_fen, training_manager)
    
    assert data["is_player_turn"] is False # White played d4, now black's turn
    assert data["opponent_moves"] == [] # No moves in repo lead from d4 or to d4 response

def test_get_repertoire_moves_for_fen_player(complex_repertoire):
    # Start position: e4 is active
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    moves = complex_repertoire.get_repertoire_moves_for_fen(start_fen)
    assert "e2e4" in moves

def test_get_repertoire_moves_for_fen_opponent(complex_repertoire):
    # After 1. e4, what are repertoire moves? (1... e5)
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    moves = complex_repertoire.get_repertoire_moves_for_fen(e4_fen)
    assert "e7e5" in moves

def test_check_if_alternative_good_move(complex_repertoire):
    session = complex_repertoire.repo_session
    p_start = session.query(Position).filter(Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")).first()
    m_e4 = session.query(Move).filter_by(from_position_id=p_start.id, uci="e2e4").first()
    
    # e2e4 is the main move
    assert complex_repertoire.check_if_alternative_good_move(m_e4, "e2e4") is True
    
    # Add d2d4 as a "good move" json
    p_start.good_moves = '["d2d4"]'
    session.commit()
    
    assert complex_repertoire.check_if_alternative_good_move(m_e4, "d2d4") is True
    assert complex_repertoire.check_if_alternative_good_move(m_e4, "g1f3") is False

def test_get_alternative_move_type(complex_repertoire):
    session = complex_repertoire.repo_session
    p_start = session.query(Position).filter(Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")).first()
    m_e4 = session.query(Move).filter_by(from_position_id=p_start.id, uci="e2e4").first()
    
    # e2e4 is active in the repertoire
    assert complex_repertoire.get_alternative_move_type(m_e4, "e2e4") == 'repertoire'
    
    # Add d2d4 as a "good move" json
    p_start.good_moves = '["d2d4"]'
    session.commit()
    
    assert complex_repertoire.get_alternative_move_type(m_e4, "d2d4") == 'good'
    assert complex_repertoire.get_alternative_move_type(m_e4, "g1f3") is None

def test_delete_repertoire(complex_repertoire):
    # This might be destructive so we do it last
    repo_name = complex_repertoire.active_repertoire_name
    
    with patch('opening_fenix.core.services.repertoire_service.delete_repertoire_db') as mock_del:
        mock_del.return_value = (True, "Deleted")
        success, msg = complex_repertoire.delete_repertoire(repo_name)
        assert success is True
        assert complex_repertoire.active_repertoire_name is None

from unittest.mock import patch
