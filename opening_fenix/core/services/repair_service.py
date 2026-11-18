import chess
from sqlalchemy import func, text
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.logger import logger

def repair_repertoire_health(session, fast=False):
    """
    Runs a set of maintenance tasks to ensure the repertoire is logically consistent.
    1. Repairs Gaps (Broken move chains)
    2. Enforces Level Consistency (Parents must be at least as basic as children)
    3. Canonicalizes Castling UCIs
    """
    logger.info("Maintenance: Running repertoire health check...")

    # Load graph into memory once instead of running multi-pass full-table SQL scans per ply
    all_moves = session.query(Move.id, Move.from_position_id, Move.to_position_id).all()
    rep_rows = session.query(RepertoireMove.id, RepertoireMove.move_id, RepertoireMove.level).all()

    move_by_id = {m_id: (from_id, to_id) for m_id, from_id, to_id in all_moves}
    incoming_by_pos = {}
    outgoing_by_pos = {}
    for m_id, from_id, to_id in all_moves:
        outgoing_by_pos.setdefault(from_id, []).append(m_id)
        if to_id is not None:
            incoming_by_pos.setdefault(to_id, []).append(m_id)

    rep_level_by_move = {}
    rep_id_by_move = {}
    for rm_id, m_id, lvl in rep_rows:
        eff_lvl = lvl if lvl is not None else 1
        rep_level_by_move[m_id] = eff_lvl
        rep_id_by_move[m_id] = rm_id

    # 1. Repair Gaps (propagate upwards in memory)
    gaps_fixed = 0
    new_rep_moves = []
    pos_with_rep_out = set()
    for m_id in rep_level_by_move:
        edge = move_by_id.get(m_id)
        if edge:
            pos_with_rep_out.add(edge[0])

    # Queue positions that have outgoing repertoire moves and check their unassigned incoming moves
    from collections import deque
    queue = deque(pos_with_rep_out)
    while queue:
        pos_id = queue.popleft()
        out_lvls = [rep_level_by_move[m_id] for m_id in outgoing_by_pos.get(pos_id, ()) if m_id in rep_level_by_move]
        if not out_lvls:
            continue
        min_out_lvl = min(out_lvls)
        for in_m_id in incoming_by_pos.get(pos_id, ()):
            if in_m_id not in rep_level_by_move:
                from_id, _ = move_by_id[in_m_id]
                in_lvls = [rep_level_by_move[pm_id] for pm_id in incoming_by_pos.get(from_id, ()) if pm_id in rep_level_by_move]
                lvl = min([min_out_lvl] + in_lvls) if in_lvls else min_out_lvl
                rep_level_by_move[in_m_id] = lvl
                new_rep_moves.append({'move_id': in_m_id, 'level': lvl, 'is_active': True})
                gaps_fixed += 1
                if not fast and from_id not in pos_with_rep_out:
                    pos_with_rep_out.add(from_id)
                    queue.append(from_id)

    if new_rep_moves:
        session.bulk_insert_mappings(RepertoireMove, new_rep_moves)
        session.flush()
        logger.info(f"Maintenance: Fixed {gaps_fixed} repertoire gaps.")

    # 2. Enforce Level Consistency (propagate min child level upward in memory)
    levels_updated = 0
    try:
        # Refresh rep_id_by_move for any newly inserted gap moves if needed
        if new_rep_moves:
            for rm_id, m_id in session.query(RepertoireMove.id, RepertoireMove.move_id).filter(
                RepertoireMove.move_id.in_([d['move_id'] for d in new_rep_moves])
            ).all():
                rep_id_by_move[m_id] = rm_id

        updated_move_ids = {}
        lvl_queue = deque([m_id for m_id in rep_level_by_move])
        in_lvl_queue = set(lvl_queue)
        while lvl_queue:
            pm_id = lvl_queue.popleft()
            in_lvl_queue.discard(pm_id)
            edge = move_by_id.get(pm_id)
            if not edge:
                continue
            from_id, to_id = edge
            if to_id is None:
                continue
            child_lvls = [rep_level_by_move[cm_id] for cm_id in outgoing_by_pos.get(to_id, ()) if cm_id in rep_level_by_move]
            if not child_lvls:
                continue
            min_child = min(child_lvls)
            if rep_level_by_move[pm_id] > min_child:
                rep_level_by_move[pm_id] = min_child
                updated_move_ids[pm_id] = min_child
                if not fast:
                    for grand_pm in incoming_by_pos.get(from_id, ()):
                        if grand_pm in rep_level_by_move and grand_pm not in in_lvl_queue:
                            lvl_queue.append(grand_pm)
                            in_lvl_queue.add(grand_pm)

        if updated_move_ids:
            updates = [
                {'id': rep_id_by_move[m_id], 'level': lvl}
                for m_id, lvl in updated_move_ids.items()
                if m_id in rep_id_by_move
            ]
            if updates:
                for i in range(0, len(updates), 1000):
                    session.bulk_update_mappings(RepertoireMove, updates[i:i + 1000])
                levels_updated = len(updates)
                session.flush()
    except Exception as e:
        logger.error(f"Maintenance: Error during level consistency repair: {e}")

    if levels_updated > 0:
        logger.info(f"Maintenance: Updated {levels_updated} levels for consistency.")

    # 3. Canonicalize Castling UCIs (Chess960 e1h1 -> Standard e1g1)
    repair_castling_ucis(session, auto_commit=False)

    session.commit()
    return gaps_fixed, levels_updated

