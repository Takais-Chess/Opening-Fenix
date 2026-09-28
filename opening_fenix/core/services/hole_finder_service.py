import collections
import json
import os
import sys
import subprocess
import time
import chess
import chess.engine
from typing import Optional, Callable, Dict, Any, List
from sqlalchemy.orm import Session
from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel, LichessData, Metadata
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.utils import get_repertoire_db_path, CASTLING_ALT, CASTLING_SANS
from opening_fenix.core.services.engine_cache_service import EngineCacheService
from opening_fenix.core.logger import logger

def run_hole_finder_task(repo_name, is_test, threshold, elo_range, mode="holes", level=None, find_rare=False,
                        engine_path=None, threads_count=1, item_callback=None, cancel_check=None, engine=None,
                        depth=18, progress_callback=None, recheck_unadded: bool = False):
    """
    Stand-alone task to find repertoire holes or priority mismatches.
    Creates its own DB session for thread safety.
    """
    db_path = get_repertoire_db_path(repo_name, is_test)
    db_manager = DatabaseManager(db_path)
    session = db_manager.get_session()
    
    try:
        if mode == "holes":
            return find_repertoire_holes(
                session, threshold, elo_range,
                include_user_gaps=False,
                engine_path=engine_path,
                threads_count=threads_count,
                depth=depth,
                item_callback=item_callback,
                cancel_check=cancel_check
            )
        elif mode == "unanswered":
            return find_unanswered_moves(
                session,
                threshold=threshold,
                cancel_check=cancel_check,
                item_callback=item_callback,
                progress_callback=progress_callback
            )
        elif mode == "level_check":
            return find_level_mismatches(session, cancel_check=cancel_check)
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
                progress_callback=progress_callback,
                recheck_unadded=recheck_unadded,
            )
        else:
            return find_priority_mismatches(session, level, threshold, find_rare=find_rare, cancel_check=cancel_check)
    finally:
        session.close()
        db_manager.close()

