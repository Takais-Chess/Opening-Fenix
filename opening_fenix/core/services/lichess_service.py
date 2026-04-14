import os
import json
import time
import urllib.request
import urllib.parse
from typing import Tuple, Callable, Optional, Dict, List

from opening_fenix.core.db.models import Position, Move, RepertoireMove, LichessData
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path, _update_lichess_delay_config

ELO_MAPPING: Dict[str, List[str]] = {
    'low': ['400', '1000', '1200'],
    'mid': ['1600'],
    'high': ['2200', '2500'],
    'masters': []
}

def run_lichess_import(repo_name: str, elo_category: str, progress_callback: Optional[Callable[[int], None]] = None, check_cancel: Optional[Callable[[], bool]] = None) -> Tuple[bool, str]:
    from opening_fenix.core.db.models import LichessData # local import if needed
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    config = {}
    config_path = os.path.join(get_user_dir(), "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                pass
    
    current_delay = config.get("lichess_delay", 0.5)
    # Support LICHESS_TOKEN from environment for CI/CD
    lichess_token = os.environ.get("LICHESS_TOKEN") or config.get("lichess_token", "")
    
    print(f"INFO: Starting Lichess import with a delay of {current_delay:.3f}s")

    try:
        existing_fens_query = session.query(LichessData.fen).filter_by(elo_range=elo_category)
        
        # Now querying all positions that don't have Lichess data yet, regardless of turn
        positions_to_query = session.query(Position).filter(
            ~Position.fen.in_(existing_fens_query)
        ).distinct().all()

        total_pos = len(positions_to_query)

        if not positions_to_query:
            set_meta(session, "lichess_elo", elo_category)
            # Invalidate coverage cache to force recalculation with new Elo if changed
            set_meta(session, "cov_cache_count", "-1")
            session.commit()
            return True, f"Alle Positionen haben bereits Lichess-Daten für ELO '{elo_category}'."

        lichess_ratings = ELO_MAPPING.get(elo_category, ['1800', '2000'])

        new_data_points_added = 0
        successful_requests_in_a_row = 0
        last_failure_delay = None
        
        i = 0
        while i < len(positions_to_query):
            # Refresh position state before querying to avoid ObjectDeletedError using a new query to fetch it fresh if needed
            pos_id = positions_to_query[i].id
            pos = session.get(Position, pos_id)
            if pos is None:
                i += 1
                continue
                
            if check_cancel and check_cancel():
                session.commit()
                _update_lichess_delay_config(current_delay)
                return False, "Import abgebrochen."

            if elo_category == 'masters':
                params = {
                    'variant': 'standard',
                    'fen': pos.fen
                }
                query_string = urllib.parse.urlencode(params)
                url = f"https://explorer.lichess.org/masters?{query_string}"
            else:
                params = {
                    'variant': 'standard',
                    'fen': pos.fen, 
                    'ratings': ",".join(lichess_ratings),
                    'speeds': 'rapid,classical'
                }
                query_string = urllib.parse.urlencode(params)
                url = f"https://explorer.lichess.org/lichess?{query_string}"
            
            retry_same_position = False
            
            try:
                headers = {'User-Agent': 'OpeningFenix/1.0 (Python urllib)'}
                if lichess_token and lichess_token != "YOUR_TOKEN_HERE":
                    headers['Authorization'] = f'Bearer {lichess_token}'
                
                req = urllib.request.Request(url, headers=headers)
                
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    successful_requests_in_a_row += 1
                    
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
                        
                        new_data = LichessData(
                            fen=pos.fen,
                            elo_range=elo_category,
                            moves_json=json.dumps(moves_dict)
                        )
                        session.add(new_data)
                        new_data_points_added += 1
                    else:
                        new_data = LichessData(
                            fen=pos.fen,
                            elo_range=elo_category,
                            moves_json=json.dumps({})
                        )
                        session.add(new_data)
                        new_data_points_added += 1
            
            except urllib.error.HTTPError as e:
                successful_requests_in_a_row = 0
                if e.code == 429:
                    print(f"WARN: Rate limit exceeded (429) for FEN {pos.fen}.")
                    last_failure_delay = current_delay
                    
                    current_delay = min(current_delay * 1.5, 5.0) 
                    _update_lichess_delay_config(current_delay) 
                    
                    print("Waiting 60 seconds before retrying...")
                    time.sleep(60)
                    retry_same_position = True
                elif e.code == 401:
                    return False, "Fehler 401: Ungültiges Lichess Token. Bitte überprüfe config.json."
                else:
                    print(f"HTTP Error {e.code} for FEN {pos.fen}. Skipping.")
            except Exception as e:
                successful_requests_in_a_row = 0
                print(f"An error occurred for FEN {pos.fen}: {e}. Skipping.")

            if retry_same_position:
                continue

            if successful_requests_in_a_row >= 50:
                is_safe_to_speed_up = True
                if last_failure_delay is not None:
                    if current_delay <= last_failure_delay * 1.2:
                        is_safe_to_speed_up = False
                
                if is_safe_to_speed_up:
                    new_delay = max(current_delay * 0.95, 0.05)
                    if f"{new_delay:.3f}" != f"{current_delay:.3f}":
                        current_delay = new_delay
                
                successful_requests_in_a_row = 0

            i += 1
            
            if new_data_points_added > 0 and new_data_points_added % 10 == 0:
                session.commit()

            if progress_callback:
                progress_callback(int(i * 100 / total_pos))
            
            time.sleep(current_delay)

        set_meta(session, "lichess_elo", elo_category)
        session.commit()
        _update_lichess_delay_config(current_delay)
        return True, f"{new_data_points_added} neue Lichess-Datenpunkte für ELO '{elo_category}' erfolgreich importiert."

    except Exception as e:
        session.rollback()
        import traceback
        print(traceback.format_exc())
        return False, f"Fehler beim Lichess-Import: {e}"
    finally:
        session.close()
        db.close()


def run_lichess_import_and_calculate_scores(repo_name: str, elo_category: str, progress_callback: Optional[Callable[[int], None]] = None, check_cancel: Optional[Callable[[], bool]] = None) -> Tuple[bool, str]:
    from opening_fenix.core.services.priority_service import calculate_priority_scores

    def import_progress_wrapper(percent):
        if progress_callback:
            progress_callback(int(percent * 0.95))

    import_success, import_msg = run_lichess_import(
        repo_name, elo_category,
        progress_callback=import_progress_wrapper,
        check_cancel=check_cancel
    )

    if not import_success:
        return False, import_msg

    if check_cancel and check_cancel():
        return False, "Operation cancelled after Lichess import."

    def priority_progress_wrapper(percent):
        if progress_callback:
            progress_callback(95 + int(percent * 0.05))

    priority_success, priority_msg = calculate_priority_scores(
        repo_name, elo_category,
        progress_callback=priority_progress_wrapper,
        check_cancel=check_cancel
    )

    if not priority_success:
        return False, f"Lichess import OK, but priority calculation failed: {priority_msg}"

    return True, "Lichess import und Prioritäts-Scores erfolgreich abgeschlossen."

def delete_lichess_data(repo_name: str, elo_category: str) -> Tuple[bool, str]:
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return False, "Repertoire-Datenbank nicht gefunden."

    db = DatabaseManager(db_path)
    session = db.get_session()
    try:
        num_deleted = session.query(LichessData).filter_by(
            elo_range=elo_category
        ).delete(synchronize_session=False)

        current_elo = get_meta(session, "lichess_elo")
        if current_elo == elo_category:
            set_meta(session, "lichess_elo", None)
        
        session.commit()
        
        if num_deleted > 0:
            return True, f"{num_deleted} Lichess-Daten-Einträge für ELO '{elo_category}' gelöscht."
        else:
            return True, f"Keine Lichess-Daten für ELO '{elo_category}' zum Löschen gefunden."

    except Exception as e:
        session.rollback()
        return False, f"Fehler beim Löschen der Lichess-Daten: {e}"
    finally:
        session.close()
        db.close()


def verify_lichess_token(token: str) -> Tuple[bool, str]:
    """
    Verifies a Lichess API token by making a request to the /api/account endpoint.
    Returns (Success: bool, Message: str).
    """
    if not token or token == "YOUR_TOKEN_HERE":
        return False, "Kein Token angegeben."

    url = "https://lichess.org/api/account"
    headers = {
        'User-Agent': 'OpeningFenix/1.0',
        'Authorization': f'Bearer {token}'
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                username = data.get('username', 'Unbekannt')
                return True, f"Verbindung erfolgreich! (Hallo {username})"
            else:
                return False, f"Fehler {response.status}: {response.reason}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Fehler 401: Ungültiges oder abgelaufenes Token."
        elif e.code == 429:
            return False, "Fehler 429: Zu viele Anfragen. Bitte warte einen Moment."
        else:
            return False, f"HTTP Fehler {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Netzwerkfehler: {str(e)}"

def run_lichess_orphan_cleanup(repo_name: str, progress_callback: Optional[Callable[[int], None]] = None) -> Tuple[bool, str]:
    """Removes all LichessData entries that are no longer referenced by any Position."""
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return False, "Datenbank nicht gefunden."
        
    db = DatabaseManager(db_path)
    session = db.get_session()
    try:
        # Fetch all Lichess FENs and check existence in the position table.
        all_lichess_fens = session.query(LichessData.fen).distinct().all()
        total = len(all_lichess_fens)
        deleted_count = 0
        
        for idx, (l_fen,) in enumerate(all_lichess_fens):
            # Check if any position matches this FEN prefix
            exists = session.query(Position.id).filter(Position.fen.like(l_fen + "%")).first()
            if not exists:
                n = session.query(LichessData).filter_by(fen=l_fen).delete()
                deleted_count += n
            
            if progress_callback and total > 0:
                progress_callback(int((idx + 1) * 100 / total))
                
        if deleted_count > 0:
            session.commit()
            
        return True, f"{deleted_count} Einträge bereinigt."
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()
        db.close()
