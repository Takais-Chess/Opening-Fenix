import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Tuple, List, Dict, Optional
from PyQt6.QtCore import QThread, pyqtSignal

from opening_fenix.core.logger import logger

_CACHED_TOKEN_USERNAME: Optional[str] = None
_CACHED_TOKEN: Optional[str] = None


def resolve_token_username(token: str) -> Optional[str]:
    """
    Resolves the Lichess username associated with an API token.
    Caches the result in memory to avoid redundant network calls.
    """
    global _CACHED_TOKEN_USERNAME, _CACHED_TOKEN
    if not token or token == "YOUR_TOKEN_HERE":
        return None
    
    if _CACHED_TOKEN == token and _CACHED_TOKEN_USERNAME:
        return _CACHED_TOKEN_USERNAME

    url = "https://lichess.org/api/account"
    headers = {
        "User-Agent": "OpeningFenix/1.0 (Python urllib)",
        "Authorization": f"Bearer {token.strip()}"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            username = data.get("username")
            if username:
                _CACHED_TOKEN = token
                _CACHED_TOKEN_USERNAME = username
                logger.info(f"Resolved Lichess account from token: {username}")
                return username
    except Exception as e:
        logger.warning(f"Failed to resolve Lichess account username from token: {e}")
        return None

    return None


def check_players_in_game(
    usernames: List[str], 
    token: Optional[str] = None
) -> Tuple[bool, List[str], Dict[str, str]]:
    """
    Queries Lichess API for the given usernames to determine if any of them
    are currently playing a live game.
    
    Returns:
        (is_any_playing, list_of_playing_usernames, dict_of_username_to_game_id)
    """
    clean_usernames = [u.strip() for u in usernames if u and u.strip()]
    if not clean_usernames:
        return False, [], {}

    ids_param = ",".join([urllib.parse.quote(u) for u in clean_usernames])
    url = f"https://lichess.org/api/users/status?ids={ids_param}&withGameIds=true"
    
    headers = {
        "User-Agent": "OpeningFenix/1.0 (Python urllib)"
    }
    if token and token != "YOUR_TOKEN_HERE":
        headers["Authorization"] = f"Bearer {token.strip()}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            playing_users: List[str] = []
            game_ids: Dict[str, str] = {}
            
            for item in data:
                if item.get("playing") is True:
                    uname = item.get("name") or item.get("id")
                    playing_users.append(uname)
                    if "playingId" in item:
                        game_ids[uname] = item["playingId"]
            
            is_any_playing = len(playing_users) > 0
            return is_any_playing, playing_users, game_ids

    except urllib.error.HTTPError as e:
        logger.warning(f"Lichess status check HTTP error {e.code}: {e.reason}")
        raise
    except Exception as e:
        logger.warning(f"Lichess status check error: {e}")
        raise


def get_monitored_usernames(config: dict) -> List[str]:
    """
    Determines all usernames that should be monitored based on user configuration.
    Includes token-associated account if enabled, and any manually entered usernames.
    """
    usernames: List[str] = []
    
    use_token = config.get("lichess_lockout_use_token", True)
    token = config.get("lichess_token", "")
    if use_token and token:
        token_uname = resolve_token_username(token)
        if token_uname and token_uname not in usernames:
            usernames.append(token_uname)

    raw_names = config.get("lichess_lockout_usernames", "")
    if raw_names:
        if isinstance(raw_names, str):
            for part in raw_names.split(","):
                p = part.strip()
                if p and p.lower() not in [u.lower() for u in usernames]:
                    usernames.append(p)
        elif isinstance(raw_names, list):
            for p in raw_names:
                p_str = str(p).strip()
                if p_str and p_str.lower() not in [u.lower() for u in usernames]:
                    usernames.append(p_str)

    return usernames


class LichessLockoutWorker(QThread):
    """
    Background worker thread to perform the Lichess status check asynchronously
    without blocking the Qt main GUI thread.
    """
    check_completed = pyqtSignal(bool, list,
                                dict, str)
    check_failed = pyqtSignal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = dict(config)

    def run(self):
        try:
            if not self.config.get("lichess_lockout_enabled", False):
                self.check_completed.emit(False, [], {}, "Feature is disabled.")
                return

            usernames = get_monitored_usernames(self.config)
            if not usernames:
                self.check_completed.emit(False, [], {}, "No usernames configured to monitor.")
                return

            token = self.config.get("lichess_token")
            is_playing, playing_users, game_ids = check_players_in_game(usernames, token=token)
            
            if is_playing:
                msg = f"In game: {', '.join(playing_users)}"
            else:
                msg = "No live games detected."

            self.check_completed.emit(is_playing, playing_users, game_ids, msg)

        except Exception as e:
            self.check_failed.emit(str(e))
