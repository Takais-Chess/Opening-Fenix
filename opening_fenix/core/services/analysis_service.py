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
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path
from opening_fenix.core.services.priority_service import calculate_local_priority_scores
from opening_fenix.core.services.lichess_service import ELO_MAPPING, LichessData
import urllib.request
import urllib.parse

def run_db_analysis(repo_name: str, engine_path: str, depth: int, threads: int, progress_callback: Optional[Callable[[int], None]] = None, check_cancel: Optional[Callable[[], bool]] = None) -> Tuple[bool, str]:
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

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        engine = chess.engine.SimpleEngine.popen_uci(engine_path, creationflags=creationflags)
        engine.configure({"Threads": threads})

        for i, pos in enumerate(positions_to_analyze):
            if check_cancel and check_cancel():
                session.commit()
                return False, "Analyse abgebrochen. Bisheriger Fortschritt wurde gespeichert."
            
            board = chess.Board(pos.fen)
            
            repertoire_move = session.query(Move).join(RepertoireMove).filter(Move.from_position_id == pos.id).first()
            repertoire_uci = repertoire_move.uci if repertoire_move else None

            try:
                # MultiPV is automatically managed by the analysis context manager in python-chess.
                # Setting it manually via configure can cause warnings or errors depending on the engine.
                multi_pv = 1
                if "MultiPV" in engine.options:
                    # Limit to whatever the engine supports or 20
                    opt = engine.options["MultiPV"]
                    max_allowed = opt.max if (hasattr(opt, 'max') and opt.max is not None) else 20
                    multi_pv = min(20, max_allowed)
                
                result = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multi_pv)
                
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

                pos.good_moves = json.dumps(list(set(good_moves)))
                pos.analysis_depth = depth

            except Exception as e:
                print(f"Error analyzing FEN {pos.fen}: {e}")
                pos.good_moves = json.dumps([])

            if progress_callback:
                progress_callback(int((i + 1) * 100 / total_positions))
            
            if (i + 1) % 10 == 0 or (i + 1) == total_positions:
                 session.commit()
        
        # Invalidate cache after successful analysis
        set_meta(session, "ana_cache_count", "-1")
        session.commit()
        
        return True, f"Analyse von {total_positions} Positionen abgeschlossen."

    except Exception as e:
        session.rollback()
        return False, f"Fehler bei der Analyse: {e}"
    finally:
        if engine:
            engine.quit()
        session.close()
        db.close()

def get_repertoire_analysis_status(repo_name: str, session: Optional[Session] = None) -> str:
    db = None
    if session is None:
        db_path = get_repertoire_db_path(repo_name)
        if not os.path.exists(db_path):
            return "Repertoire nicht gefunden"
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
            return cached_status

        # If no valid cache, calculate with FAST SQL
        # We need: total positions for player, count of analyzed, min depth, max depth
        stats = session.query(
            func.count(Position.id),
            func.count(Position.analysis_depth),
            func.min(Position.analysis_depth),
            func.max(Position.analysis_depth)
        ).filter(turn_filter).first()
        
        total_player_pos, analyzed_count, min_depth, max_depth = stats
        
        status = ""
        if not total_player_pos or total_player_pos == 0:
            status = "Keine Spielerzüge"
        elif not analyzed_count or analyzed_count == 0:
            status = "Nicht analysiert"
        elif analyzed_count < total_player_pos:
            status = "Teilweise analysiert"
        elif min_depth == max_depth:
            status = f"Tiefe: {min_depth}"
        else:
            status = f"Tiefe: Zwischen {min_depth} und {max_depth}"

        # Save to cache
        set_meta(session, "ana_cache_count", total_p)
        set_meta(session, "ana_cache_status", status)
        session.commit()
        return status

    except Exception as e:
        print(f"Error getting analysis status for {repo_name}: {e}")
        return "Fehler bei Statusprüfung"
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
                            session.add(LichessData(fen=p_clean, elo_range=elo_category, moves_json=json.dumps(moves_dict)))
                            session.flush()
                except Exception as e:
                    print(f"Lichess fetch failed for enrichment of {p_clean}: {e}")

        if engine_path and os.path.exists(engine_path) and (pos.analysis_depth is None or pos.analysis_depth < depth):
            engine = None
            try:
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NO_WINDOW
                engine = chess.engine.SimpleEngine.popen_uci(engine_path, creationflags=creationflags)
                engine.configure({"Threads": 1})
                board = chess.Board(pos.fen) 
                
                try:
                    # Use actual MultiPV from engine options if available, capped at 10 for speed
                    analyze_kwargs = {}
                    if "MultiPV" in engine.options:
                        opt = engine.options["MultiPV"]
                        max_allowed = opt.max if (hasattr(opt, 'max') and opt.max is not None) else 10
                        analyze_kwargs["multipv"] = min(10, max_allowed)
                    
                    result = engine.analyse(board, chess.engine.Limit(depth=depth), **analyze_kwargs)
                    
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
