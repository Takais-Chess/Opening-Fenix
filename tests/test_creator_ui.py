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


def test_hole_finder_transposition_click_opens_tab(creator_window, qapp):
    """Test that clicking a transposition in Hole Finder navigates to FEN and opens Transposition Tab."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_transpos = [
        {
            "fen": start_fen,
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
            "move_san": "c5",
            "path_sans": ["c5"],
            "path_ucis": ["c7c5"],
            "depth": 1,
            "type": "transposition_1",
            "turn": "opponent",
            "quality": "",
            "quality_label": "—",
            "popularity": 50,
        },
        {
            "fen": start_fen,
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -",
            "move_san": "c5  Nf3",
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "depth": 2,
            "type": "transposition_2",
            "turn": "user",
            "quality": "ausgezeichnet",
            "quality_label": "🟢 Ausgezeichnet",
            "popularity": 70,
        }
    ]
    creator_window._on_hole_scan_finished(mock_transpos, mode="transpositions")
    qapp.processEvents()

    assert creator_window.table_holes.rowCount() == 2

    # Click row 1 (the 2-move transposition)
    item = creator_window.table_holes.item(1, 0)
    creator_window.on_hole_click(item)
    qapp.processEvents()

    # Board should be at start_fen
    assert creator_window.board_widget.board.fen().startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR")

    # Current tab should be TRANSPOSITIONS tab
    current_tab = creator_window.tabs.currentWidget()
    assert current_tab == creator_window.tab_transpositions

    # Table transpositions should contain the 2-move transposition
    found_2move = False
    for r in range(creator_window.table_transpositions.rowCount()):
        it = creator_window.table_transpositions.item(r, 0)
        if it and "c5" in it.text() and "Nf3" in it.text():
            found_2move = True
            depth_item = creator_window.table_transpositions.item(r, 1)
            assert depth_item.text() == "2"
            qual_item = creator_window.table_transpositions.item(r, 2)
            assert "Ausgezeichnet" in qual_item.text() or "🟢" in qual_item.text()
            break
    assert found_2move is True


def test_transposition_table_double_click_adds_moves(creator_window, qapp):
    """Test that double clicking a 2-move transposition in table_transpositions executes the sequence."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_transpos = [
        {
            "fen": start_fen,
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -",
            "move_san": "c5  Nf3",
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "depth": 2,
            "type": "transposition_2",
            "turn": "user",
            "quality": "ausgezeichnet",
            "quality_label": "🟢 Ausgezeichnet",
            "popularity": 70,
        }
    ]
    creator_window._on_hole_scan_finished(mock_transpos, mode="transpositions")
    item = creator_window.table_holes.item(0, 0)
    creator_window.on_hole_click(item)
    qapp.processEvents()

    # Find the row in table_transpositions containing the 2-move transposition
    target_row = -1
    for r in range(creator_window.table_transpositions.rowCount()):
        it = creator_window.table_transpositions.item(r, 0)
        if it and "c5" in it.text() and "Nf3" in it.text():
            target_row = r
            break
    assert target_row != -1
    t_item = creator_window.table_transpositions.item(target_row, 0)
    assert t_item is not None
    creator_window.on_transposition_double_clicked(t_item)
    qapp.processEvents()

    # Check that board is now at target position after 1... c5 2. Nf3
    assert creator_window.board_widget.board.fen().startswith("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R")


