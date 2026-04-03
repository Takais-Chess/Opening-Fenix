import pytest
import chess
from opening_fenix.core.db.models import Position, Move, RepertoireMove, TrainingData
import datetime

def test_ancestor_search_stops_at_variation_boundary(training_manager, repertoire_manager):
    """
    Test that _get_ancestor stops at the variation entry point when a filter is active,
    preventing the sequence from starting before the variation root.
    """
    repertoire_name = "Pirc Defense"
    repertoire_manager.set_active_repertoire(repertoire_name)
    session = repertoire_manager.repo_session
    
    # Setup positions
    # Initial -> 1. e4 (m1) -> P1
    # P1 -> 1... d6 (m2) -> P2 (Variation 1: Pirc Defense)
    # P2 -> 2. d4 (m3) -> P3 (Variation 1: Pirc Defense)
    # P3 -> 2... Nf6 (m4) -> P4 (Variation 1: Pirc Defense)
    # P4 -> 3. Nc3 (m5) -> P5 (Variation 1: Pirc Defense)
    # P5 -> 3... g6 (m6) -> P6 (Variation 2: Classical Pirc)
    # P6 -> 4. Nf3 (m7) -> P7
    # P7 -> 4... Bg7 (m8) -> P8 (Variation 2: Classical Pirc)
    
    def get_or_create_pos(fen, **kwargs):
        existing = session.query(Position).filter_by(fen=fen).first()
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            return existing
        p = Position(fen=fen, **kwargs)
        session.add(p); session.flush()
        return p

    p0 = get_or_create_pos(chess.STARTING_FEN)
    
    # 1. e4
    p1_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    p1 = get_or_create_pos(p1_fen)
    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
    session.add(m1)
    
    # 1... d6 (Variation Root for Pirc)
    p2_fen = "rnbqkbnr/ppp1pppp/3p4/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    p2 = get_or_create_pos(p2_fen, variation_1="Pirc Defense", cached_v1="Pirc Defense")
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="d7d6", san="d6")
    session.add(m2)
    
    # 2. d4
    p3_fen = "rnbqkbnr/ppp1pppp/3p4/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq -"
    p3 = get_or_create_pos(p3_fen, cached_v1="Pirc Defense")
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="d2d4", san="d4")
    session.add(m3)
    
    # 2... Nf6
    p4_fen = "rnbqkb1r/ppp1pppp/3p1n2/8/3PP3/8/PPP2PPP/RNBQKBNR w KQkq -"
    p4 = get_or_create_pos(p4_fen, cached_v1="Pirc Defense")
    m4 = Move(from_position_id=p3.id, to_position_id=p4.id, uci="g8f6", san="Nf6")
    session.add(m4)
    
    # 3. Nc3
    p5_fen = "rnbqkb1r/ppp1pppp/3p1n2/8/3PP3/2N5/PPP2PPP/R1BQKBNR b KQkq -"
    p5 = get_or_create_pos(p5_fen, cached_v1="Pirc Defense")
    m5 = Move(from_position_id=p4.id, to_position_id=p5.id, uci="b1c3", san="Nc3")
    session.add(m5)
    
    # 3... g6 (Variation Root for Classical Pirc)
    p6_fen = "rnbqkb1r/ppp1pp1p/3p1np1/8/3PP3/2N5/PPP2PPP/R1BQKBNR w KQkq -"
    p6 = get_or_create_pos(p6_fen, variation_2="Classical Pirc", cached_v1="Pirc Defense", cached_v2="Classical Pirc")
    m6 = Move(from_position_id=p5.id, to_position_id=p6.id, uci="g7g6", san="g6")
    session.add(m6)
    
    # 4. Nf3
    p7_fen = "rnbqkb1r/ppp1pp1p/3p1np1/8/3PP3/2N2N2/PPP2PPP/R1BQKB1R b KQkq -"
    p7 = get_or_create_pos(p7_fen, cached_v1="Pirc Defense", cached_v2="Classical Pirc")
    m7 = Move(from_position_id=p6.id, to_position_id=p7.id, uci="g1f3", san="Nf3")
    session.add(m7)
    
    # 4... Bg7
    p8_fen = "rnbqk2r/ppp1ppbp/3p1np1/8/3PP3/2N2N2/PPP2PPP/R1BQKB1R w KQkq -"
    p8 = get_or_create_pos(p8_fen, cached_v1="Pirc Defense", cached_v2="Classical Pirc")
    m8 = Move(from_position_id=p7.id, to_position_id=p8.id, uci="f8g7", san="Bg7")
    session.add(m8)
    
    # Mark as repertoire moves (Player side: Black)
    session.flush()
    session.add(RepertoireMove(move_id=m2.id, level=1)) # 1... d6
    session.add(RepertoireMove(move_id=m4.id, level=1)) # 2... Nf6
    session.add(RepertoireMove(move_id=m6.id, level=1)) # 3... g6
    session.add(RepertoireMove(move_id=m8.id, level=1)) # 4... Bg7
    
    session.commit()
    
    training_manager.on_repertoire_changed()
    
    # Scenario: User is filtered for "Classical Pirc" (starts at 3... g6)
    # The picked move is 4... Bg7 (m8).
    # All moves before it are NOT learned.
    
    # Without the fix, _get_ancestor(m8) would go all the way back to initial position 
    # (since no moves are learned).
    
    # 1. Verify Entry Point
    entry_fen = repertoire_manager.get_variation_entry_point_fen("Classical Pirc")
    # Entry point should be p6 (the first position with the tag)
    assert entry_fen.startswith("rnbqkb1r/ppp1pp1p/3p1np1/8/3PP3/2N5/PPP2PPP/R1BQKBNR w KQkq")

    # 2. Test _get_ancestor with filter
    ancestor = training_manager._get_ancestor(m8, check_due=False, variation_filter="Classical Pirc")
    
    # It should stop at m8 (4... Bg7) because its parent (m7: 4. Nf3) starts at the boundary (P6)
    assert ancestor.uci == "f8g7", f"Should stop at 4... Bg7, but got {ancestor.san} (UCI: {ancestor.uci})"
    
    # 3. Test _get_ancestor without filter (legacy behavior)
    ancestor_no_filter = training_manager._get_ancestor(m8, check_due=False, variation_filter=None)
    # Should be m2 (1... d6) because m1 has no parent
    assert ancestor_no_filter.uci == "d7d6"

    print("Success: Ancestor search respects variation boundaries!")