def find_repertoire_holes(session: Session, threshold: float, elo_range: str = "high",
                          include_user_gaps: bool = True,
                          engine_path: Optional[str] = None,
                          threads_count: int = 1,
                          depth: int = 18,
                          item_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                          cancel_check: Optional[Callable[[], bool]] = None,
                          engine: Optional[Any] = None,
                          cache_service: Optional[EngineCacheService] = None):
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
            # These should show up regardless of threshold_val when user gaps are requested
            if is_user and not rep_moves:
                if include_user_gaps and not is_exempt:
                    holes.append({
                        "fen": clean_fen,
                        "move_san": "—",
                        "type": "repertoire_gap",
                        "popularity": p_reach * 100,
                        "ply_depth": d,
                    })

            if p_reach < threshold_val:
                continue

            if is_user:
                if not rep_moves:
                    # User candidate logic (Lichess suggestions)
                    if include_user_gaps and not is_exempt:
                        lichess_moves = lichess_cache.get(clean_fen, {})
                        total_games = sum(v.get('total', 0) for v in lichess_moves.values())
                        if total_games > 0:
                            for uci, stats in lichess_moves.items():
                                move_total = stats.get('total', 0)
                                p_move = move_total / total_games
                                p_total = p_reach * p_move
                                if p_total >= threshold_val:
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
                                "move_uci": norm_uci,
                                "type": "opponent",
                                "popularity": p_total * 100,
                                "ply_depth": d,
                                "eval_loss": None,
                                "eval_loss_cp": None,
                                "best_move_uci": None,
                            })

    holes.sort(key=lambda x: x['popularity'], reverse=True)

    # Engine loss evaluation & live streaming
    if (engine or (engine_path and os.path.exists(engine_path))) and holes:
        if cache_service is None:
            cache_service = EngineCacheService()
        active_engine = engine
        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x08000000 | 0x00004000  # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS

        fen_to_holes = collections.defaultdict(list)
        for h in holes:
            if h.get("move_uci"):
                fen_to_holes[h["fen"]].append(h)

        try:
            for fen, f_holes in fen_to_holes.items():
                if cancel_check and cancel_check():
                    break
                clean_fen = " ".join(fen.split(" ")[:4])

                # Check Engine Cache first
                cached_eval = cache_service.get_eval_data(clean_fen, min_depth=depth)
                all_cached = False
                if cached_eval and "moves" in cached_eval and cached_eval.get("best_score") is not None:
                    all_cached = all(h.get("move_uci") in cached_eval["moves"] for h in f_holes)

                if all_cached:
                    best_score = cached_eval["best_score"]
                    best_uci = cached_eval.get("best_uci")
                    for h in f_holes:
                        m_u = h.get("move_uci")
                        score_m = cached_eval["moves"].get(m_u)
                        if score_m is not None and best_score is not None:
                            loss_cp = max(0, best_score - score_m)
                            h["eval_loss"] = round(loss_cp / 100.0, 2)
                            h["eval_loss_cp"] = loss_cp
                        h["best_move_uci"] = best_uci
                        if item_callback:
                            item_callback(h)
                    continue

                # Launch engine on demand
                if active_engine is None:
                    try:
                        active_engine = chess.engine.SimpleEngine.popen_uci(engine_path, creationflags=creationflags)
                        if "Threads" in active_engine.options:
                            active_engine.configure({"Threads": threads_count})
                    except Exception as e:
                        logger.warning(f"Could not start engine for hole eval: {e}")
                        break

                try:
                    board = chess.Board(clean_fen)
                except Exception:
                    continue

                legal_count = board.legal_moves.count()
                if legal_count == 0:
                    continue

                mpv_count = min(5, legal_count)
                try:
                    mpv_infos = active_engine.analyse(
                        board,
                        chess.engine.Limit(depth=depth),
                        multipv=mpv_count
                    )
                except Exception as e:
                    logger.debug(f"Engine analysis error on FEN {clean_fen}: {e}")
                    continue

                if not isinstance(mpv_infos, list):
                    mpv_infos = [mpv_infos]

                best_uci = None
                best_score = None
                move_scores = {}
                for info_item in mpv_infos:
                    pv = info_item.get("pv", [])
                    if pv:
                        m_u = pv[0].uci().lower()
                        s_obj = info_item.get("score")
                        s = s_obj.relative.score(mate_score=10000) if s_obj else None
                        move_scores[m_u] = s
                        if best_uci is None:
                            best_uci = m_u
                            best_score = s
                        elif s is not None and (best_score is None or s > best_score):
                            best_score = s
                            best_uci = m_u

                # Targeted root_moves analysis for candidate moves not in MultiPV
                for h in f_holes:
                    if cancel_check and cancel_check():
                        break
                    m_u = h.get("move_uci", "").lower()
                    if m_u and m_u not in move_scores:
                        try:
                            m_obj = chess.Move.from_uci(m_u)
                            if m_obj in board.legal_moves:
                                res = active_engine.analyse(
                                    board,
                                    chess.engine.Limit(depth=depth),
                                    root_moves=[m_obj]
                                )
                                if res and isinstance(res, list) and res[0].get("score"):
                                    s_val = res[0]["score"].relative.score(mate_score=10000)
                                    move_scores[m_u] = s_val
                        except Exception:
                            pass

                if best_uci:
                    eval_payload = {
                        "best_uci": best_uci,
                        "best_score": best_score,
                        "moves": move_scores,
                    }
                    try:
                        cache_service.set_eval_data(clean_fen, depth, best_uci, eval_payload)
                    except Exception:
                        pass

                for h in f_holes:
                    m_u = h.get("move_uci", "").lower()
                    score_m = move_scores.get(m_u)
                    if score_m is not None and best_score is not None:
                        loss_cp = max(0, best_score - score_m)
                        h["eval_loss"] = round(loss_cp / 100.0, 2)
                        h["eval_loss_cp"] = loss_cp
                    h["best_move_uci"] = best_uci
                    if item_callback:
                        item_callback(h)
        finally:
            if active_engine and active_engine is not engine:
                try:
                    active_engine.quit()
                except Exception:
                    pass
    elif item_callback:
        for h in holes:
            if cancel_check and cancel_check():
                break
            item_callback(h)

    return holes

