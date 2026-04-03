from opening_fenix.core.utils import get_repertoire_db_path
import pytest
import json
import io
import urllib.request
from unittest.mock import MagicMock, patch
import opening_fenix.core.data_tools as dt
from opening_fenix.core.data_tools import run_lichess_import, calculate_priority_scores
from opening_fenix.core.models import LichessData, Move, Position, RepertoireMove
import chess

@pytest.fixture
def mock_lichess_response():
    def _mock(data):
        response = MagicMock()
        response.read.return_value = json.dumps(data).encode('utf-8')
        response.__enter__.return_value = response
        return response
    return _mock

def test_run_lichess_import(mock_user_dir, sample_repertoire, mock_lichess_response):
    # Prepare mock data for explorer.lichess.org
    mock_data = {
        "moves": [
            {"uci": "e7e5", "white": 100, "draws": 50, "black": 50},
            {"uci": "c7c5", "white": 80, "draws": 40, "black": 80}
        ]
    }
    
    with patch('urllib.request.urlopen', return_value=mock_lichess_response(mock_data)):
        # We need an opponent turn position in the DB for it to be queried
        # sample_repertoire usually adds 1. e4, so FEN after 1. e4 is an opponent turn (Black)
        success, msg = run_lichess_import(sample_repertoire, "mid")
        assert success is True
        
    # Check if data was saved to DB
    from opening_fenix.core.models import DatabaseManager
    import os
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    data = session.query(LichessData).filter_by(fen=e4_fen, elo_range="mid").first()
    assert data is not None
    moves_json = json.loads(data.moves_json)
    assert "e7e5" in moves_json
    assert moves_json["e7e5"]["total"] == 200

def test_calculate_priority_scores(mock_user_dir, sample_repertoire):
    # Setup: 1. e4 is in repertoire. We add Lichess data for 1. e4
    from opening_fenix.core.models import DatabaseManager
    import os
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    # 1... e5 (50%), 1... c5 (50%)
    moves_dict = {
        "e7e5": {"total": 100, "wins": 50, "draws": 25, "losses": 25},
        "c7c5": {"total": 100, "wins": 50, "draws": 25, "losses": 25}
    }
    lichess_entry = LichessData(fen=e4_fen, elo_range="mid", moves_json=json.dumps(moves_dict))
    session.add(lichess_entry)
    
    # Add 1... e5 and 1... c5 to repertoire so they get scores
    # (sample_repertoire only has 1. e4 by default usually)
    # Let's check what sample_repertoire actually has. 
    # From test_repertoire.py it seems it has 1. e4
    
    # Add moves to repertoire
    from opening_fenix.core.data_tools import normalize_fen
    board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    
    def add_rep_move(from_f, uci, san):
        p = session.query(Position).filter_by(fen=from_f).first()
        if not p:
            p = Position(fen=from_f); session.add(p); session.flush()
        
        b = chess.Board(from_f)
        b.push_uci(uci)
        to_f = dt.normalize_fen(b)
        tp = session.query(Position).filter_by(fen=to_f).first()
        if not tp:
            tp = Position(fen=to_f); session.add(tp); session.flush()
            
        m = session.query(Move).filter_by(from_position_id=p.id, uci=uci).first()
        if not m:
            m = Move(from_position_id=p.id, to_position_id=tp.id, uci=uci, san=san)
            session.add(m); session.flush()
        
        rm = session.query(RepertoireMove).filter_by(move_id=m.id).first()
        if not rm:
            rm = RepertoireMove(move_id=m.id, level=1)
            session.add(rm)
        
    add_rep_move(e4_fen, "e7e5", "e5")
    add_rep_move(e4_fen, "c7c5", "c5")
    session.commit()
    
    # Run calculation
    success, msg = calculate_priority_scores(sample_repertoire, "mid")
    assert success is True
    
    # Check scores
    # 1. e4 should have 1.0 (start move)
    e4_move = session.query(Move).filter_by(uci="e2e4").first()
    assert e4_move.priority_score == 1.0
    
    # 1... e5 should have 0.5 (50% of 1.0)
    e5_move = session.query(Move).filter_by(uci="e7e5").first()
    assert e5_move.priority_score == 0.5
    
    # 1... c5 should have 0.5 (50% of 1.0)
    c5_move = session.query(Move).filter_by(uci="c7c5").first()
    assert c5_move.priority_score == 0.5
