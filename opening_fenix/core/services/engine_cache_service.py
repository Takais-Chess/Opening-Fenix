"""
Global persistent cache for chess engine evaluations (e.g. Stockfish depth 25).
Persists best-move findings across application restarts and repertoires.
"""

import json
import os
import sqlite3
import threading
from typing import Optional, Dict, Iterable
from opening_fenix.core.utils import get_user_dir

_lock = threading.Lock()


def get_engine_cache_db_path(custom_dir: Optional[str] = None) -> str:
    """Returns the path to the global engine evaluation cache database."""
    base_dir = custom_dir or get_user_dir()
    cache_dir = os.path.join(base_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "engine_eval_cache.db")


class EngineCacheService:
    """
    Thread-safe service to store and query engine evaluations (depth, best move, and MultiPV scores).
    Uses a local SQLite database in the user cache directory with an in-memory L1 cache.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_engine_cache_db_path()
        self._local_cache: Dict[str, tuple] = {}
        self._alt_cache: Dict[str, tuple] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with _lock:
            try:
                conn = self._get_connection()
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS engine_evals (
                            fen TEXT PRIMARY KEY,
                            depth INTEGER NOT NULL,
                            best_uci TEXT NOT NULL,
                            eval_json TEXT,
                            alternate_moves_json TEXT,
                            alternates_depth INTEGER,
                            alternates_exhaustive INTEGER DEFAULT 0,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_engine_evals_depth ON engine_evals (depth);")
                    try:
                        conn.execute("CREATE INDEX IF NOT EXISTS idx_engine_evals_alt_depth ON engine_evals (alternates_depth);")
                    except Exception:
                        pass
                    try:
                        conn.execute("ALTER TABLE engine_evals ADD COLUMN eval_json TEXT;")
                    except Exception:
                        pass
                    try:
                        conn.execute("ALTER TABLE engine_evals ADD COLUMN alternate_moves_json TEXT;")
                    except Exception:
                        pass
                    try:
                        conn.execute("ALTER TABLE engine_evals ADD COLUMN alternates_depth INTEGER;")
                    except Exception:
                        pass
                    try:
                        conn.execute("ALTER TABLE engine_evals ADD COLUMN alternates_exhaustive INTEGER DEFAULT 0;")
                    except Exception:
                        pass
                conn.close()
            except Exception:
                pass

    def get_best_move(self, fen: str, min_depth: int = 25) -> Optional[str]:
        """
        Retrieves the cached best move for a FEN if evaluated at >= min_depth.
        Returns the move in UCI string format, or None if not cached.
        """
        if not fen:
            return None
        clean = " ".join(fen.strip().split()[:4])

        # 1. Fast in-memory check
        with _lock:
            if clean in self._local_cache:
                entry = self._local_cache[clean]
                cached_uci, cached_depth = entry[0], entry[1]
                if cached_depth >= min_depth:
                    return cached_uci

        # 2. SQLite lookup
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT best_uci, depth, eval_json FROM engine_evals WHERE fen = ? AND depth >= ?",
                (clean, min_depth)
            )
            row = cur.fetchone()
            conn.close()
            if row:
                best_uci, depth, eval_json = row[0], row[1], row[2]
                eval_data = None
                if eval_json:
                    try:
                        eval_data = json.loads(eval_json)
                    except Exception:
                        pass
                with _lock:
                    self._local_cache[clean] = (best_uci, depth, eval_data)
                return best_uci
        except Exception:
            pass
        return None

    def get_eval_data(self, fen: str, min_depth: int = 25) -> Optional[dict]:
        """
        Retrieves cached evaluation data (best_uci, best_score, moves dict) for a FEN.
        Returns a dict with {"best_uci": str, "best_score": Optional[int], "moves": dict, "depth": int} or None.
        """
        if not fen:
            return None
        clean = " ".join(fen.strip().split()[:4])

        with _lock:
            if clean in self._local_cache:
                entry = self._local_cache[clean]
                cached_uci, cached_depth = entry[0], entry[1]
                cached_eval = entry[2] if len(entry) > 2 else None
                if cached_depth >= min_depth:
                    if cached_eval and isinstance(cached_eval, dict):
                        return {**cached_eval, "best_uci": cached_uci, "depth": cached_depth}
                    return {
                        "best_uci": cached_uci,
                        "best_score": None,
                        "moves": {cached_uci: 0},
                        "depth": cached_depth,
                    }

        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT best_uci, depth, eval_json FROM engine_evals WHERE fen = ? AND depth >= ?",
                (clean, min_depth)
            )
            row = cur.fetchone()
            conn.close()
            if row:
                best_uci, depth, eval_json = row[0], row[1], row[2]
                eval_data = None
                if eval_json:
                    try:
                        eval_data = json.loads(eval_json)
                    except Exception:
                        eval_data = None
                with _lock:
                    self._local_cache[clean] = (best_uci, depth, eval_data)

                if eval_data and isinstance(eval_data, dict):
                    return {**eval_data, "best_uci": best_uci, "depth": depth}
                return {
                    "best_uci": best_uci,
                    "best_score": None,
                    "moves": {best_uci: 0},
                    "depth": depth,
                }
        except Exception:
            pass
        return None

    def get_batch(self, fens: Iterable[str], min_depth: int = 25) -> Dict[str, str]:
        """
        Retrieves cached best moves for multiple FENs at once.
        Returns a mapping of {clean_fen: best_uci}.
        """
        result = {}
        missing = []
        cleaned = [" ".join(f.strip().split()[:4]) for f in fens if f]
        with _lock:
            for c in cleaned:
                if c in self._local_cache:
                    c_uci, c_depth = self._local_cache[c]
                    if c_depth >= min_depth:
                        result[c] = c_uci
                    else:
                        missing.append(c)
                else:
                    missing.append(c)

        if not missing:
            return result

        try:
            conn = self._get_connection()
            cur = conn.cursor()
            for i in range(0, len(missing), 500):
                chunk = missing[i:i + 500]
                placeholders = ",".join("?" for _ in chunk)
                query = f"SELECT fen, best_uci, depth FROM engine_evals WHERE fen IN ({placeholders}) AND depth >= ?"
                cur.execute(query, (*chunk, min_depth))
                for r_fen, r_uci, r_depth in cur.fetchall():
                    result[r_fen] = r_uci
                    with _lock:
                        self._local_cache[r_fen] = (r_uci, r_depth)
            conn.close()
        except Exception:
            pass
        return result

    def set_best_move(self, fen: str, depth: int, best_uci: str):
        """
        Stores or updates an engine evaluation for a FEN.
        Only overwrites if the new evaluation has equal or higher depth.
        """
        self.set_eval_data(fen, depth, best_uci, None)

    def set_eval_data(self, fen: str, depth: int, best_uci: str, eval_data: Optional[dict] = None):
        """
        Stores or updates an engine evaluation with full MultiPV candidate move scores.
        Only overwrites if the new evaluation has equal or higher depth.
        """
        if not fen or not best_uci:
            return
        clean = " ".join(fen.strip().split()[:4])
        eval_json_str = None
        if eval_data and isinstance(eval_data, dict):
            try:
                eval_json_str = json.dumps(eval_data)
            except Exception:
                eval_json_str = None

        with _lock:
            self._local_cache[clean] = (best_uci, depth, eval_data)

        try:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO engine_evals (fen, depth, best_uci, eval_json, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(fen) DO UPDATE SET
                        depth = excluded.depth,
                        best_uci = excluded.best_uci,
                        eval_json = COALESCE(excluded.eval_json, engine_evals.eval_json),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE excluded.depth >= engine_evals.depth;
                """, (clean, depth, best_uci, eval_json_str))
            conn.close()
        except Exception:
            pass

    def get_alternate_moves(self, fen: str, min_depth: int = 18, require_exhaustive: bool = True) -> Optional[dict]:
        """
        Retrieves cached alternate moves for a FEN.
        Returns a dict {"good_moves": list, "depth": int, "is_exhaustive": bool, "best_uci": Optional[str]} or None.
        If require_exhaustive is True, returns data only if is_exhaustive is True and depth >= min_depth.
        """
        if not fen:
            return None
        clean = " ".join(fen.strip().split()[:4])

        with _lock:
            if clean in self._alt_cache:
                gm, d, exh, b_uci = self._alt_cache[clean]
                if d >= min_depth and (exh or not require_exhaustive):
                    return {"good_moves": list(gm), "depth": d, "is_exhaustive": exh, "best_uci": b_uci}

        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT alternate_moves_json, alternates_depth, alternates_exhaustive, best_uci "
                "FROM engine_evals WHERE fen = ? AND alternates_depth >= ?",
                (clean, min_depth)
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                alt_json, depth, is_exh, best_uci = row[0], row[1], bool(row[2]), row[3]
                if require_exhaustive and not is_exh:
                    return None
                try:
                    moves = json.loads(alt_json)
                    if isinstance(moves, list):
                        with _lock:
                            self._alt_cache[clean] = (moves, depth, is_exh, best_uci)
                        return {
                            "good_moves": list(moves),
                            "depth": depth,
                            "is_exhaustive": is_exh,
                            "best_uci": best_uci
                        }
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def set_alternate_moves(
        self,
        fen: str,
        depth: int,
        good_moves: list,
        is_exhaustive: bool = True,
        best_uci: Optional[str] = None
    ):
        """
        Stores or updates alternate moves evaluation for a FEN.
        Only overwrites existing good_moves if:
          1. New evaluation is exhaustive and previous was not, OR
          2. New evaluation has >= depth and is at least as exhaustive as previous, OR
          3. Previous had no alternate moves.
        If the new evaluation is NOT exhaustive, it merges good_moves with existing cached good_moves.
        Preserves existing targeted/transposition eval_json and best_uci.
        """
        if not fen or good_moves is None:
            return
        clean = " ".join(fen.strip().split()[:4])
        cleaned_moves = list(dict.fromkeys(good_moves))
        alt_json_str = json.dumps(cleaned_moves)
        is_exh_int = 1 if is_exhaustive else 0

        try:
            conn = self._get_connection()
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT alternate_moves_json, alternates_depth, alternates_exhaustive, best_uci FROM engine_evals WHERE fen = ?",
                    (clean,)
                )
                row = cur.fetchone()
                if row:
                    prev_json, prev_depth, prev_exh, prev_best = row[0], row[1] or 0, bool(row[2]), row[3]
                    eff_best = best_uci or prev_best or (cleaned_moves[0] if cleaned_moves else "")
                    
                    merged_moves = cleaned_moves
                    if prev_json:
                        try:
                            prev_list = json.loads(prev_json)
                            if isinstance(prev_list, list):
                                if not is_exhaustive or not prev_exh or depth < prev_depth:
                                    merged_moves = list(dict.fromkeys(prev_list + cleaned_moves))
                                else:
                                    merged_moves = cleaned_moves
                                alt_json_str = json.dumps(merged_moves)
                        except Exception:
                            pass

                    should_update = False
                    if prev_json is None:
                        should_update = True
                    elif is_exhaustive and not prev_exh:
                        should_update = True
                    elif is_exhaustive == prev_exh and depth >= prev_depth:
                        should_update = True
                    elif not is_exhaustive:
                        should_update = True

                    new_exh = True if (is_exhaustive or prev_exh) else False
                    new_depth = max(depth, prev_depth)

                    if should_update:
                        cur.execute("""
                            UPDATE engine_evals SET
                                alternate_moves_json = ?,
                                alternates_depth = ?,
                                alternates_exhaustive = ?,
                                best_uci = CASE WHEN best_uci IS NOT NULL AND best_uci != '' THEN best_uci ELSE ? END,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE fen = ?
                        """, (alt_json_str, new_depth, 1 if new_exh else 0, eff_best, clean))

                    with _lock:
                        self._alt_cache[clean] = (merged_moves, new_depth, new_exh, eff_best)
                else:
                    eff_best = best_uci or (cleaned_moves[0] if cleaned_moves else "")
                    cur.execute("""
                        INSERT INTO engine_evals (fen, depth, best_uci, alternate_moves_json, alternates_depth, alternates_exhaustive, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (clean, depth, eff_best, alt_json_str, depth, is_exh_int))
                    with _lock:
                        self._alt_cache[clean] = (cleaned_moves, depth, is_exhaustive, eff_best)
            conn.close()
        except Exception:
            pass

    def clear_alternate_moves(self):
        """
        Clears alternate moves analysis data from the cache table.
        Leaves best_uci and transposition eval_json intact.
        """
        with _lock:
            self._alt_cache.clear()
        try:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    UPDATE engine_evals SET
                        alternate_moves_json = NULL,
                        alternates_depth = NULL,
                        alternates_exhaustive = 0
                """)
            conn.close()
        except Exception:
            pass


