import os
import json
from collections import deque, defaultdict
import chess
from typing import Tuple, Callable, Optional, Dict, List, Set
from sqlalchemy import or_
from sqlalchemy.orm import Session

from opening_fenix.core.db.models import Position, Move, RepertoireMove, LichessData, MovePriority
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.db.meta_utils import get_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path, parse_elo_list
from opening_fenix.core.services.lichess_service import ELO_MAPPING

_CASTLING_ALT = {
    'e1c1': 'e1a1',
    'e1g1': 'e1h1',
    'e8c8': 'e8a8',
    'e8g8': 'e8h8',
}


def _norm_fen4(fen: str) -> str:
    if not fen:
        return ""
    s = fen.strip()
    if s.count(" ") >= 5:
        return s.rsplit(" ", 2)[0]
    parts = s.split(" ")
    return " ".join(parts[:4])


def _compute_depths_topo(
    roots: List[int],
    outgoing_edges: Dict[int, List[int]],
    allowed_ids: Optional[Set[int]] = None,
) -> List[List[int]]:
    """Computes longest-path depth buckets in O(V + E) via Kahn's topological sort with cycle fallback."""
    reachable: Set[int] = set(roots)
    bfs_q = deque(roots)
    in_deg: Dict[int, int] = {r: 0 for r in roots}

    while bfs_q:
        pid = bfs_q.popleft()
        for to_id in outgoing_edges.get(pid, ()):
            if not to_id or (allowed_ids is not None and to_id not in allowed_ids):
                continue
            in_deg[to_id] = in_deg.get(to_id, 0) + 1
            if to_id not in reachable:
                reachable.add(to_id)
                bfs_q.append(to_id)

    pos_depths: Dict[int, int] = {r: 0 for r in roots}
    topo_q = deque(r for r in roots if in_deg.get(r, 0) == 0)
    processed: Set[int] = set()

    while topo_q:
        pid = topo_q.popleft()
        if pid in processed:
            continue
        processed.add(pid)
        curr_d = pos_depths.get(pid, 0)
        for to_id in outgoing_edges.get(pid, ()):
            if not to_id or to_id not in reachable:
                continue
            nd = curr_d + 1
            if nd > pos_depths.get(to_id, -1):
                pos_depths[to_id] = nd
            in_deg[to_id] -= 1
            if in_deg[to_id] <= 0 and to_id not in processed:
                topo_q.append(to_id)

    # Rare cycle fallback so cyclic graphs still resolve every reachable node
    if len(processed) < len(reachable):
        extra_d = (max(pos_depths.values()) + 1) if pos_depths else 0
        for pid in reachable:
            if pid not in pos_depths:
                pos_depths[pid] = extra_d

    max_d = max(pos_depths.values()) if pos_depths else 0
    buckets: List[List[int]] = [[] for _ in range(max_d + 1)]
    for pid, d in pos_depths.items():
        buckets[d].append(pid)
    return buckets


def sync_move_priorities_to_default_elo(session: Session, elo_category: str, keep_missing: bool = False) -> bool:
    """
    Copies precomputed MovePriority rows for `elo_category` onto Move.priority_score
    for instant default-Elo switching and backwards compatibility.
    If keep_missing is True, moves without a stored row keep their current score instead of 0.
    Returns True if MovePriority rows existed for `elo_category`.
    """
    if not elo_category:
        return False
    mp_rows = session.query(MovePriority.move_id, MovePriority.priority_score).filter_by(elo_range=elo_category).all()
    if not mp_rows:
        return False
    score_map = {m_id: (prio or 0.0) for m_id, prio in mp_rows}
    all_moves = session.query(Move.id, Move.priority_score).all()
    updates = []
    for m_id, old_prio in all_moves:
        if keep_missing and m_id not in score_map:
            continue
        target = score_map.get(m_id, 0.0)
        if old_prio is None or old_prio != target:
            updates.append({'id': m_id, 'priority_score': target})
    if updates:
        for i in range(0, len(updates), 2000):
            session.bulk_update_mappings(Move, updates[i:i + 2000])
    return True


