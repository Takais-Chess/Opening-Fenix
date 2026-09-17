import os
import sys
import json
import subprocess
import chess
import chess.engine
from typing import Tuple, Callable, Optional
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager, commit_with_retry
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path
from opening_fenix.core.services.priority_service import calculate_local_priority_scores
from opening_fenix.core.services.lichess_service import ELO_MAPPING, LichessData
from opening_fenix.core.translation import tr_ui
import collections
import urllib.request
import urllib.parse

def order_positions_topologically(session: Session, positions: list) -> list:
    """
    Sorts positions in Breadth-First Search (BFS) / topological order starting from the root position(s).
    
    Analyzing positions closer to the root first seeds Stockfish's in-memory Transposition Table (TT)
    with evaluations of subtrees, maximizing hash hits and significantly speeding up subsequent searches
    deeper down the tree.
    """
    if len(positions) <= 1:
        return positions

    # Fetch move graph (from_pos -> to_pos)
    all_moves = session.query(Move.from_position_id, Move.to_position_id).all()
    graph = collections.defaultdict(list)
    has_incoming = set()
    all_from_ids = set()

    for f_id, t_id in all_moves:
        graph[f_id].append(t_id)
        has_incoming.add(t_id)
        all_from_ids.add(f_id)

    queue = collections.deque()
    seen = set()

    # 1. Look for standard starting FEN
    start_pos = session.query(Position.id).filter(
        Position.fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
    ).first()

    if start_pos:
        start_id = start_pos[0]
        queue.append(start_id)
        seen.add(start_id)

    # 2. Add any other root positions (in-degree 0) for non-standard or multi-root repertoires
    for f_id in sorted(all_from_ids):
        if f_id not in has_incoming and f_id not in seen:
            queue.append(f_id)
            seen.add(f_id)

    pos_id_order = {}
    order = 0
    while queue:
        curr = queue.popleft()
        pos_id_order[curr] = order
        order += 1
        for nxt in graph.get(curr, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)

    # Sort positions by BFS discovery order; unreached/orphan positions sort deterministically by id
    return sorted(positions, key=lambda p: (pos_id_order.get(p.id, 999999999), p.id))

