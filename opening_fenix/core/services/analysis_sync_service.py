"""
Analysis Sync Service.
Synchronizes alternate moves engine analysis (good_moves, analysis_depth, engine_eval)
from other repertoires/courses when positions have already been evaluated at an equal
or higher depth.
"""

import os
import json
import sqlite3
from typing import Optional, Callable, Dict, List, Tuple

from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import commit_with_retry
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.services.repertoire_service import RepertoireService
from opening_fenix.core.logger import logger


def normalize_fen(fen: str) -> str:
    """Returns the board, turn, castling rights, and en-passant square (first 4 FEN components)."""
    if not fen:
        return ""
    return " ".join(fen.strip().split()[:4])


def sync_analysis_data_from_other_repertoires(
    target_session,
    current_repo_name: str,
    target_depth: int,
    player_color: str = "w",
    check_cancel: Optional[Callable[[], bool]] = None,
    status_callback: Optional[Callable[[str], None]] = None
) -> int:
    """
    Scans other course databases for matching FEN positions where analysis_depth >= target_depth.
    When a position exists in another course at an equal or higher depth, its good_moves,
    analysis_depth, and engine_eval are adopted into target_session. If multiple courses have
    the position, the one with the highest analysis depth is chosen.
    
    Returns the number of positions successfully updated from other courses.
    """
    turn_filter = Position.fen.like(f'% {player_color} %')
    positions_needing_analysis = target_session.query(Position).filter(
        turn_filter,
        (Position.analysis_depth == None) | (Position.analysis_depth < target_depth)
    ).all()

    if not positions_needing_analysis:
        return 0

    fen_to_positions: Dict[str, List[Position]] = {}
    for pos in positions_needing_analysis:
        norm = normalize_fen(pos.fen)
        if norm:
            fen_to_positions.setdefault(norm, []).append(pos)

    if not fen_to_positions:
        return 0

    try:
        all_repos = RepertoireService().get_all_repertoires()
    except Exception as e:
        logger.warning(f"[Analysis Cross-Sync] Failed to list repertoires: {e}")
        return 0

    other_repos = [r for r in all_repos if r != current_repo_name]
    if not other_repos:
        return 0

    if status_callback:
        status_callback(f"Prüfe {len(other_repos)} andere Kurse auf vorhandene Analysen...")

    # best_match maps norm_fen -> (depth, good_moves_json, engine_eval)
    best_match: Dict[str, Tuple[int, str, Optional[int]]] = {}

    for other_repo in other_repos:
        if check_cancel and check_cancel():
            break

        other_db_path = get_repertoire_db_path(other_repo)
        if not os.path.exists(other_db_path):
            continue

        try:
            conn = sqlite3.connect(other_db_path, timeout=5.0)
            cursor = conn.cursor()

            # Ensure table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
            if not cursor.fetchone():
                conn.close()
                continue

            cursor.execute("PRAGMA table_info(positions)")
            cols = [row[1] for row in cursor.fetchall()]
            if 'analysis_depth' not in cols or 'good_moves' not in cols or 'fen' not in cols:
                conn.close()
                continue

            has_eval = 'engine_eval' in cols
            select_eval = ", engine_eval" if has_eval else ", NULL"

            query = (
                f"SELECT fen, analysis_depth, good_moves{select_eval} "
                f"FROM positions WHERE analysis_depth IS NOT NULL "
                f"AND analysis_depth >= ? AND good_moves IS NOT NULL"
            )
            cursor.execute(query, (target_depth,))
            rows = cursor.fetchall()
            conn.close()

            for r_fen, r_depth, r_gm, r_eval in rows:
                if not r_fen or not r_gm:
                    continue
                norm = normalize_fen(r_fen)
                if norm in fen_to_positions:
                    # Validate good_moves is valid JSON list
                    try:
                        parsed = json.loads(r_gm)
                        if not isinstance(parsed, list):
                            continue
                    except Exception:
                        continue

                    # Select highest depth if multiple courses have this position
                    prev_best = best_match.get(norm)
                    if prev_best is None or r_depth > prev_best[0]:
                        best_match[norm] = (r_depth, r_gm, r_eval)

        except Exception as e:
            logger.debug(f"[Analysis Cross-Sync] Error reading repo '{other_repo}': {e}")
            continue

    if not best_match:
        return 0

    copied_count = 0
    for norm_fen, (best_depth, best_gm_json, best_eval) in best_match.items():
        if check_cancel and check_cancel():
            break

        try:
            cand_moves = json.loads(best_gm_json)
        except Exception:
            continue

        for pos in fen_to_positions.get(norm_fen, []):
            # Check current course's repertoire move to preserve it
            rep_move = (
                target_session.query(Move)
                .join(RepertoireMove, Move.id == RepertoireMove.move_id)
                .filter(Move.from_position_id == pos.id)
                .first()
            )
            rep_uci = rep_move.uci if rep_move else None

            merged_moves = list(cand_moves)
            if rep_uci and rep_uci not in merged_moves:
                merged_moves.append(rep_uci)

            pos.good_moves = json.dumps(list(set(merged_moves)))
            pos.analysis_depth = best_depth
            if best_eval is not None:
                pos.engine_eval = best_eval

            copied_count += 1

    if copied_count > 0:
        try:
            commit_with_retry(target_session)
            logger.info(
                f"[Analysis Cross-Sync] Successfully copied analysis for {copied_count} "
                f"positions into '{current_repo_name}' (min depth: {target_depth})."
            )
        except Exception as e:
            target_session.rollback()
            logger.error(f"[Analysis Cross-Sync] Failed to commit copied analyses: {e}")
            return 0

    return copied_count