def _upsert_move_priorities(session: Session, elo_category: str, scores_by_move_id: Dict[int, float]) -> None:
    """Bulk-upserts MovePriority entries for a given elo_category."""
    if not elo_category or not scores_by_move_id:
        return
    move_ids = list(scores_by_move_id.keys())
    existing_map: Dict[int, Tuple[int, float]] = {}
    chunk_size = 900
    for i in range(0, len(move_ids), chunk_size):
        chunk = move_ids[i:i + chunk_size]
        for row_id, m_id, old_score in session.query(
            MovePriority.id, MovePriority.move_id, MovePriority.priority_score
        ).filter(MovePriority.elo_range == elo_category, MovePriority.move_id.in_(chunk)).all():
            existing_map[m_id] = (row_id, old_score)

    to_update = []
    to_insert = []
    for m_id, score in scores_by_move_id.items():
        if m_id in existing_map:
            row_id, old_score = existing_map[m_id]
            if old_score is None or old_score != score:
                to_update.append({'id': row_id, 'priority_score': score})
        else:
            to_insert.append({'move_id': m_id, 'elo_range': elo_category, 'priority_score': score})

    if to_update:
        for i in range(0, len(to_update), 2000):
            session.bulk_update_mappings(MovePriority, to_update[i:i + 2000])
    if to_insert:
        for i in range(0, len(to_insert), 2000):
            session.bulk_insert_mappings(MovePriority, to_insert[i:i + 2000])