def run_db_analysis(repo_name: str, engine_path: str, depth: int, threads: int, progress_callback: Optional[Callable[[int], None]] = None, check_cancel: Optional[Callable[[], bool]] = None, hash_size: int = 256) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()

    engine = None
    try:
        player_color = get_meta(session, "color", "w")
        turn_filter = Position.fen.like(f'% {player_color} %')

        query = session.query(Position).filter(
            turn_filter,
            or_(Position.analysis_depth == None, Position.analysis_depth < depth)
        )
        
        positions_to_analyze = query.all()
        total_positions = len(positions_to_analyze)
        if total_positions == 0:
            return True, f"Alle Positionen sind bereits auf Tiefe {depth} oder tiefer analysiert."

        # Order positions in BFS / topological order to maximize Stockfish hash hits
        positions_to_analyze = order_positions_topologically(session, positions_to_analyze)

        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NO_WINDOW (0x08000000) | BELOW_NORMAL_PRIORITY_CLASS (0x00004000)
            creationflags = 0x08000000 | 0x00004000

        engine = chess.engine.SimpleEngine.popen_uci(engine_path, creationflags=creationflags)
        engine.configure({"Threads": threads, "Hash": hash_size})

        def analyse_with_cancel(board_to_analyse, limit, multipv=1):
            if isinstance(engine, chess.engine.SimpleEngine):
                results = {}
                try:
                    with engine.analysis(board_to_analyse, limit, multipv=multipv) as analysis:
                        for info in analysis:
                            if check_cancel and check_cancel():
                                break
                            pv_idx = info.get("multipv", 1) - 1
                            results[pv_idx] = info
                    return [results[k] for k in sorted(results.keys()) if "pv" in results[k] and results[k]["pv"]]
                except Exception:
                    if check_cancel and check_cancel():
                        return []
                    raise
            return engine.analyse(board_to_analyse, limit, multipv=multipv)

        for i, pos in enumerate(positions_to_analyze):
            if check_cancel and check_cancel():
                try:
                    commit_with_retry(session)
                except Exception:
                    session.rollback()
                return False, "Analyse abgebrochen. Bisheriger Fortschritt wurde gespeichert."
            
            # Refresh position state to avoid ObjectDeletedError/StaleDataError if modified or deleted in Creator
            current_pos = session.get(Position, pos.id)
            if current_pos is None:
                if progress_callback:
                    pct = int((i + 1) * 100 / total_positions)
                    try:
                        progress_callback(pct, i + 1, total_positions)
                    except TypeError:
                        progress_callback(pct)
                continue

            board = chess.Board(current_pos.fen)
            
            repertoire_move = session.query(Move).join(RepertoireMove).filter(Move.from_position_id == current_pos.id).first()
            repertoire_uci = repertoire_move.uci if repertoire_move else None

            try:
                # --- STAGE 1: DISCOVERY ---
                # Quick search to see if we actually need high MultiPV
                discovery_depth = min(depth, 10)
                discovery_multipv = 5
                if "MultiPV" in engine.options:
                    opt = engine.options["MultiPV"]
                    max_allowed = opt.max if (hasattr(opt, 'max') and opt.max is not None) else 5
                    discovery_multipv = min(5, max_allowed)
                
                # Fast look
                discovery_res = analyse_with_cancel(board, chess.engine.Limit(depth=discovery_depth), multipv=discovery_multipv)
                
                if check_cancel and check_cancel():
                    try:
                        commit_with_retry(session)
                    except Exception:
                        session.rollback()
                    return False, "Analyse abgebrochen. Bisheriger Fortschritt wurde gespeichert."

                # --- STAGE 2: DECISION & DEEPENING ---
                final_multipv = 1
                if len(discovery_res) > 1:
                    best_discover = discovery_res[0]['score'].white().score(mate_score=100000)
                    second_discover = discovery_res[1]['score'].white().score(mate_score=100000)
                    
                    # If the gap is small (< 150cp), we keep looking at multiple moves.
                    # Otherwise, we focus resources on the best move to reach depth faster.
                    if abs(best_discover - second_discover) < 150:
                        final_multipv = discovery_multipv

                # Full analysis to target depth
                result = analyse_with_cancel(board, chess.engine.Limit(depth=depth), multipv=final_multipv)
                
                if check_cancel and check_cancel():
                    try:
                        commit_with_retry(session)
                    except Exception:
                        session.rollback()
                    return False, "Analyse abgebrochen. Bisheriger Fortschritt wurde gespeichert."
                
                if not result:
                    continue

                best_score = result[0]['score'].white()
                
                good_moves = []
                if repertoire_uci:
                    good_moves.append(repertoire_uci)

                for info in result:
                    if 'pv' not in info or not info['pv']: continue
                    move = info['pv'][0]
                    score = info['score'].white()
                    # Use a more permissive threshold at lower depths (<= 17) to catch more "good" candidate moves.
                    threshold = 50 if depth <= 17 else 30
                    if abs(best_score.score(mate_score=100000) - score.score(mate_score=100000)) <= threshold:
                        if move.uci() not in good_moves:
                            good_moves.append(move.uci())

                current_pos = session.get(Position, pos.id)
                if current_pos is not None:
                    current_pos.good_moves = json.dumps(list(set(good_moves)))
                    current_pos.analysis_depth = depth

            except Exception as e:
                print(f"Error analyzing FEN {pos.fen}: {e}")
                current_pos = session.get(Position, pos.id)
                if current_pos is not None:
                    current_pos.good_moves = json.dumps([])

            if progress_callback:
                pct = int((i + 1) * 100 / total_positions)
                try:
                    progress_callback(pct, i + 1, total_positions)
                except TypeError:
                    progress_callback(pct)
            
            if (i + 1) % 10 == 0 or (i + 1) == total_positions:
                try:
                    commit_with_retry(session)
                except Exception as commit_err:
                    session.rollback()
                    from opening_fenix.core.logger import logger
                    logger.warning(f"Batch commit warning during analysis: {commit_err}")
        
        # Invalidate cache after successful analysis
        set_meta(session, "ana_cache_count", "-1")
        try:
            commit_with_retry(session)
        except Exception:
            session.rollback()
        
        return True, f"Analyse von {total_positions} Positionen abgeschlossen."

    except Exception as e:
        session.rollback()
        return False, f"Fehler bei der Analyse: {e}"
    finally:
        if engine:
            engine.quit()
        session.close()
        db.close()

