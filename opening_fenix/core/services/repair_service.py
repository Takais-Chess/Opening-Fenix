import chess
from sqlalchemy import func, text
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.logger import logger

def repair_repertoire_health(session, fast=False):
    """
    Runs a set of maintenance tasks to ensure the repertoire is logically consistent.
    1. Repairs Gaps (Broken move chains)
    2. Enforces Level Consistency (Parents must be at least as basic as children)
    """
    logger.info("Maintenance: Running repertoire health check...")
    
    # 1. Repair Gaps
    # A gap is a move that leads to a repertoire position but isn't marked as a repertoire move.
    gaps_fixed = 0
    while True:
        # Find all positions that have outgoing repertoire moves
        subq = session.query(Move.from_position_id).join(RepertoireMove, Move.id == RepertoireMove.move_id).distinct().subquery()
        
        # Find moves that lead to these positions but aren't repertoire moves
        gaps = session.query(Move).outerjoin(RepertoireMove, Move.id == RepertoireMove.move_id)\
            .filter(RepertoireMove.id == None)\
            .filter(Move.to_position_id.in_(subq.select())).all()
        
        if not gaps:
            break
            
        # Pre-fetch min levels for outgoing and incoming moves in bulk (eliminates N+1 query loop)
        outgoing_min = dict(
            session.query(Move.from_position_id, func.min(RepertoireMove.level))
            .join(RepertoireMove, Move.id == RepertoireMove.move_id)
            .group_by(Move.from_position_id).all()
        )
        incoming_min = dict(
            session.query(Move.to_position_id, func.min(RepertoireMove.level))
            .join(RepertoireMove, Move.id == RepertoireMove.move_id)
            .group_by(Move.to_position_id).all()
        )

        for g in gaps:
            lvl_out = outgoing_min.get(g.to_position_id)
            lvl_in = incoming_min.get(g.from_position_id)
            candidates = [l for l in (lvl_out, lvl_in) if l is not None]
            lvl = min(candidates) if candidates else 1
            session.add(RepertoireMove(move_id=g.id, level=lvl))
            gaps_fixed += 1
        
        session.flush()
        if fast: break # Only one pass in fast mode

    if gaps_fixed > 0:
        logger.info(f"Maintenance: Fixed {gaps_fixed} repertoire gaps.")

    # 2. Enforce Level Consistency
    # Rule: If a move is in Level N, its parents should also be in Level <= N (higher priority).
    levels_updated = 0
    try:
        # Use a single UPDATE statement for efficiency and to avoid correlation issues
        # We find parent repertoire moves that have at least one child with a HIGHER priority level (lower number)
        # and update the parent to match that child's level.
        query = text("""
            UPDATE repertoire_moves
            SET level = (
                SELECT MIN(crm.level)
                FROM moves pm
                JOIN moves cm ON pm.to_position_id = cm.from_position_id
                JOIN repertoire_moves crm ON cm.id = crm.move_id
                WHERE pm.id = repertoire_moves.move_id
            )
            WHERE id IN (
                SELECT prm.id
                FROM repertoire_moves prm
                JOIN moves pm ON prm.move_id = pm.id
                JOIN moves cm ON pm.to_position_id = cm.from_position_id
                JOIN repertoire_moves crm ON cm.id = crm.move_id
                WHERE prm.level > crm.level
            )
        """)
        
        # We loop because updating a parent might create a new inconsistency with ITS parent (propagation)
        while True:
            res = session.execute(query)
            if res.rowcount == 0:
                break
            levels_updated += res.rowcount
            session.flush()
            if fast: break
            
    except Exception as e:
        logger.error(f"Maintenance: Error during level consistency repair: {e}")

    if levels_updated > 0:
        logger.info(f"Maintenance: Updated {levels_updated} levels for consistency.")

    # 3. Canonicalize Castling UCIs (Chess960 e1h1 -> Standard e1g1)
    castling_fixed = repair_castling_ucis(session)

    session.commit()
    return gaps_fixed, levels_updated

def repair_castling_ucis(session) -> int:
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
        session.commit()
        logger.info(f"Maintenance: Repaired {fixed_count} castling UCI moves to standard notation.")
        
    return fixed_count

def repair_unassigned_moves(session) -> int:
    """
    Finds moves in the database that originate from a known repertoire position
    but lack an entry in `repertoire_moves` (e.g. leaf moves of variations
    from older PGN imports), and assigns them to the parent move's repertoire level.
    """
    from sqlalchemy import func
    total_fixed = 0

    start_pos = session.query(Position).filter_by(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -").first()
    start_id = start_pos.id if start_pos else None

    while True:
        unassigned = session.query(Move).outerjoin(
            RepertoireMove, Move.id == RepertoireMove.move_id
        ).filter(
            RepertoireMove.id == None
        ).all()

        if not unassigned:
            break

        incoming_min = dict(
            session.query(Move.to_position_id, func.min(RepertoireMove.level))
            .join(RepertoireMove, Move.id == RepertoireMove.move_id)
            .group_by(Move.to_position_id).all()
        )

        pass_fixed = 0
        for m in unassigned:
            lvl = incoming_min.get(m.from_position_id)
            if lvl is None and start_id and m.from_position_id == start_id:
                lvl = 1
            if lvl is not None:
                session.add(RepertoireMove(move_id=m.id, level=lvl, is_active=True))
                pass_fixed += 1

        if pass_fixed == 0:
            break

        session.flush()
        total_fixed += pass_fixed

    if total_fixed > 0:
        session.commit()
        logger.info(f"Maintenance: Repaired {total_fixed} unassigned leaf moves into repertoire levels.")

    return total_fixed

def repair_schema_and_orphans(session):
    """Placeholder for other diagnostic repairs if needed."""
    # This logic remains in CreatorBackend for now as it involves DatabaseManager's migrate
    pass
