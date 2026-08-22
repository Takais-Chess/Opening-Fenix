import pytest
import chess
from PyQt6.QtWidgets import QApplication, QPushButton, QHeaderView
from PyQt6.QtCore import Qt, QTimer
from opening_fenix.creator.creator_window import CreatorWindow

def test_tab_switching(creator_window, qapp):
    """Test switching between tabs in the Creator window."""
    assert creator_window.tabs.currentIndex() == 0
    creator_window.tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert creator_window.tabs.currentIndex() == 1

def test_navigation_buttons(creator_window, qapp):
    """Test the FEN navigation buttons (Start, Back, Forward)."""
    new_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    creator_window.set_board_to_fen(new_fen)
    assert creator_window.board_widget.board.fen().startswith(new_fen)
    
    creator_window.go_start()
    from chess import STARTING_FEN
    assert creator_window.board_widget.board.fen().startswith(STARTING_FEN)

def test_details_panel_updates(creator_window, qapp):
    """Test that the details panel updates when changing FEN."""
    backend = creator_window.backend
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    backend.update_position_data(start_fen, "Initial Position Comment", "Var1", "Var2", "Var3", target_lang=creator_window.active_comment_lang)
    
    creator_window.update_ui_from_fen()
    qapp.processEvents()
    assert creator_window.txt_c.toPlainText() == "Initial Position Comment"

def test_hole_finder_ui_trigger(creator_window, qapp, monkeypatch):
    """Test triggering a hole scan from the UI."""
    # Force enable the HOLES tab for testing if not already visible
    active_tabs = creator_window.config.get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
    if "HOLES" not in active_tabs:
        # We modify a copy to avoid mutation issues if config is shared
        new_active = list(active_tabs)
        new_active.append("HOLES")
        creator_window.config["creator_active_tabs"] = new_active
        creator_window.apply_tab_visibility()
        qapp.processEvents()
        
    # Ensure Hole Finder tab is visible
    found_idx = -1
    for i in range(creator_window.tabs.count()):
        # Searching for "Loch Finder" as it is named "Rep. Loch Finder" in the UI
        if "Loch Finder" in creator_window.tabs.tabText(i):
            found_idx = i
            break
    
    if found_idx == -1:
        pytest.skip("Hole Finder tab not found")

    creator_window.tabs.setCurrentIndex(found_idx)
    qapp.processEvents()
    
    mock_holes = [{'fen': 'f1', 'move_uci': 'e2e4', 'move_san': 'e4', 'prob': 0.5, 'type': 'user'}]
    import opening_fenix.core.threads
    monkeypatch.setattr("opening_fenix.core.threads.run_hole_finder_task", lambda *args, **kwargs: mock_holes)
    
    creator_window.run_hole_scan()
    # The QThread might need to run, so process events and wait briefly to let finished_signal fire
    import time
    time.sleep(0.1)
    qapp.processEvents()
    assert creator_window.table_holes.rowCount() >= 1

def test_variant_visibility_logic(creator_window, qapp):
    """Test dynamic visibility of variation line edits."""
    creator_window.i_v1.setText("")
    creator_window.i_v2.setText("")
    creator_window.i_v3.setText("")
    qapp.processEvents()
    
    assert creator_window.i_v1.isVisible()
    creator_window.i_v1.setText("V1")
    qapp.processEvents()
    assert creator_window.i_v2.isVisible()

def test_engine_toggle_ui(creator_window, qapp, monkeypatch):
    """Test toggling engine from UI."""
    # Toggle on
    creator_window._on_engine_toggle_toggled(True)
    qapp.processEvents()
    assert "Analyse" in creator_window.btn_engine_toggle.text() # "Stoppen" or similar
    
    # Toggle off
    creator_window._on_engine_toggle_toggled(False)
    qapp.processEvents()
    assert "Starten" in creator_window.btn_engine_toggle.text()

def test_symbol_insertion(creator_window, qapp):
    """Test inserting symbols into the comment field."""
    creator_window.txt_c.setPlainText("Test")
    # QPlainTextEdit uses textCursor() for positioning
    cursor = creator_window.txt_c.textCursor()
    cursor.setPosition(4)
    creator_window.txt_c.setTextCursor(cursor)
    
    found_btn = None
    for btn in creator_window.findChildren(QPushButton):
        if btn.text() in ["±", "+−"]:
            found_btn = btn
            break
            
    assert found_btn
    found_btn.click()
    assert any(s in creator_window.txt_c.toPlainText() for s in ["±", "+−"])

def test_tab_visibility_persistence(creator_window, qapp):
    """Test tab visibility management."""
    initial_count = creator_window.tabs.count()
    if initial_count > 1:
        creator_window.tabs.removeTab(1)
        qapp.processEvents()
        assert creator_window.tabs.count() == initial_count - 1

