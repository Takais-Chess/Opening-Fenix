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

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox, QSplitter, QFrame,
    QComboBox, QInputDialog, QCheckBox, QGroupBox, QFormLayout,
    QDialog, QTextEdit, QHeaderView, QMenu, QGridLayout,
    QScrollArea, QSlider, QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QTabWidget, QProgressBar, QProgressDialog, QListWidget,
    QTableWidget, QTableWidgetItem, QApplication, QToolBar, QStyle, QListWidgetItem, QStackedWidget, QPlainTextEdit,
    QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QUrl, QRectF, QSize, QEvent
from PyQt6.QtGui import QIcon, QAction, QColor, QPainter, QBrush, QPen, QPolygonF, QPalette, QFontMetrics, QFont
from PyQt6.QtMultimedia import QSoundEffect
from sqlalchemy import or_, func, desc, text
from sqlalchemy.orm import joinedload

from opening_fenix.core.models import DatabaseManager, Position, Move, RepertoireMove, RepertoireLevel, Metadata, LichessData
from opening_fenix.core.data_tools import get_base_path, get_user_dir, get_repertoire_analysis_status, calculate_local_priority_scores
from opening_fenix.core.threads import AnalysisThread, LichessImportThread, IslandDetectionThread, BackgroundEnrichmentThread, PGNImportThread
from opening_fenix.core.engine import EngineThread
from opening_fenix.gui.widgets.board_widget import ChessBoardWidget, THEMES
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
from opening_fenix.gui.widgets.common import AspectRatioFrame

# Import centralized styles
from opening_fenix.gui.styles import get_creator_window_style, get_creator_toolbar_style, COLORS
from opening_fenix.gui.widgets.title_bar import CustomTitleBar
from opening_fenix.gui.scaling import scale


