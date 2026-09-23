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
        
    found_idx = creator_window.tabs.indexOf(creator_window.tab_holes)
    if found_idx == -1:
        for i in range(creator_window.tabs.count()):
            if any(k in creator_window.tabs.tabText(i).lower() for k in ["loch", "such", "search", "hole"]):
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
    monkeypatch.setattr(creator_window, "toggle_engine", lambda active: None)
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
            qual_item = creator_window.table_transpositions.item(r, 3)
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


def test_transposition_row_level_buttons(creator_window, qapp):
    """Test that rows in table_transpositions contain level addition buttons."""
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

    # In col 4, there should be the cell widget containing level buttons
    cell_widget = creator_window.table_transpositions.cellWidget(target_row, 4)
    assert cell_widget is not None


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

    # Column 3 (Quality/Ranking) should be HIDDEN in table_transpositions
    assert creator_window.table_transpositions.isColumnHidden(3) is True

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

    # Column 3 (Quality/Ranking) should now be VISIBLE
    assert creator_window.table_transpositions.isColumnHidden(3) is False


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


def test_transposition_triggers_background_enrichment(creator_window, qapp, monkeypatch):
    """Test that inputting a 2-move transposition triggers background enrichment for intermediate and target positions."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    target_fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"

    enriched_fens = []
    monkeypatch.setattr(
        creator_window,
        "trigger_background_enrichment",
        lambda fen: enriched_fens.append(" ".join(fen.split()[:4]))
    )

    data = {
        "type": "bfs",
        "search_fen": start_fen,
        "target_fen": target_fen,
        "path_sans": ["c5", "Nf3"],
        "path_ucis": ["c7c5", "g1f3"],
        "depth": 2,
    }

    # 1. Test via add_transposition_to_level
    creator_window.add_transposition_to_level(data, level_order=1)
    qapp.processEvents()

    # Calculate expected intermediate FEN (after 1... c5)
    b = chess.Board(start_fen)
    b.push_san("c5")
    intermediate_clean = " ".join(b.fen().split()[:4])
    b.push_san("Nf3")
    target_clean = " ".join(b.fen().split()[:4])

    assert intermediate_clean in enriched_fens
    assert target_clean in enriched_fens
    assert len(enriched_fens) == 2


def test_transposition_tab_unified_layout(creator_window, qapp):
    """Test that the transpositions tab uses a single unified container with 5-column table and unified toolbar."""
    # Verify main unified card
    assert hasattr(creator_window, "card_transpos_main")
    assert creator_window.card_transpos_main.objectName() == "TranspositionMainCard"

    # Verify toolbar elements
    assert hasattr(creator_window, "btn_transpos_info")
    assert hasattr(creator_window, "btn_deep_transpos")
    assert hasattr(creator_window, "combo_transpos_depth")
    assert hasattr(creator_window, "btn_global_transpos_scan")

    # Verify unified 5-column table
    assert hasattr(creator_window, "table_transpositions")
    assert creator_window.table_transpositions.columnCount() == 5
    headers = [creator_window.table_transpositions.horizontalHeaderItem(i).text() for i in range(5)]
    assert "Zug" in headers[0]
    assert "Prio" in headers[1]
    assert "Pos-Prio" in headers[2]
    assert "Qualität" in headers[3]
    assert "Level" in headers[4]

    # Verify table_global_transpositions alias for backward compatibility
    assert creator_window.table_global_transpositions is creator_window.table_transpositions


def test_global_transposition_quality_column_hidden_until_2m(creator_window, qapp):
    """Test that Quality column (index 3) is hidden in table when only 1-move items exist, and shown when 2-move items exist."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_1m_only = [
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
        }
    ]

    creator_window._on_global_transpos_scan_finished(mock_1m_only, mode="transpositions")
    qapp.processEvents()

    # 1 separator row + 1 item row = 2 rows
    assert creator_window.table_global_transpositions.rowCount() == 2
    # Quality column (column 3) is hidden when there are only 1-move transpositions
    assert creator_window.table_global_transpositions.isColumnHidden(3) is True

    mock_both = mock_1m_only + [
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

    creator_window.table_global_transpositions.setRowCount(0)
    creator_window._on_global_transpos_scan_finished(mock_both, mode="transpositions")
    qapp.processEvents()

    # 1 separator row + 2 item rows = 3 rows
    assert creator_window.table_global_transpositions.rowCount() == 3
    # Quality column (column 3) is visible when there are 2-move transpositions
    assert creator_window.table_global_transpositions.isColumnHidden(3) is False


def test_global_transposition_activation_and_level_add(creator_window, qapp):
    """Test clicking a global transposition row sets the board and adding to level removes the row."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    target_fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"
    mock_items = [
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

    creator_window._on_global_transpos_scan_finished(mock_items, mode="transpositions")
    qapp.processEvents()
    # 1 separator row + 1 item row = 2 rows
    assert creator_window.table_global_transpositions.rowCount() == 2

    # Activate row 1 (row 0 is separator)
    item1 = creator_window.table_global_transpositions.item(1, 0)
    creator_window.on_global_transposition_activated(item1)
    qapp.processEvents()

    assert creator_window._preset_transposition is not None
    assert creator_window._preset_transposition.get("move_san") == "c5  Nf3"

    # Add to level
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

    # The item should now be removed from global results
    assert len(creator_window._global_transpos_results) == 0


def test_search_mode_combo_does_not_contain_transpositions(creator_window):
    """Verify that 'transpositions' was removed from combo_hole_mode in Search Mode panel."""
    modes = [creator_window.combo_hole_mode.itemData(i) for i in range(creator_window.combo_hole_mode.count())]
    assert "transpositions" not in modes
    assert "holes" in modes
    assert "priority" in modes
    assert "level_down" in modes
    assert "level_check" in modes


def test_clear_search_tab_clears_global_transpositions(creator_window, qapp):
    """Verify that clear_search_tab() clears table_global_transpositions."""
    mock_items = [
        {
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
            "move_san": "c5",
            "depth": 1,
            "type": "transposition_1",
        }
    ]
    creator_window._on_global_transpos_scan_finished(mock_items, mode="transpositions")
    # 1 separator row + 1 item row = 2 rows
    assert creator_window.table_global_transpositions.rowCount() == 2

    creator_window.clear_search_tab()
    assert creator_window.table_global_transpositions.rowCount() == 0


def test_transpos_depth_selector_and_move_number_formatting(creator_window, qapp):
    """Verify depth combo changes config, and move columns display algebraic move numbers."""
    assert hasattr(creator_window, "combo_transpos_depth")
    creator_window.combo_transpos_depth.setCurrentText("20")
    qapp.processEvents()
    assert creator_window.config.get("transposition_depth") == "20"

    # 1. table_holes formatting
    creator_window.table_holes.setRowCount(0)
    mock_hole_white = {
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "move_san": "e4",
        "type": "user",
        "popularity": 85.0,
        "ply_depth": 0,
    }
    creator_window._add_hole_row(mock_hole_white, mode="holes")
    assert creator_window.table_holes.item(0, 2).text() == "1.e4"

    mock_hole_black = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "move_san": "c5",
        "type": "opponent",
        "popularity": 55.0,
        "ply_depth": 1,
    }
    creator_window._add_hole_row(mock_hole_black, mode="holes")
    assert creator_window.table_holes.item(1, 2).text() == "1...c5"

    # 2. table_global_transpositions formatting
    creator_window.table_global_transpositions.setRowCount(0)
    mock_global_2m = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "move_san": "c5  Nf3",
        "path_sans": ["c5", "Nf3"],
        "path_ucis": ["c7c5", "g1f3"],
        "depth": 2,
        "type": "transposition_2",
        "turn": "user",
        "quality": "ausgezeichnet",
        "quality_label": "🟢 Ausgezeichnet",
        "ply_depth": 1,
    }
    creator_window._add_global_transpos_row(mock_global_2m)
    assert creator_window.table_global_transpositions.item(1, 0).text() == "1...c5  2.Nf3"


def test_creator_window_set_repertoire_elo(creator_window, qapp):
    """Verify that set_repertoire_elo updates combo box, display label, and triggers UI refresh."""
    creator_window.set_repertoire_elo("mid")
    qapp.processEvents()
    assert creator_window.combo_lichess_cat.currentText() == "mid"
    lbl_text = creator_window.lbl_lichess_cat_display.text()
    assert "1700" in lbl_text or "Vereins" in lbl_text or "Club" in lbl_text

    # Change to low
    creator_window.set_repertoire_elo("low")
    qapp.processEvents()
    assert creator_window.combo_lichess_cat.currentText() == "low"
    lbl_text_low = creator_window.lbl_lichess_cat_display.text()
    assert "Hobby" in lbl_text_low or "1400" in lbl_text_low


def test_transposition_highlight_cleared_on_position_change(creator_window, qapp):
    """Verify that transposition preview highlights the move, and clears when navigating to a different position."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_item = {
        "fen": start_fen,
        "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -",
        "move_san": "c5",
        "path_sans": ["c5"],
        "path_ucis": ["c7c5"],
        "depth": 1,
        "type": "transposition_1",
    }
    creator_window.table_global_transpositions.setRowCount(0)
    creator_window._on_global_transpos_scan_finished([mock_item], mode="transpositions")
    qapp.processEvents()

    # 1. Activate transposition -> last_move must be set to c7c5 (potential new move)
    # Row 0 is separator, Row 1 is the item
    item1 = creator_window.table_global_transpositions.item(1, 0)
    creator_window.on_global_transposition_activated(item1)
    qapp.processEvents()

    assert creator_window._transposition_highlight_move == chess.Move.from_uci("c7c5")
    assert creator_window.board_widget.last_move == chess.Move.from_uci("c7c5")

    # 2. Navigate to a different position
    other_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    creator_window.set_board_to_fen(other_fen)
    qapp.processEvents()

    # 3. Transposition highlight must be cleared!
    assert creator_window._transposition_highlight_fen is None
    assert creator_window._transposition_highlight_move is None
    assert creator_window.board_widget.last_move != chess.Move.from_uci("c7c5")


