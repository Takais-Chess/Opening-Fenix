import pytest
from opening_fenix.core.db.models import Position, Move, RepertoireMove
import datetime

def test_variation_filter_excludes_v2_transpositions(training_manager, repertoire_manager):
    """
    Test that the variation filter correctly prunes moves that transpose to a 
    different variation_2 branch.
    """
    session = repertoire_manager.repo_session
    
    # 1. Setup a complex repertoire with transpositions
    # Root: 1. e4
    # Branch A (Dragon): 1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 g6 (explicit v2="Dragon")
    # Branch B (Scheveningen): 1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 e6 (explicit v2="Scheveningen")
    # Transposition: A move from Dragon branch into Scheveningen branch.
    
    # Let's simplify for the test:
    # P1 (Start) -> m1 (e4) -> P2
    # P2 -> m2 (c5) -> P3
    # P3 -> m3 (Nf3) -> P4
    # P4 -> m4 (d6) -> P5
    # P5 -> m5 (d4) -> P6
    # P6 -> m6 (cxd4) -> P7
    # P7 -> m7 (Nxd4) -> P8
    # P8 -> m8 (Nf6) -> P9
    # P9 -> m9 (Nc3) -> P10
    
    # P10 -> m_dragon (g6) -> P_dragon (v2="Dragon")
    # P10 -> m_schev (e6) -> P_schev (v2="Scheveningen")
    
    # Now the "evil" transposition move:
    # P11_inside_dragon -> m_transpose -> P12_inside_scheveningen
    
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    p1 = session.query(Position).filter_by(fen=start_fen).first()
    
    # Create P10 (Sicilian after 5. Nc3)
    p10_fen = "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R b KQkq -"
    p10 = Position(fen=p10_fen)
    session.add(p10)
    session.flush()
    
    # P10 -> Dragon
    p_dragon_fen = "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq -"
    p_dragon = Position(fen=p_dragon_fen, variation_2="Dragon", cached_v2="Dragon")
    session.add(p_dragon)
    session.flush()
    m_dragon = Move(from_position_id=p10.id, to_position_id=p_dragon.id, uci="g7g6", san="g6", priority_score=1.0)
    session.add(m_dragon)
    
    # P10 -> Scheveningen
    p_schev_fen = "rnbqkb1r/pp3ppp/3ppn2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq -"
    p_schev = Position(fen=p_schev_fen, variation_2="Scheveningen", cached_v2="Scheveningen")
    session.add(p_schev)
    session.flush()
    m_schev = Move(from_position_id=p10.id, to_position_id=p_schev.id, uci="e7e6", san="e6", priority_score=1.0)
    session.add(m_schev)
    
    # Position AFTER some Dragon moves
    # P_dragon -> m_a -> P_dragon_2
    p_dragon_2_fen = "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N2P2/PPP3PP/R1BQKB1R b KQkq -"
    p_dragon_2 = Position(fen=p_dragon_2_fen, cached_v2="Dragon")
    session.add(p_dragon_2)
    session.flush()
    m_a = Move(from_position_id=p_dragon.id, to_position_id=p_dragon_2.id, uci="f2f3", san="f3", priority_score=1.0)
    session.add(m_a)
    
    # THE TRANSPOSITION MOVE:
    # A move from p_dragon_2 that lands in a position that is cached as Scheveningen
    # (In reality this would be some weird move that transposes back or sideways)
    p_transposed_fen = "rnbqkb1r/pp3ppp/3ppn2/8/3NP3/2N2P2/PPP3PP/R1BQKB1R b KQkq -"
    p_transposed = Position(fen=p_transposed_fen, cached_v2="Scheveningen") 
    session.add(p_transposed)
    session.flush()
    
    m_transpose = Move(from_position_id=p_dragon_2.id, to_position_id=p_transposed.id, uci="h2h4", san="h4", priority_score=0.5)
    session.add(m_transpose)
    session.flush()
    
    # Mark moves as repertoire moves
    session.add(RepertoireMove(move_id=m_dragon.id, level=1))
    session.add(RepertoireMove(move_id=m_schev.id, level=1))
    session.add(RepertoireMove(move_id=m_a.id, level=1))
    session.add(RepertoireMove(move_id=m_transpose.id, level=1))
    
    session.commit()
    
    # Reset training manager caches to see new data
    training_manager.on_repertoire_changed()
    
    # 2. Test without filter
    all_moves_ids = training_manager._build_variation_move_set(None)
    # Without filter, all_moves_ids should be empty because _build_variation_move_set returns empty set for None 
    # (it expects get_stats/get_next_move to handle None case)
    # But let's verify Dragon filter specifically.
    
    # 3. Test with "Dragon" filter
    dragon_move_ids = training_manager._build_variation_move_set("Dragon")
    
    # Assertions
    assert m_dragon.id in dragon_move_ids, "Dragon move should be in set"
    assert m_a.id in dragon_move_ids, "Move inside Dragon should be in set"
    
    # THE FIX VERIFICATION:
    assert m_transpose.id not in dragon_move_ids, "Transposing move to Scheveningen branch should be PRUNED"
    
    # Verify Scheveningen move is also not in Dragon set (unless it's a lead-up, but here it's a sibling)
    assert m_schev.id not in dragon_move_ids, "Sibling branch move should not be in Dragon set"