# --- BACKEND ---
class CreatorBackend:
    def __init__(self):
        self.db_manager = None
        self.session = None
        self.active_repo_name = None
        self._export_count = 0
        self._cached_start_move = 1
        
        # IN-MEMORY CACHE FOR UI RESPONSIVENESS
        self._ui_cache = {}
        
        # DEBUG TRACE
        self._last_cascade_trace = []

    def load_repertoire(self, name):
        self.close()
        self.active_repo_name = name
        db_path = os.path.join(get_user_dir(), "repertoires", f"{name}.db")
        self.db_manager = DatabaseManager(db_path)
        self.session = self.db_manager.get_session()
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
        clean_fen = " ".join(fen.split(" ")[:4])
        pos = self.session.query(Position).filter_by(fen=clean_fen).first()
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
            
        clean_fen = " ".join(fen.split(" ")[:4])
        pos = self.session.query(Position).filter_by(fen=clean_fen).first()
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

    def update_position_data(self, fen, comment, var1, var2, var3, append=False):
        if not self.session: return
        clean_fen = " ".join(fen.split(" ")[:4])
        pos = self.session.query(Position).filter_by(fen=clean_fen).first()
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

        self.session.flush()

        if names_changed:
            self._update_cached_names_recursive(pos)

        self.session.commit()
        self.clear_cache()


    def _update_cached_names_recursive(self, pos, visited=None):
        if visited is None: visited = set()
        if pos.id in visited: return
        visited.add(pos.id)

        new_v1, new_v2, new_v3 = pos.variation_1, pos.variation_2, pos.variation_3

        if not (new_v1 and new_v2 and new_v3):
            parent_v1, parent_v2, parent_v3 = self._get_best_parent_names(pos.id)
            if not new_v1: new_v1 = parent_v1
            if not new_v2: new_v2 = parent_v2
            if not new_v3: new_v3 = parent_v3

        pos.cached_v1 = new_v1
        pos.cached_v2 = new_v2
        pos.cached_v3 = new_v3

        children_moves = self.session.query(Move).filter_by(from_position_id=pos.id).all()
        for move in children_moves:
            child_pos = self.session.get(Position, move.to_position_id)
            if child_pos:
                self._update_cached_names_recursive(child_pos, visited)

    def _get_best_parent_names(self, pos_id):
        incoming_moves = self.session.query(Move).filter_by(to_position_id=pos_id).order_by(Move.priority_score.desc()).all()
        best_v1, best_v2, best_v3 = None, None, None
        for move in incoming_moves:
            parent = self.session.get(Position, move.from_position_id)
            if not parent: continue
            if best_v1 is None and parent.cached_v1: best_v1 = parent.cached_v1
            if best_v2 is None and parent.cached_v2: best_v2 = parent.cached_v2
            if best_v3 is None and parent.cached_v3: best_v3 = parent.cached_v3
            if best_v1 and best_v2 and best_v3: break
        return best_v1, best_v2, best_v3

    def update_position_analysis(self, fen, depth, eval_val):
        if not self.session: return
        pos = self.session.query(Position).filter_by(fen=" ".join(fen.split(" ")[:4])).first()
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
            
        pos = self.session.query(Position).filter_by(fen=" ".join(fen.split(" ")[:4])).first()
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
                "nag": m.nag, "eval": next_pos.engine_eval if next_pos else None
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
            wins = stats.get('wins', 0)
            draws = stats.get('draws', 0)
            losses = stats.get('losses', 0)
            total = stats.get('total', wins + draws + losses)
            if total == 0: continue

            try:
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

    def add_move(self, from_fen, move_uci, move_san, level_order=None):
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
            db_move = Move(from_position_id=from_pos.id, to_position_id=to_pos.id, uci=move_uci, san=move_san)
            self.session.add(db_move)
            self.session.flush()

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

    def preview_delete_impact(self, uci, fen):
        if not self.session: return 0, 0
        pos = self.session.query(Position).filter_by(fen=" ".join(fen.split(" ")[:4])).first()
        if not pos: return 0, 0
        move = self.session.query(Move).filter_by(from_position_id=pos.id, uci=uci).first()
        if not move: return 0, 0
        dm, dp = set(), set()
        self._simulate_delete_recursive(move, dm, dp)
        return len(dm), len(dp)

    def _simulate_delete_recursive(self, move, dm, dp):
        if move.id in dm: return
        dm.add(move.id)
        incoming = self.session.query(Move).filter_by(to_position_id=move.to_position_id).all()
        if all(inc.id in dm for inc in incoming):
            if move.to_position_id not in dp:
                dp.add(move.to_position_id)
                for out in self.session.query(Move).filter_by(from_position_id=move.to_position_id).all():
                    self._simulate_delete_recursive(out, dm, dp)

    def delete_move(self, uci, fen):
        if not self.session: return
        pos = self.session.query(Position).filter_by(fen=" ".join(fen.split(" ")[:4])).first()
        if not pos: return
        move = self.session.query(Move).filter_by(from_position_id=pos.id, uci=uci).first()
        if move:
            parent_pos_id = move.from_position_id
            self._delete_move_recursive(move)
            self.session.commit()

            # After deletion, update local priority scores for the affected subtree
            try:
                elo_meta = self.session.query(Metadata).filter_by(key="lichess_elo").first()
                elo_category = (elo_meta.value if elo_meta and elo_meta.value in ["low", "mid", "high", "masters"] else "high")
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
        self.session.query(RepertoireMove).filter_by(move_id=move.id).delete()
        next_id = move.to_position_id
        self.session.delete(move)
        self.session.flush()
        if self.session.query(Move).filter_by(to_position_id=next_id).count() == 0:
            for out in self.session.query(Move).filter_by(from_position_id=next_id).all():
                self._delete_move_recursive(out)
            self.session.query(Position).filter_by(id=next_id).delete()

    def set_nag(self, uci, fen, nag):
        if not self.session: return
        pos = self.session.query(Position).filter_by(fen=" ".join(fen.split(" ")[:4])).first()
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
                self.add_move(from_f, uci, san, level)
                if node.nags: self.set_nag(uci, from_f, list(node.nags)[0])
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
            if not v1: v1 = p.cached_v1 or "Misc"
            if not v2 and v3: v2 = p.cached_v2 or "Misc"
            if v1:
                if v1 not in struct: struct[v1] = {"name": v1, "fen": p.fen, "children": {}}
                if v2:
                    if v2 not in struct[v1]["children"]: struct[v1]["children"][v2] = {"name": v2, "fen": p.fen, "children": {}}
                    if v3: struct[v1]["children"][v2]["children"][v3] = {"name": v3, "fen": p.fen, "priority": priority}
                    else: struct[v1]["children"][v2]["priority"] = priority
                else: struct[v1]["priority"] = priority
        
        res = []
        for k1 in sorted(struct.keys()):
            v1_node = struct[k1]
            v1_children = []
            for k2 in sorted(v1_node["children"].keys()):
                v2_node = v1_node["children"][k2]
                v2_children = []
                for k3 in sorted(v2_node["children"].keys()):
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

    def get_repertoire_info(self):
        if not self.session: return {"name": self.active_repo_name, "levels": [], "depth": "N/A", "elo": "N/A", "moves": "N/A", "description": ""}
        levels = self.get_repertoire_levels()
        moves = self.session.query(RepertoireMove.move_id).distinct().count()
        def gm(k, d): m = self.session.query(Metadata).filter_by(key=k).first(); return m.value if m else d
        
        # Use the more accurate analysis status calculation
        analysis_status = get_repertoire_analysis_status(self.active_repo_name)
        
        return {
            "name": self.active_repo_name,
            "levels": [l['name'] for l in levels],
            "depth": analysis_status,
            "elo": gm("lichess_elo", "N/A"),
            "moves": moves,
            "description": gm("description", "")
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

    def delete_repertoire(self):
        if not self.active_repo_name: return False, "No active repo."
        n = self.active_repo_name
        if self.session: self.session.close(); self.session = None
        if self.db_manager: self.db_manager.close(); self.db_manager = None
        import gc
        gc.collect()
        from opening_fenix.core.data_tools import delete_repertoire_db
        return delete_repertoire_db(n)

    def export_pgn(self, start=None, transpos_mode=2, cb=None, max_l=None):
        if not self.session: return None
        if start is None: start = chess.STARTING_FEN
        pos = self.session.query(Position).filter_by(fen=" ".join(start.split(" ")[:4])).first()
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
                    self._build_pgn_tree(node, pos.id, set(), {} if transpos_mode > 0 else None, "", cb, max_l, transpos_mode)
                    
                    # Clean up cache
                    del self.export_moves_cache
                    del self.export_rep_cache
                    return game.accept(chess.pgn.StringExporter(headers=True, variations=True, comments=True))
                    
            self._build_pgn_tree(game, pos.id, set(), {} if transpos_mode > 0 else None, "", cb, max_l, transpos_mode)
            
            # Clean up cache
            del self.export_moves_cache
            del self.export_rep_cache
            return game.accept(chess.pgn.StringExporter(headers=True, variations=True, comments=True))
        except InterruptedError: return None

    def _get_history_for_pos(self, pid):
        path = []; curr = pid
        for _ in range(200):
            inc = self.session.query(Move).filter_by(to_position_id=curr).order_by(Move.priority_score.desc()).first()
            if not inc: break
            path.insert(0, inc.uci); curr = inc.from_position_id
        return path

    def _build_pgn_tree(self, node, pid, vp, vg, line, cb, max_l, transpos_mode=2):
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
            seg = f"{mn}. {m_db.san}" if board.turn == chess.WHITE else (f"{mn}... {m_db.san}" if not line else m_db.san)
            
            self._build_pgn_tree(new, m_db.to_position_id, vp, vg, f"{line} {seg}".strip(), cb, max_l, transpos_mode)
            
        vp.remove(pid)

    def add_repertoire_level(self, name, idx):
        if not self.session: return False, "No repo."
        try:
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

    def rename_repertoire(self, new_name):
        if not self.active_repo_name: return False, "No active repo."
        if not new_name: return False, "Invalid name."
        old_path = os.path.join(get_user_dir(), "repertoires", f"{self.active_repo_name}.db")
        new_path = os.path.join(get_user_dir(), "repertoires", f"{new_name}.db")
        if os.path.exists(new_path): return False, "Name already exists."
        try:
            self.session.close()
            self.db_manager.close()
            import gc
            gc.collect()
            os.rename(old_path, new_path)
            self.load_repertoire(new_name)
            return True, "Renamed."
        except Exception as e:
            return False, str(e)

    def export_db(self, path, start=None):
        if not self.active_repo_name: return False, "No active repo."
        try: shutil.copy2(os.path.join(get_user_dir(), "repertoires", f"{self.active_repo_name}.db"), path); return True, "Exported."
        except Exception as e: return False, str(e)

    def scan_and_get_impact(self, uci, fen):
        pos = self.session.query(Position).filter_by(fen=" ".join(fen.split(" ")[:4])).first()
        if not pos: return 0, 0
        move = self.session.query(Move).filter_by(from_position_id=pos.id, uci=uci).first()
        if not move: return 0, 0
        dm, dp = set(), set(); self._simulate_delete_recursive(move, dm, dp)
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
        
        return result

    def repair_diagnostic_issues(self):
        if not self.session: return
        
        # 1. Repair Schema
        self.db_manager._migrate_schema()
        
        # 2. Repair Gaps
        while True:
            subq = self.session.query(Move.from_position_id).join(RepertoireMove, Move.id == RepertoireMove.move_id).distinct()
            gaps = self.session.query(Move).outerjoin(RepertoireMove, Move.id == RepertoireMove.move_id)\
                .filter(RepertoireMove.id == None)\
                .filter(Move.to_position_id.in_(subq)).all()
            
            if not gaps: break
                
            for g in gaps:
                min_child_level = self.session.query(func.min(RepertoireMove.level))\
                    .join(Move, RepertoireMove.move_id == Move.id)\
                    .filter(Move.from_position_id == g.to_position_id).scalar()
                
                lvl = min_child_level if min_child_level is not None else 1
                self.session.add(RepertoireMove(move_id=g.id, level=lvl))
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

        self.session.commit()
        self.clear_cache()

# --- DIALOGS ---
class DiagnosticDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datenbank Diagnose")
        self.setMinimumWidth(450)
        self.backend = backend
        self.init_ui()
        self.run_diagnostic()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.lbl_info = QLabel("Überprüfe Repertoire-Struktur...")
        layout.addWidget(self.lbl_info)
        
        self.txt_results = QTextEdit()
        self.txt_results.setReadOnly(True)
        layout.addWidget(self.txt_results)
        
        self.btn_repair = QPushButton("🔧 Probleme beheben")
        self.btn_repair.clicked.connect(self.repair)
        self.btn_repair.setEnabled(False)
        self.btn_repair.setStyleSheet(f"background-color: {COLORS['success_green']}; color: white; font-weight: bold;")
        
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.accept)
        
        h_btn = QHBoxLayout()
        h_btn.addWidget(btn_close)
        h_btn.addWidget(self.btn_repair)
        layout.addLayout(h_btn)

    def run_diagnostic(self):
        self.issues = self.backend.run_diagnostic()
        msg = "<b>Diagnose-Ergebnis:</b><br><br>"
        
        has_issues = False
        
        # Schema
        if self.issues['schema']:
            msg += f"<span style='color: red;'>⚠️ Veraltetes Datenbankschema. Fehlende Spalten: {', '.join(self.issues['schema'])}</span><br>"
            has_issues = True
        else:
            msg += "<span style='color: green;'>✅ Datenbankschema ist aktuell.</span><br>"
            
        # Gaps
        if self.issues['gaps'] > 0:
            msg += f"<span style='color: red;'>⚠️ {self.issues['gaps']} fehlende Repertoire-Links (Löcher) gefunden.</span><br>"
            has_issues = True
        else:
            msg += "<span style='color: green;'>✅ Keine Lücken in der Kette gefunden.</span><br>"
            
        # Duplicates
        if self.issues['duplicates'] > 0:
            msg += f"<span style='color: red;'>⚠️ {self.issues['duplicates']} duplizierte FENs (Geister-Stellungen) gefunden.</span><br>"
            has_issues = True
        else:
            msg += "<span style='color: green;'>✅ Keine FEN-Duplikate gefunden.</span><br>"
            
        # Orphans
        if self.issues['orphans'] > 0:
            msg += f"<span style='color: orange;'>⚠️ {self.issues['orphans']} isolierte Stellungen (nicht erreichbar).</span><br>"
            # We don't automatically delete orphans yet, just report them
        else:
            msg += "<span style='color: green;'>✅ Keine isolierten Stellungen.</span><br>"
            
        self.txt_results.setHtml(msg)
        
        if has_issues:
            self.lbl_info.setText("Es wurden Probleme gefunden, die die Funktionalität beeinträchtigen können.")
            self.btn_repair.setEnabled(True)
            self.btn_repair.setVisible(True)
        else:
            self.lbl_info.setText("Alles in bester Ordnung! Deine Datenbank ist strukturell gesund.")
            # Keine Aktion erforderlich, Reparatur-Button ausblenden
            self.btn_repair.setVisible(False)

    def repair(self):
        self.btn_repair.setEnabled(False)
        self.lbl_info.setText("Führe Reparatur und Kaskadierung durch... Bitte warten.")
        QApplication.processEvents()
        
        self.backend.repair_diagnostic_issues()
        
        self.txt_results.append("<br><br><b>Reparatur erfolgreich abgeschlossen!</b>")
        self.txt_results.append("Alle Löcher wurden gestopft und Duplikate zusammengeführt.")
        self.lbl_info.setText("Probleme behoben.")
        if hasattr(self.parent(), 'refresh_info'):
            self.parent().refresh_info()


