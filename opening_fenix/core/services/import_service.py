import os
import io
import chess.pgn
from typing import Tuple, Optional, Callable
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path, initialize_repertoire_assets, combine_comments
from opening_fenix.core.services.repair_service import repair_repertoire_health

def import_pgn_to_db(pgn_path: str, repo_name: str, side: str, level_name: str, level_order: int, progress_callback: Optional[Callable[[int], None]] = None, target_lang: str = "de") -> Tuple[bool, str]:
    """Imports a PGN file into a new or existing repertoire database using bulk operations."""
    db_path = get_repertoire_db_path(repo_name)
    is_new_db = not os.path.exists(db_path)
    
    if not is_new_db:
        try:
            from opening_fenix.core.services.backup_service import create_repertoire_backup
            create_repertoire_backup(repo_name, trigger_type="pre_import_safety")
        except Exception as ex:
            pass

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
            set_meta(session, "repertoire_display_name", repo_name)
            set_meta(session, "color", side)
            session.commit()
            initialize_repertoire_assets(repo_name)
        
        session.flush()

        level = session.query(RepertoireLevel).filter_by(order=level_order).first()
        if not level:
            level = RepertoireLevel(name=level_name, order=level_order)
            session.add(level)
            session.commit()
            
        # 2. BULK CACHE INITIALIZATION
        pos_cache = {p.fen: p.id for p in session.query(Position.fen, Position.id).all()}
        move_cache = {(m.from_position_id, m.uci): m.id for m in session.query(Move.from_position_id, Move.uci, Move.id).all()}
        rep_move_cache = {rm.move_id: rm.level for rm in session.query(RepertoireMove.move_id, RepertoireMove.level).all()}

        max_pos_id = max(pos_cache.values()) if pos_cache else 0
        max_move_id = max(move_cache.values()) if move_cache else 0

        new_positions_to_insert = {}
        new_moves_to_insert = []
        new_rep_moves_to_insert = []
        comments_to_append = {}

        # 3. FAST PGN PARSING
        with open(pgn_path, "r", encoding="utf-8", errors="ignore") as f_pgn:
            pgn_content = f_pgn.read()

        pgn_io = io.StringIO(pgn_content)
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
                    lang = target_lang if target_lang and target_lang != "auto" else "de"
                    if to_fen in comments_to_append:
                        comments_to_append[to_fen] = combine_comments(comments_to_append[to_fen], current_node.comment, default_lang=lang)
                    else:
                        comments_to_append[to_fen] = combine_comments("", current_node.comment, default_lang=lang)

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
                if move_id not in rep_move_cache:
                    rep_move_cache[move_id] = level_order
                    new_rep_moves_to_insert.append(
                        RepertoireMove(move_id=move_id, level=level_order)
                    )
                    new_moves_count += 1
                elif level_order < rep_move_cache[move_id]:
                    rep_move_cache[move_id] = level_order
                    existing_rm = session.query(RepertoireMove).filter_by(move_id=move_id).first()
                    if existing_rm:
                        existing_rm.level = level_order
                
                for var in reversed(current_node.variations):
                    node_stack.append((var, board.copy()))
        
        # 4. BULK DB EXECUTION
        if new_positions_to_insert:
            session.bulk_save_objects(list(new_positions_to_insert.values()))
        if new_moves_to_insert:
            session.bulk_save_objects(new_moves_to_insert)
        if new_rep_moves_to_insert:
            session.bulk_save_objects(new_rep_moves_to_insert)
        
        # 6. UPDATE COMMENTS 
        if comments_to_append:
            lang = target_lang if target_lang and target_lang != "auto" else "de"
            fens_with_comments = list(comments_to_append.keys())
            chunk_size = 900
            for i in range(0, len(fens_with_comments), chunk_size):
                chunk_fens = fens_with_comments[i:i + chunk_size]
                positions_to_update = session.query(Position).filter(Position.fen.in_(chunk_fens)).all()
                for pos in positions_to_update:
                    new_c = comments_to_append[pos.fen]
                    pos.comment = combine_comments(pos.comment, new_c, default_lang=lang)

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