def find_unanswered_moves(session: Session, threshold: float = 0.0,
                          cancel_check: Optional[Callable[[], bool]] = None,
                          item_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                          progress_callback: Optional[Callable[[int, int, str], None]] = None) -> List[Dict[str, Any]]:
    """
    Finds positions where it is our turn and we have no move in the repertoire
    (unanswered branches where our response is missing).
    """
    threshold_val = threshold / 100.0 if threshold > 0 else 0.0

    m = session.query(Metadata).filter_by(key="color").first()
    user_turn_char = m.value[0].lower() if (m and m.value) else 'w'

    all_positions = session.query(Position).all()
    id_to_fen = {p.id: p.fen for p in all_positions}

    rep_moves_db = session.query(Move).join(
        RepertoireMove, Move.id == RepertoireMove.move_id
    ).filter(RepertoireMove.is_active == True).all()

    rep_moves_from = collections.defaultdict(list)
    for rm in rep_moves_db:
        rep_moves_from[rm.from_position_id].append(rm)

    exempt_fens = {
        " ".join(row[0].split(" ")[:4])
        for row in session.query(Position.fen).filter(Position.is_hole_exempt == True).all()
    }

    # Root position
    sp = session.query(Position.id).filter(
        Position.fen.like("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%")
    ).first()
    if not sp:
        return []
    root_id = sp[0]

    reach_probs = {root_id: 1.0}
    depth_map = {root_id: 0}
    incoming_move_map = {}

    bfs_queue = collections.deque([(root_id, 0)])
    bfs_visited = set()
    pos_by_depth = []

    while bfs_queue:
        if cancel_check and cancel_check():
            return []
        pid, d = bfs_queue.popleft()
        if pid in bfs_visited:
            continue
        bfs_visited.add(pid)
        if d > 150:
            continue

        while len(pos_by_depth) <= d:
            pos_by_depth.append([])
        pos_by_depth[d].append(pid)

        nexts = rep_moves_from.get(pid, [])
        for m_obj in nexts:
            if m_obj.to_position_id:
                if m_obj.to_position_id not in incoming_move_map:
                    incoming_move_map[m_obj.to_position_id] = m_obj
                if m_obj.to_position_id not in bfs_visited:
                    bfs_queue.append((m_obj.to_position_id, d + 1))
                    depth_map[m_obj.to_position_id] = d + 1

    # Probability propagation
    for d, depth_list in enumerate(pos_by_depth):
        for pid in depth_list:
            p_reach = reach_probs.get(pid, 0.0)
            nexts = rep_moves_from.get(pid, [])
            if nexts:
                p_next = p_reach / len(nexts)
                for m_obj in nexts:
                    if m_obj.to_position_id:
                        reach_probs[m_obj.to_position_id] = reach_probs.get(m_obj.to_position_id, 0.0) + p_next

    results = []
    for d, depth_list in enumerate(pos_by_depth):
        for pid in depth_list:
            if cancel_check and cancel_check():
                break
            fen = id_to_fen.get(pid)
            if not fen:
                continue
            clean_fen = " ".join(fen.split(" ")[:4])
            if clean_fen in exempt_fens:
                continue

            parts = clean_fen.split(" ")
            is_user = len(parts) > 1 and parts[1].lower() == user_turn_char
            if not is_user:
                continue

            rep_moves = rep_moves_from.get(pid, [])
            p_reach = reach_probs.get(pid, 0.0)

            if p_reach < threshold_val:
                continue

            if not rep_moves:
                inc_m = incoming_move_map.get(pid)
                last_san = inc_m.san if inc_m else "—"
                last_uci = inc_m.uci if inc_m else None
                from_pid = inc_m.from_position_id if inc_m else None
                from_fen = id_to_fen.get(from_pid, clean_fen) if from_pid else clean_fen

                item = {
                    "fen": clean_fen,
                    "from_fen": from_fen,
                    "move_san": last_san,
                    "last_move_san": last_san,
                    "move_uci": last_uci,
                    "last_move_uci": last_uci,
                    "is_user_turn": True,
                    "status_key": "our_move_missing",
                    "type": "unanswered_user",
                    "popularity": p_reach * 100,
                    "ply_depth": d,
                }
                results.append(item)

    # Sort results: by popularity descending
    results.sort(key=lambda x: x["popularity"], reverse=True)

    if item_callback:
        for it in results:
            if cancel_check and cancel_check():
                break
            item_callback(it)

    return results