def repair_castling_ucis(session, auto_commit: bool = True) -> int:
    """
    Finds moves where SAN represents castling (O-O, O-O-O) but UCI was stored in
    Chess960 / FRC format (e1h1, e1a1, e8h8, e8a8), and normalizes them to standard
    chess UCI (e1g1, e1c1, e8g8, e8c8).
    Handles potential uniqueness collisions if standard UCI already exists.
    """
    from opening_fenix.core.utils import CASTLE_FRC_TO_STD, CASTLING_SANS
    
    frc_moves = session.query(Move).filter(
        Move.san.in_(list(CASTLING_SANS)),
        Move.uci.in_(list(CASTLE_FRC_TO_STD.keys()))
    ).all()
    
    if not frc_moves:
        return 0
        
    fixed_count = 0
    for m in frc_moves:
        target_uci = CASTLE_FRC_TO_STD.get(m.uci)
        if not target_uci:
            continue
            
        # Check if target_uci already exists from the same position
        existing_std = session.query(Move).filter_by(
            from_position_id=m.from_position_id,
            uci=target_uci
        ).first()
        
        if existing_std:
            # Re-link or remove RepertoireMove referencing m
            rm_frc = session.query(RepertoireMove).filter_by(move_id=m.id).first()
            rm_std = session.query(RepertoireMove).filter_by(move_id=existing_std.id).first()
            if rm_frc and not rm_std:
                rm_frc.move_id = existing_std.id
            elif rm_frc and rm_std:
                session.delete(rm_frc)
            session.delete(m)
        else:
            m.uci = target_uci
            
        fixed_count += 1
        
    if fixed_count > 0:
        if auto_commit:
            session.commit()
        else:
            session.flush()
        logger.info(f"Maintenance: Repaired {fixed_count} castling UCI moves to standard notation.")
        
    return fixed_count

def repair_unassigned_moves(session) -> int:
    """
    Finds moves in the database that originate from a known repertoire position
    but lack an entry in `repertoire_moves` (e.g. leaf moves of variations
    from older PGN imports), and assigns them to the parent move's repertoire level.
    """
    from collections import deque
    total_fixed = 0

    start_pos = session.query(Position.id).filter_by(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -").first()
    start_id = start_pos[0] if start_pos else None

    all_moves = session.query(Move.id, Move.from_position_id, Move.to_position_id).all()
    rep_rows = session.query(RepertoireMove.move_id, RepertoireMove.level).all()
    assigned_lvl = {m_id: (lvl if lvl is not None else 1) for m_id, lvl in rep_rows}

    outgoing_unassigned = {}
    pos_incoming_min = {}
    for m_id, from_id, to_id in all_moves:
        if m_id in assigned_lvl:
            if to_id is not None:
                lvl = assigned_lvl[m_id]
                prev = pos_incoming_min.get(to_id)
                if prev is None or lvl < prev:
                    pos_incoming_min[to_id] = lvl
        else:
            outgoing_unassigned.setdefault(from_id, []).append((m_id, to_id))

    if not outgoing_unassigned:
        return 0

    seed_positions = set(pos_incoming_min.keys())
    if start_id is not None and start_id not in pos_incoming_min:
        pos_incoming_min[start_id] = 1
        seed_positions.add(start_id)

    new_rows = []
    queue = deque(seed_positions)
    while queue:
        pos_id = queue.popleft()
        lvl = pos_incoming_min.get(pos_id)
        if lvl is None:
            continue
        unassigned_list = outgoing_unassigned.pop(pos_id, None)
        if not unassigned_list:
            continue
        for m_id, to_id in unassigned_list:
            new_rows.append({'move_id': m_id, 'level': lvl, 'is_active': True})
            total_fixed += 1
            if to_id is not None:
                prev = pos_incoming_min.get(to_id)
                if prev is None or lvl < prev:
                    pos_incoming_min[to_id] = lvl
                    queue.append(to_id)

    if new_rows:
        for i in range(0, len(new_rows), 1000):
            session.bulk_insert_mappings(RepertoireMove, new_rows[i:i + 1000])
        session.commit()
        logger.info(f"Maintenance: Repaired {total_fixed} unassigned leaf moves into repertoire levels.")

    return total_fixed

def repair_schema_and_orphans(session):
    """Placeholder for other diagnostic repairs if needed."""
    # This logic remains in CreatorBackend for now as it involves DatabaseManager's migrate
    pass
