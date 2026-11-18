import chess
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import joinedload
from opening_fenix.core.db.models import Position, Move, RepertoireMove, TrainingData
from opening_fenix.core.logger import logger


def _norm_fen4(fen: str) -> str:
    s = fen.strip()
    if s.count(" ") >= 5:
        return s.rsplit(" ", 2)[0]
    parts = s.split(" ")
    return " ".join(parts[:4])


class ExplorerService:
    def __init__(self, session, training_manager=None):
        self.repo_session = session
        self.training_manager = training_manager
        self._cache = {}  # Manual cache to avoid memory leaks with lru_cache on session-bound objects

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def get_explorer_data_for_fen(self, fen: str, repertoire_color: str) -> Dict[str, Any]:
        """Provides all necessary data for the UI explorer view at a specific FEN."""
        if not self.repo_session or not fen:
            return {}

        clean_fen = _norm_fen4(fen)
        cache_key = (clean_fen, repertoire_color)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if cached.get("fen") == fen:
                return cached
            return {**cached, "fen": fen}

        parts = clean_fen.split(" ")
        turn_char = parts[1] if len(parts) > 1 else "w"
        is_player_turn = (turn_char == repertoire_color)

        tm = self.training_manager
        pos_cache = getattr(tm, "_pos_cache", None) if tm is not None else None
        fwd_cache = getattr(tm, "_forward_moves_cache", None) if tm is not None else None
        rep_cache = getattr(tm, "_rep_move_cache", None) if tm is not None else None
        parent_cache = getattr(tm, "_move_parent_cache", None) if tm is not None else None

        pos = None
        use_tm_cache = (pos_cache is not None and fwd_cache is not None and rep_cache is not None and parent_cache is not None)
        if use_tm_cache:
            for p_obj in pos_cache.values():
                if p_obj.fen == clean_fen:
                    pos = p_obj
                    break
        else:
            pos = self.repo_session.query(Position).filter_by(fen=clean_fen).first()

        if not pos:
            res = self._prepare_entry_data(
                fen, is_player_turn,
                pos_cache if use_tm_cache else None,
                fwd_cache if use_tm_cache else None,
                rep_cache if use_tm_cache else None,
            )
        else:
            res = self._prepare_known_position_data(fen, pos, is_player_turn, use_tm_cache)

        if len(self._cache) >= 128:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = res
        return res

    def _prepare_entry_data(self, fen, is_player_turn, pos_cache=None, fwd_cache=None, rep_cache=None):
        board = chess.Board(fen)
        legal_moves = list(board.legal_moves)
        candidates = []

        for move in legal_moves:
            san = board.san(move)
            board.push(move)
            next_clean_fen = _norm_fen4(board.fen())
            board.pop()
            candidates.append((san, move.uci(), next_clean_fen))

        entry_moves = []
        if pos_cache is not None and fwd_cache is not None and rep_cache is not None:
            needed_fens = {cf for _, _, cf in candidates}
            fen_to_pos = {p.fen: p for p in pos_cache.values() if p.fen in needed_fens}
            for san, uci, next_clean_fen in candidates:
                next_pos = fen_to_pos.get(next_clean_fen)
                if not next_pos:
                    continue
                has_rep_response = any(m.id in rep_cache for m in fwd_cache.get(next_pos.id, ()))
                if has_rep_response or is_player_turn:
                    entry_moves.append({
                        "san": san, "uci": uci, "comment": next_pos.comment, "level": 1
                    })
        else:
            unique_fens = list({cf for _, _, cf in candidates})
            fen_to_pos = {}
            if unique_fens:
                for p in self.repo_session.query(Position).filter(Position.fen.in_(unique_fens)).all():
                    fen_to_pos[p.fen] = p

            matched_pos_ids = [p.id for p in fen_to_pos.values()]
            has_response_ids = set()
            if matched_pos_ids and not is_player_turn:
                has_response_ids = {
                    from_pid for (from_pid,) in self.repo_session.query(Move.from_position_id)
                    .join(RepertoireMove, Move.id == RepertoireMove.move_id)
                    .filter(Move.from_position_id.in_(matched_pos_ids))
                    .distinct().all()
                }

            for san, uci, next_clean_fen in candidates:
                next_pos = fen_to_pos.get(next_clean_fen)
                if next_pos and (is_player_turn or next_pos.id in has_response_ids):
                    entry_moves.append({
                        "san": san, "uci": uci, "comment": next_pos.comment, "level": 1
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

    def _prepare_known_position_data(self, fen, pos, is_player_turn, use_tm_cache=False):
        player_moves = None
        opponent_moves = None
        priority_score = 0
        box = 0
        tm = self.training_manager

        if use_tm_cache and tm is not None:
            pos_cache = tm._pos_cache
            fwd_cache = tm._forward_moves_cache
            rep_cache = tm._rep_move_cache
            parent_cache = tm._move_parent_cache
            td_cache = getattr(tm, "_td_cache", None)

            parents = parent_cache.get(pos.id)
            if parents:
                lead_move = parents[0]
                priority_score = lead_move.priority_score or 0
                if td_cache is not None:
                    lead_from_pos = pos_cache.get(lead_move.from_position_id)
                    if lead_from_pos:
                        td = td_cache.get((lead_from_pos.fen, lead_move.uci))
                        if td is not None:
                            box = td.box

            out_moves = fwd_cache.get(pos.id, ())
            if is_player_turn:
                player_moves = {"main_move": None, "alt_moves": [], "analysis_depth": getattr(pos, "analysis_depth", None)}
                rep_moves = [m for m in out_moves if m.id in rep_cache and getattr(rep_cache[m.id], "is_active", True)]
                if rep_moves:
                    main_m = rep_moves[0]
                    main_to = pos_cache.get(main_m.to_position_id)
                    player_moves["main_move"] = {
                        "san": main_m.san, "uci": main_m.uci, "comment": main_to.comment if main_to else None
                    }
                    player_moves["alt_moves"] = [{
                        "san": alt.san,
                        "uci": alt.uci,
                        "comment": pos_cache[alt.to_position_id].comment if alt.to_position_id in pos_cache else None
                    } for alt in rep_moves[1:]]
            else:
                opponent_moves = []
                for m in out_moves:
                    best_lvl = None
                    for nxt in fwd_cache.get(m.to_position_id, ()):
                        rm = rep_cache.get(nxt.id)
                        if rm and getattr(rm, "is_active", True):
                            best_lvl = rm.level
                            break
                    if best_lvl is not None:
                        to_p = pos_cache.get(m.to_position_id)
                        opponent_moves.append({
                            "san": m.san, "uci": m.uci, "comment": to_p.comment if to_p else None, "level": best_lvl
                        })

            return {
                "fen": fen, "is_player_turn": is_player_turn, "priority_score": priority_score,
                "box": box, "player_moves": player_moves, "opponent_moves": opponent_moves
            }

        # Fallback DB path (batched, no N+1 queries)
        move_that_led_here = (
            self.repo_session.query(Move)
            .options(joinedload(Move.from_position))
            .filter(Move.to_position_id == pos.id)
            .order_by(Move.priority_score.desc())
            .first()
        )
        if move_that_led_here and tm:
            priority_score = move_that_led_here.priority_score
            repo_name = getattr(getattr(tm, "repertoire_manager", None), "active_repertoire_name", None)
            td_q = tm.user_session.query(TrainingData).filter_by(
                fen=move_that_led_here.from_position.fen,
                move_uci=move_that_led_here.uci
            )
            if repo_name:
                td_q = td_q.filter_by(repertoire_name=repo_name)
            training_data = td_q.first()
            if training_data:
                box = training_data.box

        if is_player_turn:
            player_moves = {"main_move": None, "alt_moves": [], "analysis_depth": pos.analysis_depth}
            repertoire_moves_from_pos = (
                self.repo_session.query(Move)
                .options(joinedload(Move.to_position))
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)
                .filter(Move.from_position_id == pos.id, RepertoireMove.is_active == True)
                .order_by(Move.priority_score.desc())
                .all()
            )

            if repertoire_moves_from_pos:
                main_move_obj = repertoire_moves_from_pos[0]
                player_moves["main_move"] = {
                    "san": main_move_obj.san, "uci": main_move_obj.uci, "comment": main_move_obj.to_position.comment
                }
                player_moves["alt_moves"] = [{
                    "san": alt.san, "uci": alt.uci, "comment": alt.to_position.comment
                } for alt in repertoire_moves_from_pos[1:]]
        else:
            opponent_moves = []
            all_moves_from_pos = (
                self.repo_session.query(Move)
                .options(joinedload(Move.to_position))
                .filter(Move.from_position_id == pos.id)
                .all()
            )
            next_ids = [m.to_position_id for m in all_moves_from_pos if m.to_position_id]
            next_rep_levels = {}
            if next_ids:
                for from_pid, lvl in (
                    self.repo_session.query(Move.from_position_id, RepertoireMove.level)
                    .join(RepertoireMove, RepertoireMove.move_id == Move.id)
                    .filter(Move.from_position_id.in_(next_ids), RepertoireMove.is_active == True)
                    .all()
                ):
                    if from_pid not in next_rep_levels:
                        next_rep_levels[from_pid] = lvl

            for move in all_moves_from_pos:
                lvl = next_rep_levels.get(move.to_position_id)
                if lvl is not None:
                    opponent_moves.append({
                        "san": move.san, "uci": move.uci, "comment": move.to_position.comment, "level": lvl
                    })

        return {
            "fen": fen, "is_player_turn": is_player_turn, "priority_score": priority_score,
            "box": box, "player_moves": player_moves, "opponent_moves": opponent_moves
        }
