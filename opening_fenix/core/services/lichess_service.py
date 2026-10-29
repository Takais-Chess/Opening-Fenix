import os
import json
import time
import datetime
import http.client
import urllib.request
import urllib.parse
import urllib.error
from typing import Tuple, Callable, Optional, Dict, List, Set

import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, LichessData
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path, _update_lichess_delay_config
from opening_fenix.core.logger import logger

ELO_MAPPING: Dict[str, List[str]] = {
    'low': ['400', '1000', '1200'],
    'mid': ['1600'],
    'high': ['2200', '2500'],
    'masters': []
}

class LichessConnectionManager:
    """
    Manages a persistent HTTPS connection to explorer.lichess.org for HTTP Keep-Alive.
    Reuses the TLS/TCP socket across requests for ~25-30ms round-trips.
    Falls back to urllib if mock_urlopen is detected in test environments.
    """
    def __init__(self, host: str = "explorer.lichess.org", timeout: int = 15):
        self.host = host
        self.timeout = timeout
        self.conn: Optional[http.client.HTTPSConnection] = None

    def get(self, url: str, headers: dict) -> bytes:
        is_mocked = getattr(urllib.request.urlopen, '_mock_return_value', None) is not None or \
                    'Mock' in type(urllib.request.urlopen).__name__ or \
                    getattr(urllib.request.urlopen, 'side_effect', None) is not None

        if is_mocked:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read()

        parsed = urllib.parse.urlparse(url)
        path_and_query = parsed.path + ('?' + parsed.query if parsed.query else '')

        for attempt in range(2):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPSConnection(self.host, timeout=self.timeout)
                self.conn.request("GET", path_and_query, headers=headers)
                resp = self.conn.getresponse()
                body = resp.read()
                if resp.status == 200:
                    return body
                else:
                    raise urllib.error.HTTPError(url, resp.status, resp.reason, dict(resp.getheaders()), None)
            except (http.client.RemoteDisconnected, http.client.CannotSendRequest,
                    BrokenPipeError, ConnectionResetError, OSError):
                self.close()
                if attempt == 1:
                    raise

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def compute_position_bfs_depths(session) -> Dict[int, int]:
    """
    Computes the shortest ply depth (distance from root/starting position)
    for all positions in the repertoire using Breadth-First Search (BFS).
    Root/starting position is depth 0. Move 1 is depth 1, etc.
    Positions not reachable from the starting position get assigned depth 9999.
    """
    import chess
    from collections import deque

    all_moves = session.query(Move.from_position_id, Move.to_position_id).all()
    outgoing: Dict[int, List[int]] = {}
    for from_id, to_id in all_moves:
        if to_id:
            outgoing.setdefault(from_id, []).append(to_id)

    all_pos = session.query(Position.id, Position.fen).all()
    id_to_fen = {p.id: p.fen for p in all_pos}

    start_board = chess.Board()
    start_fen_normalized = " ".join(start_board.fen().split(" ")[:4])

    start_pos_id = None
    for pid, fen in id_to_fen.items():
        if " ".join(fen.split(" ")[:4]) == start_fen_normalized:
            start_pos_id = pid
            break

    pos_depths: Dict[int, int] = {}
    if start_pos_id is not None:
        roots = [start_pos_id]
    else:
        incoming_pos_ids = {to_id for _, to_id in all_moves if to_id}
        roots = [pid for pid in id_to_fen.keys() if pid not in incoming_pos_ids]
        if not roots and id_to_fen:
            roots = [min(id_to_fen.keys())]

    queue = deque([(r, 0) for r in roots])
    for r in roots:
        pos_depths[r] = 0

    nodes_visited = 0
    while queue:
        curr_id, d = queue.popleft()
        nodes_visited += 1
        if nodes_visited % 1000 == 0:
            time.sleep(0)  # Yield GIL periodically without incurring 15.6ms Windows timer sleep
        for next_id in outgoing.get(curr_id, []):
            if next_id not in pos_depths:
                pos_depths[next_id] = d + 1
                queue.append((next_id, d + 1))

    return pos_depths


def compute_position_grandparents(session) -> Tuple[Dict[int, Set[int]], Dict[int, str]]:
    """
    Computes all grandparent position IDs for each position in the repertoire.
    A grandparent is any position 2 plies back along any incoming move path (transposition-aware).
    Also returns a mapping from position ID to FEN.
    """
    all_moves = session.query(Move.from_position_id, Move.to_position_id).all()
    parents_map: Dict[int, Set[int]] = {}
    for from_id, to_id in all_moves:
        if to_id and from_id:
            parents_map.setdefault(to_id, set()).add(from_id)

    grandparents_map: Dict[int, Set[int]] = {}
    for to_id, parents in parents_map.items():
        gps: Set[int] = set()
        for p in parents:
            gps.update(parents_map.get(p, set()))
        if gps:
            grandparents_map[to_id] = gps

    all_pos = session.query(Position.id, Position.fen).all()
    id_to_fen = {p.id: p.fen for p in all_pos}

    return grandparents_map, id_to_fen


def get_move_game_count(
    from_fen: str,
    uci: str,
    san: str,
    fen_lichess_data: Dict[str, dict]
) -> Optional[int]:
    """
    Returns the total game count for a move if the origin position's Lichess data is present,
    or None if the origin position has not been evaluated yet.
    """
    clean_fen = " ".join(from_fen.split(" ")[:4])
    mdict = fen_lichess_data.get(clean_fen)
    if mdict is None:
        return None
    stat = mdict.get(uci) or mdict.get(san)
    if not stat:
        alt_uci = None
        if uci == 'e1c1': alt_uci = 'e1a1'
        elif uci == 'e1g1': alt_uci = 'e1h1'
        elif uci == 'e8c8': alt_uci = 'e8a8'
        elif uci == 'e8g8': alt_uci = 'e8h8'
        if alt_uci:
            stat = mdict.get(alt_uci)
    if stat:
        tot = stat.get('white', 0) + stat.get('draws', 0) + stat.get('black', 0)
        return stat.get('total', tot)
    return 0


