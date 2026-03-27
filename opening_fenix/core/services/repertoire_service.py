import os
import json
import sqlite3
import gc
import time
import chess
from collections import deque
from typing import List, Dict, Tuple, Any, Optional, Set
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, Base, TrainingData
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.data_tools import get_user_dir, get_meta, set_meta, delete_repertoire_db

class RepertoireManager:
    def __init__(self, profile_name: str = "Default") -> None:
        self.profile_name = profile_name
        self.active_repertoire_name = None
        
        self.repo_db = None
        self.repo_session = None
        
        self._variation_cache = {} # Cache for variation filtering
        self.priority_cache = None # Cache for (fen, uci) -> priority_score
        
        # New Caches for performance
        self._explorer_cache = {}
        self._history_cache = {}
        self._structure_cache = None
        self._move_parent_cache = None # Cache for get_history_for_move

    def get_all_repertoires(self) -> List[str]:
        repo_dir = os.path.join(get_user_dir(), "repertoires")
        if not os.path.exists(repo_dir): 
            return []
        
        files = []
        for f in os.listdir(repo_dir):
            if f.endswith(".db"):
                try:
                    db_path = os.path.join(repo_dir, f)
                    conn = sqlite3.connect(db_path)
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                    conn.close()
                    name = f[:-3] 
                    files.append(name)
                except sqlite3.DatabaseError:
                    continue
        return files

    def set_active_repertoire(self, repo_name: Optional[str]) -> None:
        self.close()
            
        self.active_repertoire_name = repo_name
        self._variation_cache = {} 
        self.priority_cache = None 
        
        # Clear caches on repertoire change
        self._explorer_cache = {}
        self._history_cache = {}
        self._structure_cache = None
        self._move_parent_cache = None
        
        if not repo_name: 
            return

        db_path = os.path.join(get_user_dir(), "repertoires", f"{repo_name}.db")
        self.repo_db = DatabaseManager(db_path, base=Base)
        self.repo_session = self.repo_db.get_session()

    def close(self) -> None:
        if self.repo_session:
            self.repo_session.close()
            self.repo_session = None
        if self.repo_db:
            self.repo_db.close()
            self.repo_db = None

    def delete_repertoire(self, repo_name: str) -> Tuple[bool, str]:
        if self.active_repertoire_name == repo_name:
            self.set_active_repertoire(None)
        
        gc.collect()
        time.sleep(0.5) 
        
        success, msg = delete_repertoire_db(repo_name)
        return success, msg

    def get_repertoire_levels(self) -> List[Dict[str, Any]]:
        if not self.repo_session: return []
        levels = self.repo_session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
        return [{"name": lvl.name, "order": lvl.order, "target_elo": lvl.target_elo} for lvl in levels]

    def get_level_info(self, level_order: int) -> Optional[RepertoireLevel]:
        if not self.repo_session: return None
        return self.repo_session.query(RepertoireLevel).filter_by(order=level_order).first()

    def update_level_elo(self, level_order: int, target_elo: int) -> None:
        if not self.repo_session: return
        lvl = self.repo_session.query(RepertoireLevel).filter_by(order=level_order).first()
        if lvl:
            lvl.target_elo = target_elo
            self.repo_session.commit()

    def get_repertoire_info(self) -> Dict[str, Any]:
        if not self.repo_session:
            return {
                "name": self.active_repertoire_name,
                "levels": [],
                "depth": "N/A",
                "elo": "N/A",
                "moves": "N/A",
                "description": ""
            }

        levels = self.get_repertoire_levels()
        level_names = [lvl['name'] for lvl in levels]
        moves_count = self.repo_session.query(RepertoireMove.move_id).filter(RepertoireMove.is_active == True).distinct().count()

        return {
            "name": get_meta(self.repo_session, "name", self.active_repertoire_name),
            "levels": level_names,
            "depth": get_meta(self.repo_session, "analysis_depth", "N/A"),
            "elo": get_meta(self.repo_session, "lichess_elo", "N/A"),
            "moves": moves_count,
            "description": get_meta(self.repo_session, "description", "")
        }

    def get_repertoire_color(self) -> str:
        if not self.repo_session: return 'w'
        return get_meta(self.repo_session, "color", "w")

    def get_repertoire_start_move(self) -> int:
        if not self.repo_session: return 1
        try:
            return int(get_meta(self.repo_session, "start_move", 1))
        except:
            return 1

    def set_repertoire_start_move(self, start_move: int) -> None:
        if not self.repo_session: return
        set_meta(self.repo_session, "start_move", str(start_move))
        self.repo_session.commit()

    def _get_variation_roots(self, variation_name):
        roots = self.repo_session.query(Position.id).filter(
            or_(Position.variation_1 == variation_name, Position.variation_2 == variation_name)
        ).all()
        return {r.id for r in roots}

    def _get_lead_up_ids(self, root_ids):
        # We need this to quickly find parents without hitting the DB in a loop.
        # Since this happens on variation filter, let's load all moves into memory once.
        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()
            
        queue = deque(root_ids)
        visited = set(root_ids)
        lead_up = set()
        
        while queue:
            curr_id = queue.popleft()
            parents = self._move_parent_cache.get(curr_id, [])
            for parent_move in parents:
                pid = parent_move.from_position_id
                if pid and pid not in visited:
                    visited.add(pid)
                    lead_up.add(pid)
                    queue.append(pid)
        return lead_up

    def _get_position_state(self, position_id, root_ids, lead_up_ids, cache):
        if position_id in cache: return cache[position_id]
        
        if position_id in root_ids:
            cache[position_id] = 2 
            return 2
        
        if position_id in lead_up_ids:
            cache[position_id] = 1 
            return 1
            
        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()
            
        parents = self._move_parent_cache.get(position_id, [])
        if not parents:
            cache[position_id] = 0 
            return 0
            
        for parent_move in parents:
            p_state = self._get_position_state(parent_move.from_position_id, root_ids, lead_up_ids, cache)
            if p_state == 2 or p_state == 3: 
                cache[position_id] = 3 
                return 3
        
        cache[position_id] = 0
        return 0

    def _prepare_variation_filter(self, variation_name):
        if not variation_name: return None
        if variation_name in self._variation_cache:
            return self._variation_cache[variation_name]
            
        root_ids = self._get_variation_roots(variation_name)
        lead_up_ids = self._get_lead_up_ids(root_ids)
        
        data = {
            "roots": root_ids,
            "lead_up": lead_up_ids,
            "cache": {}
        }
        self._variation_cache[variation_name] = data
        return data

    def _find_inherited_v1(self, position_id):
        curr_id = position_id
        visited = set()
        
        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()
            
        while curr_id:
            if curr_id in visited: break
            visited.add(curr_id)

            incoming_moves = self._move_parent_cache.get(curr_id, [])
            if not incoming_moves: break
            incoming_moves.sort(key=lambda m: m.priority_score, reverse=True)
            dominant_move = incoming_moves[0]
            
            parent = self.repo_session.query(Position).get(dominant_move.from_position_id)
            if not parent: break
            
            if parent.variation_1:
                return parent.variation_1
            
            curr_id = parent.id
        return None

    def get_variation_structure(self):
        if self._structure_cache is not None:
            return self._structure_cache

        if not self.repo_session: return {}
        
        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()
        
        structure = {}
        v1_priorities = {}
        v2_priorities = {}
        
        named_positions = self.repo_session.query(Position).filter(
            or_(
                (Position.variation_1 != None) & (Position.variation_1 != ""),
                (Position.variation_2 != None) & (Position.variation_2 != "")
            )
        ).all()
        
        for pos in named_positions:
            v1 = pos.variation_1
            v2 = pos.variation_2
            
            if not v1 and v2:
                v1 = self._find_inherited_v1(pos.id)

            if v1:
                incoming_moves = self._move_parent_cache.get(pos.id, [])
                prio = 0.0
                if incoming_moves:
                    prio = max((m.priority_score for m in incoming_moves), default=0.0)
                
                if v1 not in v1_priorities:
                    v1_priorities[v1] = 0.0
                if prio > v1_priorities[v1]:
                    v1_priorities[v1] = prio

                if v1 not in structure:
                    structure[v1] = set()
                
                if v2:
                    structure[v1].add(v2)
                    key = (v1, v2)
                    if key not in v2_priorities:
                        v2_priorities[key] = 0.0
                    if prio > v2_priorities[key]:
                        v2_priorities[key] = prio
        
        final_structure = {}
        sorted_v1 = sorted(structure.keys(), key=lambda k: v1_priorities.get(k, 0.0), reverse=True)

        for k in sorted_v1:
            v2_list = list(structure[k])
            v2_list.sort(key=lambda v2: v2_priorities.get((k, v2), 0.0), reverse=True)
            final_structure[k] = v2_list
            
        self._structure_cache = final_structure
        return final_structure
        
    def _ensure_move_parent_cache(self):
        """Pre-fetches all moves and their target positions into memory to avoid N+1 queries during tree traversal."""
        if not self.repo_session: return
        self._move_parent_cache = {}
        all_moves = self.repo_session.query(Move).options(joinedload(Move.from_position), joinedload(Move.to_position)).all()
        for move in all_moves:
            if move.to_position_id not in self._move_parent_cache:
                self._move_parent_cache[move.to_position_id] = []
            self._move_parent_cache[move.to_position_id].append(move)

    def get_history_for_move(self, move_obj, root_fen=None):
        if not self.repo_session or move_obj is None: return []
        
        cache_key = (move_obj.id, root_fen)
        if cache_key in self._history_cache:
            return self._history_cache[cache_key]

        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()

        history = []
        curr = move_obj

        clean_root_fen = None
        if root_fen:
            clean_root_fen = " ".join(root_fen.split(" ")[:4])

        for _ in range(100):
            history.insert(0, {
                'san': curr.san, 
                'uci': curr.uci, 
                'fen': curr.to_position.fen, 
                'comment': curr.to_position.comment,
                'nag': getattr(curr, 'nag', 0)
            })
            
            if curr.from_position.fen == clean_root_fen:
                break
                
            # Use cache instead of query
            parents = self._move_parent_cache.get(curr.from_position_id, [])
            parents = sorted(parents, key=lambda m: m.priority_score, reverse=True)
            
            if not parents: break
            
            selected_parent = parents[0]
            
            if clean_root_fen:
                found_parent_from_root = False
                for p in parents:
                    if p.from_position.fen == clean_root_fen:
                        selected_parent = p
                        found_parent_from_root = True
                        break
                if found_parent_from_root:
                    history.insert(0, {
                        'san': selected_parent.san, 
                        'uci': selected_parent.uci, 
                        'fen': selected_parent.to_position.fen, 
                        'comment': selected_parent.to_position.comment,
                        'nag': getattr(selected_parent, 'nag', 0)
                    })
                    break

            curr = selected_parent
            
        self._history_cache[cache_key] = history
        return history

    def get_history_for_fen(self, fen):
        if not self.repo_session: return []
        board = chess.Board(fen)
        clean_fen = " ".join(board.fen().split(" ")[:4])
        pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()
        if not pos: return []
        
        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()
            
        parents = self._move_parent_cache.get(pos.id, [])
        if not parents: return []
        
        parents = sorted(parents, key=lambda m: m.priority_score, reverse=True)
        move_to_pos = parents[0]

        return self.get_history_for_move(move_to_pos)

    def get_repertoire_root_fen(self):
        if not self.repo_session:
            return None

        any_move = self.repo_session.query(Move).join(RepertoireMove).first()

        if not any_move:
            return None 
            
        if self._move_parent_cache is None:
            self._ensure_move_parent_cache()

        ancestor = self._get_absolute_ancestor(any_move)
        root_pos = ancestor.from_position
        
        board = chess.Board()
        board.set_epd(root_pos.fen)
        return board.fen()

    def _get_absolute_ancestor(self, move_obj):
        """ Helper to find the ultimate root of a sequence, ignoring training status. """
        parents = self._move_parent_cache.get(move_obj.from_position_id, [])
        if parents:
            parents = sorted(parents, key=lambda m: m.priority_score, reverse=True)
            return self._get_absolute_ancestor(parents[0])
        return move_obj

    def get_explorer_data_for_fen(self, fen, training_manager):
        if not self.repo_session: 
            return {}

        if fen in self._explorer_cache:
            return self._explorer_cache[fen]

        board = chess.Board(fen)
        clean_fen = " ".join(board.fen().split(" ")[:4])
        
        pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()
        repertoire_color = self.get_repertoire_color()
        if not repertoire_color: 
            return {}

        is_player_turn = (board.turn == chess.WHITE and repertoire_color == 'w') or \
                         (board.turn == chess.BLACK and repertoire_color == 'b')

        if not pos:
            entry_moves = []
            for move in board.legal_moves:
                temp_board = board.copy()
                temp_board.push(move)
                next_clean_fen = " ".join(temp_board.fen().split(" ")[:4])
                next_pos = self.repo_session.query(Position).filter_by(fen=next_clean_fen).first()
                if next_pos:
                    our_response = self.repo_session.query(Move)\
                        .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                        .filter(Move.from_position_id == next_pos.id).first()
                    
                    if our_response or is_player_turn:
                        entry_moves.append({
                            "san": board.san(move), "uci": move.uci(), "comment": next_pos.comment, "level": 1
                        })

            player_moves, opponent_moves = None, None
            if is_player_turn:
                player_moves = {"main_move": None, "alt_moves": [], "analysis_depth": None}
                if entry_moves:
                    player_moves["main_move"] = {"san": entry_moves[0]["san"], "uci": entry_moves[0]["uci"]}
                    player_moves["alt_moves"] = [{"san": m["san"], "uci": m["uci"]} for m in entry_moves[1:]]
            else:
                opponent_moves = entry_moves

            res = {
                "fen": fen, "is_player_turn": is_player_turn, "priority_score": 0,
                "box": 0, "player_moves": player_moves, "opponent_moves": opponent_moves
            }
            self._explorer_cache[fen] = res
            return res

        move_that_led_here = self.repo_session.query(Move).filter(Move.to_position_id == pos.id).order_by(Move.priority_score.desc()).first()
        priority_score, box = 0, 0
        if move_that_led_here:
            priority_score = move_that_led_here.priority_score
            
            training_data = training_manager.user_session.query(TrainingData).filter_by(
                repertoire_name=self.active_repertoire_name, 
                fen=move_that_led_here.from_position.fen, 
                move_uci=move_that_led_here.uci
            ).first()
            
            if training_data: box = training_data.box

        if priority_score == 0:
             outgoing_rep_move = self.repo_session.query(Move)\
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                .filter(Move.from_position_id == pos.id)\
                .order_by(Move.priority_score.desc())\
                .first()
             if outgoing_rep_move:
                 priority_score = outgoing_rep_move.priority_score

        player_moves, opponent_moves = None, None
        if is_player_turn:
            player_moves = {"main_move": None, "alt_moves": [], "analysis_depth": pos.analysis_depth}
            repertoire_moves_from_pos = self.repo_session.query(Move)\
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                .filter(Move.from_position_id == pos.id, RepertoireMove.is_active == True)\
                .order_by(Move.priority_score.desc()).all()

            if repertoire_moves_from_pos:
                main_move_obj = repertoire_moves_from_pos[0]
                player_moves["main_move"] = {
                    "san": main_move_obj.san, 
                    "uci": main_move_obj.uci,
                    "comment": main_move_obj.to_position.comment 
                }
                player_moves["alt_moves"] = [{
                    "san": alt.san, 
                    "uci": alt.uci,
                    "comment": alt.to_position.comment
                } for alt in repertoire_moves_from_pos[1:]]

            if pos.good_moves:
                try:
                    existing_ucis = {m.uci for m in repertoire_moves_from_pos}
                    good_moves_list = json.loads(pos.good_moves)
                    board_for_san = chess.Board(fen)
                    for uci in good_moves_list:
                        if uci not in existing_ucis:
                            try:
                                move = chess.Move.from_uci(uci)
                                if board_for_san.is_legal(move):
                                    san = board_for_san.san(move)
                                    player_moves["alt_moves"].append({"san": san, "uci": uci, "comment": ""})
                            except:
                                continue
                except: pass
        else: # Opponent's turn
            opponent_moves = []
            all_moves_from_pos = self.repo_session.query(Move).filter(Move.from_position_id == pos.id).all()
            for move in all_moves_from_pos:
                next_pos_id = move.to_position_id
                our_next_move = self.repo_session.query(Move)\
                    .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                    .filter(Move.from_position_id == next_pos_id, RepertoireMove.is_active == True).first()
                if our_next_move:
                    rep_info = self.repo_session.query(RepertoireMove).filter_by(move_id=our_next_move.id).first()
                    level = rep_info.level if rep_info else 1
                    opponent_moves.append({"san": move.san, "uci": move.uci, "comment": move.to_position.comment, "level": level})

        res = {
            "fen": fen, "is_player_turn": is_player_turn, "priority_score": priority_score,
            "box": box, "player_moves": player_moves, "opponent_moves": opponent_moves
        }
        self._explorer_cache[fen] = res
        return res

    def get_repertoire_moves_for_fen(self, fen):
        if not self.repo_session:
            return []

        board = chess.Board(fen)
        clean_fen = " ".join(board.fen().split(" ")[:4])
        pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()

        all_ucis = set()

        if not pos:
            entry_point_ucis = []
            for move in board.legal_moves:
                temp_board = board.copy()
                temp_board.push(move)
                next_clean_fen = " ".join(temp_board.fen().split(" ")[:4])
                next_pos_exists = self.repo_session.query(Position).filter_by(fen=next_clean_fen).first()
                if next_pos_exists:
                    entry_point_ucis.append(move.uci())
            return entry_point_ucis

        repertoire_color = self.get_repertoire_color()
        is_player_turn = (board.turn == chess.WHITE and repertoire_color == 'w') or \
                         (board.turn == chess.BLACK and repertoire_color == 'b')


        if is_player_turn:
            player_moves_query = self.repo_session.query(Move.uci)\
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                .filter(Move.from_position_id == pos.id, RepertoireMove.is_active == True)
            
            for move in player_moves_query.all():
                all_ucis.add(move[0])

            if pos.good_moves:
                try:
                    good_moves_list = json.loads(pos.good_moves)
                    for good_move in good_moves_list:
                        all_ucis.add(good_move)
                except:
                    pass
        else:
            opponent_moves_query = self.repo_session.query(Move).filter(Move.from_position_id == pos.id).all()
            for move in opponent_moves_query:
                next_pos_id = move.to_position_id
                our_next_move_exists = self.repo_session.query(RepertoireMove)\
                    .join(Move, RepertoireMove.move_id == Move.id)\
                    .filter(Move.from_position_id == next_pos_id, RepertoireMove.is_active == True)\
                    .first()
                if our_next_move_exists:
                    all_ucis.add(move.uci)

        return list(all_ucis)

    def _ensure_priority_cache(self):
        if self.priority_cache is None and self.repo_session:
            try:
                q = self.repo_session.query(Position.fen, Move.uci, Move.priority_score)\
                    .join(Move, Position.id == Move.from_position_id)
                self.priority_cache = {(fen, uci): prio for fen, uci, prio in q.all()}
            except Exception as e:
                print(f"Error loading priority cache: {e}")
                self.priority_cache = {}

    def check_if_alternative_good_move(self, move_obj, played_uci):
        if not self.repo_session: return False
        other_rep_move = self.repo_session.query(RepertoireMove).join(Move).filter(
            Move.from_position_id == move_obj.from_position_id,
            Move.uci == played_uci,
            RepertoireMove.is_active == True
        ).first()
        if other_rep_move: return True
        pos = move_obj.from_position
        if pos.good_moves:
            try:
                good_list = json.loads(pos.good_moves)
                return played_uci in good_list
            except: pass
        return False
