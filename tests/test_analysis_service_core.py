import os
import json
import pytest
from unittest.mock import MagicMock, patch
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.services.analysis_service import (
    get_repertoire_analysis_status, run_db_analysis, enrich_position
)

def test_get_repertoire_analysis_status_not_found(mock_user_dir):
    status = get_repertoire_analysis_status("NonExistent")
    assert status == "Repertoire nicht gefunden"

def test_get_repertoire_analysis_status_no_positions(mock_user_dir, sample_repertoire):
    # To get "Keine Spielerzüge", we need a color that has NO positions in the DB.
    # If we mock get_meta to return "x", total_positions will be 0.
    with patch("opening_fenix.core.services.analysis_service.get_meta", return_value="x"):
        status = get_repertoire_analysis_status(sample_repertoire)
        assert status == "Keine Spielerzüge"

def test_get_repertoire_analysis_status_depths(mock_user_dir, sample_repertoire):
    db_path = os.path.join(mock_user_dir, "repertoires", f"{sample_repertoire}.db")
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Set depth for some positions
    pos1 = session.query(Position).first()
    pos1.analysis_depth = 12
    session.commit()
    session.close()
    db.close()
    
    with patch("opening_fenix.core.services.analysis_service.get_meta", return_value="w"):
        status = get_repertoire_analysis_status(sample_repertoire)
        assert "Teilweise analysiert" in status or "Tiefe: 12" in status
        # Since only 1 of 2 positions is analyzed, it should be "Teilweise analysiert"
        # Wait, how many white positions are there? 
        # start_fen (w), e5_fen (w) -> 2 white positions.
        assert status == "Teilweise analysiert"

@patch("chess.engine.SimpleEngine.popen_uci")
def test_run_db_analysis_basic(mock_popen, mock_user_dir, sample_repertoire):
    # Setup mock engine
    mock_engine = MagicMock()
    mock_popen.return_value = mock_engine
    
    # Mock analysis result
    mock_info = {"pv": [MagicMock(uci=lambda: "e2e4")], "score": MagicMock(white=lambda: MagicMock(score=lambda mate_score: 100))}
    mock_engine.analyse.return_value = [mock_info]
    
    success, msg = run_db_analysis(sample_repertoire, "dummy_path", depth=10, threads=1)
    
    assert success is True
    assert "abgeschlossen" in msg
    
    # Verify DB was updated
    db_path = os.path.join(mock_user_dir, "repertoires", f"{sample_repertoire}.db")
    db = DatabaseManager(db_path)
    session = db.get_session()
    pos = session.query(Position).filter(Position.analysis_depth == 10).first()
    assert pos is not None
    assert "e2e4" in pos.good_moves
    session.close()
    db.close()

@patch("urllib.request.urlopen")
def test_enrich_position_lichess(mock_urlopen, mock_user_dir, sample_repertoire):
    # Mock Lichess API response
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "moves": [{"uci": "e2e4", "wins": 100, "draws": 50, "black": 50}]
    }).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response
    
    # Use e4_fen (b), which is opponent turn if user is "w"
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    
    # We need to mock get_meta for user color
    with patch("opening_fenix.core.services.analysis_service.get_meta", return_value="w"):
        success, msg = enrich_position(sample_repertoire, e4_fen, "1800", None, depth=10)
        
    assert success is True
    assert "complete" in msg
    
    # Check LichessData was added
    db_path = os.path.join(mock_user_dir, "repertoires", f"{sample_repertoire}.db")
    db = DatabaseManager(db_path)
    session = db.get_session()
    from opening_fenix.core.services.lichess_service import LichessData
    data = session.query(LichessData).first()
    assert data is not None
    assert "e2e4" in data.moves_json
    session.close()
    db.close()
