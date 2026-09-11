import collections
import json
import chess
from sqlalchemy.orm import Session
from opening_fenix.core.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path

def run_hole_finder_task(repo_name, is_test, threshold, elo_range, mode="holes", level=None, find_rare=False):
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
            return find_repertoire_transpositions(session, elo_range)
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
    for ld in session.query(LichessData).filter_by(elo_range=elo_range).all():
        clean = " ".join(ld.fen.split(" ")[:4])
        try:
            lichess_cache[clean] = json.loads(ld.moves_json)
        except: pass

    exempt_fens = {
        " ".join(row[0].split(" ")[:4])
        for row in session.query(Position.fen).filter(Position.is_hole_exempt == True).all()
    }

    CASTLING_ALT = {
        'e1g1': 'e1h1', 'e1h1': 'e1g1', 'e1c1': 'e1a1', 'e1a1': 'e1c1',
        'e8g8': 'e8h8', 'e8h8': 'e8g8', 'e8c8': 'e8a8', 'e8a8': 'e8c8',
    }

    def covered_ucis_for(pid):
        ucis = set()
        for m in rep_moves_from.get(pid, []):
            u = m.uci.strip().lower()
            ucis.add(u)
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
    for depth_list in pos_by_depth:
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
    bfs_queue = collections.deque([root_id])
    
    while bfs_queue:
        curr_id = bfs_queue.popleft()
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
                if tnorm not in path_lvl or new_lvl < path_lvl[tnorm]:
                    path_lvl[tnorm] = new_lvl
                    bfs_queue.append(tid)

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
                            "popularity": 0
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
                        "popularity": 0
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

    for move, rm in moves_with_rm:
        mismatches.append({
            "fen": move.from_position.fen if move.from_position else None,
            "move_san": move.san,
            "type": "priority_check",
            "popularity": move.priority_score * 100,
            "path": get_path_to_pos(move.from_position_id)
        })
    
    return sorted(mismatches, key=lambda x: x['popularity'], reverse=True)


