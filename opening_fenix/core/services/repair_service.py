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
            .filter(Move.to_position_id.in_(subq)).all()
        
        if not gaps:
            break
            
        for g in gaps:
            # Find the minimum level among parents AND children of this move
            min_related_level = session.query(func.min(RepertoireMove.level))\
                .filter(Move.id == RepertoireMove.move_id)\
                .filter(
                    (Move.from_position_id == g.to_position_id) | 
                    # If g.from_position_id is missing, default to no parent check. Safeline.
                    (Move.to_position_id == g.from_position_id)
                ).scalar()
            
            lvl = min_related_level if min_related_level is not None else 1
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

    session.commit()
    return gaps_fixed, levels_updated

def repair_schema_and_orphans(session):
    """Placeholder for other diagnostic repairs if needed."""
    # This logic remains in CreatorBackend for now as it involves DatabaseManager's migrate
    pass
