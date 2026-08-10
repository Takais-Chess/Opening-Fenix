import pytest
import chess.pgn
import io
from opening_fenix.creator.creator_window import CreatorBackend

@pytest.fixture
def backend(mock_user_dir):
    b = CreatorBackend()
    b.load_repertoire("PGNTest")
    return b

def test_import_simple_pgn(backend):
    pgn_text = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6"
    success, msg = backend.import_pgn_text(pgn_text)
    assert success is True
    
    # Verify moves in DB
    start_fen = chess.STARTING_FEN
    moves = backend.get_candidate_moves(start_fen)
    assert any(m['san'] == 'e4' for m in moves)
    
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    moves_e4 = backend.get_candidate_moves(e4_fen)
    assert any(m['san'] == 'e5' for m in moves_e4)

def test_import_pgn_with_comments_and_nags(backend):
    pgn_text = "1. e4 {Best move} e5 2. Nf3 Nc6 3. Bb5! a6"
    backend.import_pgn_text(pgn_text)
    
    # Check comment for 1. e4
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    data = backend.get_position_data(e4_fen)
    assert data['comment'] == "Best move"
    
    # Check NAG for 3. Bb5
    # Move tree: 1. e4 e5 2. Nf3 Nc6 3. Bb5
    board = chess.Board()
    board.push_san("e4")
    board.push_san("e5")
    board.push_san("Nf3")
    board.push_san("Nc6")
    bb5_parent_fen = board.fen()
    
    moves = backend.get_candidate_moves(bb5_parent_fen)
    bb5_move = next(m for m in moves if m['san'] == 'Bb5')
    assert bb5_move['nag'] == 1 # '!' is NAG 1

def test_import_pgn_with_variations(backend):
    pgn_text = "1. e4 (1. d4 d5) e5"
    backend.import_pgn_text(pgn_text)
    
    start_fen = chess.STARTING_FEN
    moves = backend.get_candidate_moves(start_fen)
    assert any(m['san'] == 'e4' for m in moves)
    assert any(m['san'] == 'd4' for m in moves)

def test_export_pgn(backend):
    # Add some moves
    backend.add_move(chess.STARTING_FEN, "e2e4", "e4")
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    backend.add_move(e4_fen, "e7e5", "e5")
    backend.update_position_data(e4_fen, "King's Pawn", "", "", "")
    
    pgn_output = backend.export_pgn()
    assert "e4" in pgn_output
    assert "e5" in pgn_output
    assert "King's Pawn" in pgn_output
    
    # Parse back to verify
    game = chess.pgn.read_game(io.StringIO(pgn_output))
    assert game.headers["Event"] == "PGNTest"
    main_line = [node.san() for node in game.mainline()]
    assert main_line == ["e4", "e5"]

def test_export_pgn_max_level(backend):
    # Add moves at different levels
    backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=1)
    backend.add_move(chess.STARTING_FEN, "d2d4", "d4", level_order=2)
    
    # Export only level 1
    pgn_l1 = backend.export_pgn(max_l=1)
    assert "e4" in pgn_l1
    assert "d4" not in pgn_l1
    
    # Export level 2
    pgn_l2 = backend.export_pgn(max_l=2)
    assert "e4" in pgn_l2
    assert "d4" in pgn_l2

def test_import_pgn_append_comments(backend):
    # Initial import with comment
    pgn1 = "1. e4 {First comment}"
    backend.import_pgn_text(pgn1)
    
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    data = backend.get_position_data(e4_fen)
    assert data['comment'] == "First comment"
    
    # Second import with different comment
    pgn2 = "1. e4 {Second comment}"
    backend.import_pgn_text(pgn2)
    
    data = backend.get_position_data(e4_fen)
    assert data['comment'] == "First comment | Second comment"
    
    # Third import with same comment (should be ignored)
    backend.import_pgn_text(pgn2)
    data = backend.get_position_data(e4_fen)
    assert data['comment'] == "First comment | Second comment"

def test_import_pgn_to_db_target_language(mock_user_dir, temp_dir):
    import os
    from opening_fenix.core.services.import_service import import_pgn_to_db
    from opening_fenix.core.utils import get_repertoire_db_path, get_multilingual_comment_dict
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Position
    
    pgn_path = os.path.join(temp_dir, "english_comments.pgn")
    with open(pgn_path, "w", encoding="utf-8") as f:
        f.write("1. e4 {Strong pawn center} e5")
        
    repo_name = "LangImportRepo"
    success, msg = import_pgn_to_db(pgn_path, repo_name, "w", "Core", 1, target_lang="en")
    assert success is True
    
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    pos = session.query(Position).filter_by(fen=e4_fen).first()
    assert pos is not None
    cdict = get_multilingual_comment_dict(pos.comment)
    assert cdict.get("en") == "Strong pawn center"
    session.close()
    db.close()