def _resolve_status(status_key: str) -> str:
    if not status_key:
        return ""
    if status_key == "repo_not_found":
        return tr_ui("analysis.repo_not_found", "Repertoire nicht gefunden")
    if status_key == "no_player_moves":
        return tr_ui("analysis.no_player_moves", "Keine Spielerzüge")
    if status_key == "not_analyzed":
        return tr_ui("analysis.not_analyzed", "Nicht analysiert")
    if status_key == "partially_analyzed":
        return tr_ui("analysis.partially_analyzed", "Teilweise analysiert")
    if status_key == "error_checking_status":
        return tr_ui("analysis.error_checking_status", "Fehler bei Statusprüfung")
    if status_key.startswith("depth:"):
        parts = status_key.split(":")
        depth_val = parts[1] if len(parts) > 1 else "-"
        return tr_ui("analysis.depth", "Tiefe: {depth}", depth=depth_val)
    if status_key.startswith("depth_range:"):
        parts = status_key.split(":")
        min_val = parts[1] if len(parts) > 1 else "-"
        max_val = parts[2] if len(parts) > 2 else "-"
        return tr_ui("analysis.depth_range", "Tiefe: Zwischen {min} und {max}", min=min_val, max=max_val)
    
    # Fallback to legacy string if it contains German words
    if status_key == "Keine Spielerzüge":
        return tr_ui("analysis.no_player_moves", "Keine Spielerzüge")
    if status_key == "Nicht analysiert":
        return tr_ui("analysis.not_analyzed", "Nicht analysiert")
    if status_key == "Teilweise analysiert":
        return tr_ui("analysis.partially_analyzed", "Teilweise analysiert")
    
    import re
    if "Tiefe: Zwischen" in status_key:
        m = re.search(r"Zwischen\s+(\d+)\s+und\s+(\d+)", status_key)
        if m:
            return tr_ui("analysis.depth_range", "Tiefe: Zwischen {min} und {max}", min=m.group(1), max=m.group(2))
    if "Tiefe:" in status_key:
        m = re.search(r"Tiefe:\s+(\d+)", status_key)
        if m:
            return tr_ui("analysis.depth", "Tiefe: {depth}", depth=m.group(1))
    return status_key

def get_repertoire_analysis_status(repo_name: str, session: Optional[Session] = None) -> str:
    db = None
    if session is None:
        db_path = get_repertoire_db_path(repo_name)
        if not os.path.exists(db_path):
            return _resolve_status("repo_not_found")
        db = DatabaseManager(db_path)
        session = db.get_session()
    
    try:
        player_color = get_meta(session, "color", "w")
        turn_filter = Position.fen.like(f'% {player_color} %')
        
        # Performance check: Compare with cache
        total_p = session.query(func.count(Position.id)).scalar() or 0
        cached_count = get_meta(session, "ana_cache_count", "-1")
        cached_status = get_meta(session, "ana_cache_status", "")
        
        if str(total_p) == str(cached_count) and cached_status:
            return _resolve_status(cached_status)

        # If no valid cache, calculate with FAST SQL
        stats = session.query(
            func.count(Position.id),
            func.count(Position.analysis_depth),
            func.min(Position.analysis_depth),
            func.max(Position.analysis_depth)
        ).filter(turn_filter).first()
        
        total_player_pos, analyzed_count, min_depth, max_depth = stats
        
        status_key = ""
        if not total_player_pos or total_player_pos == 0:
            status_key = "no_player_moves"
        elif not analyzed_count or analyzed_count == 0:
            status_key = "not_analyzed"
        elif analyzed_count < total_player_pos:
            status_key = "partially_analyzed"
        elif min_depth == max_depth:
            status_key = f"depth:{min_depth}"
        else:
            status_key = f"depth_range:{min_depth}:{max_depth}"

        # Save to cache
        set_meta(session, "ana_cache_count", total_p)
        set_meta(session, "ana_cache_status", status_key)
        session.commit()
        return _resolve_status(status_key)

    except Exception as e:
        print(f"Error getting analysis status for {repo_name}: {e}")
        return _resolve_status("error_checking_status")
    finally:
        if db:
            session.close()
            db.close()