def test_variation_filter_legacy_pruning(training_manager, repertoire_manager):
    """
    Verify that explicit tags are still pruning correctly (original functionality).
    """
    session = repertoire_manager.repo_session
    
    p_root = session.query(Position).filter_by(variation_2="Dragon").first()
    if not p_root:
        # If running standalone, we need to setup. But let's assume it runs after the previous test
        # or use a fresh setup if needed. Pytest fixtures are function-scoped by default, 
        # so we might need to redo setup or use a module-scoped one.
        # Let's just do a quick setup here.
        p_root = Position(fen="rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq -", variation_2="Dragon")
        session.add(p_root)
        session.flush()

    # Move to a position with explicit OTHER name
    p_other = Position(fen="8/8/8/8/8/8/8/8 w - -", variation_1="ExplicitOther")
    session.add(p_other)
    session.flush()
    
    m_to_other = Move(from_position_id=p_root.id, to_position_id=p_other.id, uci="h2h3", san="h3")
    session.add(m_to_other)
    session.commit()
    
    training_manager.on_repertoire_changed()
    dragon_ids = training_manager._build_variation_move_set("Dragon")
    
    assert m_to_other.id not in dragon_ids, "Move to explicit OTHER variation should be pruned (legacy logic)"

def test_v1_filter_includes_v2_subvariation(training_manager, repertoire_manager):
    """
    Test that filtering for Variantenname 1 now correctly INCLUDES moves tagged 
    as Variantenname 2 under it, instead of pruning them.
    """
    session = repertoire_manager.repo_session
    
    # Setup: 
    # Root (V1="Sicilian") -> Move A -> Pos B (V2="Najdorf", inherits V1="Sicilian")
    # Pos B -> Move C -> Pos D (inner Najdorf)
    
    p_start = Position(fen="start", variation_1="Sicilian", cached_v1="Sicilian")
    session.add(p_start)
    session.flush()
    
    p_najdorf = Position(fen="najdorf", variation_2="Najdorf", cached_v1="Sicilian", cached_v2="Najdorf")
    session.add(p_najdorf)
    session.flush()
    
    m_a = Move(from_position_id=p_start.id, to_position_id=p_najdorf.id, uci="e2e4", san="e4")
    session.add(m_a)
    
    p_inner = Position(fen="inner", cached_v1="Sicilian", cached_v2="Najdorf")
    session.add(p_inner)
    session.flush()
    
    m_c = Move(from_position_id=p_najdorf.id, to_position_id=p_inner.id, uci="d2d3", san="d3")
    session.add(m_c)
    
    session.commit()
    
    # 2. Filter for "Sicilian" (V1)
    training_manager.on_repertoire_changed()
    sicilian_ids = training_manager._build_variation_move_set("Sicilian")
    
    # Assertions
    assert m_a.id in sicilian_ids, "Entry move to Najdorf should be included in Sicilian V1 filter"
    assert m_c.id in sicilian_ids, "Inner Najdorf move should be included in Sicilian V1 filter (FIXED)"
    
    # 3. Filter for "Najdorf" (V2)
    training_manager.on_repertoire_changed()
    najdorf_ids = training_manager._build_variation_move_set("Najdorf")
    
    assert m_a.id in najdorf_ids, "Lead-up to Najdorf should be included"
    assert m_c.id in najdorf_ids, "Inner Najdorf move should be included in Najdorf V2 filter"
