import chess
import chess.engine
import subprocess
import sys
import time
import threading
from PyQt6.QtCore import QThread, pyqtSignal, QElapsedTimer
from opening_fenix.core.logger import logger

class EngineThread(QThread):
    info_signal = pyqtSignal(object) # Can be list of strings (status) or list of dicts (analysis)
    db_update_signal = pyqtSignal(str, int, int) # fen, depth, eval (cp)
    analysis_finished_signal = pyqtSignal(str, int, list) # fen, depth, lines_data

    def __init__(self, engine_path, threads=4, depth=20, use_depth_limit=True, multipv=3, hash_size=256):
        super().__init__()
        self.engine_path = engine_path
        self.threads = threads
        self.target_depth = depth
        self.use_depth_limit = use_depth_limit
        self.multipv = multipv
        self.hash_size = hash_size
        self.engine = None
        self.board = None
        self.running = False
        self.is_active = False
        self.lines_cache = {} # Stores latest info for each multipv index
        
        # MultiPV Iteration synchronization state
        self.current_iter_depth = 0
        self.current_iter_lines = {}
        self.completed_lines = {}
        self._last_emit_time = QElapsedTimer()
        self._last_emit_time.start()
        
        # Thread synchronization
        self._lock = threading.Lock()
        self._wake_cond = threading.Condition(self._lock)
        
        # Performance state
        self._target_fen = None
        self._is_analyzing = False
        self._active_analysis = None
        
        # Throttling
        self._throttle_timer = QElapsedTimer()
        self._throttle_timer.start()
        self._emit_interval = 100  # ms

    def start_engine(self):
        if not self.engine:
            try:
                # Prevent console window from appearing on Windows
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NO_WINDOW

                self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path, creationflags=creationflags)
                try:
                    config = {}
                    # Check if options are supported before setting them
                    if "Threads" in self.engine.options:
                        config["Threads"] = self.threads
                    if "Hash" in self.engine.options:
                        config["Hash"] = self.hash_size
                        
                    if config:
                        self.engine.configure(config)
                except Exception as e:
                    logger.warning(f"Engine configuration warning: {e}")
                    self.info_signal.emit([f"Config Warning: {e}"])
                self.running = True
                self.info_signal.emit(["Engine bereit."])
            except Exception as e:
                logger.error(f"Failed to start engine: {e}")
                self.info_signal.emit([f"Engine Fehler: {e}"])

    def _close_engine_process(self):
        with self._lock:
            eng = self.engine
            self.engine = None
        if eng:
            try:
                eng.quit()
            except Exception:
                try:
                    eng.close()
                except Exception:
                    pass

    def _interrupt_active_analysis(self):
        with self._lock:
            analysis = self._active_analysis
        if analysis is not None:
            try:
                analysis.stop()
            except Exception:
                pass

    def stop_engine(self):
        with self._lock:
            self.running = False
            self.is_active = False
            self._wake_cond.notify_all()
        self._interrupt_active_analysis()
        self._close_engine_process()

    def set_position(self, fen, force_restart=False):
        with self._lock:
            if self._target_fen == fen and not force_restart:
                return
                
            self._target_fen = fen
            self.board = chess.Board(fen)
            self._wake_cond.notify_all()
        self._interrupt_active_analysis()

    def toggle_analysis(self, active):
        should_interrupt = False
        with self._lock:
            if self.is_active == active:
                return
                
            self.is_active = active
            if active and self._target_fen:
                self.board = chess.Board(self._target_fen)
            elif not active:
                should_interrupt = True
            self._wake_cond.notify_all()
        if should_interrupt:
            self._interrupt_active_analysis()

    def update_config(self, threads, depth, use_depth_limit, multipv, hash_size=None):
        changed = False
        with self._lock:
            if self.threads != threads or self.multipv != multipv or (hash_size is not None and self.hash_size != hash_size):
                changed = True
                
            self.threads = threads
            self.target_depth = depth
            self.use_depth_limit = use_depth_limit
            self.multipv = multipv
            if hash_size is not None:
                self.hash_size = hash_size
            self._wake_cond.notify_all()
        
        with self._lock:
            eng = self.engine
            threads_val = self.threads
            hash_val = self.hash_size
        if changed and eng:
            try:
                config = {}
                if "Threads" in eng.options:
                    config["Threads"] = threads_val
                if "Hash" in eng.options:
                    config["Hash"] = hash_val

                if config:
                    eng.configure(config)
            except Exception as e:
                logger.warning(f"Error updating engine configuration: {e}")
                self.info_signal.emit([f"Update Config Error: {e}"])

    def run(self):
        self.info_signal.emit(["Engine-Thread gestartet."])
        self.start_engine()

        current_board_fen = None
        current_multipv = None
        current_depth = None
        
        while self.running:
            if self.is_active and self.board:
                # LAZY START: Only start the process when actually analyzing
                if not self.engine:
                    self.start_engine()
                
                if not self.engine: # Failed to start
                    with self._lock:
                        self._wake_cond.wait(timeout=1.0)
                    continue

                # Check if we need to start a new analysis
                with self._lock:
                    settings_changed = (self.multipv != current_multipv) or (self.target_depth != current_depth)
                    position_changed = (self._target_fen != current_board_fen)
                    target_fen = self._target_fen
                    target_multipv = self.multipv
                    target_depth = self.target_depth
                    board_snapshot = self.board.copy() if self.board else None
                
                if position_changed or settings_changed:
                    current_board_fen = target_fen
                    current_multipv = target_multipv
                    current_depth = target_depth
                    self.lines_cache = {}
                    self.current_iter_depth = 0
                    self.current_iter_lines = {}
                    self.completed_lines = {}
                    self._last_emit_time.restart()
                    
                    limit = None
                    if self.use_depth_limit:
                        limit = chess.engine.Limit(depth=self.target_depth)
                    
                    if not board_snapshot:
                        with self._lock:
                            self._wake_cond.wait(timeout=0.05)
                        continue

                    legal_moves_count = board_snapshot.legal_moves.count()
                    if legal_moves_count == 0:
                        self.info_signal.emit(["Partieende / Keine legalen Züge"])
                        with self._lock:
                            self._wake_cond.wait(timeout=0.1)
                        continue
                        
                    actual_multipv = max(1, min(self.multipv, legal_moves_count))
                    
                    try:
                        self._is_analyzing = True
                        with self.engine.analysis(board_snapshot, limit, multipv=actual_multipv) as analysis:
                            with self._lock:
                                self._active_analysis = analysis
                                if (
                                    not self.running
                                    or not self.is_active
                                    or self._target_fen != current_board_fen
                                    or self.multipv != current_multipv
                                    or self.target_depth != current_depth
                                ):
                                    try:
                                        analysis.stop()
                                    except Exception:
                                        pass
                            for info in analysis:
                                # FAST ABORT CHECKS
                                if not self.running or not self.is_active:
                                    break
                                if self._target_fen != current_board_fen:
                                    break
                                if self.multipv != current_multipv or self.target_depth != current_depth:
                                    break
                                
                                # Process the info packet directly
                                self.process_info(info, board_snapshot, actual_multipv=actual_multipv)
                                
                        # One final flush to ensure the UI gets the very last evaluation
                        if self._target_fen == current_board_fen:
                            if self.completed_lines:
                                self.lines_cache.update(self.completed_lines)
                            self._emit_current_cache(board_snapshot)

                        # If analysis reached target_depth without being aborted by moves or settings changes:
                        if (self._target_fen == current_board_fen and 
                            self.running and self.is_active and 
                            self.multipv == current_multipv and 
                            self.target_depth == current_depth):
                            src_lines = self.completed_lines if self.completed_lines else self.lines_cache
                            final_lines = [
                                src_lines[k].copy() 
                                for k in sorted(src_lines.keys()) 
                                if k <= actual_multipv and src_lines[k].get("pv")
                            ]
                            if final_lines:
                                self.analysis_finished_signal.emit(current_board_fen, current_depth, final_lines)

                        self._is_analyzing = False
                        
                    except Exception as e:
                        self._is_analyzing = False
                        logger.error(f"Analysis error at {current_board_fen}: {e}")
                        self.info_signal.emit([f"Analysis Error: {e}"])
                        
                        self._close_engine_process()
                        self.start_engine()
                        
                        current_board_fen = None # Force restart on next loop
                        with self._lock:
                            self._wake_cond.wait(timeout=1.0)
                    finally:
                        with self._lock:
                            self._active_analysis = None
                else:
                    with self._lock:
                        if self.running and self.is_active and self._target_fen == current_board_fen and self.multipv == current_multipv and self.target_depth == current_depth:
                            self._wake_cond.wait(timeout=0.2)
            else:
                current_board_fen = None 
                # LAZY STOP: Release RAM when not analyzing
                if self.engine:
                    self._close_engine_process()
                with self._lock:
                    if self.running and not (self.is_active and self.board):
                        self._wake_cond.wait(timeout=0.5)
                
        self.stop_engine()

    def process_info(self, info, board, actual_multipv=None):
        if actual_multipv is None:
            actual_multipv = self.multipv

        # Only cache the raw data quickly (one shallow snapshot per info packet)
        idx = info.get("multipv")
        if idx is None and "pv" in info:
            idx = 1

        if idx is not None:
            info_snap = info.copy()
            self.lines_cache[idx] = info_snap
            depth = info_snap.get("depth", 0)
            if depth > self.current_iter_depth:
                self.current_iter_depth = depth
                self.current_iter_lines = {idx: info_snap}
            elif depth == self.current_iter_depth:
                self.current_iter_lines[idx] = info_snap

            # When all active MultiPV lines have reached the current depth iteration:
            if len(self.current_iter_lines) >= actual_multipv:
                self.completed_lines = dict(self.current_iter_lines)
                if self._throttle_timer.hasExpired(self._emit_interval):
                    self.lines_cache.update(self.completed_lines)
                    self._emit_current_cache(board)
                    self._throttle_timer.restart()
                    self._last_emit_time.restart()
                    return

        # Fallback / single line: emit when throttle timer has expired
        if self._throttle_timer.hasExpired(self._emit_interval):
            if actual_multipv == 1 or self._last_emit_time.hasExpired(1000) or not self.completed_lines:
                if self.completed_lines:
                    self.lines_cache.update(self.completed_lines)
                self._emit_current_cache(board)
                self._throttle_timer.restart()
                self._last_emit_time.restart()

    def _emit_current_cache(self, board):
        """Builds strings and emits to UI. Separated from process_info to allow throttling."""
        if not self.lines_cache:
            return
        
        # Calculate synchronized depth to prevent lines showing mismatched depths (e.g. 19 vs 20)
        valid_depths = [self.lines_cache[k].get("depth", 0) for k in sorted(self.lines_cache.keys()) if k <= self.multipv and self.lines_cache[k].get("depth", 0) > 0]
        sync_depth = min(valid_depths) if valid_depths else 0
        
        structured_lines = []
        best_eval_cp = None
        best_depth = 0

        # Process the cached lines
        for idx in sorted(self.lines_cache.keys()):
            if idx > self.multipv:
                continue
                
            line_data = self.lines_cache[idx]
            extracted = self._extract_line_data(line_data, board)
            if extracted:
                if sync_depth > 0:
                    extracted['depth'] = sync_depth
                structured_lines.append(extracted)
                if idx == 1:
                    best_eval_cp = extracted['cp_val']
                    best_depth = extracted['depth']

        if structured_lines:
            self.info_signal.emit(structured_lines)
            if best_eval_cp is not None and best_depth > 0:
                self.db_update_signal.emit(board.fen(), best_depth, best_eval_cp)

    @staticmethod
    def _extract_line_data(line_info, board):
        score = line_info.get("score")
        score_str = "..."
        cp_val = None
        
        if score:
            if score.is_mate():
                mate = score.white().mate()
                score_str = f"M{mate:+d}"
                cp_val = 10000 if mate > 0 else -10000
            else:
                cp = score.white().score()
                if cp is not None:
                    score_str = f"{cp/100:+.2f}"
                    cp_val = cp
        
        pv = line_info.get("pv", [])
        first_uci = pv[0].uci() if (pv and len(pv) > 0) else None
        
        # Optimization: Only push moves we actually intend to show (max 6)
        temp_board = board.copy()
        pv_san = []
        for m in pv[:6]:
            try:
                pv_san.append(temp_board.san(m))
                temp_board.push(m)
            except Exception:
                break
        pv_str = " ".join(pv_san)
        
        depth = line_info.get("depth", 0)
        
        return {
            "score": score_str,
            "depth": depth,
            "pv": pv_str,
            "cp_val": cp_val,
            "first_uci": first_uci
        }