def enrich_position(repo_name: str, fen: str, elo_category: str, engine_path: str, depth: int = 10) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    from opening_fenix.core.logger import logger
    logger.info(f"enrich_position: Using DB at {db_path}")
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    try:
        clean_fen = " ".join(fen.strip().split()[:4])
        pos = session.query(Position).filter_by(fen=clean_fen).first()
        if not pos:
            # Fallback for old databases that might have full FENs or slightly different spacing
            pos = session.query(Position).filter(Position.fen.like(f"{clean_fen}%")).first()
            if not pos:
                return False, "Position not found in DB."

        positions_to_check = [pos]
        parents = session.query(Position).join(Move, Move.from_position_id == Position.id).filter(Move.to_position_id == pos.id).all()
        positions_to_check.extend(parents)
        
        user_color = get_meta(session, "color", "w")
        # Support LICHESS_TOKEN from environment for CI/CD
        lichess_token = os.environ.get("LICHESS_TOKEN")
        if not lichess_token:
            config_path = os.path.join(get_user_dir(), "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        conf = json.load(f)
                        lichess_token = conf.get("lichess_token")
                except Exception as e:
                    from opening_fenix.core.logger import logger
                    logger.debug(f"Could not read config.json for Lichess token: {e}")

        for p_obj in positions_to_check:
            p_clean = " ".join(p_obj.fen.split(" ")[:4])
            
            existing_lichess = session.query(LichessData).filter_by(fen=p_clean, elo_range=elo_category).first()
            if not existing_lichess:
                ratings = ELO_MAPPING.get(elo_category, ['1800', '2000'])
                if elo_category == 'masters':
                    url = f"https://explorer.lichess.org/masters?variant=standard&fen={urllib.parse.quote(p_clean)}"
                else:
                    url = f"https://explorer.lichess.org/lichess?variant=standard&fen={urllib.parse.quote(p_clean)}&ratings={','.join(ratings)}&speeds=rapid,classical"
                
                try:
                    headers = {'User-Agent': 'OpeningFenix/1.0'}
                    if lichess_token and lichess_token != "YOUR_TOKEN_HERE":
                        headers['Authorization'] = f'Bearer {lichess_token}'

                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read().decode('utf-8'))
                        moves_data = data.get('moves', [])
                        if moves_data:
                            moves_dict = {
                                move['uci']: {
                                    'white': move.get('white', 0),
                                    'draws': move.get('draws', 0),
                                    'black': move.get('black', 0),
                                    'total': move.get('white', 0) + move.get('draws', 0) + move.get('black', 0)
                                } for move in moves_data if 'uci' in move
                            }
                            # Double check to prevent race condition during long network request
                            if not session.query(LichessData).filter_by(fen=p_clean, elo_range=elo_category).first():
                                session.add(LichessData(fen=p_clean, elo_range=elo_category, moves_json=json.dumps(moves_dict)))
                                try:
                                    session.flush()
                                except Exception as inner_e:
                                    session.rollback()
                                    from opening_fenix.core.logger import logger
                                    logger.debug(f"Ignored Lichess data insert collision for {p_clean}")
                except Exception as e:
                    print(f"Lichess fetch failed for enrichment of {p_clean}: {e}")

        if engine_path and os.path.exists(engine_path) and (pos.analysis_depth is None or pos.analysis_depth < depth):
            engine = None
            try:
                creationflags = 0
                if sys.platform == "win32":
                    # CREATE_NO_WINDOW (0x08000000) | BELOW_NORMAL_PRIORITY_CLASS (0x00004000)
                    creationflags = 0x08000000 | 0x00004000
                engine = chess.engine.SimpleEngine.popen_uci(engine_path, creationflags=creationflags)
                engine.configure({"Threads": 1})
                board = chess.Board(pos.fen) 
                
                try:
                    # --- STAGE 1: DISCOVERY ---
                    discovery_depth = min(depth, 10)
                    discovery_multipv = 5
                    if "MultiPV" in engine.options:
                        opt = engine.options["MultiPV"]
                        max_allowed = opt.max if (hasattr(opt, 'max') and opt.max is not None) else 5
                        discovery_multipv = min(5, max_allowed)
                    
                    discovery_res = engine.analyse(board, chess.engine.Limit(depth=discovery_depth), multipv=discovery_multipv)

                    # --- STAGE 2: DECISION & DEEPENING ---
                    final_multipv = 1
                    if len(discovery_res) > 1:
                        best_discover = discovery_res[0]['score'].white().score(mate_score=100000)
                        second_discover = discovery_res[1]['score'].white().score(mate_score=100000)
                        
                        if abs(best_discover - second_discover) < 150:
                            final_multipv = discovery_multipv

                    result = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=final_multipv)
                    
                    if result:
                        best_score_info = result[0]['score'].white()
                        best_score_val = best_score_info.score(mate_score=100000)
                        
                        good_moves = []
                        rep_moves = session.query(Move).join(RepertoireMove).filter(Move.from_position_id == pos.id).all()
                        for rm in rep_moves:
                            good_moves.append(rm.uci)

                        for info in result:
                            if 'pv' not in info or not info['pv']: continue
                            move = info['pv'][0]
                            score = info['score'].white()
                            score_val = score.score(mate_score=100000)
                            # Use a more permissive threshold at lower depths (<= 17) to catch more "good" candidate moves.
                            threshold = 50 if depth <= 17 else 30
                            if abs(best_score_val - score_val) <= threshold:
                                if move.uci() not in good_moves:
                                    good_moves.append(move.uci())
                        
                        pos.good_moves = json.dumps(list(set(good_moves)))
                        pos.analysis_depth = depth
                        session.flush()
                except Exception as e:
                    print(f"Engine analysis failed for enrichment: {e}")
            finally:
                if engine: engine.quit()

        parent_moves = session.query(Move).filter_by(to_position_id=pos.id).all()
        if parent_moves:
            for pm in parent_moves:
                calculate_local_priority_scores(session, pm.from_position_id, elo_category)
        else:
            calculate_local_priority_scores(session, pos.id, elo_category)
            
        session.commit()
        return True, "Enrichment complete."

    except Exception as e:
        session.rollback()
        print(f"Enrichment error: {e}")
        return False, str(e)
    finally:
        session.close()
        db.close()
