import pytest
import chess
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove

def clean_fen(fen):
    return " ".join(fen.split(" ")[:4])

@pytest.fixture
def backend(mock_user_dir, sample_repertoire):
    be = CreatorBackend()
    be.load_repertoire(sample_repertoire)
    yield be
    if be.session:
        be.session.close()
    if be.db_manager:
        be.db_manager.close()

def test_mark_position_reviewed(backend):
    start_fen_full = chess.STARTING_FEN
    start_fen = clean_fen(start_fen_full)
    
    # Initially None
    pos = backend.session.query(Position).filter_by(fen=start_fen).first()
    assert pos is not None
    assert pos.last_overhaul_review is None
    
    backend.mark_position_reviewed(start_fen_full)
    backend.session.expire_all()
    
    pos = backend.session.query(Position).filter_by(fen=start_fen).first()
    assert pos.last_overhaul_review is not None

def test_get_overhaul_stats(backend):
    # sample_repertoire has 3 positions: start, e4, e5. 
    # But only start->e4 move is in RepertoireMove.
    # So reachable positions are start and e4. Total = 2.
    reviewed, total = backend.get_overhaul_stats()
    assert total == 2
    assert reviewed == 0
    
    backend.mark_position_reviewed(chess.STARTING_FEN)
    reviewed, total = backend.get_overhaul_stats()
    assert reviewed == 1
    assert total == 2

def test_find_nearest_unreviewed(backend):
    start_fen = clean_fen(chess.STARTING_FEN)
    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    
    # In sample_repertoire, e5 is not a RepertoireMove, so find_nearest won't visit it.
    
    # Nearest to start should be start itself.
    nearest = backend.find_nearest_unreviewed(start_fen)
    assert nearest == start_fen
    
    # Mark start as reviewed
    backend.mark_position_reviewed(start_fen)
    
    # Nearest to start should now be e4 (1 move away)
    nearest = backend.find_nearest_unreviewed(start_fen)
    assert nearest == e4_fen
    
    # Mark e4 as reviewed
    backend.mark_position_reviewed(e4_fen)
    
    # No more unreviewed reachable positions
    nearest = backend.find_nearest_unreviewed(start_fen)
    assert nearest is None

def test_reset_overhaul_progress(backend):
    backend.mark_position_reviewed(chess.STARTING_FEN)
    reviewed, _ = backend.get_overhaul_stats()
    assert reviewed == 1
    
    backend.reset_overhaul_progress()
    backend.session.expire_all()
    
    reviewed, _ = backend.get_overhaul_stats()
    assert reviewed == 0
