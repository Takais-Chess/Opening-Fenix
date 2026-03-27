import chess
import chess.engine
import subprocess
import sys
import time
from PyQt6.QtCore import QThread, pyqtSignal

class EngineThread(QThread):
    info_signal = pyqtSignal(object) # Can be list of strings (status) or list of dicts (analysis)
    db_update_signal = pyqtSignal(str, int, int) # fen, depth, eval (cp)

    def __init__(self, engine_path, threads=4, depth=20, use_depth_limit=True, multipv=3):
        super().__init__()
        self.engine_path = engine_path
        self.threads = threads
        self.target_depth = depth
        self.use_depth_limit = use_depth_limit
        self.multipv = multipv
        self.engine = None
        self.board = None
        self.running = False
        self.is_active = False
        self.lines_cache = {} # Stores latest info for each multipv index
        
        # Performance state
        self._target_fen = None
        self._is_analyzing = False
        
        # Throttling
        self._last_emit_time = 0
        self._emit_interval = 0.1  # Only emit UI updates 10 times per second (100ms)

    def start_engine(self):
        if not self.engine:
            try:
                # Prevent console window from appearing on Windows
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NO_WINDOW

                self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path, creationflags=creationflags)
                try:
                    self.engine.configure({"Threads": self.threads, "MultiPV": self.multipv})
                except Exception as e:
                    self.info_signal.emit([f"Config Warning: {e}"])
                self.running = True
                self.info_signal.emit(["Engine geladen."])
            except Exception as e:
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

    def set_position(self, fen):
        if self._target_fen == fen:
            return
            
        self._target_fen = fen
        self.board = chess.Board(fen)

    def toggle_analysis(self, active):
        if self.is_active == active:
            return
            
        self.is_active = active
        if active and self._target_fen:
            self.board = chess.Board(self._target_fen)

    def update_config(self, threads, depth, use_depth_limit, multipv):
        changed = False
        if self.threads != threads or self.multipv != multipv:
            changed = True
            
        self.threads = threads
        self.target_depth = depth
        self.use_depth_limit = use_depth_limit
        self.multipv = multipv
        
        if changed and self.engine:
            try:
                self.engine.configure({"Threads": self.threads, "MultiPV": self.multipv})
            except Exception as e:
                self.info_signal.emit([f"Update Config Error: {e}"])

    def run(self):
        self.info_signal.emit(["Engine-Thread gestartet."])
        self.start_engine()

        current_board_fen = None
        current_multipv = None
        current_depth = None
        
        while self.running:
            if self.is_active and self.board and self.engine:
                # Check if we need to start a new analysis
                settings_changed = (self.multipv != current_multipv) or (self.target_depth != current_depth)
                position_changed = (self._target_fen != current_board_fen)
                
                if position_changed or settings_changed:
                    current_board_fen = self._target_fen
                    current_multipv = self.multipv
                    current_depth = self.target_depth
                    self.lines_cache = {} 
                    
                    limit = None
                    if self.use_depth_limit:
                        limit = chess.engine.Limit(depth=self.target_depth)
                    
                    legal_moves_count = self.board.legal_moves.count()
                    if legal_moves_count == 0:
                        self.msleep(100)
                        continue
                        
                    actual_multipv = max(1, min(self.multipv, legal_moves_count))
                    
                    try:
                        self._is_analyzing = True
                        with self.engine.analysis(self.board, limit, multipv=actual_multipv) as analysis:
                            for info in analysis:
                                # FAST ABORT CHECKS
                                if not self.running or not self.is_active:
                                    break
                                if self._target_fen != current_board_fen:
                                    break
                                if self.multipv != current_multipv or self.target_depth != current_depth:
                                    break
                                
                                # Process the info packet directly
                                self.process_info(info, self.board)
                                
                        # One final flush to ensure the UI gets the very last evaluation 
                        # even if it happened faster than our 100ms throttle timer
                        self._emit_current_cache(self.board)
                        self._is_analyzing = False
                        
                    except Exception as e:
                        self._is_analyzing = False
                        self.info_signal.emit([f"Analysis Error: {e}"])
                        self.msleep(1000)
                else:
                    self.msleep(50)
            else:
                current_board_fen = None 
                self.msleep(100)
                
        self.stop_engine()

    def process_info(self, info, board):
        # Only cache the raw data quickly
        if "multipv" in info:
            idx = info["multipv"]
            self.lines_cache[idx] = info.copy()
        elif "pv" in info:
            self.lines_cache[1] = info.copy()
            
        # THROTTLING: Only do the heavy string building and UI emitting every 100ms
        current_time = time.time()
        if current_time - self._last_emit_time > self._emit_interval:
            self._emit_current_cache(board)
            self._last_emit_time = current_time

    def _emit_current_cache(self, board):
        """Builds strings and emits to UI. Separated from process_info to allow throttling."""
        if not self.lines_cache: return
        
        structured_lines = []
        best_eval_cp = None
        best_depth = 0

        # Process the cached lines
        for idx in sorted(self.lines_cache.keys()):
            if idx > self.multipv: continue
                
            line_data = self.lines_cache[idx]
            extracted = self._extract_line_data(line_data, board)
            if extracted:
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
                mate = score.mate()
                score_str = f"M{mate:+d}"
                cp_val = 10000 if mate > 0 else -10000
            else:
                cp = score.white().score()
                if cp is not None:
                    score_str = f"{cp/100:+.2f}"
                    cp_val = cp
        
        pv = line_info.get("pv", [])
        
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
            "cp_val": cp_val
        }