def calculate_priority_scores(
    repo_name: str,
    elo_category: str,
    progress_callback: Optional[Callable[[int], None]] = None,
    check_cancel: Optional[Callable[[], bool]] = None,
    update_move_column: Optional[bool] = None,
) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    try:
        all_moves_rows = session.query(
            Move.id, Move.from_position_id, Move.to_position_id, Move.uci, Move.san, Move.priority_score
        ).all()
        rep_move_ids = {
            rm_id for (rm_id,) in session.query(RepertoireMove.move_id).filter_by(is_active=True).all()
        }

        outgoing_moves_cache: Dict[int, list] = defaultdict(list)
        outgoing_targets: Dict[int, List[int]] = defaultdict(list)
        incoming_pos_ids: Set[int] = set()
        for row in all_moves_rows:
            m_id, from_id, to_id, uci, san, old_prio = row
            outgoing_moves_cache[from_id].append((m_id, to_id, uci, san))
            if to_id:
                outgoing_targets[from_id].append(to_id)
                incoming_pos_ids.add(to_id)

        all_positions_info = session.query(Position.id, Position.fen).all()
        id_to_clean_fen: Dict[int, str] = {}
        start_pos_id = None
        start_fen_normalized = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        for pid, fen in all_positions_info:
            if fen:
                cf = _norm_fen4(fen)
                id_to_clean_fen[pid] = cf
                if start_pos_id is None and cf == start_fen_normalized:
                    start_pos_id = pid
            else:
                id_to_clean_fen[pid] = ""

        if start_pos_id is not None:
            roots = [start_pos_id]
        else:
            roots = [pid for pid in id_to_clean_fen if pid not in incoming_pos_ids]

        if not roots:
            if id_to_clean_fen:
                roots = [min(id_to_clean_fen.keys())]
            else:
                return False, "Database contains no positions."

        positions_by_depth = _compute_depths_topo(roots, outgoing_targets)

        id_probabilities: Dict[int, float] = {root_id: 1.0 for root_id in roots}
        new_scores: Dict[int, float] = {}

        lichess_rows = session.query(LichessData.fen, LichessData.moves_json).filter_by(elo_range=elo_category).all()
        lichess_data_cache: Dict[str, dict] = {}
        for ld_fen, ld_json in lichess_rows:
            if ld_fen and ld_json:
                lichess_data_cache[_norm_fen4(ld_fen)] = json.loads(ld_json)

        user_turn_char = get_meta(session, "color", "w")
        user_turn_marker = f" {user_turn_char} "

        total_depths = len(positions_by_depth)
        for depth, pos_ids in enumerate(positions_by_depth):
            if check_cancel and check_cancel():
                session.rollback()
                return False, "Calculation cancelled."

            for pos_id in pos_ids:
                current_prob = id_probabilities.get(pos_id, 0.0)
                if current_prob == 0.0:
                    continue

                clean_pos_fen = id_to_clean_fen.get(pos_id)
                if not clean_pos_fen:
                    continue

                is_user_turn = user_turn_marker in clean_pos_fen
                all_outgoing_moves = outgoing_moves_cache.get(pos_id)
                if not all_outgoing_moves:
                    continue

                if is_user_turn:
                    for m_id, to_id, _uci, _san in all_outgoing_moves:
                        if m_id in rep_move_ids:
                            new_scores[m_id] = current_prob
                            if to_id and current_prob > id_probabilities.get(to_id, 0.0):
                                id_probabilities[to_id] = current_prob
                else:
                    lichess_move_data = lichess_data_cache.get(clean_pos_fen) or {}
                    total_from_lichess = sum(m_info.get('total', 0) for m_info in lichess_move_data.values()) if lichess_move_data else 0

                    moves_with_stats = []
                    rare_moves_with_weights = []

                    for m_id, to_id, uci, san in all_outgoing_moves:
                        lichess_info = lichess_move_data.get(uci) or lichess_move_data.get(san)
                        if not lichess_info:
                            alt_uci = _CASTLING_ALT.get(uci)
                            if alt_uci:
                                lichess_info = lichess_move_data.get(alt_uci)

                        if lichess_info and lichess_info.get('total', 0) > 0:
                            moves_with_stats.append((m_id, to_id, lichess_info['total']))
                        else:
                            weight = 1
                            if to_id:
                                clean_child_fen = id_to_clean_fen.get(to_id)
                                if clean_child_fen:
                                    child_data = lichess_data_cache.get(clean_child_fen)
                                    if child_data:
                                        w_sum = sum(m_info.get('total', 0) for m_info in child_data.values())
                                        if w_sum > 1:
                                            weight = w_sum
                            rare_moves_with_weights.append((m_id, to_id, weight))

                    if moves_with_stats:
                        min_lichess_total = min(tot for _, _, tot in moves_with_stats)
                        rare_moves_with_weights = [(m_id, to_id, min(w, min_lichess_total)) for m_id, to_id, w in rare_moves_with_weights]

                    total_rare_weight = sum(w for _, _, w in rare_moves_with_weights)
                    effective_total = total_from_lichess + total_rare_weight

                    if effective_total > 0:
                        inv_total = current_prob / effective_total
                        for m_id, to_id, tot in moves_with_stats:
                            next_prob = tot * inv_total
                            new_scores[m_id] = next_prob
                            if to_id and next_prob > id_probabilities.get(to_id, 0.0):
                                id_probabilities[to_id] = next_prob

                        for m_id, to_id, weight in rare_moves_with_weights:
                            next_prob = weight * inv_total
                            new_scores[m_id] = next_prob
                            if to_id and next_prob > id_probabilities.get(to_id, 0.0):
                                id_probabilities[to_id] = next_prob
                    else:
                        split_prob = current_prob / len(all_outgoing_moves)
                        for m_id, to_id, _uci, _san in all_outgoing_moves:
                            new_scores[m_id] = split_prob
                            if to_id and split_prob > id_probabilities.get(to_id, 0.0):
                                id_probabilities[to_id] = split_prob

            if progress_callback:
                progress_callback(int((depth + 1) * 100 / total_depths))

        # Always store per-Elo priorities in move_priorities for instant multi-Elo switching
        all_target_scores = {m_id: new_scores.get(m_id, 0.0) for m_id, _, _, _, _, _ in all_moves_rows}
        _upsert_move_priorities(session, elo_category, all_target_scores)

        # Sync Move.priority_score if requested or if elo_category is the course's primary/default Elo
        if update_move_column is None:
            primary_elo = get_meta(session, "lichess_elo") or get_meta(session, "elo")
            should_sync_moves = (not primary_elo) or (primary_elo == elo_category)
        else:
            should_sync_moves = bool(update_move_column)

        if should_sync_moves:
            updates = []
            for m_id, _from_id, _to_id, _uci, _san, old_prio in all_moves_rows:
                target_prio = all_target_scores.get(m_id, 0.0)
                if old_prio is None or old_prio != target_prio:
                    updates.append({'id': m_id, 'priority_score': target_prio})

            if updates:
                for i in range(0, len(updates), 2000):
                    session.bulk_update_mappings(Move, updates[i:i + 2000])
        commit_with_retry(session)
        return True, "Priority scores calculated successfully."

    except Exception as e:
        session.rollback()
        import traceback
        print(traceback.format_exc())
        return False, f"Error calculating priority scores: {e}"
    finally:
        session.close()
        db.close()

