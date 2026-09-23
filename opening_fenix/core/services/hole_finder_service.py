import collections
import json
import os
import sys
import subprocess
import time
import chess
import chess.engine
from sqlalchemy.orm import Session
from opening_fenix.core.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path, CASTLING_ALT, CASTLING_SANS
from opening_fenix.core.logger import logger

def run_hole_finder_task(repo_name, is_test, threshold, elo_range, mode="holes", level=None, find_rare=False,
                        engine_path=None, threads_count=1, item_callback=None, cancel_check=None, engine=None,
                        depth=25, progress_callback=None):
    """
    Stand-alone task to find repertoire holes or priority mismatches.
    Creates its own DB session for thread safety.
    """
    db_path = get_repertoire_db_path(repo_name, is_test)
    db_manager = DatabaseManager(db_path)
    session = db_manager.get_session()
    
    try:
        if mode == "holes":
            return find_repertoire_holes(session, threshold, elo_range)
        elif mode == "level_check":
            return find_level_mismatches(session)
        elif mode == "transpositions":
            return find_repertoire_transpositions(
                session,
                elo_range,
                engine_path=engine_path,
                threads_count=threads_count,
                item_callback=item_callback,
                cancel_check=cancel_check,
                engine=engine,
                depth=depth,
                progress_callback=progress_callback
            )
        else:
            return find_priority_mismatches(session, level, threshold, find_rare=find_rare)
    finally:
        session.close()
        db_manager.close()

def find_repertoire_holes(session: Session, threshold: float, elo_range: str):
    """Ported logic from CreatorBackend.find_repertoire_holes"""
    threshold_val = threshold / 100.0
    
    # Get Repertoire Color
    m = session.query(Metadata).filter_by(key="color").first()
    user_turn_char = m.value if m else 'w'

    # 1. Pre-fetch
    all_moves_db = session.query(Move).all()
    rep_move_ids = {
        rm.move_id
        for rm in session.query(RepertoireMove.move_id).filter_by(is_active=True).all()
    }

    all_moves_from = collections.defaultdict(list)
    rep_moves_from = collections.defaultdict(list)
    for m in all_moves_db:
        all_moves_from[m.from_position_id].append(m)
        if m.id in rep_move_ids:
            rep_moves_from[m.from_position_id].append(m)

    id_to_fen = dict(session.query(Position.id, Position.fen).all())

    lichess_cache = {}
    rows = session.query(LichessData).filter_by(elo_range=elo_range).all()
    if not rows:
        # Fallback to the repertoire's saved lichess_elo / elo metadata, or any available elo_range in DB
        meta_elo = session.query(Metadata).filter(Metadata.key.in_(["elo", "lichess_elo"])).all()
        for m_e in meta_elo:
            if m_e.value and m_e.value.strip() != elo_range:
                rows = session.query(LichessData).filter_by(elo_range=m_e.value.strip()).all()
                if rows: break
        if not rows:
            first_ld = session.query(LichessData.elo_range).first()
            if first_ld:
                rows = session.query(LichessData).filter_by(elo_range=first_ld[0]).all()

    for ld in rows:
        clean = " ".join(ld.fen.split(" ")[:4])
        try:
            lichess_cache[clean] = json.loads(ld.moves_json)
        except: pass

    exempt_fens = {
        " ".join(row[0].split(" ")[:4])
        for row in session.query(Position.fen).filter(Position.is_hole_exempt == True).all()
    }

    def covered_ucis_for(pid):
        ucis = set()
        for m in rep_moves_from.get(pid, []):
            u = m.uci.strip().lower()
            ucis.add(u)
            if m.san in CASTLING_SANS:
                alt = CASTLING_ALT.get(u)
                if alt: ucis.add(alt)
        return ucis

    # 2. Root
    sp = session.query(Position.id).filter(
        Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")
    ).first()
    if not sp: return []
    root_id = sp[0]

    # 3. BFS
    reach_probs = {root_id: 1.0}
    pos_by_depth = []
    bfs_queue = collections.deque([(root_id, 0)])
    bfs_visited = set()

    while bfs_queue:
        pid, d = bfs_queue.popleft()
        if pid in bfs_visited: continue
        bfs_visited.add(pid)
        if d > 150: continue

        while len(pos_by_depth) <= d: pos_by_depth.append([])
        pos_by_depth[d].append(pid)

        fen = id_to_fen.get(pid, "")
        parts = fen.split(" ")
        is_user = len(parts) > 1 and parts[1] == user_turn_char

        nexts = rep_moves_from.get(pid, []) if is_user else all_moves_from.get(pid, [])
        for m in nexts:
            if m.to_position_id and m.to_position_id not in bfs_visited:
                bfs_queue.append((m.to_position_id, d + 1))

    # 4. Propagation
    holes = []
    for d, depth_list in enumerate(pos_by_depth):
        for pid in depth_list:
            p_reach = reach_probs.get(pid, 0.0)
            fen = id_to_fen.get(pid)
            if not fen: continue
            clean_fen = " ".join(fen.split(" ")[:4])
            is_exempt = clean_fen in exempt_fens

            parts = clean_fen.split(" ")
            is_user = len(parts) > 1 and parts[1] == user_turn_char
            rep_moves = rep_moves_from.get(pid, [])
            
            # --- FEATURE: REPERTOIRE GAP DETECTION (User turn but no moves) ---
            # These should show up regardless of threshold_val
            if is_user and not rep_moves:
                if not is_exempt:
                   holes.append({
                        "fen": clean_fen,
                        "move_san": "—",
                        "type": "repertoire_gap",
                        "popularity": p_reach * 100,
                        "ply_depth": d,
                    })
                # We skip candidate move search if it's a gap (user should decide what to play first)
                # or we can continue if we want to show Lichess suggestions too. 

            if p_reach < threshold_val:
                continue

            if is_user:
                if not rep_moves:
                    # User candidate logic (Lichess suggestions)
                    if not is_exempt:
                        lichess_moves = lichess_cache.get(clean_fen, {})
                        total_games = sum(v.get('total', 0) for v in lichess_moves.values())
                        if total_games > 0:
                            for uci, stats in lichess_moves.items():
                                move_total = stats.get('total', 0)
                                p_move = move_total / total_games
                                p_total = p_reach * p_move
                                if p_total >= threshold_val:
                                    # Calculate SAN if missing
                                    move_san = stats.get('san')
                                    if not move_san:
                                        try:
                                            board = chess.Board(clean_fen)
                                            move = chess.Move.from_uci(uci)
                                            move_san = board.san(move)
                                        except:
                                            move_san = uci
                                            
                                    holes.append({
                                        "fen": clean_fen,
                                        "move_san": move_san,
                                        "type": "user",
                                        "popularity": p_total * 100,
                                        "ply_depth": d,
                                    })
                else:
                    p_next = p_reach / len(rep_moves)
                    for m in rep_moves:
                        if m.to_position_id:
                            reach_probs[m.to_position_id] = reach_probs.get(m.to_position_id, 0.0) + p_next
            else:
                lichess_moves = lichess_cache.get(clean_fen, {})
                total_games = sum(v.get('total', 0) for v in lichess_moves.values())
                if total_games == 0:
                    out_moves = all_moves_from.get(pid, [])
                    if out_moves:
                        p_next = p_reach / len(out_moves)
                        for m in out_moves:
                            if m.to_position_id:
                                reach_probs[m.to_position_id] = reach_probs.get(m.to_position_id, 0.0) + p_next
                    continue

                covered = covered_ucis_for(pid)
                for uci, stats in lichess_moves.items():
                    move_total = stats.get('total', 0)
                    if move_total == 0: continue
                    norm_uci = uci.strip().lower()
                    p_move = move_total / total_games
                    p_total = p_reach * p_move

                    if norm_uci in covered or CASTLING_ALT.get(norm_uci, '') in covered:
                        for m in rep_moves:
                            m_uci = m.uci.strip().lower()
                            if m_uci == norm_uci or CASTLING_ALT.get(m_uci, '') == norm_uci:
                                if m.to_position_id:
                                    reach_probs[m.to_position_id] = reach_probs.get(m.to_position_id, 0.0) + p_total
                                break
                    else:
                        if p_total >= threshold_val and not is_exempt:
                            # Calculate SAN if missing
                            move_san = stats.get('san')
                            if not move_san:
                                try:
                                    board = chess.Board(clean_fen)
                                    move = chess.Move.from_uci(uci)
                                    move_san = board.san(move)
                                except:
                                    move_san = uci

                            holes.append({
                                "fen": clean_fen,
                                "move_san": move_san,
                                "type": "opponent",
                                "popularity": p_total * 100,
                                "ply_depth": d,
                            })
    return sorted(holes, key=lambda x: x['popularity'], reverse=True)

