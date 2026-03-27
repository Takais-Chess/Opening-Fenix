import pytest
import chess
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Move, Position, RepertoireMove

@pytest.fixture
def backend(mock_user_dir):
    b = CreatorBackend()
    b.load_repertoire("ExtendedTest")
    return b

def test_add_and_delete_move(backend):
    start_fen = chess.STARTING_FEN
    backend.add_move(start_fen, "e2e4", "e4")
    
    # Verify move exists
    moves = backend.get_candidate_moves(start_fen)
    assert any(m['uci'] == 'e2e4' for m in moves)
    
    # Delete move
    backend.delete_move("e2e4", start_fen)
    
    # Verify move is gone
    moves_after = backend.get_candidate_moves(start_fen)
    assert not any(m['uci'] == 'e2e4' for m in moves_after)

def test_delete_move_recursive(backend):
    # Setup: 1. e4 e5 2. Nf3
    backend.add_move(chess.STARTING_FEN, "e2e4", "e4")
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    backend.add_move(e4_fen, "e7e5", "e5")
    e5_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    backend.add_move(e5_fen, "g1f3", "Nf3")
    
    # Delete 1. e4
    backend.delete_move("e2e4", chess.STARTING_FEN)
    
    # Verify all descendants are also cleaned up if orphaned (though RepertoireMove should be gone)
    # The Position objects might stay in DB but RepertoireMove should be gone.
    # In CreatorBackend.delete_move, it calls _delete_move_recursive which removes RepertoireMove.
    
    assert backend.session.query(RepertoireMove).count() == 0

def test_update_position_data(backend):
    start_fen = chess.STARTING_FEN
    backend.add_move(start_fen, "e2e4", "e4")
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    
    backend.update_position_data(e4_fen, "King's Pawn", "Open Games", "Sicilian", "Najdorf")
    
    data = backend.get_position_data(e4_fen)
    assert data['comment'] == "King's Pawn"
    assert data['variation_1'] == "Open Games"
    assert data['variation_2'] == "Sicilian"
    assert data['variation_3'] == "Najdorf"

def test_set_nag(backend):
    start_fen = chess.STARTING_FEN
    backend.add_move(start_fen, "e2e4", "e4")
    
    backend.set_nag("e2e4", start_fen, 1) # '!'
    
    moves = backend.get_candidate_moves(start_fen)
    e4_move = next(m for m in moves if m['uci'] == 'e2e4')
    assert e4_move['nag'] == 1

def test_repertoire_metadata(backend):
    # Default color is white
    assert backend.get_repertoire_color() == 'w'
    
    # Test description
    backend.set_repertoire_description("My test repertoire")
    assert backend.get_repertoire_description() == "My test repertoire"
    
    info = backend.get_repertoire_info()
    assert info['description'] == "My test repertoire"
    assert info['name'] == "ExtendedTest"

def test_add_repertoire_level(backend):
    backend.add_repertoire_level("New Level", 5)
    levels = backend.get_repertoire_levels()
    assert any(l['name'] == "New Level" and l['order'] == 5 for l in levels)

def test_rename_repertoire_level(backend):
    # First level is usually "Basic" or added by fixture
    # Let's add one to be sure
    backend.add_repertoire_level("OldName", 10)
    backend.rename_repertoire_level("OldName", "NewName")
    levels = backend.get_repertoire_levels()
    assert any(l['name'] == "NewName" for l in levels)
    assert not any(l['name'] == "OldName" for l in levels)