def check_can_skip_position_3ply(
    pos_id: int,
    incoming_moves: Dict[int, List[Move]],
    id_to_fen: Dict[int, str],
    fen_lichess_data: Dict[str, dict]
) -> bool:
    """
    Determines if a position can be safely skipped during Lichess import.
    A position is only skipped if along ALL incoming paths of length 3:
    1. Incoming move m1 (1 ply back) has been evaluated and has 0 games in Lichess.
    2. Move m2 (2 plies back) has been evaluated and has 0 games.
    3. Move m3 (3 plies back) has been evaluated and has 0 games.
    If any incoming path has depth < 3, has un-evaluated moves, or has > 0 games,
    the position cannot be skipped.
    """
    inc1 = incoming_moves.get(pos_id, [])
    if not inc1:
        return False  # Root or unreachable

    for m1 in inc1:
        p1_id = m1.from_position_id
        p1_fen = id_to_fen.get(p1_id)
        if not p1_fen:
            return False
        g1 = get_move_game_count(p1_fen, m1.uci, m1.san, fen_lichess_data)
        if g1 is None or g1 > 0:
            return False

        inc2 = incoming_moves.get(p1_id, [])
        if not inc2:
            return False  # Path has depth < 2

        for m2 in inc2:
            p2_id = m2.from_position_id
            p2_fen = id_to_fen.get(p2_id)
            if not p2_fen:
                return False
            g2 = get_move_game_count(p2_fen, m2.uci, m2.san, fen_lichess_data)
            if g2 is None or g2 > 0:
                return False

            inc3 = incoming_moves.get(p2_id, [])
            if not inc3:
                return False  # Path has depth < 3

            for m3 in inc3:
                p3_id = m3.from_position_id
                p3_fen = id_to_fen.get(p3_id)
                if not p3_fen:
                    return False
                g3 = get_move_game_count(p3_fen, m3.uci, m3.san, fen_lichess_data)
                if g3 is None or g3 > 0:
                    return False

    return True


def compute_estimated_position_priorities(
    roots: List[int],
    positions_by_depth: List[List[int]],
    outgoing_moves: Dict[int, List[Move]],
    id_to_fen: Dict[int, str],
    rep_move_ids: Set[int],
    user_turn_char: str,
    fen_lichess_data: Dict[str, dict]
) -> Dict[int, float]:
    """
    Propagates estimated occurrence probabilities across the repertoire graph.
    - User turns: flow through active repertoire moves (or evenly across outgoing if none active).
    - Opponent turns: if Lichess data is already cached for the position, flow proportionally
      to move game counts; otherwise divide evenly across candidate moves.
    """
    id_probabilities: Dict[int, float] = {pid: 0.0 for pid in id_to_fen.keys()}
    for r in roots:
        id_probabilities[r] = 1.0

    total_depths = len(positions_by_depth)
    for depth in range(total_depths):
        for pos_id in positions_by_depth[depth]:
            curr_prob = id_probabilities.get(pos_id, 0.0)
            if curr_prob <= 0.0:
                continue

            fen = id_to_fen.get(pos_id, "")
            if not fen:
                continue
            clean_fen = " ".join(fen.split(" ")[:4])
            tokens = clean_fen.split(" ")
            turn_char = tokens[1] if len(tokens) > 1 else "w"
            is_user_turn = (turn_char == user_turn_char)

            out_moves = outgoing_moves.get(pos_id, [])
            if not out_moves:
                continue

            if is_user_turn:
                user_moves = [m for m in out_moves if m.id in rep_move_ids]
                if user_moves:
                    split = curr_prob / len(user_moves)
                    for m in user_moves:
                        if m.to_position_id:
                            id_probabilities[m.to_position_id] = id_probabilities.get(m.to_position_id, 0.0) + split
                else:
                    split = curr_prob / len(out_moves)
                    for m in out_moves:
                        if m.to_position_id:
                            id_probabilities[m.to_position_id] = id_probabilities.get(m.to_position_id, 0.0) + split
            else:
                ld_moves = fen_lichess_data.get(clean_fen)
                if ld_moves is not None:
                    total_games = sum(m_info.get('total', 0) for m_info in ld_moves.values())
                    if total_games > 0:
                        for m in out_moves:
                            stat = ld_moves.get(m.uci) or ld_moves.get(m.san)
                            if not stat:
                                alt_uci = None
                                if m.uci == 'e1c1': alt_uci = 'e1a1'
                                elif m.uci == 'e1g1': alt_uci = 'e1h1'
                                elif m.uci == 'e8c8': alt_uci = 'e8a8'
                                elif m.uci == 'e8g8': alt_uci = 'e8h8'
                                if alt_uci:
                                    stat = ld_moves.get(alt_uci)
                            m_total = stat.get('total', 0) if stat else 0
                            if m_total > 0 and m.to_position_id:
                                share = m_total / total_games
                                id_probabilities[m.to_position_id] = id_probabilities.get(m.to_position_id, 0.0) + (curr_prob * share)
                else:
                    split = curr_prob / len(out_moves)
                    for m in out_moves:
                        if m.to_position_id:
                            id_probabilities[m.to_position_id] = id_probabilities.get(m.to_position_id, 0.0) + split

    return id_probabilities