def find_level_mismatches(session: Session):
    """
    Finds:
    1. Level Mismatches (Gaps): Positions reached at Path Level L where ALL user moves are Level > L.
    2. Orphaned Moves: Moves that are assigned a level < Path Level L (e.g., Level 1 move trapped behind Level 3).
    """
    m = session.query(Metadata).filter_by(key="color").first()
    player_color = m.value if m else 'w'

    all_rep_moves = session.query(Move, RepertoireMove).join(
        RepertoireMove, Move.id == RepertoireMove.move_id
    ).filter(RepertoireMove.is_active == True).all()

    moves_from = collections.defaultdict(list)
    for move, rm in all_rep_moves:
        moves_from[move.from_position_id].append((move, rm))

    sp = session.query(Position.id).filter(
        Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")
    ).first()
    if not sp: return []
    root_id = sp[0]
    
    # Pre-fetch all FENs for active positions
    # It's fast enough to just fetch all of them
    id_to_fen = dict(session.query(Position.id, Position.fen).all())
    
    root_fen = id_to_fen.get(root_id)
    if not root_fen: return []
    root_norm = " ".join(root_fen.split(" ")[:4])
    
    # path_lvl[fen_norm] = the minimum required level to reach this exact board state
    path_lvl = {root_norm: 0}
    depth_map = {root_norm: 0}
    bfs_queue = collections.deque([(root_id, 0)])
    
    while bfs_queue:
        curr_id, curr_depth = bfs_queue.popleft()
        curr_fen = id_to_fen.get(curr_id)
        if not curr_fen: continue
        curr_norm = " ".join(curr_fen.split(" ")[:4])
        curr_lvl = path_lvl.get(curr_norm, 0)
        
        for move, rm in moves_from.get(curr_id, []):
            tid = move.to_position_id
            if tid:
                tfen = id_to_fen.get(tid)
                if not tfen: continue
                tnorm = " ".join(tfen.split(" ")[:4])
                
                new_lvl = max(curr_lvl, rm.level)
                new_depth = curr_depth + 1
                if tnorm not in depth_map or new_depth < depth_map[tnorm]:
                    depth_map[tnorm] = new_depth

                if tnorm not in path_lvl or new_lvl < path_lvl[tnorm]:
                    path_lvl[tnorm] = new_lvl
                    bfs_queue.append((tid, new_depth))

    # 2. Check for mismatches
    mismatches = []
    seen_mismatches = set() # (fen_norm, move_san, type)
    
    for curr_id, out_moves in moves_from.items():
        curr_fen = id_to_fen.get(curr_id)
        if not curr_fen: continue
        curr_norm = " ".join(curr_fen.split(" ")[:4])
        
        # If position is completely unreachable from root, skip
        if curr_norm not in path_lvl: continue
        lvl = path_lvl[curr_norm]
        pos_depth = depth_map.get(curr_norm, 0)
        
        parts = curr_fen.split(" ")
        is_user_turn = len(parts) > 1 and parts[1] == player_color
        
        if is_user_turn:
            all_higher = True
            for move, rm in out_moves:
                if rm.level <= lvl or lvl == 0:
                    all_higher = False
                    break
            
            if all_higher:
                for move, rm in out_moves:
                    key = (curr_norm, move.san, "level_mismatch")
                    if key not in seen_mismatches:
                        seen_mismatches.add(key)
                        mismatches.append({
                            "fen": curr_norm,  # Return BEFORE position FEN
                            "move_san": move.san,
                            "type": "level_mismatch",
                            "from_level": lvl,
                            "to_level": rm.level,
                            "popularity": 0,
                            "ply_depth": pos_depth,
                        })
        
        for move, rm in out_moves:
            if rm.level < lvl and lvl > 0:
                key = (curr_norm, move.san, "orphaned_move")
                if key not in seen_mismatches:
                    seen_mismatches.add(key)
                    mismatches.append({
                        "fen": curr_norm,  # Return BEFORE position FEN
                        "move_san": move.san,
                        "type": "orphaned_move",
                        "from_level": lvl,
                        "to_level": rm.level,
                        "popularity": 0,
                        "ply_depth": pos_depth,
                    })

    return mismatches

