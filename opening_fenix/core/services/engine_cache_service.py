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
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_engine_evals_depth ON engine_evals (depth);")
                    try:
                        conn.execute("ALTER TABLE engine_evals ADD COLUMN eval_json TEXT;")
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