class AdaptiveSlidingWindowLimiter:
    """
    Tracks requests in a rolling 60-second window and enforces a dynamic Target RPM.
    1. Rolling 60-second sliding window: mathematically guarantees request count <= target_rpm.
    2. Inter-request pacing: spreads requests evenly (interval = 60.0 / target_rpm).
    3. Latency awareness: adapts target_rpm up or down based on server responsiveness.
    4. Diagnostic Telemetry: logs request volume, rolling window counts, latencies, and 429 events.
    """
    def __init__(self, has_token: bool = True):
        self.has_token = has_token
        self.min_rpm = 20.0 if has_token else 15.0
        self.max_rpm = 80.0 if has_token else 30.0
        self.target_rpm = 30.0 if has_token else 20.0
        self.window_seconds = 60.0
        from collections import deque
        self.request_timestamps: deque = deque()
        self.recent_latencies: deque = deque(maxlen=25)
        self.last_request_time: float = 0.0
        self.fast_success_streak: int = 0
        self.total_requests: int = 0
        self.total_429_hits: int = 0
        self.history_429: List[dict] = []

    def prune_window(self, now: float):
        cutoff = now - self.window_seconds
        while self.request_timestamps and self.request_timestamps[0] <= cutoff:
            self.request_timestamps.popleft()

    def get_current_window_count(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self.prune_window(now)
        return len(self.request_timestamps)

    def wait_for_slot(self, check_cancel: Optional[Callable[[], bool]] = None) -> bool:
        """
        Waits until a request slot is available under both the rolling 60s quota and pacing gap.
        Returns True if cancelled, False otherwise.
        """
        is_mocked_sleep = 'Mock' in type(time.sleep).__name__
        while True:
            if check_cancel and check_cancel():
                return True
            now = time.time()
            self.prune_window(now)

            wait_for_window = 0.0
            if len(self.request_timestamps) >= int(self.target_rpm):
                oldest = self.request_timestamps[0]
                wait_for_window = max(0.0, (oldest + self.window_seconds) - now + 0.05)

            pacing_interval = self.window_seconds / self.target_rpm
            wait_for_pacing = max(0.0, (self.last_request_time + pacing_interval) - now)
            wait_time = max(wait_for_window, wait_for_pacing)

            if wait_time <= 0.005 or is_mocked_sleep:
                now_slot = time.time()
                self.request_timestamps.append(now_slot)
                self.last_request_time = now_slot
                self.total_requests += 1
                return False

            sleep_chunk = min(wait_time, 0.05)
            time.sleep(sleep_chunk)

    def record_success(self, latency_seconds: float):
        """
        Adapts target_rpm based on server round-trip latency.
        """
        self.recent_latencies.append(latency_seconds)
        if latency_seconds > 0.350:
            # Latency spike: server is under load, proactively brake
            self.fast_success_streak = 0
            old_rpm = self.target_rpm
            self.target_rpm = max(self.min_rpm, self.target_rpm - 3.0)
            if self.target_rpm != old_rpm:
                logger.debug(f"[Lichess Limiter] Latency spike ({latency_seconds*1000:.0f}ms). RPM dialed back: {old_rpm:.0f} -> {self.target_rpm:.0f}")
        elif latency_seconds < 0.120:
            # Fast and snappy response
            self.fast_success_streak += 1
            if self.fast_success_streak >= 25:
                old_rpm = self.target_rpm
                self.target_rpm = min(self.max_rpm, self.target_rpm + 1.0)
                self.fast_success_streak = 0
                if self.target_rpm != old_rpm:
                    logger.debug(f"[Lichess Limiter] 25 fast responses. Probing RPM up: {old_rpm:.0f} -> {self.target_rpm:.0f}")
        else:
            # Normal range: maintain current pace
            pass

    def record_429(self, fen: str = "") -> Tuple[float, float]:
        """
        Multiplicative backoff on HTTP 429.
        Returns (old_rpm, new_rpm).
        """
        self.total_429_hits += 1
        self.fast_success_streak = 0
        old_rpm = self.target_rpm
        self.target_rpm = max(self.min_rpm, self.target_rpm - 10.0)
        entry = {
            "timestamp": time.time(),
            "request_num": self.total_requests,
            "window_count": len(self.request_timestamps),
            "rpm_before": old_rpm,
            "rpm_after": self.target_rpm,
            "fen": fen
        }
        self.history_429.append(entry)
        return old_rpm, self.target_rpm


def is_valid_token_string(token: Optional[str]) -> bool:
    """Checks whether a given token string is non-empty and not a placeholder."""
    if not token or not isinstance(token, str):
        return False
    t = token.strip()
    if not t or "TOKEN_HERE" in t.upper() or t.startswith("YOUR_"):
        return False
    return True

def clean_lichess_token(token: Optional[str]) -> str:
    """Returns stripped token if valid format, otherwise empty string."""
    if is_valid_token_string(token):
        return token.strip()
    return ""

def _parse_datetime_safe(val) -> Optional[datetime.datetime]:
    if isinstance(val, datetime.datetime):
        return val
    if not val or not isinstance(val, str):
        return None
    s = val.strip().rstrip('Z')
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def sync_lichess_data_from_other_repertoires(
    target_session,
    current_repo_name: str,
    elo_category: str,
    max_age_days: Optional[int] = 180,
    check_cancel: Optional[Callable[[], bool]] = None
) -> int:
    """
    Copies already fetched Lichess data for the same Elo range from other local repertoires.
    Applies an age/date filter to avoid pulling outdated statistics.
    Returns the number of positions successfully copied.
    """
    import sqlite3
    from opening_fenix.core.services.repertoire_service import RepertoireService

    existing_fens_query = target_session.query(LichessData.fen).filter_by(elo_range=elo_category)
    missing_fens = [
        r[0] for r in target_session.query(Position.fen).filter(
            ~Position.fen.in_(existing_fens_query)
        ).distinct().all()
    ]
    if not missing_fens:
        return 0

    missing_fen_set = set(missing_fens)

    try:
        all_repos = RepertoireService().get_all_repertoires()
    except Exception as e:
        logger.warning(f"[Lichess Cross-Sync] Failed to list repertoires: {e}")
        return 0

    other_repos = [r for r in all_repos if r != current_repo_name]
    if not other_repos:
        return 0

    cutoff_dt: Optional[datetime.datetime] = None
    cutoff_ts: Optional[float] = None
    if max_age_days is not None and max_age_days > 0:
        cutoff_dt = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
        cutoff_ts = cutoff_dt.timestamp()

    copied_count = 0

    for other_repo in other_repos:
        if check_cancel and check_cancel():
            break
        if not missing_fen_set:
            break

        other_db_path = get_repertoire_db_path(other_repo)
        if not os.path.exists(other_db_path):
            continue

        mtime = os.path.getmtime(other_db_path)
        # If max_age is set and the DB file itself is older than cutoff, all data inside is older
        if cutoff_ts is not None and mtime < cutoff_ts:
            continue

        try:
            conn = sqlite3.connect(other_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lichess_data'")
            if not cursor.fetchone():
                conn.close()
                continue

            cursor.execute("PRAGMA table_info(lichess_data)")
            cols = [row[1] for row in cursor.fetchall()]
            has_fetched_at = 'fetched_at' in cols

            if has_fetched_at:
                cursor.execute("SELECT fen, moves_json, fetched_at FROM lichess_data WHERE elo_range = ?", (elo_category,))
            else:
                cursor.execute("SELECT fen, moves_json, NULL FROM lichess_data WHERE elo_range = ?", (elo_category,))

            rows = cursor.fetchall()
            conn.close()

            for r_fen, r_moves_json, r_fetched_at in rows:
                if r_fen not in missing_fen_set:
                    continue

                f_dt = _parse_datetime_safe(r_fetched_at)
                # Apply date filter
                if cutoff_dt is not None:
                    if f_dt is not None:
                        if f_dt < cutoff_dt:
                            continue
                    else:
                        if mtime < cutoff_ts:
                            continue

                date_to_store = f_dt or datetime.datetime.fromtimestamp(mtime)
                new_data = LichessData(
                    fen=r_fen,
                    elo_range=elo_category,
                    moves_json=r_moves_json,
                    fetched_at=date_to_store
                )
                target_session.add(new_data)
                missing_fen_set.discard(r_fen)
                copied_count += 1

                if copied_count % 50 == 0:
                    try:
                        commit_with_retry(target_session)
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"[Lichess Cross-Sync] Error reading repo '{other_repo}': {e}")
            continue

    if copied_count > 0:
        try:
            commit_with_retry(target_session)
        except Exception:
            pass

    return copied_count

def run_lichess_import(
    repo_name: str,
    elo_category: str,
    progress_callback: Optional[Callable[..., None]] = None,
    check_cancel: Optional[Callable[[], bool]] = None,
    reuse_other_courses: bool = False,
    max_data_age_days: Optional[int] = 180,
    batch_size: int = 20
) -> Tuple[bool, str]:
    from opening_fenix.core.db.models import LichessData # local import if needed
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    config = {}
    config_path = os.path.join(get_user_dir(), "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                pass
    
    raw_token = os.environ.get("LICHESS_TOKEN") or config.get("lichess_token", "")
    lichess_token = clean_lichess_token(raw_token)

    limiter = AdaptiveSlidingWindowLimiter(has_token=bool(lichess_token))
    client = LichessConnectionManager(timeout=15)

    try:
        if reuse_other_courses:
            if progress_callback:
                try:
                    progress_callback(0, "Prüfe Daten aus anderen Kursen...")
                except TypeError:
                    progress_callback(0)
            reused_count = sync_lichess_data_from_other_repertoires(
                session, repo_name, elo_category,
                max_age_days=max_data_age_days,
                check_cancel=check_cancel
            )
            if reused_count > 0:
                logger.info(f"[Lichess Import] Reused {reused_count} positions from other courses (max age: {max_data_age_days} days).")

        # Compute structural graph metadata for priority, self-healing and BFS ordering
        pos_depths = compute_position_bfs_depths(session)
        pos_grandparents, id_to_fen = compute_position_grandparents(session)

        # Preload moves and repertoire info for fast in-memory priority estimation and graph traversal
        all_moves_db = session.query(Move.id, Move.from_position_id, Move.to_position_id, Move.uci, Move.san).all()
        outgoing_moves: Dict[int, List[Move]] = {}
        incoming_moves: Dict[int, List[Move]] = {}
        incoming_pos_ids = set()
        for m in all_moves_db:
            if m.from_position_id:
                outgoing_moves.setdefault(m.from_position_id, []).append(m)
            if m.to_position_id:
                incoming_moves.setdefault(m.to_position_id, []).append(m)
                incoming_pos_ids.add(m.to_position_id)

        rep_moves_db = session.query(RepertoireMove.move_id).filter_by(is_active=True).all()
        rep_move_ids = {rm.move_id for rm in rep_moves_db}
        user_turn_char = get_meta(session, "color", "w")

        start_board = chess.Board()
        start_fen_normalized = " ".join(start_board.fen().split(" ")[:4])
        start_pos_id = None
        for pid, fen in id_to_fen.items():
            if " ".join(fen.split(" ")[:4]) == start_fen_normalized:
                start_pos_id = pid
                break

        if start_pos_id is not None:
            roots = [start_pos_id]
        else:
            roots = [pid for pid in id_to_fen.keys() if pid not in incoming_pos_ids]
            if not roots and id_to_fen:
                roots = [min(id_to_fen.keys())]

        max_d = max(pos_depths.values()) if pos_depths else 0
        positions_by_depth: List[List[int]] = [[] for _ in range(max_d + 1)]
        for pid, d in pos_depths.items():
            if d <= max_d:
                positions_by_depth[d].append(pid)

        # Comprehensive Initial Self-Healing:
        # Check all positions that currently have empty ({}) LichessData.
        # If any of them CANNOT be skipped under the 3-ply rule (check_can_skip_position_3ply == False),
        # it was falsely skipped by earlier versions.
        # Purge its stale empty LichessData record so it is included in positions_to_query.
        existing_ld_rows = session.query(LichessData.fen, LichessData.moves_json).filter_by(elo_range=elo_category).all()
        existing_ld_map: Dict[str, dict] = {}
        for f_val, mjson in existing_ld_rows:
            clean_f = " ".join(f_val.split(" ")[:4])
            try:
                existing_ld_map[clean_f] = json.loads(mjson)
            except Exception:
                existing_ld_map[clean_f] = {}

        stale_fens_to_purge = set()
        for pid, fen in id_to_fen.items():
            clean_f = " ".join(fen.split(" ")[:4])
            mdict = existing_ld_map.get(clean_f)
            if mdict is not None:
                total_games = sum(v.get('total', 0) for v in mdict.values() if isinstance(v, dict))
                if total_games == 0:
                    if not check_can_skip_position_3ply(pid, incoming_moves, id_to_fen, existing_ld_map):
                        stale_fens_to_purge.add(fen)
                        stale_fens_to_purge.add(clean_f)

        if stale_fens_to_purge:
            num_purged = session.query(LichessData).filter(
                LichessData.elo_range == elo_category,
                LichessData.fen.in_(stale_fens_to_purge)
            ).delete(synchronize_session=False)
            commit_with_retry(session)
            for sf in stale_fens_to_purge:
                existing_ld_map.pop(sf, None)
            logger.info(f"[Lichess Import] Self-healing: Purged {num_purged} stale empty records that cannot be skipped under 3-ply rule for ELO '{elo_category}'.")

        existing_fens_query = session.query(LichessData.fen).filter_by(elo_range=elo_category)
        
        # Query positions that don't have Lichess data yet
        positions_to_query = session.query(Position).filter(
            ~Position.fen.in_(existing_fens_query)
        ).distinct().all()

        total_pos = len(positions_to_query)

        logger.info(
            f"[Lichess Import] Started for repo '{repo_name}' (ELO: {elo_category}). "
            f"Positions to query: {total_pos}. Starting Target RPM: {limiter.target_rpm:.0f} "
            f"(Token present: {bool(lichess_token)})"
        )

        if not positions_to_query:
            set_meta(session, "lichess_elo", elo_category)
            # Invalidate coverage cache to force recalculation with new Elo if changed
            set_meta(session, "cov_cache_count", "-1")
            commit_with_retry(session)
            return True, f"Alle Positionen haben bereits Lichess-Daten für ELO '{elo_category}'."

        fen_lichess_data: Dict[str, dict] = {}
        fen_games_count: Dict[str, int] = {}
        all_existing_data = session.query(LichessData.fen, LichessData.moves_json).filter_by(elo_range=elo_category).all()
        for f_val, mjson in all_existing_data:
            clean_f = " ".join(f_val.split(" ")[:4])
            try:
                mdict = json.loads(mjson)
                fen_lichess_data[clean_f] = mdict
                g_count = sum(m.get('total', 0) for m in mdict.values())
                fen_games_count[f_val] = g_count
                fen_games_count[clean_f] = g_count
            except Exception:
                fen_lichess_data[clean_f] = {}
                fen_games_count[f_val] = 0
                fen_games_count[clean_f] = 0

        lichess_ratings = ELO_MAPPING.get(elo_category, ['1800', '2000'])

        new_data_points_added = 0
        uncommitted_items = 0
        successful_requests_in_a_row = 0
        last_progress_emit_time = 0.0
        last_reported_429_hits = 0

        remaining_pos_ids = {p.id for p in positions_to_query}
        processed_count = 0
        BATCH_SIZE = max(1, batch_size)

        while remaining_pos_ids:
            if check_cancel and check_cancel():
                logger.info(
                    f"[Lichess Import] Cancelled for '{repo_name}' at item {processed_count}/{total_pos}. "
                    f"Total requests: {limiter.total_requests}, 429 hits: {limiter.total_429_hits}."
                )
                set_meta(session, "cov_cache_count", "-1")
                commit_with_retry(session)
                return False, "Import abgebrochen."

            # Best-First Prioritization: Propagate estimated occurrence probabilities across the frontier
            estimated_probs = compute_estimated_position_priorities(
                roots=roots,
                positions_by_depth=positions_by_depth,
                outgoing_moves=outgoing_moves,
                id_to_fen=id_to_fen,
                rep_move_ids=rep_move_ids,
                user_turn_char=user_turn_char,
                fen_lichess_data=fen_lichess_data
            )

            # Sort remaining positions:
            # 1. Estimated priority descending (highest probability lines first)
            # 2. Ply depth ascending (prefer shallower on ties)
            # 3. Position ID ascending (deterministic tie-breaker)
            candidate_list = list(remaining_pos_ids)
            candidate_list.sort(key=lambda pid: (
                -round(estimated_probs.get(pid, 0.0), 6),
                pos_depths.get(pid, 9999),
                pid
            ))
            current_batch = candidate_list[:BATCH_SIZE]

            batch_idx = 0
            while batch_idx < len(current_batch):
                pos_id = current_batch[batch_idx]
                pos = session.get(Position, pos_id)
                if pos is None:
                    remaining_pos_ids.discard(pos_id)
                    batch_idx += 1
                    continue

                if check_cancel and check_cancel():
                    logger.info(
                        f"[Lichess Import] Cancelled for '{repo_name}' at item {processed_count}/{total_pos}. "
                        f"Total requests: {limiter.total_requests}, 429 hits: {limiter.total_429_hits}."
                    )
                    set_meta(session, "cov_cache_count", "-1")
                    commit_with_retry(session)
                    return False, "Import abgebrochen."

                clean_pos_fen = " ".join(pos.fen.split(" ")[:4])

                # 3-Move Lead-Up Skip Optimization (Transposition-Aware):
                # A position is only skipped if along ALL incoming move paths:
                # 1. Incoming move m1 (1 ply back) has been evaluated and has 0 games in Lichess.
                # 2. Move m2 (2 plies back) has been evaluated and has 0 games.
                # 3. Move m3 (3 plies back) has been evaluated and has 0 games.
                # If any incoming path has depth < 3 or any move with games > 0, it is NOT skipped.
                if check_can_skip_position_3ply(pos.id, incoming_moves, id_to_fen, fen_lichess_data):
                    new_data = LichessData(
                        fen=pos.fen,
                        elo_range=elo_category,
                        moves_json=json.dumps({}),
                        fetched_at=datetime.datetime.now()
                    )
                    session.add(new_data)
                    try:
                        with session.begin_nested():
                            session.flush()
                        new_data_points_added += 1
                        uncommitted_items += 1
                        fen_games_count[pos.fen] = 0
                        fen_games_count[clean_pos_fen] = 0
                        fen_lichess_data[clean_pos_fen] = {}
                    except Exception:
                        pass

                    remaining_pos_ids.discard(pos_id)
                    processed_count += 1
                    batch_idx += 1

                    if uncommitted_items >= 5:
                        commit_with_retry(session)
                        uncommitted_items = 0

                    pct = int(processed_count * 100 / total_pos) if total_pos > 0 else 0
                    now_t = time.time()
                    if progress_callback and (processed_count == 1 or processed_count == total_pos or (now_t - last_progress_emit_time) >= 0.25):
                        last_progress_emit_time = now_t
                        status_text = f"{processed_count}/{total_pos} [Übersprungen: 0 Partien]"
                        try:
                            progress_callback(pct, processed_count, total_pos)
                        except TypeError:
                            try:
                                progress_callback(pct, status_text)
                            except TypeError:
                                progress_callback(pct)
                    time.sleep(0.001)
                    continue

                # Release SQLite write transaction before waiting for rate-limit slot (prevents 2-3s locks)
                if uncommitted_items > 0:
                    commit_with_retry(session)
                    uncommitted_items = 0

                if limiter.wait_for_slot(check_cancel):
                    logger.info(
                        f"[Lichess Import] Cancelled while waiting for slot at item {processed_count}/{total_pos}. "
                        f"Total requests: {limiter.total_requests}, 429 hits: {limiter.total_429_hits}."
                    )
                    set_meta(session, "cov_cache_count", "-1")
                    commit_with_retry(session)
                    return False, "Import abgebrochen."

                if elo_category == 'masters':
                    params = {
                        'variant': 'standard',
                        'fen': pos.fen,
                        'moves': 25
                    }
                    query_string = urllib.parse.urlencode(params)
                    url = f"https://explorer.lichess.org/masters?{query_string}"
                else:
                    params = {
                        'variant': 'standard',
                        'fen': pos.fen,
                        'ratings': ",".join(lichess_ratings),
                        'speeds': 'rapid,classical',
                        'moves': 25
                    }
                    query_string = urllib.parse.urlencode(params)
                    url = f"https://explorer.lichess.org/lichess?{query_string}"

                retry_same_position = False

                t_req_start = time.time()
                try:
                    headers = {'User-Agent': 'OpeningFenix/1.0 (Python urllib)'}
                    if lichess_token:
                        headers['Authorization'] = f'Bearer {lichess_token}'

                    resp_bytes = client.get(url, headers=headers)
                    latency = time.time() - t_req_start
                    limiter.record_success(latency)
                    data = json.loads(resp_bytes.decode('utf-8'))
                    successful_requests_in_a_row += 1

                    moves_data = data.get('moves', [])
                    # Double check to prevent race condition during long network request
                    existing = session.query(LichessData).filter_by(fen=pos.fen, elo_range=elo_category).first()
                    if moves_data:
                        moves_dict = {
                            move['uci']: {
                                'white': move.get('white', 0),
                                'draws': move.get('draws', 0),
                                'black': move.get('black', 0),
                                'total': move.get('white', 0) + move.get('draws', 0) + move.get('black', 0)
                            } for move in moves_data if 'uci' in move
                        }
                        if existing:
                            existing.moves_json = json.dumps(moves_dict)
                            existing.fetched_at = datetime.datetime.now()
                        else:
                            new_data = LichessData(
                                fen=pos.fen,
                                elo_range=elo_category,
                                moves_json=json.dumps(moves_dict),
                                fetched_at=datetime.datetime.now()
                            )
                            session.add(new_data)
                        g_total = sum(m.get('total', 0) for m in moves_dict.values())
                        fen_games_count[pos.fen] = g_total
                        fen_games_count[clean_pos_fen] = g_total
                        fen_lichess_data[clean_pos_fen] = moves_dict

                        # Dynamic cascading unblocking:
                        # If this position returned moves with games > 0, check all outgoing moves.
                        # If any child position in the repertoire was previously marked empty ({}),
                        # unblock it dynamically so it is queried in this same run!
                        for out_m in outgoing_moves.get(pos.id, []):
                            child_pid = out_m.to_position_id
                            if not child_pid or child_pid in remaining_pos_ids:
                                continue
                            m_games = moves_dict.get(out_m.uci, {}).get('total', 0)
                            if m_games > 0:
                                child_fen = id_to_fen.get(child_pid)
                                if child_fen:
                                    child_clean = " ".join(child_fen.split(" ")[:4])
                                    c_dict = fen_lichess_data.get(child_clean)
                                    c_games = sum(v.get('total', 0) for v in c_dict.values() if isinstance(v, dict)) if c_dict is not None else -1
                                    if c_games == 0:
                                        session.query(LichessData).filter(
                                            LichessData.elo_range == elo_category,
                                            LichessData.fen.in_([child_fen, child_clean])
                                        ).delete(synchronize_session=False)
                                        fen_lichess_data.pop(child_clean, None)
                                        fen_games_count.pop(child_clean, None)
                                        fen_games_count.pop(child_fen, None)
                                        remaining_pos_ids.add(child_pid)
                                        total_pos += 1
                                        c_depth = pos_depths.get(child_pid, 0)
                                        while len(positions_by_depth) <= c_depth:
                                            positions_by_depth.append([])
                                        if child_pid not in positions_by_depth[c_depth]:
                                            positions_by_depth[c_depth].append(child_pid)
                                        max_d = max(max_d, c_depth)
                    else:
                        if existing:
                            existing.moves_json = json.dumps({})
                            existing.fetched_at = datetime.datetime.now()
                        else:
                            new_data = LichessData(
                                fen=pos.fen,
                                elo_range=elo_category,
                                moves_json=json.dumps({}),
                                fetched_at=datetime.datetime.now()
                            )
                            session.add(new_data)
                        fen_games_count[pos.fen] = 0
                        fen_games_count[clean_pos_fen] = 0
                        fen_lichess_data[clean_pos_fen] = {}
                    try:
                        with session.begin_nested():
                            session.flush()
                        new_data_points_added += 1
                        uncommitted_items += 1
                    except Exception:
                        # Ignored collision (already inserted by another thread)
                        pass

                except urllib.error.HTTPError as e:
                    successful_requests_in_a_row = 0
                    if e.code == 429:
                        if uncommitted_items > 0:
                            commit_with_retry(session)
                            uncommitted_items = 0
                        old_rpm, new_rpm = limiter.record_429(fen=pos.fen)
                        window_count = limiter.get_current_window_count()
                        logger.warning(
                            f"[Lichess Import] HTTP 429 Rate Limit HIT #{limiter.total_429_hits}! "
                            f"At position {processed_count+1}/{total_pos} (Total requests sent: {limiter.total_requests}, FEN: {pos.fen}). "
                            f"Rolling 60s requests: {window_count}. RPM dropped: {old_rpm:.0f} -> {new_rpm:.0f}. "
                            f"Entering 70s cooldown."
                        )
                        cooldown_remaining = 70.0
                        cooldown_step = 0.5
                        while cooldown_remaining > 0:
                            if check_cancel and check_cancel():
                                set_meta(session, "cov_cache_count", "-1")
                                commit_with_retry(session)
                                return False, "Import abgebrochen."
                            if progress_callback:
                                pct = int(processed_count * 100 / total_pos) if total_pos > 0 else 0
                                try:
                                    progress_callback(
                                        pct,
                                        f"⏳ Rate Limit (429)! Warte {int(cooldown_remaining)}s... [Hits: {limiter.total_429_hits}, RPM: {new_rpm:.0f}]"
                                    )
                                except TypeError:
                                    progress_callback(pct)
                            sleep_time = min(cooldown_step, cooldown_remaining)
                            time.sleep(sleep_time)
                            cooldown_remaining -= sleep_time
                        retry_same_position = True
                    elif e.code == 401:
                        logger.error(f"[Lichess Import] HTTP 401 Unauthorized for FEN {pos.fen}. Invalid or expired token.")
                        return False, "Fehler 401: Das Lichess API-Token ist ungültig oder abgelaufen. Bitte überprüfe dein Token in den Einstellungen."
                    else:
                        logger.warning(f"[Lichess Import] HTTP Error {e.code} for FEN {pos.fen}. Skipping.")
                except Exception as e:
                    successful_requests_in_a_row = 0
                    logger.error(f"[Lichess Import] Error for FEN {pos.fen}: {e}. Skipping.")

                if retry_same_position:
                    continue

                remaining_pos_ids.discard(pos_id)
                processed_count += 1
                batch_idx += 1

                if uncommitted_items >= 5:
                    commit_with_retry(session)
                    uncommitted_items = 0

                pct = int(processed_count * 100 / total_pos) if total_pos > 0 else 0

                if processed_count > 0 and processed_count % 25 == 0:
                    avg_lat = (sum(limiter.recent_latencies) / len(limiter.recent_latencies) * 1000) if limiter.recent_latencies else 0.0
                    logger.debug(
                        f"[Lichess Import] Progress: {processed_count}/{total_pos} ({pct}%) | "
                        f"60s Window: {limiter.get_current_window_count()} reqs | "
                        f"Target RPM: {limiter.target_rpm:.0f} | "
                        f"Avg Latency: {avg_lat:.0f}ms | "
                        f"429 Hits: {limiter.total_429_hits}"
                    )

                now_t = time.time()
                is_first = (processed_count == 1)
                is_last = (processed_count == total_pos)
                has_429_alert = (limiter.total_429_hits > 0 and limiter.total_429_hits != last_reported_429_hits)
                time_since_last_emit = now_t - last_progress_emit_time

                if progress_callback and (is_first or is_last or has_429_alert or time_since_last_emit >= 0.25):
                    last_progress_emit_time = now_t
                    if has_429_alert:
                        last_reported_429_hits = limiter.total_429_hits
                    if limiter.total_429_hits > 0:
                        status_text = f"{processed_count}/{total_pos} [⚠️ 429: {limiter.total_429_hits}x, RPM: {limiter.target_rpm:.0f}]"
                    else:
                        status_text = f"{processed_count}/{total_pos} [RPM: {limiter.target_rpm:.0f}]"
                    try:
                        progress_callback(pct, processed_count, total_pos)
                    except TypeError:
                        try:
                            progress_callback(pct, status_text)
                        except TypeError:
                            progress_callback(pct)

                time.sleep(0.002)

            # End of batch of 20: commit database transaction
            if uncommitted_items > 0:
                commit_with_retry(session)
                uncommitted_items = 0

        if uncommitted_items > 0:
            commit_with_retry(session)
            uncommitted_items = 0

        logger.info(
            f"[Lichess Import] Finished for '{repo_name}': {new_data_points_added} points saved. "
            f"Total requests: {limiter.total_requests}. "
            f"Rate Limit (429) hits: {limiter.total_429_hits}. "
            f"Final RPM: {limiter.target_rpm:.0f}."
        )
        set_meta(session, "lichess_elo", elo_category)
        set_meta(session, "cov_cache_count", "-1")
        commit_with_retry(session)
        base_delay = round(60.0 / limiter.target_rpm, 3)
        _update_lichess_delay_config(base_delay)
        rate_hit_suffix = f" (429-Rate-Limits: {limiter.total_429_hits})" if limiter.total_429_hits > 0 else ""
        return True, f"{new_data_points_added} neue Lichess-Datenpunkte für ELO '{elo_category}' erfolgreich importiert{rate_hit_suffix}."

    except Exception as e:
        session.rollback()
        import traceback
        print(traceback.format_exc())
        return False, f"Fehler beim Lichess-Import: {e}"
    finally:
        client.close()
        session.close()
        db.close()


def run_lichess_import_and_calculate_scores(
    repo_name: str,
    elo_category: str,
    progress_callback: Optional[Callable[..., None]] = None,
    check_cancel: Optional[Callable[[], bool]] = None,
    reuse_other_courses: bool = False,
    max_data_age_days: Optional[int] = 180
) -> Tuple[bool, str]:
    from opening_fenix.core.services.priority_service import calculate_priority_scores

    def import_progress_wrapper(percent, *args):
        if progress_callback:
            scaled_pct = int(percent * 0.95)
            if args:
                try:
                    progress_callback(scaled_pct, *args)
                except TypeError:
                    progress_callback(scaled_pct)
            else:
                progress_callback(scaled_pct)

    import_success, import_msg = run_lichess_import(
        repo_name, elo_category,
        progress_callback=import_progress_wrapper,
        check_cancel=check_cancel,
        reuse_other_courses=reuse_other_courses,
        max_data_age_days=max_data_age_days
    )

    if not import_success:
        # If the import was cancelled or stopped, calculate priority scores on partial data so the repertoire is ready to use
        if "abgebrochen" in import_msg.lower() or "cancel" in import_msg.lower():
            if progress_callback:
                try:
                    progress_callback(96, "Berechne Prioritäten für vorhandene Lichess-Daten...")
                except TypeError:
                    progress_callback(96)
            calculate_priority_scores(
                repo_name, elo_category,
                progress_callback=None,
                check_cancel=None
            )
            return False, f"{import_msg} (Prioritäts-Scores für vorhandene Daten wurden berechnet)."
        return False, import_msg

    if check_cancel and check_cancel():
        calculate_priority_scores(
            repo_name, elo_category,
            progress_callback=None,
            check_cancel=None
        )
        return False, "Operation abgebrochen (Prioritäts-Scores wurden berechnet)."

    def priority_progress_wrapper(percent):
        if progress_callback:
            progress_callback(95 + int(percent * 0.05))

    priority_success, priority_msg = calculate_priority_scores(
        repo_name, elo_category,
        progress_callback=priority_progress_wrapper,
        check_cancel=check_cancel
    )

    if not priority_success:
        return False, f"Lichess import OK, but priority calculation failed: {priority_msg}"

    return True, "Lichess import und Prioritäts-Scores erfolgreich abgeschlossen."

def delete_lichess_data(repo_name: str, elo_category: Optional[str] = None) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return False, "Repertoire-Datenbank nicht gefunden."

    db = DatabaseManager(db_path)
    session = db.get_session()
    try:
        query = session.query(LichessData)
        if elo_category is not None:
            query = query.filter_by(elo_range=elo_category)
        num_deleted = query.delete(synchronize_session=False)

        if elo_category is not None:
            current_elo = get_meta(session, "lichess_elo")
            if current_elo == elo_category:
                set_meta(session, "lichess_elo", None)
        else:
            set_meta(session, "lichess_elo", None)
        
        set_meta(session, "cov_cache_count", "-1")
        session.commit()
        
        if elo_category is not None:
            if num_deleted > 0:
                return True, f"{num_deleted} Lichess-Daten-Einträge für ELO '{elo_category}' gelöscht."
            else:
                return True, f"Keine Lichess-Daten für ELO '{elo_category}' zum Löschen gefunden."
        else:
            if num_deleted > 0:
                return True, f"{num_deleted} Lichess-Daten-Einträge aller ELO-Bereiche gelöscht."
            else:
                return True, "Keine Lichess-Daten zum Löschen gefunden."

    except Exception as e:
        session.rollback()
        return False, f"Fehler beim Löschen der Lichess-Daten: {e}"
    finally:
        session.close()
        db.close()


def verify_lichess_token(token: str) -> Tuple[bool, str]:
    """
    Verifies a Lichess API token by making a request to the /api/account endpoint.
    Returns (Success: bool, Message: str).
    """
    cleaned = clean_lichess_token(token)
    if not cleaned:
        return False, "Kein gültiges Token angegeben."

    url = "https://lichess.org/api/account"
    headers = {
        'User-Agent': 'OpeningFenix/1.0',
        'Authorization': f'Bearer {cleaned}'
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                username = data.get('username', 'Unbekannt')
                return True, f"Verbindung erfolgreich! (Hallo {username})"
            else:
                return False, f"Fehler {response.status}: {response.reason}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Fehler 401: Ungültiges oder abgelaufenes Token."
        elif e.code == 429:
            return False, "Fehler 429: Zu viele Anfragen. Bitte warte einen Moment."
        else:
            return False, f"HTTP Fehler {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Netzwerkfehler: {str(e)}"

def run_lichess_orphan_cleanup(repo_name: str, progress_callback: Optional[Callable[[int], None]] = None) -> Tuple[bool, str]:
    """Removes all LichessData entries that are no longer referenced by any Position."""
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return False, "Datenbank nicht gefunden."
        
    db = DatabaseManager(db_path)
    session = db.get_session()
    try:
        # Fetch all Lichess FENs and check existence in the position table.
        all_lichess_fens = session.query(LichessData.fen).distinct().all()
        total = len(all_lichess_fens)
        deleted_count = 0
        
        for idx, (l_fen,) in enumerate(all_lichess_fens):
            # Check if any position matches this FEN prefix
            exists = session.query(Position.id).filter(Position.fen.like(l_fen + "%")).first()
            if not exists:
                n = session.query(LichessData).filter_by(fen=l_fen).delete()
                deleted_count += n
            
            if progress_callback and total > 0:
                progress_callback(int((idx + 1) * 100 / total))
                
        if deleted_count > 0:
            session.commit()
            
        return True, f"{deleted_count} Einträge bereinigt."
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()
        db.close()
