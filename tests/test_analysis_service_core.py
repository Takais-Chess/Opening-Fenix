import os
import json
import pytest
from unittest.mock import MagicMock, patch
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path
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
    db_path = get_repertoire_db_path(sample_repertoire)
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
    from opening_fenix.core.utils import get_repertoire_db_path
    db_path = get_repertoire_db_path(sample_repertoire)
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
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    from opening_fenix.core.services.lichess_service import LichessData
    data = session.query(LichessData).first()
    assert data is not None
    assert "e2e4" in data.moves_json
    session.close()
    db.close()

@patch("chess.engine.SimpleEngine.popen_uci")
def test_run_db_analysis_with_cancel(mock_popen, mock_user_dir, sample_repertoire):
    mock_popen.return_value = MagicMock()
    # Mock cancel becoming True immediately
    check_cancel = lambda: True
    success, msg = run_db_analysis(sample_repertoire, "dummy", depth=10, threads=1, check_cancel=check_cancel)
    assert success is False
    assert "abgebrochen" in msg

@patch("chess.engine.SimpleEngine.popen_uci")
def test_run_db_analysis_engine_error(mock_popen, mock_user_dir, sample_repertoire):
    mock_popen.side_effect = Exception("Engine crash")
    success, msg = run_db_analysis(sample_repertoire, "dummy", depth=10, threads=1)
    assert success is False
    assert "Fehler bei der Analyse: Engine crash" in msg

def test_enrich_position_already_exists(mock_user_dir, sample_repertoire):
    # Setup Lichess data already in DB
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    from opening_fenix.core.db.models import LichessData
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    session.add(LichessData(fen=" ".join(e4_fen.split()[:4]), elo_range="1800", moves_json="{}"))
    session.commit()
    session.close()
    
    # Run enrich_position - should skip Lichess but might run engine if configured
    success, msg = enrich_position(sample_repertoire, e4_fen, "1800", engine_path=None, depth=10)
    assert success is True
    assert "complete" in msg


@patch("os.path.exists")
@patch("chess.engine.SimpleEngine.popen_uci")
def test_enrich_position_engine_only(mock_popen, mock_exists, mock_user_dir, sample_repertoire):
    mock_exists.return_value = True
    mock_engine = MagicMock()
    mock_popen.return_value = mock_engine
    
    # Mocking result
    mock_info = {"pv": [], "score": MagicMock(white=lambda: MagicMock(score=lambda x: 0))}
    mock_engine.analyse.return_value = [mock_info]
    # Options check
    mock_engine.options = ["MultiPV"]
    
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    # Set elo_category=None to skip Lichess
    success, msg = enrich_position(sample_repertoire, f"{fen} 0 1", elo_category=None, engine_path="dummy")
    
    assert success is True
    assert mock_popen.called

def test_order_positions_topologically_bfs(mock_user_dir, sample_repertoire):
    from opening_fenix.core.services.analysis_service import order_positions_topologically

    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # Clear existing moves/positions for a clean test
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.query(Position).delete()

    # Create root and branch positions
    p_root = Position(id=1, fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    p_e4 = Position(id=2, fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    p_d4 = Position(id=3, fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1")
    p_e5 = Position(id=4, fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2")
    p_orphan = Position(id=5, fen="8/8/8/8/8/8/8/4K2k w - - 0 50")

    session.add_all([p_root, p_e4, p_d4, p_e5, p_orphan])
    session.flush()

    # Moves: root -> e4, root -> d4, e4 -> e5
    m1 = Move(id=1, from_position_id=1, to_position_id=2, uci="e2e4", san="e4")
    m2 = Move(id=2, from_position_id=1, to_position_id=3, uci="d2d4", san="d4")
    m3 = Move(id=3, from_position_id=2, to_position_id=4, uci="e7e5", san="e5")
    session.add_all([m1, m2, m3])
    session.commit()

    # Pass in reversed / jumbled order
    jumbled = [p_orphan, p_e5, p_d4, p_e4, p_root]
    ordered = order_positions_topologically(session, jumbled)

    ordered_ids = [p.id for p in ordered]
    # Root (1) must be first
    assert ordered_ids[0] == 1
    # Depth 1 positions (2 and 3) must come before Depth 2 position (4)
    assert set(ordered_ids[1:3]) == {2, 3}
    assert ordered_ids[3] == 4
    # Orphan (5) must come last
    assert ordered_ids[4] == 5

    # Trivial cases (<= 1 elements)
    assert order_positions_topologically(session, []) == []
    assert order_positions_topologically(session, [p_root]) == [p_root]

    session.close()
    db.close()


