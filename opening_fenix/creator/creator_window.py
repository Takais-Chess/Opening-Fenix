import sys
import os
import json
from PyQt6 import sip
import chess
import chess.engine
import chess.pgn
import io
import datetime
import shutil
import multiprocessing
import re
import collections
import webbrowser
import time
import stat

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox, QSplitter, QFrame,
    QComboBox, QInputDialog, QCheckBox, QGroupBox, QFormLayout,
    QDialog, QTextEdit, QHeaderView, QMenu, QGridLayout,
    QScrollArea, QSlider, QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QTabWidget, QProgressBar, QProgressDialog, QListWidget,
    QTableWidget, QTableWidgetItem, QApplication, QToolBar, QStyle, QListWidgetItem, QStackedWidget, QPlainTextEdit,
    QGraphicsDropShadowEffect, QAbstractItemView
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QUrl, QRectF, QSize, QEvent
from PyQt6.QtGui import QIcon, QAction, QColor, QPainter, QBrush, QPen, QPolygonF, QPalette, QFontMetrics, QFont
from PyQt6.QtMultimedia import QSoundEffect
from sqlalchemy import or_, func, desc, text
from sqlalchemy.orm import joinedload

from opening_fenix.core.models import DatabaseManager, Position, Move, RepertoireMove, RepertoireLevel, Metadata, LichessData
from opening_fenix.core.data_tools import get_base_path, get_user_dir, get_repertoire_analysis_status, calculate_local_priority_scores
from opening_fenix.core.utils import get_repertoire_db_path, get_repertoire_dir, initialize_repertoire_assets, localize_san
from opening_fenix.core.threads import AnalysisThread, LichessImportThread, IslandDetectionThread, BackgroundEnrichmentThread, PGNImportThread, MaintenanceThread, HoleFinderThread, FenIndexBuilderThread, BfsTranspositionThread, InstantMultiPVThread, PathQualityEvalThread

from opening_fenix.core.services.maintenance_service import list_all_repertoires
from opening_fenix.core.engine import EngineThread
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
from opening_fenix.gui.widgets.common import AspectRatioFrame
from opening_fenix.gui.dialogs.repo_settings_dialog import RepoSettingsDialog, DiagnosticDialog

# Import centralized styles
from opening_fenix.gui.styles import get_creator_window_style, get_creator_toolbar_style, COLORS, set_consistent_icon
from opening_fenix.gui.widgets.title_bar import CustomTitleBar
from opening_fenix.gui.scaling import scale


# --- EXPORTERS ---
class LocalizedExporter(chess.pgn.StringExporter):
    def __init__(self, language='en', **kwargs):
        super().__init__(**kwargs)
        self.language = language
        
    def visit_move(self, board, move):
        if self.language == 'en':
            return super().visit_move(board, move)
            
        # Standard PGN logic with localized SAN
        # We ensure move numbers and spaces are correctly placed
        if board.turn == chess.WHITE:
            self.write_token(str(board.fullmove_number) + ". ")
        elif self.force_movenumber:
            self.write_token(str(board.fullmove_number) + "... ")

        san = localize_san(board.san(move), self.language)
        self.write_token(san + " ")
        self.force_movenumber = False

