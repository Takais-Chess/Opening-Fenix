"""
Repertoire Mistake Service.
Audits the repertoire with a chess engine to detect player moves where the
pawn loss is greater than 0.5 (centipawn loss > 50 cp) compared to the engine's best move.
Leverages existing Alternate Moves engine analysis (good_moves, analysis_depth, EngineCacheService)
and synchronizes updates back to the repertoire database.
"""

import os
import sys
import json
import subprocess
import chess
import chess.engine
from typing import Tuple, Callable, Optional, List, Dict, Any

from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.services.engine_cache_service import EngineCacheService
from opening_fenix.core.logger import logger


def format_score_to_str(score: chess.engine.Score) -> Tuple[str, int]:
    """Formats a python-chess Score into (display_str, white_cp_val)."""
    if score.is_mate():
        mate = score.white().mate()
        score_str = f"M{mate:+d}" if mate is not None else "M?"
        cp_val = 10000 if (mate is not None and mate > 0) else -10000
    else:
        cp = score.white().score()
        if cp is not None:
            score_str = f"{cp / 100.0:+.2f}"
            cp_val = cp
        else:
            score_str = "0.00"
            cp_val = 0
    return score_str, cp_val


def audit_repertoire_mistakes(
    repo_name: str,
    engine_path: str,
    depth: int = 18,
    threads: int = 4,
    hash_size: int = 256,
    threshold_pawns: float = 0.5,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
    mistake_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    check_cancel: Optional[Callable[[], bool]] = None
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Scans the player's active repertoire positions and identifies moves where
    the repertoire move has a pawn loss > threshold_pawns (default 0.5 pawns / 50 cp)
    compared to the best engine move.

    Also updates Position.good_moves, Position.analysis_depth, and Position.engine_eval
    to keep Alternate Moves in sync.
    """
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return False, f"Repertoire-Datenbank für '{repo_name}' nicht gefunden.", []

    db = DatabaseManager(db_path)
    session = db.get_session()
    engine = None
    mistakes: List[Dict[str, Any]] = []

    try:
        player_color = get_meta(session, "color", "w")
        turn_filter = Position.fen.like(f'% {player_color} %')

        # Find all positions where player moves exist in active repertoire
        positions_query = session.query(Position).join(
            Move, Position.id == Move.from_position_id
        ).join(
            RepertoireMove, Move.id == RepertoireMove.move_id
        ).filter(
            turn_filter,
            RepertoireMove.is_active == True
        ).distinct()

        positions = positions_query.all()
        total_positions = len(positions)
        if total_positions == 0:
            return True, "Keine aktiven Repertoire-Züge für die Spielerfarbe gefunden.", []

        # Start Engine
        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x08000000 | 0x00004000  # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS

        engine = chess.engine.SimpleEngine.popen_uci(engine_path, creationflags=creationflags)
        config: Dict[str, Any] = {}
        if "Threads" in engine.options:
            config["Threads"] = threads
        if "Hash" in engine.options:
            config["Hash"] = hash_size
        if config:
            engine.configure(config)

        cache_service = EngineCacheService()
        threshold_cp = int(threshold_pawns * 100)

        for i, pos in enumerate(positions):
            if check_cancel and check_cancel():
                commit_with_retry(session)
                return False, "Scan abgebrochen. Bisheriger Fortschritt wurde gespeichert.", mistakes

            # Fetch primary repertoire move from this position
            rep_move = session.query(Move).join(
                RepertoireMove, Move.id == RepertoireMove.move_id
            ).filter(
                Move.from_position_id == pos.id,
                RepertoireMove.is_active == True
            ).first()

            if not rep_move:
                continue

            try:
                board = chess.Board(pos.fen)
            except Exception as e:
                logger.warning(f"Skipping invalid FEN {pos.fen}: {e}")
                continue

            try:
                rep_chess_move = chess.Move.from_uci(rep_move.uci)
            except Exception:
                continue

            if rep_chess_move not in board.legal_moves:
                continue

            # MultiPV scan (up to 5) to find best moves and alternative good moves
            multipv_count = 5
            if "MultiPV" in engine.options:
                opt = engine.options["MultiPV"]
                max_allowed = opt.max if (hasattr(opt, 'max') and opt.max is not None) else 5
                multipv_count = min(5, max_allowed)

            try:
                analysis_results = engine.analyse(
                    board,
                    chess.engine.Limit(depth=depth),
                    multipv=multipv_count
                )
            except Exception as e:
                logger.error(f"Engine analysis error on FEN {pos.fen}: {e}")
                continue

            if not analysis_results:
                continue

            # Best move info
            best_info = analysis_results[0]
            best_move = best_info['pv'][0] if ('pv' in best_info and best_info['pv']) else None
            if not best_move:
                continue

            best_uci = best_move.uci()
            try:
                best_san = board.san(best_move)
            except Exception:
                best_san = best_uci

            best_eval_str, best_eval_cp = format_score_to_str(best_info['score'])
            best_rel_score = best_info['score'].relative.score(mate_score=10000)

            # Store best move in global cache
            try:
                cache_service.set(pos.fen, depth, best_uci)
            except Exception:
                pass

            # Find repertoire move in MultiPV results
            rep_info = None
            for info in analysis_results:
                if 'pv' in info and info['pv'] and info['pv'][0].uci() == rep_move.uci:
                    rep_info = info
                    break

            # If repertoire move was not in top MultiPV, evaluate it specifically with root_moves
            if rep_info is None:
                try:
                    rep_eval_results = engine.analyse(
                        board,
                        chess.engine.Limit(depth=depth),
                        root_moves=[rep_chess_move]
                    )
                    if rep_eval_results:
                        rep_info = rep_eval_results[0]
                except Exception as e:
                    logger.debug(f"Direct eval of repertoire move {rep_move.uci} failed: {e}")

            if rep_info is not None:
                rep_eval_str, rep_eval_cp = format_score_to_str(rep_info['score'])
                rep_rel_score = rep_info['score'].relative.score(mate_score=10000)
            else:
                rep_eval_str, rep_eval_cp = "-9.99", -999 if board.turn == chess.WHITE else 999
                rep_rel_score = -10000

            # Calculate Pawn Loss
            # Positive loss means the player's move scored lower relative to the best move
            loss_cp = max(0, best_rel_score - rep_rel_score)
            loss_pawns = round(loss_cp / 100.0, 2)

            # Collect good moves for Position.good_moves (Alternate Moves Engine synergy)
            good_moves = [rep_move.uci]
            for info in analysis_results:
                if 'pv' not in info or not info['pv']:
                    continue
                cand_move = info['pv'][0]
                cand_rel = info['score'].relative.score(mate_score=10000)
                if (best_rel_score - cand_rel) <= 50:
                    if cand_move.uci() not in good_moves:
                        good_moves.append(cand_move.uci())

            # Update position in DB
            pos.good_moves = json.dumps(list(set(good_moves)))
            pos.analysis_depth = depth
            pos.engine_eval = best_eval_cp

            # Check if this move is a mistake (> threshold_pawns)
            if loss_cp > threshold_cp:
                # Extract PV text (up to 5 moves)
                pv_san_list = []
                temp_board = board.copy()
                for m in (best_info.get('pv') or [])[:5]:
                    try:
                        pv_san_list.append(temp_board.san(m))
                        temp_board.push(m)
                    except Exception:
                        break
                pv_str = " ".join(pv_san_list)

                mistake_data = {
                    "position_id": pos.id,
                    "fen": pos.fen,
                    "played_uci": rep_move.uci,
                    "played_san": rep_move.san,
                    "played_eval_str": rep_eval_str,
                    "played_eval_cp": rep_eval_cp,
                    "best_uci": best_uci,
                    "best_san": best_san,
                    "best_eval_str": best_eval_str,
                    "best_eval_cp": best_eval_cp,
                    "loss_cp": loss_cp,
                    "loss_pawns": loss_pawns,
                    "depth": depth,
                    "pv_str": pv_str
                }
                mistakes.append(mistake_data)
                if mistake_callback:
                    try:
                        mistake_callback(mistake_data)
                    except Exception:
                        pass

            # Progress notification
            if progress_callback:
                pct = int(((i + 1) / total_positions) * 100)
                progress_callback(i + 1, total_positions, pct)

            if (i + 1) % 10 == 0 or (i + 1) == total_positions:
                commit_with_retry(session)

        # Invalidate status cache
        set_meta(session, "ana_cache_count", "-1")
        commit_with_retry(session)

        # Sort mistakes by pawn loss descending (worst blunders first)
        mistakes.sort(key=lambda m: m["loss_pawns"], reverse=True)
        return True, f"Scan abgeschlossen: {len(mistakes)} Fehler mit > {threshold_pawns} Bauernverlust gefunden.", mistakes

    except Exception as e:
        session.rollback()
        logger.error(f"Error during repertoire mistake audit: {e}", exc_info=True)
        return False, f"Fehler bei der Analyse: {e}", mistakes
    finally:
        if engine:
            try:
                engine.quit()
            except Exception:
                pass
        session.close()
        db.close()
