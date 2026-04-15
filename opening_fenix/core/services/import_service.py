import os
import io
import chess.pgn
from typing import Tuple, Optional, Callable
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path, initialize_repertoire_assets
from opening_fenix.core.services.repair_service import repair_repertoire_health

def import_pgn_to_db(pgn_path: str, repo_name: str, side: str, level_name: str, level_order: int, progress_callback: Optional[Callable[[int], None]] = None) -> Tuple[bool, str]:
    """Imports a PGN file into a new or existing repertoire database using bulk operations."""
    db_path = get_repertoire_db_path(repo_name)
    is_new_db = not os.path.exists(db_path)
    
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    new_moves_count = 0

    try:
        # 1. SETUP & METADATA
        if is_new_db:
            start_board = chess.Board()
            start_fen = " ".join(start_board.fen().split(" ")[:4])
            start_pos_check = session.query(Position).filter_by(fen=start_fen).first()
            if not start_pos_check:
                start_pos = Position(fen=start_fen)
                session.add(start_pos)
            set_meta(session, "name", repo_name)
            set_meta(session, "color", side)
            
            # Initialize PGN assets and Tactics folder
            initialize_repertoire_assets(os.path.dirname(db_path))
        
        session.flush()

        level_obj = session.query(RepertoireLevel).filter_by(order=level_order).first()
        if not level_obj:
            level_obj = RepertoireLevel(name=level_name, order=level_order)
            session.add(level_obj)
            session.flush()
            
        current_repo_side = get_meta(session, "color", side)

        # 2. PRE-FETCH CACHES
        print("INFO: Building in-memory cache for PGN import...")
        pos_cache = {fen: pid for pid, fen in session.query(Position.id, Position.fen).all()}
        move_cache = {(from_id, uci): mid for mid, from_id, uci in session.query(Move.id, Move.from_position_id, Move.uci).all()}
        rep_move_cache = {mid: lvl for mid, lvl in session.query(RepertoireMove.move_id, RepertoireMove.level).all()}

        # 3. READ FILE
        try:
            with open(pgn_path, 'r', encoding='utf-8') as f:
                pgn_content = f.read()
        except UnicodeDecodeError:
            with open(pgn_path, 'r', encoding='latin-1') as f:
                pgn_content = f.read()
        
        pgn_io = io.StringIO(pgn_content)

        # 4. PARSE PGN & BUILD BATCHES
        print("INFO: Parsing PGN and building bulk objects...")
        new_positions_to_insert = {} 
        new_moves_to_insert = []     
        new_rep_moves_to_insert = [] 
        rep_moves_to_update = {}
        comments_to_append = {} 

        max_pos_id = max(pos_cache.values()) if pos_cache else 0
        max_move_id = max(move_cache.values()) if move_cache else 0

        # Estimate file size for progress
        file_size = os.path.getsize(pgn_path)
        processed_bytes = 0

        while True:
            game = chess.pgn.read_game(pgn_io)
            if game is None:
                break
            
            # Simple progress estimation based on file pointer
            if progress_callback:
                processed_bytes = pgn_io.tell()
                progress_callback(int((processed_bytes / len(pgn_content)) * 100))
            
            node_stack = []
            initial_board = game.board()
            for node in reversed(game.variations):
                node_stack.append((node, initial_board.copy()))

            while node_stack:
                current_node, board = node_stack.pop()
                move = current_node.move
                from_fen = " ".join(board.fen().split(" ")[:4])

                try:
                    board.push(move)
                except Exception as e:
                    continue

                to_fen = " ".join(board.fen().split(" ")[:4])
                
                from_pos_id = pos_cache.get(from_fen)
                if not from_pos_id:
                    max_pos_id += 1
                    from_pos_id = max_pos_id
                    pos_cache[from_fen] = from_pos_id
                    new_positions_to_insert[from_fen] = Position(id=from_pos_id, fen=from_fen)

                to_pos_id = pos_cache.get(to_fen)
                if not to_pos_id:
                    max_pos_id += 1
                    to_pos_id = max_pos_id
                    pos_cache[to_fen] = to_pos_id
                    new_positions_to_insert[to_fen] = Position(id=to_pos_id, fen=to_fen)
                
                if current_node.comment:
                    if to_fen in comments_to_append:
                        if current_node.comment not in comments_to_append[to_fen]:
                            comments_to_append[to_fen] += " | " + current_node.comment
                    else:
                        comments_to_append[to_fen] = current_node.comment

                uci_str = move.uci()
                move_id = move_cache.get((from_pos_id, uci_str))
                
                if not move_id:
                    max_move_id += 1
                    move_id = max_move_id
                    move_cache[(from_pos_id, uci_str)] = move_id
                    new_moves_to_insert.append(
                        Move(id=move_id, from_position_id=from_pos_id, to_position_id=to_pos_id, uci=uci_str, san=current_node.san(), nag=next(iter(current_node.nags), 0))
                    )
                
                # REPERTOIRE MOVE LOGIC
                # We now add ALL moves from the PGN to prevent holes, regardless of which side is being imported.
                # We also ensure we keep the highest priority level (lowest numerical value).
                if move_id not in rep_move_cache:
                    rep_move_cache[move_id] = level_order
                    new_rep_moves_to_insert.append(
                        RepertoireMove(move_id=move_id, level=level_order)
                    )
                    new_moves_count += 1
                elif level_order < rep_move_cache[move_id]:
                    # User imported this move into a higher priority level than before
                    rep_move_cache[move_id] = level_order
                    rep_moves_to_update[move_id] = level_order
                    new_moves_count += 1
                
                for variation in reversed(current_node.variations):
                    node_stack.append((variation, board.copy()))
        
        # 5. BULK EXECUTION
        if new_positions_to_insert:
            session.bulk_save_objects(list(new_positions_to_insert.values()))
        if new_moves_to_insert:
            session.bulk_save_objects(new_moves_to_insert)
        if new_rep_moves_to_insert:
            session.bulk_save_objects(new_rep_moves_to_insert)
        
        if rep_moves_to_update:
            # Efficiently update levels for existing repertoire moves
            for mid, new_lvl in rep_moves_to_update.items():
                session.query(RepertoireMove).filter_by(move_id=mid).update({"level": new_lvl}, synchronize_session=False)
            
        # 6. UPDATE COMMENTS 
        if comments_to_append:
            fens_with_comments = list(comments_to_append.keys())
            chunk_size = 900
            for i in range(0, len(fens_with_comments), chunk_size):
                chunk_fens = fens_with_comments[i:i + chunk_size]
                positions_to_update = session.query(Position).filter(Position.fen.in_(chunk_fens)).all()
                for pos in positions_to_update:
                    new_c = comments_to_append[pos.fen]
                    if pos.comment:
                        if new_c not in pos.comment:
                            pos.comment += " | " + new_c
                    else:
                        pos.comment = new_c

        if new_moves_count > 0 or comments_to_append:
            # 7. AUTOMATED HEALTH REPAIR
            # This ensures no holes were created and levels are consistent.
            repair_repertoire_health(session, fast=True)

            set_meta(session, "ana_cache_count", "-1")
            set_meta(session, "cov_cache_count", "-1")
            session.commit()
            return True, f"{new_moves_count} Züge erfolgreich importiert."
        else:
            session.rollback()
            return False, "Keine neuen Züge in der PGN-Datei gefunden, die importiert werden konnten."

    except Exception as e:
        session.rollback()
        import traceback
        print(traceback.format_exc())
        return False, f"Fehler beim Import: {e}"
    finally:
        session.close()
        db.close()
