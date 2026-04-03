import pytest
import json
from unittest.mock import MagicMock, patch
import chess
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.db.models import LichessData, Position

@pytest.fixture
def mock_backend(mock_user_dir):
    """Fixture for CreatorBackend with a mocked session."""
    with patch("opening_fenix.creator.creator_window.DatabaseManager"):
        backend = CreatorBackend()
        backend.session = MagicMock()
        return backend

def test_get_lichess_common_moves_keys(mock_backend):
    """Test that get_lichess_common_moves uses correct keys (white/black)."""
    # 1. Setup mock data in DB style (as saved by lichess_service.py)
    # { "e2e4": { "white": 30, "draws": 40, "black": 30, "total": 100 } }
    moves_data = {
        "e2e4": {
            "white": 30,
            "draws": 40,
            "black": 30,
            "total": 100
        }
    }
    
    mock_lichess_data = MagicMock(spec=LichessData)
    mock_lichess_data.moves_json = json.dumps(moves_data)
    mock_lichess_data.fen = chess.STARTING_FEN
    
    # Mock the query return value
    mock_backend.session.query(LichessData).filter_by().first.return_value = mock_lichess_data
    
    # 2. Call the method
    results = mock_backend.get_lichess_common_moves(chess.STARTING_FEN, "high")
    
    # 3. Assertions
    assert len(results) == 1
    res = results[0]
    assert res['uci'] == "e2e4"
    assert res['san'] == "e4"
    assert res['white_pct'] == 30.0
    assert res['draw_pct'] == 40.0
    assert res['black_pct'] == 30.0
    assert res['total'] == 100

def test_get_lichess_common_moves_missing_keys_fallback(mock_backend):
    """Test fallback to total calculation if total key is missing but white/black are correct."""
    moves_data = {
        "d2d4": {
            "white": 50,
            "draws": 20,
            "black": 30
            # 'total' is missing
        }
    }
    
    mock_lichess_data = MagicMock(spec=LichessData)
    mock_lichess_data.moves_json = json.dumps(moves_data)
    
    mock_backend.session.query(LichessData).filter_by().first.return_value = mock_lichess_data
    
    results = mock_backend.get_lichess_common_moves(chess.STARTING_FEN, "high")
    
    assert len(results) == 1
    res = results[0]
    assert res['total'] == 100
    assert res['white_pct'] == 50.0
    assert res['draw_pct'] == 20.0
    assert res['black_pct'] == 30.0
