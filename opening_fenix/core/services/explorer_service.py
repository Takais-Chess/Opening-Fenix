import chess
import json
from functools import lru_cache
from typing import Dict, Any, List, Optional
from opening_fenix.core.db.models import Position, Move, RepertoireMove, TrainingData
from opening_fenix.core.logger import logger

class ExplorerService:
    def __init__(self, session, training_manager=None):
        self.repo_session = session
        self.training_manager = training_manager
        self._cache = {} # Manual cache to avoid memory leaks with lru_cache on session-bound objects

    def get_explorer_data_for_fen(self, fen: str, repertoire_color: str) -> Dict[str, Any]:
        """Provides all necessary data for the UI explorer view at a specific FEN."""
        if not self.repo_session: return {}
        
        # Check cache
        if fen in self._cache:
            return self._cache[fen]

        board = chess.Board(fen)
        clean_fen = " ".join(board.fen().split(" ")[:4])
        pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()
        
        is_player_turn = (board.turn == chess.WHITE and repertoire_color == 'w') or \
                         (board.turn == chess.BLACK and repertoire_color == 'b')

        if not pos:
            # Handle unknown position (entry moves)
            return self._prepare_entry_data(fen, board, is_player_turn)

        # Handle known position
        res = self._prepare_known_position_data(fen, board, pos, is_player_turn)
        
        # Cache management: cap size
        if len(self._cache) > 100:
            self._cache.pop(next(iter(self._cache)))
        self._cache[fen] = res
        
        return res

    def _prepare_entry_data(self, fen, board, is_player_turn):
        # Existing logic to find entry moves...
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

        player_moves = None
        opponent_moves = None
        if is_player_turn:
            player_moves = {"main_move": None, "alt_moves": [], "analysis_depth": None}
            if entry_moves:
                player_moves["main_move"] = {"san": entry_moves[0]["san"], "uci": entry_moves[0]["uci"]}
                player_moves["alt_moves"] = [{"san": m["san"], "uci": m["uci"]} for m in entry_moves[1:]]
        else:
            opponent_moves = entry_moves

        return {
            "fen": fen, "is_player_turn": is_player_turn, "priority_score": 0,
            "box": 0, "player_moves": player_moves, "opponent_moves": opponent_moves
        }

    def _prepare_known_position_data(self, fen, board, pos, is_player_turn):
        # Load moves from DB
        player_moves = None
        opponent_moves = None
        priority_score = 0
        box = 0
        
        # Training data check
        move_that_led_here = self.repo_session.query(Move).filter(Move.to_position_id == pos.id).order_by(Move.priority_score.desc()).first()
        if move_that_led_here and self.training_manager:
            priority_score = move_that_led_here.priority_score
            training_data = self.training_manager.user_session.query(TrainingData).filter_by(
                fen=move_that_led_here.from_position.fen, 
                move_uci=move_that_led_here.uci
            ).first()
            if training_data: box = training_data.box

        if is_player_turn:
            player_moves = {"main_move": None, "alt_moves": [], "analysis_depth": pos.analysis_depth}
            repertoire_moves_from_pos = self.repo_session.query(Move)\
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)\
                .filter(Move.from_position_id == pos.id, RepertoireMove.is_active == True)\
                .order_by(Move.priority_score.desc()).all()

            if repertoire_moves_from_pos:
                main_move_obj = repertoire_moves_from_pos[0]
                player_moves["main_move"] = {
                    "san": main_move_obj.san, "uci": main_move_obj.uci, "comment": main_move_obj.to_position.comment 
                }
                player_moves["alt_moves"] = [{
                    "san": alt.san, "uci": alt.uci, "comment": alt.to_position.comment
                } for alt in repertoire_moves_from_pos[1:]]
        else:
            # Opponent moves
            opponent_moves = []
            all_moves_from_pos = self.repo_session.query(Move).filter(Move.from_position_id == pos.id).all()
            for move in all_moves_from_pos:
                next_pos_id = move.to_position_id
                our_next_move = self.repo_session.query(RepertoireMove)\
                    .join(Move, Move.id == RepertoireMove.move_id)\
                    .filter(Move.from_position_id == next_pos_id, RepertoireMove.is_active == True).first()
                if our_next_move:
                    opponent_moves.append({
                        "san": move.san, "uci": move.uci, "comment": move.to_position.comment, "level": our_next_move.level
                    })

        return {
            "fen": fen, "is_player_turn": is_player_turn, "priority_score": priority_score,
            "box": box, "player_moves": player_moves, "opponent_moves": opponent_moves
        }
