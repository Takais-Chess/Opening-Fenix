from PyQt6.QtCore import QThread, pyqtSignal
from opening_fenix.core.data_tools import run_db_analysis, run_lichess_import_and_calculate_scores, detect_islands, enrich_position
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.services.hole_finder_service import run_hole_finder_task


class AnalysisThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name, depth, threads, engine_path):
        super().__init__()
        self.repo_name = repo_name
        self.depth = depth
        self.threads = threads
        self.engine_path = engine_path
        self._is_canceled = False

    def run(self):
        success, msg = run_db_analysis(
            self.repo_name, 
            self.engine_path, 
            self.depth, 
            self.threads, 
            progress_callback=self.progress_signal.emit,
            check_cancel=lambda: self._is_canceled
        )
        self.finished_signal.emit(success, msg)

    def cancel(self):
        self._is_canceled = True

class LichessImportThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name, elo_category):
        super().__init__()
        self.repo_name = repo_name
        self.elo_category = elo_category
        self._is_canceled = False

    def run(self):
        success, msg = run_lichess_import_and_calculate_scores(
            self.repo_name, 
            self.elo_category, 
            progress_callback=self.progress_signal.emit,
            check_cancel=lambda: self._is_canceled
        )
        self.finished_signal.emit(success, msg)

    def cancel(self):
        self._is_canceled = True

class IslandDetectionThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name):
        super().__init__()
        self.repo_name = repo_name

    def run(self):
        success, msg = detect_islands(self.repo_name)
        self.finished_signal.emit(success, msg)


class BackgroundEnrichmentThread(QThread):
    """
    Background thread to enrich a position with Lichess data, engine analysis,
    and local priority scores. Silently works in the background.
    """
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_name, fen, elo_category, engine_path, depth=10):
        super().__init__()
        self.repo_name = repo_name
        self.fen = fen
        self.elo_category = elo_category
        self.engine_path = engine_path
        self.depth = depth

    def run(self):
        success, msg = enrich_position(
            self.repo_name,
            self.fen,
            self.elo_category,
            self.engine_path,
            self.depth
        )
        self.finished_signal.emit(success, msg)

class PGNImportThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, pgn_path, repo_name, side, level_name, level_order):
        super().__init__()
        self.pgn_path = pgn_path
        self.repo_name = repo_name
        self.side = side
        self.level_name = level_name
        self.level_order = level_order

    def run(self):
        success, msg = import_pgn_to_db(
            self.pgn_path,
            self.repo_name,
            self.side,
            self.level_name,
            self.level_order,
            progress_callback=self.progress_signal.emit
        )
        self.finished_signal.emit(success, msg)

from opening_fenix.core.services.maintenance_service import run_group_maintenance

class MaintenanceThread(QThread):
    # Overall summary: (current_repo_index, total_repos, last_completed_name)
    overall_progress_signal = pyqtSignal(int, int, str)
    # Granular status: (repo_name, task_type, percentage, status_text)
    repo_status_signal = pyqtSignal(str, str, int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, repo_configs, tasks, engine_settings=None):
        super().__init__()
        self.repo_configs = repo_configs
        self.tasks = tasks
        self.engine_settings = engine_settings
        self._is_canceled = False

    def run(self):
        success, msg = run_group_maintenance(
            self.repo_configs,
            self.tasks,
            self.engine_settings,
            overall_progress_callback=self.overall_progress_signal.emit,
            repo_status_callback=self.repo_status_signal.emit,
            check_cancel=lambda: self._is_canceled
        )
        self.finished_signal.emit(success, msg)

    def cancel(self):
        self._is_canceled = True

class RepertoireStatsWorker(QThread):
    stats_ready = pyqtSignal(int, str, float, str) # row_index, analysis_status, coverage_pct, elo
    finished = pyqtSignal()

    def __init__(self, repo_data_list):
        """
        repo_data_list: List of dicts {'row': int, 'name': str}
        """
        super().__init__()
        self.repo_data_list = repo_data_list
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True

    def run(self):
        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        service = RepertoireService()
        for item in self.repo_data_list:
            if self._is_stopped:
                break
            try:
                service.set_active_repertoire(item['name'])
                info = service.get_repertoire_info()
                if self._is_stopped: break
                self.stats_ready.emit(item['row'], info.get('depth', 'Error'), info.get('coverage_pct', 0.0), info.get('elo', 'high'))
                service.close()
            except Exception as e:
                print(f"DEBUG: StatsWorker Error for {item['name']}: {e}")
                if not self._is_stopped:
                    self.stats_ready.emit(item['row'], "Error", 0.0, "high")
        self.finished.emit()