def find_level_mismatches(session: Session, cancel_check: Optional[Callable[[], bool]] = None):
    """
    Finds:
    1. Level Mismatches (Gaps): Positions reached at Path Level L where ALL user moves are Level > L.
    2. Orphaned Moves: Moves that are assigned a level < Path Level L (e.g., Level 1 move trapped behind Level 3).
    """
    if cancel_check and cancel_check():
        return []

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
        if cancel_check and cancel_check():
            return []
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
        if cancel_check and cancel_check():
            return []
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

def find_priority_mismatches(session: Session, level: int, threshold_pct: float, find_rare: bool = False, only_opponent: bool = True, cancel_check: Optional[Callable[[], bool]] = None):
    """Ported logic from CreatorBackend.find_priority_mismatches with pre-simulated impact and cancellation check."""
    if cancel_check and cancel_check():
        return []

    threshold = threshold_pct / 100.0
    
    # Get Repertoire Color (level changes only occur on opponent moves)
    m = session.query(Metadata).filter_by(key="color").first()
    player_color = m.value[0].lower() if (m and m.value) else 'w'

    mismatches = []
    
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload
    # Selection criteria: >= threshold (too important) OR <= threshold (too rare, including 0/NULL priority)
    op = or_(Move.priority_score <= threshold, Move.priority_score == None) if find_rare else Move.priority_score >= threshold

    # Query for RepertoireMoves joined with Moves
    moves_with_rm = session.query(Move, RepertoireMove).join(
        RepertoireMove, Move.id == RepertoireMove.move_id
    ).options(joinedload(Move.from_position)).filter(
        RepertoireMove.is_active == True,
        RepertoireMove.level == level,
        op
    ).all()

    if cancel_check and cancel_check():
        return []

    # Target level calculation
    levels = session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
    orders = [lvl.order for lvl in levels]
    target_level = None
    if level in orders:
        idx = orders.index(level)
        if find_rare:
            target_level = orders[idx + 1] if idx < len(orders) - 1 else None
        else:
            target_level = orders[idx - 1] if idx > 0 else None

    # Pre-build in-memory graph for lightning-fast downstream impact simulation
    rep_moves = (
        session.query(Move.id, Move.from_position_id, Move.to_position_id, RepertoireMove.level)
        .join(RepertoireMove, Move.id == RepertoireMove.move_id)
        .filter(RepertoireMove.is_active == True)
        .all()
    )
    incoming = collections.defaultdict(list)
    outgoing = collections.defaultdict(list)
    move_levels = {}
    move_to_pos = {}
    for mid, from_id, to_id, lvl in rep_moves:
        lvl_val = lvl if lvl is not None else 1
        move_levels[mid] = lvl_val
        move_to_pos[mid] = to_id
        incoming[to_id].append((from_id, mid))
        outgoing[from_id].append((to_id, mid))

    def simulate_move_impact(m_id, t_lvl):
        if t_lvl is None or m_id not in move_levels:
            return 0, 0
        if move_levels[m_id] == t_lvl:
            return 0, 0
        sim_levels = {m_id: t_lvl}
        changed_mids = {m_id}
        visited_rec = set()
        stack = [move_to_pos[m_id]] if m_id in move_to_pos else []
        while stack:
            pos_id = stack.pop()
            if pos_id in visited_rec:
                continue
            visited_rec.add(pos_id)
            inc = incoming.get(pos_id, [])
            if not inc:
                continue
            effective = min(sim_levels.get(mid, move_levels.get(mid, 1)) for _, mid in inc)
            out = outgoing.get(pos_id, [])
            if not out:
                continue
            if len(out) > 1:
                for to_id, mid in out:
                    curr = sim_levels.get(mid, move_levels.get(mid, 1))
                    if curr < effective:
                        sim_levels[mid] = effective
                        changed_mids.add(mid)
                        stack.append(to_id)
            else:
                to_id, mid = out[0]
                curr = sim_levels.get(mid, move_levels.get(mid, 1))
                if curr != effective:
                    sim_levels[mid] = effective
                    changed_mids.add(mid)
                    stack.append(to_id)
        final_changed = {mid for mid in changed_mids if sim_levels.get(mid, move_levels[mid]) != move_levels[mid]}
        changed_pos = {move_to_pos[mid] for mid in final_changed if mid in move_to_pos}
        return max(1, len(changed_pos)), max(1, len(final_changed))

    # Pre-build in-memory parent map to construct path strings for UI context without query overhead
    parent_map = {}
    for from_pos_id, to_pos_id, san, prio in session.query(Move.from_position_id, Move.to_position_id, Move.san, Move.priority_score).all():
        prio_val = prio or 0.0
        existing = parent_map.get(to_pos_id)
        if not existing or prio_val > existing[2]:
            parent_map[to_pos_id] = (from_pos_id, san, prio_val)

    # Build path strings in memory
    def get_path_to_pos(pid, visited=None):
        seen = set()
        sans = []
        curr = pid
        while curr and curr not in seen:
            seen.add(curr)
            parent_info = parent_map.get(curr)
            if not parent_info:
                break
            sans.append(parent_info[1])
            curr = parent_info[0]
        sans.reverse()
        return "Start" if not sans else "Start -> " + " -> ".join(sans)

    def get_depth_to_pos(pid, visited=None):
        seen = set()
        depth = 0
        curr = pid
        while curr and curr not in seen:
            seen.add(curr)
            parent_info = parent_map.get(curr)
            if not parent_info:
                break
            depth += 1
            curr = parent_info[0]
        return depth

    for move, rm in moves_with_rm:
        if cancel_check and cancel_check():
            return []
        if only_opponent:
            if not move.from_position or not move.from_position.fen:
                continue
            parts = move.from_position.fen.strip().split()
            move_turn = parts[1].lower() if len(parts) > 1 else 'w'
            if move_turn == player_color:
                continue  # Level changes only happen on opponent's moves

        pos_cnt, mov_cnt = simulate_move_impact(move.id, target_level) if target_level is not None else (0, 0)

        mismatches.append({
            "fen": move.from_position.fen if move.from_position else None,
            "move_san": move.san,
            "move_uci": move.uci,
            "move_id": move.id,
            "current_level": rm.level,
            "target_level": target_level,
            "impact": {
                "positions_changed": pos_cnt,
                "moves_changed": mov_cnt,
                "target_level": target_level,
            },
            "from_position_id": move.from_position_id,
            "to_position_id": move.to_position_id,
            "type": "priority_check",
            "popularity": (move.priority_score or 0.0) * 100,
            "path": get_path_to_pos(move.from_position_id),
            "ply_depth": get_depth_to_pos(move.from_position_id),
        })
    
    return sorted(mismatches, key=lambda x: x['popularity'], reverse=True)