def test_suggest_transposition_level_and_buttons(creator_window, qapp):
    """Test suggested level calculation and level addition buttons for transpositions."""
    from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel, LichessData
    import json

    session = creator_window.backend.session

    # 1. Setup levels: Level 1 (order 1), Level 2 (order 2)
    session.query(RepertoireLevel).delete()
    session.add(RepertoireLevel(name="Hauptvarianten", order=1, target_elo=1500))
    session.add(RepertoireLevel(name="Nebenvarianten", order=2, target_elo=1800))
    session.commit()

    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    target_fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"
    clean_target = " ".join(target_fen.split()[:4])

    # Setup target position with an outgoing move in Level 2
    t_pos = Position(fen=clean_target)
    session.add(t_pos)
    session.flush()

    out_pos = Position(fen="rnbqkbnr/pp1ppppp/8/8/4p3/5N2/PPPP1PPP/RNBQKB1R w KQkq -")
    session.add(out_pos)
    session.flush()

    m_out = Move(from_position_id=t_pos.id, to_position_id=out_pos.id, uci="d7d6", san="d6")
    session.add(m_out)
    session.flush()

    session.add(RepertoireMove(move_id=m_out.id, level=2, is_active=True))
    session.commit()

    data_2move = {
        "type": "bfs",
        "search_fen": start_fen,
        "target_fen": target_fen,
        "path_sans": ["c5", "Nf3"],
        "path_ucis": ["c7c5", "g1f3"],
        "depth": 2,
    }

    # 1. Test target alignment suggestion: target has Level 2 outgoing move -> suggested level is 2
    sugg_lvl, reason = creator_window.suggest_transposition_level(data_2move)
    assert sugg_lvl == 2

    # 2. Test low frequency penalty: opponent move < 5% shifts level by +1 (or caps at max level)
    # Add LichessData where c7c5 has 20 games out of 1000 total games (2% frequency)
    clean_start = " ".join(start_fen.split()[:4])
    ld = LichessData(
        fen=clean_start,
        elo_range="high",
        moves_json=json.dumps({"c7c5": {"total": 20, "white": 10, "draws": 5, "black": 5}, "e7e5": {"total": 980, "white": 490, "draws": 245, "black": 245}})
    )
    session.add(ld)
    session.commit()

    # Now origin has < 5% frequency for c7c5
    # With base level 1 (e.g. if target was level 1), it would shift to 2
    # Let's test with a direct transposition whose target is level 1
    t_pos_lvl1 = Position(fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    session.add(t_pos_lvl1)
    session.flush()
    m_out_l1 = Move(from_position_id=t_pos_lvl1.id, to_position_id=out_pos.id, uci="g1f3", san="Nf3")
    session.add(m_out_l1)
    session.flush()
    session.add(RepertoireMove(move_id=m_out_l1.id, level=1, is_active=True))
    session.commit()

    data_direct_low_freq = {
        "type": "direct",
        "search_fen": start_fen,
        "target_fen": t_pos_lvl1.fen,
        "move_uci": "c7c5",
        "move_san": "c5",
        "depth": 1,
    }
    sugg_lvl_low, reason_low = creator_window.suggest_transposition_level(data_direct_low_freq)
    # Base level is 1, but frequency is 2% (< 5%) -> shifted to min(1 + 1, 2) = 2
    assert sugg_lvl_low == 2
    assert "5%" in reason_low or "< 5%" in reason_low

    # 3. Test cell widget generation and clicking level button
    cell_widget = creator_window._create_transposition_level_cell(data_2move)
    assert cell_widget is not None
    btns = cell_widget.findChildren(QPushButton)
    assert len(btns) == 2  # Level 1 and Level 2 buttons

    # One button should be highlighted as suggested (starts with ⭐)
    suggested_btns = [b for b in btns if "⭐" in b.text()]
    assert len(suggested_btns) == 1
    assert "L2" in suggested_btns[0].text()

    # 4. Click the button to add to Level 2
    suggested_btns[0].click()
    qapp.processEvents()

    # Verify that the moves were added to the repertoire with level=2
    m_c5 = session.query(Move).filter_by(uci="c7c5").first()
    assert m_c5 is not None
    rm_c5 = session.query(RepertoireMove).filter_by(move_id=m_c5.id).first()
    assert rm_c5 is not None
    assert rm_c5.level == 2

    m_nf3 = session.query(Move).filter_by(uci="g1f3", from_position_id=m_c5.to_position_id).first()
    assert m_nf3 is not None
    rm_nf3 = session.query(RepertoireMove).filter_by(move_id=m_nf3.id).first()
    assert rm_nf3 is not None
    assert rm_nf3.level == 2


def test_transposition_bottom_bar_update(creator_window, qapp):
    """Test that selecting a row in table_transpositions updates the bottom action bar."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_transpos = [
        {
            "fen": start_fen,
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -",
            "move_san": "c5  Nf3",
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "depth": 2,
            "type": "transposition_2",
            "turn": "user",
            "quality": "ausgezeichnet",
            "quality_label": "🟢 Ausgezeichnet",
            "popularity": 70,
        }
    ]
    creator_window._on_hole_scan_finished(mock_transpos, mode="transpositions")
    item = creator_window.table_holes.item(0, 0)
    creator_window.on_hole_click(item)
    qapp.processEvents()

    # Find the row in table_transpositions
    target_row = -1
    for r in range(creator_window.table_transpositions.rowCount()):
        it = creator_window.table_transpositions.item(r, 0)
        if it and "c5" in it.text():
            target_row = r
            break
    assert target_row != -1

    creator_window.table_transpositions.selectRow(target_row)
    qapp.processEvents()

    assert creator_window.lbl_transpos_add.isVisible() is True
    bottom_btns = creator_window.h_bottom_levels_layout.count()
    assert bottom_btns >= 1

    # Clear selection
    creator_window.table_transpositions.clearSelection()
    qapp.processEvents()
    assert creator_window.lbl_transpos_add.isVisible() is False


def test_unreachable_level_buttons_filtered(creator_window, qapp):
    """Test that level buttons lower than the position's reachable level are filtered out."""
    from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel
    session = creator_window.backend.session

    # Setup 3 levels: L1, L2, L3
    session.query(RepertoireLevel).delete()
    session.add(RepertoireLevel(name="L1", order=1))
    session.add(RepertoireLevel(name="L2", order=2))
    session.add(RepertoireLevel(name="L3", order=3))
    session.commit()

    # Create root -> P3 via a Level 3 move (1. a3)
    root_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    p3_fen = "rnbqkbnr/pppppppp/8/8/8/P7/1PPPPPPP/RNBQKBNR b KQkq -"
    clean_root = " ".join(root_fen.split()[:4])
    clean_p3 = " ".join(p3_fen.split()[:4])

    r_pos = Position(fen=clean_root)
    p3_pos = Position(fen=clean_p3)
    session.add_all([r_pos, p3_pos])
    session.flush()

    m_a3 = Move(from_position_id=r_pos.id, to_position_id=p3_pos.id, uci="a2a3", san="a3")
    session.add(m_a3)
    session.flush()
    session.add(RepertoireMove(move_id=m_a3.id, level=3, is_active=True))
    session.commit()

    # Minimum reachable level for p3_fen should be 3
    min_lvl = creator_window.backend.get_position_min_reachable_level(p3_fen)
    assert min_lvl == 3

    # For a transposition starting from p3_fen, L1 and L2 buttons must NOT be rendered
    data = {
        "type": "direct",
        "search_fen": p3_fen,
        "target_fen": "rnbqkbnr/pppp1ppp/8/4p3/8/P7/1PPPPPPP/RNBQKBNR w KQkq -",
        "move_uci": "e7e5",
        "move_san": "e5",
        "depth": 1,
    }

    cell = creator_window._create_transposition_level_cell(data)
    btns = cell.findChildren(QPushButton)
    # Only Level 3 button should be present!
    assert len(btns) == 1
    assert "L3" in btns[0].text()


def test_transposition_marker_removed_after_level_added(creator_window, qapp):
    """Test that transposition marker and table_holes entry are removed once a level button is pressed."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    target_fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"

    mock_transpos = [
        {
            "fen": start_fen,
            "target_fen": target_fen,
            "move_san": "c5  Nf3",
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "depth": 2,
            "type": "transposition_2",
            "turn": "user",
            "quality": "ausgezeichnet",
            "quality_label": "🟢 Ausgezeichnet",
            "popularity": 70,
        }
    ]

    creator_window._on_hole_scan_finished(mock_transpos, mode="transpositions")
    assert creator_window.table_holes.rowCount() == 1

    item = creator_window.table_holes.item(0, 0)
    creator_window.on_hole_click(item)
    qapp.processEvents()

    assert creator_window._preset_transposition is not None

    # Click level button / call add_transposition_to_level
    data = {
        "type": "bfs",
        "search_fen": start_fen,
        "target_fen": target_fen,
        "path_sans": ["c5", "Nf3"],
        "path_ucis": ["c7c5", "g1f3"],
        "depth": 2,
    }
    creator_window.add_transposition_to_level(data, level_order=1)
    qapp.processEvents()

    # Preset should be cleared
    assert creator_window._preset_transposition is None
    # Entry in table_holes should be removed
    assert creator_window.table_holes.rowCount() == 0


def test_quality_column_hidden_for_1move_transpositions(creator_window, qapp):
    """Test that Quality column is hidden when only 1-move transpositions exist in search mode and transposition tab."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    target_fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"

    # 1. Search Mode / Hole Finder with ONLY 1-move transpositions
    mock_1move = [
        {
            "fen": start_fen,
            "target_fen": target_fen,
            "move_san": "c5",
            "path_sans": ["c5"],
            "path_ucis": ["c7c5"],
            "depth": 1,
            "type": "transposition_1",
            "turn": "opponent",
            "quality": "",
            "quality_label": "—",
            "popularity": 50,
        }
    ]
    creator_window._on_hole_scan_finished(mock_1move, mode="transpositions")
    qapp.processEvents()

    # Column 0 (Qualität) should be HIDDEN in table_holes
    assert creator_window.table_holes.isColumnHidden(0) is True

    # 2. Search Mode / Hole Finder with 2-move transpositions
    mock_2move = [
        {
            "fen": start_fen,
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -",
            "move_san": "c5  Nf3",
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "depth": 2,
            "type": "transposition_2",
            "turn": "user",
            "quality": "ausgezeichnet",
            "quality_label": "🟢 Ausgezeichnet",
            "popularity": 70,
        }
    ]
    creator_window._on_hole_scan_finished(mock_2move, mode="transpositions")
    qapp.processEvents()

    # Column 0 (Qualität) should be VISIBLE when depth > 1
    assert creator_window.table_holes.isColumnHidden(0) is False

    # 3. Transposition Tab with ONLY 1-move transpositions
    direct_items = [
        {
            "move_san": "e5",
            "move_uci": "e7e5",
            "target_fen": target_fen,
        }
    ]
    creator_window._populate_outgoing_table(direct_items)
    qapp.processEvents()

    # Column 2 (Quality/Ranking) should be HIDDEN in table_transpositions
    assert creator_window.table_transpositions.isColumnHidden(2) is True

    # 4. Transposition Tab with deep BFS transpositions (depth 2+)
    deep_paths = [
        {
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "target_fen": target_fen,
            "depth": 2,
            "quality": "möglich",
            "quality_label": "🟡 Möglich",
        }
    ]
    creator_window._populate_deep_table(deep_paths)
    qapp.processEvents()

    # Column 2 (Quality/Ranking) should now be VISIBLE
    assert creator_window.table_transpositions.isColumnHidden(2) is False


def test_clear_search_tab_on_repertoire_switch(creator_window, qapp):
    """Test that switching repertoires completely clears the Search Tab / Hole Finder state."""
    # 1. Populate table_holes with mock data and set a status label
    mock_holes = [
        {
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
            "move_san": "e5",
            "type": "user",
            "popularity": 45.0,
        },
        {
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
            "move_san": "c5",
            "type": "user",
            "popularity": 35.0,
        }
    ]
    creator_window._on_hole_scan_finished(mock_holes, mode="holes")
    creator_window._preset_transposition = {"test": "preset"}
    qapp.processEvents()

    assert creator_window.table_holes.rowCount() == 2
    assert "Ergebnisse gefunden" in creator_window.lbl_hole_scan_res.text()
    assert creator_window._preset_transposition is not None

    # 2. Switch/load repertoire
    creator_window.load_repertoire(creator_window.backend.active_repo_name, is_test=True)
    qapp.processEvents()

    # 3. Assert search tab is completely cleared
    assert creator_window.table_holes.rowCount() == 0
    assert creator_window.lbl_hole_scan_res.text() == ""
    assert creator_window._preset_transposition is None
    assert creator_window.btn_hole_scan.isEnabled() is True