def test_transposition_highlight_cleared_on_tab_switch(creator_window, qapp):
    """Verify that switching tabs away from Transpositions clears the preview highlight."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_item = {
        "fen": start_fen,
        "move_san": "c5",
        "path_sans": ["c5"],
        "path_ucis": ["c7c5"],
        "depth": 1,
        "type": "transposition_1",
    }
    creator_window.table_global_transpositions.setRowCount(0)
    creator_window._on_global_transpos_scan_finished([mock_item], mode="transpositions")
    qapp.processEvents()

    # Switch to transpositions tab first
    creator_window.tabs.setCurrentWidget(creator_window.tab_transpositions)
    qapp.processEvents()

    # Activate (Row 0 is separator, Row 1 is the item)
    item1 = creator_window.table_global_transpositions.item(1, 0)
    creator_window.on_global_transposition_activated(item1)
    qapp.processEvents()

    assert creator_window.board_widget.last_move == chess.Move.from_uci("c7c5")

    # Switch away from tab_transpositions to DETAILS tab
    creator_window.tabs.setCurrentWidget(creator_window.tab_details)
    qapp.processEvents()

    assert creator_window._transposition_highlight_move is None
    assert creator_window._transposition_highlight_fen is None
    assert creator_window.board_widget.last_move != chess.Move.from_uci("c7c5")


def test_table_transpositions_click_highlights_move(creator_window, qapp):
    """Verify that clicking a row in table_transpositions sets the transposition preview highlight."""
    creator_window.set_board_to_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    qapp.processEvents()

    items = [
        {
            "move_san": "c5",
            "move_uci": "c7c5",
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        }
    ]
    creator_window._populate_outgoing_table(items)
    qapp.processEvents()

    item0 = creator_window.table_transpositions.item(0, 0)
    creator_window.on_transposition_clicked(item0)
    qapp.processEvents()

    assert creator_window._transposition_highlight_move == chess.Move.from_uci("c7c5")
    assert creator_window.board_widget.last_move == chess.Move.from_uci("c7c5")


def test_transposition_header_responsive_layout(creator_window, qapp):
    """Verify that transpositions tab headers have word wrap enabled and compact layout."""
    assert hasattr(creator_window, "lbl_transpos_status")
    assert creator_window.lbl_transpos_status.wordWrap() is True

    assert hasattr(creator_window, "lbl_global_transpos_status")
    assert creator_window.lbl_global_transpos_status.wordWrap() is True

    # Card bottom should have minimum width 0 to prevent pushing the splitter
    card_bot = creator_window.table_global_transpositions.parentWidget()
    assert card_bot is not None
    assert card_bot.minimumWidth() == 0


def test_board_auto_adjust_preserves_square_on_resize(creator_window, qapp):
    """Verify that resizing to laptop dimensions keeps the board width matched to height."""
    # Resize to simulated laptop window size
    creator_window.resize(1000, 600)
    qapp.processEvents()
    creator_window.trigger_board_adjust()
    qapp.processEvents()

    sizes = creator_window.main_splitter.sizes()
    splitter_h = creator_window.main_splitter.height()
    margins = creator_window.board_container.layout().contentsMargins()
    margin_x = margins.left() + margins.right()
    # Board width (container minus layout margins) should match splitter height
    assert abs((sizes[0] - margin_x) - splitter_h) <= 1
    # Total sizes plus handle width equals total splitter width
    handle_w = creator_window.main_splitter.handleWidth()
    assert abs(sum(sizes) + handle_w - creator_window.main_splitter.width()) <= 1


def test_tab_switch_preserves_board_size(creator_window, qapp):
    """Verify that switching to Transpositionen tab does not shrink the board."""
    creator_window.resize(1000, 600)
    qapp.processEvents()
    creator_window.trigger_board_adjust()
    qapp.processEvents()

    initial_board_w = creator_window.main_splitter.sizes()[0]

    # Find Transpositionen tab index and switch to it
    for i in range(creator_window.tabs.count()):
        if "Transposition" in creator_window.tabs.tabText(i):
            creator_window.tabs.setCurrentIndex(i)
            break
    qapp.processEvents()

    # Board container should not be squeezed by the transpositions tab
    current_board_w = creator_window.main_splitter.sizes()[0]
    assert current_board_w == initial_board_w


def test_splitter_resize_does_not_switch_tab(creator_window, qapp):
    """Verify that resizing the chess board / splitter does not force-switch the tab to DETAILS."""
    # Switch to Transpositions tab
    transpos_idx = -1
    for i in range(creator_window.tabs.count()):
        if "Transposition" in creator_window.tabs.tabText(i):
            transpos_idx = i
            break
    if transpos_idx == -1:
        pytest.skip("Transpositions tab not present")

    creator_window.tabs.setCurrentIndex(transpos_idx)
    qapp.processEvents()
    assert creator_window.tabs.currentIndex() == transpos_idx

    # Simulate splitter movement (user resizing the board)
    creator_window._on_splitter_moved(pos=450, index=1)
    qapp.processEvents()

    # Active tab must remain the Transpositions tab and NOT revert to DETAILS
    assert creator_window.tabs.currentIndex() == transpos_idx


def test_splitter_double_click_resets_auto_size(creator_window, qapp):
    """Verify that double clicking the main splitter handle re-enables board auto-sizing."""
    from PyQt6.QtCore import QPointF, QEvent
    from PyQt6.QtGui import QMouseEvent

    creator_window._auto_size_board = False
    handle = creator_window.main_splitter.handle(1)
    assert handle is not None

    dbl_click_ev = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier
    )
    creator_window.eventFilter(handle, dbl_click_ev)
    qapp.processEvents()

    assert creator_window._auto_size_board is True


def test_global_transposition_streaming_batching(creator_window, qapp):
    """Verify that streamed transposition items are queued and flushed in batches without UI freeze."""
    creator_window._global_transpos_results = []
    creator_window._pending_global_transpos = []
    creator_window.table_transpositions.clearSpans()
    creator_window.table_transpositions.setRowCount(0)

    item1 = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "move_san": "c5",
        "path_sans": ["c5"],
        "path_ucis": ["c7c5"],
        "depth": 1,
        "type": "transposition_1",
        "turn": "opponent",
        "quality": "",
        "quality_label": "—",
        "ply_depth": 1,
    }
    item2 = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "target_fen": "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "move_san": "e6",
        "path_sans": ["e6"],
        "path_ucis": ["e7e6"],
        "depth": 1,
        "type": "transposition_1",
        "turn": "opponent",
        "quality": "",
        "quality_label": "—",
        "ply_depth": 1,
    }

    # Simulate arrival of 2 items
    creator_window._on_global_transpos_item_found(item1, "transpositions")
    creator_window._on_global_transpos_item_found(item2, "transpositions")

    assert len(creator_window._global_transpos_results) == 2
    assert len(creator_window._pending_global_transpos) == 2
    assert "2 gefunden" in creator_window.lbl_global_transpos_status.text()

    # Flush batch manually (simulating timer tick)
    creator_window._flush_pending_global_transpositions()
    qapp.processEvents()

    assert len(creator_window._pending_global_transpos) == 0
    # 1 separator row + 2 items = 3 rows
    assert creator_window.table_transpositions.rowCount() == 3
    sep_item = creator_window.table_transpositions.item(0, 0)
    assert sep_item.data(Qt.ItemDataRole.UserRole) == "__separator__"
    assert "2 Überleitungen gefunden" in sep_item.text()

    # Finish scan
    creator_window._on_global_transpos_scan_finished([item1, item2], "transpositions")
    status_text = creator_window.lbl_global_transpos_status.text()
    assert "2" in status_text and "gefunden" in status_text


def test_backend_min_reachable_level_caching(creator_window):
    """Verify that get_position_min_reachable_level computes once and caches all positions."""
    backend = creator_window.backend
    if not backend or not backend.session:
        pytest.skip("No backend session available")

    # Invalidate cache
    backend.clear_cache()
    assert backend._min_reachable_level_cache is None

    # First call builds cache
    lvl = backend.get_position_min_reachable_level(chess.STARTING_FEN)
    assert lvl == 1
    assert backend._min_reachable_level_cache is not None
    assert isinstance(backend._min_reachable_level_cache, dict)

    # Subsequent call hits cache
    clean_root = " ".join(chess.STARTING_FEN.split()[:4])
    backend._min_reachable_level_cache[clean_root] = 42
    assert backend.get_position_min_reachable_level(chess.STARTING_FEN) == 42

    # clear_cache resets it
    backend.clear_cache()
    assert backend._min_reachable_level_cache is None


def test_suggest_transposition_level_memoization(creator_window):
    """Verify that suggest_transposition_level memoizes results in _transpos_suggestion_cache."""
    creator_window._transpos_suggestion_cache = {}
    data = {
        "search_fen": chess.STARTING_FEN,
        "target_fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "move_uci": "e2e4",
        "move_san": "e4",
        "type": "direct",
    }

    order, reason = creator_window.suggest_transposition_level(data)
    assert order >= 1

    clean_origin = " ".join(chess.STARTING_FEN.split()[:4])
    clean_target = " ".join("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -".split()[:4])
    cache_key = (clean_origin, clean_target, "e2e4")
    assert cache_key in creator_window._transpos_suggestion_cache


def test_incremental_transposition_rendering_and_disabled_1move_engine(creator_window, qapp):
    """Verify that incremental rendering preserves global rows and engine is disabled for 1-move."""
    # 1. Setup global transpositions
    h1 = {
        "fen": chess.STARTING_FEN,
        "target_fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "move_san": "e4",
        "depth": 1,
        "priority_score": 0.5,
        "pos_prio": 0.5,
    }
    h2 = {
        "fen": chess.STARTING_FEN,
        "target_fen": "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -",
        "move_san": "d4",
        "depth": 2,
        "priority_score": 0.3,
        "pos_prio": 0.3,
        "quality": "ausgezeichnet",
    }
    creator_window._global_transpos_results = [h1, h2]
    creator_window._current_outgoing_items = []
    creator_window._current_bfs_items = []
    creator_window._render_transpositions_table(rebuild_global=True)

    # Separator + 2 global rows = 3 rows
    assert creator_window.table_transpositions.rowCount() == 3
    sep_it = creator_window.table_transpositions.item(0, 0)
    assert sep_it.data(Qt.ItemDataRole.UserRole) == "__separator__"
    assert "2" in sep_it.text()

    # 2. Simulate board position move with 1 direct outgoing transposition
    outgoing_direct = [{
        "move_san": "Nf3",
        "move_uci": "g1f3",
        "target_fen": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq -",
        "variation_name": "Reti",
    }]
    creator_window.update_transpositions_tab(outgoing=outgoing_direct)

    # Engine must NOT be running for 1-move transpositions
    assert getattr(creator_window, "_instant_multipv_thread", None) is None

    # Table should now have: 1 direct row + separator + 2 global rows = 4 rows
    assert creator_window.table_transpositions.rowCount() == 4
    row0_it = creator_window.table_transpositions.item(0, 0)
    assert "Nf3" in row0_it.text()
    # Quality for 1-move is neutral '—'
    qual_it = creator_window.table_transpositions.item(0, 3)
    assert qual_it.text() == "—"

    # Separator is now at row 1
    sep_it2 = creator_window.table_transpositions.item(1, 0)
    assert sep_it2.data(Qt.ItemDataRole.UserRole) == "__separator__"
    assert "2" in sep_it2.text()

    # 3. Add one global transposition to level 1
    creator_window.add_transposition_to_level(h1, level_order=1)

    # Global items in list is now 1
    assert len(creator_window._global_transpos_results) == 1
    # Separator text updated to 1
    sep_it3 = None
    for r in range(creator_window.table_transpositions.rowCount()):
        it = creator_window.table_transpositions.item(r, 0)
        if it and it.data(Qt.ItemDataRole.UserRole) == "__separator__":
            sep_it3 = it
            break
    assert sep_it3 is not None
    assert "1" in sep_it3.text()


def test_transposition_styling_and_pct_formatting(creator_window):
    """Verifies that:
    1. _format_transpos_pct never returns raw '0.0%' and correctly handles edge cases.
    2. Table selection uses soft translucent tint without cell border-radius.
    3. Toolbar status label has proper sizing and does not dominate the bar as an input box.
    """
    # 1. Percentage formatting
    fmt = creator_window._format_transpos_pct
    assert fmt(16.0) == "16%"
    assert fmt(3.6) == "3.6%"
    assert fmt(0.05) == "0.05%"
    assert fmt(0.03) == "0.03%"
    assert fmt(0.005) == "<0.01%"
    assert fmt(0.0) == "—"
    assert fmt(-1.0) == "—"
    assert fmt(None) == "—"

    # 2. Table selection stylesheet
    style = creator_window.table_transpositions.styleSheet()
    assert "rgba(211, 84, 0, 0.15)" in style
    assert "border-radius: 0px" in style

    # 3. Status box does not have expanding stretch and has compact styling
    assert hasattr(creator_window, "lbl_transpos_status")
    status_style = creator_window.lbl_transpos_status.styleSheet()
    assert "background: transparent" in status_style or "border-radius" in status_style


def test_creator_back_button_tooltip_style(creator_window, qtbot):
    from PyQt6.QtWidgets import QToolTip, QApplication
    from PyQt6.QtCore import QPoint
    from opening_fenix.gui.styles import scale

    btn = creator_window.btn_back
    assert btn is not None
    assert btn.toolTip() != ""

    # Ensure button has scoped stylesheet so QToolTip does not inherit button font-size or height
    assert "QPushButton#BtnBack" in btn.styleSheet()

    # Trigger tooltip
    pos = btn.mapToGlobal(QPoint(5, 5))
    QToolTip.showText(pos, btn.toolTip(), btn)
    app = QApplication.instance()
    app.processEvents()

    for w in app.topLevelWidgets():
        if "Tip" in w.metaObject().className():
            # Tooltip font size should not be bloated by button's 24px/36px font
            assert w.font().pixelSize() <= scale(16)
            # Tooltip maxHeight should not be constrained by button's max-height: 32px
            assert w.maximumHeight() > scale(32)


def test_hole_item_click_switches_to_analysis_and_highlights_move(creator_window, qapp):
    """Verify that clicking a move in search/hole finder jumps to ANALYSIS tab and highlights candidate move."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    mock_item = {
        "fen": start_fen,
        "move_san": "c5",
        "move_uci": "c7c5",
        "type": "opponent",
        "popularity": 45.0,
    }
    creator_window.table_holes.setRowCount(0)
    creator_window._on_hole_scan_finished([mock_item], mode="holes")
    qapp.processEvents()

    assert creator_window.table_holes.rowCount() == 1

    # Ensure we start in HOLES tab
    idx_holes = creator_window.tabs.indexOf(creator_window.tab_holes)
    if idx_holes != -1:
        creator_window.tabs.setCurrentIndex(idx_holes)
        qapp.processEvents()

    # Click on the unanalyzed popular move
    item = creator_window.table_holes.item(0, 0)
    creator_window.on_hole_click(item)
    qapp.processEvents()

    # Must jump to ANALYSIS tab
    assert creator_window.tabs.currentWidget() == creator_window.tab_analysis

    # Board must be at the position and highlight the candidate move
    assert creator_window.board_widget.board.fen().startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR")
    assert creator_window.board_widget.last_move == chess.Move.from_uci("c7c5")
    assert creator_window._search_highlight_move == chess.Move.from_uci("c7c5")

    # When switching position (e.g. going to start fen), search highlight should be cleared
    creator_window.set_board_to_fen(chess.STARTING_FEN)
    qapp.processEvents()
    assert creator_window._search_highlight_move is None
    assert creator_window.board_widget.last_move != chess.Move.from_uci("c7c5")


