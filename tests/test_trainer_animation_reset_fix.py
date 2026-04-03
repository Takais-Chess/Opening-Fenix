import os
import pytest
import chess
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6 import sip
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from unittest.mock import MagicMock, patch

@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def main_window(qapp, mock_user_dir, sample_repertoire):
    profile_name = "TestUser"
    win = MainWindow(profile_name)
    yield win
    win.close()
    if not sip.isdeleted(win):
        win.deleteLater()
    qapp.processEvents()

def test_animation_reset_to_variation_boundary(main_window, training_manager, repertoire_manager):
    """
    Verify that start_animation resets to the variation entry point instead of STARTING_FEN
    when a filter is active and the board is at an unrelated position.
    """
    session = repertoire_manager.repo_session
    repertoire_manager.set_active_repertoire("Test Repo")
    
    def get_or_create_pos(fen, **kwargs):
        existing = session.query(Position).filter_by(fen=fen).first()
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            return existing
        p = Position(fen=fen, **kwargs)
        session.add(p); session.flush()
        return p

    # 1. Setup variation: 1. e4 d6 2. d4 Nf6 3. Nc3 g6 (Classical Pirc)
    # Entry Point for "Classical Pirc" is P6 (after 3... g6)
    p0 = get_or_create_pos(chess.STARTING_FEN)
    
    # 1. e4
    p1 = get_or_create_pos("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
    session.add(m1)
    
    # ... skip some moves ...
    # P5 (before 3... g6)
    p5_fen = "rnbqkb1r/ppp1pppp/3p1n2/8/3PP3/2N5/PPP2PPP/R1BQKBNR b KQkq -"
    p5 = get_or_create_pos(p5_fen)
    
    # 3... g6 (Enters Classical Pirc)
    p6_fen = "rnbqkb1r/ppp1pp1p/3p1np1/8/3PP3/2N5/PPP2PPP/R1BQKBNR w KQkq -"
    p6 = get_or_create_pos(p6_fen, variation_2="Classical Pirc")
    m6 = Move(from_position_id=p5.id, to_position_id=p6.id, uci="g7g6", san="g6")
    session.add(m6)
    
    # 4. Nf3
    p7_fen = "rnbqkb1r/ppp1pp1p/3p1np1/8/3PP3/2N2N2/PPP2PPP/R1BQKB1R b KQkq -"
    p7 = get_or_create_pos(p7_fen)
    m7 = Move(from_position_id=p6.id, to_position_id=p7.id, uci="g1f3", san="Nf3")
    session.add(m7)
    
    # 4... Bg7 (Challenge Move)
    p8_fen = "rnbqk2r/ppp1ppbp/3p1np1/8/3PP3/2N2N2/PPP2PPP/R1BQKB1R w KQkq -"
    p8 = get_or_create_pos(p8_fen)
    m8 = Move(from_position_id=p7.id, to_position_id=p8.id, uci="f8g7", san="Bg7")
    session.add(m8)
    
    session.commit()
    
    # 2. Configure Main Window
    main_window.active_variation_filter = "Classical Pirc"
    main_window.active_variation_entry_fen = p6_fen
    main_window.current_move_obj = m8
    
    # Define history for mocks
    history = [
        {'san': 'e4', 'fen': p1.fen},
        {'san': 'd6', 'fen': '...'},
        {'san': 'd4', 'fen': '...'},
        {'san': 'Nf6', 'fen': '...'},
        {'san': 'Nc3', 'fen': p5_fen},
        {'san': 'g6', 'fen': p6_fen}, # Index 5
        {'san': 'Nf3', 'fen': p7_fen}, # Index 6
        {'san': 'Bg7', 'fen': p8_fen}  # Index 7
    ]

    # Mocking specifically the manager inside the window using patch to ensure it binds correctly
    with patch.object(main_window.repertoire_manager, 'get_history_for_move', return_value=history), \
         patch.object(main_window.repertoire_manager, 'get_variation_entry_point_fen', return_value=p6_fen):
         
        # 3. Simulate board being at an UNRELATED position (e.g. from another branch)
        main_window.board_widget.board.set_fen("8/8/8/8/8/8/8/8 w - -")
        original_set_fen = main_window.board_widget.set_fen
        main_window.board_widget.set_fen = MagicMock(side_effect=original_set_fen)
        
        # 4. Trigger Animation
        main_window.start_animation(None)
    
    # 5. Assertions
    # Board should be reset to p6_fen (Classical Pirc entry point), NOT chess.STARTING_FEN
    main_window.board_widget.set_fen.assert_called_with(p6_fen)
    
    # Animation moves should only be ['Nf3'] (History from p6 to m8)
    # Move 1-6 are the lead up to p6. Move 7 (idx 6) is Nf3.
    # history[:-1] is moves 1-7.
    # Animation pops the first (and only) move 'Nf3' to immediately start playing it.
    assert main_window.animation_moves == []
    assert main_window.board_widget.is_animating == True
    assert main_window.board_widget.animating_piece_data['move'].uci() == m7.uci
    
    print("Success: Animation correctly handles resets with filters!")
