import time
from unittest.mock import patch
from opening_fenix.core.services.lichess_service import run_lichess_import, compute_position_bfs_depths
from opening_fenix.core.db.models import Position
from opening_fenix.core.db.database import DatabaseManager

def test_progress_callback_throttled(tmp_path):
    """Verifies that progress callbacks are throttled to avoid flooding the Qt main event loop."""
    db_file = tmp_path / "test_repo.db"
    db_m = DatabaseManager(str(db_file))
    session = db_m.get_session()

    # Create 30 dummy positions
    for idx in range(30):
        pos = Position(fen=f"8/8/8/8/8/8/8/{idx}K1k w - - 0 1")
        session.add(pos)
    session.commit()
    session.close()
    db_m.close()

    emitted_progress = []
    def on_progress(pct, *args):
        emitted_progress.append((pct, args, time.time()))

    mock_resp = b'{"moves": []}'
    with patch("opening_fenix.core.services.lichess_service.get_repertoire_db_path", return_value=str(db_file)):
        with patch("opening_fenix.core.services.lichess_service.LichessConnectionManager.get", return_value=mock_resp):
            with patch("opening_fenix.core.services.lichess_service.AdaptiveSlidingWindowLimiter.wait_for_slot", return_value=False):
                success, msg = run_lichess_import("test_repo", "high", progress_callback=on_progress)
                assert success is True

    # With 30 positions executed fast under mock, throttling should ensure fewer calls than 30
    # First position (i=1) and last position (i=30) must be included
    assert len(emitted_progress) >= 2
    assert len(emitted_progress) < 30  # Throttled compared to 30 unthrottled calls
    first_call = emitted_progress[0]
    last_call = emitted_progress[-1]
    # First call must be for item 1
    assert first_call[1][0] == 1
    # Last call must be for item 30 (100%)
    assert last_call[0] == 100
    assert last_call[1][0] == 30

def test_compute_position_bfs_depths_with_yield(tmp_path):
    """Verifies BFS traversal works accurately with GIL yielding."""
    db_file = tmp_path / "test_bfs.db"
    db_m = DatabaseManager(str(db_file))
    session = db_m.get_session()

    p1 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    session.add(p1)
    session.commit()

    depths = compute_position_bfs_depths(session)
    assert p1.id in depths
    assert depths[p1.id] == 0

    session.close()
    db_m.close()