def test_transposition_prio_pos_prio_displays_less_than_001_for_zero_games(creator_window, qapp):
    """Verify that transpositions with 0 games or unplayed opponent moves display '<0.01%'."""
    item = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "move_san": "f5  exf6",
        "path_sans": ["f5", "exf6"],
        "path_ucis": ["f7f5", "e4f6"],
        "depth": 2,
        "type": "transposition_2",
        "turn": "user",
        "quality": "ausgezeichnet",
        "quality_label": "🟢 Ausgezeichnet",
        "priority_score": 0.0,
        "pos_prio": 0.0,
    }
    creator_window.table_transpositions.setRowCount(0)
    creator_window._add_single_global_transpos_row(item)
    qapp.processEvents()

    assert creator_window.table_transpositions.rowCount() == 1
    prio_item = creator_window.table_transpositions.item(0, 1)
    pos_prio_item = creator_window.table_transpositions.item(0, 2)
    assert prio_item.text() == "<0.01%"
    assert pos_prio_item.text() == "<0.01%"


def test_preset_transposition_deduplication_and_no_under_separator(creator_window, qapp):
    """Verify clicking an existing global transposition row does not duplicate it under the separator."""
    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    item = {
        "fen": start_fen,
        "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "move_san": "13...f5  14.exf6",
        "path_sans": ["f5", "exf6"],
        "path_ucis": ["f7f5", "e4f6"],
        "depth": 2,
        "type": "transposition_2",
        "turn": "user",
        "quality": "ausgezeichnet",
        "quality_label": "🟢 Ausgezeichnet",
        "priority_score": 0.0,
        "pos_prio": 0.0,
    }
    creator_window._on_global_transpos_scan_finished([item], mode="transpositions")
    qapp.processEvents()

    # 1 separator + 1 item = 2 rows
    assert creator_window.table_transpositions.rowCount() == 2

    # Activate the global row
    it0 = creator_window.table_transpositions.item(1, 0)
    creator_window.on_global_transposition_activated(it0)
    qapp.processEvents()

    # Must NOT have inserted a duplicate 3rd row under the separator!
    assert creator_window.table_transpositions.rowCount() == 2


