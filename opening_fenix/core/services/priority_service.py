import os
import json
from collections import deque
import chess
from typing import Tuple, Callable, Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session

from opening_fenix.core.db.models import Position, Move, RepertoireMove, LichessData
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.db.meta_utils import get_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path
from opening_fenix.core.services.lichess_service import ELO_MAPPING

def calculate_priority_scores(repo_name: str, elo_category: str, progress_callback: Optional[Callable[[int], None]] = None, check_cancel: Optional[Callable[[], bool]] = None) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    try:
        session.query(Move).update({Move.priority_score: 0.0})
        session.flush()

        all_moves_db = session.query(Move).all()
        rep_moves_db = session.query(RepertoireMove.move_id).filter_by(is_active=True).all()
        rep_move_ids = {rm.move_id for rm in rep_moves_db}
        
        outgoing_moves_cache = {}
        for move in all_moves_db:
            if move.from_position_id not in outgoing_moves_cache:
                outgoing_moves_cache[move.from_position_id] = []
            outgoing_moves_cache[move.from_position_id].append(move)

        all_positions_info = session.query(Position.id, Position.fen).all()
        id_to_fen = {p.id: p.fen for p in all_positions_info}
        
        incoming_pos_ids = set()
        for move in all_moves_db:
            if move.to_position_id:
                incoming_pos_ids.add(move.to_position_id)
        
        start_board = chess.Board()
        start_fen_normalized = " ".join(start_board.fen().split(" ")[:4])
        
        start_pos_id = None
        for pid, fen in id_to_fen.items():
            clean_f = " ".join(fen.split(" ")[:4])
            if clean_f == start_fen_normalized:
                start_pos_id = pid
                break
        
        if start_pos_id is not None:
            roots = [start_pos_id]
        else:
            roots = [pid for pid in id_to_fen.keys() if pid not in incoming_pos_ids]
            
        if not roots:
            if id_to_fen:
                roots = [min(id_to_fen.keys())]
            else:
                session.close()
                db.close()
                return False, "Database contains no positions."

        pos_depths = {root_id: 0 for root_id in roots}
        visit_count = {root_id: 1 for root_id in roots}
        queue = deque(roots)

        while queue:
            pos_id = queue.popleft()
            curr_d = pos_depths[pos_id]

            outgoing_moves = outgoing_moves_cache.get(pos_id, [])
            for move in outgoing_moves:
                to_id = move.to_position_id
                if to_id:
                    new_d = curr_d + 1
                    if to_id not in pos_depths or new_d > pos_depths[to_id]:
                        pos_depths[to_id] = new_d
                        vc = visit_count.get(to_id, 0) + 1
                        visit_count[to_id] = vc
                        if vc <= 100:  # Prevent infinite loops in case of cyclic graphs
                            queue.append(to_id)

        max_d = max(pos_depths.values()) if pos_depths else 0
        positions_by_depth = [[] for _ in range(max_d + 1)]
        for pid, d in pos_depths.items():
            positions_by_depth[d].append(pid)

        id_probabilities = {pos_id: 0.0 for pos_id in id_to_fen.keys()}
        for root_id in roots:
            id_probabilities[root_id] = 1.0

        lichess_data_cache = {" ".join(ld.fen.split(" ")[:4]): json.loads(ld.moves_json) for ld in session.query(LichessData).filter_by(elo_range=elo_category).all()}

        user_turn_char = get_meta(session, "color", "w")

        total_depths = len(positions_by_depth)
        for depth, pos_ids in enumerate(positions_by_depth):
            if check_cancel and check_cancel():
                session.rollback()
                return False, "Calculation cancelled."

            for pos_id in pos_ids:
                current_prob = id_probabilities.get(pos_id, 0.0)
                if current_prob == 0.0:
                    continue
                
                position_fen = id_to_fen.get(pos_id)
                if not position_fen: continue
                
                clean_pos_fen = " ".join(position_fen.split(" ")[:4])
                is_user_turn = clean_pos_fen.split(" ")[1] == user_turn_char
                
                all_outgoing_moves = outgoing_moves_cache.get(pos_id, [])
                
                if is_user_turn:
                    user_repertoire_moves = [m for m in all_outgoing_moves if m.id in rep_move_ids]

                    if user_repertoire_moves:
                        split_prob = current_prob / len(user_repertoire_moves)
                        for user_move in user_repertoire_moves:
                            user_move.priority_score = split_prob
                            if user_move.to_position_id:
                                id_probabilities[user_move.to_position_id] = id_probabilities.get(user_move.to_position_id, 0.0) + split_prob

                else:
                    if not all_outgoing_moves:
                        continue

                    # LICESS DATA & TOTAL GAMES LOGIC
                    lichess_move_data = lichess_data_cache.get(clean_pos_fen) or {}
                    total_from_lichess = sum(m_info.get('total', 0) for m_info in lichess_move_data.values())
                    
                    moves_with_stats = []
                    rare_moves_with_weights = []
                    
                    for move in all_outgoing_moves:
                        lichess_info = lichess_move_data.get(move.uci) or lichess_move_data.get(move.san)
                        if not lichess_info:
                            alt_uci = None
                            if move.uci == 'e1c1': alt_uci = 'e1a1'
                            elif move.uci == 'e1g1': alt_uci = 'e1h1'
                            elif move.uci == 'e8c8': alt_uci = 'e8a8'
                            elif move.uci == 'e8g8': alt_uci = 'e8h8'
                            if alt_uci:
                                lichess_info = lichess_move_data.get(alt_uci)

                        if lichess_info and lichess_info.get('total', 0) > 0:
                            moves_with_stats.append((move, lichess_info))
                        else:
                            # BACK-PROPAGATION: Check if child position has Lichess data
                            weight = 1
                            if move.to_position_id:
                                child_fen = id_to_fen.get(move.to_position_id)
                                if child_fen:
                                    clean_child_fen = " ".join(child_fen.split(" ")[:4])
                                    child_data = lichess_data_cache.get(clean_child_fen)
                                    if child_data:
                                        weight = sum(m_info.get('total', 0) for m_info in child_data.values())
                                        if weight < 1: weight = 1
                            rare_moves_with_weights.append((move, weight))
                    
                    if moves_with_stats:
                        min_lichess_total = min(stats['total'] for _, stats in moves_with_stats)
                        rare_moves_with_weights = [(m, min(w, min_lichess_total)) for m, w in rare_moves_with_weights]
                    
                    # TOTAL GAMES = SUM(LICHESS TOP 12) + SUM(PROPAGATED RARE WEIGHTS)
                    total_rare_weight = sum(w for m, w in rare_moves_with_weights)
                    effective_total = total_from_lichess + total_rare_weight
                    
                    if effective_total > 0:
                        for move, stats in moves_with_stats:
                            share = stats['total'] / effective_total
                            next_prob = current_prob * share
                            move.priority_score = next_prob
                            if move.to_position_id:
                                id_probabilities[move.to_position_id] = id_probabilities.get(move.to_position_id, 0.0) + next_prob
                        
                        for move, weight in rare_moves_with_weights:
                            share = weight / effective_total
                            next_prob = current_prob * share
                            move.priority_score = next_prob
                            if move.to_position_id:
                                id_probabilities[move.to_position_id] = id_probabilities.get(move.to_position_id, 0.0) + next_prob
                    else:
                        # Fallback for no data
                        split_prob = current_prob / len(all_outgoing_moves)
                        for move in all_outgoing_moves:
                            move.priority_score = split_prob
                            if move.to_position_id:
                                id_probabilities[move.to_position_id] += split_prob

            if progress_callback:
                progress_callback(int((depth + 1) * 100 / total_depths))
            
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
            start_prob = sum((m.priority_score or 0.0) for m in incoming_moves)
            
        if start_prob <= 0 and clean_start_fen != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR":
            return True, "No probability to propagate."

        from sqlalchemy import text
        # ── 1. Use Recursive CTE to find all reachable position IDs instantly ──
        sql_reachable = text("""
            WITH RECURSIVE descendants(id) AS (
                SELECT :start_id
                UNION
                SELECT m.to_position_id
                FROM moves m
                INNER JOIN descendants d ON m.from_position_id = d.id
                WHERE m.to_position_id IS NOT NULL
            )
            SELECT id FROM descendants
        """)
        reachable_ids = {row[0] for row in session.execute(sql_reachable, {"start_id": start_pos_id}).fetchall()}
        
        # ── 2. Bulk fetch all relevant Moves efficiently (handling SQLite limits) ──
        all_moves_in_subtree = []
        seen_move_ids = set()
        reachable_list = list(reachable_ids)
        chunk_size = 900
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
        incoming_moves_cache = {pid: [] for pid in reachable_ids}
        
        for m in all_moves_in_subtree:
            if m.from_position_id in outgoing_moves_cache:
                outgoing_moves_cache[m.from_position_id].append(m)
            if m.to_position_id in incoming_moves_cache:
                incoming_moves_cache[m.to_position_id].append(m)

        # ── 3. Build queue dynamically (BFS in memory with max depth tracking) ──
        pos_depths = {start_pos_id: 0}
        visit_count = {start_pos_id: 1}
        queue = deque([start_pos_id])

        while queue:
            pos_id = queue.popleft()
            curr_d = pos_depths[pos_id]

            for m in outgoing_moves_cache.get(pos_id, []):
                to_id = m.to_position_id
                if to_id and to_id in reachable_ids:
                    new_d = curr_d + 1
                    if to_id not in pos_depths or new_d > pos_depths[to_id]:
                        pos_depths[to_id] = new_d
                        vc = visit_count.get(to_id, 0) + 1
                        visit_count[to_id] = vc
                        if vc <= 100:
                            queue.append(to_id)

        max_d = max(pos_depths.values()) if pos_depths else 0
        subtree_positions_by_depth = [[] for _ in range(max_d + 1)]
        for pid, d in pos_depths.items():
            subtree_positions_by_depth[d].append(pid)
        
        id_probabilities = {pid: 0.0 for pid in reachable_ids}
        id_probabilities[start_pos_id] = start_prob
        
        for pid in reachable_ids:
            if pid == start_pos_id: continue
            incoming = incoming_moves_cache.get(pid, [])
            ext_prob = sum((m.priority_score or 0.0) for m in incoming if m.from_position_id not in reachable_ids)
            id_probabilities[pid] = ext_prob

        rep_moves_db = session.query(RepertoireMove.move_id).filter_by(is_active=True).all()
        rep_move_ids = {rm.move_id for rm in rep_moves_db}
        user_turn_char = get_meta(session, "color", "w")
        
        reachable_pos = session.query(Position.id, Position.fen).filter(Position.id.in_(list(reachable_ids))).all()
        id_to_fen_dict = {p.id: p.fen for p in reachable_pos}
        reachable_clean_fens = {" ".join(p.fen.split(" ")[:4]) for p in reachable_pos}
        
        lichess_data_cache = {" ".join(ld.fen.split(" ")[:4]): json.loads(ld.moves_json) for ld in session.query(LichessData).filter(LichessData.fen.in_(list(reachable_clean_fens)), LichessData.elo_range == elo_category).all()}

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
                        split_prob = current_prob / len(user_rep_moves)
                        for m in user_rep_moves:
                            m.priority_score = split_prob
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] += split_prob
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
                                id_probabilities[m.to_position_id] += next_p
                        
                        for m, weight in rare_moves_with_weights:
                            share = weight / effective_total
                            next_p = current_prob * share
                            m.priority_score = next_p
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] += next_p
                        continue

                    # Fallback for no data
                    if out_moves:
                        split_prob = current_prob / len(out_moves)
                        for m in out_moves:
                            m.priority_score = split_prob
                            if m.to_position_id in id_probabilities:
                                id_probabilities[m.to_position_id] += split_prob

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

        while queue:
            pos_id = queue.popleft()
            reachable_pos_ids.add(pos_id)
            
            fen = id_to_fen.get(pos_id, "")
            is_user_turn = fen.split(" ")[1] == user_turn_char

            if is_user_turn:
                user_repertoire_moves = session.query(Move).join(RepertoireMove).filter(
                    Move.from_position_id == pos_id
                ).all()

                if user_repertoire_moves:
                    for user_move in user_repertoire_moves:
                        if user_move.to_position_id and user_move.to_position_id not in visited_bfs:
                            visited_bfs.add(user_move.to_position_id)
                            queue.append(user_move.to_position_id)
                else:
                    dead_end_user_turns.append(pos_id)
            else:
                outgoing_moves = session.query(Move).filter_by(from_position_id=pos_id).all()
                for move in outgoing_moves:
                    if move.to_position_id and move.to_position_id not in visited_bfs:
                        visited_bfs.add(move.to_position_id)
                        queue.append(move.to_position_id)

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