class HoleFinderThread(QThread):
    finished_signal = pyqtSignal(list, str)
    
    def __init__(self, repo_name, is_test, threshold, elo_range, mode="holes", level=None):
        super().__init__()
        self.repo_name = repo_name
        self.is_test = is_test
        self.threshold = threshold
        self.elo_range = elo_range
        self.mode = mode
        self.level = level

    def run(self):
        try:
            results = run_hole_finder_task(
                self.repo_name, 
                self.is_test, 
                self.threshold, 
                self.elo_range, 
                self.mode, 
                self.level
            )
            self.finished_signal.emit(results, self.mode)
        except Exception as e:
            print(f"DEBUG: HoleFinderThread Error: {e}")
            self.finished_signal.emit(results, self.mode)
        except Exception as e:
            print(f"DEBUG: HoleFinderThread Error: {e}")
            self.finished_signal.emit([], self.mode)


class FenIndexBuilderThread(QThread):
    """
    Builds the in-memory FEN set AND the repertoire adjacency dict from the
    repertoire DB using its own sqlite3 connection — completely non-blocking.

    Emits (fen_set: set[str], repo_adjacency: dict[str, list[str]])
      fen_set        — 4-part normalised FENs of every position in the DB
      repo_adjacency — mapping from_fen_norm → [uci1, uci2, ...] for each
                       existing repertoire move
    """
    ready = pyqtSignal(object, object)   # set[str], dict[str, list[str]]

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path

    def run(self):
        import sqlite3
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()

            # ── 1. All position FENs ──────────────────────────────────────────────
            cur.execute("SELECT fen FROM positions")
            fen_set = {
                " ".join(row[0].strip().split()[:4])
                for row in cur.fetchall() if row[0]
            }

            # ── 2. Repertoire move adjacency (one JOIN, one query) ────────────────
            # from_fen_norm → [uci, uci, ...] for every existing repertoire move
            repo_adj: dict = {}
            try:
                cur.execute("""
                    SELECT p.fen, m.uci
                    FROM moves m
                    JOIN positions p ON m.from_position_id = p.id
                    INNER JOIN repertoire_moves rm ON rm.move_id = m.id
                """)
                for fen, uci in cur.fetchall():
                    fn = " ".join(fen.strip().split()[:4])
                    repo_adj.setdefault(fn, []).append(uci)
            except Exception:
                pass   # schema mismatch — fall back to no exclusions

            con.close()
            self.ready.emit(fen_set, repo_adj)
        except Exception as e:
            import logging
            logging.error(f"FenIndexBuilderThread error: {e}")
            self.ready.emit(set(), {})


class BfsTranspositionThread(QThread):
    """
    BFS over the legal move tree from a starting FEN.
    Checks each reached position against the in-memory FEN index.
    Emits depth_complete after each depth level with ALL results found so far.

    repo_adjacency: dict[fen_norm, list[uci]] built by FenIndexBuilderThread.
    At thread start, a quick in-memory BFS over repo_adjacency identifies FENs
    already reachable via existing repertoire moves — those are silently excluded
    from results so we never show already-connected positions as transpositions.
    (No DB queries inside the thread — zero main-thread contention.)
    """
    depth_complete = pyqtSignal(int, list)   # Emitted ONLY when target_depth is reached
    progress_update = pyqtSignal(int)        # Emitted for each intermediate depth

    def __init__(self, start_fen, fen_index, target_depth, repo_adjacency=None, parent=None):
        super().__init__(parent)
        self.start_fen = start_fen
        self.fen_index = fen_index
        self.target_depth = target_depth
        self.repo_adjacency = repo_adjacency or {}
        self._stop = False

    def stop(self):
        self._stop = True

    # ── helpers ──────────────────────────────────────────────────────────────────

    def _compute_exclude_fens(self):
        """In-memory BFS over repo_adjacency to find positions already connected."""
        import chess

        def norm(f):
            return " ".join(f.strip().split()[:4])

        start_norm = norm(self.start_fen)
        visited = {start_norm}
        frontier = [start_norm]

        for _ in range(self.target_depth):
            next_frontier = []
            for fn in frontier:
                for uci in self.repo_adjacency.get(fn, []):
                    try:
                        board = chess.Board(fn + " 0 1")
                        board.push(chess.Move.from_uci(uci))
                        new_fn = norm(board.fen())
                        if new_fn not in visited:
                            visited.add(new_fn)
                            next_frontier.append(new_fn)
                    except Exception:
                        pass
            frontier = next_frontier
        return visited

    # ── main BFS ─────────────────────────────────────────────────────────────────

    def run(self):
        import chess

        def norm(f):
            return " ".join(f.strip().split()[:4])

        # Positions reachable via existing repertoire moves (computed off main thread)
        exclude_fens = self._compute_exclude_fens()

        start_norm = norm(self.start_fen)

        # Frontier: list of (full_fen_str, path_ucis, path_sans)
        frontier = [(self.start_fen, [], [])]
        expanded = {start_norm}          # FENs already expanded — prevents BFS cycles
        all_results = []
        seen_targets = set()             # target FENs already reported

        for depth in range(1, self.target_depth + 1):
            if self._stop:
                break
            
            self.progress_update.emit(depth)
            next_frontier = []

            for base_fen, path_ucis, path_sans in frontier:
                if self._stop:
                    break
                try:
                    board = chess.Board(base_fen)
                except Exception:
                    continue

                for move in board.legal_moves:
                    if self._stop:
                        break

                    uci = move.uci()
                    try:
                        san = board.san(move)
                    except Exception:
                        san = uci

                    board.push(move)
                    new_fen = board.fen()
                    new_norm = norm(new_fen)
                    board.pop()

                    new_ucis = path_ucis + [uci]
                    new_sans = path_sans + [san]

                    # Report if in repertoire, not yet reported, not already linked
                    if (new_norm in self.fen_index
                            and new_norm not in seen_targets
                            and new_norm not in exclude_fens):
                        seen_targets.add(new_norm)
                        all_results.append({
                            "path_ucis": new_ucis,
                            "path_sans": new_sans,
                            "target_fen": new_norm,
                            "depth": depth,
                        })

                    # Expand for next depth level if not yet visited
                    if new_norm not in expanded and depth < self.target_depth:
                        expanded.add(new_norm)
                        next_frontier.append((new_fen, new_ucis, new_sans))

            frontier = next_frontier

        if not self._stop:
            self.depth_complete.emit(self.target_depth, list(all_results))