def find_priority_mismatches(session: Session, level: int, threshold_pct: float, find_rare: bool = False):
    """Ported logic from CreatorBackend.find_priority_mismatches"""
    threshold = threshold_pct / 100.0
    
    mismatches = []
    
    # Selection criteria: >= threshold (too important) OR <= threshold (too rare)
    op = Move.priority_score <= threshold if find_rare else Move.priority_score >= threshold

    from sqlalchemy.orm import joinedload
    # Query for RepertoireMoves joined with Moves
    moves_with_rm = session.query(Move, RepertoireMove).join(
        RepertoireMove, Move.id == RepertoireMove.move_id
    ).options(joinedload(Move.from_position)).filter(
        RepertoireMove.is_active == True,
        RepertoireMove.level == level,
        op
    ).all()

    # Pre-build in-memory parent map to construct path strings for UI context without query overhead
    parent_map = {}
    for from_pos_id, to_pos_id, san, prio in session.query(Move.from_position_id, Move.to_position_id, Move.san, Move.priority_score).all():
        prio_val = prio or 0.0
        existing = parent_map.get(to_pos_id)
        if not existing or prio_val > existing[2]:
            parent_map[to_pos_id] = (from_pos_id, san, prio_val)

    # Build path strings in memory
    def get_path_to_pos(pid, visited=None):
        if visited is None: visited = set()
        if pid in visited: return "..."
        visited.add(pid)
        
        parent_info = parent_map.get(pid)
        if not parent_info: return "Start"
        parent_id, san, _ = parent_info
        return get_path_to_pos(parent_id, visited) + " -> " + san

    def get_depth_to_pos(pid, visited=None):
        if visited is None: visited = set()
        if pid in visited: return 0
        visited.add(pid)
        parent_info = parent_map.get(pid)
        if not parent_info: return 0
        return get_depth_to_pos(parent_info[0], visited) + 1

    for move, rm in moves_with_rm:
        mismatches.append({
            "fen": move.from_position.fen if move.from_position else None,
            "move_san": move.san,
            "type": "priority_check",
            "popularity": move.priority_score * 100,
            "path": get_path_to_pos(move.from_position_id),
            "ply_depth": get_depth_to_pos(move.from_position_id),
        })
    
    return sorted(mismatches, key=lambda x: x['popularity'], reverse=True)


