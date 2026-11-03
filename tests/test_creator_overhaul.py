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


def test_overhaul_session_level_persistence(creator_window):
    """Test saving and loading overhaul session level in backend."""
    backend = creator_window.backend
    assert backend.get_overhaul_session_level() is None
    
    backend.save_overhaul_session_level(2)
    assert backend.get_overhaul_session_level() == 2
    
    backend.save_overhaul_session_level(None)
    assert backend.get_overhaul_session_level() is None


def test_repertoire_switch_isolates_sessions_and_levels(qapp, mock_user_dir):
    """Test that switching repertoires unloads session and preserves level settings per repertoire."""
    from opening_fenix.core.utils import get_repertoire_db_path
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.models import Base, RepertoireLevel, Position, Move, RepertoireMove
    import chess

    # 1. Setup RepoA and RepoB
    for r_name in ["RepoA", "RepoB"]:
        db_path = get_repertoire_db_path(r_name)
        db = DatabaseManager(db_path, base=Base)
        s = db.get_session()
        lvl1 = RepertoireLevel(name="Basics", order=1)
        lvl2 = RepertoireLevel(name="Deep Theory", order=2)
        s.add_all([lvl1, lvl2])
        p1 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
        p2 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR")
        s.add_all([p1, p2])
        s.flush()
        m = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4")
        s.add(m)
        s.flush()
        rm = RepertoireMove(move_id=m.id, level=1, is_active=True)
        s.add(rm)
        s.commit()
        db.close()

    # 2. Open Creator with RepoA
    win = CreatorWindow("RepoA")
    win.show()
    qapp.processEvents()

    # Ensure tab is active
    if not any("KONTROLLE" in win.tabs.tabText(i).upper() for i in range(win.tabs.count())):
        widget, title = win._all_tabs["KONTROLLE"]
        win.tabs.addTab(widget, title)
    for i in range(win.tabs.count()):
        if "KONTROLLE" in win.tabs.tabText(i).upper():
            win.tabs.setCurrentIndex(i)
            break
    qapp.processEvents()

    # In RepoA, select Level 1 (order 1)
    idx_lvl1 = -1
    for i in range(win.combo_overhaul_level.count()):
        if win.combo_overhaul_level.itemData(i) == 1:
            idx_lvl1 = i
            break
    assert idx_lvl1 != -1
    win.combo_overhaul_level.setCurrentIndex(idx_lvl1)
    qapp.processEvents()

    # Start session in RepoA with Level 1
    win.toggle_overhaul_session()
    qapp.processEvents()
    assert win.overhaul_active is True
    assert win.backend.get_overhaul_session_level() == 1
    assert win.combo_overhaul_level.isEnabled() is False

    # 3. Switch to RepoB (RepoB has NO active session)
    win.load_repertoire("RepoB")
    qapp.processEvents()

    # Verify session is NOT leaked into RepoB
    assert win.overhaul_active is False
    assert win.overhaul_start is None
    assert win.combo_overhaul_level.isEnabled() is True
    assert "Starten" in win.btn_overhaul_start.text()

    # In RepoB, user sets filter to Level 2 (Deep Theory)
    idx_lvl2 = -1
    for i in range(win.combo_overhaul_level.count()):
        if win.combo_overhaul_level.itemData(i) == 2:
            idx_lvl2 = i
            break
    assert idx_lvl2 != -1
    win.combo_overhaul_level.setCurrentIndex(idx_lvl2)
    qapp.processEvents()
    assert win.backend.get_meta("overhaul_selected_level") == "2"

    # 4. Switch back to RepoA
    win.load_repertoire("RepoA")
    qapp.processEvents()

    # Verify RepoA's session is restored and locked to Level 1
    assert win.overhaul_active is True
    assert win.overhaul_start is not None
    assert win.combo_overhaul_level.currentData() == 1
    assert win.combo_overhaul_level.isEnabled() is False
    assert "Fortsetzen" in win.btn_overhaul_start.text()

    win.close()