def find_repertoire_transpositions(session: Session, elo_range: str = "high",
                                   engine_path: str = None, threads_count: int = 1,
                                   item_callback = None, cancel_check = None,
                                   engine = None, max_transpositions: int = None,
                                   cache_service = None, depth: int = 25,
                                   progress_callback = None, only_1move: bool = False,
                                   recheck_unadded: bool = False):
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
                                    if eval_data is None and cache_service:
                                        # 1. Check persistent global cache
                                        cached_eval = cache_service.get_eval_data(inter_fen, min_depth=target_engine_depth)
                                        if cached_eval is not None:
                                            has_scores = cached_eval.get("best_score") is not None
                                            u2_in_cache = (u2 == cached_eval.get("best_uci")) or (u2 in cached_eval.get("moves", {}))
                                            if has_scores and u2_in_cache:
                                                eval_data = cached_eval
                                                engine_eval_cache[inter_fen] = eval_data
                                            elif not recheck_unadded:
                                                eval_data = cached_eval
                                                engine_eval_cache[inter_fen] = eval_data

                                    need_engine_eval = False
                                    if eval_data is None:
                                        need_engine_eval = (active_engine is not None)
                                    elif recheck_unadded and active_engine is not None:
                                        if eval_data.get("best_score") is None:
                                            need_engine_eval = True
                                        elif u2 not in eval_data.get("moves", {}):
                                            best_s = eval_data.get("best_score")
                                            moves_dict = eval_data.get("moves", {})
                                            worst_s = min(moves_dict.values()) if moves_dict else None
                                            if best_s is not None and worst_s is not None and (best_s - worst_s) <= 10:
                                                need_engine_eval = True

                                    if need_engine_eval and active_engine is not None:
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
                                                    cache_service.set_eval_data(inter_fen, target_engine_depth, best_uci, eval_data)

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
                                                    if cp_loss <= 0:
                                                        quality = "ausgezeichnet"
                                                        quality_label = "🟢 Ausgezeichnet"
                                                    else:
                                                        quality = "solide"
                                                        quality_label = f"🟡 Solide (-{cp_loss} cp)"
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


