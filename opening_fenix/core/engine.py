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
        
        # Performance state
        self._target_fen = None
        self._is_analyzing = False
        
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

    def stop_engine(self):
        self.running = False
        self.is_active = False
        if self.engine:
            try:
                self.engine.quit()
            except Exception:
                pass
            self.engine = None

    def set_position(self, fen, force_restart=False):
        with self._lock:
            if self._target_fen == fen and not force_restart:
                return
                
            self._target_fen = fen
            self.board = chess.Board(fen)

    def toggle_analysis(self, active):
        with self._lock:
            if self.is_active == active:
                return
                
            self.is_active = active
            if active and self._target_fen:
                self.board = chess.Board(self._target_fen)

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
        
        if changed and self.engine:
            try:
                config = {}
                if "Threads" in self.engine.options:
                    config["Threads"] = self.threads
                if "Hash" in self.engine.options:
                    config["Hash"] = self.hash_size
                
                if config:
                    self.engine.configure(config)
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
                    self.msleep(1000)
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
                        self.msleep(50)
                        continue

                    legal_moves_count = board_snapshot.legal_moves.count()
                    if legal_moves_count == 0:
                        self.info_signal.emit(["Partieende / Keine legalen Züge"])
                        self.msleep(100)
                        continue
                        
                    actual_multipv = max(1, min(self.multipv, legal_moves_count))
                    
                    try:
                        self._is_analyzing = True
                        with self.engine.analysis(board_snapshot, limit, multipv=actual_multipv) as analysis:
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
                        
                        was_active = self.is_active
                        self.stop_engine()
                        self.start_engine()
                        self.is_active = was_active
                        
                        current_board_fen = None # Force restart on next loop
                        self.msleep(1000)
                else:
                    self.msleep(50)
            else:
                current_board_fen = None 
                # LAZY STOP: Release RAM when not analyzing
                if self.engine:
                    self.stop_engine()
                self.msleep(100)
                
        self.stop_engine()

    def process_info(self, info, board, actual_multipv=None):
        if actual_multipv is None:
            actual_multipv = self.multipv

        # Only cache the raw data quickly
        idx = None
        if "multipv" in info:
            idx = info["multipv"]
            self.lines_cache[idx] = info.copy()
        elif "pv" in info:
            idx = 1
            self.lines_cache[1] = info.copy()

        if idx is not None:
            depth = info.get("depth", 0)
            if depth > self.current_iter_depth:
                self.current_iter_depth = depth
                self.current_iter_lines = {idx: info.copy()}
            elif depth == self.current_iter_depth:
                self.current_iter_lines[idx] = info.copy()

            # When all active MultiPV lines have reached the current depth iteration:
            if len(self.current_iter_lines) >= actual_multipv:
                self.completed_lines = {k: v.copy() for k, v in self.current_iter_lines.items()}
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
