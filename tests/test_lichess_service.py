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

def test_delete_all_lichess_data(mock_user_dir, sample_repertoire):
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Add dummy data with multiple elo ranges
    session.add(LichessData(fen="fen1", elo_range="low", moves_json="{}"))
    session.add(LichessData(fen="fen2", elo_range="high", moves_json="{}"))
    session.commit()
    
    success, msg = delete_lichess_data(sample_repertoire, None)
    assert success is True
    assert session.query(LichessData).count() == 0
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


def test_run_lichess_import_duplicate_collision(mock_user_dir, sample_repertoire, mock_urlopen):
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path
    from opening_fenix.core.db.models import Position, LichessData
    
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Get a FEN that will be queried
    pos = session.query(Position).first()
    assert pos is not None
    
    # Define a side effect that inserts the LichessData into the database
    # simulating a concurrent background enrichment
    def side_effect(*args, **kwargs):
        # We need a separate session to commit the concurrent insert
        side_db = DatabaseManager(db_path)
        side_session = side_db.get_session()
        try:
            # Only insert if not already present
            if not side_session.query(LichessData).filter_by(fen=pos.fen, elo_range="high").first():
                side_session.add(LichessData(
                    fen=pos.fen,
                    elo_range="high",
                    moves_json='{"e2e4": {"white": 10, "draws": 5, "black": 5, "total": 20}}'
                ))
                side_session.commit()
        finally:
            side_session.close()
            side_db.close()
            
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "moves": [{"uci": "e2e4", "white": 100, "draws": 50, "black": 30}]
        }).encode("utf-8")
        return mock_response.__enter__.return_value

    mock_urlopen.side_effect = side_effect
    
    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        success, msg = run_lichess_import(sample_repertoire, "high")
        
    assert success is True
    # The import should have skipped or handled the collision without throwing an IntegrityError
    # Check that we have exactly 1 record in LichessData for this FEN and elo_range
    count = session.query(LichessData).filter_by(fen=pos.fen, elo_range="high").count()
    assert count == 1
    session.close()
    db.close()


