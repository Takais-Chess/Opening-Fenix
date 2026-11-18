import os
import io
import chess.pgn
from typing import Tuple, Optional, Callable
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import (
    get_user_dir,
    get_repertoire_db_path,
    initialize_repertoire_assets,
    combine_comments,
    normalize_castling_uci,
    parse_chessbase_annotations,
    update_comment_with_annotations,
    get_multilingual_comment_dict,
)
from opening_fenix.core.services.repair_service import repair_repertoire_health
from opening_fenix.core.services.course_import_service import SanitizedPGNReader, format_variation_tree_as_text
from opening_fenix.core.translation import tr_ui

_EXIT_MARKER = object()


def _board_fen4(board: chess.Board) -> str:
    return " ".join(board.fen().split(" ", 4)[:4])


def _merge_comment_fragments(existing: Optional[str], fragments: list, default_lang: str) -> str:
    res = existing or ""
    for frag in fragments:
        res = combine_comments(res, frag, default_lang=default_lang)
    return res


def import_pgn_to_db(pgn_path: str, repo_name: str, side: str, level_name: str, level_order: int, progress_callback: Optional[Callable[[int], None]] = None, target_lang: str = "de", subvariations_as_comments: bool = False) -> Tuple[bool, str]:
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
        move_cache = {(m.from_position_id, m.uci): (m.id, m.nag) for m in session.query(Move.from_position_id, Move.uci, Move.id, Move.nag).all()}
        existing_rm_rows = session.query(RepertoireMove.id, RepertoireMove.move_id, RepertoireMove.level).all()
        rep_move_cache = {rm.move_id: rm.level for rm in existing_rm_rows}
        rep_move_id_by_move_id = {rm.move_id: rm.id for rm in existing_rm_rows}

        max_pos_id = max(pos_cache.values()) if pos_cache else 0
        max_move_id = max(m_id for m_id, _ in move_cache.values()) if move_cache else 0

        new_positions_to_insert = {}
        new_moves_to_insert = []
        new_moves_by_id = {}
        new_rep_moves_to_insert = []
        new_rep_moves_by_move_id = {}
        moves_to_update_nag = {}
        rep_moves_to_update_level = {}
        comments_to_append = {}
        c_lang = target_lang if target_lang and target_lang != "auto" else "de"
        last_pct = -1

        # 3. FAST STREAMING PGN PARSING
        total_file_size = os.path.getsize(pgn_path) if os.path.exists(pgn_path) else 0
        with open(pgn_path, "r", encoding="utf-8", errors="ignore") as f_pgn:
            reader = SanitizedPGNReader(f_pgn)
            while True:
                game = chess.pgn.read_game(reader)
                if game is None:
                    break
                
                # Simple progress estimation based on file pointer
                if progress_callback and total_file_size > 0:
                    processed_bytes = f_pgn.tell()
                    pct = min(100, int((processed_bytes / total_file_size) * 100))
                    if pct != last_pct:
                        last_pct = pct
                        progress_callback(pct)
            
                if subvariations_as_comments:
                    board = game.board()
                    cur_fen = _board_fen4(board)
                    for current_node in game.mainline():
                        move = current_node.move
                        from_fen = cur_fen

                        try:
                            move_san = board.san(move)
                        except Exception:
                            try:
                                move_san = current_node.san()
                            except Exception:
                                continue

                        # Collect sibling subvariations BEFORE pushing onto board
                        sibling_texts = []
                        parent = current_node.parent
                        if parent and len(parent.variations) > 1:
                            for v in parent.variations:
                                if v != current_node:
                                    sub_text = format_variation_tree_as_text(v, board)
                                    if sub_text:
                                        sibling_texts.append(sub_text)

                        try:
                            board.push(move)
                        except Exception:
                            continue

                        to_fen = _board_fen4(board)
                        cur_fen = to_fen

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

                        # 1. Mainline node comment
                        combined_node_comment = ""
                        if current_node.starting_comment:
                            combined_node_comment = current_node.starting_comment.strip()
                        if current_node.comment:
                            c = current_node.comment.strip()
                            combined_node_comment = f"{combined_node_comment} {c}".strip() if combined_node_comment else c

                        if combined_node_comment:
                            lst = comments_to_append.setdefault(to_fen, [])
                            if combined_node_comment not in lst:
                                lst.append(combined_node_comment)

                        # 2. Sibling subvariations on parent
                        if sibling_texts:
                            lst = comments_to_append.setdefault(to_fen, [])
                            for sub_text in sibling_texts:
                                if sub_text not in lst:
                                    lst.append(sub_text)

                        incoming_nag = next(iter(current_node.nags), 0)
                        uci_str = normalize_castling_uci(move.uci(), move_san)
                        move_entry = move_cache.get((from_pos_id, uci_str))

                        if not move_entry:
                            max_move_id += 1
                            move_id = max_move_id
                            move_cache[(from_pos_id, uci_str)] = (move_id, incoming_nag)
                            new_m = Move(id=move_id, from_position_id=from_pos_id, to_position_id=to_pos_id, uci=uci_str, san=move_san, nag=incoming_nag)
                            new_moves_to_insert.append(new_m)
                            new_moves_by_id[move_id] = new_m
                        else:
                            move_id, existing_nag = move_entry
                            if incoming_nag != 0 and existing_nag != incoming_nag:
                                move_cache[(from_pos_id, uci_str)] = (move_id, incoming_nag)
                                if move_id in new_moves_by_id:
                                    new_moves_by_id[move_id].nag = incoming_nag
                                else:
                                    moves_to_update_nag[move_id] = incoming_nag

                        # REPERTOIRE MOVE LOGIC
                        if move_id not in rep_move_cache:
                            rep_move_cache[move_id] = level_order
                            new_rm = RepertoireMove(move_id=move_id, level=level_order)
                            new_rep_moves_to_insert.append(new_rm)
                            new_rep_moves_by_move_id[move_id] = new_rm
                            new_moves_count += 1
                        elif level_order < rep_move_cache[move_id]:
                            rep_move_cache[move_id] = level_order
                            if move_id in new_rep_moves_by_move_id:
                                new_rep_moves_by_move_id[move_id].level = level_order
                            elif move_id in rep_move_id_by_move_id:
                                rep_moves_to_update_level[rep_move_id_by_move_id[move_id]] = level_order
                else:
                    board = game.board()
                    init_fen = _board_fen4(board)
                    init_pos_id = pos_cache.get(init_fen)
                    if not init_pos_id:
                        max_pos_id += 1
                        init_pos_id = max_pos_id
                        pos_cache[init_fen] = init_pos_id
                        new_positions_to_insert[init_fen] = Position(id=init_pos_id, fen=init_fen)

                    node_stack = [(node, init_pos_id) for node in reversed(game.variations)]

                    while node_stack:
                        item = node_stack.pop()
                        if item is _EXIT_MARKER:
                            board.pop()
                            continue

                        current_node, from_pos_id = item
                        move = current_node.move

                        try:
                            move_san = board.san(move)
                            board.push(move)
                        except Exception:
                            continue

                        to_fen = _board_fen4(board)

                        to_pos_id = pos_cache.get(to_fen)
                        if not to_pos_id:
                            max_pos_id += 1
                            to_pos_id = max_pos_id
                            pos_cache[to_fen] = to_pos_id
                            new_positions_to_insert[to_fen] = Position(id=to_pos_id, fen=to_fen)
                        
                        combined_node_comment = ""
                        if current_node.starting_comment:
                            combined_node_comment = current_node.starting_comment.strip()
                        if current_node.comment:
                            c = current_node.comment.strip()
                            combined_node_comment = f"{combined_node_comment} {c}".strip() if combined_node_comment else c

                        if combined_node_comment:
                            lst = comments_to_append.setdefault(to_fen, [])
                            if combined_node_comment not in lst:
                                lst.append(combined_node_comment)

                        incoming_nag = next(iter(current_node.nags), 0)
                        uci_str = normalize_castling_uci(move.uci(), move_san)
                        move_entry = move_cache.get((from_pos_id, uci_str))
                        
                        if not move_entry:
                            max_move_id += 1
                            move_id = max_move_id
                            move_cache[(from_pos_id, uci_str)] = (move_id, incoming_nag)
                            new_m = Move(id=move_id, from_position_id=from_pos_id, to_position_id=to_pos_id, uci=uci_str, san=move_san, nag=incoming_nag)
                            new_moves_to_insert.append(new_m)
                            new_moves_by_id[move_id] = new_m
                        else:
                            move_id, existing_nag = move_entry
                            if incoming_nag != 0 and existing_nag != incoming_nag:
                                move_cache[(from_pos_id, uci_str)] = (move_id, incoming_nag)
                                if move_id in new_moves_by_id:
                                    new_moves_by_id[move_id].nag = incoming_nag
                                else:
                                    moves_to_update_nag[move_id] = incoming_nag
                        
                        # REPERTOIRE MOVE LOGIC
                        if move_id not in rep_move_cache:
                            rep_move_cache[move_id] = level_order
                            new_rm = RepertoireMove(move_id=move_id, level=level_order)
                            new_rep_moves_to_insert.append(new_rm)
                            new_rep_moves_by_move_id[move_id] = new_rm
                            new_moves_count += 1
                        elif level_order < rep_move_cache[move_id]:
                            rep_move_cache[move_id] = level_order
                            if move_id in new_rep_moves_by_move_id:
                                new_rep_moves_by_move_id[move_id].level = level_order
                            elif move_id in rep_move_id_by_move_id:
                                rep_moves_to_update_level[rep_move_id_by_move_id[move_id]] = level_order
                        
                        if current_node.variations:
                            node_stack.append(_EXIT_MARKER)
                            for var in reversed(current_node.variations):
                                node_stack.append((var, to_pos_id))
                        else:
                            board.pop()
        
        # Pre-populate comments on newly inserted positions before bulk insert
        existing_fens_with_comments = []
        if comments_to_append:
            for to_fen, frags in comments_to_append.items():
                if to_fen in new_positions_to_insert:
                    new_positions_to_insert[to_fen].comment = _merge_comment_fragments(None, frags, c_lang)
                else:
                    existing_fens_with_comments.append(to_fen)

        # 4. BULK DB EXECUTION
        if new_positions_to_insert:
            session.bulk_save_objects(list(new_positions_to_insert.values()))
        if new_moves_to_insert:
            session.bulk_save_objects(new_moves_to_insert)
        if new_rep_moves_to_insert:
            session.bulk_save_objects(new_rep_moves_to_insert)
        if rep_moves_to_update_level:
            session.bulk_update_mappings(
                RepertoireMove,
                [{"id": rm_id, "level": lvl} for rm_id, lvl in rep_moves_to_update_level.items()]
            )
        if moves_to_update_nag:
            session.bulk_update_mappings(
                Move,
                [{"id": m_id, "nag": n} for m_id, n in moves_to_update_nag.items()]
            )
        session.flush()
        session.expire_all()
        
        # 6. UPDATE COMMENTS on previously existing positions
        if existing_fens_with_comments:
            chunk_size = 900
            for i in range(0, len(existing_fens_with_comments), chunk_size):
                chunk_fens = existing_fens_with_comments[i:i + chunk_size]
                positions_to_update = session.query(Position).filter(Position.fen.in_(chunk_fens)).all()
                for pos in positions_to_update:
                    pos.comment = _merge_comment_fragments(pos.comment, comments_to_append[pos.fen], c_lang)

        if new_moves_count > 0 or comments_to_append or moves_to_update_nag or rep_moves_to_update_level:
            # 7. AUTOMATED HEALTH REPAIR
            # This ensures no holes were created and levels are consistent.
            repair_repertoire_health(session, fast=True)

            set_meta(session, "ana_cache_count", "-1")
            set_meta(session, "cov_cache_count", "-1")
            session.commit()
            return True, tr_ui("creator.msg_import_success", "{count} Züge erfolgreich importiert.", count=new_moves_count)
        else:
            session.rollback()
            return False, tr_ui("creator.msg_import_no_moves", "Keine neuen Züge in der PGN-Datei gefunden, die importiert werden konnten.")

    except Exception as e:
        session.rollback()
        import traceback
        print(traceback.format_exc())
        return False, tr_ui("creator.msg_import_error", "Fehler beim Import: {error}", error=str(e))
    finally:
        session.close()
        db.close()


