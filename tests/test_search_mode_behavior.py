import time
import pytest
from PyQt6.QtCore import Qt
from opening_fenix.creator.creator_window import CreatorWindow

def ensure_holes_tab_active(creator_window, qapp):
    active_tabs = creator_window.config.get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
    if "HOLES" not in active_tabs:
        new_active = list(active_tabs)
        new_active.append("HOLES")
        creator_window.config["creator_active_tabs"] = new_active
        creator_window.apply_tab_visibility()
        qapp.processEvents()

    found_idx = creator_window.tabs.indexOf(creator_window.tab_holes)
    if found_idx == -1:
        for i in range(creator_window.tabs.count()):
            if any(k in creator_window.tabs.tabText(i).lower() for k in ["loch", "such", "search", "hole"]):
                found_idx = i
                break
    if found_idx != -1:
        creator_window.tabs.setCurrentIndex(found_idx)
        qapp.processEvents()

def test_search_mode_button_state_and_stop_click(creator_window, qapp, monkeypatch):
    """Test that starting search keeps button enabled with stop text, and clicking stops the search."""
    ensure_holes_tab_active(creator_window, qapp)

    # Mock long-running search that respects cancel_check
    def slow_task(*args, **kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(50):
            if cancel_check and cancel_check():
                break
            time.sleep(0.05)
        return []

    monkeypatch.setattr("opening_fenix.core.threads.run_hole_finder_task", slow_task)

    # Initial state
    assert creator_window.btn_hole_scan.isEnabled()
    assert any(k in creator_window.btn_hole_scan.text() for k in ["Suchen", "Search"])

    # Start search
    creator_window.run_hole_scan()
    qapp.processEvents()

    # Search is active: button must be enabled and show cancel/stop
    assert creator_window.hole_thread is not None
    assert creator_window.hole_thread.isRunning()
    assert creator_window.btn_hole_scan.isEnabled()
    assert any(k in creator_window.btn_hole_scan.text() for k in ["Abbrechen", "Stop"])

    # Click the button to stop the search
    creator_window.btn_hole_scan.click()
    qapp.processEvents()
    time.sleep(0.1)
    qapp.processEvents()

    # Thread stopped, button reset to Suchen/Search, status updated to abgebrochen/cancelled
    assert creator_window.hole_thread is None
    assert creator_window.btn_hole_scan.isEnabled()
    assert any(k in creator_window.btn_hole_scan.text() for k in ["Suchen", "Search"])
    assert any(k in creator_window.lbl_hole_scan_res.text().lower() for k in ["abgebrochen", "cancelled"])

def test_search_mode_change_cancels_running_search(creator_window, qapp, monkeypatch):
    """Test that changing search mode dropdown while search is running immediately stops it."""
    ensure_holes_tab_active(creator_window, qapp)

    def slow_task(*args, **kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(50):
            if cancel_check and cancel_check():
                break
            time.sleep(0.05)
        return []

    monkeypatch.setattr("opening_fenix.core.threads.run_hole_finder_task", slow_task)

    # Set mode to holes (index 0)
    creator_window.combo_hole_mode.setCurrentIndex(0)
    qapp.processEvents()

    # Start search
    creator_window.run_hole_scan()
    qapp.processEvents()
    assert creator_window.hole_thread is not None
    assert creator_window.hole_thread.isRunning()

    # Change mode to unanswered (index 1)
    creator_window.combo_hole_mode.setCurrentIndex(1)
    qapp.processEvents()
    time.sleep(0.1)
    qapp.processEvents()

    # Active thread must be cancelled and reset
    assert creator_window.hole_thread is None
    assert any(k in creator_window.btn_hole_scan.text() for k in ["Suchen", "Search"])
    assert creator_window.lbl_hole_scan_res.text() == ""
    # Unanswered mode has 2 columns
    assert creator_window.table_holes.columnCount() == 2
    assert creator_window.table_holes.rowCount() == 0

def test_delayed_signals_from_old_mode_ignored(creator_window, qapp):
    """Test that incoming item_found or scan_finished signals for a previous mode are ignored."""
    ensure_holes_tab_active(creator_window, qapp)

    # Mode is unanswered (index 1)
    creator_window.combo_hole_mode.setCurrentIndex(1)
    qapp.processEvents()
    assert creator_window.table_holes.columnCount() == 2
    assert creator_window.table_holes.rowCount() == 0

    # Simulate an item arriving from an old 'holes' search
    old_item = {
        'fen': 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -',
        'move_san': 'e4',
        'move_uci': 'e2e4',
        'popularity': 45.0,
    }
    creator_window._on_hole_item_found(old_item, mode="holes")
    qapp.processEvents()
    # It must be ignored
    assert creator_window.table_holes.rowCount() == 0

    # Simulate finished signal from 'holes'
    creator_window._on_hole_scan_finished([old_item], mode="holes")
    qapp.processEvents()
    # Must still be ignored
    assert creator_window.table_holes.rowCount() == 0

def test_tab_switch_does_not_clear_search_results(creator_window, qapp):
    """Test that switching tabs away and returning to search tab does not clear existing results."""
    ensure_holes_tab_active(creator_window, qapp)

    creator_window.combo_hole_mode.setCurrentIndex(0)
    qapp.processEvents()

    # Add dummy row
    item = {
        'fen': 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -',
        'move_san': 'e4',
        'move_uci': 'e2e4',
        'popularity': 45.0,
    }
    creator_window._add_hole_row(item, mode="holes")
    assert creator_window.table_holes.rowCount() == 1

    # Switch away to Analysis tab
    idx_analysis = creator_window.tabs.indexOf(creator_window.tab_analysis)
    if idx_analysis != -1:
        creator_window.tabs.setCurrentIndex(idx_analysis)
        qapp.processEvents()

    # Switch back to Holes tab
    idx_holes = creator_window.tabs.indexOf(creator_window.tab_holes)
    creator_window.tabs.setCurrentIndex(idx_holes)
    qapp.processEvents()

    # Result row must still be intact!
    assert creator_window.table_holes.rowCount() == 1

def test_changing_level_or_threshold_cancels_running_search(creator_window, qapp, monkeypatch):
    """Test that changing level or threshold while searching stops the active thread."""
    ensure_holes_tab_active(creator_window, qapp)

    def slow_task(*args, **kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(50):
            if cancel_check and cancel_check():
                break
            time.sleep(0.05)
        return []

    monkeypatch.setattr("opening_fenix.core.threads.run_hole_finder_task", slow_task)

    creator_window.combo_hole_mode.setCurrentIndex(0)
    qapp.processEvents()

    creator_window.run_hole_scan()
    qapp.processEvents()
    assert creator_window.hole_thread is not None
    assert creator_window.hole_thread.isRunning()

    # Change threshold
    creator_window._on_hole_level_or_threshold_changed()
    qapp.processEvents()
    time.sleep(0.1)
    qapp.processEvents()

    assert creator_window.hole_thread is None
    assert any(k in creator_window.btn_hole_scan.text() for k in ["Suchen", "Search"])
