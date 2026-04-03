import os
import sys
import json
import subprocess
import chess
import chess.engine
from typing import Tuple, Callable, Optional
from sqlalchemy import or_

from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path, get_repertoire_db_path
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
                # Check if engine supports MultiPV
                analyze_kwargs = {"multipv": 20} if "MultiPV" in engine.options else {}
                result = engine.analyse(board, chess.engine.Limit(depth=depth), **analyze_kwargs)
                
                if not result:
                    continue

                best_score = result[0]['score'].white()
                
                good_moves = []
                if repertoire_uci:
                    good_moves.append(repertoire_uci)

                for info in result:
                    move = info['pv'][0]
                    score = info['score'].white()
                    
                    if abs(best_score.score(mate_score=100000) - score.score(mate_score=100000)) <= 30:
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
        
        return True, f"Analyse von {total_positions} Positionen abgeschlossen."

    except Exception as e:
        session.rollback()
        return False, f"Fehler bei der Analyse: {e}"
    finally:
        if engine:
            engine.quit()
        session.close()
        db.close()

def get_repertoire_analysis_status(repo_name: str) -> str:
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return "Repertoire nicht gefunden"

    db = DatabaseManager(db_path)
    session = db.get_session()
    
    try:
        player_color = get_meta(session, "color", "w")
        turn_filter = Position.fen.like(f'% {player_color} %')
        
        positions = session.query(Position.analysis_depth).filter(turn_filter).all()
        total_positions = len(positions)
        
        if total_positions == 0:
            return "Keine Spielerzüge"

        analyzed_depths = [d.analysis_depth for d in positions if d.analysis_depth is not None]
        
        analyzed_count = len(analyzed_depths)

        if analyzed_count == 0:
            return "Nicht analysiert"
        
        if analyzed_count < total_positions:
            return "Teilweise analysiert"
        
        min_depth = min(analyzed_depths)
        max_depth = max(analyzed_depths)
        
        if min_depth == max_depth:
            return f"Tiefe: {min_depth}"
        else:
            return f"Tiefe: Zwischen {min_depth} und {max_depth}"

    except Exception as e:
        print(f"Error getting analysis status for {repo_name}: {e}")
        return "Fehler bei Statusprüfung"
    finally:
        session.close()
        db.close()

def enrich_position(repo_name: str, fen: str, elo_category: str, engine_path: str, depth: int = 10) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    try:
        clean_fen = " ".join(fen.split(" ")[:4])
        pos = session.query(Position).filter_by(fen=clean_fen).first()
        if not pos:
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
                except: pass

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
                
                # Check if engine supports MultiPV
                analyze_kwargs = {"multipv": 10} if "MultiPV" in engine.options else {}
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
                        
                        if abs(best_score_val - score_val) <= 50:
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
