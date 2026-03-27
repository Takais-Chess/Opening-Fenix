import os
import pytest
import opening_fenix.core.data_tools as dt
import chess

def test_get_user_dir(mock_user_dir):
    user_dir = dt.get_user_dir()
    assert user_dir == mock_user_dir
    assert os.path.exists(user_dir)
    assert os.path.isdir(user_dir)

def test_get_base_path():
    base_path = dt.get_base_path()
    assert os.path.exists(base_path)
    assert os.path.isdir(base_path)

def test_normalize_fen():
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    # Should only keep first 4 parts
    norm = dt.normalize_fen(board)
    assert norm == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"

def test_normalize_fen_with_moves():
    board = chess.Board()
    board.push_san("e4")
    norm = dt.normalize_fen(board)
    assert norm == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