def find_repertoire_transpositions(session: Session, elo_range: str = "high",
                                   engine_path: str = None, threads_count: int = 1,
                                   item_callback = None, cancel_check = None,
                                   engine = None, max_transpositions: int = None,
                                   cache_service = None, depth: int = 25,
                                   progress_callback = None, only_1move: bool = False):
    """
    Finds unlinked 1-move and 2-move transpositions across the entire active repertoire.
    Filters strictly for sound/good lines:
      - 2-Move transpositions: User move is verified with chess engine at depth 25 to ensure
        it is the #1 best move (PV1) punishing any opponent inaccuracy.
      - Classified as 'ausgezeichnet' (🟢) only if it is the best move.
      - Uses persistent global cache for depth 25 engine evaluations across scans.
      - Results can stream incrementally via item_callback.
    """
    def clean_fen(f):
        if not f:
            return ""
        return " ".join(f.strip().split()[:4])

    # 1. Metadata
    m = session.query(Metadata).filter_by(key="color").first()
    player_color = m.value if m else 'w'

    # 2. Pre-fetch positions and moves
    all_positions = session.query(Position).all()
    if not all_positions:
        return []

    fen_to_pos = {clean_fen(p.fen): p for p in all_positions if p.fen}
    id_to_clean_fen = {p.id: clean_fen(p.fen) for p in all_positions if p.fen}

    exempt_fens = {
        clean_fen(row[0])
        for row in session.query(Position.fen).filter(Position.is_hole_exempt == True).all()
        if row[0]
    }

    # Repertoire moves
    all_rep_moves = session.query(Move, RepertoireMove).join(
        RepertoireMove, Move.id == RepertoireMove.move_id
    ).all()

    rep_moves_from_id = collections.defaultdict(list)
    rep_adj_fen = collections.defaultdict(set)
    inactive_adj_fen = collections.defaultdict(set)
    for move, rm in all_rep_moves:
        f_fen = id_to_clean_fen.get(move.from_position_id)
        u = move.uci.strip().lower()
        alts = {u}
        if move.san in CASTLING_SANS:
            alt = CASTLING_ALT.get(u)
            if alt:
                alts.add(alt)

        if rm.is_active:
            rep_moves_from_id[move.from_position_id].append(move)
            if f_fen:
                rep_adj_fen[f_fen].update(alts)
        else:
            if f_fen:
                inactive_adj_fen[f_fen].update(alts)

    # 3. BFS from Root to get reachable active repertoire positions and reach probabilities
    sp = session.query(Position.id, Position.fen).filter(
        Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")
    ).first()
    if not sp:
        return []
    root_id, root_fen = sp
    root_norm = clean_fen(root_fen)

    # Pre-fetch Lichess data for elo_range
    lichess_cache = {}
    rows = session.query(LichessData).filter_by(elo_range=elo_range).all()
    if not rows:
        meta_elo = session.query(Metadata).filter(Metadata.key.in_(["elo", "lichess_elo"])).all()
        for m_e in meta_elo:
            if m_e.value and m_e.value.strip() != elo_range:
                rows = session.query(LichessData).filter_by(elo_range=m_e.value.strip()).all()
                if rows:
                    break
        if not rows:
            first_ld = session.query(LichessData.elo_range).first()
            if first_ld:
                rows = session.query(LichessData).filter_by(elo_range=first_ld[0]).all()

    for ld in rows:
        clean = clean_fen(ld.fen)
        try:
            lichess_cache[clean] = json.loads(ld.moves_json)
        except Exception:
            pass

    def get_variation_name(pos):
        if not pos:
            return "Variante"
        return (
            pos.variation_1 or pos.cached_v1 or
            pos.variation_2 or pos.cached_v2 or
            pos.variation_3 or pos.cached_v3 or
            "Variante"
        )

    target_engine_depth = depth
    reachable_fens = {root_norm}
    reachable_depths = {root_norm: 0}
    reach_probs = {root_id: 1.0}
    reach_probs_fen = {root_norm: 1.0}
    bfs_queue = collections.deque([(root_id, root_norm, 0)])
    visited_ids = {root_id}

    while bfs_queue:
        curr_id, curr_norm, curr_ply = bfs_queue.popleft()
        p_curr = reach_probs.get(curr_id, 0.0)
        curr_is_user = (len(curr_norm.split()) > 1 and curr_norm.split()[1] == player_color)
        rep_moves = rep_moves_from_id.get(curr_id, [])

        if curr_is_user:
            if rep_moves:
                p_split = p_curr / len(rep_moves)
                for move in rep_moves:
                    tid = move.to_position_id
                    if tid:
                        reach_probs[tid] = reach_probs.get(tid, 0.0) + p_split
                        t_norm = id_to_clean_fen.get(tid)
                        if t_norm:
                            reach_probs_fen[t_norm] = reach_probs[tid]
        else:
            lichess_moves = lichess_cache.get(curr_norm, {})
            total_games = sum(v.get('total', 0) for v in lichess_moves.values())
            for move in rep_moves:
                tid = move.to_position_id
                if tid:
                    if move.priority_score and move.priority_score > 0:
                        p_move = move.priority_score
                    elif total_games > 0:
                        u = move.uci.strip().lower()
                        stats = lichess_moves.get(u) or lichess_moves.get(move.san)
                        if not stats and move.san in CASTLING_SANS:
                            alt = CASTLING_ALT.get(u)
                            if alt:
                                stats = lichess_moves.get(alt)
                        move_total = stats.get('total', 0) if stats else 0
                        p_move = p_curr * (move_total / total_games)
                    else:
                        p_move = p_curr / len(rep_moves) if rep_moves else 0.0
                    reach_probs[tid] = reach_probs.get(tid, 0.0) + p_move
                    t_norm = id_to_clean_fen.get(tid)
                    if t_norm:
                        reach_probs_fen[t_norm] = reach_probs[tid]

        for move in rep_moves:
            tid = move.to_position_id
            if tid and tid not in visited_ids:
                visited_ids.add(tid)
                t_norm = id_to_clean_fen.get(tid)
                if t_norm:
                    reachable_fens.add(t_norm)
                    reachable_depths[t_norm] = curr_ply + 1
                    bfs_queue.append((tid, t_norm, curr_ply + 1))

    # Helper to calculate potential prio score of an unadded opponent move
    def calculate_potential_prio(from_pos_id, from_fen, move_uci, move_san):
        if from_fen == root_norm:
            p_reach = 1.0
        else:
            p_reach = reach_probs.get(from_pos_id) or reach_probs_fen.get(from_fen, 0.0)
            if p_reach <= 0.0 and from_pos_id:
                p_obj = fen_to_pos.get(from_fen)
                if p_obj and p_obj.incoming_moves:
                    p_reach = max((m.priority_score or 0.0 for m in p_obj.incoming_moves), default=0.0)
        
        if p_reach <= 0.0 and from_fen != root_norm:
            p_reach = 1.0

        lichess_moves = lichess_cache.get(from_fen, {})
        total_games = sum(v.get('total', 0) for v in lichess_moves.values())
        if total_games > 0:
            stats = lichess_moves.get(move_uci) or lichess_moves.get(move_san)
            if not stats and move_san in CASTLING_SANS:
                alt = CASTLING_ALT.get(move_uci)
                if alt:
                    stats = lichess_moves.get(alt)
            if stats and stats.get('total', 0) > 0:
                share = stats.get('total', 0) / total_games
                return p_reach * share, share
            else:
                share = min(1.0 / (total_games + 1), 0.00005)
                return p_reach * share, share
        min_share = 0.00005
        return p_reach * min_share, min_share

    # 4. Helpers to evaluate move soundness when offline / without live engine
    def evaluate_user_move(from_pos, from_fen, move_uci, target_pos, covered_from_inter=None):
        if covered_from_inter and move_uci in covered_from_inter:
            return True

        if from_pos and from_pos.good_moves:
            try:
                gm_list = json.loads(from_pos.good_moves)
                if move_uci in gm_list:
                    return True
            except Exception:
                pass

        if from_pos and from_pos.engine_eval is not None and target_pos and target_pos.engine_eval is not None:
            p_turn = from_fen.split()[1] if len(from_fen.split()) > 1 else 'w'
            score_diff = target_pos.engine_eval - from_pos.engine_eval
            user_loss = -score_diff if p_turn == 'w' else score_diff
            if user_loss <= 15:
                return True
            return False

        # Fallback when no live engine is supplied (e.g. offline unit testing)
        return True

    results = []
    seen_keys = set()

    # Fast bitboard transposition keys for 5x-6x faster lookups
    all_rep_keys = {}
    for clean_f in fen_to_pos:
        try:
            b = chess.Board(clean_f + " 0 1")
            all_rep_keys[b._transposition_key()] = clean_f
        except Exception:
            pass

    reachable_keys = set()
    for clean_f in reachable_fens:
        try:
            b = chess.Board(clean_f + " 0 1")
            reachable_keys.add(b._transposition_key())
        except Exception:
            pass

    # We only scan from positions where it is the OPPONENT's turn
    opponent_reachable_fens = [
        f for f in reachable_fens
        if len(f.split()) > 1 and f.split()[1] != player_color and f not in exempt_fens
    ]

    # Sort opponent-reachable positions so the most popular positions are searched first:
    # 1. Primary: Repertoire reach probability (reach_probs_fen / reach_probs / incoming move priority)
    # 2. Secondary: Total games in Lichess database for this position
    # 3. Tertiary: Shallower ply depth (closer to root)
    def get_position_reach_prob(f):
        if f == root_norm:
            return 1.0
        p_obj = fen_to_pos.get(f)
        pid = p_obj.id if p_obj else None
        prob = reach_probs_fen.get(f, 0.0)
        if prob <= 0.0 and pid:
            prob = reach_probs.get(pid, 0.0)
        if prob <= 0.0 and p_obj and p_obj.incoming_moves:
            prob = max((m.priority_score or 0.0 for m in p_obj.incoming_moves), default=0.0)
        return prob or 0.0

    def get_position_total_games(f):
        lm = lichess_cache.get(f, {})
        return sum(v.get('total', 0) for v in lm.values()) if lm else 0

    def position_popularity_key(f):
        p_reach = get_position_reach_prob(f)
        total_games = get_position_total_games(f)
        ply = reachable_depths.get(f, 999) or 999
        return (-p_reach, -total_games, ply)

    opponent_reachable_fens.sort(key=position_popularity_key)
    total_opp = len(opponent_reachable_fens)

    # Pass 1: 1-Move Opponent Transpositions (Opponent plays m1 directly into our repertoire, no badge)
    for idx1, f_orig in enumerate(opponent_reachable_fens):
        if max_transpositions is not None and len(results) >= max_transpositions:
            break
        if cancel_check and cancel_check():
            break

        p_orig = fen_to_pos.get(f_orig)
        if not p_orig:
            continue

        orig_depth = reachable_depths.get(f_orig)
        covered_from_orig = rep_adj_fen.get(f_orig, set())
        inactive_from_orig = inactive_adj_fen.get(f_orig, set())

        try:
            board_1 = chess.Board(f_orig + " 0 1")
        except Exception:
            continue

        lichess_moves_1 = lichess_cache.get(f_orig, {})
        def m1_popularity_key(m):
            u = m.uci().strip().lower()
            st = lichess_moves_1.get(u)
            if not st:
                alt = CASTLING_ALT.get(u)
                if alt:
                    st = lichess_moves_1.get(alt)
            return st.get('total', 0) if st else 0

        for m1 in sorted(board_1.legal_moves, key=m1_popularity_key, reverse=True):
            if max_transpositions is not None and len(results) >= max_transpositions:
                break
            if cancel_check and cancel_check():
                break
            u1 = m1.uci().strip().lower()
            if u1 in covered_from_orig or u1 in inactive_from_orig:
                continue

            # Filter out underpromotions on m1
            if m1.promotion is not None and m1.promotion != chess.QUEEN:
                continue

            board_1.push(m1)
            k1 = board_1._transposition_key()
            board_1.pop()

            if k1 in all_rep_keys:
                t1_fen = all_rep_keys[k1]
                if t1_fen != f_orig:
                    t1_depth = reachable_depths.get(t1_fen)
                    if orig_depth is not None and t1_depth is not None and t1_depth < orig_depth:
                        continue

                    p_target = fen_to_pos.get(t1_fen)
                    key = (f_orig, t1_fen, u1)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        try:
                            s1 = board_1.san(m1)
                        except Exception:
                            s1 = u1

                        prio_score, pos_prio = calculate_potential_prio(p_orig.id, f_orig, u1, s1)
                        res_item = {
                            "fen": f_orig,
                            "target_fen": t1_fen,
                            "move_san": s1,
                            "path_sans": [s1],
                            "path_ucis": [u1],
                            "depth": 1,
                            "type": "transposition_1",
                            "turn": "opponent",
                            "quality": "",
                            "quality_label": "—",
                            "priority_score": prio_score,
                            "pos_prio": pos_prio,
                            "popularity": prio_score * 100.0,
                            "ply_depth": orig_depth,
                        }
                        results.append(res_item)
                        if item_callback:
                            item_callback(res_item)
                            time.sleep(0.001)

    if only_1move:
        return results

    # Pass 2: 2-Move Transpositions (Opponent plays m1, then WE play m2 to get back into repertoire)
    if max_transpositions is None or len(results) < max_transpositions:
        own_engine = False
        active_engine = engine
        if active_engine is None and engine_path and os.path.exists(engine_path):
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW | 0x00004000
            try:
                active_engine = chess.engine.SimpleEngine.popen_uci(
                    engine_path, creationflags=creationflags
                )
                # Reserve 1 CPU thread for the OS / UI so the PC stays responsive.
                scan_threads = max(1, int(threads_count) - 1)
                active_engine.configure({"Threads": scan_threads})
                own_engine = True
            except Exception:
                active_engine = None

        if cache_service is None and engine is None:
            from opening_fenix.core.services.engine_cache_service import EngineCacheService
            cache_service = EngineCacheService()
        engine_eval_cache = {}

        try:
            for idx2, f_orig in enumerate(opponent_reachable_fens):
                if max_transpositions is not None and len(results) >= max_transpositions:
                    break
                if cancel_check and cancel_check():
                    break

                if progress_callback:
                    progress_callback(idx2 + 1, total_opp, f"Pass 2: {idx2 + 1}/{total_opp}")

                p_orig = fen_to_pos.get(f_orig)
                if not p_orig:
                    continue

                orig_depth = reachable_depths.get(f_orig)
                covered_from_orig = rep_adj_fen.get(f_orig, set())
                inactive_from_orig = inactive_adj_fen.get(f_orig, set())

                try:
                    board_1 = chess.Board(f_orig + " 0 1")
                except Exception:
                    continue

                lichess_moves_1 = lichess_cache.get(f_orig, {})
                def m1_popularity_key(m):
                    u = m.uci().strip().lower()
                    st = lichess_moves_1.get(u)
                    if not st:
                        alt = CASTLING_ALT.get(u)
                        if alt:
                            st = lichess_moves_1.get(alt)
                    return st.get('total', 0) if st else 0

                for m1 in sorted(board_1.legal_moves, key=m1_popularity_key, reverse=True):
                    if max_transpositions is not None and len(results) >= max_transpositions:
                        break
                    if cancel_check and cancel_check():
                        break
                    u1 = m1.uci().strip().lower()
                    if u1 in covered_from_orig or u1 in inactive_from_orig:
                        continue

                    # Filter out underpromotions on m1
                    if m1.promotion is not None and m1.promotion != chess.QUEEN:
                        continue

                    board_1.push(m1)
                    k_inter = board_1._transposition_key()

                    # If m1 already lands on an active repertoire position, this was already
                    # detected as a 1-move transposition in Pass 1. Suggesting m1 + m2 from here
                    # would re-suggest our own move m2 that is already part of the repertoire.
                    if k_inter in reachable_keys:
                        board_1.pop()
                        continue

                    inter_fen = clean_fen(board_1.fen())
                    p_inter = fen_to_pos.get(inter_fen)
                    covered_from_inter = rep_adj_fen.get(inter_fen, set())
                    inactive_from_inter = inactive_adj_fen.get(inter_fen, set())

                    try:
                        for m2 in list(board_1.legal_moves):
                            if max_transpositions is not None and len(results) >= max_transpositions:
                                break
                            if cancel_check and cancel_check():
                                break
                            u2 = m2.uci().strip().lower()
                            if u2 in inactive_from_inter:
                                continue

                            # Filter out underpromotions on m2
                            if m2.promotion is not None and m2.promotion != chess.QUEEN:
                                continue

                            # Filter out transpositions where m1 was a promotion and m2 captures the promoted piece
                            # (since piece choice is irrelevant to the resulting position)
                            if m1.promotion is not None and m2.to_square == m1.to_square:
                                continue

                            board_1.push(m2)
                            k2 = board_1._transposition_key()
                            board_1.pop()

                            if k2 in all_rep_keys:
                                t2_fen = all_rep_keys[k2]
                                if t2_fen != f_orig and t2_fen != inter_fen:
                                    # Forward-only check (eliminate backward cycles / shallower depth)
                                    t2_depth = reachable_depths.get(t2_fen)
                                    if orig_depth is not None and t2_depth is not None and t2_depth < orig_depth:
                                        continue

                                    p_target = fen_to_pos.get(t2_fen)
                                    key = (f_orig, t2_fen, f"{u1}_{u2}")
                                    if key not in seen_keys:
                                        seen_keys.add(key)
                                        logger.info(f"[Transpos-2M] Candidate: from {f_orig} -> m1: {u1} -> m2: {u2} -> reaches {t2_fen}")

                                    # User plays m2: evaluate if user move is sound (within 10 cp of best move)
                                    is_best = False
                                    quality = "ausgezeichnet"
                                    quality_label = "🟢 Ausgezeichnet"

                                    eval_data = engine_eval_cache.get(inter_fen)
                                    if eval_data is None:
                                        # 1. Check persistent global cache
                                        cached_move = cache_service.get_best_move(inter_fen, min_depth=target_engine_depth) if cache_service else None
                                        if cached_move is not None:
                                            eval_data = {
                                                "best_uci": cached_move,
                                                "best_score": None,
                                                "moves": {cached_move: 0}
                                            }
                                            engine_eval_cache[inter_fen] = eval_data
                                        elif active_engine is not None:
                                            if cancel_check and cancel_check():
                                                break
                                            # Incremental MultiPV: start small, increase only if needed.
                                            # This ensures all move scores come from the same search context
                                            # (avoids root_moves hash-table interference that can misreport cp loss).
                                            eval_data = None
                                            for mpv_count in (3, 6, 10):
                                                if cancel_check and cancel_check():
                                                    break
                                                try:
                                                    eval_board = chess.Board(inter_fen + " 0 1")
                                                    mpv_infos = active_engine.analyse(
                                                        eval_board,
                                                        chess.engine.Limit(depth=target_engine_depth),
                                                        multipv=mpv_count
                                                    )
                                                    if not isinstance(mpv_infos, list):
                                                        mpv_infos = [mpv_infos]

                                                    best_uci = None
                                                    best_score = None
                                                    move_scores = {}
                                                    worst_score = None
                                                    for info_item in mpv_infos:
                                                        pv = info_item.get("pv", [])
                                                        if pv:
                                                            m_uci = pv[0].uci().lower()
                                                            s_obj = info_item.get("score")
                                                            s = s_obj.relative.score(mate_score=10000) if s_obj else None
                                                            # Always track the move; first PV = best by rank order
                                                            move_scores[m_uci] = s
                                                            if best_uci is None:
                                                                best_uci = m_uci
                                                            if s is not None:
                                                                if best_score is None or s > best_score:
                                                                    best_score = s
                                                                    best_uci = m_uci
                                                                worst_score = s  # last scored item is lowest-ranked

                                                    eval_data = {
                                                        "best_uci": best_uci,
                                                        "best_score": best_score,
                                                        "moves": move_scores,
                                                    }

                                                    if best_uci and cache_service:
                                                        cache_service.set_best_move(inter_fen, target_engine_depth, best_uci)

                                                    # Early exit conditions:
                                                    # 1) Our move u2 is already in the scored moves → done
                                                    if u2 in move_scores:
                                                        logger.info(f"[Transpos-2M] MultiPV={mpv_count}: found u2={u2} at score {move_scores[u2]} cp (best={best_score} cp)")
                                                        break
                                                    # 2) The worst-ranked move in this batch is already >10 cp
                                                    #    below best → u2 (ranked even lower) must be worse → done
                                                    if best_score is not None and worst_score is not None and (best_score - worst_score) > 10:
                                                        logger.info(f"[Transpos-2M] MultiPV={mpv_count}: spread {best_score - worst_score} cp > 10 cp, u2={u2} not in top {mpv_count} → rejected")
                                                        break
                                                    # Otherwise: u2 might still be within 10 cp → widen search
                                                    logger.info(f"[Transpos-2M] MultiPV={mpv_count}: u2={u2} not found, spread {best_score - worst_score if (best_score is not None and worst_score is not None) else '?'} cp ≤ 10 cp → widening")

                                                    # Yield to OS so the PC stays responsive between engine calls.
                                                    time.sleep(0)
                                                except Exception as e:
                                                    logger.warning(f"[Transpos-2M] Engine error analyzing {inter_fen} (MultiPV={mpv_count}): {e}")
                                                    eval_data = None
                                                    break

                                            engine_eval_cache[inter_fen] = eval_data

                                    if eval_data:
                                        best_uci = eval_data.get("best_uci")
                                        best_score = eval_data.get("best_score")

                                        if u2 == best_uci:
                                            is_best = True
                                            quality = "ausgezeichnet"
                                            quality_label = "🟢 Ausgezeichnet"
                                            logger.info(f"[Transpos-2M] ✓ m2={u2} is the #1 engine move from {inter_fen}")
                                        elif best_score is not None and u2 in eval_data.get("moves", {}):
                                            u2_score = eval_data["moves"][u2]
                                            if u2_score is not None:
                                                cp_loss = best_score - u2_score
                                                if cp_loss <= 10:
                                                    is_best = True
                                                    quality = "solide"
                                                    quality_label = f"🟡 Solide (-{cp_loss} cp)" if cp_loss > 0 else "🟢 Ausgezeichnet"
                                                    logger.info(f"[Transpos-2M] ✓ m2={u2} accepted: loss {cp_loss} cp <= 10 cp (best={best_uci} [{best_score} cp], m2=[{u2_score} cp])")
                                                else:
                                                    logger.info(f"[Transpos-2M] ✗ m2={u2} rejected: loss {cp_loss} cp > 10 cp (best={best_uci} [{best_score} cp], m2=[{u2_score} cp])")
                                            else:
                                                logger.info(f"[Transpos-2M] ✗ m2={u2} could not be evaluated by engine")
                                        elif best_score is not None:
                                            # u2 was not found in any MultiPV tier → it's worse than the spread threshold
                                            logger.info(f"[Transpos-2M] ✗ m2={u2} not in MultiPV results, beyond threshold (best={best_uci} [{best_score} cp])")
                                        else:
                                            # Fallback if best_score is None (e.g. mock engine or cached move without score)
                                            is_best = (u2 == best_uci)
                                            if not is_best:
                                                logger.info(f"[Transpos-2M] ✗ m2={u2} != best_uci={best_uci} (no engine scores available)")
                                    elif active_engine is None:
                                        # Offline fallback when no live engine is configured and not in cache
                                        is_best = evaluate_user_move(p_inter, inter_fen, u2, p_target, covered_from_inter)
                                        if is_best:
                                            logger.info(f"[Transpos-2M] ✓ m2={u2} accepted via offline heuristic")
                                        else:
                                            logger.info(f"[Transpos-2M] ✗ m2={u2} rejected via offline heuristic")

                                    if is_best:
                                        # Lazy SAN calculation
                                        board_1.pop()
                                        try:
                                            s1 = board_1.san(m1)
                                        except Exception:
                                            s1 = u1
                                        finally:
                                            board_1.push(m1)

                                        try:
                                            s2 = board_1.san(m2)
                                        except Exception:
                                            s2 = u2

                                        prio_score, pos_prio = calculate_potential_prio(p_orig.id, f_orig, u1, s1)
                                        seq_str = f"{s1}  {s2}"
                                        res_item = {
                                            "fen": f_orig,
                                            "target_fen": t2_fen,
                                            "move_san": seq_str,
                                            "path_sans": [s1, s2],
                                            "path_ucis": [u1, u2],
                                            "depth": 2,
                                            "type": "transposition_2",
                                            "turn": "user",
                                            "quality": quality,
                                            "quality_label": quality_label,
                                            "priority_score": prio_score,
                                            "pos_prio": pos_prio,
                                            "popularity": prio_score * 100.0,
                                            "ply_depth": orig_depth,
                                        }
                                        results.append(res_item)
                                        if item_callback:
                                            item_callback(res_item)
                                            time.sleep(0.001)
                    except Exception:
                        pass

                    board_1.pop()
        finally:
            if own_engine and active_engine:
                try:
                    active_engine.quit()
                except Exception:
                    pass

    def sort_key(item):
        d_val = item["depth"]
        q_val = 0 if item["quality"] == "ausgezeichnet" else (1 if item["quality"] == "solide" else 2)
        return (d_val, q_val, -item.get("popularity", 0))

    return sorted(results, key=sort_key)