def find_repertoire_transpositions(session: Session, elo_range: str = "high"):
    """
    Finds unlinked 1-move and 2-move transpositions across the entire active repertoire.
    Filters strictly for sound/good lines:
      - User moves: Verified against good_moves / engine eval / non-blunder.
      - Opponent moves: Verified against plausible game frequency or legal variations.
    Classifies results as 'ausgezeichnet' (🟢) or 'solide' (🟡).
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
        if rm.is_active:
            rep_moves_from_id[move.from_position_id].append(move)
            if f_fen:
                rep_adj_fen[f_fen].add(move.uci.strip().lower())
        else:
            if f_fen:
                inactive_adj_fen[f_fen].add(move.uci.strip().lower())

    # Lichess cache
    lichess_cache = {}
    for ld in session.query(LichessData).all():
        cf = clean_fen(ld.fen)
        try:
            lichess_cache[cf] = json.loads(ld.moves_json)
        except Exception:
            pass

    # 3. BFS from Root to get reachable active repertoire positions
    sp = session.query(Position.id, Position.fen).filter(
        Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")
    ).first()
    if not sp:
        return []
    root_id, root_fen = sp
    root_norm = clean_fen(root_fen)

    def get_variation_name(pos):
        if not pos:
            return "Variante"
        return (
            pos.variation_1 or pos.cached_v1 or
            pos.variation_2 or pos.cached_v2 or
            pos.variation_3 or pos.cached_v3 or
            "Variante"
        )

    reachable_fens = {root_norm}
    reachable_depths = {root_norm: 0}
    bfs_queue = collections.deque([(root_id, root_norm, 0)])
    visited_ids = {root_id}

    while bfs_queue:
        curr_id, curr_norm, depth = bfs_queue.popleft()
        for move in rep_moves_from_id.get(curr_id, []):
            tid = move.to_position_id
            if tid and tid not in visited_ids:
                visited_ids.add(tid)
                t_norm = id_to_clean_fen.get(tid)
                if t_norm:
                    reachable_fens.add(t_norm)
                    reachable_depths[t_norm] = depth + 1
                    bfs_queue.append((tid, t_norm, depth + 1))

    # 4. Helpers to evaluate move soundness
    def evaluate_user_move(from_pos, from_fen, move_uci, target_pos, covered_from_inter=None):
        if covered_from_inter and move_uci in covered_from_inter:
            return (True, True)

        if from_pos and from_pos.good_moves:
            try:
                gm_list = json.loads(from_pos.good_moves)
                if move_uci in gm_list:
                    return (True, True)
            except Exception:
                pass

        if from_pos and from_pos.engine_eval is not None and target_pos and target_pos.engine_eval is not None:
            p_turn = from_fen.split()[1] if len(from_fen.split()) > 1 else 'w'
            score_diff = target_pos.engine_eval - from_pos.engine_eval
            user_loss = -score_diff if p_turn == 'w' else score_diff
            if user_loss <= 15:
                return (True, True)
            return (False, False)

        ld_moves = lichess_cache.get(from_fen, {})
        if ld_moves:
            if move_uci in ld_moves:
                m_stat = ld_moves[move_uci]
                total_games = sum(v.get('total', 0) for v in ld_moves.values())
                m_total = m_stat.get('total', 0)
                if total_games > 0 and (m_total / total_games) >= 0.10:
                    return (True, True)
                return (False, False)
            return (False, False)

        # Fallback: When no cached Lichess/engine data exists for the off-repertoire intermediate position,
        # our move into an active, deeper repertoire position is considered sound.
        return (True, True)

    MAX_TRANSPOSITIONS = 15
    results = []
    seen_keys = set()

    # We only scan from positions where it is the OPPONENT's turn
    opponent_reachable_fens = [
        f for f in reachable_fens
        if len(f.split()) > 1 and f.split()[1] != player_color and f not in exempt_fens
    ]

    # Pass 1: 1-Move Opponent Transpositions (Opponent plays m1 directly into our repertoire, no badge)
    for f_orig in opponent_reachable_fens:
        if len(results) >= MAX_TRANSPOSITIONS:
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

        for m1 in list(board_1.legal_moves):
            if len(results) >= MAX_TRANSPOSITIONS:
                break
            u1 = m1.uci().strip().lower()
            if u1 in covered_from_orig or u1 in inactive_from_orig:
                continue

            board_1.push(m1)
            t1_fen = clean_fen(board_1.fen())
            board_1.pop()

            if t1_fen in fen_to_pos and t1_fen != f_orig:
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

                    results.append({
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
                        "popularity": 50,
                    })

    # Pass 2: 2-Move Transpositions (Opponent plays m1, then WE play m2 to get back into repertoire)
    if len(results) < MAX_TRANSPOSITIONS:
        for f_orig in opponent_reachable_fens:
            if len(results) >= MAX_TRANSPOSITIONS:
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

            for m1 in list(board_1.legal_moves):
                if len(results) >= MAX_TRANSPOSITIONS:
                    break
                u1 = m1.uci().strip().lower()
                if u1 in covered_from_orig or u1 in inactive_from_orig:
                    continue

                board_1.push(m1)
                inter_fen = clean_fen(board_1.fen())
                p_inter = fen_to_pos.get(inter_fen)
                covered_from_inter = rep_adj_fen.get(inter_fen, set())
                inactive_from_inter = inactive_adj_fen.get(inter_fen, set())

                try:
                    for m2 in list(board_1.legal_moves):
                        if len(results) >= MAX_TRANSPOSITIONS:
                            break
                        u2 = m2.uci().strip().lower()
                        if (u1 in covered_from_orig and u2 in covered_from_inter) or u2 in inactive_from_inter:
                            continue

                        board_1.push(m2)
                        t2_fen = clean_fen(board_1.fen())
                        board_1.pop()

                        if t2_fen in fen_to_pos and t2_fen != f_orig and t2_fen != inter_fen:
                            # Forward-only check (eliminate backward cycles / shallower depth)
                            t2_depth = reachable_depths.get(t2_fen)
                            if orig_depth is not None and t2_depth is not None and t2_depth <= orig_depth:
                                continue

                            p_target = fen_to_pos.get(t2_fen)
                            key = (f_orig, t2_fen, f"{u1}_{u2}")
                            if key not in seen_keys:
                                seen_keys.add(key)

                                # User plays m2: evaluate soundness of our move
                                _, m2_exc = evaluate_user_move(p_inter, inter_fen, u2, p_target, covered_from_inter)
                                if m2_exc:
                                    # Lazy SAN calculation
                                    try:
                                        s2 = board_1.san(m2)
                                    except Exception:
                                        s2 = u2
                                    board_1.pop()
                                    try:
                                        s1 = board_1.san(m1)
                                    except Exception:
                                        s1 = u1
                                    board_1.push(m1)

                                    seq_str = f"{s1}  {s2}"
                                    results.append({
                                        "fen": f_orig,
                                        "target_fen": t2_fen,
                                        "move_san": seq_str,
                                        "path_sans": [s1, s2],
                                        "path_ucis": [u1, u2],
                                        "depth": 2,
                                        "type": "transposition_2",
                                        "turn": "user",
                                        "quality": "ausgezeichnet",
                                        "quality_label": "🟢 Ausgezeichnet",
                                        "popularity": 70,
                                    })
                except Exception:
                    pass

                board_1.pop()

    def sort_key(item):
        d_val = item["depth"]
        q_val = 0 if item["quality"] == "ausgezeichnet" else (1 if item["quality"] == "solide" else 2)
        return (d_val, q_val, -item.get("popularity", 0))

    return sorted(results, key=sort_key)