def test_run_lichess_import_progress_callback_no_eta(mock_user_dir, sample_repertoire, mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "moves": [{"uci": "e2e4", "white": 100, "draws": 50, "black": 30}]
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    captured_progress = []
    def progress_cb(*args):
        captured_progress.append(args)

    with patch("time.sleep"), patch("opening_fenix.core.services.lichess_service._update_lichess_delay_config"):
        success, msg = run_lichess_import(sample_repertoire, "high", progress_callback=progress_cb)

    assert success is True
    assert len(captured_progress) > 0
    # Verify each progress call passes (pct, cur, total) with 3 elements without eta string
    for call in captured_progress:
        assert len(call) == 3
        pct, cur, total = call
        assert isinstance(pct, int)
        assert isinstance(cur, int)
        assert isinstance(total, int)


def test_compute_position_bfs_depths(mock_user_dir, sample_repertoire):
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path
    from opening_fenix.core.services.lichess_service import compute_position_bfs_depths
    
    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()
    try:
        depths = compute_position_bfs_depths(session)
        assert len(depths) > 0
        # Starting position has depth 0
        min_depth = min(depths.values())
        assert min_depth == 0
    finally:
        session.close()
        db.close()


def test_run_lichess_import_and_calculate_scores_on_cancel(mock_user_dir, sample_repertoire):
    with patch("opening_fenix.core.services.lichess_service.run_lichess_import") as mock_import, \
         patch("opening_fenix.core.services.priority_service.calculate_priority_scores") as mock_stats:
        
        mock_import.return_value = (False, "Import abgebrochen.")
        mock_stats.return_value = (True, "Priority OK")
        
        success, msg = run_lichess_import_and_calculate_scores(sample_repertoire, "high")
        assert success is False
        assert "abgebrochen" in msg
        # Must still have called calculate_priority_scores
        assert mock_stats.called


def test_adaptive_sliding_window_limiter():
    from opening_fenix.core.services.lichess_service import AdaptiveSlidingWindowLimiter
    
    # 1. Token limiter defaults
    limiter = AdaptiveSlidingWindowLimiter(has_token=True)
    assert limiter.target_rpm == 30.0
    assert limiter.min_rpm == 20.0
    assert limiter.max_rpm == 80.0

    # 2. Non-token limiter defaults
    anon_limiter = AdaptiveSlidingWindowLimiter(has_token=False)
    assert anon_limiter.target_rpm == 20.0
    assert anon_limiter.min_rpm == 15.0
    assert anon_limiter.max_rpm == 30.0

    # 3. Dynamic RPM adaptation on low latency
    for _ in range(25):
        limiter.record_success(0.04)
    assert limiter.target_rpm == 31.0

    # 4. Dynamic RPM adaptation on latency spike
    limiter.record_success(0.450)
    assert limiter.target_rpm == 28.0

    # 5. Multiplicative backoff on 429
    limiter.record_429()
    assert limiter.target_rpm == 20.0  # Hit min_rpm floor

    # 6. Cancellation test in wait_for_slot
    cancelled = limiter.wait_for_slot(check_cancel=lambda: True)
    assert cancelled is True


def test_batched_best_first_priority_ordering(tmp_path):
    """
    Verifies that high-priority deep positions (mainlines) are prioritized
    over low-priority shallow positions (rare sidelines) across batches.
    """
    from opening_fenix.core.db.models import Position, Move, LichessData
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.services.lichess_service import run_lichess_import

    db_file = tmp_path / "best_first_test.db"
    db_m = DatabaseManager(str(db_file))
    session = db_m.get_session()

    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    fen_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    fen_a4 = "rnbqkbnr/pppppppp/8/8/P7/8/1PPPPPPP/RNBQKBNR b KQkq - 0 1"
    fen_e4_e5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    fen_a4_e5 = "rnbqkbnr/pppp1ppp/8/4p3/P7/8/1PPPPPPP/RNBQKBNR w KQkq - 0 2"

    p_root = Position(fen=start_fen)
    p_e4 = Position(fen=fen_e4)
    p_a4 = Position(fen=fen_a4)
    p_e4_e5 = Position(fen=fen_e4_e5)
    p_a4_e5 = Position(fen=fen_a4_e5)
    session.add_all([p_root, p_e4, p_a4, p_e4_e5, p_a4_e5])
    session.commit()

    m_e4 = Move(from_position_id=p_root.id, to_position_id=p_e4.id, uci="e2e4", san="e4")
    m_a4 = Move(from_position_id=p_root.id, to_position_id=p_a4.id, uci="a2a4", san="a4")
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e4_e5.id, uci="e7e5", san="e5")
    m_a4_e5 = Move(from_position_id=p_a4.id, to_position_id=p_a4_e5.id, uci="e7e5", san="e5")
    session.add_all([m_e4, m_a4, m_e5, m_a4_e5])
    session.commit()

    # Pre-populate root with 10,000 games for e4 and only 10 games for a4
    session.add(LichessData(
        fen=p_root.fen,
        elo_range="high",
        moves_json=json.dumps({
            "e2e4": {"total": 10000, "white": 4000, "draws": 3000, "black": 3000},
            "a2a4": {"total": 10, "white": 2, "draws": 3, "black": 5}
        })
    ))
    from opening_fenix.core.db.meta_utils import set_meta
    set_meta(session, "color", "b")
    session.commit()
    session.close()
    db_m.close()

    queried_fens = []
    def mock_get(url, headers):
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        fen_requested = params.get('fen', [''])[0]
        queried_fens.append(fen_requested)
        # When p_e4 is requested, return strong continuation (e5 has 8,000 games)
        if "4P3" in fen_requested:
            return json.dumps({
                "moves": [{"uci": "e7e5", "white": 3000, "draws": 2000, "black": 3000}]
            }).encode("utf-8")
        return json.dumps({"moves": []}).encode("utf-8")

    with patch("opening_fenix.core.services.lichess_service.get_repertoire_db_path", return_value=str(db_file)), \
         patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", side_effect=mock_get), \
         patch("opening_fenix.core.services.lichess_service.AdaptiveSlidingWindowLimiter.wait_for_slot", return_value=False), \
         patch("time.sleep"):

        # Run import with batch_size=1 to observe dynamic re-prioritization between batches
        success, msg = run_lichess_import("test_prio_repo", "high", batch_size=1)
        assert success is True

    # 1. First batch queries the highest priority depth 1 move: 1. e4 (10,000 games vs 1. a4's 10 games)
    assert queried_fens[0] == fen_e4

    # 2. Second batch re-estimates probabilities: 1. e4 e5 (ply 2 mainline) now has ~0.999 probability,
    # whereas 1. a4 (ply 1 sideline) only has ~0.001 probability.
    # Therefore, the mainline ply 2 move is fetched BEFORE the sideline ply 1 move!
    assert queried_fens[1] == fen_e4_e5

    # 3. Sideline 1. a4 is fetched only after the high priority line
    assert fen_a4 in queried_fens
    assert queried_fens.index(fen_a4) > queried_fens.index(fen_e4_e5)






