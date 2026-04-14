import pytest
import json
import os
from unittest.mock import MagicMock, patch
import urllib.error
from urllib.error import HTTPError
from opening_fenix.core.services.lichess_service import (
    run_lichess_import,
    verify_lichess_token,
    delete_lichess_data,
    run_lichess_import_and_calculate_scores
)
from opening_fenix.core.db.models import Position, LichessData

@pytest.fixture
def mock_urlopen():
    with patch("urllib.request.urlopen") as mock:
        yield mock

def test_verify_lichess_token_success(mock_urlopen):
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"username": "testuser"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    success, msg = verify_lichess_token("fake-token")
    assert success is True
    assert "testuser" in msg

def test_verify_lichess_token_error(mock_urlopen):
    # Mock 401 Unauthorized
    mock_urlopen.side_effect = HTTPError("url", 401, "Unauthorized", {}, None)
    
    success, msg = verify_lichess_token("bad-token")
    assert success is False
    assert "401" in msg

def test_run_lichess_import_success(mock_user_dir, sample_repertoire, mock_urlopen):
    # Setup some positions in the demo DB
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path
    
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # We already have 3 positions from the sample_repertoire fixture
    # Let's mock a successful Lichess response for one FEN
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "moves": [{"uci": "e2e4", "white": 100, "draws": 50, "black": 30}]
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    # Run the import (mocking time.sleep and _update_lichess_delay_config to speed up tests)
    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        success, msg = run_lichess_import(sample_repertoire, "high")
        
    assert success is True
    # Check if data was saved
    data_count = session.query(LichessData).count()
    assert data_count > 0
    session.close()
    db.close()

def test_run_lichess_import_rate_limit(mock_user_dir, sample_repertoire, mock_urlopen):
    # Mock 429 error
    responses = [
        HTTPError("url", 429, "Too Many Requests", {}, None),
        MagicMock() # Second try success (after "waiting")
    ]
    mock_urlopen.side_effect = responses
    # We need to set up the second try to return something
    responses[1].__enter__.return_value.read.return_value = json.dumps({"moves": []}).encode("utf-8")
    
    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        # We only expect it to try once and skip or retry depending on implementation
        # The current implementation retries once if it hits 429.
        success, msg = run_lichess_import(sample_repertoire, "high")
        
    assert success is True # Should complete eventually or skip

def test_delete_lichess_data(mock_user_dir, sample_repertoire):
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Add dummy data
    session.add(LichessData(fen="fen1", elo_range="mid", moves_json="{}"))
    session.commit()
    
    success, msg = delete_lichess_data(sample_repertoire, "mid")
    assert success is True
    assert session.query(LichessData).filter_by(elo_range="mid").count() == 0
    session.close()
    db.close()

def test_run_lichess_import_and_calculate_scores_success(mock_user_dir, sample_repertoire):
    with patch("opening_fenix.core.services.lichess_service.run_lichess_import") as mock_import, \
         patch("opening_fenix.core.services.priority_service.calculate_priority_scores") as mock_stats:
        
        mock_import.return_value = (True, "Import OK")
        mock_stats.return_value = (True, "Priority OK")
        
        success, msg = run_lichess_import_and_calculate_scores(sample_repertoire, "high")
        assert success is True
        assert mock_import.called
        assert mock_stats.called

def test_run_lichess_import_cancel(mock_user_dir, sample_repertoire, mock_urlopen):
    # Mock cancel appearing after second position
    cancel_calls = [False, False, True]
    def check_cancel():
        return cancel_calls.pop(0) if cancel_calls else True
    
    mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({"moves": []}).encode("utf-8")
    
    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        success, msg = run_lichess_import(sample_repertoire, "high", check_cancel=check_cancel)
        
    assert success is False
    assert "abgebrochen" in msg

def test_run_lichess_import_masters(mock_user_dir, sample_repertoire, mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"moves": []}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response
    
    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        success, msg = run_lichess_import(sample_repertoire, "masters")
        
    assert success is True
    # Verify URL used 'masters'
    url = mock_urlopen.call_args[0][0].full_url
    assert "lichess.org/masters" in url

def test_run_lichess_import_401_error(mock_user_dir, sample_repertoire, mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
    
    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        success, msg = run_lichess_import(sample_repertoire, "high")
        
    assert success is False
    assert "401" in msg

def test_verify_lichess_token_network_error(mock_urlopen):
    mock_urlopen.side_effect = Exception("Network down")
    success, msg = verify_lichess_token("some-token")
    assert success is False
    assert "Netzwerkfehler" in msg

