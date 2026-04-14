import pytest
from PyQt6.QtCore import Qt
from opening_fenix.creator.creator_window import CreatorWindow

@pytest.fixture
def creator_window(qapp, mock_user_dir, sample_repertoire):
    """Fixture for CreatorWindow."""
    win = CreatorWindow(sample_repertoire)
    win.show()
    yield win
    win.close()

def test_overhaul_session_ui_flow(creator_window, qapp, monkeypatch):
    """Test the UI flow for starting and running an overhaul session."""
    # 1. Ensure Rep. Kontrolle tab is visible
    # By default, only DETAILS and ANALYSIS might be active
    if not any("KONTROLLE" in creator_window.tabs.tabText(i).upper() for i in range(creator_window.tabs.count())):
        widget, title = creator_window._all_tabs["KONTROLLE"]
        creator_window.tabs.addTab(widget, title)
    
    idx = -1
    for i in range(creator_window.tabs.count()):
        if "KONTROLLE" in creator_window.tabs.tabText(i).upper():
            idx = i
            break
    assert idx != -1
    creator_window.tabs.setCurrentIndex(idx)
    qapp.processEvents()
    
    # Fix: select a level first, otherwise toggle_overhaul_session returns early
    if creator_window.combo_overhaul_level.count() > 0:
        creator_window.combo_overhaul_level.setCurrentIndex(0)
    else:
        # Fallback if not populated for some reason
        creator_window.combo_overhaul_level.addItem("Test Level", userData=1)
        creator_window.combo_overhaul_level.setCurrentIndex(0)
    
    # 2. Start session
    # Initial state should be "Starten"
    assert "Starten" in creator_window.btn_overhaul_start.text()
    
    # Trigger start
    creator_window.toggle_overhaul_session()
    qapp.processEvents()
    
    # After start, overhaul_start should be set in the window
    assert creator_window.overhaul_start is not None
    
    # 3. Test progress bar (should be 0% initially)
    assert creator_window.pb_overhaul.value() >= 0
    
    # 4. Jump to next unchecked
    # We monkeypatch find_nearest_unreviewed to return a specific FEN
    test_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    monkeypatch.setattr(creator_window.backend, "find_nearest_unreviewed", lambda *args, **kwargs: test_fen)
    
    creator_window.jump_to_next_unchecked()
    qapp.processEvents()
    
    # Current board should be at test_fen
    assert creator_window.board_widget.board.fen().startswith(test_fen)
    
    # 5. Mark reviewed
    # In the UI, mark_position_reviewed is a method of CreatorBackend
    creator_window.backend.mark_position_reviewed(test_fen)
    qapp.processEvents()
    
    # 6. Reset session
    # Mock confirmation box
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.question", lambda *args, **kwargs: 16384) # Yes/Okay
    creator_window.reset_overhaul_session()
    qapp.processEvents()

def test_overhaul_filters(creator_window, qapp):
    """Test filtering in the overhaul tab."""
    # Ensure Rep. Kontrolle tab is visible
    if not any("KONTROLLE" in creator_window.tabs.tabText(i).upper() for i in range(creator_window.tabs.count())):
        widget, title = creator_window._all_tabs["KONTROLLE"]
        creator_window.tabs.addTab(widget, title)

    idx = -1
    for i in range(creator_window.tabs.count()):
        if "KONTROLLE" in creator_window.tabs.tabText(i).upper():
            idx = i
            break
    creator_window.tabs.setCurrentIndex(idx)
    qapp.processEvents()
    
    # Change level filter
    creator_window.combo_overhaul_level.setCurrentIndex(1)
    qapp.processEvents()
    
    # Change variation filter
    if creator_window.combo_overhaul_variation.count() > 1:
        creator_window.combo_overhaul_variation.setCurrentIndex(1)
        qapp.processEvents()
    
    # Verify UI reflects change
    assert creator_window.combo_overhaul_level.currentIndex() == 1