def _collect_drawings_from_text(text: str, fen: str, drawings_by_fen: dict) -> None:
    """Extracts [%csl] highlights and [%cal] arrows from PGN comment text into drawings_by_fen."""
    if not text:
        return
    parsed = parse_chessbase_annotations(text)
    if not parsed["arrows"] and not parsed["highlights"]:
        return

    entry = drawings_by_fen.setdefault(fen, {"arrows": {}, "highlights": {}})
    for sq, color_name in parsed["highlights"]:
        entry["highlights"][sq] = color_name
    for from_sq, to_sq, color_name in parsed["arrows"]:
        entry["arrows"][(from_sq, to_sq)] = color_name


def _extract_existing_drawings(raw_comment: Optional[str]) -> Tuple[dict, dict]:
    """Extracts existing arrows and highlights from a Position.comment (plain or multilingual JSON)."""
    arrows = {}
    highlights = {}
    if not raw_comment or not isinstance(raw_comment, str):
        return arrows, highlights

    stripped = raw_comment.strip()
    texts = (
        list(get_multilingual_comment_dict(stripped).values())
        if stripped.startswith("{") and stripped.endswith("}")
        else [raw_comment]
    )
    for text in texts:
        parsed = parse_chessbase_annotations(text)
        for sq, col in parsed["highlights"]:
            highlights[sq] = col
        for from_sq, to_sq, col in parsed["arrows"]:
            arrows[(from_sq, to_sq)] = col
    return arrows, highlights


