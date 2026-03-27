import pytest
import chess
from opening_fenix.core.repertoire import RepertoireManager

def test_get_all_repertoires(mock_user_dir, sample_repertoire):
    mgr = RepertoireManager()
    repos = mgr.get_all_repertoires()
    assert sample_repertoire in repos

def test_set_active_repertoire(repertoire_manager, sample_repertoire):
    assert repertoire_manager.active_repertoire_name == sample_repertoire
    assert repertoire_manager.repo_session is not None

def test_get_repertoire_color(repertoire_manager):
    # Default is 'w'
    assert repertoire_manager.get_repertoire_color() == 'w'

def test_get_repertoire_levels(repertoire_manager):
    levels = repertoire_manager.get_repertoire_levels()
    assert len(levels) == 1
    assert levels[0]['name'] == "Basic"

def test_get_history_for_fen(repertoire_manager):
    e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    history = repertoire_manager.get_history_for_fen(e4_fen)
    assert len(history) == 1
    assert history[0]['san'] == "e4"
    assert history[0]['uci'] == "e2e4"

def test_get_repertoire_moves_for_fen(repertoire_manager):
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    moves = repertoire_manager.get_repertoire_moves_for_fen(start_fen)
    assert "e2e4" in moves
    assert len(moves) == 1

def test_get_explorer_data(repertoire_manager, training_manager):
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    data = repertoire_manager.get_explorer_data_for_fen(start_fen, training_manager)
    
    assert data['is_player_turn'] is True
    assert data['player_moves']['main_move']['san'] == "e4"
    assert data['box'] == 0
