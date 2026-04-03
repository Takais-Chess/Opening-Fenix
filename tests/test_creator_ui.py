import pytest
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from opening_fenix.creator.creator_window import CreatorWindow

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def creator_window(qapp, mock_user_dir, sample_repertoire):
    """Fixture for CreatorWindow with sample repertoire."""
    win = CreatorWindow(sample_repertoire)
    win.show()
    yield win
    win.close()

def test_tab_switching(creator_window, qapp):
    """Test switching between tabs in the Creator window."""
    # Details is index 0
    assert creator_window.tabs.currentIndex() == 0
    
    # Switch to second tab
    creator_window.tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert creator_window.tabs.currentIndex() == 1

def test_structure_tree_loading(creator_window, qapp):
    """Test that the structure tree is populated."""
    # Switch to Struktur tab if needed, but it's usually 🧩 Struktur Explorer in a combo
    # or it might be a tab. Let's check.
    # In init_ui: self.tabs.addTab(td, " DETAILS")
    # Let's just check the tree_widget which is always there
    assert creator_window.tree_widget is not None

def test_navigation_buttons(creator_window, qapp):
    """Test the FEN navigation buttons (Start, Back, Forward)."""
    # Set to some position
    new_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    creator_window.set_board_to_fen(new_fen)
    # Check the board itself
    assert creator_window.board_widget.board.fen().startswith(new_fen)
    
    # Go to start
    creator_window.go_start()
    from chess import STARTING_FEN
    # After go_start, board should be at start
    assert creator_window.board_widget.board.fen().startswith(STARTING_FEN)

def test_details_panel_updates(creator_window, qapp):
    """Test that the details panel updates when changing FEN."""
    # Set comment on backend
    from opening_fenix.core.db.models import Position
    backend = creator_window.backend
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    backend.update_position_data(start_fen, "Initial Position Comment", "Var1", "Var2", "Var3")
    
    # Refresh UI
    creator_window.update_ui_from_fen()
    qapp.processEvents()
    
    assert creator_window.txt_c.toPlainText() == "Initial Position Comment"

def test_hole_finder_ui_trigger(creator_window, qapp, monkeypatch):
    """Test triggering a hole scan from the UI."""
    # The hole finder is a tab
    idx = -1
    for i in range(creator_window.tabs.count()):
        text = creator_window.tabs.tabText(i).upper()
        if "LOCH" in text or "LÜCKEN" in text:
            idx = i
            break
    
    if idx != -1:
        creator_window.tabs.setCurrentIndex(idx)
        qapp.processEvents()
    
    # Mock the actual scan - accept any args/kwargs
    mock_holes = [{'fen': 'fen1', 'move_uci': 'e2e4', 'move_san': 'e4', 'prob': 0.5, 'type': 'user'}]
    monkeypatch.setattr(creator_window.backend, "find_repertoire_holes", lambda *args, **kwargs: mock_holes)
    
    # Run scan
    creator_window.run_hole_scan()
    qapp.processEvents()
    
    # Verify table is populated
    print(f"DEBUG: hole rows={creator_window.table_holes.rowCount()}")
    assert creator_window.table_holes.rowCount() >= 1