def test_level_buttons_not_squished_and_column_interactive(creator_window, qapp):
    """Verify Column 4 header is Interactive and buttons have minimum width to prevent squishing."""
    hdr = creator_window.table_transpositions.horizontalHeader()
    from PyQt6.QtWidgets import QHeaderView
    assert hdr.sectionResizeMode(4) == QHeaderView.ResizeMode.Interactive

    item = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "move_san": "c5  Nf3",
        "path_sans": ["c5", "Nf3"],
        "path_ucis": ["c7c5", "g1f3"],
        "depth": 2,
        "type": "transposition_2",
        "priority_score": 0.5,
    }
    cell = creator_window._create_transposition_level_cell(item)
    buttons = cell.findChildren(QPushButton)
    assert len(buttons) >= 1
    for btn in buttons:
        text_adv = btn.fontMetrics().horizontalAdvance(btn.text())
        assert btn.minimumWidth() >= text_adv + 10

    # Column 4 width must be ample (>= 200px)
    creator_window._adjust_transposition_table_columns()
    assert creator_window.table_transpositions.columnWidth(4) >= 200


def test_global_transposition_progress_updates_status(creator_window, qapp):
    """Verify that _on_global_transpos_progress updates lbl_global_transpos_status with percentage."""
    creator_window._global_transpos_results = [{"some": "item"}]
    creator_window._on_global_transpos_progress(current=50, total=100, msg="Pass 2: 50/100")
    text = creator_window.lbl_global_transpos_status.text()
    assert "50%" in text
    assert "50/100" in text
    assert "1 gefunden" in text