def is_transposition_path_in_repertoire(session: Session, item: dict) -> bool:
    """Returns True if all moves along the transposition path are already active in the repertoire."""
    if not item or not isinstance(item, dict):
        return False
    search_fen = item.get("fen") or item.get("search_fen")
    path_ucis = item.get("path_ucis") or ([item.get("move_uci")] if item.get("move_uci") else [])
    if not search_fen or not path_ucis:
        return False

    try:
        board = chess.Board(search_fen)
        for uci in path_ucis:
            if not uci:
                return False
            curr_fen = board.fen()
            clean_fen = " ".join(curr_fen.strip().split()[:4])
            db_pos = session.query(Position).filter(Position.fen.op('GLOB')(clean_fen + "*")).first()
            if not db_pos:
                return False
            norm_uci = uci.strip().lower()
            alt_uci = CASTLING_ALT.get(norm_uci)
            check_ucis = [norm_uci, uci]
            if alt_uci:
                check_ucis.append(alt_uci)
            rep = (
                session.query(RepertoireMove)
                .join(Move, RepertoireMove.move_id == Move.id)
                .filter(
                    Move.from_position_id == db_pos.id,
                    Move.uci.in_(check_ucis),
                    RepertoireMove.is_active == True
                )
                .first()
            )
            if not rep:
                return False
            m = chess.Move.from_uci(uci)
            if m not in board.legal_moves:
                return False
            board.push(m)
        return True
    except Exception:
        return False


def save_cached_transpositions(session: Session, items: list, merge: bool = True) -> int:
    """
    Saves unadded transposition items to repertoire metadata, pruning already-added moves.
    Returns the count of saved items.
    """
    try:
        from opening_fenix.core.db.meta_utils import get_meta, set_meta
        candidate_items = []
        if merge:
            raw = get_meta(session, "cached_unadded_transpositions")
            if raw:
                try:
                    existing = json.loads(raw)
                    if isinstance(existing, list):
                        candidate_items.extend(existing)
                except Exception:
                    pass
        if items:
            candidate_items.extend(items)

        dedup = {}
        for h in candidate_items:
            if not isinstance(h, dict):
                continue
            if is_transposition_path_in_repertoire(session, h):
                continue
            f = " ".join((h.get("fen") or h.get("search_fen") or "").strip().split()[:4])
            ucis = tuple(h.get("path_ucis") or ([h.get("move_uci")] if h.get("move_uci") else []))
            key = (f, ucis, h.get("target_fen", ""))
            dedup[key] = h

        valid_items = list(dedup.values())
        set_meta(session, "cached_unadded_transpositions", json.dumps(valid_items))
        commit_with_retry(session)
        return len(valid_items)
    except Exception as e:
        logger.warning(f"save_cached_transpositions error: {e}")
        return 0


def load_cached_transpositions(session: Session) -> list:
    """Loads saved unadded transpositions from repertoire metadata, pruning any already added."""
    try:
        from opening_fenix.core.db.meta_utils import get_meta, set_meta
        raw = get_meta(session, "cached_unadded_transpositions")
        if not raw:
            return []
        items = json.loads(raw)
        if not isinstance(items, list):
            return []

        valid_items = []
        pruned_count = 0
        for h in items:
            if isinstance(h, dict):
                if is_transposition_path_in_repertoire(session, h):
                    pruned_count += 1
                else:
                    valid_items.append(h)

        if pruned_count > 0:
            set_meta(session, "cached_unadded_transpositions", json.dumps(valid_items))
            session.commit()
        return valid_items
    except Exception as e:
        logger.warning(f"load_cached_transpositions error: {e}")
        return []