class InstantMultiPVThread(QThread):
    """
    Runs MultiPV engine analysis on the CURRENT position (before the transposition move)
    to determine how the transposition move ranks against all other options.
    Emits a dict mapping each transposition UCI to its ranking info.
    """
    finished = pyqtSignal(dict)  # {move_uci: {"rank": int, "delta": float, "best_san": str}}

    def __init__(self, current_fen, transposition_ucis, engine_path, threads_count=1, parent=None):
        super().__init__(parent)
        self.current_fen = current_fen
        self.transposition_ucis = list(transposition_ucis)
        self.engine_path = engine_path
        self.threads_count = threads_count

    def run(self):
        import chess
        import chess.engine
        import subprocess
        import sys

        results = {}
        engine = None
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            engine = chess.engine.SimpleEngine.popen_uci(
                self.engine_path, creationflags=creationflags
            )
            engine.configure({"Threads": self.threads_count})

            board = chess.Board(self.current_fen)
            multipv = max(10, len(self.transposition_ucis) + 5)

            info_list = engine.analyse(
                board,
                chess.engine.Limit(time=1.5),
                multipv=multipv,
            )

            # Build ranked list: [(rank, uci, score_cp)]
            ranked = []
            best_score = None
            for i, info in enumerate(info_list):
                if "pv" in info and info["pv"]:
                    m_uci = info["pv"][0].uci()
                    score_obj = info.get("score")
                    s = score_obj.white().score(mate_score=10000) if score_obj else 0
                    if best_score is None:
                        best_score = s
                    ranked.append((i + 1, m_uci, s))

            best_san = ""
            if ranked:
                try:
                    best_san = board.san(chess.Move.from_uci(ranked[0][1]))
                except Exception:
                    best_san = ranked[0][1]

            uci_to_rank = {uci: (rank, score) for rank, uci, score in ranked}

            for t_uci in self.transposition_ucis:
                if t_uci in uci_to_rank:
                    rank, score = uci_to_rank[t_uci]
                    delta = (score - best_score) / 100.0 if best_score is not None else 0.0
                else:
                    rank = multipv + 1
                    delta = -99.0
                results[t_uci] = {"rank": rank, "delta": delta, "best_san": best_san}

            engine.quit()
        except Exception as e:
            import logging
            logging.error(f"InstantMultiPVThread error: {e}")
            if engine:
                try:
                    engine.quit()
                except Exception:
                    pass
        finally:
            self.finished.emit(results)