def test_suggest_transposition_level_5pct_rule_only_on_level_1(creator_window, qapp):
    """Verify that the 5% frequency penalty ONLY shifts level when considering Level 1 (x_base == 1)."""
    from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel

    session = creator_window.backend.session
    session.query(RepertoireLevel).delete()
    session.add(RepertoireLevel(name="Level 1", order=1, target_elo=1500))
    session.add(RepertoireLevel(name="Level 2", order=2, target_elo=1800))
    session.add(RepertoireLevel(name="Level 3", order=3, target_elo=2000))
    session.commit()

    start_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    t_fen_l1 = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    t_fen_l2 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -"
    t_fen_l3 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq -"

    # Setup positions
    p_l1 = Position(fen=" ".join(t_fen_l1.split()[:4]))
    p_l2 = Position(fen=" ".join(t_fen_l2.split()[:4]))
    p_l3 = Position(fen=" ".join(t_fen_l3.split()[:4]))
    session.add_all([p_l1, p_l2, p_l3])
    session.flush()

    # Outgoing moves for each target
    p_out = Position(fen="rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -")
    session.add(p_out)
    session.flush()

    m1 = Move(from_position_id=p_l1.id, to_position_id=p_out.id, uci="c7c5", san="c5")
    m2 = Move(from_position_id=p_l2.id, to_position_id=p_out.id, uci="e7e5", san="e5")
    m3 = Move(from_position_id=p_l3.id, to_position_id=p_out.id, uci="d7d6", san="d6")
    session.add_all([m1, m2, m3])
    session.flush()

    session.add(RepertoireMove(move_id=m1.id, level=1, is_active=True))
    session.add(RepertoireMove(move_id=m2.id, level=2, is_active=True))
    session.add(RepertoireMove(move_id=m3.id, level=3, is_active=True))
    session.commit()

    # Clear suggestion caches
    creator_window._transpos_suggestion_cache = {}
    creator_window._target_level_cache = {}

    # Case 1: Base is Level 1, low frequency (1% < 5%) -> should shift to Level 2
    data_lvl1_low = {
        "type": "direct",
        "search_fen": start_fen,
        "target_fen": t_fen_l1,
        "move_uci": "c7c5",
        "move_san": "c5",
        "pos_prio": 0.01,
        "depth": 1,
    }
    sugg1, reason1 = creator_window.suggest_transposition_level(data_lvl1_low)
    assert sugg1 == 2
    assert "5%" in reason1

    # Case 2: Base is Level 2, low frequency (1% < 5%) -> should STAY at Level 2 (no bump to Level 3!)
    data_lvl2_low = {
        "type": "direct",
        "search_fen": start_fen,
        "target_fen": t_fen_l2,
        "move_uci": "e7e5",
        "move_san": "e5",
        "pos_prio": 0.01,
        "depth": 1,
    }
    sugg2, reason2 = creator_window.suggest_transposition_level(data_lvl2_low)
    assert sugg2 == 2
    assert "Level 2" in reason2
    assert "5%" not in reason2

    # Case 3: Base is Level 3, low frequency (0.001 < 0.05) -> should STAY at Level 3 (no bump to Level 4!)
    data_lvl3_low = {
        "type": "direct",
        "search_fen": start_fen,
        "target_fen": t_fen_l3,
        "move_uci": "d7d6",
        "move_san": "d6",
        "pos_prio": 0.001,
        "depth": 1,
    }
    sugg3, reason3 = creator_window.suggest_transposition_level(data_lvl3_low)
    assert sugg3 == 3
    assert "Level 3" in reason3
    assert "5%" not in reason3


