import pytest
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from PyQt6.QtWidgets import QApplication

from opening_fenix.core.services.lichess_lockout_service import (
    resolve_token_username,
    check_players_in_game,
    get_monitored_usernames,
    LichessLockoutWorker
)
from opening_fenix.gui.widgets.lichess_lockout_overlay import (
    HoldProgressButton,
    LichessLockoutOverlay
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_resolve_token_username_cached():
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"username": "GrandmasterX"}).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        # First call hits API
        name1 = resolve_token_username("token_abc_123")
        assert name1 == "GrandmasterX"
        assert mock_url.call_count == 1

        # Second call uses cache
        name2 = resolve_token_username("token_abc_123")
        assert name2 == "GrandmasterX"
        assert mock_url.call_count == 1


def test_resolve_token_username_invalid():
    assert resolve_token_username("") is None
    assert resolve_token_username("YOUR_TOKEN_HERE") is None


def test_check_players_in_game_none_playing():
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {"id": "player1", "name": "Player1", "playing": False},
            {"id": "player2", "name": "Player2", "playing": False}
        ]).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        is_playing, playing_users, game_ids = check_players_in_game(["Player1", "Player2"])
        assert is_playing is False
        assert len(playing_users) == 0
        assert len(game_ids) == 0


def test_check_players_in_game_active():
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {"id": "player1", "name": "Player1", "playing": True, "playingId": "liveGame777"},
            {"id": "player2", "name": "Player2", "playing": False}
        ]).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        is_playing, playing_users, game_ids = check_players_in_game(["Player1", "Player2"])
        assert is_playing is True
        assert "Player1" in playing_users
        assert game_ids.get("Player1") == "liveGame777"


def test_check_players_in_game_empty():
    is_playing, playing_users, game_ids = check_players_in_game([])
    assert is_playing is False
    assert playing_users == []
    assert game_ids == {}


def test_get_monitored_usernames():
    with patch("opening_fenix.core.services.lichess_lockout_service.resolve_token_username", return_value="TokenUser"):
        config = {
            "lichess_lockout_use_token": True,
            "lichess_token": "valid_token",
            "lichess_lockout_usernames": "Opponent1, Opponent2, TokenUser"
        }
        names = get_monitored_usernames(config)
        assert "TokenUser" in names
        assert "Opponent1" in names
        assert "Opponent2" in names
        # Check deduplication
        assert names.count("TokenUser") == 1


def test_lichess_lockout_worker_disabled():
    worker = LichessLockoutWorker({"lichess_lockout_enabled": False})
    results = []
    worker.check_completed.connect(lambda is_p, users, gids, msg: results.append((is_p, users)))
    worker.run()
    assert len(results) == 1
    assert results[0][0] is False


def test_hold_progress_button(qapp):
    import time
    btn = HoldProgressButton(text="Test Button", hold_duration_sec=1.0)
    completed = []
    btn.hold_completed.connect(lambda: completed.append(True))

    # Simulate press that exceeds hold duration
    btn.press_start_time = time.time() - 2.0
    btn._on_timer_tick()

    assert len(completed) == 1
    assert btn.progress == 0.0


def test_lockout_overlay_lifecycle(qapp):
    overlay = LichessLockoutOverlay()
    assert not overlay.isVisible()

    overlay.show_lockout(["PlayerX"], {"PlayerX": "game999"})
    assert overlay.isVisible()
    assert "PlayerX" in overlay.lbl_desc.text()
    assert overlay.btn_open_game.isVisible()

    overlay.unlock()
    assert not overlay.isVisible()