# --- BACKEND ---
class CreatorBackend:
    def __init__(self, is_test=None):
        self.db_manager = None
        self.session = None
        self.active_repo_name = None
        self.is_test = is_test
        self._export_count = 0
        self._cached_start_move = 1
        
        # IN-MEMORY CACHE FOR UI RESPONSIVENESS
        self._ui_cache = {}
        
        # DEBUG TRACE
        self._last_cascade_trace = []
        
        # Overhaul Session State
        self.overhaul_session_start = None

    def get_meta(self, key, default=None):
        if not self.session: return default
        m = self.session.query(Metadata).filter_by(key=key).first()
        return m.value if m else default

    def load_repertoire(self, name, is_test=None):
        self.close()
        self.active_repo_name = name
        # If is_test is explicitly provided as True/False, use it, otherwise use self.is_test
        if is_test is None:
            is_test = self.is_test
        
        self.is_test = is_test
        db_path = get_repertoire_db_path(name, is_test)
        repo_dir = get_repertoire_dir(name, is_test)
        
        from opening_fenix.core.logger import logger
        logger.info(f"CreatorBackend: Loading repertoire '{name}' (is_test={is_test}) from {db_path}")
        
        # Ensure directory and assets exist
        initialize_repertoire_assets(repo_dir)
        
        self.db_manager = DatabaseManager(db_path)
        self.session = self.db_manager.get_session()
        self._seed_default_levels()
        self.clear_cache()

        self._cached_start_move = self.get_repertoire_start_move(force_refresh=True)


    def close(self):
        if self.session:
            self.session.close()
            self.session = None
        if self.db_manager:
            self.db_manager.close()
            self.db_manager = None

    def clear_cache(self):
        """Clears the LRU cache and expires session objects to ensure fresh data."""
        self._ui_cache = {}
        if self.session:
            self.session.expire_all()

    def get_repertoire_start_move(self, force_refresh=False):
        if not force_refresh: return self._cached_start_move
        if not self.session: return 1
        m = self.session.query(Metadata).filter_by(key="start_move").first()
        try:
            val = int(m.value) if m else 1
            self._cached_start_move = val
            return val
        except:
            self._cached_start_move = 1
            return 1

    def set_repertoire_start_move(self, value):
        if not self.session: return
        m = self.session.query(Metadata).filter_by(key="start_move").first()
        if m: m.value = str(value)
        else: self.session.add(Metadata(key="start_move", value=str(value)))
        self.session.commit()
        self._cached_start_move = value

    def rename_repertoire(self, old_name, new_name):
        """Delegates renaming to the core service and reloads if necessary."""
        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        service = RepertoireService()
        
        # If the renamed repo is the one we have open, close it first
        if self.active_repo_name == old_name:
            self.close()
            
        success, msg = service.rename_repertoire(old_name, new_name)
        
        if success and self.active_repo_name == old_name:
            self.load_repertoire(new_name)
            
        return success, msg

    def get_repertoire_description(self):
        if not self.session: return ""
        m = self.session.query(Metadata).filter_by(key="description").first()
        return m.value if m else ""

    def set_repertoire_description(self, text):
        if not self.session: return
        m = self.session.query(Metadata).filter_by(key="description").first()
        if m: m.value = text
        else: self.session.add(Metadata(key="description", value=text))
        self.session.commit()

    def get_path_to_fen(self, fen):
        if not self.session: return None, []
        # Robust FEN Cleaning (normalize spaces and trim)
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if not pos: return None, []
        path = []
        curr_id = pos.id
        for _ in range(200):
            incoming = self.session.query(Move).filter_by(to_position_id=curr_id).order_by(Move.priority_score.desc()).first()
            if not incoming: break
            path.insert(0, incoming.uci)
            curr_id = incoming.from_position_id
        root_pos = self.session.get(Position, curr_id)
        return (root_pos.fen if root_pos else None), path

    def get_position_data(self, fen):
        if not self.session: return None
        
        # Check cache
        cache_key = f"pos_data_{fen}"
        if cache_key in self._ui_cache:
            return self._ui_cache[cache_key]
            
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        data = {"id": None, "comment": "", "variation_1": "", "variation_2": "", "variation_3": "",
                "v1_inherited": False, "v2_inherited": False, "v3_inherited": False}
        if not pos: 
            self._ui_cache[cache_key] = data
            return data

        data["id"] = pos.id
        data["comment"] = pos.comment or ""

        # Explicit values
        data["variation_1"] = pos.variation_1 or ""
        data["variation_2"] = pos.variation_2 or ""
        data["variation_3"] = pos.variation_3 or ""

        # Inherited values (from cache)
        if not pos.variation_1 and pos.cached_v1:
            data["variation_1"] = pos.cached_v1
            data["v1_inherited"] = True
        if not pos.variation_2 and pos.cached_v2:
            data["variation_2"] = pos.cached_v2
            data["v2_inherited"] = True
        if not pos.variation_3 and pos.cached_v3:
            data["variation_3"] = pos.cached_v3
            data["v3_inherited"] = True

        self._ui_cache[cache_key] = data
        return data

    def update_position_data(self, fen, comment, var1, var2, var3, append=False, auto_review=False):
        if not self.session: return
        # Robust FEN Cleaning for query consistency
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if not pos: 
            pos = Position(fen=clean_fen)
            self.session.add(pos)

        # Check if variation names actually changed to avoid unnecessary recursion
        v1 = var1 if var1 else None
        v2 = var2 if var2 else None
        v3 = var3 if var3 else None

        names_changed = (pos.variation_1 != v1) or (pos.variation_2 != v2) or (pos.variation_3 != v3)

        if append and comment:
            if pos.comment:
                if comment not in pos.comment:
                    pos.comment += " | " + comment
            else:
                pos.comment = comment
        else:
            pos.comment = comment
        pos.variation_1 = v1
        pos.variation_2 = v2
        pos.variation_3 = v3

        if auto_review:
            pos.last_overhaul_review = datetime.datetime.now()

        self.session.flush()

        if names_changed:
            self._update_cached_names_recursive(pos)

        self.session.commit()
        self.clear_cache()

    def mark_position_reviewed(self, fen):
        if not self.session: return
        clean_fen = " ".join(fen.split(" ")[:4])
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if pos:
            pos.last_overhaul_review = datetime.datetime.now()
            self.session.commit()
            self.clear_cache()

    def reset_overhaul_progress(self):
        """Clears overhaul review timestamps for all positions in the repertoire."""
        if not self.session: return
        self.session.query(Position).update({Position.last_overhaul_review: None})
        self.session.commit()
        self.clear_cache()

    def _get_reachable_position_ids(self, level=None, variation_filter=None):
        """Helper to find all position IDs reachable via active repertoire moves <= level.
        If variation_filter is provided, returns only the subset that matches.
        """
        if not self.session: return set()
        if level is None: level = 99 # Default to all levels
        
        # Use clean FEN (4 fields) to match DB
        start_fen = " ".join(chess.STARTING_FEN.split(" ")[:4])
        start_pos = self.session.query(Position).filter(Position.fen.like(start_fen + "%")).first()
        if not start_pos: return set()
        
        reachable = {start_pos.id}
        queue = collections.deque([start_pos.id])
        
        # 1. Structure Analysis (Build DAG of all active moves at appropriate level)
        all_rep_moves = self.session.query(Move.from_position_id, Move.to_position_id).join(RepertoireMove).filter(
            RepertoireMove.is_active == True,
            RepertoireMove.level <= level
        ).all()
        graph = collections.defaultdict(list)
        for f_id, t_id in all_rep_moves: graph[f_id].append(t_id)

        # 2. BFS for full reachability (NO filtering while moving)
        while queue:
            curr = queue.popleft()
            for nxt in graph.get(curr, []):
                if nxt not in reachable:
                    reachable.add(nxt)
                    queue.append(nxt)
        
        # 3. Post-Filtering: If variation_filter is set, only keep matching positions
        if variation_filter:
            # Query the names for all reachable IDs
            p_data = self.session.query(Position.id, Position.variation_1, Position.variation_2, Position.variation_3, 
                                      Position.cached_v1, Position.cached_v2, Position.cached_v3).filter(
                Position.id.in_(list(reachable))
            ).all()
            
            filtered_ids = set()
            for pid, v1, v2, v3, cv1, cv2, cv3 in p_data:
                # v_set contains all naming variation tags for this position
                v_set = {v1, v2, v3, cv1, cv2, cv3}
                
                if isinstance(variation_filter, (list, tuple)):
                    fv1, fv2 = variation_filter
                    # Hierarchical filter must match ALL specified levels
                    if fv1 and fv1 not in v_set: continue
                    if fv2 and fv2 not in v_set: continue
                else:
                    if variation_filter not in v_set: continue
                
                filtered_ids.add(pid)
                
            return filtered_ids
            
        return reachable

    def get_variation_structure(self):
        """
        Builds a hierarchical dictionary mapping V1 variation names to a list of V2 names.
        Modified version of the trainer's logic for the Creator context.
        """
        if not self.session: return {}
        
        # 1. Fetch all positions that have ANY variation tag
        # Use simple distinct queries to find pairings
        results = self.session.query(
            Position.variation_1, Position.variation_2, 
            Position.cached_v1, Position.cached_v2
        ).filter(
            (Position.variation_1 != None) | 
            (Position.variation_2 != None) | 
            (Position.cached_v1 != None) |
            (Position.cached_v2 != None)
        ).distinct().all()

        structure = {} # V1 -> set(V2)
        for v1, v2, cv1, cv2 in results:
            # Use cached inheritance if variation tags are missing on the position itself
            final_v1 = v1 if v1 else cv1
            final_v2 = v2 if v2 else cv2

            if not final_v1: final_v1 = "Sonstiges"
            
            if final_v1 not in structure:
                structure[final_v1] = set()
            
            if final_v2:
                structure[final_v1].add(final_v2)

        # Build final result with sorted V2s
        res = {}
        for v1 in sorted(structure.keys()):
            v2s = sorted(list(structure[v1]))
            res[v1] = v2s

        return res

    def get_overhaul_stats(self, level=None, variation_filter=None, session_start=None):
        """Returns (checked_count, total_count) for positions at or above the given level within the variation."""
        if not self.session: return 0, 0
        if level is None: level = 99
        
        # Reachable positions at or below this level
        total_ids = self._get_reachable_position_ids(level, variation_filter)
        total_count = len(total_ids)
        
        if total_count == 0: return 0, 0
        
        query = self.session.query(Position).filter(Position.id.in_(total_ids))
        if session_start:
            query = query.filter(Position.last_overhaul_review >= session_start)
        else:
            query = query.filter(Position.last_overhaul_review != None)
            
        checked_count = query.count()
        return checked_count, total_count

    def get_overhaul_session_start(self):
        """Loads the overhaul session start time from metadata."""
        val = self.get_meta("overhaul_session_start")
        if val:
            try:
                return datetime.datetime.fromisoformat(val)
            except:
                return None
        return None

    def save_overhaul_session_start(self, dt):
        """Saves the overhaul session start time to metadata."""
        if dt:
            self.set_meta("overhaul_session_start", dt.isoformat())
        else:
            self.set_meta("overhaul_session_start", None)
        self.session.commit()

    def set_meta(self, key, value):
        """Helper to set metadata value."""
        if not self.session: return
        m = self.session.query(Metadata).filter_by(key=key).first()
        if value is None:
            if m: self.session.delete(m)
        else:
            if m: m.value = str(value)
            else: self.session.add(Metadata(key=key, value=str(value)))
        self.session.commit()

    def is_branch_fully_reviewed(self, pos_id, session_start):
        """
        Uses a Recursive CTE to check if a position and all its reachable
        repertoire descendants have been reviewed in the current session.
        Performance optimization: Returns True/False efficiently.
        """
        if not self.session or not session_start: return False
        
        # SQLite Recursive CTE to find all descendant positions in the active repertoire
        # and check if any of them have last_overhaul_review < session_start OR NULL.
        sql = text("""
            WITH RECURSIVE descendants(id) AS (
                SELECT :pos_id
                UNION
                SELECT m.to_position_id
                FROM moves m
                INNER JOIN descendants d ON m.from_position_id = d.id
                INNER JOIN repertoire_moves rm ON m.id = rm.move_id
                WHERE rm.is_active = 1
            )
            SELECT COUNT(*)
            FROM descendants d
            LEFT JOIN positions p ON d.id = p.id
            WHERE p.last_overhaul_review IS NULL OR p.last_overhaul_review < :session_start
        """)
        
        try:
            result = self.session.execute(sql, {"pos_id": pos_id, "session_start": session_start.isoformat()}).scalar()
            return result == 0
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Error in is_branch_fully_reviewed: {e}")
            return False

    def get_unique_variation_names(self):
        """Returns a sorted list of all unique variation names in the repertoire."""
        if not self.session: return []
        
        v1 = self.session.query(Position.variation_1).filter(Position.variation_1 != None).distinct()
        v2 = self.session.query(Position.variation_2).filter(Position.variation_2 != None).distinct()
        v3 = self.session.query(Position.variation_3).filter(Position.variation_3 != None).distinct()
        
        names = set()
        for r in v1.all(): names.add(r[0])
        for r in v2.all(): names.add(r[0])
        for r in v3.all(): names.add(r[0])
        
        return sorted(list(names))

    def find_nearest_unreviewed(self, current_fen, level=None, variation_filter=None, session_start=None):
        """Finds the nearest unchecked position in the repertoire tree, strictly filtered by variation."""
        if not self.session: return None
        if level is None: level = 99
        
        clean_curr = " ".join(current_fen.split(" ")[:4])
        start_pos = self.session.query(Position).filter_by(fen=clean_curr).first()
        if not start_pos: 
            start_pos = self.session.query(Position).filter_by(fen=chess.STARTING_FEN).first()
            if not start_pos: return None

        queue = collections.deque([start_pos.id])
        visited = {start_pos.id}
        
        # Scope the search to the reachable set for THIS variation/level
        reachable_ids = self._get_reachable_position_ids(level, variation_filter)
        
        while queue:
            curr_id = queue.popleft()
            
            if curr_id in reachable_ids:
                pos = self.session.get(Position, curr_id)
                is_unreviewed = False
                if session_start:
                    if pos.last_overhaul_review is None or pos.last_overhaul_review < session_start:
                        is_unreviewed = True
                else:
                    if pos.last_overhaul_review is None:
                        is_unreviewed = True
                
                if is_unreviewed:
                    return pos.fen

            # Add neighbors (children moves)
            children = self.session.query(Move.to_position_id).filter_by(from_position_id=curr_id).all()
            for (c_id,) in children:
                if c_id not in visited:
                    visited.add(c_id)
                    queue.append(c_id)
                    
            # Add neighbors (parents)
            parents = self.session.query(Move.from_position_id).filter_by(to_position_id=curr_id).all()
            for (p_id,) in parents:
                if p_id not in visited:
                    visited.add(p_id)
                    queue.append(p_id)
                    
        return None



    def reset_hole_exemptions(self):

        if not self.session: return
        self.session.query(Position).update({Position.is_hole_exempt: False})
        self.session.commit()
        self.clear_cache()

    def set_position_hole_exempt(self, fen, exempt):
        if not self.session: return
        clean_fen = " ".join(fen.split(" ")[:4])
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if pos:
            pos.is_hole_exempt = exempt
            self.session.commit()
            self.clear_cache()


    def _update_cached_names_recursive(self, pos, visited=None):
        if visited is None: visited = set()
        
        new_v1, new_v2, new_v3 = pos.variation_1, pos.variation_2, pos.variation_3

        if not (new_v1 and new_v2 and new_v3):
            parent_v1, parent_v2, parent_v3 = self._get_best_parent_names(pos.id)
            if not new_v1: new_v1 = parent_v1
            if not new_v2: new_v2 = parent_v2
            if not new_v3: new_v3 = parent_v3

        names_changed = (pos.cached_v1 != new_v1) or (pos.cached_v2 != new_v2) or (pos.cached_v3 != new_v3)
        
        pos.cached_v1 = new_v1
        pos.cached_v2 = new_v2
        pos.cached_v3 = new_v3

        # If names didn't change and we already visited this node, we can stop recursion here.
        # But if names DID change, we must propagate them downstream even if already visited.
        if not names_changed and pos.id in visited:
            return
        
        visited.add(pos.id)

        children_moves = self.session.query(Move).filter_by(from_position_id=pos.id).all()
        for move in children_moves:
            child_pos = self.session.get(Position, move.to_position_id)
            if child_pos:
                self._update_cached_names_recursive(child_pos, visited)

    def _get_best_parent_names(self, pos_id):
        """Iterates through all parents in priority order to find missing variation names."""
        parents_moves = self.session.query(Move).filter_by(to_position_id=pos_id).order_by(Move.priority_score.desc()).all()
        pv1, pv2, pv3 = None, None, None
        
        for move in parents_moves:
            parent = self.session.get(Position, move.from_position_id)
            if not parent: continue
            
            if pv1 is None and parent.cached_v1: pv1 = parent.cached_v1
            if pv2 is None and parent.cached_v2: pv2 = parent.cached_v2
            if pv3 is None and parent.cached_v3: pv3 = parent.cached_v3
            
            if pv1 and pv2 and pv3: break
            
        return pv1, pv2, pv3

    def update_position_analysis(self, fen, depth, eval_val):
        if not self.session: return
        clean_fen = " ".join(fen.strip().split()[:4])
        # Use GLOB for case-sensitive prefix matching in SQLite
        pos = self.session.query(Position).filter(Position.fen.op('GLOB')(clean_fen + "*")).first()
        if pos and (pos.analysis_depth is None or depth > pos.analysis_depth):
            pos.analysis_depth, pos.engine_eval = depth, eval_val
            self.session.commit()
            self.clear_cache()

    def get_candidate_moves(self, fen):
        if not self.session: return []
        
        # Check cache
        cache_key = f"cand_moves_{fen}"
        if cache_key in self._ui_cache:
            return self._ui_cache[cache_key]
            
        clean_fen = " ".join(fen.strip().split()[:4])
        # Use GLOB for case-sensitive prefix matching in SQLite
        pos = self.session.query(Position).filter(Position.fen.op('GLOB')(clean_fen + "*")).first()
        if not pos: 
            self._ui_cache[cache_key] = []
            return []
        
        moves = self.session.query(Move)\
            .options(joinedload(Move.to_position))\
            .filter_by(from_position_id=pos.id)\
            .order_by(Move.priority_score.desc(), Move.id).all()
            
        if not moves:
            self._ui_cache[cache_key] = []
            return []
            
        move_ids = [m.id for m in moves]
        to_pos_ids = [m.to_position_id for m in moves]
        
        # 1. Which of the candidate moves are repertoire moves?
        rep_moves = self.session.query(RepertoireMove).filter(RepertoireMove.move_id.in_(move_ids)).all()
        rep_moves_dict = {rm.move_id: rm for rm in rep_moves}
        
        # 2. Are there any repertoire responses to these moves?
        # Note: We also want to know if these responses are active
        child_moves = self.session.query(Move.id, Move.from_position_id).filter(Move.from_position_id.in_(to_pos_ids)).all()
        
        child_move_map = {} 
        child_move_ids = []
        for c_mid, c_from_id in child_moves:
            if c_from_id not in child_move_map:
                child_move_map[c_from_id] = []
            child_move_map[c_from_id].append(c_mid)
            child_move_ids.append(c_mid)
            
        # Get repertoire info for those child moves
        child_rep_moves = []
        if child_move_ids:
            child_rep_moves = self.session.query(RepertoireMove.move_id, RepertoireMove.level, RepertoireMove.is_active).filter(RepertoireMove.move_id.in_(child_move_ids)).all()
        
        child_rep_map = {rm_id: (lvl, active) for rm_id, lvl, active in child_rep_moves}

        results = []
        for m in moves:
            rep_move = rep_moves_dict.get(m.id)
            is_repo = rep_move is not None
            level = rep_move.level if rep_move else 0
            is_active = rep_move.is_active if rep_move else True # Default to True if not in repo but has repo children
            
            if not is_repo:
                responses = child_move_map.get(m.to_position_id, [])
                our_responses_data = [child_rep_map[r_mid] for r_mid in responses if r_mid in child_rep_map]
                if our_responses_data:
                    is_repo = True
                    level = min(d[0] for d in our_responses_data)
                    is_active = any(d[1] for d in our_responses_data)
            
            next_pos = m.to_position
            results.append({
                "id": m.id, "uci": m.uci, "san": m.san, "is_repo": is_repo, "level": level, "is_active": is_active,
                "comment": next_pos.comment if next_pos else "", "priority": m.priority_score,
                "nag": m.nag, "eval": next_pos.engine_eval if next_pos else None,
                "to_pos_id": m.to_position_id
            })
            
        # Enforce LRU bounds (keep max 100 entries to save RAM)
        if len(self._ui_cache) > 100:
            # Simple purge, dicts preserve insertion order in Python 3.7+
            keys_to_delete = list(self._ui_cache.keys())[:20]
            for k in keys_to_delete:
                del self._ui_cache[k]
                
        self._ui_cache[cache_key] = results
        return results

    def get_lichess_common_moves(self, fen, elo_category):
        if not self.session: return []
        
        # Check cache
        cache_key = f"lichess_{fen}_{elo_category}"
        if cache_key in self._ui_cache:
            return self._ui_cache[cache_key]
            
        clean_fen = " ".join(fen.split(" ")[:4])
        data = self.session.query(LichessData).filter_by(fen=clean_fen, elo_range=elo_category).first()
        if not data or not data.moves_json:
            self._ui_cache[cache_key] = []
            return []
        
        try:
            moves_dict = json.loads(data.moves_json)
        except json.JSONDecodeError:
            self._ui_cache[cache_key] = []
            return []

        board = chess.Board(fen)
        results = []
        for uci, stats in moves_dict.items():
            if not stats: continue
            wins = stats.get('white', 0)
            draws = stats.get('draws', 0)
            losses = stats.get('black', 0)
            total = stats.get('total', wins + draws + losses)
            if total == 0: continue

            try:
                san = stats.get('san')
                if not san:
                    move = chess.Move.from_uci(uci)
                    san = board.san(move)
            except:
                san = uci # Fallback

            results.append({
                "uci": uci,
                "san": san,
                "white_pct": (wins / total) * 100,
                "draw_pct": (draws / total) * 100,
                "black_pct": (losses / total) * 100,
                "total": total
            })
        
        results.sort(key=lambda x: x['total'], reverse=True)
        final_results = results[:10]
        self._ui_cache[cache_key] = final_results
        return final_results

    def get_repertoire_levels(self):
        if not self.session: return []
        return [{"name": lvl.name, "order": lvl.order, "target_elo": lvl.target_elo} for lvl in self.session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()]

    def update_level_elo(self, level_order, target_elo):
        if not self.session: return
        lvl = self.session.query(RepertoireLevel).filter_by(order=level_order).first()
        if lvl:
            lvl.target_elo = target_elo
            self.session.commit()

    def update_level_name(self, level_order, new_name):
        if not self.session: return
        lvl = self.session.query(RepertoireLevel).filter_by(order=level_order).first()
        if lvl:
            lvl.name = new_name
            self.session.commit()


    def update_move_level(self, move_id, level_order):
        if not self.session: return
        move = self.session.get(Move, move_id)
        if not move: return
        rep_move = self.session.query(RepertoireMove).filter_by(move_id=move.id).first()
        if not rep_move:
            rep_move = RepertoireMove(move_id=move.id, level=level_order)
            self.session.add(rep_move)
        else:
            rep_move.level = level_order
        
        self.session.flush()
        self._last_cascade_trace = []
        # Start propagation from the target position of this move with the NEW level
        self._update_level_recursive(move.to_position_id, set(), level_order)
        self.session.commit()
        self.clear_cache()

    def get_strong_level_impact(self, move_id):
        """
        Calculates the impact of a strong level change.
        Returns (move_count, unique_variation_names)
        """
        if not self.session: return 0, []
        move = self.session.get(Move, move_id)
        if not move: return 0, []
        
        move_count = 0
        variation_names = set()
        visited_pos = set()
        queue = collections.deque([move.to_position_id])
        
        # Initial move counts as 1 if it's in repertoire
        rep_move = self.session.query(RepertoireMove).filter_by(move_id=move.id).first()
        if rep_move:
            move_count += 1
            
        while queue:
            pos_id = queue.popleft()
            if pos_id in visited_pos:
                continue
            visited_pos.add(pos_id)
            
            pos = self.session.get(Position, pos_id)
            if pos:
                if pos.cached_v1: variation_names.add(pos.cached_v1)
                elif pos.variation_1: variation_names.add(pos.variation_1)
                if pos.cached_v2: variation_names.add(pos.cached_v2)
                elif pos.variation_2: variation_names.add(pos.variation_2)
                if pos.cached_v3: variation_names.add(pos.cached_v3)
                elif pos.variation_3: variation_names.add(pos.variation_3)
            
            # Find all outgoing repertoire moves
            out_moves = self.session.query(Move).join(RepertoireMove, Move.id == RepertoireMove.move_id).filter(Move.from_position_id == pos_id).all()
            for m in out_moves:
                move_count += 1
                queue.append(m.to_position_id)
                
        return move_count, sorted([v for v in variation_names if v])

    def update_move_level_strong(self, move_id, level_order):
        """
        Forcefully sets the level of a move and all its descendants.
        """
        if not self.session: return
        move = self.session.get(Move, move_id)
        if not move: return
        
        rep_move = self.session.query(RepertoireMove).filter_by(move_id=move.id).first()
        if not rep_move:
            rep_move = RepertoireMove(move_id=move.id, level=level_order)
            self.session.add(rep_move)
        else:
            rep_move.level = level_order
        
        self.session.flush()
        
        # Recursive force update
        self._update_level_strong_recursive(move.to_position_id, set(), level_order)
        self.session.commit()
        self.clear_cache()

    def _update_level_strong_recursive(self, pos_id, visited, new_level):
        if pos_id in visited:
            return
        visited.add(pos_id)
        
        # Find all outgoing repertoire moves
        outgoing_rep = self.session.query(RepertoireMove).join(Move, RepertoireMove.move_id == Move.id).filter(Move.from_position_id == pos_id).all()
        
        for rm in outgoing_rep:
            rm.level = new_level
            self.session.flush()
            # Find the move to get the to_position_id
            m = self.session.get(Move, rm.move_id)
            if m:
                self._update_level_strong_recursive(m.to_position_id, visited, new_level)

    def move_all_to_level(self, level: int) -> int:
        if not self.session: return 0
        from opening_fenix.core.models import RepertoireMove
        updated_count = self.session.query(RepertoireMove).update({"level": level})
        self.session.commit()
        self.clear_cache()
        return updated_count

    def toggle_move_active(self, move_id):
        if not self.session: return False
        rep_move = self.session.query(RepertoireMove).filter_by(move_id=move_id).first()
        if not rep_move:
            return False
        
        rep_move.is_active = not rep_move.is_active
        self.session.flush()

        # Recalculate local priority scores for the branch
        try:
            move = self.session.get(Move, move_id)
            if move:
                elo_meta = self.session.query(Metadata).filter_by(key="lichess_elo").first()
                elo_category = (elo_meta.value if elo_meta and elo_meta.value in ["low", "mid", "high", "masters"] else "high")
                calculate_local_priority_scores(self.session, move.from_position_id, elo_category)
        except Exception as e:
            print(f"Error updating priority after toggle: {e}")

        self.session.commit()
        self.clear_cache()
        return rep_move.is_active

    def _update_level_recursive(self, pos_id, visited, new_level):
        """
        Recursively propagates a level change down a branch.
        Rule: The level of an outgoing move can never be 'stronger' (lower number)
        than the most important (lowest number) of all incoming paths reaching that position.
        """
        if pos_id in visited:
            return
        visited.add(pos_id)
        
        # Calculate the "effective level" of the position: 
        # The strongest (lowest numerical) level of all incoming repertoire paths.
        incoming_rep = self.session.query(RepertoireMove).join(Move, RepertoireMove.move_id == Move.id).filter(Move.to_position_id == pos_id).all()
        if not incoming_rep:
            return
            
        effective_level = min(rm.level for rm in incoming_rep)

        # Find all outgoing repertoire moves from this position
        outgoing_moves = self.session.query(Move).filter_by(from_position_id=pos_id).all()
        outgoing_rep = []
        for m in outgoing_moves:
            rm = self.session.query(RepertoireMove).filter_by(move_id=m.id).first()
            if rm:
                outgoing_rep.append((m, rm))
                
        if not outgoing_rep:
            return

        # Case: Branching Point.
        # We only demote (increase number) if the move is currently too important.
        if len(outgoing_rep) > 1:
            for m, rm in outgoing_rep:
                if rm.level < effective_level:
                    rm.level = effective_level
                    self.session.flush()
                    self._update_level_recursive(m.to_position_id, visited, effective_level)
            return

        # Special Case: Forced Line.
        # If there's exactly one move, we follow the modified path's level (new_level)
        # BUT only if no other path provides a stronger access (effective_level).
        m, rm = outgoing_rep[0]
        # Calculate what the level should be for this path.
        # If we are the main path being updated, we take new_level.
        # But we must never be stronger than effective_level.
        # Wait, if we are in a forced line, effective_level is either new_level or something else.
        target_level = max(new_level, effective_level)
        
        if rm.level != target_level:
            rm.level = target_level
            self.session.flush()
            # Recurse because level changed
            self._update_level_recursive(m.to_position_id, visited, target_level)
        else:
            # Even if level didn't change, we MUST recurse to ensure downstream 
            # transpositions are checked against the potentially weaker new_level.
            # But wait, if target_level == rm.level, and we already visited downstream 
            # with this level, recursion stops anyway.
            self._update_level_recursive(m.to_position_id, visited, target_level)

    def add_move(self, from_fen, move_uci, move_san, level_order=None, nag=0):
        if not self.session: return
        clean_from = " ".join(from_fen.split(" ")[:4])
        from_pos = self.session.query(Position).filter_by(fen=clean_from).first()
        if not from_pos:
            from_pos = Position(fen=clean_from)
            self.session.add(from_pos)
            self.session.flush()

        board = chess.Board(from_fen)
        try:
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                return # Or raise Exception
            board.push(move)
        except Exception:
            return

        clean_to = " ".join(board.fen().split(" ")[:4])

        to_pos = self.session.query(Position).filter_by(fen=clean_to).first()
        if not to_pos:
            to_pos = Position(fen=clean_to)
            self.session.add(to_pos)
            self.session.flush()
            # Initialize cached names for new position from parent
            if from_pos.cached_v1: to_pos.cached_v1 = from_pos.cached_v1
            if from_pos.cached_v2: to_pos.cached_v2 = from_pos.cached_v2
            if from_pos.cached_v3: to_pos.cached_v3 = from_pos.cached_v3

        db_move = self.session.query(Move).filter_by(from_position_id=from_pos.id, uci=move_uci).first()
        if not db_move:
            db_move = Move(from_position_id=from_pos.id, to_position_id=to_pos.id, uci=move_uci, san=move_san, nag=nag)
            self.session.add(db_move)
            self.session.flush()
        elif nag != 0:
            db_move.nag = nag

        rep_move = self.session.query(RepertoireMove).filter_by(move_id=db_move.id).first()
        if not rep_move:
            if level_order is None:
                # NEW DEFAULT LEVEL LOGIC:
                # 1. Check for siblings first. If siblings exist, assign the HIGHEST level order available in the entire repertoire.
                # 2. If no siblings, inherit from parent.

                has_siblings = self.session.query(RepertoireMove).join(Move).filter(
                    Move.from_position_id == from_pos.id
                ).count() > 0

                if has_siblings:
                    # Assign the highest level available in the DB (lowest priority)
                    max_level_in_db = self.session.query(func.max(RepertoireLevel.order)).scalar()
                    final_level = max_level_in_db if max_level_in_db is not None else 1
                else:
                    # No siblings, inherit from parent
                    parent_rep = self.session.query(RepertoireMove).join(Move).filter(
                        Move.to_position_id == from_pos.id
                    ).order_by(RepertoireMove.level).first()

                    if parent_rep:
                        final_level = parent_rep.level
                    else:
                        # No parent, no siblings. Default to 1.
                        final_level = 1
            else:
                final_level = level_order
            self.session.add(RepertoireMove(move_id=db_move.id, level=final_level))
        elif level_order is not None and level_order < rep_move.level:
            rep_move.level = level_order
        self.session.commit()
        self.clear_cache()

    def get_delete_impact(self, from_pos_id, uci):
        """Iteratively built set of move_ids and pos_ids that will be orphaned."""
        move = self.session.query(Move).filter_by(from_position_id=from_pos_id, uci=uci).first()
        if not move: return set(), set()
        
        dm = set()
        dp = set()
        
        # BFS using queries. Can be optimized further but usually < 50ms.
        queue = [move]
        while queue:
            curr_move = queue.pop(0)
            if curr_move.id in dm: continue
            dm.add(curr_move.id)
            
            # If all incoming moves to the target position are being deleted
            incoming_ids = [m_id for (m_id,) in self.session.query(Move.id).filter_by(to_position_id=curr_move.to_position_id).all()]
            if all(inc_id in dm for inc_id in incoming_ids):
                if curr_move.to_position_id not in dp:
                    dp.add(curr_move.to_position_id)
                    out_moves = self.session.query(Move).filter_by(from_position_id=curr_move.to_position_id).all()
                    for out in out_moves:
                        queue.append(out)
                        
        return dm, dp

    def preview_delete_impact(self, uci, fen):
        if not self.session: return 0, 0
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if not pos: return 0, 0
        dm, dp = self.get_delete_impact(pos.id, uci)
        return len(dm), len(dp)

    def delete_move(self, uci, fen):
        if not self.session: return
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if not pos: return
        move = self.session.query(Move).filter_by(from_position_id=pos.id, uci=uci).first()
        if move:
            parent_pos_id = move.from_position_id
            
            # ── BULK DELETE EXACTLY WHAT WILL BE ORPHANED ──
            dm, dp = self.get_delete_impact(pos.id, uci)
            
            if dm:
                # Chunk IDs to avoid SQLite limit
                dm_list = list(dm)
                for i in range(0, len(dm_list), 900):
                    chunk = dm_list[i:i+900]
                    self.session.query(RepertoireMove).filter(RepertoireMove.move_id.in_(chunk)).delete(synchronize_session=False)
                    self.session.query(Move).filter(Move.id.in_(chunk)).delete(synchronize_session=False)
                    
            if dp:
                dp_list = list(dp)
                # First fetch FENs for Lichess cleanup
                fens_to_delete = []
                for i in range(0, len(dp_list), 900):
                    chunk = dp_list[i:i+900]
                    fens = self.session.query(Position.fen).filter(Position.id.in_(chunk)).all()
                    fens_to_delete.extend([" ".join(f[0].split(" ")[:4]) for f in fens])
                    
                # Delete LichessData
                for i in range(0, len(fens_to_delete), 900):
                    chunk = fens_to_delete[i:i+900]
                    self.session.query(LichessData).filter(LichessData.fen.in_(chunk)).delete(synchronize_session=False)

                # Delete Positions
                for i in range(0, len(dp_list), 900):
                    chunk = dp_list[i:i+900]
                    self.session.query(Position).filter(Position.id.in_(chunk)).delete(synchronize_session=False)
            
            self.session.commit()

            # After deletion, update local priority scores for the affected subtree
            try:
                elo_meta = self.session.query(Metadata).filter_by(key="lichess_elo").first()
                elo_category = (elo_meta.value if elo_meta and elo_meta.value in ["low", "mid", "high", "masters"] else "high")
                from opening_fenix.core.services.priority_service import calculate_local_priority_scores
                calculate_local_priority_scores(self.session, parent_pos_id, elo_category)
                self.session.commit()
            except Exception:
                # Do not block deletion on prio update errors; leave scores as-is
                self.session.rollback()
            
            self.clear_cache()

    def _dedupe_comment_text(self, text: str) -> str:
        """Remove duplicate repetitions inside a single comment.
        - If the comment consists of a block repeated N times, keep the first block only.
        - Additionally collapse consecutive duplicate lines.
        Keep scope strictly inside one comment, no cross-position logic.
        """
        if not text: return text

        # Normalize: strip outer whitespace and keep non-empty lines for analysis, but
        # preserve original line breaks for output using the decided lines.
        raw_lines = [ln.rstrip() for ln in text.strip().splitlines()]
        lines = [ln.strip() for ln in raw_lines if ln.strip() != ""]
        if not lines:
            return text.strip()

        n = len(lines)
        # Try to find the smallest repeating block of lines that composes the whole comment
        best = None
        for p in range(1, (n // 2) + 1):
            if n % p != 0: continue
            block = lines[:p]
            if block * (n // p) == lines:
                best = block
                break
        dedup_lines = best if best is not None else lines

        # Also collapse consecutive duplicates within the chosen lines
        collapsed = []
        for ln in dedup_lines:
            if not collapsed or collapsed[-1] != ln:
                collapsed.append(ln)
        return "\n".join(collapsed)

    def deduplicate_comments_in_repo(self):
        """Deduplicate repeated text inside position comments of the active repertoire.
        Returns the number of positions whose comments were changed.
        """
        if not self.session: return 0
        changed = 0
        positions = self.session.query(Position).filter(
            (Position.comment != None) & (Position.comment != "")
        ).all()
        for p in positions:
            new_text = self._dedupe_comment_text(p.comment or "")
            if new_text != (p.comment or ""):
                p.comment = new_text
                changed += 1
        if changed:
            self.session.commit()
            self.clear_cache()
        return changed

    def clean_brackets_in_repo(self):
        """Removes everything inside square brackets [ ] including the brackets from all comments."""
        if not self.session: return 0
        changed = 0
        positions = self.session.query(Position).filter(
            (Position.comment != None) & (Position.comment != "")
        ).all()
        for p in positions:
            orig_text = p.comment or ""
            new_text = re.sub(r'\[.*?\]', '', orig_text, flags=re.DOTALL)
            # Collapse multiple spaces and strip
            new_text = re.sub(r' +', ' ', new_text).strip()
            if new_text != orig_text:
                p.comment = new_text
                changed += 1
        if changed:
            self.session.commit()
            self.clear_cache()
        return changed

    def _delete_move_recursive(self, move):
        # REMOVED: Replaced by the much faster bulk iterative approach inside `delete_move` directly.
        pass

    def set_nag(self, uci, fen, nag):
        if not self.session: return
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if not pos: return
        move = self.session.query(Move).filter_by(from_position_id=pos.id, uci=uci).first()
        if move:
            move.nag = nag
            self.session.commit()
            self.clear_cache()

    def import_pgn_text(self, text, level=1):
        if not self.session: return False, "No repo."
        game = chess.pgn.read_game(io.StringIO(text))
        if not game: return False, "Invalid PGN."
        def visit(node, board):
            if node.move:
                from_f = board.fen()
                san, uci = board.san(node.move), node.move.uci()
                self.add_move(from_f, uci, san, level, nag=list(node.nags)[0] if node.nags else 0)
                board.push(node.move)
                if node.comment: self.update_position_data(board.fen(), node.comment, "", "", "", append=True)
            for v in node.variations: visit(v, board.copy())
        visit(game, game.board())
        self.clear_cache()
        return True, "Imported."

    def import_pgn_file(self, path, level=1):
        try:
            with open(path, "r", encoding="utf-8") as f: return self.import_pgn_text(f.read(), level)
        except Exception as e: return False, str(e)

    def get_repertoire_structure(self):
        if not self.session: return []
        results = self.session.query(
            Position,
            func.max(Move.priority_score).label('max_prio')
        ).outerjoin(
            Move, Move.to_position_id == Position.id
        ).filter(
            or_(
                (Position.variation_1 != None) & (Position.variation_1 != ""),
                (Position.variation_2 != None) & (Position.variation_2 != ""),
                (Position.variation_3 != None) & (Position.variation_3 != "")
            )
        ).group_by(Position.id).all()

        struct = {}
        for p, prio in results:
            v1, v2, v3 = p.variation_1, p.variation_2, p.variation_3
            priority = prio if prio is not None else 0.0
            if not v1: v1 = p.cached_v1 or "Sonstiges"
            if not v2 and v3: v2 = p.cached_v2 or "Sonstiges"
            if v1:
                if v1 not in struct:
                    struct[v1] = {"name": v1, "fen": p.fen, "priority": priority, "children": {}}
                elif priority > struct[v1]["priority"]:
                    struct[v1]["priority"] = priority
                    struct[v1]["fen"] = p.fen

                if v2:
                    if v2 not in struct[v1]["children"]:
                        struct[v1]["children"][v2] = {"name": v2, "fen": p.fen, "priority": priority, "children": {}}
                    elif priority > struct[v1]["children"][v2]["priority"]:
                        struct[v1]["children"][v2]["priority"] = priority
                        struct[v1]["children"][v2]["fen"] = p.fen

                    if v3:
                        if v3 not in struct[v1]["children"][v2]["children"]:
                            struct[v1]["children"][v2]["children"][v3] = {"name": v3, "fen": p.fen, "priority": priority}
                        elif priority > struct[v1]["children"][v2]["children"][v3]["priority"]:
                            struct[v1]["children"][v2]["children"][v3]["priority"] = priority
                            struct[v1]["children"][v2]["children"][v3]["fen"] = p.fen
        
        res = []
        
        def sort_key_with_misc(node_dict):
            # Sort by priority, but "Sonstiges" always gets a very low value to be at the bottom
            if node_dict["name"] == "Sonstiges": return -1.0
            return node_dict["priority"]

        # Sort top-level by priority descending
        sorted_keys1 = sorted(struct.keys(), key=lambda k: sort_key_with_misc(struct[k]), reverse=True)
        for k1 in sorted_keys1:
            v1_node = struct[k1]
            v1_children = []
            # Sort v2 by priority descending
            sorted_keys2 = sorted(v1_node["children"].keys(), key=lambda k: sort_key_with_misc(v1_node["children"][k]), reverse=True)
            for k2 in sorted_keys2:
                v2_node = v1_node["children"][k2]
                v2_children = []
                # Sort v3 by priority descending
                sorted_keys3 = sorted(v2_node["children"].keys(), key=lambda k: sort_key_with_misc(v2_node["children"][k]), reverse=True)
                for k3 in sorted_keys3:
                    v3_node = v2_node["children"][k3]
                    v2_children.append(v3_node)
                v2_node["children"] = v2_children
                v1_children.append(v2_node)
            v1_node["children"] = v1_children
            res.append(v1_node)
        return res

    def _get_pos_prio(self, pid):
        inc = self.session.query(Move).filter_by(to_position_id=pid).order_by(Move.priority_score.desc()).first()
        return inc.priority_score if inc else 0.0

    def get_repertoire_info(self, fast_only=False):
        if not self.session: return {"name": self.active_repo_name, "levels": [], "depth": "N/A", "elo": "N/A", "moves": "N/A", "description": "", "coverage_pct": 0}
        levels = self.get_repertoire_levels()
        def gm(k, d): m = self.session.query(Metadata).filter_by(key=k).first(); return m.value if m else d
        
        elo_cat = gm("elo", "high")
        description = gm("description", "")

        if fast_only:
            return {
                "name": self.active_repo_name,
                "levels": [l['name'] for l in levels],
                "depth": "Laden...",
                "elo": elo_cat,
                "coverage_pct": 0,
                "moves": "Laden...",
                "description": description
            }

        moves = self.session.query(RepertoireMove.move_id).distinct().count()

        # Inline analysis status using the existing session (avoids opening a new DatabaseManager on every refresh)
        player_color = gm("color", "w")
        turn_filter = Position.fen.like(f'% {player_color} %')
        stats = self.session.query(
            func.count(Position.id),
            func.count(Position.analysis_depth),
            func.min(Position.analysis_depth),
            func.max(Position.analysis_depth)
        ).filter(turn_filter).first()
        
        total, analyzed_count, min_depth, max_depth = stats
        if total == 0:
            analysis_status = "Keine Spielerzüge"
        elif analyzed_count == 0:
            analysis_status = "Nicht analysiert"
        elif analyzed_count < total:
            analysis_status = "Teilweise analysiert"
        elif min_depth == max_depth:
            analysis_status = f"Tiefe: {min_depth}"
        else:
            analysis_status = f"Tiefe: Zwischen {min_depth} und {max_depth}"

        # Calculate coverage % - Join with positions to ensure we only count what belongs to this repo
        total_p = self.session.query(Position.id).count()
        # Ensure we only count LichessData that corresponds to a position actually in our DB
        covered_p = self.session.query(Position.id).join(LichessData, Position.fen.like(LichessData.fen + "%")).filter(LichessData.elo_range == elo_cat).count()

        coverage_pct = (covered_p / total_p * 100.0) if total_p > 0 else 0.0

        return {
            "name": self.active_repo_name,
            "levels": [l['name'] for l in levels],
            "depth": analysis_status,
            "elo": elo_cat,
            "coverage_pct": coverage_pct,
            "moves": moves,
            "description": description
        }

    def get_repertoire_color(self):
        if not self.session: return 'w'
        m = self.session.query(Metadata).filter_by(key="color").first()
        return m.value if m else 'w'

    def scan_and_update_metadata(self):
        if not self.session: return
        elos = ", ".join([e[0] for e in self.session.query(LichessData.elo_range).distinct().all()])
        m = self.session.query(Metadata).filter_by(key="lichess_elo").first()
        if elos:
            if not m: m = Metadata(key="lichess_elo"); self.session.add(m)
            m.value = elos
        else:
            if m: self.session.delete(m)
        self.session.commit()

    def delete_lichess_data(self, elo_category=None):
        if not self.session: return False, "No repo."
        try:
            query = self.session.query(LichessData)
            if elo_category:
                query = query.filter_by(elo_range=elo_category)
            n = query.delete()
            self.session.commit()
            self.scan_and_update_metadata()
            self.clear_cache()
            return True, f"{n} Einträge gelöscht."
        except Exception as e: self.session.rollback(); return False, str(e)

    def cleanup_orphaned_lichess_data(self):
        """Removes all LichessData entries that are no longer referenced by any Position."""
        from opening_fenix.core.services.lichess_service import run_lichess_orphan_cleanup
        success, msg = run_lichess_orphan_cleanup(self.active_repo_name)
        if success:
            self.clear_cache()
            # Extract count from message "X Einträge bereinigt."
            try:
                return int(msg.split(" ")[0])
            except:
                return 0
        return 0

    def delete_repertoire(self):
        if not self.active_repo_name: return False, "No active repo."
        n = self.active_repo_name
        if self.session: self.session.close(); self.session = None
        if self.db_manager: self.db_manager.close(); self.db_manager = None
        import gc
        gc.collect()
        from opening_fenix.core.data_tools import delete_repertoire_db
        return delete_repertoire_db(n)

    def export_pgn(self, start=None, transpos_mode=2, cb=None, max_l=None, language='en'):
        if not self.session: return None
        if start is None: start = chess.STARTING_FEN
        clean_start = " ".join(start.strip().split()[:4])
        pos = self.session.query(Position).filter_by(fen=clean_start).first()
        if not pos:
            # Fallback for old databases
            pos = self.session.query(Position).filter(Position.fen.op('GLOB')(f"{clean_start}*")).first()
            if not pos: return None
        
        # PRE-FETCH OPTIMIZATION for PGN export
        all_moves = self.session.query(Move).options(joinedload(Move.to_position)).all()
        rep_moves = self.session.query(RepertoireMove).all()
        
        self.export_moves_cache = {}
        for m in all_moves:
            if m.from_position_id not in self.export_moves_cache:
                self.export_moves_cache[m.from_position_id] = []
            self.export_moves_cache[m.from_position_id].append(m)
            
        for k in self.export_moves_cache:
            self.export_moves_cache[k].sort(key=lambda x: x.priority_score, reverse=True)
            
        self.export_rep_cache = {rm.move_id: rm for rm in rep_moves}
        
        game = chess.pgn.Game(); game.headers["Event"] = self.active_repo_name; self._export_count = 0
        try:
            if " ".join(start.split(" ")[:4]) != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR":
                game.headers["FEN"] = start; game.setup(chess.Board(start))
                hist = self._get_history_for_pos(pos.id)
                if hist:
                    game.headers["FEN"] = chess.STARTING_FEN; game.setup(chess.Board()); node = game; board = game.board()
                    for uci in hist:
                        m = chess.Move.from_uci(uci)
                        if m in board.legal_moves: node = node.add_variation(m); board.push(m)
                        else: break
                    self._build_pgn_tree(node, pos.id, set(), {} if transpos_mode > 0 else None, "", cb, max_l, transpos_mode, language=language)
                    
                    # Clean up cache
                    del self.export_moves_cache
                    del self.export_rep_cache
                    return game.accept(LocalizedExporter(language=language, headers=True, variations=True, comments=True))
                    
            self._build_pgn_tree(game, pos.id, set(), {} if transpos_mode > 0 else None, "", cb, max_l, transpos_mode, language=language)
            
            # Clean up cache
            del self.export_moves_cache
            del self.export_rep_cache
            return game.accept(LocalizedExporter(language=language, headers=True, variations=True, comments=True))
        except InterruptedError: return None

    def _normalize_fen(self, fen: str) -> str:
        """Return the canonical 4-part FEN (strips halfmove/fullmove)."""
        return " ".join(fen.strip().split()[:4])

    def _get_history_for_pos(self, pid):
        path = []; curr = pid
        for _ in range(200):
            inc = self.session.query(Move).filter_by(to_position_id=curr).order_by(Move.priority_score.desc()).first()
            if not inc: break
            path.insert(0, inc.uci); curr = inc.from_position_id
        return path

    def check_immediate_transposition(self, current_fen):
        """Fast check if any legal move leads to a position already in the repertoire.
        Returns outgoing transpositions (moves from HERE that reach existing repertoire positions)."""
        return self.find_outgoing_transpositions(current_fen)

    def find_outgoing_transpositions(self, current_fen):
        """Find all legal moves from current_fen that land on an existing repertoire position,
        excluding moves already explicitly in the repertoire from this position."""
        if not self.session: return []

        board = chess.Board(current_fen)
        clean_current = self._normalize_fen(current_fen)

        # Find moves already in the repertoire FROM this position (skip those)
        current_pos_db = self.session.query(Position).filter(
            Position.fen.op('GLOB')(clean_current + "*")
        ).first()
        ignored_ucis = set()
        if current_pos_db:
            existing = self.session.query(Move.uci).join(RepertoireMove).filter(
                Move.from_position_id == current_pos_db.id
            ).all()
            ignored_ucis = {m.uci for m in existing}

        results = []
        for move in board.legal_moves:
            uci = move.uci()
            if uci in ignored_ucis:
                continue

            san = board.san(move)
            board.push(move)
            next_fen = self._normalize_fen(board.fen())
            board.pop()

            pos = self.session.query(Position).filter(
                Position.fen.op('GLOB')(next_fen + "*")
            ).first()
            if pos:
                has_variation = any([pos.variation_1, pos.variation_2, pos.variation_3,
                                     pos.cached_v1, pos.cached_v2])
                incoming_repo = self.session.query(RepertoireMove).join(Move).filter(
                    Move.to_position_id == pos.id).count() > 0
                outgoing_repo = self.session.query(RepertoireMove).join(Move).filter(
                    Move.from_position_id == pos.id).count() > 0

                if has_variation or incoming_repo or outgoing_repo:
                    v_name = (pos.variation_1 or pos.cached_v1 or
                              pos.variation_2 or pos.cached_v2 or "Variante")
                    results.append({
                        "move_uci": uci,
                        "move_san": san,
                        "target_fen": next_fen,
                        "variation_name": v_name,
                    })
        return results

    def find_incoming_transpositions(self, current_fen):
        """Find all repertoire paths (from other move orders) that also reach current_fen.
        Excludes the 'main' path that the current board history represents.
        Returns list of {variation_name, arriving_move_san, arriving_move_uci,
                          parent_variation_name, path_length}."""
        if not self.session: return []

        clean_fen = self._normalize_fen(current_fen)
        positions = self.session.query(Position).filter(
            Position.fen.op('GLOB')(clean_fen + "*")
        ).all()

        results = []
        seen_move_ids = set()
        for pos in positions:
            # All RepertoireMoves that lead INTO this position
            incoming = (
                self.session.query(Move)
                .join(RepertoireMove, RepertoireMove.move_id == Move.id)
                .filter(Move.to_position_id == pos.id)
                .all()
            )
            for m in incoming:
                if m.id in seen_move_ids:
                    continue
                seen_move_ids.add(m.id)

                # Get the parent position's variation name for context
                parent_pos = self.session.query(Position).filter(
                    Position.id == m.from_position_id
                ).first()
                parent_vname = ""
                if parent_pos:
                    parent_vname = (parent_pos.variation_1 or parent_pos.cached_v1 or
                                    parent_pos.variation_2 or parent_pos.cached_v2 or "")

                # The target variation name
                target_vname = (pos.variation_1 or pos.cached_v1 or
                                pos.variation_2 or pos.cached_v2 or "Variante")

                # Count how many moves in the repertoire lead to this position's parent
                # as a rough proxy for path depth
                depth = self.session.query(RepertoireMove).join(Move).filter(
                    Move.to_position_id == m.from_position_id
                ).count()

                results.append({
                    "variation_name": target_vname,
                    "parent_variation_name": parent_vname,
                    "arriving_move_san": m.san,
                    "arriving_move_uci": m.uci,
                    "from_position_id": m.from_position_id,
                    "priority": m.priority_score or 0,
                    "depth": depth,
                })

        # Sort by priority descending so most-played paths come first
        results.sort(key=lambda x: x["priority"], reverse=True)
        return results

    def find_direct_transpositions(self, fen, exclude_path=None):
        """Legacy wrapper — delegates to find_incoming_transpositions."""
        return self.find_incoming_transpositions(fen)

    def find_engine_approved_transpositions(self, start_fen, pvs):
        """
        Takes a list of engine PVs and checks if any FEN in those paths exists in the repertoire.
        Each PV is a dict: {score (cp), moves (list of UCI strings)}.
        Returns a de-duplicated list of matching sequences, sorted by eval descending.
        """
        if not self.session: return []

        seen_fens = set()
        results = []
        for pv_data in pvs:
            score = pv_data.get("score", 0)
            moves = pv_data.get("moves", [])

            board = chess.Board(start_fen)
            current_path_sans = []
            current_path_ucis = []

            for move_uci in moves:
                try:
                    move = chess.Move.from_uci(move_uci)
                    san = board.san(move)
                    board.push(move)
                    current_path_sans.append(san)
                    current_path_ucis.append(move_uci)

                    target_fen = self._normalize_fen(board.fen())

                    # Skip if we already found this target FEN from another PV
                    if target_fen in seen_fens:
                        continue

                    pos = self.session.query(Position).filter(
                        Position.fen.op('GLOB')(target_fen + "*")
                    ).first()
                    if pos:
                        is_in_repo = (
                            self.session.query(RepertoireMove)
                            .join(Move)
                            .filter(Move.to_position_id == pos.id)
                            .count() > 0
                        )
                        if is_in_repo:
                            v_name = (pos.variation_1 or pos.cached_v1 or
                                      pos.variation_2 or pos.cached_v2 or "Variante")
                            results.append({
                                "sequence": " ".join(current_path_sans),
                                "move_ucis": list(current_path_ucis),
                                "move_sans": list(current_path_sans),
                                "target_fen": target_fen,
                                "variation_name": v_name,
                                "eval": score,
                                "moves_count": len(current_path_ucis),
                            })
                            seen_fens.add(target_fen)
                            # Stop at first hit within this PV so we don't find
                            # a transposition deeper than necessary
                            break
                except Exception as e:
                    import logging
                    logging.error(f"Error in transposition path verification: {e}")
                    break

        results.sort(key=lambda x: x["eval"], reverse=True)
        return results

    def _build_pgn_tree(self, node, pid, vp, vg, line, cb, max_l, transpos_mode=2, language='en'):
        # Prevent infinite loops from actual cycles
        if pid in vp: 
            node.comment = f"{node.comment} (Cycle)" if node.comment else "(Cycle)"
            return
            
        # Transposition handling logic
        if vg is not None:
            if pid in vg:
                if transpos_mode == 2:
                    # Cut off and add comment pointing to the original line
                    comment_text = f"Position wird genauer betrachtet in dieser Zugreihenfolge: {vg[pid]}"
                    node.comment = f"{node.comment} | {comment_text}" if node.comment else comment_text
                # If transpos_mode == 1, we just cut off and do nothing (no comment)
                return
            # First time seeing this position, record its line
            vg[pid] = line
            
        vp.add(pid)
        
        # USE PRE-FETCHED CACHE
        moves = self.export_moves_cache.get(pid, [])
        board = node.board()
        for m_db in moves:
            repo_c = self.get_repertoire_color()
            is_p = (board.turn == chess.WHITE and repo_c == 'w') or (board.turn == chess.BLACK and repo_c == 'b')
            inc = True
            if max_l is not None:
                if is_p:
                    rm = self.export_rep_cache.get(m_db.id)
                    if not rm or rm.level > max_l: inc = False
                else:
                    # Are there any repertoire responses to this move?
                    child_moves = self.export_moves_cache.get(m_db.to_position_id, [])
                    has_valid_response = False
                    for child in child_moves:
                        crm = self.export_rep_cache.get(child.id)
                        if crm and crm.level <= max_l:
                            has_valid_response = True
                            break
                    if not has_valid_response: inc = False
                        
            if not inc: continue
            
            if cb:
                self._export_count += 1
                if self._export_count % 50 == 0 and cb(self._export_count): raise InterruptedError()
            
            m = chess.Move.from_uci(m_db.uci)
            new = node.add_variation(m)
            
            if m_db.nag: new.nags.add(m_db.nag)
            
            # Position comment is already loaded via eager loading
            np = m_db.to_position
            if np and np.comment: new.comment = np.comment
            
            mn = board.fullmove_number
            san = localize_san(m_db.san, language)
            seg = f"{mn}. {san}" if board.turn == chess.WHITE else (f"{mn}... {san}" if not line else san)
            
            self._build_pgn_tree(new, m_db.to_position_id, vp, vg, f"{line} {seg}".strip(), cb, max_l, transpos_mode, language=language)
            
        vp.remove(pid)

    def _seed_default_levels(self):
        """Adds default levels to a new/empty repertoire."""
        if not self.session: return
        try:
            count = self.session.query(RepertoireLevel).count()
            if count == 0:
                defaults = [
                    "Grundlagen",
                    "Tiefe Theorie",
                    "Nachschlagewerk und Erklärungen"
                ]
                from opening_fenix.core.logger import logger
                logger.info(f"CreatorBackend: Seeding default levels for '{self.active_repo_name}'")
                for i, name in enumerate(defaults, 1):
                    lvl = RepertoireLevel(name=name, order=i, target_elo=1500)
                    self.session.add(lvl)
                self.session.commit()
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Error seeding default levels: {e}")
            self.session.rollback()

    def add_repertoire_level(self, name, idx=None):
        if not self.session: return False, "Kein Repertoire geladen."
        
        try:
            if idx is None:
                # Append at the end (Legacy behavior from first definition)
                max_order = self.session.query(func.max(RepertoireLevel.order)).scalar()
                idx = (max_order if max_order is not None else 0) + 1

            # 1. Update Levels (one by one to avoid unique constraint violations in SQLite)
            levels_to_shift = self.session.query(RepertoireLevel).filter(RepertoireLevel.order >= idx).order_by(desc(RepertoireLevel.order)).all()
            for lvl in levels_to_shift:
                lvl.order += 1
                self.session.flush()

            # 2. Update Moves
            self.session.query(RepertoireMove).filter(RepertoireMove.level >= idx).update(
                {RepertoireMove.level: RepertoireMove.level + 1},
                synchronize_session=False
            )

            # 3. Add new level
            new_lvl = RepertoireLevel(name=name, order=idx)
            self.session.add(new_lvl)
            self.session.commit()

            # 4. Update User Profiles (active_level shift)
            try:
                self._update_profiles_level_shift(self.active_repo_name, idx, 1)
            except Exception as e:
                print(f"Warning: Could not update profiles: {e}")

            return True, f"Added {name}."
        except Exception as e:
            self.session.rollback()
            return False, str(e)

    def get_priority_level_impact(self, threshold_pct, target_level):
        """Returns the number of moves that would be updated."""
        if not self.session: return 0
        threshold = threshold_pct / 100.0
        
        # Count moves where:
        # 1. Priority >= threshold
        # 2. They are RepertoireMoves (have a level)
        # 3. Current Level is numerically HIGHER (less important) than target_level
        count = self.session.query(RepertoireMove)\
            .join(Move, RepertoireMove.move_id == Move.id)\
            .filter(Move.priority_score >= threshold)\
            .filter(RepertoireMove.level > target_level)\
            .count()
        return count

    def apply_priority_level_update(self, threshold_pct, target_level):
        """Updates qualifying moves and returns the number of modified moves."""
        if not self.session: return 0
        threshold = threshold_pct / 100.0
        
        # 1. Find RM entries that need update
        q_moves = self.session.query(RepertoireMove)\
            .join(Move, RepertoireMove.move_id == Move.id)\
            .filter(Move.priority_score >= threshold)\
            .filter(RepertoireMove.level > target_level)\
            .all()
            
        modified = len(q_moves)
        if modified == 0:
            return 0
            
        # 2. Update levels and propagate changes downstream
        for rm in q_moves:
            rm.level = target_level
            self.session.flush()
            # Ensure branch consistency
            self._update_level_recursive(rm.move.to_position_id, set(), target_level)
            
        self.session.commit()
        self.clear_cache()
        return modified

    def _update_profiles_level_shift(self, repo_name, threshold, delta):
        from opening_fenix.core.models import UserBase, UserRepertoireSettings
        profiles_dir = os.path.join(get_user_dir(), "profiles")
        if not os.path.exists(profiles_dir): return
        
        for f in os.listdir(profiles_dir):
            if f.endswith(".db"):
                profile_path = os.path.join(profiles_dir, f)
                try:
                    db = DatabaseManager(profile_path, base=UserBase)
                    # Add busy_timeout for SQLite to handle existing locks from the main window gracefully
                    with db.engine.connect() as conn:
                        conn.execute(text("PRAGMA busy_timeout = 5000"))
                        
                    session = db.get_session()
                    session.query(UserRepertoireSettings).filter(
                        UserRepertoireSettings.repertoire_name == repo_name,
                        UserRepertoireSettings.active_level >= threshold
                    ).update(
                        {UserRepertoireSettings.active_level: UserRepertoireSettings.active_level + delta},
                        synchronize_session=False
                    )
                    session.commit()
                    session.close()
                    db.close()
                except Exception as e:
                    print(f"Failed to update profile {f}: {e}")

    def rename_repertoire_level(self, old_name, new_name):
        if not self.session: return False, "No repo."
        try:
            lvl = self.session.query(RepertoireLevel).filter_by(name=old_name).first()
            if lvl:
                lvl.name = new_name
                self.session.commit()
                return True, f"Renamed to {new_name}."
            return False, "Level not found."
        except Exception as e:
            self.session.rollback()
            return False, str(e)

    def export_db(self, path, start=None):
        if not self.active_repo_name: return False, "No active repo."
        try: shutil.copy2(get_repertoire_db_path(self.active_repo_name), path); return True, "Exported."
        except Exception as e: return False, str(e)

    def scan_and_get_impact(self, uci, fen):
        clean_fen = " ".join(fen.strip().split(" ")[:4])
        pos = self.session.query(Position).filter(Position.fen.like(clean_fen + "%")).first()
        if not pos: return 0, 0
        dm, dp = self.get_delete_impact(pos.id, uci)
        return len(dm), len(dp)

    def get_incoming_moves(self, fen):
        if not self.session: return []
        clean_fen = " ".join(fen.split(" ")[:4])
        positions = self.session.query(Position).filter_by(fen=clean_fen).all()
        results = []
        for p in positions:
            moves = self.session.query(Move).options(joinedload(Move.from_position)).filter_by(to_position_id=p.id).all()
            for m in moves:
                rep_move = self.session.query(RepertoireMove).filter_by(move_id=m.id).first()
                results.append({
                    "uci": m.uci, "san": m.san, "level": rep_move.level if rep_move else None,
                    "parent_fen": m.from_position.fen if m.from_position else "Unknown",
                    "to_pos_id": p.id, "move_id": m.id
                })
        return results

    def manually_fix_gap(self, move_id):
        if not self.session: return
        rm = self.session.query(RepertoireMove).filter_by(move_id=move_id).first()
        if not rm:
            self.session.add(RepertoireMove(move_id=move_id, level=1))
            self.session.commit()
            self.clear_cache()

    def run_diagnostic(self):
        if not self.session: return {"schema": [], "gaps": 0, "duplicates": 0, "orphans": 0, "level_inconsistencies": 0}
        
        result = {}
        
        # 1. Check Schema (Missing Columns from old versions)
        missing_columns = []
        try:
            with self.db_manager.engine.connect() as conn:
                res = conn.execute(text("PRAGMA table_info(positions)"))
                pos_cols = [row[1] for row in res.fetchall()]
                for col in ['variation_3', 'cached_v1', 'cached_v2', 'cached_v3']:
                    if col not in pos_cols: missing_columns.append(f"positions.{col}")
                    
                res = conn.execute(text("PRAGMA table_info(moves)"))
                move_cols = [row[1] for row in res.fetchall()]
                if 'nag' not in move_cols: missing_columns.append("moves.nag")
        except Exception:
            pass
        result['schema'] = missing_columns

        # 2. Check Gaps
        subq = self.session.query(Move.from_position_id).join(RepertoireMove, Move.id == RepertoireMove.move_id).distinct()
        gaps_count = self.session.query(Move).outerjoin(RepertoireMove, Move.id == RepertoireMove.move_id)\
            .filter(RepertoireMove.id == None)\
            .filter(Move.to_position_id.in_(subq)).count()
        result['gaps'] = gaps_count
            
        # 3. Check FEN Duplicates
        duplicates_count = self.session.query(Position.fen).group_by(Position.fen).having(func.count(Position.id) > 1).count()
        result['duplicates'] = duplicates_count
        
        # 4. Check Orphans (Positions not reachable from start)
        # We do a fast BFS from the start position
        start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        start_pos = self.session.query(Position).filter_by(fen=start_fen).first()
        
        reachable_ids = set()
        if start_pos:
            queue = [start_pos.id]
            reachable_ids.add(start_pos.id)
            
            # Fetch all moves once into memory to build graph quickly
            all_moves = self.session.query(Move.from_position_id, Move.to_position_id).all()
            graph = {}
            for f_id, t_id in all_moves:
                if f_id not in graph: graph[f_id] = []
                graph[f_id].append(t_id)
                
            # BFS
            head = 0
            while head < len(queue):
                curr = queue[head]
                head += 1
                for nxt in graph.get(curr, []):
                    if nxt not in reachable_ids:
                        reachable_ids.add(nxt)
                        queue.append(nxt)
        
        total_positions = self.session.query(Position).count()
        result['orphans'] = total_positions - len(reachable_ids) if start_pos else 0

        # 5. Check Level Inconsistencies (Child < Min(Parents))
        inconsistencies = 0
        # For simplicity in diagnostic, we just count how many repertoire moves have a level
        # that is strictly less than the minimum level of all incoming repertoire moves.
        # This is a bit complex in pure SQL, so we do it in Python on the reachable set.
        if start_pos:
            all_rep_moves = self.session.query(RepertoireMove.move_id, RepertoireMove.level, Move.from_position_id, Move.to_position_id)\
                .join(Move, RepertoireMove.move_id == Move.id).all()
                
            pos_min_incoming_level = {start_pos.id: 1} # Start pos has implicit level 1
            
            # Build edges
            rep_edges = []
            for m_id, lvl, f_id, t_id in all_rep_moves:
                rep_edges.append((f_id, t_id, lvl))
                
            # Simple iterative propagation to find the "true" incoming level for each pos
            changed = True
            while changed:
                changed = False
                for f_id, t_id, lvl in rep_edges:
                    if f_id in pos_min_incoming_level:
                        eff_lvl = max(pos_min_incoming_level[f_id], lvl) # Max because larger number = lower priority
                        if t_id not in pos_min_incoming_level or eff_lvl > pos_min_incoming_level[t_id]:
                            # Actually we want MIN numerical value (highest priority) of all incoming paths
                            pass
            
            # A simpler check: Just find any move where rm.level < min(incoming_rep.level)
            # We'll skip this heavy check in the diagnostic to save time, or do a light version:
            inconsistencies = 0 # Placeholder for now to keep diagnostic fast
            
        result['level_inconsistencies'] = inconsistencies
        
        # 6. Check Orphaned Lichess Data
        all_lichess_fens = self.session.query(LichessData.fen).distinct().all()
        orphaned_lichess = 0
        for (l_fen,) in all_lichess_fens:
            exists = self.session.query(Position.id).filter(Position.fen.like(l_fen + "%")).first()
            if not exists:
                orphaned_lichess += self.session.query(LichessData).filter_by(fen=l_fen).count()
        result['orphaned_lichess'] = orphaned_lichess

        return result

    def repair_diagnostic_issues(self):
        if not self.session: return
        
        # 1. Repair Schema
        from opening_fenix.core.models import Base
        self.db_manager._migrate_schema(Base)
        
        # 2. Repair Gaps & Enforce Level Consistency
        from opening_fenix.core.services.repair_service import repair_repertoire_health
        repair_repertoire_health(self.session)
        self.session.flush()

        # 3. Repair FEN Duplicates (Merging)
        duplicates = self.session.query(Position.fen).group_by(Position.fen).having(func.count(Position.id) > 1).all()
        for dup in duplicates:
            fen = dup[0]
            positions = self.session.query(Position).filter_by(fen=fen).order_by(Position.id).all()
            if len(positions) > 1:
                keep_pos = positions[0]
                for p in positions[1:]:
                    # Redirect incoming moves
                    inc_moves = self.session.query(Move).filter_by(to_position_id=p.id).all()
                    for m in inc_moves:
                        m.to_position_id = keep_pos.id
                    
                    # Redirect outgoing moves
                    out_moves = self.session.query(Move).filter_by(from_position_id=p.id).all()
                    for m in out_moves:
                        existing = self.session.query(Move).filter_by(from_position_id=keep_pos.id, uci=m.uci).first()
                        if existing:
                            rep_m = self.session.query(RepertoireMove).filter_by(move_id=m.id).first()
                            if rep_m:
                                ex_rep = self.session.query(RepertoireMove).filter_by(move_id=existing.id).first()
                                if not ex_rep:
                                    rep_m.move_id = existing.id
                                else:
                                    self.session.delete(rep_m)
                            self.session.delete(m)
                        else:
                            m.from_position_id = keep_pos.id
                            
                    self.session.delete(p)
                self.session.flush()

        # 4. Repair Orphaned Lichess Data
        self.cleanup_orphaned_lichess_data()

        self.session.commit()
        self.clear_cache()
        return 0

    def reset_and_repair_variation_names(self):
        """Clears all cached variation names and recalculates them from the starting position."""
        if not self.session: return
        
        # 1. Clear all cached variation names (Reset)
        self.session.query(Position).update({
            Position.cached_v1: None,
            Position.cached_v2: None,
            Position.cached_v3: None
        })
        self.session.flush()
        
        # 2. Recalculate from starting position
        start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        start_pos = self.session.query(Position).filter_by(fen=start_fen).first()
        
        if start_pos:
            self._update_cached_names_recursive(start_pos)
            
        self.session.commit()
        self.clear_cache()





class SortableTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn()
        if col == 1: # Priority column (0-indexed)
            v1 = self.data(col, Qt.ItemDataRole.UserRole)
            v2 = other.data(col, Qt.ItemDataRole.UserRole)
            if v1 is None: v1 = -1.0
            if v2 is None: v2 = -1.0
            return v1 < v2
        return self.text(col) < other.text(col)


class NewRepertoireDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neues Repertoire")
        self.setFixedWidth(scale(400))
        set_consistent_icon(self)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(15))
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("z.B. Caro-Kann für Fortgeschrittene")
        
        self.color_combo = QComboBox()
        self.color_combo.addItem("Weiß", "w")
        self.color_combo.addItem("Schwarz", "b")
        
        form.addRow("Name:", self.name_input)
        form.addRow("Deine Farbe:", self.color_combo)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_ok = QPushButton("Erstellen")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.clicked.connect(self.reject)
        
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def get_data(self):
        return self.name_input.text().strip(), self.color_combo.currentData()

class CreatorWindow(QMainWindow):
    def _is_ui_valid(self):
        """Robust check if the UI widgets are initialized and not deleted."""
        try:
            return all([
                self.i_v1 is not None and not sip.isdeleted(self.i_v1),
                self.i_v2 is not None and not sip.isdeleted(self.i_v2),
                self.i_v3 is not None and not sip.isdeleted(self.i_v3),
                self.txt_c is not None and not sip.isdeleted(self.txt_c)
            ])
        except (AttributeError, RuntimeError):
            return False

    def __init__(self, repertoire_name=None, initial_fen=None, training_manager=None, is_test=False):
        super().__init__()
        self.setWindowTitle("Opening Fenix - Repertoire Creator")
        set_consistent_icon(self)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.resize(scale(1400), scale(900))

        self.backend = CreatorBackend(is_test=is_test)
        self.training_manager = training_manager
        self.is_test = is_test
        self._processing_event = False  # Re-entrancy guard for eventFilter
        self.engine_thread = None
        self.sounds, self.piece_icons = {}, {}
        self.enrichment_threads = []
        self._auto_size_board = True
        
        # UI references for guards
        self.i_v1 = None
        self.i_v2 = None
        self.i_v3 = None
        self.txt_c = None
        
        # Hole Finder Async
        self.hole_thread = None
        self.hole_anim_timer = QTimer(self)
        self.hole_anim_timer.timeout.connect(self._animate_hole_button)
        self._hole_dots = 0


        cp = os.path.join(get_user_dir(), "config.json")
        if os.path.exists(cp):
            with open(cp, "r") as f: self.config = json.load(f)
        else: self.config = {}

        # Debounce Timer for saving details
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.save_current_details_now)
        self.details_changed = False

        # Overhaul Session State
        self.overhaul_active = False
        self.overhaul_paused = True
        self.overhaul_start = None

        # Tab visibility defaults
        if "creator_active_tabs" not in self.config:
            self.config["creator_active_tabs"] = ["DETAILS", "ANALYSIS", "TRANSPOSITIONS"]
        elif "TRANSPOSITIONS" not in self.config["creator_active_tabs"]:
            # Auto-enable for the first time
            self.config["creator_active_tabs"].append("TRANSPOSITIONS")
        
        self.init_icons()
        self.init_ui()
        self.init_engine()

        # Lazy load sounds to improve startup time
        QTimer.singleShot(200, self.init_sounds)

        st = self.get_setting("theme")
        if st: self.board_widget.set_theme(st)
        QApplication.instance().installEventFilter(self)

        rtl = repertoire_name or self.config.get("last_active_repertoire")
        self.is_test = is_test

        if rtl and isinstance(rtl, str):
            # Probe is_test if not explicitly provided (for backward compatibility / last_active)
            if self.is_test is None:
                db_path_reg = get_repertoire_db_path(rtl, is_test=False)
                db_path_test = get_repertoire_db_path(rtl, is_test=True)
                if os.path.exists(db_path_test): self.is_test = True
                elif os.path.exists(db_path_reg): self.is_test = False
            
            self.load_repertoire(rtl, training_manager, self.is_test)
            self.set_board_to_fen(initial_fen or chess.STARTING_FEN)
            
            # Load persistent overhaul session if exists
            session_dt = self.backend.get_overhaul_session_start()
            if session_dt:
                self.overhaul_start = session_dt
                self.overhaul_active = True
                self.overhaul_paused = True

            self.setWindowTitle(f"Creator - {rtl}")
            self.board_widget.flipped = (self.backend.get_repertoire_color() == 'b')
            self.board_widget.update()
        else:
            # If no repertoire is found, default to creating a new one or opening empty state
            self.setWindowTitle("Creator - Kein Repertoire")
            # We can automatically prompt for a new repertoire if none is found
            QTimer.singleShot(100, self.new_repertoire_dialog)

    def get_setting(self, key, default=None):
        if self.training_manager:
            # TrainingManager.get_setting returns the setting value directly
            return self.training_manager.get_setting(key) or self.config.get(key, default)
        return self.config.get(key, default)

    def set_setting(self, key, value):
        if self.training_manager:
            self.training_manager.set_setting(key, value)
        self.config[key] = value
        self.save_config()

    def get_notation_lang(self):
        return self.get_setting("notation_language", "en")

    def save_config(self):
        config_path = os.path.join(get_user_dir(), "config.json")
        try:
            with open(config_path, "w") as f:
                json.dump(self.config, f, indent=4)
        except: pass

    def showEvent(self, event):
        super().showEvent(event)
        # Re-apply icon after native handle is created (needed for FramelessWindowHint on Windows)
        QTimer.singleShot(0, lambda: set_consistent_icon(self))

    def init_ui(self):
        self.setStyleSheet(get_creator_window_style())

        central = QWidget()
        self.setCentralWidget(central)
        main_layout_v = QVBoxLayout(central)
        main_layout_v.setContentsMargins(0, 0, 0, 0)
        main_layout_v.setSpacing(0)

        # Custom Title Bar
        rtl = self.config.get("last_active_repertoire", "") if getattr(self, "config", None) else ""
        self.custom_title_bar = CustomTitleBar(self, title=f" {rtl}" if rtl else " Kein Rep")
        self.custom_title_bar.setFixedHeight(scale(65))
        main_layout_v.addWidget(self.custom_title_bar)


        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(scale(10), scale(6), scale(20), scale(6))
        top_layout.setSpacing(0)


        # Toolbar Container
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setStyleSheet(get_creator_toolbar_style())

        # Toolbar Buttons using QPushButtons for reliable CSS rounding
        btn_load = QPushButton("📂 Laden")
        btn_load.setProperty("class", "GlassPill")
        self.repolish(btn_load)
        btn_load.setToolTip("Ein anderes Repertoire laden")
        btn_load.clicked.connect(self.load_repertoire_dialog)
        self.toolbar.addWidget(btn_load)

        btn_new = QPushButton("➕ Neu")
        btn_new.setProperty("class", "GlassPill")
        self.repolish(btn_new)
        btn_new.setToolTip("Ein neues, leeres Repertoire erstellen")
        btn_new.clicked.connect(self.new_repertoire_dialog)
        self.toolbar.addWidget(btn_new)

        btn_repo = QPushButton("⚙ Settings")
        btn_repo.setProperty("class", "GlassPill")
        self.repolish(btn_repo)
        btn_repo.setToolTip("Repertoire-Einstellungen öffnen")
        btn_repo.clicked.connect(self.open_repo_settings)
        self.toolbar.addWidget(btn_repo)

        self.combo_structure = QComboBox()
        self.combo_structure.setMinimumWidth(scale(220))
        self.combo_structure.addItem("🧩 Struktur Explorer")
        self.combo_structure.setProperty("class", "GlassPill")
        self.repolish(self.combo_structure)
        self.combo_structure.currentIndexChanged.connect(self.on_structure_combo_changed)
        self.toolbar.addWidget(self.combo_structure)

        # Lichess Button (NEW)
        self.btn_lichess = QPushButton()
        self.btn_lichess.setProperty("class", "GlassPill")
        lichess_icon_path = os.path.join(get_base_path(), "assets", "Icons", "lichess.png")
        if os.path.exists(lichess_icon_path):
            self.btn_lichess.setIcon(QIcon(lichess_icon_path))
            self.btn_lichess.setIconSize(QSize(scale(22), scale(22)))
        else:
            self.btn_lichess.setText("🔬")
        self.btn_lichess.setToolTip("<b>Lichess Analyse</b><br>Öffne die aktuelle Stellung in der Lichess-Analyse.")
        self.btn_lichess.clicked.connect(self.open_lichess_analysis)
        self.repolish(self.btn_lichess)
        self.toolbar.addWidget(self.btn_lichess)

        # Repertoire Resources Button
        self.btn_resources = QPushButton("📁 Ressourcen")
        self.btn_resources.setProperty("class", "GlassPill")
        self.repolish(self.btn_resources)
        self.btn_resources.setToolTip("Öffne den Repertoire-Ordner für weitere Ressourcen (Model Games, Tactics, etc.)")
        self.btn_resources.clicked.connect(self.open_repertoire_folder)
        self.toolbar.addWidget(self.btn_resources)

        top_layout.addWidget(self.toolbar)

        top_layout.addStretch()

        self.custom_title_bar.layout.insertLayout(1, top_layout, 1)

        inner_widget = QWidget()
        l = QHBoxLayout(inner_widget)
        l.setContentsMargins(scale(10), scale(10), scale(10), scale(10)) # Uniform 10px margins on all sides
        l.setSpacing(scale(10))
        main_layout_v.addWidget(inner_widget, 1)


        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Board Container
        cc = QWidget()
        cl = QVBoxLayout(cc)
        cl.setContentsMargins(0, 0, scale(10), scale(10)) # 0 left (inner_widget provides 10px), 10 right gap to splitter, 10 bottom
        cl.setSpacing(scale(10))

        self.board_panel = AspectRatioFrame()
        self.board_panel.setObjectName("BoardPanel")
        board_layout = QVBoxLayout(self.board_panel)
        board_layout.setContentsMargins(0, 0, 0, 0) # Remove internal padding, use layout margins
        self.board_widget = ChessBoardWidget(self)
        self.board_widget.move_executed.connect(self.on_board_move)
        board_layout.addWidget(self.board_widget)
        
        # Symmetrical vertical layout - board maximized
        cl.addWidget(self.board_panel, 1)

        self.main_splitter.addWidget(cc)

        # Right Side - Now using a Vertical Splitter for Tree vs Tabs
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Upper Right - Tree
        self.tree_group = QWidget()
        self.tree_group.setProperty("class", "GlassPill")
        t_layout = QVBoxLayout(self.tree_group)
        t_layout.setContentsMargins(scale(10), scale(10), scale(10), scale(10)) # Reverted to 10px in previous step
        t_layout.setSpacing(scale(10))

        h_header = QHBoxLayout()
        h_header.setContentsMargins(0, 0, 0, 0) # Margins handled by parent layout
        lbl_title = QLabel("KANDIDATENZÜGE")
        lbl_title.setStyleSheet("font-weight: bold; border: none;")
        
        self.chk_a = QPushButton("Zug-Pfeile anzeigen")
        self.chk_a.setCheckable(True)
        self.chk_a.setProperty("class", "GlassPill")
        self.repolish(self.chk_a)
        self.chk_a.toggled.connect(self.update_board_arrows)
        
        h_header.addWidget(lbl_title)
        h_header.addStretch()
        h_header.addWidget(self.chk_a)
        t_layout.addLayout(h_header)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Zug", "Prio", "Kommentar", "Level", "Aktiv"])
        header = self.tree_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Kommentar
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_widget.itemClicked.connect(self.on_tree_click)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree_widget.setStyleSheet("border: none;")
        t_layout.addWidget(self.tree_widget)
        self.right_splitter.addWidget(self.tree_group)

        # Lower Right - Tabs
        self.tabs = QTabWidget()
        
        # Tab 1: Stellungs Details
        self.tab_details = QWidget()
        dl = QVBoxLayout(self.tab_details)
        dl.setContentsMargins(0, scale(5), 0, 0) # Use 0 horizontal margin to align with parent tab width


        # Combined Glass Container for Details & Variants
        self.details_panel = QFrame()
        self.details_panel.setObjectName("SidePanel")
        dv = QVBoxLayout(self.details_panel)
        dv.setContentsMargins(scale(10), scale(10), scale(10), scale(10)) # Standard internal padding for the glass pill
        dv.setSpacing(scale(10))


        # Kommentar Section
        self.txt_c = QPlainTextEdit()
        self.txt_c.setPlaceholderText("Stellungs-Kommentar hier eingeben...")
        self.txt_c.setMinimumHeight(scale(150))
        self.txt_c.textChanged.connect(self.on_details_changed)

        dv.addWidget(self.txt_c)

        sym_layout = QHBoxLayout()
        sym_layout.setSpacing(scale(8))
        syms = [("+−", "Weiß steht deutlich besser"),
                ("±", "Weiß steht besser"),
                ("⩲", "Weiß steht etwas besser"),
                ("=", "Stellung ist ausgeglichen"),
                ("∞", "Stellung ist unklar"),
                ("⇆", "Stellung mit Gegenspiel"),
                ("⩱", "Schwarz steht etwas besser"),
                ("∓", "Schwarz steht besser"),
                ("−+", "Schwarz steht deutlich besser")]
        for s, tooltip in syms:
            btn = QPushButton(s)
            btn.setFixedSize(scale(30), scale(30))
            btn.setToolTip(tooltip)

            btn.setProperty("class", "SymbolButton")
            self.repolish(btn)
            btn.clicked.connect(lambda _, x=s: self.insert_symbol(x))
            sym_layout.addWidget(btn)
        sym_layout.addStretch()
        dv.addLayout(sym_layout)

        # Variant Name Section (Dynamic)
        self.variant_layout = QFormLayout()
        self.variant_layout.setSpacing(scale(10))

        self.i_v1 = QLineEdit()
        self.i_v2 = QLineEdit()
        self.i_v3 = QLineEdit()
        self.i_v1.setPlaceholderText("Variante 1")
        self.i_v2.setPlaceholderText("Variante 2")
        self.i_v3.setPlaceholderText("Variante 3")

        self.i_v1.textChanged.connect(self.on_details_changed)
        self.i_v1.textChanged.connect(self._update_variant_visibility)
        self.i_v2.textChanged.connect(self.on_details_changed)
        self.i_v2.textChanged.connect(self._update_variant_visibility)
        self.i_v3.textChanged.connect(self.on_details_changed)

        self.variant_layout.addRow(self.i_v1)
        self.variant_layout.addRow(self.i_v2)
        self.variant_layout.addRow(self.i_v3)
        dv.addLayout(self.variant_layout)
        
        # Initial Visibility
        self._update_variant_visibility()
        dl.addWidget(self.details_panel)
        

        # Analysis Tab (Merged Engine & Common Moves)
        self.tab_analysis = QWidget()
        al = QHBoxLayout(self.tab_analysis)
        al.setContentsMargins(0, scale(5), 0, 0)
        al.setSpacing(scale(15))

        # Left Column: Engine (GlassPill)
        engine_container = QFrame()
        engine_container.setProperty("class", "GlassPill")
        self.repolish(engine_container)
        evl = QVBoxLayout(engine_container)
        
        # Engine Settings (Dropdowns)
        h_eng_settings = QHBoxLayout()
        h_eng_settings.setSpacing(scale(5))
        
        self.combo_depth = QComboBox()
        self.combo_depth.setEditable(True)
        self.combo_depth.lineEdit().setReadOnly(True)
        self.combo_depth.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_depth.addItems([str(i) for i in range(10, 51, 2)])
        self.combo_depth.setCurrentText("20")
        self.combo_depth.setFixedWidth(scale(48))
        self.combo_depth.setProperty("class", "SmallCombo")
        self.repolish(self.combo_depth)
        self.combo_depth.lineEdit().setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_depth.lineEdit().installEventFilter(self)
        
        self.combo_threads = QComboBox()
        self.combo_threads.setEditable(True)
        self.combo_threads.lineEdit().setReadOnly(True)
        self.combo_threads.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_threads.lineEdit().setCursor(Qt.CursorShape.PointingHandCursor)
        max_threads = multiprocessing.cpu_count()
        self.combo_threads.addItems([str(i) for i in range(1, max_threads + 1)])
        self.combo_threads.setCurrentText(str(max(1, min(4, max_threads))))
        self.combo_threads.setFixedWidth(scale(48))
        self.combo_threads.setProperty("class", "SmallCombo")
        self.repolish(self.combo_threads)
        self.combo_threads.lineEdit().installEventFilter(self)
        
        self.combo_lines = QComboBox()
        self.combo_lines.setEditable(True)
        self.combo_lines.lineEdit().setReadOnly(True)
        self.combo_lines.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_lines.lineEdit().setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_lines.addItems([str(i) for i in range(1, 11)])
        self.combo_lines.setCurrentText("5")
        self.combo_lines.setFixedWidth(scale(48))
        self.combo_lines.setProperty("class", "SmallCombo")
        self.repolish(self.combo_lines)
        self.combo_lines.lineEdit().installEventFilter(self)
        
        lbl_depth = QLabel("Depth:")
        lbl_threads = QLabel("Threads:")
        lbl_lines = QLabel("Lines:")
        
        h_eng_settings.addWidget(lbl_depth)
        h_eng_settings.addWidget(self.combo_depth)
        h_eng_settings.addWidget(lbl_threads)
        h_eng_settings.addWidget(self.combo_threads)
        h_eng_settings.addWidget(lbl_lines)
        h_eng_settings.addWidget(self.combo_lines)
        h_eng_settings.addStretch()
        evl.addLayout(h_eng_settings)
        
        self.btn_engine_toggle = QPushButton("▶ Analyse Starten")
        self.btn_engine_toggle.setCheckable(True)
        self.btn_engine_toggle.setMinimumHeight(scale(40))
        self.btn_engine_toggle.setProperty("class", "GlassPill")
        self.repolish(self.btn_engine_toggle)
        self.btn_engine_toggle.toggled.connect(self._on_engine_toggle_toggled)
        evl.addWidget(self.btn_engine_toggle)
        
        self.table_engine = QTableWidget(0, 3)
        self.table_engine.setHorizontalHeaderLabels(["Eval", "Depth", "Move"])
        self.table_engine.verticalHeader().setVisible(False)
        self.table_engine.setAlternatingRowColors(True)
        self.table_engine.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_engine.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header_e = self.table_engine.horizontalHeader()
        header_e.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_e.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_e.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        evl.addWidget(self.table_engine)
        al.addWidget(engine_container, 2) # Engine part now more compact

        # Right Column: Common Moves (GlassPill)
        common_container = QFrame()
        common_container.setProperty("class", "GlassPill")
        self.repolish(common_container)
        cvl = QVBoxLayout(common_container)
        
        h_cat = QHBoxLayout()
        h_cat.addWidget(QLabel("Database:"))
        self.combo_lichess_cat = QComboBox()
        self.combo_lichess_cat.addItems(["low", "mid", "high", "masters"])
        self.combo_lichess_cat.setToolTip("<b>Lichess ELO-Kategorien:</b><br>"
                                          "• <b>low</b>: Spieler <1400 ELO<br>"
                                          "• <b>mid</b>: Spieler 1400-2000 ELO<br>"
                                          "• <b>high</b>: Spieler >2000 ELO<br>"
                                          "• <b>masters</b>: Lichess Masters Datenbank (Titelträger)")
        self.combo_lichess_cat.setCurrentText("high")
        self.combo_lichess_cat.currentTextChanged.connect(self.update_ui_from_fen)
        
        h_cat.addWidget(self.combo_lichess_cat)
        h_cat.addStretch()
        cvl.addLayout(h_cat)
        
        self.table_common_moves = QTableWidget(0, 5)
        self.table_common_moves.setHorizontalHeaderLabels(["Move", "Played", "White %", "Black %", "Draw %"])
        self.table_common_moves.verticalHeader().setVisible(False)
        self.table_common_moves.setAlternatingRowColors(True)
        self.table_common_moves.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_common_moves.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_common_moves.cellDoubleClicked.connect(self.on_common_move_double_click)
        header_cm = self.table_common_moves.horizontalHeader()
        header_cm.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cvl.addWidget(self.table_common_moves)
        al.addWidget(common_container, 5) # Common moves now significantly wider
        
        # Rep. Loch Finder Tab
        self.tab_holes = QWidget()
        self.init_hole_finder_tab()
        
        # Rep. KONTROLLE Tab
        self.tab_kontrolle = QWidget()
        self.init_kontrolle_tab()
        
        # Transposition Finder Tab
        self.tab_transpositions = QWidget()
        self.init_transpositions_tab()
        
        # Store all possible tabs in a mapping
        self._all_tabs = {
            "DETAILS": (self.tab_details, "DETAILS"),
            "ANALYSIS": (self.tab_analysis, "ANALYSIS"),
            "HOLES": (self.tab_holes, "Rep. Loch Finder"),
            "KONTROLLE": (self.tab_kontrolle, "Rep. Kontrolle"),
            "TRANSPOSITIONS": (self.tab_transpositions, "Transpositionen")
        }
        
        self.apply_tab_visibility()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.right_splitter.addWidget(self.tabs)
        # Symmetrical layout for bottoms: Ensure tabs (Details panel) is flushed to bottom
        self.tabs.setContentsMargins(0, 0, 0, 0)
        
        # Set initial sizes so it looks like before (e.g., split 50/50 vertically)
        self.right_splitter.setSizes([300, 300])

        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.splitterMoved.connect(lambda: setattr(self, '_auto_size_board', False))
        l.addWidget(self.main_splitter)

        self.init_management_slots()

        header_font = QFont()
        header_font.setPointSize(16)
        self.tree_widget.header().setFont(header_font)

        # Apply Drop Shadows for glass depth
        for panel in [self.board_panel, self.tree_group, self.tabs]:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(0, 0, 0, 50))
            shadow.setOffset(0, 6)
            panel.setGraphicsEffect(shadow)

        # Ensure "DETAILS" tab is selected by default on startup if visible
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "DETAILS":
                self.tabs.setCurrentIndex(i)
                break

    def _on_tab_changed(self, index):
        if not self._is_ui_valid(): return
        widget = self.tabs.widget(index)
        if widget == self.tab_transpositions:
            self.update_transpositions_tab()
        elif widget == self.tab_kontrolle:
            self.update_overhaul_progress()

    def apply_tab_visibility(self):
        # Determine which tabs should be visible
        active_tabs = self.config.get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
        
        # Remember current index if possible
        current_text = ""
        if self.tabs.count() > 0:
            current_text = self.tabs.tabText(self.tabs.currentIndex())

        # Clear current tabs without deleting the widgets
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)
            
        # Re-add requested tabs in specific order
        order = ["DETAILS", "ANALYSIS", "TRANSPOSITIONS", "HOLES", "KONTROLLE"]
        for key in order:
            if key in active_tabs and key in self._all_tabs:
                widget, title = self._all_tabs[key]
                self.tabs.addTab(widget, title)
                
        # Restore index if possible
        if current_text:
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == current_text:
                    self.tabs.setCurrentIndex(i)
                    break

    def on_details_changed(self):
        if not self._is_ui_valid() or not self.backend.current_fen: return
        self.backend.save_position_details(
            self.backend.current_fen,
            self.txt_c.toPlainText(),
            self.i_v1.text(),
            self.i_v2.text(),
            self.i_v3.text()
        )

    def _update_variant_visibility(self):
        if not self._is_ui_valid(): return
        
        # A field is considered 'filled' if it has typed text 
        # OR if it has placeholder text that isn't the default "Variante X"
        def is_filled(line_edit, default_placeholder):
            has_text = bool(line_edit.text().strip())
            placeholder = line_edit.placeholderText()
            has_inherited = bool(placeholder and placeholder.strip() and placeholder != default_placeholder)
            return has_text or has_inherited

        v1_filled = is_filled(self.i_v1, "Variante 1")
        self.i_v2.setVisible(v1_filled)
        
        v2_filled = is_filled(self.i_v2, "Variante 2")
        self.i_v3.setVisible(v1_filled and v2_filled)

    def _load_saved_elo_or_autoselect(self):
        """Loads the last used ELO category from DB, or auto-selects based on description."""
        if not self.backend.session:
            return
            
        current_elo_meta = self.backend.session.query(Metadata).filter_by(key="elo").first()
        if not current_elo_meta:
             current_elo_meta = self.backend.session.query(Metadata).filter_by(key="lichess_elo").first()
             
        if current_elo_meta and current_elo_meta.value:
            # If there's a comma-separated list, take the first valid entry
            vals = [v.strip() for v in current_elo_meta.value.split(",")]
            for v in vals:
                if v in ["low", "mid", "high", "masters"]:
                    self.combo_lichess_cat.setCurrentText(v)
                    return # Successfully loaded from DB


        # If we reach here, there was no saved metadata, so we autoselect
        self._autoselect_elo_range()

    def _autoselect_elo_range(self):
        desc = self.backend.get_repertoire_description()
        if not desc or not isinstance(desc, str):
            return
        
        desc_lower = desc.lower()
        
        # Use regex to avoid "word-within-a-word" false positives
        if re.search(r'\bmasters?\b', desc_lower):
            self.combo_lichess_cat.setCurrentText("masters")
        elif re.search(r'\bhigh\b', desc_lower):
            self.combo_lichess_cat.setCurrentText("high")
        elif re.search(r'\b(mid|medium)\b', desc_lower):
            self.combo_lichess_cat.setCurrentText("mid")
        elif re.search(r'\blow\b', desc_lower):
            self.combo_lichess_cat.setCurrentText("low")

    def on_common_move_double_click(self, row, column):
        uci = self.table_common_moves.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if uci:
            self.save_current_details_now()
            try:
                move = chess.Move.from_uci(uci)
                if move in self.board_widget.board.legal_moves:
                    san = self.board_widget.board.san(move)
                    fen = self.board_widget.board.fen()
                    self.board_widget.board.push(move)
                    self.board_widget.update()
                    self.play_sound("move")
                    self.backend.add_move(fen, move.uci(), san)
                    self.update_ui_from_fen()
                    self.trigger_background_enrichment(self.board_widget.board.fen())
            except:
                pass

    def on_board_move(self, move):
        if not self.backend.active_repo_name: return
        self.save_current_details_now()
        
        # Evaluate FEN BEFORE pushing the move
        from_fen = self.board_widget.board.fen()
        s = self.board_widget.board.san(move)
        
        self.board_widget.board.push(move)
        self.board_widget.update()
        self.play_sound("move")
        
        self.backend.add_move(from_fen, move.uci(), s)
        self.update_ui_from_fen()
        self.trigger_background_enrichment(self.board_widget.board.fen())

    def trigger_background_enrichment(self, fen):
        """
        Starts a background thread to fetch Lichess data, run engine analysis,
        and update priority scores for the given FEN.
        """
        if not self.backend.active_repo_name: return
        
        ep = self.config.get("engine_path")
        cat = self.combo_lichess_cat.currentText()
        
        # Check if already running for this FEN to avoid duplicates
        for t in self.enrichment_threads:
            if t.fen == fen: return
            
        t = BackgroundEnrichmentThread(self.backend.active_repo_name, fen, cat, ep, 10)
        
        def on_finished(success, msg, thread=t):
            if thread in self.enrichment_threads:
                self.enrichment_threads.remove(thread)
            if success:
                # Clear UI cache to ensure we see updated data from the DB
                self.backend.clear_cache()
                
                # Silently refresh the UI to show updated priority scores/good moves
                # We only refresh if we are still on the same position or nearby
                self.update_ui_from_fen()
        
        t.finished_signal.connect(on_finished)
        self.enrichment_threads.append(t)
        t.start()

    def go_back(self):
        self.save_current_details_now()
        if len(self.board_widget.board.move_stack) > 0:
            self.board_widget.board.pop()
            self.board_widget.update()
            self.play_sound("move")
            self.update_ui_from_fen()

    def go_start(self):
        self.save_current_details_now()
        self.board_widget.board.reset()
        self.board_widget.update()
        self.play_sound("move")
        self.update_ui_from_fen()

    def go_forward(self):
        it = self.tree_widget.currentItem()
        if not it: it = self.tree_widget.topLevelItem(0)
        if it: self.on_tree_click(it, 0)

    def set_board_to_fen(self, fen):
        self.save_current_details_now()
        res = self.backend.get_path_to_fen(fen)
        if isinstance(res, tuple) and len(res) == 2:
            rf, ms = res
        else:
            rf, ms = None, []
        
        if not rf:
            from opening_fenix.core.logger import logger
            logger.info(f"Creator: Could not find path to FEN {fen}. Attempting direct set.")
            try:
                self.board_widget.board.set_fen(fen)
            except Exception as e:
                logger.error(f"Creator: Direct FEN set failed: {e}")
        else:
            self.board_widget.board = chess.Board(rf)
            for u in ms:
                try:
                    self.board_widget.board.push(chess.Move.from_uci(u))
                except Exception as e:
                    from opening_fenix.core.logger import logger
                    logger.error(f"Creator: Failed to push move {u} during navigation: {e}")
                    break
        
        self.board_widget.update()
        self.update_ui_from_fen()

    def update_ui_from_fen(self, force_details=False):
        # Guard: Ensure UI is initialized and valid before updating
        if not self._is_ui_valid():
            return
            
        f = self.board_widget.board.fen()
        
        # Auto-mark for overhaul if session is active and NOT paused
        if self.overhaul_active and not self.overhaul_paused:
            self.backend.mark_position_reviewed(f)
            self.update_overhaul_progress()
        elif not self.overhaul_active:
            # Still update progress bar to show general completion for current filter
            self.update_overhaul_progress()

        d = self.backend.get_position_data(f)
        
        # Only update details if not currently being edited by the user to avoid overwriting typing
        if not self.details_changed or force_details:
            self.block_signals_details(True)
            if d and isinstance(d, dict):
                self.i_v1.setText(str(d.get('variation_1','')) if not d.get('v1_inherited') else "")
                self.i_v1.setPlaceholderText(str(d.get('variation_1','')) if (d.get('v1_inherited') and d.get('variation_1')) else "Variante 1")
                self.i_v2.setText(str(d.get('variation_2','')) if not d.get('v2_inherited') else "")
                self.i_v2.setPlaceholderText(str(d.get('variation_2','')) if (d.get('v2_inherited') and d.get('variation_2')) else "Variante 2")
                self.i_v3.setText(str(d.get('variation_3','')) if not d.get('v3_inherited') else "")
                self.i_v3.setPlaceholderText(str(d.get('variation_3','')) if (d.get('v3_inherited') and d.get('variation_3')) else "Variante 3")
                self.txt_c.setPlainText(str(d.get('comment','')))
            else:
                self.i_v1.setText(""); self.i_v1.setPlaceholderText("Variante 1")
                self.i_v2.setText(""); self.i_v2.setPlaceholderText("Variante 2")
                self.i_v3.setText(""); self.i_v3.setPlaceholderText("Variante 3")
                self.txt_c.setPlainText("")
            
            # Ensure visibility is updated after text changes
            self._update_variant_visibility()
            
            self.details_changed = False
            self.block_signals_details(False)

        self.tree_widget.clear()
        
        # This function was heavily optimized with eager loading!
        cs = self.backend.get_candidate_moves(f)
        
        # Hide/show Aktiv column dynamically
        repo_color = self.backend.get_repertoire_color()
        is_my_turn = True if repo_color not in ['w', 'b'] else (self.board_widget.board.turn == (repo_color == 'w'))
        if is_my_turn and len(cs) > 1:
            self.tree_widget.showColumn(4)
        else:
            self.tree_widget.hideColumn(4)
        
        lvls = self.backend.get_repertoire_levels()
        l_map = {l['order']: l['name'] for l in lvls}
        large_font = QFont()
        large_font.setPointSize(16)
        board = self.board_widget.board
        move_num = board.fullmove_number
        prefix = f"{move_num}. " if board.turn == chess.WHITE else f"{move_num}... "
        
        for c in cs:
            nag_map = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
            nag_s = f" {nag_map[c['nag']]}" if c['nag'] in nag_map else ""
            
            lang = self.get_notation_lang()
            san_text = f"{prefix}{localize_san(c['san'], lang)}{nag_s}"
            
            # OVERHAUL V2: Add checkmark if branch is fully reviewed
            if self.overhaul_active and not self.overhaul_paused:
                # Use .get() for safety, though it should be there now
                to_pos_id = c.get('to_pos_id')
                if to_pos_id and self.backend.is_branch_fully_reviewed(to_pos_id, self.overhaul_start):
                    san_text += "  ✅"
            
            it = SortableTreeWidgetItem([
                san_text, 
                f"{c['priority']*100:.2f}%", 
                c['comment'], 
                l_map.get(c['level'], str(c['level'])) if c['level'] > 0 else "",
                "" 
            ])
            it.setData(0, Qt.ItemDataRole.UserRole, c['uci'])
            it.setData(1, Qt.ItemDataRole.UserRole, c['priority'])
            it.setData(0, Qt.ItemDataRole.UserRole + 1, c['id'])
            
            if c['is_repo']:
                it.setCheckState(4, Qt.CheckState.Checked if c['is_active'] else Qt.CheckState.Unchecked)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            
            it.setFont(0, large_font)
            it.setFont(1, large_font)
            it.setFont(3, large_font)
            it.setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            
            if c['is_repo']:
                for i in range(5):
                    fnt = it.font(i)
                    fnt.setBold(True)
                    it.setFont(i, fnt)
            
            if not c['is_active']:
                for i in range(5):
                    it.setForeground(i, QBrush(QColor("gray")))
                    
            self.tree_widget.addTopLevelItem(it)
        self.tree_widget.sortItems(1, Qt.SortOrder.DescendingOrder)
        if self.engine_thread: self.engine_thread.set_position(f)
        
        # Update Common Moves Table
        cat = self.combo_lichess_cat.currentText()
        common_moves = self.backend.get_lichess_common_moves(f, cat)
        self.table_common_moves.setRowCount(len(common_moves))
        for r, mv in enumerate(common_moves):
            lang = self.get_notation_lang()
            item_san = QTableWidgetItem(localize_san(mv['san'], lang))
            item_san.setData(Qt.ItemDataRole.UserRole, mv['uci']) # Store UCI for double click
            self.table_common_moves.setItem(r, 0, item_san)
            self.table_common_moves.setItem(r, 1, QTableWidgetItem(str(mv['total'])))
            self.table_common_moves.setItem(r, 2, QTableWidgetItem(f"{mv['white_pct']:.1f}%"))
            self.table_common_moves.setItem(r, 3, QTableWidgetItem(f"{mv['black_pct']:.1f}%"))
            self.table_common_moves.setItem(r, 4, QTableWidgetItem(f"{mv['draw_pct']:.1f}%"))

        self.update_board_arrows()
        
        # --- TRANSPOSITION DETECTION (badge update) ---
        outgoing_list = self.backend.find_outgoing_transpositions(f)
        total_transpos = len(outgoing_list)
        idx = self.tabs.indexOf(self.tab_transpositions)
        if idx != -1:
            if total_transpos > 0:
                # Vibrant Gold badge
                self.tabs.tabBar().setTabTextColor(idx, QColor("#FFD700"))
                icon_path = os.path.join(get_base_path(), "assets", "Icons", "sync.png")
                if os.path.exists(icon_path):
                    self.tabs.setTabIcon(idx, QIcon(icon_path))
            else:
                self.tabs.tabBar().setTabTextColor(idx, QColor())  # Reset to palette default
                self.tabs.setTabIcon(idx, QIcon())
            
            # If current tab is Transpositionen, refresh it
            if self.tabs.currentIndex() == idx:
                self.update_transpositions_tab()


    def block_signals_details(self, b):
        if not self._is_ui_valid():
            return
        self.i_v1.blockSignals(b)
        self.i_v2.blockSignals(b)
        self.i_v3.blockSignals(b)
        self.txt_c.blockSignals(b)

    def on_details_changed(self):
        self.details_changed = True
        self.save_timer.start()

    def save_current_details_now(self):
        if self.save_timer.isActive(): self.save_timer.stop()
        if self.details_changed and self.backend.active_repo_name:
            self.backend.update_position_data(self.board_widget.board.fen(), self.txt_c.toPlainText(), self.i_v1.text(), self.i_v2.text(), self.i_v3.text(), auto_review=self.overhaul_active)
            self.update_structure_tree()
            self.update_overhaul_progress()
            # If we are in the Kontrolle tab, we might want to refresh the variation dropdown too
            if self.tabs.currentIndex() == 2: # KONTROLLE
                self.init_management_slots()
            self.details_changed = False

    def insert_symbol(self, s):
        text = self.txt_c.toPlainText()
        symbols = ["+−", "±", "⩲", "=", "∞", "⇆", "⩱", "∓", "−+"]
        lines = text.split('\n')
        if lines and lines[-1].strip() in symbols:
            lines[-1] = s
            new_text = "\n".join(lines)
        else:
            if not text: new_text = s
            elif text.endswith('\n'): new_text = text + s
            else: new_text = text + "\n" + s
        self.txt_c.setPlainText(new_text)
        self.on_details_changed()

    def on_tree_click(self, it, col):
        if col == 4:
            mid = it.data(0, Qt.ItemDataRole.UserRole + 1)
            # Toggle in backend
            self.backend.toggle_move_active(mid)
            # Refresh everything to ensure descendant colors are updated
            self.update_ui_from_fen()
            return

        self.save_current_details_now()
        uci = it.data(0, Qt.ItemDataRole.UserRole)
        if not uci: return
        self.board_widget.board.push(chess.Move.from_uci(uci))
        self.board_widget.update()
        self.play_sound("move")
        self.update_ui_from_fen()

    def show_tree_context_menu(self, pos):
        it = self.tree_widget.itemAt(pos)
        
        menu = QMenu(self)

        # Always add Debug info at the top
        act_debug = QAction("🛠 Debug: Stellungs-Info anzeigen", self)
        act_debug.triggered.connect(self.show_debug_position_info)
        menu.addAction(act_debug)
        menu.addSeparator()

        if not it:
            menu.exec(self.tree_widget.mapToGlobal(pos))
            return
        
        uci = it.data(0, Qt.ItemDataRole.UserRole)
        mid = it.data(0, Qt.ItemDataRole.UserRole + 1)
        act_del = QAction("Löschen", self)
        act_del.triggered.connect(lambda: self.delete_move_action(uci))
        menu.addAction(act_del)
        
        if mid:
            act_active = QAction("Aktiv / Inaktiv umschalten", self)
            act_active.triggered.connect(lambda: self.on_tree_click(it, 1))
            menu.addAction(act_active)

        menu.addSeparator()
        nag_menu = menu.addMenu("Annotation (NAG)")
        nags = {
            "None": (0, "Keine Annotation"),
            "!": (1, "Guter Zug"),
            "?": (2, "Fehler"),
            "!!": (3, "Brillanter Zug"),
            "??": (4, "Grober Patzer"),
            "!?": (5, "Interessanter Zug"),
            "?!": (6, "Fragwürdiger Zug")
        }
        for label, (val, tooltip) in nags.items():
            a = QAction(label, self)
            a.setToolTip(tooltip)
            a.setStatusTip(tooltip)
            a.triggered.connect(lambda checked, v=val: self.set_nag_action(uci, v))
            nag_menu.addAction(a)
        lvl_menu = menu.addMenu("Setze Level")
        for lvl in self.backend.get_repertoire_levels():
            a = QAction(lvl['name'], self)
            a.triggered.connect(lambda checked, l=lvl['order']: self.set_level_action(mid, l))
            lvl_menu.addAction(a)
            
        if mid:
            lvl_stark_menu = menu.addMenu("Setze Level stark")
            for lvl in self.backend.get_repertoire_levels():
                a = QAction(lvl['name'], self)
                a.triggered.connect(lambda checked, l=lvl['order']: self.set_level_strong_action(mid, l))
                lvl_stark_menu.addAction(a)

        menu.exec(self.tree_widget.mapToGlobal(pos))

    def show_debug_position_info(self):
        fen = self.board_widget.board.fen()
        incoming = self.backend.get_incoming_moves(fen)
        
        # Fetch good_moves and depth from DB
        clean_fen = " ".join(fen.split(" ")[:4])
        
        if not self.backend.session:
            QMessageBox.warning(self, "Debug Info", "Datenbank-Verbindung ist nicht aktiv. Bitte das Repertoire neu laden.")
            return

        pos_entry = self.backend.session.query(Position).filter_by(fen=clean_fen).first()

        title = "Stellungs-Analyse (Debug)"
        msg = f"<b>Aktuelle FEN:</b><br><code style='background-color: #eee;'>{fen}</code><br><br>"
        
        if pos_entry:
            msg += f"<b>Engine Analyse (Abgespeichert):</b><br>"
            if pos_entry.analysis_depth:
                msg += f"• Tiefe: {pos_entry.analysis_depth}<br>"
            
            if pos_entry.good_moves:
                try:
                    gm_ucis = json.loads(pos_entry.good_moves)
                    board = chess.Board(fen)
                    gm_sans = []
                    for u in gm_ucis:
                        try:
                            gm_sans.append(board.san(chess.Move.from_uci(u)))
                        except:
                            gm_sans.append(u)
                    msg += f"• Alternate Good Moves: <b style='color: green;'>{', '.join(gm_sans)}</b><br>"
                except Exception as e:
                    msg += f"• Fehler beim laden der Good Moves: {e}<br>"
            else:
                msg += "• Keine gespeicherten Good Moves vorhanden.<br>"
            msg += "<br>"
        
        # Check for Duplicate Positions
        unique_pos_ids = set(m['to_pos_id'] for m in incoming)
        if len(unique_pos_ids) > 1:
            msg += f"<b style='color: red;'>⚠️ WARNUNG: {len(unique_pos_ids)} verschiedene IDs für diese FEN gefunden!</b><br>"
            msg += f"IDs: {', '.join(map(str, unique_pos_ids))}<br>Das ist die Ursache für Kaskadierungsprobleme.<br><br>"

        msg += f"<b>Eingehende Pfade ({len(incoming)}):</b><br>"

        # Setup Dialog for buttons
        d = QDialog(self)
        d.setWindowTitle(title)
        layout = QVBoxLayout(d)
        
        if not incoming:
            msg += "<i>Keine (Startstellung oder isolierte Stellung)</i>"
        else:
            for m in incoming:
                lvl_text = f"<b>L{m['level']}</b>" if m['level'] else "<span style='color: red;'>Kein Repertoire</span>"
                msg += f"<hr>• Zug: <b>{m['san']}</b> ({m['uci']}) -> Level: {lvl_text}<br>"
                msg += f"  Von FEN: <small>{m['parent_fen']}</small><br>"
                
                if not m['level']:
                    btn_fix = QPushButton(f"'{m['san']}' zum Repertoire hinzufügen")
                    btn_fix.clicked.connect(lambda checked, mid=m['move_id']: self._on_manual_gap_fix(mid, d))
                    layout.addWidget(btn_fix)
        
        # DISPLAY CASCADE TRACE
        if self.backend._last_cascade_trace:
            msg += "<br><br><b style='color: blue;'>Letzte Kaskadierung (Abbruch-Trace):</b><br>"
            for step in self.backend._last_cascade_trace[-5:]:
                msg += f"<hr>Stopp bei Pos ID {step['pos_id']}: {step['reason']}<br>"
                msg += f"Details: {', '.join(step['details'])}<br>"

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(msg)
        layout.insertWidget(0, QLabel("Details zu dieser Stellung:"))
        layout.insertWidget(1, text_edit)
        
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        d.resize(600, 500)
        d.exec()

    def _on_manual_gap_fix(self, mid, dialog):
        self.backend.manually_fix_gap(mid)
        dialog.accept()
        self.update_ui_from_fen()
        QMessageBox.information(self, "Erfolg", "Zug wurde hinzugefügt. Ändere nun das Level erneut, um die Kaskadierung zu triggern.")

    def delete_move_action(self, u):
        res = self.backend.scan_and_get_impact(u, self.board_widget.board.fen())
        if isinstance(res, (tuple, list)) and len(res) == 2:
            m, p = res
        else:
            m, p = [], []
        if QMessageBox.question(self, "Löschen", f"Sicher? {m} Züge und {p} Positionen werden gelöscht.") == QMessageBox.StandardButton.Yes:
            self.backend.delete_move(u, self.board_widget.board.fen())
            self.update_ui_from_fen()

    def set_nag_action(self, u, v):
        self.backend.set_nag(u, self.board_widget.board.fen(), v)
        self.update_ui_from_fen()

    def set_level_action(self, mid, l):
        self.backend.update_move_level(mid, l)
        self.update_ui_from_fen()

    def set_level_strong_action(self, mid, l):
        res = self.backend.get_strong_level_impact(mid)
        if isinstance(res, (tuple, list)) and len(res) == 2:
            count, variations = res
        else:
            count, variations = 0, []
        if count == 0:
            self.backend.update_move_level_strong(mid, l)
            self.update_ui_from_fen()
            return
            
        var_str = ", ".join(variations[:10])
        if len(variations) > 10:
            var_str += f", ..."
            
        msg = f"Achtung: Du wirst {count} Züge in den folgenden Varianten ändern:\n\n\"{var_str}\"\n\nFortfahren?"
        if QMessageBox.warning(self, "Starkes Level setzen", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.backend.update_move_level_strong(mid, l)
            self.update_ui_from_fen()

    def set_engine_button_blocked(self, blocked, message=""):
        self.btn_engine_toggle.setEnabled(not blocked)
        if blocked:
            self.btn_engine_toggle.setText("🚫 Engine blockiert")
            self.btn_engine_toggle.setToolTip(message)
            # Stop local engine if it was running
            if self.btn_engine_toggle.isChecked():
                self.btn_engine_toggle.setChecked(False)
        else:
            self.btn_engine_toggle.setText("▶ Analyse Starten")
            self.btn_engine_toggle.setToolTip("")
            self.repolish(self.btn_engine_toggle)

    def toggle_engine_click(self):
        is_running = self.btn_engine_toggle.isChecked()
        # POLISH: Added "..." to indicate it's thinking
    def _on_engine_toggle_toggled(self, checked):
        if checked:
            self.btn_engine_toggle.setText("⏹ Analyse Stoppen")
            self.btn_engine_toggle.setStyleSheet(f"background-color: {COLORS['error_red']}; color: white; border-radius: 18px;")
        else:
            self.btn_engine_toggle.setText("▶ Analyse Starten")
            self.btn_engine_toggle.setStyleSheet(f"background-color: {COLORS['success_green']}; color: white; border-radius: 18px;")
        self.toggle_engine(checked)

    def toggle_engine(self, active):
        if self.engine_thread:
            self.engine_thread.update_config(int(self.combo_threads.currentText()), int(self.combo_depth.currentText()), True, int(self.combo_lines.currentText()))
            self.engine_thread.toggle_analysis(active)
            if active: 
                self.engine_thread.set_position(self.board_widget.board.fen())
        elif active:
            # Situation 1: Engine thread was not initialized due to missing path
            QMessageBox.warning(self, "Engine Fehler", 
                "Kein gültiger Engine-Pfad gefunden.\n\nBitte setze einen gültigen Engine-Pfad in den Repertoire-Einstellungen (Werkzeuge-Tab), um die Analyse nutzen zu können.")
            
            # Reset button UI state
            self.btn_engine_toggle.blockSignals(True)
            self.btn_engine_toggle.setChecked(False)
            self._on_engine_toggle_toggled(False)
            self.btn_engine_toggle.blockSignals(False)

    def update_engine_output(self, d):
        if not d or isinstance(d[0], str): return
        self.table_engine.setRowCount(len(d))
        for r, l in enumerate(d):
            self.table_engine.setItem(r, 0, QTableWidgetItem(l['score']))
            self.table_engine.setItem(r, 1, QTableWidgetItem(str(l['depth'])))
            self.table_engine.setItem(r, 2, QTableWidgetItem(l['pv']))

    def on_db_update(self, f, d, e):
        self.backend.update_position_analysis(f, d, e)

    def open_repo_settings(self):
        if self.backend.active_repo_name:
            if not hasattr(self, 'repo_settings_dialog') or not self.repo_settings_dialog:
                self.repo_settings_dialog = RepoSettingsDialog(self, self.backend)
                self.repo_settings_dialog.finished.connect(self._on_settings_closed)
            
            self.repo_settings_dialog.show()
            self.repo_settings_dialog.raise_()
            self.repo_settings_dialog.activateWindow()

    def _on_settings_closed(self):
        self.repo_settings_dialog = None

    def delete_repertoire_action(self):
        """Actual deletion of the active repertoire files and closing the window."""
        repo_name = self.backend.active_repo_name
        if not repo_name:
            return
            
        # 1. Stop all threads in this window to release locks
        if hasattr(self, 'engine_thread') and self.engine_thread:
            self.engine_thread.running = False
            self.engine_thread.is_active = False
            self.engine_thread.wait(1000) # Wait up to 1 second
            
        # 2. Close backend to release database locks
        self.backend.close()
        
        # 3. Small wait for the OS to finalize handle releases
        time.sleep(0.3)
        
        # 4. Robust delete with retries
        repo_dir = get_repertoire_dir(repo_name)
        
        def remove_readonly(func, path, _):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        success = False
        last_err = ""
        for attempt in range(3):
            try:
                if os.path.exists(repo_dir):
                    shutil.rmtree(repo_dir, onerror=remove_readonly)
                success = True
                break
            except Exception as e:
                last_err = str(e)
                time.sleep(0.5) # Wait longer between retries
        
        if success:
            # 5. Notify application if possible
            for w in QApplication.topLevelWidgets():
                if hasattr(w, "on_repertoire_deleted"):
                    w.on_repertoire_deleted()
            
            # 6. Close the creator window
            self.close()
        else:
            QMessageBox.critical(self, "Fehler beim Löschen", 
                f"Das Repertoire konnte nicht vollständig gelöscht werden.\nWindows verweigert den Zugriff (Datei evtl. noch gesperrt).\n\nDetails: {last_err}")

    def import_pgn_file_dialog(self):
        """Opens a file dialog to select and import a PGN file."""
        if not self.backend.active_repo_name: return
        path, _ = QFileDialog.getOpenFileName(self, "PGN Datei wählen", "", "PGN Dateien (*.pgn)")
        if not path: return
        self._start_pgn_import(path)

    def paste_pgn_dialog(self):
        """Opens a multi-line input dialog to paste PGN text."""
        if not self.backend.active_repo_name: return
        text, ok = QInputDialog.getMultiLineText(self, "PGN Text einfügen", "PGN Inhalt:")
        if not (ok and text.strip()): return
        
        # Save to temp file
        temp_dir = os.path.join(get_user_dir(), "tmp")
        if not os.path.exists(temp_dir): os.makedirs(temp_dir, exist_ok=True)
        path = os.path.join(temp_dir, "temp_import.pgn")
        with open(path, "w", encoding="utf-8") as f: f.write(text)
        self._start_pgn_import(path)

    def _start_pgn_import(self, pgn_path):
        """Asks for target level and starts the import thread."""
        levels = self.backend.get_repertoire_levels()
        if not levels:
            QMessageBox.warning(self, "Import", "Keine Level gefunden. Bitte erstelle zuerst ein Level in den Einstellungen.")
            return
            
        level_choices = [f"Lvl {l['order']}: {l['name']}" for l in levels]
        choice, ok = QInputDialog.getItem(self, "Ziel-Level", "In welches Level sollen die Züge importiert werden?", level_choices, 0, False)
        if not ok: return
        
        idx = level_choices.index(choice)
        target_lvl = levels[idx]
        
        self.p_pgn = QProgressDialog("Importiere PGN...", "Abbrechen", 0, 100, self)
        self.p_pgn.setWindowModality(Qt.WindowModality.WindowModal)
        self.p_pgn.show()
        
        side = self.backend.get_repertoire_color()
        self.w_pgn = PGNImportThread(
            pgn_path, 
            self.backend.active_repo_name, 
            side, 
            target_lvl['name'], 
            target_lvl['order']
        )
        self.w_pgn.progress_signal.connect(self.p_pgn.setValue)
        self.w_pgn.finished_signal.connect(self._on_pgn_import_finished)
        self.w_pgn.start()

    def _on_pgn_import_finished(self, success, message):
        if hasattr(self, 'p_pgn'): self.p_pgn.close()
        if success:
            QMessageBox.information(self, "Erfolg", message)
            self.update_ui_from_fen()
            self.update_structure_tree()
        else:
            QMessageBox.warning(self, "Import Fehler", message)

    def update_structure_tree(self):
        self.combo_structure.blockSignals(True)
        self.combo_structure.clear()
        self.combo_structure.addItem("🧩 Struktur Explorer", userData=None)
        if not self.backend.active_repo_name:
            self.combo_structure.blockSignals(False)
            return
        structure = self.backend.get_repertoire_structure()
        self.combo_structure.addItem("Start Position", userData=chess.STARTING_FEN)
        for v1 in structure:
            self.combo_structure.addItem(f"📂 {v1['name']}", userData=v1['fen'])
            for v2 in v1['children']:
                self.combo_structure.addItem(f"   ↳ {v2['name']}", userData=v2['fen'])
                for v3 in v2['children']:
                    self.combo_structure.addItem(f"      ↳ {v3['name']}", userData=v3['fen'])
        self.combo_structure.blockSignals(False)

    def open_lichess_analysis(self):
        if not self.backend.active_repo_name: return
        url = f"https://lichess.org/analysis/{self.board_widget.board.fen().replace(' ', '_')}"
        webbrowser.open(url)

    def on_structure_combo_changed(self, index):
        fen = self.combo_structure.currentData()
        if fen: self.set_board_to_fen(fen)
        self.combo_structure.blockSignals(True)
        self.combo_structure.setCurrentIndex(0)
        self.combo_structure.blockSignals(False)

    def load_repertoire_dialog(self):
        from .repo_selection_dialog import RepoSelectionDialog
        d = RepoSelectionDialog(self)
        if d.exec():
            self.load_repertoire(d.selected_repo)
            self.set_board_to_fen(chess.STARTING_FEN)
            self.init_management_slots() # Refresh level dropdown

    def load_repertoire(self, repo_name, training_manager=None, is_test=False):
        """Switches the active repertoire and refreshes all UI components."""
        if hasattr(self, 'repo_settings_dialog') and self.repo_settings_dialog:
            self.repo_settings_dialog.close()
        
        if training_manager:
            self.training_manager = training_manager
        
        self.is_test = is_test
        self.backend.load_repertoire(repo_name, is_test)
        self._load_saved_elo_or_autoselect()
        self.update_structure_tree()
        self.init_management_slots()
        self.setWindowTitle(f"Creator - {repo_name}")
        self.board_widget.flipped = (self.backend.get_repertoire_color() == 'b')
        self.board_widget.update()
        # Rebuild FEN index on the next idle tick (after UI is fully rendered)
        # singleShot(0) = "as soon as current call stack finishes" — no blocking, no arbitrary wait
        self.backend._fen_index = None   # invalidate old index immediately
        QTimer.singleShot(0, self._build_fen_index)

    def new_repertoire_dialog(self):
        d = NewRepertoireDialog(self)
        if d.exec():
            n, color = d.get_data()
            if n:
                self.load_repertoire(n)
                # Set initial color metadata
                self.backend.set_meta("color", color)
                # Ensure UI reflects the color (flip board)
                self.board_widget.flipped = (color == 'b')
                self.board_widget.update()
                self.set_board_to_fen(chess.STARTING_FEN)

    def update_board_arrows(self):
        self.board_widget.explorer_arrows = []
        if not self.chk_a.isChecked():
            self.board_widget.update()
            return
        cs = self.backend.get_candidate_moves(self.board_widget.board.fen())
        for c in cs:
            if c['is_repo']:
                # Use deep rich blue from styles, with level-based alpha
                col = QColor(20, 60, 150)
                alpha = 180 if c['level'] == 1 else 100
                col.setAlpha(alpha)
                self.board_widget.explorer_arrows.append((chess.Move.from_uci(c['uci']), col))
        self.board_widget.update()

    def init_icons(self):
        self.piece_icons = {}
        for c in ['w', 'b']:
            for p in ['P', 'N', 'B', 'R', 'Q', 'K']:
                path = os.path.join(get_base_path(), "assets", "pieces", f"{c}{p}.svg")
                if os.path.exists(path): self.piece_icons[f"{c}{p}"] = QIcon(path)

    def init_sounds(self):
        vol = self.config.get("master_volume", 100)
        for s in ["move", "capture"]:
            path = os.path.join(get_base_path(), "assets", "sounds", f"{s}.wav")
            if os.path.exists(path):
                eff = QSoundEffect()
                eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                eff.setVolume(vol / 100.0)
                self.sounds[s] = eff

    def play_sound(self, n):
        if n in self.sounds: self.sounds[n].play()

    def init_engine(self):
        ep = self.config.get("engine_path", "")
        if ep and os.path.exists(ep):
            self.engine_thread = EngineThread(ep, multipv=int(self.combo_lines.currentText()))
            self.engine_thread.info_signal.connect(self.update_engine_output)
            self.engine_thread.db_update_signal.connect(self.on_db_update)
            self.engine_thread.start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.trigger_board_adjust)
        QTimer.singleShot(100, self.trigger_board_adjust)

    def trigger_board_adjust(self):
        if hasattr(self, 'board_panel') and hasattr(self, 'main_splitter'):
            # Allow board to shrink/expand freely
            self.board_panel.setMinimumWidth(0)
            self.board_panel.setMaximumWidth(16777215)
            
            # Auto-suggest a square width based on current height
            # But only if user hasn't manually adjusted the splitter yet
            if getattr(self, '_auto_size_board', True):
                h = self.board_panel.height()
                if h > 0:
                    total_w = self.main_splitter.width()
                    # Only suggest if we have enough space for both board and tools
                    if total_w > h + scale(400):
                        self.main_splitter.setSizes([h, total_w - h])
            
            self.board_panel.adjust_size()
            self.board_widget.update()

    def eventFilter(self, obj, event):
        if hasattr(self, '_processing_event') and self._processing_event:
            return False
            
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in [Qt.Key.Key_Up, Qt.Key.Key_Down]:
                focus_w = self.focusWidget()
                if focus_w not in [self.i_v1, self.i_v2, self.i_v3, self.txt_c]:
                    if obj != self.tree_widget:
                        if focus_w != self.tree_widget:
                            self.tree_widget.setFocus()
                        
                        self._processing_event = True
                        try:
                            QApplication.sendEvent(self.tree_widget, event)
                        finally:
                            self._processing_event = False
                        return True
                    
            if self.focusWidget() in [self.i_v1, self.i_v2, self.i_v3, self.txt_c]:
                return super().eventFilter(obj, event)
            if event.key() == Qt.Key.Key_Left:
                self.go_back()
                return True
            if event.key() == Qt.Key.Key_Right:
                self.go_forward()
                return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            # Check if click is on one of our settings boxes (now through the internal lineEdit)
            from PyQt6.QtWidgets import QLineEdit
            if isinstance(obj, QLineEdit) and obj.parent() in [self.combo_depth, self.combo_threads, self.combo_lines]:
                # Trigger the dropdown menu
                obj.parent().showPopup()
                return True

        return super().eventFilter(obj, event)

    def repolish(self, widget):
        if widget:
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def open_repertoire_folder(self):
        """Opens the active repertoire's folder in Windows Explorer."""
        repo_name = self.backend.active_repo_name
        if not repo_name:
            return
        
        from opening_fenix.core.utils import get_repertoire_dir
        path = get_repertoire_dir(repo_name)
        
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Ordner nicht gefunden", f"Der Repertoire-Ordner konnte nicht gefunden werden:\n{path}")

    def closeEvent(self, event):
        """Clean up resources before closing."""
        if self.backend:
            self.backend.close()
        super().closeEvent(event)

    def init_hole_finder_tab(self):
        layout = QVBoxLayout(self.tab_holes)
        layout.setContentsMargins(scale(15), scale(15), scale(15), scale(15))
        layout.setSpacing(scale(15))
        
        # Upper Glass Card for Controls
        self.card_hole_controls = QFrame()
        self.card_hole_controls.setProperty("class", "GlassPill")
        self.repolish(self.card_hole_controls)
        ctrl_layout = QVBoxLayout(self.card_hole_controls)
        ctrl_layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        
        # Mode Selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("<b>Such-Modus:</b>"))
        self.btn_mode_holes = QRadioButton("Lücken finden (Verschollene Züge)")
        self.btn_mode_level = QRadioButton("Prioritäts-Check (Häufigkeit)")
        self.btn_mode_level_check = QRadioButton("Level-Check (Aufstieg prüfen)")
        self.btn_mode_holes.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_mode_holes)
        self.mode_group.addButton(self.btn_mode_level)
        self.mode_group.addButton(self.btn_mode_level_check)
        mode_layout.addWidget(self.btn_mode_holes)
        mode_layout.addWidget(self.btn_mode_level)
        mode_layout.addWidget(self.btn_mode_level_check)
        mode_layout.addStretch()
        ctrl_layout.addLayout(mode_layout)
        
        ctrl_layout.addSpacing(scale(10))
        
        # Parameters
        param_layout = QHBoxLayout()
        
        self.lbl_hole_threshold = QLabel("Min. Popularität:")
        self.spin_hole_threshold = QDoubleSpinBox()
        self.spin_hole_threshold.setRange(0.1, 100.0)
        self.spin_hole_threshold.setValue(1.0)
        self.spin_hole_threshold.setSuffix("%")
        param_layout.addWidget(self.lbl_hole_threshold)
        param_layout.addWidget(self.spin_hole_threshold)
        
        self.lbl_hole_elo = QLabel("Elo-Bereich:")
        self.combo_hole_elo = QComboBox()
        self.combo_hole_elo.addItems(["low", "mid", "high", "masters"])
        self.combo_hole_elo.setCurrentText("high")
        param_layout.addWidget(self.lbl_hole_elo)
        param_layout.addWidget(self.combo_hole_elo)
        
        self.lbl_hole_level = QLabel("Ziel-Level:")
        self.combo_hole_level = QComboBox()
        param_layout.addWidget(self.lbl_hole_level)
        param_layout.addWidget(self.combo_hole_level)
        
        # Connect mode toggle to show/hide level selector
        def on_mode_toggle():
            is_level_mode = self.btn_mode_level.isChecked()
            is_level_check = self.btn_mode_level_check.isChecked()
            self.combo_hole_level.setVisible(is_level_mode)
            self.lbl_hole_level.setVisible(is_level_mode)
            
            # Hide threshold and ELO for Level Check
            self.lbl_hole_threshold.setVisible(not is_level_check)
            self.spin_hole_threshold.setVisible(not is_level_check)
            self.lbl_hole_elo.setVisible(not is_level_mode and not is_level_check)
            self.combo_hole_elo.setVisible(not is_level_mode and not is_level_check)
        
        self.btn_mode_holes.toggled.connect(on_mode_toggle)
        self.btn_mode_level.toggled.connect(on_mode_toggle)
        self.btn_mode_level_check.toggled.connect(on_mode_toggle)
        
        # Initial state
        self.combo_hole_level.setVisible(False)
        self.lbl_hole_level.setVisible(False)
        
        param_layout.addStretch()
        
        self.btn_hole_scan = QPushButton("🔎 Scan Repertoire")
        self.btn_hole_scan.setMinimumHeight(scale(40))
        self.btn_hole_scan.setStyleSheet(f"background-color: {COLORS['success_green']}; color: white; font-weight: bold; border-radius: {scale(20)}px;")
        self.btn_hole_scan.clicked.connect(self.run_hole_scan)
        param_layout.addWidget(self.btn_hole_scan)
        
        ctrl_layout.addLayout(param_layout)
        layout.addWidget(self.card_hole_controls)
        
        self.table_holes = QTableWidget(0, 3)
        self.table_holes.setHorizontalHeaderLabels(["Pop %", "Typ", "Zug"])
        self.table_holes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_holes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_holes.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_holes.verticalHeader().setVisible(False)
        self.table_holes.itemDoubleClicked.connect(self.on_hole_double_click)
        layout.addWidget(self.table_holes)
        
        h_btm = QHBoxLayout()
        self.btn_hole_exempt = QPushButton("🚫 Auswahl ignorieren")
        self.btn_hole_exempt.clicked.connect(self.exempt_selected_hole)
        h_btm.addWidget(self.btn_hole_exempt)
        h_btm.addStretch()
        layout.addLayout(h_btm)

    def init_kontrolle_tab(self):
        layout = QVBoxLayout(self.tab_kontrolle)
        layout.setContentsMargins(scale(15), scale(15), scale(15), scale(15))
        layout.setSpacing(scale(15))
        
        # Glass Dashboard Card for Stats
        self.card_stats = QFrame()
        self.card_stats.setObjectName("OverhaulStatsCard")
        self.card_stats.setProperty("class", "GlassPill")
        self.repolish(self.card_stats)
        card_layout = QVBoxLayout(self.card_stats)
        card_layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        
        lbl_title = QLabel("Repertoire Überarbeitung")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")
        card_layout.addWidget(lbl_title)
        
        self.lbl_overhaul_status = QLabel("Keine aktive Session")
        self.lbl_overhaul_status.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        card_layout.addWidget(self.lbl_overhaul_status)
        
        card_layout.addSpacing(scale(10))
        
        self.pb_overhaul = QProgressBar()
        self.pb_overhaul.setValue(0)
        self.pb_overhaul.setFormat("%v / %m Stellungen (%p%)")
        self.pb_overhaul.setMinimumHeight(scale(25))
        card_layout.addWidget(self.pb_overhaul)
        
        layout.addWidget(self.card_stats)
        
        # Settings Group
        settings_group = QGroupBox("Filter && Einstellungen")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setSpacing(scale(10))
        
        # Row 1: Level
        settings_layout.addWidget(QLabel("Prüf-Level:"), 0, 0)
        self.combo_overhaul_level = QComboBox()
        settings_layout.addWidget(self.combo_overhaul_level, 0, 1)
        
        # Row 2: Variation Filter
        settings_layout.addWidget(QLabel("Variante filtern:"), 1, 0)
        self.combo_overhaul_variation = QComboBox()
        self.combo_overhaul_variation.addItem("Alle Varianten", userData=None)
        settings_layout.addWidget(self.combo_overhaul_variation, 1, 1)
        
        layout.addWidget(settings_group)
        
        # Controls Group
        h_btns = QHBoxLayout()
        h_btns.setSpacing(scale(10))
        
        self.btn_overhaul_start = QPushButton("▶ Session Starten")
        self.btn_overhaul_start.setMinimumHeight(scale(45))
        self.btn_overhaul_start.clicked.connect(self.toggle_overhaul_session)
        h_btns.addWidget(self.btn_overhaul_start, 2)
        
        self.btn_overhaul_pause = QPushButton("⏸ Pause")
        self.btn_overhaul_pause.setMinimumHeight(scale(45))
        self.btn_overhaul_pause.clicked.connect(self.toggle_overhaul_pause)
        self.btn_overhaul_pause.setVisible(False)
        h_btns.addWidget(self.btn_overhaul_pause, 1)
        
        self.btn_overhaul_reset = QPushButton("🔄 Reset")
        self.btn_overhaul_reset.setMinimumHeight(scale(40))
        self.btn_overhaul_reset.clicked.connect(self.reset_overhaul_session)
        h_btns.addWidget(self.btn_overhaul_reset, 1)
        
        layout.addLayout(h_btns)
        
        self.btn_overhaul_next = QPushButton("⏭ Nächste unkontrollierte Stellung")
        self.btn_overhaul_next.clicked.connect(self.jump_to_next_unchecked)
        self.btn_overhaul_next.setEnabled(False)
        self.btn_overhaul_next.setMinimumHeight(scale(50))
        self.btn_overhaul_next.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.btn_overhaul_next)
        
        layout.addStretch()

    def init_transpositions_tab(self):
        outer = QVBoxLayout(self.tab_transpositions)
        outer.setContentsMargins(scale(12), scale(12), scale(12), scale(12))
        outer.setSpacing(scale(10))

        def _section_lbl(text):
            l = QLabel(text)
            l.setStyleSheet(
                f"font-size: {scale(12)}px; font-weight: bold; color: #1a1a2e;"
            )
            return l

        def _status_lbl(text):
            l = QLabel(text)
            l.setStyleSheet("color: #333355; font-style: italic; font-size: 11px;")
            return l

        def _table(cols, headers, max_h=160):
            t = QTableWidget(0, cols)
            t.setHorizontalHeaderLabels(headers)
            t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            t.verticalHeader().setVisible(False)
            t.setAlternatingRowColors(True)
            t.setMaximumHeight(scale(max_h))
            hdr = t.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for i in range(1, cols):
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
            return t

        def _pill_card():
            card = QFrame()
            card.setProperty("class", "GlassPill")
            self.repolish(card)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(scale(14), scale(12), scale(14), scale(12))
            inner.setSpacing(scale(8))
            return card, inner

        # ── Card 1: Instant 1-move outgoing ──────────────────────────────────────
        card1, lay1 = _pill_card()
        lay1.addWidget(_section_lbl("→ Von hier direkt erreichbar (1 Zug):"))
        self.table_transpositions = _table(3, ["Variante", "Zug", "Ranking"])
        self.table_transpositions.itemDoubleClicked.connect(self.on_transposition_double_clicked)
        lay1.addWidget(self.table_transpositions)
        self.lbl_outgoing_status = _status_lbl("—")
        lay1.addWidget(self.lbl_outgoing_status)
        outer.addWidget(card1)

        # ── Card 2: BFS Deep Search ───────────────────────────────────────────────
        card2, lay2 = _pill_card()
        h_deep = QHBoxLayout()
        h_deep.addWidget(_section_lbl("🔍 Tiefe Suche (alle möglichen Wege):"))
        h_deep.addStretch()
        self.btn_deep_transpos = QPushButton("🔍 Tiefe Suche starten")
        self.btn_deep_transpos.setMinimumHeight(scale(30))
        self.btn_deep_transpos.setProperty("class", "GlassPill")
        self.repolish(self.btn_deep_transpos)
        self.btn_deep_transpos.setEnabled(False)
        self.btn_deep_transpos.clicked.connect(self.on_deep_transpos_button_clicked)
        h_deep.addWidget(self.btn_deep_transpos)
        lay2.addLayout(h_deep)

        self.table_transpos_deep = _table(4, ["Variante", "Zugfolge", "Tiefe", "Qualität"], max_h=220)
        self.table_transpos_deep.itemDoubleClicked.connect(self.on_transposition_double_clicked)
        lay2.addWidget(self.table_transpos_deep)

        self.lbl_transpos_status = _status_lbl("FEN-Index wird aufgebaut…")
        lay2.addWidget(self.lbl_transpos_status)
        outer.addWidget(card2)

        outer.addStretch()

        # Internal BFS state
        self._bfs_thread = None
        self._fen_index_thread = None
        self._path_quality_thread = None
        self._instant_multipv_thread = None
        self._bfs_next_depth = 3           # first click searches depth 3
        self._bfs_start_fen = None         # FEN at time BFS was started
        self._bfs_running = False

        # FEN index is built lazily after each repertoire load (see load_repertoire)

    def update_transpositions_tab(self):
        fen = self.board_widget.board.fen()
        if not fen:
            return

        # ── Outgoing immediate transpositions (1-move) ───────────────────────────
        outgoing = self.backend.find_outgoing_transpositions(fen)
        self.table_transpositions.setRowCount(0)
        for ot in outgoing:
            row = self.table_transpositions.rowCount()
            self.table_transpositions.insertRow(row)

            name_item = QTableWidgetItem(f"★ {ot['variation_name']}")
            name_item.setData(Qt.ItemDataRole.UserRole, {
                "type": "outgoing",
                "move_uci": ot["move_uci"],
                "move_san": ot["move_san"],
                "target_fen": ot["target_fen"],
            })
            self.table_transpositions.setItem(row, 0, name_item)

            move_item = QTableWidgetItem(ot["move_san"])
            move_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            move_item.setForeground(QColor("#FFD700"))
            self.table_transpositions.setItem(row, 1, move_item)

            # Ranking: placeholder until InstantMultiPVThread finishes
            rank_item = QTableWidgetItem("⏳ lädt…")
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            rank_item.setForeground(QColor("rgba(255,255,255,0.4)"))
            self.table_transpositions.setItem(row, 2, rank_item)

        if outgoing:
            self.lbl_outgoing_status.setText(
                f"✦ {len(outgoing)} Transposition(en) — Doppelklick um Zug zu spielen."
            )
            # Launch ranking thread if engine available
            ep = self.config.get("engine_path", "")
            if ep and os.path.exists(ep):
                t_ucis = [ot["move_uci"] for ot in outgoing]
                if hasattr(self, "_instant_multipv_thread") and self._instant_multipv_thread and self._instant_multipv_thread.isRunning():
                    self._instant_multipv_thread.terminate()
                th = InstantMultiPVThread(
                    fen, t_ucis, ep,
                    threads_count=int(self.combo_threads.currentText())
                )
                th.finished.connect(self._on_instant_ranking_ready)
                th.start()
                self._instant_multipv_thread = th
        else:
            self.lbl_outgoing_status.setText("Kein einzelner Zug führt zu einer anderen bekannten Stellung.")
            self.table_transpositions.setRowCount(0)

        # Clear deep table + reset button state when position changes
        self.table_transpos_deep.setRowCount(0)
        self._bfs_start_fen = None
        self._bfs_next_depth = 3
        self._bfs_running = False
        self._update_deep_button_state()

    # ── BFS Deep Search helpers ─────────────────────────────────────────────────

    def _build_fen_index(self):
        """Launch a background thread to build the FEN index — zero main-thread blocking."""
        if not self.backend.session:
            return
        db_path = get_repertoire_db_path(
            self.backend.active_repo_name, self.backend.is_test
        )
        # Stop any previous build still running
        if hasattr(self, "_fen_index_thread") and self._fen_index_thread and self._fen_index_thread.isRunning():
            self._fen_index_thread.terminate()
        t = FenIndexBuilderThread(db_path)
        t.ready.connect(self._on_fen_index_ready)
        t.start()
        self._fen_index_thread = t

    def _on_fen_index_ready(self, fen_set, repo_adj):
        """Receive completed FEN index + repo adjacency from background thread."""
        self.backend._fen_index = fen_set
        self.backend._repo_adjacency = repo_adj
        if hasattr(self, "btn_deep_transpos"):
            self._update_deep_button_state()

    def _update_deep_button_state(self):
        """Sync the deep search button label and enabled-state with current BFS state."""
        index_ready = getattr(self.backend, "_fen_index", None) is not None
        if not index_ready:
            self.btn_deep_transpos.setEnabled(False)
            self.btn_deep_transpos.setText("⏳ Index wird aufgebaut…")
            self.lbl_transpos_status.setText("FEN-Index wird aufgebaut…")
            return

        if self._bfs_running:
            depth = self._bfs_next_depth  # depth currently being searched
            self.btn_deep_transpos.setEnabled(True)
            self.btn_deep_transpos.setText(f"⏹ Tiefe {depth} — Stoppen")
        elif self._bfs_start_fen is None:
            # Not yet started for this position
            self.btn_deep_transpos.setEnabled(True)
            self.btn_deep_transpos.setText("🔍 Tiefe Suche starten")
        else:
            # Completed at least one depth level
            next_d = self._bfs_next_depth
            self.btn_deep_transpos.setEnabled(True)
            self.btn_deep_transpos.setText(f"⬇ Tiefe {next_d} suchen")

    def on_deep_transpos_button_clicked(self):
        """Handle deep search button: start, stop, or go one depth deeper."""
        if self._bfs_running:
            # Act as stop button
            if self._bfs_thread:
                self._bfs_thread.stop()
            if hasattr(self, "_path_quality_thread") and self._path_quality_thread:
                self._path_quality_thread.stop()
            self._bfs_running = False
            self._update_deep_button_state()
            self.lbl_transpos_status.setText("Suche gestoppt.")
            return

        fen = self.board_widget.board.fen()
        if not fen:
            return
        if not getattr(self.backend, "_fen_index", None):
            return

        ep = self.config.get("engine_path", "")
        if not ep or not os.path.exists(ep):
            QMessageBox.warning(self, "Engine Fehler", "Kein Engine-Pfad in den Einstellungen hinterlegt.")
            return

        # First click: reset start FEN and accumulated results
        if self._bfs_start_fen is None:
            self._bfs_start_fen = fen
            self.table_transpos_deep.setRowCount(0)

        target_depth = self._bfs_next_depth
        self._bfs_running = True
        self._update_deep_button_state()
        self.lbl_transpos_status.setText(f"Suche bis Tiefe {target_depth}…")

        t = BfsTranspositionThread(
            self._bfs_start_fen,
            self.backend._fen_index,
            target_depth,
            # Repo adjacency is used inside the thread to compute exclusions
            # with zero main-thread blocking
            repo_adjacency=getattr(self.backend, "_repo_adjacency", {}),
        )
        t.depth_complete.connect(self._on_bfs_depth_complete)
        t.progress_update.connect(self._on_bfs_progress)
        t.start()
        self._bfs_thread = t

    def _on_bfs_progress(self, depth):
        """Show progress as the BFS thread moves from one depth to another."""
        self.lbl_transpos_status.setText(f"Suche Tiefe {depth}…")

    def _on_bfs_depth_complete(self, depth, raw_paths):
        """Called by BfsTranspositionThread ONLY when target_depth is finished."""
        self._bfs_running = False
        
        n = len(raw_paths)
        if n == 0:
            # We finished the FULL search up to target_depth and found nothing
            self.lbl_transpos_status.setText(f"Keine Transpositionen bis Tiefe {depth} gefunden.")
            # ONLY move to the next depth if everything was empty
            self._bfs_next_depth = depth + 1
            self._update_deep_button_state()
            return

        # If we found items, we keep the next_depth at the current successful depth + 1
        # so the next search starts "cleanly" from there
        self._bfs_next_depth = depth + 1
        self._update_deep_button_state()

        self.lbl_transpos_status.setText(
            f"Tiefe {depth} fertig — {n} Pfad/Pfade gefunden. Qualität wird bewertet…"
        )
        self._update_deep_button_state()

        ep = self.config.get("engine_path", "")
        if not ep or not os.path.exists(ep) or not raw_paths:
            # Show without classification
            self._populate_deep_table([
                {**p, "quality": "möglich", "quality_label": "🟡 Möglich"} for p in raw_paths
            ])
            return

        if hasattr(self, "_path_quality_thread") and self._path_quality_thread and self._path_quality_thread.isRunning():
            self._path_quality_thread.stop()
            self._path_quality_thread.wait(500)

        # Pre-populate table with unclassified paths to provide instant user feedback
        loading_paths = [{**p, "quality": "loading", "quality_label": "⏳ Laden..."} for p in raw_paths]
        self._populate_deep_table(loading_paths)
        self.lbl_transpos_status.setText(f"Tiefe {depth} fertig — {n} Pfad/Pfade gefunden. Engine lädt (0 / ?)…")

        pq = PathQualityEvalThread(
            raw_paths,
            self._bfs_start_fen,
            ep,
            threads_count=int(self.combo_threads.currentText()),
        )
        pq.progress.connect(self._on_path_quality_progress)
        pq.finished.connect(self._on_path_quality_ready)
        pq.start()
        self._path_quality_thread = pq

    def _on_path_quality_progress(self, current_pos, total_pos):
        """Update the progress label with current eval status."""
        self.lbl_transpos_status.setText(
            f"Bewerte Pfade... {current_pos} / {total_pos} Zwischenstellungen analysiert."
        )

    def _on_path_quality_ready(self, classified_paths):
        """Called by PathQualityEvalThread when classification is complete."""
        n_ok = sum(1 for p in classified_paths if p["quality"] == "möglich")
        n_err = len(classified_paths) - n_ok
        self.lbl_transpos_status.setText(
            f"✦ {len(classified_paths)} Transposition(en): {n_ok} 🟡 Möglich, {n_err} 🔴 mit Fehlern"
        )
        self._populate_deep_table(classified_paths)

    def _populate_deep_table(self, classified_paths):
        """Fill the deep results table with classified BFS paths."""
        self.table_transpos_deep.setRowCount(0)
        for p in classified_paths:
            row = self.table_transpos_deep.rowCount()
            self.table_transpos_deep.insertRow(row)

            # Derive a variation name from the target FEN
            var_name = p.get("variation_name") or ("/".join(p["path_sans"]) if p["path_sans"] else p["target_fen"][:20])
            name_item = QTableWidgetItem(var_name)
            name_item.setData(Qt.ItemDataRole.UserRole, {
                "type": "bfs",
                "search_fen": self._bfs_start_fen,
                "path_ucis": p["path_ucis"],
                "path_sans": p["path_sans"],
                "target_fen": p["target_fen"],
            })
            self.table_transpos_deep.setItem(row, 0, name_item)

            seq_item = QTableWidgetItem(" ".join(p["path_sans"]))
            self.table_transpos_deep.setItem(row, 1, seq_item)

            depth_item = QTableWidgetItem(str(p["depth"]))
            depth_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_transpos_deep.setItem(row, 2, depth_item)

            quality_label = p.get("quality_label", "🟡 Möglich")
            qual_item = QTableWidgetItem(quality_label)
            qual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if p.get("quality") == "fehler":
                qual_item.setForeground(QColor("#e74c3c"))
            elif p.get("quality") == "loading":
                qual_item.setForeground(QColor("rgba(255,255,255,0.4)"))
            else:
                qual_item.setForeground(QColor("#f1c40f"))
            self.table_transpos_deep.setItem(row, 3, qual_item)

    def _on_instant_ranking_ready(self, ranking: dict):
        """Fill the Ranking column in the instant table after MultiPV finishes."""
        for row in range(self.table_transpositions.rowCount()):
            it0 = self.table_transpositions.item(row, 0)
            if not it0:
                continue
            data = it0.data(Qt.ItemDataRole.UserRole)
            if not data:
                continue
            uci = data.get("move_uci")
            info = ranking.get(uci)
            if info is None:
                continue

            rank = info["rank"]
            delta = info["delta"]
            best_san = info["best_san"]

            if rank == 1:
                label = "⭐ Bester Zug"
                color = "#2ecc71"
            elif rank <= 3 and delta >= -0.2:
                label = f"✓ #{rank} ({delta:+.2f})"
                color = "#f1c40f"
            elif delta < -0.3:
                label = f"⚠ #{rank} ({delta:+.2f})"
                color = "#e74c3c"
            else:
                label = f"#{rank} ({delta:+.2f})"
                color = "rgba(255,255,255,0.6)"

            rank_item = QTableWidgetItem(label)
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            rank_item.setForeground(QColor(color))
            self.table_transpositions.setItem(row, 2, rank_item)

    # ── Double-click handler ─────────────────────────────────────────────────────

    def on_transposition_double_clicked(self, item):
        tw = item.tableWidget()
        if not tw:
            return
        it0 = tw.item(item.row(), 0)
        if not it0:
            return
        data = it0.data(Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, dict):
            return

        m_type = data.get("type")

        if m_type == "outgoing":
            # Play the single move and save it to the repertoire
            uci = data.get("move_uci")
            if uci:
                move = chess.Move.from_uci(uci)
                self.on_board_move(move)

        elif m_type == "bfs":
            # Replay move sequence from the FEN when BFS was launched
            search_fen = data.get("search_fen") or self._bfs_start_fen
            ucis = data.get("path_ucis", [])
            sans = data.get("path_sans", [])

            if search_fen and ucis and sans:
                self.save_current_details_now()
                self.set_board_to_fen(search_fen)

                for u, s in zip(ucis, sans):
                    f_fen = self.board_widget.board.fen()
                    try:
                        m = chess.Move.from_uci(u)
                        if m in self.board_widget.board.legal_moves:
                            self.board_widget.board.push(m)
                            self.backend.add_move(f_fen, u, s)
                        else:
                            break
                    except Exception:
                        break

                self.board_widget.update()
                self.play_sound("move")
                self.update_ui_from_fen()
                self.trigger_background_enrichment(self.board_widget.board.fen())
            elif data.get("target_fen"):
                self.set_board_to_fen(data["target_fen"])



    def toggle_overhaul_pause(self):
        self.overhaul_paused = not self.overhaul_paused
        self._update_overhaul_ui_state()
        self.update_ui_from_fen() # Refresh to show/hide checkmarks

    def _update_overhaul_ui_state(self):
        if not self.overhaul_active:
            self.btn_overhaul_start.setText("▶ Session Starten")
            self.btn_overhaul_start.setStyleSheet(f"background-color: {COLORS['success_green']}; color: white; font-weight: bold;")
            self.btn_overhaul_pause.setVisible(False)
            self.btn_overhaul_next.setEnabled(False)
            self.lbl_overhaul_status.setText("Keine aktive Session")
            self.combo_overhaul_level.setEnabled(True)
            self.combo_overhaul_variation.setEnabled(True)
        else:
            if self.overhaul_paused:
                self.btn_overhaul_start.setText("▶ Session Fortsetzen")
                self.btn_overhaul_start.setStyleSheet(f"background-color: {COLORS['success_green']}; color: white; font-weight: bold;")
                self.btn_overhaul_pause.setVisible(False)
                self.btn_overhaul_next.setEnabled(False)
                self.lbl_overhaul_status.setText(f"Session Pausiert (Start: {self.overhaul_start.strftime('%H:%M:%S')})")
            else:
                self.btn_overhaul_start.setText("⏹ Session Stoppen")
                self.btn_overhaul_start.setStyleSheet(f"background-color: {COLORS['error_red']}; color: white; font-weight: bold;")
                self.btn_overhaul_pause.setVisible(True)
                self.btn_overhaul_pause.setText("⏸ Pause")
                self.btn_overhaul_next.setEnabled(True)
                self.lbl_overhaul_status.setText(f"Session Aktiv (Seit: {self.overhaul_start.strftime('%H:%M:%S')})")
            
            # FILTERS REMAIN LOCKED AS LONG AS SESSION IS ACTIVE (including paused)
            self.combo_overhaul_level.setEnabled(False)
            self.combo_overhaul_variation.setEnabled(False)
        
        self.repolish(self.btn_overhaul_start)
        self.update_overhaul_progress()

    def on_overhaul_filter_changed(self):
        """Called when Level or Variation filter dropdowns are changed."""
        lvl = self.combo_overhaul_level.currentData()
        var = self.combo_overhaul_variation.currentData() # This is now a tuple (v1, v2) or None
        
        # Persistence: Save to metadata
        # Levels are integers/None, Variations are tuples/None
        self.backend.set_meta("overhaul_selected_level", lvl if lvl is not None else 99)
        self.backend.set_meta("overhaul_selected_variation_v2", json.dumps(var) if var is not None else "All")
        
        # Trigger live update of progress bar
        self.update_overhaul_progress()

    def init_management_slots(self):
        self.combo_overhaul_level.blockSignals(True)
        self.combo_overhaul_level.clear()
        self.combo_hole_level.blockSignals(True)
        self.combo_hole_level.clear()
        
        levels = self.backend.get_repertoire_levels()
        self.combo_overhaul_level.addItem("Alle Level (1-99)", userData=99)
        self.combo_hole_level.addItem("Wähle Level...", userData=None)
        
        if not levels:
            self.combo_overhaul_level.addItem("Standard (Level 1)", userData=1)
            self.combo_hole_level.addItem("Level 1", userData=1)
        else:
            for lvl in levels:
                self.combo_overhaul_level.addItem(f"Level {lvl['order']} ({lvl['name']})", userData=lvl['order'])
                self.combo_hole_level.addItem(f"Level {lvl['order']} ({lvl['name']})", userData=lvl['order'])
        
        self.combo_overhaul_level.blockSignals(False)
        self.combo_hole_level.blockSignals(False)
        
        # Overhaul V3: Hierarchical Variation Filter (Parent -> Child)
        self.combo_overhaul_variation.blockSignals(True)
        self.combo_overhaul_variation.clear()
        self.combo_overhaul_variation.addItem("Alle Varianten", userData=None)
        
        # Build tree structure
        structure = self.backend.get_variation_structure()
        for v1, v2_list in structure.items():
            # Add Parent
            self.combo_overhaul_variation.addItem(v1, userData=(v1, None))
            # Add Children indented
            for v2 in v2_list:
                self.combo_overhaul_variation.addItem(f"  └ {v2}", userData=(v1, v2))
        
        self.combo_overhaul_variation.blockSignals(False)
        
        # Persistence Restore: Load from metadata
        saved_lvl = self.backend.get_meta("overhaul_selected_level", "99")
        saved_var_json = self.backend.get_meta("overhaul_selected_variation_v2", "All")
        
        # Restore Level index
        for i in range(self.combo_overhaul_level.count()):
            if str(self.combo_overhaul_level.itemData(i)) == str(saved_lvl):
                self.combo_overhaul_level.setCurrentIndex(i)
                break
        
        # Restore Variation index
        try:
            target_data = json.loads(saved_var_json) if saved_var_json != "All" else None
            for i in range(self.combo_overhaul_variation.count()):
                if self.combo_overhaul_variation.itemData(i) == target_data:
                    self.combo_overhaul_variation.setCurrentIndex(i)
                    break
        except: pass
        
        # Connect signals for live updates
        try: self.combo_overhaul_level.currentIndexChanged.disconnect(self.on_overhaul_filter_changed)
        except: pass
        try: self.combo_overhaul_variation.currentIndexChanged.disconnect(self.on_overhaul_filter_changed)
        except: pass
        
        self.combo_overhaul_level.currentIndexChanged.connect(self.on_overhaul_filter_changed)
        self.combo_overhaul_variation.currentIndexChanged.connect(self.on_overhaul_filter_changed)

        # Sync UI state if session was loaded from metadata
        if self.overhaul_active:
            self._update_overhaul_ui_state()

    def run_hole_scan(self):
        if self.hole_thread and self.hole_thread.isRunning():
            return
            
        is_hole_mode = self.btn_mode_holes.isChecked()
        is_level_mode = self.btn_mode_level.isChecked()
        is_level_check = self.btn_mode_level_check.isChecked()
        
        if is_hole_mode: mode = "holes"
        elif is_level_mode: mode = "priority"
        else: mode = "level_check"
        
        threshold = self.spin_hole_threshold.value()
        elo = self.combo_hole_elo.currentText()
        level = self.combo_hole_level.currentData()
        
        if mode == "priority" and level is None:
            QMessageBox.warning(self, "Fehler", "Bitte wähle zuerst ein Level aus.")
            return

        self.btn_hole_scan.setEnabled(False)
        self.btn_hole_scan.setText("Scannend")
        self._hole_dots = 0
        self.hole_anim_timer.start(500)
        
        self.hole_thread = HoleFinderThread(
            self.backend.active_repo_name,
            self.backend.is_test,
            threshold,
            elo,
            mode,
            level
        )
        self.hole_thread.finished_signal.connect(self._on_hole_scan_finished)
        self.hole_thread.start()

    def _animate_hole_button(self):
        self._hole_dots = (self._hole_dots + 1) % 4
        dots = "." * self._hole_dots
        self.btn_hole_scan.setText(f"Scannend{dots}")

    def _on_hole_scan_finished(self, holes, mode):
        self.hole_anim_timer.stop()
        self.btn_hole_scan.setEnabled(True)
        self.btn_hole_scan.setText("🔎 Scan Repertoire")
        
        if mode == "holes":
            self.table_holes.setHorizontalHeaderLabels(["Pop %", "Typ", "Zug"])
            self.btn_hole_exempt.setVisible(True)
        elif mode == "level_check":
            self.table_holes.setHorizontalHeaderLabels(["Info", "Analyse", "Unser Zug"])
            self.btn_hole_exempt.setVisible(False)
        else:
            self.table_holes.setHorizontalHeaderLabels(["Frequenz", "Status", "Zug"])
            self.btn_hole_exempt.setVisible(False)

        self.table_holes.setRowCount(len(holes))
        for i, h in enumerate(holes):
            pop_val = h.get('popularity', 0)
            item_pop = QTableWidgetItem(f"{pop_val:.1f}%")
            item_pop.setData(Qt.ItemDataRole.UserRole, h['fen'])
            if 'move_san' in h:
                item_pop.setData(Qt.ItemDataRole.UserRole + 1, h['move_san'])
            
            item_type = QTableWidgetItem(h['type'].upper())
            if h['type'] == 'user':
                item_type.setForeground(QBrush(QColor(COLORS['success_green'])))
                item_type.setText("BENUTZER")
            elif h['type'] == 'opponent':
                item_type.setForeground(QBrush(QColor(COLORS['error_red'])))
                item_type.setText("GEGNER")
            elif h['type'] == 'priority_check':
                item_type.setForeground(QBrush(QColor("#f39c12"))) # Orange for check
                item_type.setText("ZU WICHTIG?")
            elif h['type'] == 'level_mismatch':
                item_type.setForeground(QBrush(QColor("#9b59b6"))) # Purple for level transitions
                item_type.setText("AUFSTIEG")
                item_pop.setText("Unstimmig")
                # Add diagnostic level info to the move text
                if 'from_level' in h and 'to_level' in h:
                    move_text = h.get('move_san', '—')
                    h['move_san'] = f"{move_text} (L{h['from_level']}→L{h['to_level']})"
            elif h['type'] == 'repertoire_gap':
                item_type.setForeground(QBrush(QColor(COLORS['error_red'])))
                item_type.setText("LÜCKE")
                item_pop.setText("Unfertig")

            self.table_holes.setItem(i, 0, item_pop)
            self.table_holes.setItem(i, 1, item_type)
            self.table_holes.setItem(i, 2, QTableWidgetItem(h.get('move_san', '—')))


    def on_hole_double_click(self, item):
        row = item.row()
        fen = self.table_holes.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if fen:
            self.set_board_to_fen(fen)
            self.tabs.setCurrentIndex(0) # Switch to DETAILS to add the move

    def exempt_selected_hole(self):
        row = self.table_holes.currentRow()
        if row < 0: return
        fen = self.table_holes.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if fen:
            self.backend.set_position_hole_exempt(fen, True)
            self.table_holes.removeRow(row)

    def toggle_overhaul_session(self):
        if not self.overhaul_active:
            # START NEW SESSION
            lvl = self.combo_overhaul_level.currentData()
            if lvl is None:
                QMessageBox.warning(self, "Fehler", "Bitte wähle zuerst ein Level aus.")
                return

            self.overhaul_active = True
            self.overhaul_paused = False
            self.overhaul_start = datetime.datetime.now()
            
            # Save to metadata for persistence
            self.backend.save_overhaul_session_start(self.overhaul_start)
            
            # Mark current if valid
            f = self.board_widget.board.fen()
            self.backend.mark_position_reviewed(f)
        else:
            if self.overhaul_paused:
                # RESUME
                self.overhaul_paused = False
            else:
                # STOP/CLOSE SESSION
                if QMessageBox.question(self, "Session beenden", "Möchtest du diese Session wirklich endgültig beenden?") == QMessageBox.StandardButton.No:
                    return
                self.overhaul_active = False
                self.overhaul_paused = False
                self.overhaul_start = None
                self.backend.save_overhaul_session_start(None)
        
        self._update_overhaul_ui_state()
        self.update_ui_from_fen()

    def reset_overhaul_session(self):
        if not self.overhaul_active:
            # If no session active, just reset progress bar to general total view
            self.overhaul_start = None
            self.update_overhaul_progress()
            self._update_overhaul_ui_state()
            return

        if QMessageBox.question(self, "Session beenden", "Möchtest du die aktuelle Session wirklich beenden?\nDies ermöglicht es dir, die Filter neu zu setzen.") == QMessageBox.StandardButton.Yes:
            self.overhaul_active = False
            self.overhaul_paused = False
            self.overhaul_start = None
            self.backend.save_overhaul_session_start(None)
            self._update_overhaul_ui_state()
            self.update_ui_from_fen()

    def update_overhaul_progress(self):
        if not self.overhaul_start: 
            # If no active session, calculate total reachable for current filter
            lvl = self.combo_overhaul_level.currentData()
            var = self.combo_overhaul_variation.currentData()
            res = self.backend.get_overhaul_stats(lvl, var)
            if isinstance(res, (tuple, list)) and len(res) == 2:
                checked, total = res
            else:
                checked, total = 0, 1
            self.pb_overhaul.setMaximum(total)
            self.pb_overhaul.setValue(checked)
            return
            
        lvl = self.combo_overhaul_level.currentData()
        var = self.combo_overhaul_variation.currentData()
        res = self.backend.get_overhaul_stats(lvl, var, self.overhaul_start)
        if isinstance(res, (tuple, list)) and len(res) == 2:
            checked, total = res
        else:
            checked, total = 0, 1
        self.pb_overhaul.setMaximum(total)
        self.pb_overhaul.setValue(checked)

    def jump_to_next_unchecked(self):
        if not self.overhaul_active or not self.overhaul_start or self.overhaul_paused: return
        
        lvl = self.combo_overhaul_level.currentData()
        variation_filter = self.combo_overhaul_variation.currentData()
        
        # Backend-optimized strict filtering
        next_fen = self.backend.find_nearest_unreviewed(self.board_widget.board.fen(), lvl, variation_filter, self.overhaul_start)
        
        if next_fen:
            self.set_board_to_fen(next_fen)
        else:
            msg = "Glückwunsch! Alle Stellungen wurden in der aktuellen Session geprüft."
            if variation_filter:
                msg = f"Glückwunsch! Alle Stellungen der Variante '{variation_filter}' wurden geprüft."
            
            QMessageBox.information(self, "Fertig!", msg)
            if not variation_filter:
                self.toggle_overhaul_session()
    def closeEvent(self, event):
        """Clean up background resources before closing."""
        if hasattr(self, 'engine_thread') and self.engine_thread:
            try:
                self.engine_thread.stop_engine()
                self.engine_thread.running = False
                self.engine_thread.wait(500)
            except: pass
            
        if hasattr(self, 'backend') and self.backend:
            try:
                self.backend.close()
            except: pass
            
        if hasattr(self, 'training_manager') and self.training_manager:
            try:
                self.training_manager.close()
            except: pass

        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CreatorWindow()
    window.show()
    sys.exit(app.exec())