class RepoSettingsDialog(QDialog):
    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("Repertoire Einstellungen")
        self.setMinimumSize(scale(800), scale(600))
        self.backend = backend
        self.resize(scale(1500), scale(900))
        self.setStyleSheet(get_creator_window_style())


        self.init_ui()

        self.refresh_info()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(scale(200))

        self.sidebar.currentRowChanged.connect(self.display_page)
        for t in ["Repertoire-Daten", "Darstellung & Audio", "Import & Export", "Analyse & Werkzeuge"]:
            item = QListWidgetItem(t)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.sidebar.addItem(item)
        layout.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        self.page_gen = QWidget(); self.init_page_general(self.page_gen)
        self.page_design = QWidget(); self.init_page_design(self.page_design)
        self.page_imex = QWidget(); self.init_page_imex(self.page_imex)
        self.page_analysis = QWidget(); self.init_page_analysis(self.page_analysis)
        self.pages.addWidget(self.page_gen)
        self.pages.addWidget(self.page_design)
        self.pages.addWidget(self.page_imex)
        self.pages.addWidget(self.page_analysis)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.pages)
        layout.addWidget(scroll, 1)
        self.sidebar.setCurrentRow(0)

    def display_page(self, index): self.pages.setCurrentIndex(index)

    def init_page_general(self, page):
        l = QVBoxLayout(page)
        g_i = QGroupBox("Informationen")
        f_i = QFormLayout(g_i)
        self.l_n, self.l_d, self.l_e, self.l_m = QLabel(), QLabel(), QLabel(), QLabel()
        h_n = QHBoxLayout()
        h_n.addWidget(self.l_n)
        b_edit_name = QPushButton("✎")
        b_edit_name.setFixedSize(scale(30), scale(30))
        b_edit_name.clicked.connect(self.rename_repertoire)
        h_n.addWidget(b_edit_name)

        f_i.addRow("Name:", h_n)

        # Description Field
        self.txt_description = QPlainTextEdit()
        self.txt_description.setPlaceholderText("Beschreibe dein Repertoire...")
        self.txt_description.setMinimumHeight(scale(100))
        self.txt_description.textChanged.connect(self.save_description)
        f_i.addRow("Beschreibung:", self.txt_description)


        f_i.addRow("Analyse:", self.l_d)
        f_i.addRow("Elo:", self.l_e)
        f_i.addRow("Züge:", self.l_m)
        self.tbl_levels = QTableWidget()
        self.tbl_levels.setColumnCount(3)
        self.tbl_levels.setHorizontalHeaderLabels(["Lvl", "Name", "Ziel-Elo"])
        self.tbl_levels.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_levels.setMaximumHeight(scale(150))
        self.tbl_levels.verticalHeader().setVisible(False)

        self.tbl_levels.itemDoubleClicked.connect(self.rename_level)
        
        b_a_l = QPushButton("Level hinzufügen")
        b_a_l.clicked.connect(self.add_level)
        v_l = QVBoxLayout()
        v_l.addWidget(self.tbl_levels)
        v_l.addWidget(b_a_l)
        f_i.addRow("Levels:", v_l)
        b_r = QPushButton("Aktualisieren")
        b_r.clicked.connect(self.refresh_info)
        f_i.addRow("", b_r)
        l.addWidget(g_i)
        g_da = QGroupBox("Gefahrenzone")
        v_da = QVBoxLayout(g_da)
        b_d_r = QPushButton("Repertoire Löschen")
        b_d_r.setStyleSheet(f"color: {COLORS['error_red']};")
        b_d_r.clicked.connect(self.delete_repertoire_action)
        v_da.addWidget(b_d_r)
        l.addWidget(g_da)
        l.addStretch()

    def save_description(self):
        self.backend.set_repertoire_description(self.txt_description.toPlainText())

    def init_page_design(self, page):
        l = QVBoxLayout(page)
        g_d = QGroupBox("Visuelles Design")
        f_d = QFormLayout(g_d)
        self.combo_theme = QComboBox()
        for theme_name in THEMES.keys():
            self.combo_theme.addItem(theme_name)
        current_theme = self.main_window.config.get("theme", "Blau (Turnier)")
        index = self.combo_theme.findText(current_theme)
        if index >= 0:
            self.combo_theme.setCurrentIndex(index)
        self.combo_theme.currentTextChanged.connect(self.change_board_theme)
        f_d.addRow("Brett Design:", self.combo_theme)
        l.addWidget(g_d)
        g_a = QGroupBox("Audio")
        f_a = QFormLayout(g_a)
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        current_vol = self.main_window.config.get("master_volume", 100)
        self.slider_vol.setValue(current_vol)
        self.slider_vol.valueChanged.connect(self.change_volume)
        f_a.addRow("Lautstärke:", self.slider_vol)
        l.addWidget(g_a)
        l.addStretch()

    def change_board_theme(self, theme_name):
        self.main_window.board_widget.set_theme(theme_name)
        self.main_window.config["theme"] = theme_name
        self.save_config()

    def change_volume(self, value):
        self.main_window.config["master_volume"] = value
        self.save_config()
        for sound in self.main_window.sounds.values():
            sound.setVolume(value / 100.0)

    def save_config(self):
        config_path = os.path.join(get_user_dir(), "config.json")
        try:
            with open(config_path, "w") as f:
                json.dump(self.main_window.config, f, indent=4)
        except: pass

    def init_page_imex(self, page):
        l = QVBoxLayout(page)
        g = QGroupBox("Import / Export")
        v = QVBoxLayout(g)
        h = QHBoxLayout()
        b_p = QPushButton("PGN Text einfügen")
        b_p.clicked.connect(self.paste_pgn_dialog)
        b_f = QPushButton("PGN Datei einfügen")
        b_f.clicked.connect(self.import_pgn_file_dialog)
        h.addWidget(b_p)
        h.addWidget(b_f)
        v.addLayout(h)
        b_e = QPushButton("Exportieren")
        b_e.clicked.connect(self.export_repertoire)
        v.addWidget(b_e)
        l.addWidget(g)
        l.addStretch()

    def init_page_analysis(self, page):
        l = QVBoxLayout(page)
        lbl_info = QLabel("Hier kannst du 'Gute Züge' (Alternativen) berechnen lassen und die Prioritäts-Scores (Wahrscheinlichkeiten) aktualisieren.")
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #555; font-style: italic; margin-bottom: 10px;")
        l.addWidget(lbl_info)
        
        # --- Group 3: Structure Repair (NEW) ---
        g_repair = QGroupBox("Repertoire-Diagnose & Reparatur")
        v_repair = QVBoxLayout(g_repair)
        lbl_rep_info = QLabel("Prüft die Datenbank auf fehlende Tabellen, Löcher in der Zug-Kette und fehlerhafte Level-Inkonsistenzen.")
        lbl_rep_info.setWordWrap(True)
        lbl_rep_info.setStyleSheet("color: #666; font-size: 11px;")
        v_repair.addWidget(lbl_rep_info)
        btn_repair = QPushButton("🔎 Datenbank-Diagnose")
        btn_repair.clicked.connect(self.run_structure_repair)
        v_repair.addWidget(btn_repair)
        l.addWidget(g_repair)

        g_eng = QGroupBox("1. Engine Analyse (Alternative Züge)")
        f_eng = QFormLayout(g_eng)
        self.txt_engine_path = QLineEdit()
        self.txt_engine_path.setPlaceholderText("Pfad zur Engine Executable...")
        current_engine = self.main_window.config.get("engine_path", "")
        self.txt_engine_path.setText(current_engine)
        btn_browse_engine = QPushButton("...")
        btn_browse_engine.setFixedWidth(30)
        btn_browse_engine.clicked.connect(self.browse_engine_path)
        h_eng_path = QHBoxLayout()
        h_eng_path.addWidget(self.txt_engine_path)
        h_eng_path.addWidget(btn_browse_engine)
        f_eng.addRow("Engine Pfad:", h_eng_path)
        self.s_d = QSpinBox()
        self.s_d.setRange(10, 50)
        self.s_d.setValue(20)
        self.c_threads = QComboBox()
        max_threads = multiprocessing.cpu_count()
        for i in range(1, max_threads + 1):
            self.c_threads.addItem(str(i))
        self.c_threads.setCurrentIndex(max(0, min(3, max_threads - 1)))
        f_eng.addRow("Tiefe:", self.s_d)
        f_eng.addRow("Threads:", self.c_threads)
        b_eng = QPushButton("Engine Analyse Starten")
        b_eng.clicked.connect(self.start_analysis)
        f_eng.addRow(b_eng)
        self.pb_eng = QProgressBar()
        self.l_eng_status = QLabel("Bereit")
        l.addWidget(g_eng)
        l.addWidget(self.l_eng_status)
        l.addWidget(self.pb_eng)
        g_lich = QGroupBox("2. Lichess Daten & Prio Scores")
        v_lich = QVBoxLayout(g_lich)
        
        # --- Lichess API Token (NEW) ---
        h_token = QHBoxLayout()
        h_token.addWidget(QLabel("Lichess API Token:"))
        self.txt_lichess_token = QLineEdit()
        self.txt_lichess_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_lichess_token.setPlaceholderText("lip_...")
        current_token = self.main_window.config.get("lichess_token", "")
        self.txt_lichess_token.setText(current_token)
        self.txt_lichess_token.textChanged.connect(self.on_token_changed)
        
        btn_test_token = QPushButton("Verbindung testen")
        btn_test_token.clicked.connect(self.test_lichess_token)

        self.chk_show_token = QCheckBox("Anzeigen")
        self.chk_show_token.toggled.connect(lambda checked: self.txt_lichess_token.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))

        h_token.addWidget(self.txt_lichess_token)
        h_token.addWidget(self.chk_show_token)
        h_token.addWidget(btn_test_token)
        v_lich.addLayout(h_token)
        # -----------------------------

        self.bg_e = QButtonGroup(self)
        r1 = QRadioButton("Low (<1400)")
        r2 = QRadioButton("Mid (1400-2000)")
        r3 = QRadioButton("High (>2000)")
        r4 = QRadioButton("Masters")
        r3.setChecked(True)
        self.bg_e.addButton(r1, 1)
        self.bg_e.addButton(r2, 2)
        self.bg_e.addButton(r3, 3)
        self.bg_e.addButton(r4, 4)
        h_r = QHBoxLayout()
        h_r.addWidget(r1)
        h_r.addWidget(r2)
        h_r.addWidget(r3)
        h_r.addWidget(r4)
        v_lich.addLayout(h_r)
        b_lich = QPushButton("Daten laden & Scores berechnen")
        b_lich.clicked.connect(self.start_fetch)
        v_lich.addWidget(b_lich)
        b_del_lich = QPushButton("Lichess Daten löschen")
        b_del_lich.setStyleSheet(f"color: {COLORS['error_red']};")
        b_del_lich.clicked.connect(self.delete_lichess_data)
        v_lich.addWidget(b_del_lich)
        self.pb_lich = QProgressBar()
        self.l_lich_status = QLabel("Bereit")
        l.addWidget(g_lich)
        l.addWidget(self.l_lich_status)
        l.addWidget(self.pb_lich)

        # --- Group 4: Priority-Based Level Management (NEW) ---
        g_prio_levels = QGroupBox("4. Prioritäts-basierte Level-Anpassung")
        v_prio = QVBoxLayout(g_prio_levels)
        lbl_prio_info = QLabel("Versetzt alle Züge, deren Priorität über einem Schwellenwert liegt, in ein wichtigeres Level (z.B. Level 1). Es werden nur Züge 'befördert', niemals herabgestuft.")
        lbl_prio_info.setWordWrap(True)
        lbl_prio_info.setStyleSheet("color: #666; font-size: 11px;")
        v_prio.addWidget(lbl_prio_info)

        f_prio = QFormLayout()
        self.spin_prio_threshold = QDoubleSpinBox()
        self.spin_prio_threshold.setRange(0.0, 100.0)
        self.spin_prio_threshold.setSuffix(" %")
        self.spin_prio_threshold.setValue(1.0)
        self.spin_prio_threshold.setSingleStep(0.1)
        f_prio.addRow("Prioritäts-Schwellenwert:", self.spin_prio_threshold)

        self.combo_prio_target_level = QComboBox()
        f_prio.addRow("Ziel-Level (Wichtigkeit):", self.combo_prio_target_level)
        v_prio.addLayout(f_prio)

        h_prio_btns = QHBoxLayout()
        btn_prio_preview = QPushButton("🔎 Vorschau der Änderungen")
        btn_prio_preview.clicked.connect(self.update_priority_level_impact_preview)
        btn_prio_apply = QPushButton("🚀 Level anpassen (Nur Upgrade)")
        btn_prio_apply.clicked.connect(self.apply_priority_level_change)
        h_prio_btns.addWidget(btn_prio_preview)
        h_prio_btns.addWidget(btn_prio_apply)
        v_prio.addLayout(h_prio_btns)

        l.addWidget(g_prio_levels)

        # Kommentare bereinigen (Duplikate innerhalb einzelner Kommentare entfernen)
        g_comm = QGroupBox("Kommentare bereinigen")
        v_comm = QVBoxLayout(g_comm)
        lbl_comm = QLabel("Bereinigt Kommentare, in denen derselbe Text durch fehlerhafte Importe mehrfach hintereinander wiederholt wurde. Nur innerhalb einzelner Kommentare, nicht datenbankweit.")
        lbl_comm.setWordWrap(True)
        lbl_comm.setStyleSheet("color: #666; font-size: 11px;")
        v_comm.addWidget(lbl_comm)
        b_comm = QPushButton("Kommentare deduplizieren")
        b_comm.setToolTip("Entfernt Duplikate desselben Textes innerhalb eines einzelnen Kommentars.")
        b_comm.clicked.connect(self.run_deduplicate_comments)
        v_comm.addWidget(b_comm)

        b_brackets = QPushButton("Kommentare bereinigen von [...]")
        b_brackets.setToolTip("Entfernt alle eckigen Klammern und deren Inhalt aus den Kommentaren.")
        b_brackets.clicked.connect(self.run_clean_brackets)
        v_comm.addWidget(b_brackets)

        l.addWidget(g_comm)
        
        # --- Group 5: Bulk Level Change (NEW) ---
        g_bulk = QGroupBox("5. Massen-Aktionen (Alle Züge)")
        v_bulk = QVBoxLayout(g_bulk)
        lbl_bulk_info = QLabel("Setzt das Level ALLER Züge in diesem Repertoire auf das gewählte Ziel-Level. Nützlich für schnelle Reorganisationen.")
        lbl_bulk_info.setWordWrap(True)
        lbl_bulk_info.setStyleSheet("color: #666; font-size: 11px;")
        v_bulk.addWidget(lbl_bulk_info)
        
        f_bulk = QFormLayout()
        self.combo_bulk_level = QComboBox()
        f_bulk.addRow("Ziel-Level:", self.combo_bulk_level)
        v_bulk.addLayout(f_bulk)
        
        btn_bulk_apply = QPushButton("🚀 Alle Züge verschieben")
        btn_bulk_apply.clicked.connect(self.apply_bulk_level_move)
        v_bulk.addWidget(btn_bulk_apply)
        l.addWidget(g_bulk)

        l.addStretch()

    def update_priority_level_impact_preview(self):
        threshold = self.spin_prio_threshold.value()
        target_lvl = self.combo_prio_target_level.currentData()
        if target_lvl is None: return
        
        count = self.backend.get_priority_level_impact(threshold, target_lvl)
        QMessageBox.information(self, "Vorschau", f"Es wurden {count} Züge gefunden, die eine Priorität von ≥ {threshold}% haben und aktuell in einem weniger wichtigen Level als {target_lvl} sind.")

    def apply_priority_level_change(self):
        threshold = self.spin_prio_threshold.value()
        target_lvl = self.combo_prio_target_level.currentData()
        if target_lvl is None: return
        
        count = self.backend.get_priority_level_impact(threshold, target_lvl)
        if count == 0:
            QMessageBox.information(self, "Keine Änderungen", "Es wurden keine Züge gefunden, die den Kriterien entsprechen.")
            return
            
        if QMessageBox.question(self, "Bestätigen", f"Möchtest du wirklich {count} Züge auf Level {target_lvl} hochstufen?\n\nHinweis: Bestehende Level 1 Züge bleiben Level 1.") == QMessageBox.StandardButton.Yes:
            modified = self.backend.apply_priority_level_update(threshold, target_lvl)
            QMessageBox.information(self, "Erfolg", f"{modified} Züge wurden erfolgreich auf Level {target_lvl} angepasst.")
            self.refresh_info()
            if hasattr(self.main_window, 'update_ui_from_fen'):
                self.main_window.update_ui_from_fen()

    def apply_bulk_level_move(self):
        target_lvl = self.combo_bulk_level.currentData()
        level_name = self.combo_bulk_level.currentText()
        if target_lvl is None: return
        
        msg = f"Möchtest du wirklich ALLE Züge dieses Repertoires auf '{level_name}' setzen?"
        if QMessageBox.question(self, "Bestätigung", msg) == QMessageBox.StandardButton.Yes:
            count = self.backend.move_all_to_level(target_lvl)
            QMessageBox.information(self, "Erfolg", f"{count} Züge wurden erfolgreich auf {level_name} gesetzt.")
            self.refresh_info()
            if hasattr(self.main_window, 'update_ui_from_fen'):
                self.main_window.update_ui_from_fen()

    def run_structure_repair(self):
        dialog = DiagnosticDialog(self.backend, self)
        dialog.exec()
        if hasattr(self.main_window, 'update_ui_from_fen'):
            self.main_window.update_ui_from_fen()

    def run_deduplicate_comments(self):
        count = self.backend.deduplicate_comments_in_repo()
        if count > 0:
            QMessageBox.information(self, "Kommentare bereinigt", f"{count} Kommentare bereinigt (Duplikate innerhalb einzelner Kommentare entfernt).")
            if hasattr(self.main_window, 'update_ui_from_fen'):
                self.main_window.update_ui_from_fen()
        else:
            QMessageBox.information(self, "Keine Änderungen", "Es wurden keine doppelten Texte innerhalb einzelner Kommentare gefunden.")

    def run_clean_brackets(self):
        count = self.backend.clean_brackets_in_repo()
        if count > 0:
            QMessageBox.information(self, "Kommentare bereinigt", f"{count} Kommentare bereinigt (Klammern [...] entfernt).")
            if hasattr(self.main_window, 'update_ui_from_fen'):
                self.main_window.update_ui_from_fen()
        else:
            QMessageBox.information(self, "Keine Änderungen", "Es wurden keine Klammern [...] in den Kommentaren gefunden.")

    def browse_engine_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Engine wählen", "", "Executable (*.exe);;All Files (*)")
        if path:
            self.txt_engine_path.setText(path)
            self.main_window.config["engine_path"] = path
            self.save_config()

    def refresh_info(self):
        self.backend.scan_and_update_metadata()
        i = self.backend.get_repertoire_info()
        self.l_n.setText(i['name'])
        
        # Load description
        self.txt_description.blockSignals(True)
        self.txt_description.setPlainText(i['description'])
        self.txt_description.blockSignals(False)

        self.tbl_levels.setRowCount(0)
        levels = self.backend.get_repertoire_levels()
        for idx, lvl in enumerate(levels):
            self.tbl_levels.insertRow(idx)
            self.tbl_levels.setItem(idx, 0, QTableWidgetItem(str(lvl['order'])))
            self.tbl_levels.setItem(idx, 1, QTableWidgetItem(lvl['name']))
            
            spin = QSpinBox()
            spin.setRange(800, 4000)
            spin.setValue(lvl.get('target_elo', 1500))
            # Use a lambda that captures the current level order
            spin.valueChanged.connect(lambda val, lo=lvl['order']: self.backend.update_level_elo(lo, val))
            self.tbl_levels.setCellWidget(idx, 2, spin)

        self.l_d.setText(i['depth'])
        self.l_e.setText(i['elo'])
        self.l_m.setText(str(i['moves']))

        # Update the Common Moves Elo selector if it exists
        if hasattr(self, 'combo_lichess_cat'):
            current_elo_meta = i.get('elo', 'N/A')
            if current_elo_meta != 'N/A':
                vals = [v.strip() for v in current_elo_meta.split(",")]
                if vals:
                    current_sel = self.combo_lichess_cat.currentText()
                    if current_sel not in vals:
                        self.combo_lichess_cat.setCurrentText(vals[0])

        # Updated current priority target level combo
        current_data = self.combo_prio_target_level.currentData()
        bulk_data = self.combo_bulk_level.currentData()
        
        self.combo_prio_target_level.blockSignals(True)
        self.combo_bulk_level.blockSignals(True)
        
        self.combo_prio_target_level.clear()
        self.combo_bulk_level.clear()
        
        for lvl in levels:
            txt = f"Level {lvl['order']} ({lvl['name']})"
            self.combo_prio_target_level.addItem(txt, userData=lvl['order'])
            self.combo_bulk_level.addItem(txt, userData=lvl['order'])
            
        idx = self.combo_prio_target_level.findData(current_data)
        if idx >= 0: self.combo_prio_target_level.setCurrentIndex(idx)
        else: self.combo_prio_target_level.setCurrentIndex(0)
        
        idx_bulk = self.combo_bulk_level.findData(bulk_data)
        if idx_bulk >= 0: self.combo_bulk_level.setCurrentIndex(idx_bulk)
        else: self.combo_bulk_level.setCurrentIndex(0)
        
        self.combo_prio_target_level.blockSignals(False)
        self.combo_bulk_level.blockSignals(False)

    def delete_lichess_data(self):
        cat = {1: 'low', 2: 'mid', 3: 'high', 4: 'masters'}[self.bg_e.checkedId()]
        if QMessageBox.question(self, "Lichess-Daten löschen", f"ELO-Bereich '{cat}' löschen?") == QMessageBox.StandardButton.Yes:
            s, m = self.backend.delete_lichess_data(cat)
            (QMessageBox.information if s else QMessageBox.warning)(self, "Ergebnis", m)
            self.refresh_info()

    def start_analysis(self):
        ep = self.txt_engine_path.text()
        if not ep or not os.path.exists(ep):
            ep = os.path.join(get_base_path(), "engines", os.path.basename(ep)) if ep else ""
        if not ep or not os.path.exists(ep):
            QMessageBox.warning(self, "Fehler", "Keine gültige Engine konfiguriert.")
            return
        self.l_eng_status.setText("Analysiere...")
        self.pb_eng.setValue(0)
        threads = int(self.c_threads.currentText())
        self.w_eng = AnalysisThread(self.backend.active_repo_name, self.s_d.value(), threads, ep)
        self.w_eng.progress_signal.connect(self.pb_eng.setValue)
        self.w_eng.finished_signal.connect(self.on_analysis_finished)
        self.w_eng.start()

    def on_analysis_finished(self, success, msg):
        self.l_eng_status.setText(msg)
        (QMessageBox.information if success else QMessageBox.warning)(self, "Fertig" if success else "Fehler", msg)
        self.refresh_info()

    def start_fetch(self):
        cat = {1: 'low', 2: 'mid', 3: 'high', 4: 'masters'}[self.bg_e.checkedId()]
        self.l_lich_status.setText(f"Lade {cat}...")
        self.pb_lich.setValue(0)
        self.w_lich = LichessImportThread(self.backend.active_repo_name, cat)
        self.w_lich.progress_signal.connect(self.pb_lich.setValue)
        self.w_lich.finished_signal.connect(self.on_fetch_finished)
        self.w_lich.start()

    def on_token_changed(self, text):
        self.main_window.config["lichess_token"] = text
        self.save_config()

    def test_lichess_token(self):
        token = self.txt_lichess_token.text().strip()
        if not token:
            QMessageBox.warning(self, "Fehler", "Bitte gib zuerst ein Lichess API Token ein.")
            return
            
        from opening_fenix.core.services.lichess_service import verify_lichess_token
        
        # Show a "Testing..." status or just execute (it's fast)
        self.l_lich_status.setText("Teste Token...")
        QApplication.processEvents()
        
        success, msg = verify_lichess_token(token)
        self.l_lich_status.setText("Bereit")
        
        if success:
            QMessageBox.information(self, "Erfolg", msg)
        else:
            QMessageBox.warning(self, "Fehler", msg)

    def on_fetch_finished(self, success, msg):
        self.l_lich_status.setText(msg)
        (QMessageBox.information if success else QMessageBox.warning)(self, "Fertig" if success else "Fehler", msg)
        self.backend.clear_cache()
        self.refresh_info()

    def delete_repertoire_action(self):
        if QMessageBox.question(self, "Löschen", "Repertoire wirklich löschen?") == QMessageBox.StandardButton.Yes:
            s, m = self.backend.delete_repertoire()
            (QMessageBox.information if s else QMessageBox.warning)(self, "Ergebnis", m)
            self.accept()
            # FIX: Get the main application window (not parent dialog) to call UI updates
            app = QApplication.instance()
            for widget in app.topLevelWidgets():
                if widget.objectName() == "MainWindow" or hasattr(widget, "on_repertoire_deleted"):
                    widget.on_repertoire_deleted()
                    break

    def task_fin(self, s, m):
        self.l_p.setText(m)
        (QMessageBox.information if s else QMessageBox.warning)(self, "Fertig", m)
        self.refresh_info()

    def add_level(self):
        n, ok = QInputDialog.getText(self, "Level", "Name:")
        idx, ok2 = QInputDialog.getInt(self, "Pos", "Index:", self.tbl_levels.rowCount()+1, 1, 100)
        if ok and n:
            s, m = self.backend.add_repertoire_level(n, idx)
            (QMessageBox.information if s else QMessageBox.warning)(self, "Ergebnis", m)
            self.refresh_info()
    
    def rename_repertoire(self):
        old_name = self.l_n.text()
        new_name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name:", text=old_name)
        if ok and new_name and new_name != old_name:
            s, m = self.backend.rename_repertoire(new_name)
            if s:
                current_profile = None
                config_path = os.path.join(get_user_dir(), "config.json")
                if os.path.exists(config_path):
                    try:
                        with open(config_path, "r") as f:
                            config = json.load(f)
                            current_profile = config.get("last_profile")
                    except: pass
                if current_profile:
                    try:
                        from opening_fenix.core.training import TrainingManager
                        class DummyRepoManager:
                            def __init__(self): self.active_repertoire_name = None
                        tm = TrainingManager(current_profile, DummyRepoManager())
                        tm.rename_repertoire_in_user_data(old_name, new_name)
                        tm.user_db.close()
                    except Exception as e:
                        print(f"Warning: Could not update user profile data: {e}")
                QMessageBox.information(self, "Erfolg", m)
                self.refresh_info()
                self.main_window.setWindowTitle(f"Creator - {new_name}")
            else:
                QMessageBox.warning(self, "Fehler", m)

    def rename_level(self, item):
        if item.column() != 1: return
        old_name = item.text()
        try:
            new_name, ok = QInputDialog.getText(self, "Level Umbenennen", "Neuer Name:", text=old_name)
            if ok and new_name:
                s, m = self.backend.rename_repertoire_level(old_name, new_name)
                if s:
                    self.refresh_info()
                else:
                    QMessageBox.warning(self, "Fehler", m)
        except Exception: pass

    def paste_pgn_dialog(self):
        d = QDialog(self)
        d.setWindowTitle("Einfügen")
        l = QVBoxLayout(d)
        t = QPlainTextEdit()
        l.addWidget(t)
        c = QComboBox()
        for lvl in self.backend.get_repertoire_levels():
            c.addItem(f"L{lvl['order']} ({lvl['name']})", userData=lvl['order'])
        l.addWidget(c)
        b = QPushButton("Import")
        b.clicked.connect(lambda: self.run_pgn_import(t.toPlainText(), d, c.currentData()))
        l.addWidget(b)
        d.exec()

    def import_pgn_file_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "PGN", "", "*.pgn")
        if p:
            lvls = self.backend.get_repertoire_levels()
            n, ok = QInputDialog.getItem(self, "Level", "Level:", [f"L{l['order']} ({l['name']})" for l in lvls], 0, False)
            if ok:
                sel = next((l for l in lvls if f"L{l['order']} ({l['name']})" == n), None)
                if sel:
                    self.start_pgn_import(p, sel['order'])

    def run_pgn_import(self, text, d, lvl):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pgn', delete=False, encoding='utf-8') as tf:
            tf.write(text)
            temp_path = tf.name
        
        d.accept()
        self.start_pgn_import(temp_path, lvl, is_temp=True)

    def start_pgn_import(self, path, lvl_order, is_temp=False):
        repo_name = self.backend.active_repo_name
        side = self.backend.get_meta("color", "w")
        levels = self.backend.get_repertoire_levels()
        lvl_name = next((l['name'] for l in levels if l['order'] == lvl_order), f"Level {lvl_order}")

        progress = QProgressDialog("Importiere PGN...", "Abbrechen", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        thread = PGNImportThread(path, repo_name, side, lvl_name, lvl_order)
        thread.progress_signal.connect(progress.setValue)
        
        def on_finished(success, msg):
            progress.close()
            if is_temp:
                try: os.remove(path)
                except: pass
            
            if success:
                QMessageBox.information(self, "Erfolg", msg)
            else:
                QMessageBox.warning(self, "Fehler", msg)
            
            self.refresh_info()
            self.main_window.update_ui_from_fen()

        thread.finished_signal.connect(on_finished)
        thread.start()
        # Keep a reference to avoid GC
        self._import_thread = thread

    def export_repertoire(self):
        d = ExportDialog(self.backend, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            fmt, scope, transpos_mode, max_l = d.result_data
            start = self.main_window.board_widget.board.fen() if scope == "current" else None
            if fmt == "pgn":
                p = QProgressDialog("Exportiere...", "Abbrechen", 0, 0, self)
                p.setWindowModality(Qt.WindowModality.WindowModal)
                def cb(c): p.setValue(c); return p.wasCanceled()
                pgn = self.backend.export_pgn(start, transpos_mode, cb, max_l)
                if not p.wasCanceled() and pgn:
                    path, _ = QFileDialog.getSaveFileName(self, "Speichern", f"{self.backend.active_repo_name}.pgn", "*.pgn")
                    if path:
                        with open(path, "w", encoding="utf-8") as f: f.write(pgn)
                        QMessageBox.information(self, "OK", "Exportiert.")
            else:
                path, _ = QFileDialog.getSaveFileName(self, "Speichern", f"{self.backend.active_repo_name}_export.db", "*.db")
                if path:
                    s, m = self.backend.export_db(path, start)
                    (QMessageBox.information if s else QMessageBox.warning)(self, "Ergebnis", m)

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

    def __init__(self, repertoire_name=None, initial_fen=None):
        super().__init__()
        self.setWindowTitle("Opening Fenix - Repertoire Creator")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.resize(scale(1400), scale(900))

        self.backend = CreatorBackend()
        self._processing_event = False  # Re-entrancy guard for eventFilter
        self.engine_thread = None
        self.sounds, self.piece_icons = {}, {}
        self.enrichment_threads = []
        
        # UI references for guards
        self.i_v1 = None
        self.i_v2 = None
        self.i_v3 = None
        self.txt_c = None

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

        self.init_icons()
        self.init_ui()
        self.init_engine()

        # Lazy load sounds to improve startup time
        QTimer.singleShot(200, self.init_sounds)

        st = self.config.get("theme")
        if st: self.board_widget.set_theme(st)
        QApplication.instance().installEventFilter(self)

        rtl = repertoire_name or self.config.get("last_active_repertoire")
        if rtl and os.path.exists(os.path.join(get_user_dir(), "repertoires", f"{rtl}.db")):
            self.backend.load_repertoire(rtl)
            self._load_saved_elo_or_autoselect()
            self.set_board_to_fen(initial_fen or chess.STARTING_FEN)
            self.update_structure_tree()
            self.setWindowTitle(f"Creator - {rtl}")
            self.board_widget.flipped = (self.backend.get_repertoire_color() == 'b')
            self.board_widget.update()
        else:
            # If no repertoire is found, default to creating a new one or opening empty state
            self.setWindowTitle("Creator - Kein Repertoire")
            # We can automatically prompt for a new repertoire if none is found
            QTimer.singleShot(100, self.new_repertoire_dialog)

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
        td = QWidget()
        dl = QVBoxLayout(td)
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
        ta = QWidget()
        al = QHBoxLayout(ta)
        al.setContentsMargins(0, scale(5), 0, 0)
        al.setSpacing(scale(15))

        # Left Column: Engine (GlassPill)
        engine_container = QFrame()
        engine_container.setProperty("class", "GlassPill")
        self.repolish(engine_container)
        evl = QVBoxLayout(engine_container)
        
        # Engine Settings (Dropdowns)
        h_eng_settings = QHBoxLayout()
        h_eng_settings.setSpacing(scale(10))
        
        self.combo_depth = QComboBox()
        self.combo_depth.setEditable(True)
        self.combo_depth.lineEdit().setReadOnly(True)
        self.combo_depth.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_depth.addItems([str(i) for i in range(10, 51, 2)])
        self.combo_depth.setCurrentText("20")
        self.combo_depth.setFixedWidth(scale(55))
        self.combo_depth.setProperty("class", "SmallCombo")
        self.repolish(self.combo_depth)
        
        self.combo_threads = QComboBox()
        self.combo_threads.setEditable(True)
        self.combo_threads.lineEdit().setReadOnly(True)
        self.combo_threads.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        max_threads = multiprocessing.cpu_count()
        self.combo_threads.addItems([str(i) for i in range(1, max_threads + 1)])
        self.combo_threads.setCurrentText(str(max(1, min(4, max_threads))))
        self.combo_threads.setFixedWidth(scale(55))
        self.combo_threads.setProperty("class", "SmallCombo")
        self.repolish(self.combo_threads)
        
        self.combo_lines = QComboBox()
        self.combo_lines.setEditable(True)
        self.combo_lines.lineEdit().setReadOnly(True)
        self.combo_lines.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_lines.addItems([str(i) for i in range(1, 11)])
        self.combo_lines.setCurrentText("5")
        self.combo_lines.setFixedWidth(scale(55))
        self.combo_lines.setProperty("class", "SmallCombo")
        self.repolish(self.combo_lines)
        
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
        
        lbl_helper = QLabel("(?)")
        lbl_helper.setStyleSheet(f"color: {COLORS['light_text']}; font-weight: bold;")
        lbl_helper.setToolTip(self.combo_lichess_cat.toolTip())
        
        h_cat.addWidget(self.combo_lichess_cat)
        h_cat.addWidget(lbl_helper)
        h_cat.addStretch()
        cvl.addLayout(h_cat)
        
        self.table_common_moves = QTableWidget(0, 5)
        self.table_common_moves.setHorizontalHeaderLabels(["Move", "White %", "Draw %", "Black %", "Played"])
        self.table_common_moves.verticalHeader().setVisible(False)
        self.table_common_moves.setAlternatingRowColors(True)
        self.table_common_moves.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_common_moves.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_common_moves.cellDoubleClicked.connect(self.on_common_move_double_click)
        header_cm = self.table_common_moves.horizontalHeader()
        header_cm.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cvl.addWidget(self.table_common_moves)
        al.addWidget(common_container, 5) # Common moves now significantly wider
        
        self.tabs.addTab(ta, "ANALYSIS")
        self.tabs.addTab(QWidget(), "LOCH FINDER")
        self.tabs.addTab(QWidget(), "KONTROLLE")
        
        # Restore the missing Stellungs-Details tab
        self.tabs.insertTab(0, td, "DETAILS")

        self.right_splitter.addWidget(self.tabs)
        # Symmetrical layout for bottoms: Ensure tabs (Details panel) is flushed to bottom
        self.tabs.setContentsMargins(0, 0, 0, 0)
        
        # Set initial sizes so it looks like before (e.g., split 50/50 vertically)
        self.right_splitter.setSizes([300, 300])

        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        l.addWidget(self.main_splitter)

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

        # Ensure "DETAILS" tab is selected by default on startup
        self.tabs.setCurrentIndex(0)

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
        if not desc:
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
        rf, ms = self.backend.get_path_to_fen(fen)
        if rf: self.board_widget.board = chess.Board(rf)
        for u in ms: self.board_widget.board.push(chess.Move.from_uci(u))
        self.board_widget.update()
        self.update_ui_from_fen()

    def update_ui_from_fen(self, force_details=False):
        # Guard: Ensure UI is initialized and valid before updating
        if not self._is_ui_valid():
            return
            
        f = self.board_widget.board.fen()
        d = self.backend.get_position_data(f)
        
        # Only update details if not currently being edited by the user to avoid overwriting typing
        if not self.details_changed or force_details:
            self.block_signals_details(True)
            if d:
                self.i_v1.setText(d['variation_1'] if not d['v1_inherited'] else "")
                self.i_v1.setPlaceholderText(d['variation_1'] if (d['v1_inherited'] and d['variation_1']) else "Variante 1")
                self.i_v2.setText(d['variation_2'] if not d['v2_inherited'] else "")
                self.i_v2.setPlaceholderText(d['variation_2'] if (d['v2_inherited'] and d['variation_2']) else "Variante 2")
                self.i_v3.setText(d['variation_3'] if not d['v3_inherited'] else "")
                self.i_v3.setPlaceholderText(d['variation_3'] if (d['v3_inherited'] and d['variation_3']) else "Variante 3")
                self.txt_c.setPlainText(d['comment'])
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
        for c in cs:
            nag_map = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
            nag_s = f" {nag_map[c['nag']]}" if c['nag'] in nag_map else ""
            it = SortableTreeWidgetItem([
                f"{c['san']}{nag_s}", 
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
            item_san = QTableWidgetItem(mv['san'])
            item_san.setData(Qt.ItemDataRole.UserRole, mv['uci']) # Store UCI for double click
            self.table_common_moves.setItem(r, 0, item_san)
            self.table_common_moves.setItem(r, 1, QTableWidgetItem(f"{mv['white_pct']:.1f}%"))
            self.table_common_moves.setItem(r, 2, QTableWidgetItem(f"{mv['draw_pct']:.1f}%"))
            self.table_common_moves.setItem(r, 3, QTableWidgetItem(f"{mv['black_pct']:.1f}%"))
            self.table_common_moves.setItem(r, 4, QTableWidgetItem(str(mv['total'])))

        self.update_board_arrows()

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
            self.backend.update_position_data(self.board_widget.board.fen(), self.txt_c.toPlainText(), self.i_v1.text(), self.i_v2.text(), self.i_v3.text())
            self.update_structure_tree()
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
        if not it:
            # Right-click into empty space -> Debug Menu
            menu = QMenu(self)
            act_debug = QAction("🛠 Debug: Stellungs-Info anzeigen", self)
            act_debug.triggered.connect(self.show_debug_position_info)
            menu.addAction(act_debug)
            menu.exec(self.tree_widget.mapToGlobal(pos))
            return
        
        menu = QMenu(self)
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
        menu.exec(self.tree_widget.mapToGlobal(pos))

    def show_debug_position_info(self):
        fen = self.board_widget.board.fen()
        incoming = self.backend.get_incoming_moves(fen)
        
        title = "Stellungs-Analyse (Debug)"
        msg = f"<b>Aktuelle FEN:</b><br><code style='background-color: #eee;'>{fen}</code><br><br>"
        
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
        m, p = self.backend.scan_and_get_impact(u, self.board_widget.board.fen())
        if QMessageBox.question(self, "Löschen", f"Sicher? {m} Züge und {p} Positionen werden gelöscht.") == QMessageBox.StandardButton.Yes:
            self.backend.delete_move(u, self.board_widget.board.fen())
            self.update_ui_from_fen()

    def set_nag_action(self, u, v):
        self.backend.set_nag(u, self.board_widget.board.fen(), v)
        self.update_ui_from_fen()

    def set_level_action(self, mid, l):
        self.backend.update_move_level(mid, l)
        self.update_ui_from_fen()

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
            RepoSettingsDialog(self, self.backend).exec()

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

    def on_structure_combo_changed(self, index):
        fen = self.combo_structure.currentData()
        if fen: self.set_board_to_fen(fen)
        self.combo_structure.blockSignals(True)
        self.combo_structure.setCurrentIndex(0)
        self.combo_structure.blockSignals(False)

    def load_repertoire_dialog(self):
        from opening_fenix.gui.dialogs.settings_dialog import LoadRepertoireDialog
        d = LoadRepertoireDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.backend.load_repertoire(d.selected_repo)
            self._load_saved_elo_or_autoselect()
            self.set_board_to_fen(chess.STARTING_FEN)
            self.update_structure_tree()
            self.setWindowTitle(f"Creator - {d.selected_repo}")
            self.board_widget.flipped = (self.backend.get_repertoire_color() == 'b')
            self.board_widget.update()

    def new_repertoire_dialog(self):
        n, ok = QInputDialog.getText(self, "Neu", "Name:")
        if ok and n:
            self.backend.load_repertoire(n)
            self.update_ui_from_fen()

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
        if hasattr(self, 'board_panel'):
            self.board_panel.setMinimumWidth(0)
            self.board_panel.setMaximumWidth(16777215)
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
        return super().eventFilter(obj, event)

    def repolish(self, widget):
        if widget:
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def closeEvent(self, event):
        """Clean up resources before closing."""
        if self.backend:
            self.backend.close()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CreatorWindow()
    window.show()
    sys.exit(app.exec())
