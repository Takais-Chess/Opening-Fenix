import pytest
import chess
from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.creator.creator_window import CreatorBackend

@pytest.fixture
def backend(mock_user_dir):
    """Fixture to provide a clean CreatorBackend for each test."""
    b = CreatorBackend()
    b.load_repertoire("IntensiveInheritanceTest")
    # load_repertoire auto-seeds 3 default levels (order 1, 2, 3).
    # Rename them to the expected names for these tests to avoid UNIQUE constraint errors.
    levels = b.session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
    expected_names = ["Level 1", "Level 2", "Level 3"]
    for lvl, name in zip(levels, expected_names):
        lvl.name = name
    b.session.commit()
    return b

def get_move_by_uci(backend, from_fen, uci):
    clean_fen = " ".join(from_fen.split(" ")[:4])
    pos = backend.session.query(Position).filter_by(fen=clean_fen).first()
    if not pos: return None
    return backend.session.query(Move).filter_by(from_position_id=pos.id, uci=uci).first()

def get_rep_move(backend, move_id):
    return backend.session.query(RepertoireMove).filter_by(move_id=move_id).first()

def test_deep_line_propagation(backend):
    """Test that level changes propagate deep down a single line based on Minimum Clamping."""
    fens = [chess.STARTING_FEN]
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"] # Ruy Lopez
    
    curr_fen = fens[0]
    move_ids = []
    for m in moves:
        board = chess.Board(curr_fen)
        san = board.san(chess.Move.from_uci(m))
        backend.add_move(curr_fen, m, san, level_order=1)
        
        move_obj = get_move_by_uci(backend, curr_fen, m)
        move_ids.append(move_obj.id)
        
        board.push_uci(m)
        curr_fen = board.fen()
        fens.append(curr_fen)

    # Change first move to Level 2
    backend.update_move_level(move_ids[0], 2)
    
    # Check all moves in the line - they were L1, so they should be clamped down to L2
    for i, mid in enumerate(move_ids):
        rm = get_rep_move(backend, mid)
        assert rm.level == 2, f"Move {i} ({moves[i]}) should have cascaded to Level 2"

def test_clamping_preserves_lower_priority(backend):
    """
    Test that if a move is demoted (L1 -> L2), a child that is ALREADY L3 
    remains L3 and is not incorrectly promoted.
    """
    start = chess.STARTING_FEN
    backend.add_move(start, "e2e4", "e4", level_order=1)
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    
    # Add a main line (L1) and a side line (L3)
    backend.add_move(e4_fen, "e7e5", "e5", level_order=1)
    backend.add_move(e4_fen, "c7c5", "c5", level_order=3)
    
    e5_move = get_move_by_uci(backend, e4_fen, "e7e5")
    c5_move = get_move_by_uci(backend, e4_fen, "c7c5")
    
    # Demote e4 to L2
    e4_move = get_move_by_uci(backend, start, "e2e4")
    backend.update_move_level(e4_move.id, 2)
    
    # NEW BEHAVIOR: e5 (was L1) is DEMOTED to L2 because e4_move became L2 
    # and e4_move is the ONLY path to e4_fen.
    # Even if e4_fen has TWO outgoing moves (e5 and c5), they should BOTH be demoted
    # if their current level (1) is stronger than the best incoming level (2).
    assert get_rep_move(backend, e5_move.id).level == 2, "e5 should have been demoted to L2"
    
    # c5 (was L3) should REMAIN L3 because L3 is already weaker than L2
    assert get_rep_move(backend, c5_move.id).level == 3, "Side line (L3) should NOT be modified"

def test_transposition_branch_local_inheritance(backend):
    """
    Test transposition with 2 paths reaching the same position.
    New rule: Level changes follow the modified branch if it's a forced line, 
    ignoring other paths. This prevents 'global' automatic updates.
    """
    # Path A: 1. e4 e6 2. d4 (L2)
    # Path B: 1. d4 e6 2. e4 (L1)
    
    # Setup Path A
    backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=2)
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    backend.add_move(e4_fen, "e7e6", "e6", level_order=2)
    e6_fen_from_e4 = "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    
    # Setup Path B
    backend.add_move(chess.STARTING_FEN, "d2d4", "d4", level_order=1)
    d4_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -"
    backend.add_move(d4_fen, "e7e6", "e6", level_order=1)
    e6_fen_from_d4 = "rnbqkbnr/pppp1ppp/4p3/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq -"
    
    # Merge at Target FEN
    # Path A: ... -> e6_fen_from_e4 (Pos A) --2. d4--> TargetPos
    # Path B: ... -> e6_fen_from_d4 (Pos B) --2. e4--> TargetPos
    
    backend.add_move(e6_fen_from_d4, "e2e4", "e4", level_order=1) # Path B now merges into TargetPos
    target_pos_id = get_move_by_uci(backend, e6_fen_from_d4, "e2e4").to_position_id
    
    # Add a follow-up move from the TargetPos (this is a CHILD of both paths)
    # TargetPos --d7d5--> NextPos
    board = chess.Board("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    board.push_uci("d2d4")
    target_fen = board.fen() # Position after 1. e4 e6 2. d4
    
    backend.add_move(target_fen, "d7d5", "d5", level_order=1)
    d5_move = get_move_by_uci(backend, target_fen, "d7d5")
    
    # Initially L1
    assert get_rep_move(backend, d5_move.id).level == 1
    
    # Now, change Path B's last move (2. e4) to Level 3.
    # It leads to TargetPos, where d7d5 is the ONLY move.
    # d7d5 should become Level 3, even if Path A reached TargetPos with Level 2.
    move_b = get_move_by_uci(backend, e6_fen_from_d4, "e2e4")
    backend.update_move_level(move_b.id, 3)
    
    assert get_rep_move(backend, d5_move.id).level == 3, "Should follow the modified branch and update the shared child"

def test_circular_dependency_stability(backend):
    """
    Test that the recursive update doesn't crash on (hypothetical) cycles.
    """
    # Create a loop in positions
    # Pos 1 --m1--> Pos 2 --m2--> Pos 1
    p1 = Position(fen="pos1")
    p2 = Position(fen="pos2")
    backend.session.add_all([p1, p2])
    backend.session.flush()
    
    m1 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="m1", san="m1")
    m2 = Move(from_position_id=p2.id, to_position_id=p1.id, uci="m2", san="m2")
    backend.session.add_all([m1, m2])
    backend.session.flush()
    
    rm1 = RepertoireMove(move_id=m1.id, level=1)
    rm2 = RepertoireMove(move_id=m2.id, level=1)
    backend.session.add_all([rm1, rm2])
    backend.session.commit()
    
    # Update level of m1 - should not infinite loop
    backend.update_move_level(m1.id, 2)
    
    assert get_rep_move(backend, m1.id).level == 2
    assert get_rep_move(backend, m2.id).level == 2