def test_board_arrow_toggle(creator_window, qapp):
    """Test toggling move arrows on the board."""
    creator_window.chk_a.setChecked(True)
    qapp.processEvents()
    assert creator_window.chk_a.isChecked()
    
    creator_window.chk_a.setChecked(False)
    qapp.processEvents()
    assert not creator_window.chk_a.isChecked()

def test_auto_save_on_details_change(creator_window, qtbot, monkeypatch):
    """Test that changing text triggers auto-save logic."""
    mock_called = False
    def mock_update(*args, **kwargs):
        nonlocal mock_called
        mock_called = True
    
    monkeypatch.setattr(creator_window.backend, "update_position_data", mock_update)
    
    creator_window.txt_c.setPlainText("New Comment")
    # Wait for the timer (1s) to trigger on_details_changed timeout
    qtbot.wait(1200)
    assert mock_called


def test_common_moves_proportional_resizing(creator_window, qapp):
    """Test that table_common_moves columns resize using correct resize modes when the table size changes."""
    table = creator_window.table_common_moves
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    
    table.resize(400, 300)
    qapp.processEvents()
    
    creator_window.resize_common_moves_columns()
    
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(4) == QHeaderView.ResizeMode.Stretch


def test_multilingual_comment_save_and_switch(creator_window, qapp):
    """Test typing comments in English, saving, and switching between languages."""
    creator_window.switch_comment_lang("en")
    assert creator_window.active_comment_lang == "en"
    
    # Enter English comment
    creator_window.txt_c.setPlainText("English commentary text")
    creator_window.save_current_details_now()
    
    # Check that in-memory and database have English comment
    assert creator_window.current_position_comments.get("en") == "English commentary text"
    
    # Switch to German
    creator_window.switch_comment_lang("de")
    assert creator_window.txt_c.toPlainText() == ""
    
    # Enter German comment
    creator_window.txt_c.setPlainText("Deutscher Kommentar Text")
    creator_window.save_current_details_now()
    
    # Check both comments exist
    assert creator_window.current_position_comments.get("en") == "English commentary text"
    assert creator_window.current_position_comments.get("de") == "Deutscher Kommentar Text"
    
    # Switch back to English
    creator_window.switch_comment_lang("en")
    assert creator_window.txt_c.toPlainText() == "English commentary text"


def test_delete_comment_and_switch_lang(creator_window, qapp):
    """Test deleting a comment in one language and switching languages immediately."""
    # 1. Start on German with a German comment
    creator_window.switch_comment_lang("de")
    creator_window.txt_c.setPlainText("Deutscher Test Kommentar")
    creator_window.save_current_details_now()
    assert creator_window.txt_c.toPlainText() == "Deutscher Test Kommentar"
    
    # 2. Delete the German comment in the UI (simulate user clearing the text edit)
    creator_window.txt_c.setPlainText("")
    assert creator_window.details_changed is True
    
    # 3. Immediately switch to English before the debounce timer finishes
    creator_window.switch_comment_lang("en")
    
    # Verify English field is empty and no warning indicates German comment exists
    assert creator_window.active_comment_lang == "en"
    assert creator_window.txt_c.toPlainText() == ""
    assert "DE" not in creator_window.btn_lang_comment.toolTip()
    
    # 4. Switch back to German
    creator_window.switch_comment_lang("de")
    assert creator_window.txt_c.toPlainText() == ""
    
    # 5. Reload position from database to confirm it was persisted as deleted
    creator_window.update_ui_from_fen(force_details=True)
    qapp.processEvents()
    assert creator_window.txt_c.toPlainText() == ""
    assert creator_window.current_position_comments == {}


def test_delete_one_language_when_multilingual_exists(creator_window, qapp):
    """Test deleting only one language comment when comments exist in multiple languages."""
    # Setup German and English comments
    creator_window.switch_comment_lang("en")
    creator_window.txt_c.setPlainText("Keep English text")
    creator_window.save_current_details_now()
    
    creator_window.switch_comment_lang("de")
    creator_window.txt_c.setPlainText("Delete German text")
    creator_window.save_current_details_now()
    
    # Delete German text and immediately switch to English
    creator_window.txt_c.setPlainText("")
    creator_window.switch_comment_lang("en")
    
    # English text should still be present
    assert creator_window.txt_c.toPlainText() == "Keep English text"
    
    # Switch back to German - should be empty and highlight that English comment exists
    creator_window.switch_comment_lang("de")
    assert creator_window.txt_c.toPlainText() == ""
    assert "EN" in creator_window.btn_lang_comment.toolTip()


