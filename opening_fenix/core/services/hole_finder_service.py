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

    # Query for RepertoireMoves joined with Moves
    moves_with_rm = session.query(Move, RepertoireMove).join(
        RepertoireMove, Move.id == RepertoireMove.move_id
    ).filter(
        RepertoireMove.is_active == True,
        RepertoireMove.level == level,
        op
    ).all()


    # Build path strings for UI context
    def get_path_to_pos(pid, visited=None):
        if visited is None: visited = set()
        if pid in visited: return "..."
        visited.add(pid)
        
        m_in = session.query(Move).filter_by(to_position_id=pid).first()
        if not m_in: return "Start"
        return get_path_to_pos(m_in.from_position_id, visited) + " -> " + m_in.san

    for move, rm in moves_with_rm:
        mismatches.append({
            "fen": session.query(Position.fen).filter_by(id=move.from_position_id).scalar(),
            "move_san": move.san,
            "type": "priority_check",
            "popularity": move.priority_score * 100,
            "path": get_path_to_pos(move.from_position_id)
        })
    
    return sorted(mismatches, key=lambda x: x['popularity'], reverse=True)