def test_add_all_1move_transpositions_button_and_batch_add(creator_window, qapp, monkeypatch):
    """Test the 'Add All 1-Move Transpositions' button and batch addition logic."""
    from PyQt6.QtWidgets import QMessageBox
    from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel

    # 1. Verify button exists and is configured
    assert hasattr(creator_window, "btn_add_all_1move")
    assert creator_window.btn_add_all_1move is not None
    assert "1-Zug" in creator_window.btn_add_all_1move.text() or "1-Move" in creator_window.btn_add_all_1move.text()

    # 2. Setup DB with levels and positions
    session = creator_window.backend.session
    session.query(RepertoireLevel).delete()
    session.add(RepertoireLevel(name="Hauptvarianten", order=1, target_elo=1500))
    session.add(RepertoireLevel(name="Nebenvarianten", order=2, target_elo=1800))
    session.commit()

    f_orig = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    p_orig = Position(fen=" ".join(f_orig.split()[:4]))
    session.add(p_orig)
    session.flush()

    # Target 1 (connected in Level 1)
    f_t1 = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    p_t1 = Position(fen=" ".join(f_t1.split()[:4]))
    session.add(p_t1)
    session.flush()

    p_out1 = Position(fen="rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -")
    session.add(p_out1)
    session.flush()
    m_out1 = Move(from_position_id=p_t1.id, to_position_id=p_out1.id, uci="g1f3", san="Nf3")
    session.add(m_out1)
    session.flush()
    session.add(RepertoireMove(move_id=m_out1.id, level=1, is_active=True))

    # Target 2 (connected in Level 2)
    f_t2 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    p_t2 = Position(fen=" ".join(f_t2.split()[:4]))
    session.add(p_t2)
    session.flush()
    m_out2 = Move(from_position_id=p_t2.id, to_position_id=p_out1.id, uci="g1f3", san="Nf3")
    session.add(m_out2)
    session.flush()
    session.add(RepertoireMove(move_id=m_out2.id, level=2, is_active=True))
    session.commit()

    creator_window._transpos_suggestion_cache = {}
    creator_window._target_level_cache = {}

    # Setup _global_transpos_results with two 1-move transpositions and one 2-move transposition
    item_1m_a = {
        "fen": f_orig,
        "target_fen": f_t1,
        "move_san": "c5",
        "move_uci": "c7c5",
        "path_sans": ["c5"],
        "path_ucis": ["c7c5"],
        "depth": 1,
        "type": "transposition_1",
        "pos_prio": 0.25, # >= 5% -> suggested level 1
    }
    item_1m_b = {
        "fen": f_orig,
        "target_fen": f_t2,
        "move_san": "e5",
        "move_uci": "e7e5",
        "path_sans": ["e5"],
        "path_ucis": ["e7e5"],
        "depth": 1,
        "type": "transposition_1",
        "pos_prio": 0.01, # < 5%, but base is 2 -> suggested level 2
    }
    item_2m = {
        "fen": f_orig,
        "target_fen": f_t1,
        "move_san": "c6  Nf3",
        "move_uci": "c7c6",
        "path_sans": ["c6", "Nf3"],
        "path_ucis": ["c7c6", "g1f3"],
        "depth": 2,
        "type": "transposition_2",
    }
    creator_window._global_transpos_results = [item_1m_a, item_1m_b, item_2m]
    creator_window._render_transpositions_table(rebuild_global=True)

    # Mock QMessageBox.question to accept
    question_called = []
    def mock_question(parent, title, text, buttons, default):
        question_called.append((title, text))
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", mock_question)

    # Call add_all_1move_transpositions
    creator_window.add_all_1move_transpositions()

    # Assert confirmation dialog was shown with counts
    assert len(question_called) == 1
    assert "2" in question_called[0][1] # 2 1-move transpositions found

    # Verify both 1-move transpositions were removed from _global_transpos_results, but 2-move remains
    assert len(creator_window._global_transpos_results) == 1
    assert creator_window._global_transpos_results[0]["depth"] == 2

    # Verify DB now has both moves in the repertoire at their suggested levels
    clean_orig = " ".join(f_orig.split()[:4])
    pos_orig_db = session.query(Position).filter_by(fen=clean_orig).first()
    assert pos_orig_db is not None

    rep_moves = session.query(RepertoireMove).join(Move).filter(Move.from_position_id == pos_orig_db.id).all()
    assert len(rep_moves) == 2

    # c7c5 was suggested for Level 1
    move_c5 = session.query(Move).filter_by(from_position_id=pos_orig_db.id, uci="c7c5").first()
    assert move_c5 is not None
    rep_c5 = session.query(RepertoireMove).filter_by(move_id=move_c5.id).first()
    assert rep_c5.level == 1

    # e7e5 was suggested for Level 2
    move_e5 = session.query(Move).filter_by(from_position_id=pos_orig_db.id, uci="e7e5").first()
    assert move_e5 is not None
    rep_e5 = session.query(RepertoireMove).filter_by(move_id=move_e5.id).first()
    assert rep_e5.level == 2

    # Status label was updated
    status_text = creator_window.lbl_transpos_status.text()
    assert "2" in status_text


def test_add_all_1move_transpositions_none_found(creator_window, qapp, monkeypatch):
    """Verify notification when no 1-move transpositions are found."""
    from PyQt6.QtWidgets import QMessageBox

    creator_window._global_transpos_results = []
    
    info_called = []
    def mock_info(parent, title, text):
        info_called.append((title, text))
    monkeypatch.setattr(QMessageBox, "information", mock_info)

    # Fast scan will find 0 transpositions on an empty dummy repo
    creator_window.add_all_1move_transpositions()
    assert len(info_called) == 1 or "Keine" in creator_window.lbl_transpos_status.text() or "No" in creator_window.lbl_transpos_status.text()