class PathQualityEvalThread(QThread):
    """
    Evaluates quality of BFS transposition paths by analysing every intermediate
    position along each path with a shallow MultiPV (depth 10).

    For each move in a path the move is compared to the engine's best:
      - Threshold 0.5 pawns (50 cp) for BOTH the player's moves and the opponent's moves.

    Classification:
      🟡 Möglich   — every move in the path is within 0.5 cp of the engine's best
      🔴 mit Fehlern — at least one move deviates by more than 0.5 cp

    Results are sorted: 🟡 first (ascending depth), 🔴 last (ascending depth).
    """
    finished = pyqtSignal(list)   # classified and sorted path dicts
    progress = pyqtSignal(int, int) # (evaluated_count, total_count)

    THRESHOLD_CP = 50   # 0.5 pawns

    def __init__(self, raw_paths, start_fen, engine_path, threads_count=1, parent=None):
        super().__init__(parent)
        self.raw_paths = raw_paths
        self.start_fen = start_fen
        self.engine_path = engine_path
        self.threads_count = threads_count
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        import chess
        import chess.engine
        import subprocess
        import sys

        def norm(f):
            return " ".join(f.strip().split()[:4])

        engine = None
        classified = []
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            engine = chess.engine.SimpleEngine.popen_uci(
                self.engine_path, creationflags=creationflags
            )
            engine.configure({"Threads": self.threads_count})

            # ── Step 1: Collect unique (full_fen, move_uci) pairs from all paths ──
            # full_fen → set of UCIs we need to evaluate at that position
            fen_to_ucis: dict = {}
            # full_fen → actual chess.Board FEN (for reconstruction)
            fen_norm_to_full: dict = {}

            for path in self.raw_paths:
                if self._stop:
                    break
                board = chess.Board(self.start_fen)
                for uci in path["path_ucis"]:
                    full = board.fen()
                    fn = norm(full)
                    if fn not in fen_to_ucis:
                        fen_to_ucis[fn] = set()
                        fen_norm_to_full[fn] = full
                    fen_to_ucis[fn].add(uci)
                    try:
                        board.push(chess.Move.from_uci(uci))
                    except Exception:
                        break

            # ── Step 2: Evaluate each unique intermediate FEN once ──
            # (fen_norm, uci) → bool: True = within threshold
            move_ok: dict = {}
            total = len(fen_to_ucis)
            current = 0

            for fn, ucis_needed in fen_to_ucis.items():
                if self._stop:
                    break
                current += 1
                self.progress.emit(current, total)
                full_fen = fen_norm_to_full[fn]
                try:
                    board = chess.Board(full_fen)
                    n_pv = max(len(ucis_needed), 5)
                    info_list = engine.analyse(
                        board,
                        chess.engine.Limit(depth=10),
                        multipv=n_pv,
                    )
                except Exception:
                    # On error mark all moves at this position as OK (don't penalise)
                    for uci in ucis_needed:
                        move_ok[(fn, uci)] = True
                    continue

                best_score = None
                uci_scores: dict = {}
                for info in info_list:
                    if "pv" in info and info["pv"]:
                        m_uci = info["pv"][0].uci()
                        score_obj = info.get("score")
                        s = score_obj.white().score(mate_score=10000) if score_obj else 0
                        if best_score is None:
                            best_score = s
                        uci_scores[m_uci] = s

                for uci in ucis_needed:
                    if best_score is None or uci not in uci_scores:
                        move_ok[(fn, uci)] = False   # not in top-N → likely worse than threshold
                    else:
                        delta = abs(uci_scores[uci] - best_score)
                        move_ok[(fn, uci)] = delta <= self.THRESHOLD_CP

            # ── Step 3: Classify each path ──
            for path in self.raw_paths:
                if self._stop:
                    break
                board = chess.Board(self.start_fen)
                all_ok = True
                for uci in path["path_ucis"]:
                    fn = norm(board.fen())
                    if not move_ok.get((fn, uci), True):
                        all_ok = False
                    try:
                        board.push(chess.Move.from_uci(uci))
                    except Exception:
                        all_ok = False
                        break

                quality = "möglich" if all_ok else "fehler"
                classified.append({
                    **path,
                    "quality": quality,
                    "quality_label": "🟡 Möglich" if all_ok else "🔴 mit Fehlern",
                })

            engine.quit()

        except Exception as e:
            import logging
            logging.error(f"PathQualityEvalThread error: {e}")
            if engine:
                try:
                    engine.quit()
                except Exception:
                    pass
            # Fallback: return unclassified paths marked as Möglich
            classified = [
                {**p, "quality": "möglich", "quality_label": "🟡 Möglich"}
                for p in self.raw_paths
            ]

        # Sort: 🟡 Möglich first (depth ascending), then 🔴 mit Fehlern (depth ascending)
        classified.sort(key=lambda x: (0 if x["quality"] == "möglich" else 1, x["depth"]))
        self.finished.emit(classified)