def calculate_local_priority_scores(session: Session, start_pos_id: int, elo_category: str) -> Tuple[bool, str]:
    """
    Recomputes priority scores for the subtree below `start_pos_id`.
    For multi-Elo courses, every additional Elo with stored priorities is refreshed too
    (its scores are swapped into Move.priority_score, recalculated, then the primary Elo is restored).
    """
    ok, msg = _calculate_local_priority_scores_single(session, start_pos_id, elo_category)
    if not ok:
        return ok, msg
    try:
        elos = parse_elo_list(get_meta(session, "lichess_elos", "") or "")
    except Exception:
        elos = []
    others = [e for e in elos if e != elo_category]
    if not others:
        return ok, msg

    session.flush()
    swapped = False
    try:
        for other in others:
            session.flush()
            if not sync_move_priorities_to_default_elo(session, other, keep_missing=True):
                continue
            swapped = True
            session.expire_all()
            _calculate_local_priority_scores_single(session, start_pos_id, other)
    finally:
        if swapped:
            session.flush()
            sync_move_priorities_to_default_elo(session, elo_category, keep_missing=True)
            session.expire_all()
    return ok, msg


def _calculate_local_priority_scores_single(session: Session, start_pos_id: int, elo_category: str) -> Tuple[bool, str]:
    try:
        start_pos = session.get(Position, start_pos_id)
        if not start_pos:
            return False, "Position not found."

        incoming_moves = session.query(Move).filter_by(to_position_id=start_pos_id).all()
        start_fen_normalized = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
        clean_start_fen = " ".join(start_pos.fen.split(" ")[:4])
        
        if clean_start_fen == start_fen_normalized or not incoming_moves:
            start_prob = 1.0
        else:
            start_prob = max(((m.priority_score or 0.0) for m in incoming_moves), default=0.0)
            
        if start_prob <= 0 and clean_start_fen != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR":
            return True, "No probability to propagate."

        user_turn_char = get_meta(session, "color", "w")

        # ── Fast-path: evaluate immediate outgoing moves of start_pos_id first ──
        # Only traverse descendant subtrees whose incoming move probability actually changed
        # or that have uninitialized outgoing moves.
        start_out_moves = session.query(Move).filter_by(from_position_id=start_pos_id).all()
        if not start_out_moves:
            return True, "Local priority scores updated."

        old_scores = {m.id: m.priority_score for m in start_out_moves}
        new_scores = {}
        is_start_user_turn = clean_start_fen.split(" ")[1] == user_turn_char

        if is_start_user_turn:
            active_rep_ids = {
                rm_id for (rm_id,) in session.query(RepertoireMove.move_id)
                .filter(RepertoireMove.move_id.in_([m.id for m in start_out_moves]), RepertoireMove.is_active == True)
                .all()
            }
            for m in start_out_moves:
                new_scores[m.id] = start_prob if m.id in active_rep_ids else 0.0
        else:
            ld_row = session.query(LichessData).filter_by(fen=clean_start_fen, elo_range=elo_category).first()
            lichess_move_data = json.loads(ld_row.moves_json) if (ld_row and ld_row.moves_json) else {}
            total_from_lichess = sum(m_info.get('total', 0) for m_info in lichess_move_data.values())

            moves_with_stats = []
            missing_rare_moves = []
            for m in start_out_moves:
                info = lichess_move_data.get(m.uci) or lichess_move_data.get(m.san)
                if not info:
                    alt_uci = _CASTLING_ALT.get(m.uci)
                    if alt_uci:
                        info = lichess_move_data.get(alt_uci)
                if info and info.get('total', 0) > 0:
                    moves_with_stats.append((m, info))
                else:
                    missing_rare_moves.append(m)

            rare_moves_with_weights = []
            if missing_rare_moves:
                rare_child_ids = list({m.to_position_id for m in missing_rare_moves if m.to_position_id})
                child_clean_fens = {}
                if rare_child_ids:
                    for pid, p_fen in session.query(Position.id, Position.fen).filter(Position.id.in_(rare_child_ids)).all():
                        if p_fen:
                            child_clean_fens[pid] = _norm_fen4(p_fen)
                child_ld_map = {}
                unique_child_fens = list(set(child_clean_fens.values()))
                if unique_child_fens:
                    for ld_fen, ld_json in session.query(LichessData.fen, LichessData.moves_json).filter(
                        LichessData.fen.in_(unique_child_fens), LichessData.elo_range == elo_category
                    ).all():
                        if ld_json:
                            child_data = json.loads(ld_json)
                            child_ld_map[_norm_fen4(ld_fen)] = max(1, sum(mi.get('total', 0) for mi in child_data.values()))
                for m in missing_rare_moves:
                    cf = child_clean_fens.get(m.to_position_id, "")
                    weight = child_ld_map.get(cf, 1)
                    rare_moves_with_weights.append((m, weight))

            if moves_with_stats:
                min_lichess_total = min(stats['total'] for _, stats in moves_with_stats)
                rare_moves_with_weights = [(m, min(w, min_lichess_total)) for m, w in rare_moves_with_weights]

            total_rare_weight = sum(w for _, w in rare_moves_with_weights)
            effective_total = total_from_lichess + total_rare_weight
            if effective_total > 0:
                for m, stats in moves_with_stats:
                    new_scores[m.id] = start_prob * (stats['total'] / effective_total)
                for m, weight in rare_moves_with_weights:
                    new_scores[m.id] = start_prob * (weight / effective_total)
            else:
                split_prob = start_prob / len(start_out_moves)
                for m in start_out_moves:
                    new_scores[m.id] = split_prob

        child_ids = [m.to_position_id for m in start_out_moves if m.to_position_id]
        uninit_children = set()
        if child_ids:
            uninit_children = {
                pid for (pid,) in session.query(Move.from_position_id)
                .filter(Move.from_position_id.in_(child_ids), Move.priority_score.is_(None))
                .distinct().all()
            }

        seed_child_ids = set()
        any_start_move_dirty = False
        for m in start_out_moves:
            ns = new_scores[m.id]
            os_val = old_scores[m.id]
            if os_val is None or abs(os_val - ns) > 1e-9:
                m.priority_score = ns
                any_start_move_dirty = True
                if m.to_position_id:
                    seed_child_ids.add(m.to_position_id)
            elif m.to_position_id in uninit_children:
                seed_child_ids.add(m.to_position_id)

        if not seed_child_ids:
            if any_start_move_dirty:
                _upsert_move_priorities(session, elo_category, {m.id: (m.priority_score or 0.0) for m in start_out_moves})
                session.flush()
            return True, "Local priority scores updated."

        # ── 1. Discover reachable descendant IDs safely using chunked BFS (avoids SQL string interpolation) ──
        reachable_ids: Set[int] = set(seed_child_ids)
        frontier = list(seed_child_ids)
        chunk_size = 900
        while frontier:
            next_frontier = []
            for i in range(0, len(frontier), chunk_size):
                chunk = frontier[i:i + chunk_size]
                for (to_id,) in session.query(Move.to_position_id).filter(
                    Move.from_position_id.in_(chunk),
                    Move.to_position_id.isnot(None)
                ).all():
                    if to_id not in reachable_ids:
                        reachable_ids.add(to_id)
                        next_frontier.append(to_id)
            frontier = next_frontier

        if not reachable_ids:
            if any_start_move_dirty:
                session.flush()
            return True, "Local priority scores updated."
        
        # ── 2. Bulk fetch all relevant Moves efficiently (handling SQLite limits) ──
        all_moves_in_subtree = []
        seen_move_ids = set()
        reachable_list = list(reachable_ids)
        for i in range(0, len(reachable_list), chunk_size):
            chunk = reachable_list[i:i + chunk_size]
            moves_chunk = (
                session.query(Move)
                .filter(or_(Move.from_position_id.in_(chunk), Move.to_position_id.in_(chunk)))
                .all()
            )
            for m in moves_chunk:
                if m.id not in seen_move_ids:
                    all_moves_in_subtree.append(m)
                    seen_move_ids.add(m.id)
            
        # Build memory models
        outgoing_moves_cache = {pid: [] for pid in reachable_ids}
        outgoing_targets_local: Dict[int, List[int]] = defaultdict(list)
        incoming_moves_cache = {pid: [] for pid in reachable_ids}
        
        for m in all_moves_in_subtree:
            if m.from_position_id in outgoing_moves_cache:
                outgoing_moves_cache[m.from_position_id].append(m)
                if m.to_position_id:
                    outgoing_targets_local[m.from_position_id].append(m.to_position_id)
            if m.to_position_id in incoming_moves_cache:
                incoming_moves_cache[m.to_position_id].append(m)

        # ── 3. Build topological depth buckets in O(V + E) ──
        local_roots = [cid for cid in seed_child_ids if cid in reachable_ids]
        subtree_positions_by_depth = _compute_depths_topo(local_roots, outgoing_targets_local, allowed_ids=reachable_ids)
        
        id_probabilities = {pid: 0.0 for pid in reachable_ids}
        for pid in reachable_ids:
            incoming = incoming_moves_cache.get(pid, [])
            ext_prob = max(((m.priority_score or 0.0) for m in incoming if m.from_position_id not in reachable_ids), default=0.0)
            id_probabilities[pid] = ext_prob

        rep_moves_db = session.query(RepertoireMove.move_id).filter_by(is_active=True).all()
        rep_move_ids = {rm.move_id for rm in rep_moves_db}
        
        reachable_pos = []
        reachable_ids_list = list(reachable_ids)
        chunk_size = 900
        for i in range(0, len(reachable_ids_list), chunk_size):
            chunk = reachable_ids_list[i:i + chunk_size]
            reachable_pos.extend(session.query(Position.id, Position.fen).filter(Position.id.in_(chunk)).all())

        id_to_fen_dict = {p.id: p.fen for p in reachable_pos}
        reachable_clean_fens = list({" ".join(p.fen.split(" ")[:4]) for p in reachable_pos})
        
        lichess_data_cache = {}
        for i in range(0, len(reachable_clean_fens), chunk_size):
            chunk = reachable_clean_fens[i:i + chunk_size]
            for ld in session.query(LichessData).filter(LichessData.fen.in_(chunk), LichessData.elo_range == elo_category).all():
                lichess_data_cache[" ".join(ld.fen.split(" ")[:4])] = json.loads(ld.moves_json)

        for depth_list in subtree_positions_by_depth:
            for pos_id in depth_list:
                current_prob = id_probabilities.get(pos_id, 0.0)
                if current_prob <= 0: continue
                
                fen = id_to_fen_dict.get(pos_id)
                if not fen: continue
                clean_fen = " ".join(fen.split(" ")[:4])
                is_user_turn = clean_fen.split(" ")[1] == user_turn_char
                
                out_moves = outgoing_moves_cache.get(pos_id, [])
                if not out_moves: continue
                
                if is_user_turn:
                    user_rep_moves = [m for m in out_moves if m.id in rep_move_ids]
                    # Reset all outgoing moves to 0 first to handle moves becoming inactive
                    for m in out_moves:
                        m.priority_score = 0.0
                    
                    if user_rep_moves:
                        for m in user_rep_moves:
                            m.priority_score = current_prob
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] = max(
                                    id_probabilities[m.to_position_id],
                                    current_prob
                                )
                    # No else needed as all were reset to 0.0 above
                else:
                    # LICESS DATA & TOTAL GAMES LOGIC
                    lichess_move_data = lichess_data_cache.get(clean_fen) or {}
                    total_from_lichess = sum(m_info.get('total', 0) for m_info in lichess_move_data.values())
                    
                    moves_with_stats = []
                    rare_moves_with_weights = []
                    
                    for m in out_moves:
                        info = lichess_move_data.get(m.uci) or lichess_move_data.get(m.san)
                        if not info:
                            alt_uci = None
                            if m.uci == 'e1c1': alt_uci = 'e1a1'
                            elif m.uci == 'e1g1': alt_uci = 'e1h1'
                            elif m.uci == 'e8c8': alt_uci = 'e8a8'
                            elif m.uci == 'e8g8': alt_uci = 'e8h8'
                            if alt_uci: info = lichess_move_data.get(alt_uci)
                        
                        if info and info.get('total', 0) > 0:
                            moves_with_stats.append((m, info))
                        else:
                            # BACK-PROPAGATION: Check if child position has Lichess data
                            weight = 1
                            if m.to_position_id:
                                child_fen = id_to_fen_dict.get(m.to_position_id)
                                if child_fen:
                                    clean_child_fen = " ".join(child_fen.split(" ")[:4])
                                    child_data = lichess_data_cache.get(clean_child_fen)
                                    if child_data:
                                        weight = sum(m_info.get('total', 0) for m_info in child_data.values())
                                        if weight < 1: weight = 1
                            rare_moves_with_weights.append((m, weight))
                    
                    if moves_with_stats:
                        min_lichess_total = min(stats['total'] for _, stats in moves_with_stats)
                        rare_moves_with_weights = [(m, min(w, min_lichess_total)) for m, w in rare_moves_with_weights]
                    
                    # TOTAL GAMES = SUM(LICHESS TOP 12) + SUM(PROPAGATED RARE WEIGHTS)
                    total_rare_weight = sum(w for m, w in rare_moves_with_weights)
                    effective_total = total_from_lichess + total_rare_weight
                    
                    if effective_total > 0:
                        for m, stats in moves_with_stats:
                            share = stats['total'] / effective_total
                            next_p = current_prob * share
                            m.priority_score = next_p
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] = max(
                                    id_probabilities[m.to_position_id],
                                    next_p
                                )
                        
                        for m, weight in rare_moves_with_weights:
                            share = weight / effective_total
                            next_p = current_prob * share
                            m.priority_score = next_p
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] = max(
                                    id_probabilities[m.to_position_id],
                                    next_p
                                )
                        continue

                    # Fallback for no data
                    if out_moves:
                        split_prob = current_prob / len(out_moves)
                        for m in out_moves:
                            m.priority_score = split_prob
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] = max(
                                    id_probabilities[m.to_position_id],
                                    split_prob
                                )

        updated_mp = {m.id: (m.priority_score or 0.0) for m in start_out_moves}
        for m in all_moves_in_subtree:
            if m.from_position_id in reachable_ids:
                updated_mp[m.id] = m.priority_score or 0.0
        _upsert_move_priorities(session, elo_category, updated_mp)
        session.flush()
        return True, "Local priority scores updated."

    except Exception as e:
        print(f"Error in calculate_local_priority_scores: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)

def detect_islands(repo_name: str) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    try:
        all_pos_query = session.query(Position.id, Position.fen).all()
        all_pos_ids = {p_id for p_id, _ in all_pos_query}
        id_to_fen = {p_id: f for p_id, f in all_pos_query}

        if not all_pos_ids:
            return True, "Database contains no positions."

        start_board = chess.Board()
        start_fen = " ".join(start_board.fen().split(" ")[:4])
        start_pos = session.query(Position).filter(Position.fen == start_fen).one_or_none()
        if not start_pos:
            start_pos = session.query(Position).order_by(Position.id).first()

        if not start_pos:
            return False, "Could not determine a starting position."

        reachable_pos_ids = set()
        queue = deque([start_pos.id])
        visited_bfs = {start_pos.id}
        
        user_turn_char = get_meta(session, "color", "w")
        dead_end_user_turns = []

        # Pre-fetch move graph and repertoire move IDs in bulk to avoid N+1 queries during BFS
        all_moves_rows = session.query(Move.id, Move.from_position_id, Move.to_position_id).all()
        rep_move_ids = {rm_mid for (rm_mid,) in session.query(RepertoireMove.move_id).all()}

        outgoing_by_pos = {}
        user_rep_by_pos = {}
        for m_id, from_id, to_id in all_moves_rows:
            outgoing_by_pos.setdefault(from_id, []).append(to_id)
            if m_id in rep_move_ids:
                user_rep_by_pos.setdefault(from_id, []).append(to_id)

        while queue:
            pos_id = queue.popleft()
            reachable_pos_ids.add(pos_id)
            
            fen = id_to_fen.get(pos_id, "")
            is_user_turn = fen.split(" ")[1] == user_turn_char

            if is_user_turn:
                user_to_ids = user_rep_by_pos.get(pos_id)
                if user_to_ids:
                    for to_pos_id in user_to_ids:
                        if to_pos_id and to_pos_id not in visited_bfs:
                            visited_bfs.add(to_pos_id)
                            queue.append(to_pos_id)
                else:
                    dead_end_user_turns.append(pos_id)
            else:
                for to_pos_id in outgoing_by_pos.get(pos_id, ()):
                    if to_pos_id and to_pos_id not in visited_bfs:
                        visited_bfs.add(to_pos_id)
                        queue.append(to_pos_id)

        unreachable_ids = all_pos_ids - reachable_pos_ids

        report_lines = []
        if not unreachable_ids and not dead_end_user_turns:
            return True, f"No islands or probability dead ends detected.\nAll {len(all_pos_ids)} positions are reachable."

        if dead_end_user_turns:
            report_lines.append(f"Detected {len(dead_end_user_turns)} probability dead ends:")
            report_lines.append("These are positions where it is your turn, but no repertoire move is defined.")
            for pos_id in dead_end_user_turns[:20]: 
                fen = id_to_fen.get(pos_id, "N/A")
                report_lines.append(f"  - FEN: {fen}")
            if len(dead_end_user_turns) > 20:
                report_lines.append(f"  ... and {len(dead_end_user_turns) - 20} more.")
            report_lines.append("-" * 20)

        if unreachable_ids:
            report_lines.append(f"Detected {len(unreachable_ids)} unreachable 'island' positions.")
            report_lines.append("These positions are in the database but cannot be reached from the starting position.")
            
            for i, pos_id in enumerate(list(unreachable_ids)[:5]):
                fen = id_to_fen.get(pos_id, "N/A")
                report_lines.append(f"  - Example FEN: {fen}")
            if len(unreachable_ids) > 5:
                report_lines.append(f"  ... and {len(unreachable_ids) - 5} more.")

        return True, "\n".join(report_lines)

    except Exception as e:
        import traceback
        return False, f"Error detecting islands: {e}\n{traceback.format_exc()}"
    finally:
        session.close()
        db.close()