def import_pgn_drawings_only(
    pgn_path: str,
    repo_name: str,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Tuple[bool, str]:
    """Imports only ChessBase drawings ([%cal], [%csl]) from a PGN into existing repertoire positions."""
    db_path = get_repertoire_db_path(repo_name)
    if not os.path.exists(db_path):
        return False, tr_ui(
            "creator.msg_import_drawings_no_repo",
            "Repertoire '{repo}' nicht gefunden.",
            repo=repo_name,
        )

    drawings_by_fen = {}
    last_pct = -1
    total_file_size = os.path.getsize(pgn_path) if os.path.exists(pgn_path) else 0
    with open(pgn_path, "r", encoding="utf-8", errors="ignore") as f_pgn:
        reader = SanitizedPGNReader(f_pgn)
        while True:
            game = chess.pgn.read_game(reader)
            if game is None:
                break

            if progress_callback and total_file_size > 0:
                processed_bytes = f_pgn.tell()
                pct = min(100, int((processed_bytes / total_file_size) * 100))
                if pct != last_pct:
                    last_pct = pct
                    progress_callback(pct)

            board = game.board()
            root_fen = _board_fen4(board)
            if game.comment:
                _collect_drawings_from_text(game.comment, root_fen, drawings_by_fen)

            node_stack = [node for node in reversed(game.variations)]
            while node_stack:
                item = node_stack.pop()
                if item is _EXIT_MARKER:
                    board.pop()
                    continue
                current_node = item
                try:
                    board.push(current_node.move)
                except Exception:
                    continue

                to_fen = _board_fen4(board)
                parts = []
                if current_node.starting_comment:
                    parts.append(current_node.starting_comment.strip())
                if current_node.comment:
                    parts.append(current_node.comment.strip())
                if parts:
                    _collect_drawings_from_text(" ".join(parts), to_fen, drawings_by_fen)

                if current_node.variations:
                    node_stack.append(_EXIT_MARKER)
                    for var in reversed(current_node.variations):
                        node_stack.append(var)
                else:
                    board.pop()

    if not drawings_by_fen:
        return False, tr_ui(
            "creator.msg_import_drawings_none",
            "Keine neuen Zeichnungen für vorhandene Positionen in der PGN-Datei gefunden.",
        )

    try:
        from opening_fenix.core.services.backup_service import create_repertoire_backup
        create_repertoire_backup(repo_name, trigger_type="pre_import_safety")
    except Exception:
        pass

    db = DatabaseManager(db_path)
    session = db.get_session()
    updated_count = 0

    try:
        fens_with_drawings = list(drawings_by_fen.keys())
        chunk_size = 900
        for i in range(0, len(fens_with_drawings), chunk_size):
            chunk_fens = fens_with_drawings[i:i + chunk_size]
            positions = session.query(Position).filter(Position.fen.in_(chunk_fens)).all()
            for pos in positions:
                incoming = drawings_by_fen[pos.fen]
                existing_arrows, existing_highlights = _extract_existing_drawings(pos.comment)
                merged_arrows = {**existing_arrows, **incoming["arrows"]}
                merged_highlights = {**existing_highlights, **incoming["highlights"]}

                new_comment = update_comment_with_annotations(
                    pos.comment,
                    arrows=merged_arrows,
                    highlights=merged_highlights,
                )
                if new_comment != (pos.comment or ""):
                    pos.comment = new_comment
                    updated_count += 1

        if updated_count > 0:
            session.commit()
            return True, tr_ui(
                "creator.msg_import_drawings_success",
                "Zeichnungen für {count} Position(en) erfolgreich importiert.",
                count=updated_count,
            )

        session.rollback()
        return False, tr_ui(
            "creator.msg_import_drawings_none",
            "Keine neuen Zeichnungen für vorhandene Positionen in der PGN-Datei gefunden.",
        )
    except Exception as e:
        session.rollback()
        import traceback
        print(traceback.format_exc())
        return False, tr_ui("creator.msg_import_error", "Fehler beim Import: {error}", error=str(e))
    finally:
        session.close()
        db.close()
