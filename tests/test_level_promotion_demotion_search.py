import pytest
from PyQt6.QtWidgets import QPushButton, QLabel
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, Metadata
from opening_fenix.creator.creator_window import CreatorBackend, CreatorWindow

@pytest.fixture
def multi_level_repo(mock_user_dir):
    """Sets up a repertoire with 3 levels and sample moves."""
    repo_name = "TestMultiLevelRepo"
    from opening_fenix.core.utils import get_repertoire_db_path
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base
    
    db_path = get_repertoire_db_path(repo_name, is_test=True)
    db = DatabaseManager(db_path, base=Base)
    session = db.get_session()
    
    session.add(Metadata(key="color", value="w"))
    session.add(RepertoireLevel(name="Basics", order=1))
    session.add(RepertoireLevel(name="Club", order=2))
    session.add(RepertoireLevel(name="Extended", order=3))
    
    def norm(f): return " ".join(f.split()[:4])
    
    # 1. e4 (User)
    p_start = Position(fen=norm("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"))
    p_e4 = Position(fen=norm("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"))
    
    # 1... e5 (Opponent, high popularity, initially placed in Level 2 -> candidate for promotion)
    p_e5 = Position(fen=norm("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"))
    # 2. Nf3 (User reply to e5)
    p_nf3 = Position(fen=norm("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"))
    
    # 1... c5 (Opponent, low popularity, initially placed in Level 1 -> candidate for demotion)
    p_c5 = Position(fen=norm("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"))
    # 2. Nf3 (User reply to c5)
    p_nf3_c5 = Position(fen=norm("rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"))
    
    session.add_all([p_start, p_e4, p_e5, p_nf3, p_c5, p_nf3_c5])
    session.flush()
    
    m_e4 = Move(from_position_id=p_start.id, to_position_id=p_e4.id, uci="e2e4", san="e4", priority_score=1.0)
    m_e5 = Move(from_position_id=p_e4.id, to_position_id=p_e5.id, uci="e7e5", san="e5", priority_score=0.8)
    m_nf3_e5 = Move(from_position_id=p_e5.id, to_position_id=p_nf3.id, uci="g1f3", san="Nf3", priority_score=0.8)
    
    m_c5 = Move(from_position_id=p_e4.id, to_position_id=p_c5.id, uci="c7c5", san="c5", priority_score=0.0005)
    m_nf3_c5 = Move(from_position_id=p_c5.id, to_position_id=p_nf3_c5.id, uci="g1f3", san="Nf3", priority_score=0.0005)
    
    session.add_all([m_e4, m_e5, m_nf3_e5, m_c5, m_nf3_c5])
    session.flush()
    
    # e4 in Level 1
    session.add(RepertoireMove(move_id=m_e4.id, level=1, is_active=True))
    # e5 and reply in Level 2 (candidate to promote to Level 1)
    session.add(RepertoireMove(move_id=m_e5.id, level=2, is_active=True))
    session.add(RepertoireMove(move_id=m_nf3_e5.id, level=2, is_active=True))
    # c5 and reply in Level 1 (candidate to demote to Level 2)
    session.add(RepertoireMove(move_id=m_c5.id, level=1, is_active=True))
    session.add(RepertoireMove(move_id=m_nf3_c5.id, level=1, is_active=True))
    
    session.commit()
    session.close()
    db.close()
    return repo_name

def test_promotion_impact_and_apply(mock_user_dir, multi_level_repo):
    """Verifies that get_priority_level_change_impact and apply_priority_level_change promote correctly."""
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire(multi_level_repo)
    
    # In Level 2, e5 is priority 0.8 (80%), threshold 1.0% -> qualifies for promotion to Level 1
    impact = backend.get_priority_level_change_impact("priority", 2, 1.0)
    assert impact['target_level'] == 1
    assert impact['qualifying_moves'] == 1
    assert impact['positions_changed'] >= 2  # p_e5 and p_nf3
    assert impact['moves_changed'] >= 2      # m_e5 and m_nf3_e5
    
    # First level (Level 1) cannot be promoted
    impact_l1 = backend.get_priority_level_change_impact("priority", 1, 1.0)
    assert impact_l1['target_level'] is None
    assert impact_l1['qualifying_moves'] == 0
    assert impact_l1['positions_changed'] == 0
    
    # Apply promotion
    res = backend.apply_priority_level_change("priority", 2, 1.0)
    assert res['target_level'] == 1
    assert res['positions_changed'] >= 2
    
    # After promotion, re-checking Level 2 should return 0 positions
    impact_after = backend.get_priority_level_change_impact("priority", 2, 1.0)
    assert impact_after['qualifying_moves'] == 0
    assert impact_after['positions_changed'] == 0
    
    backend.close()

def test_demotion_impact_and_apply(mock_user_dir, multi_level_repo):
    """Verifies that get_priority_level_change_impact and apply_priority_level_change demote correctly."""
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire(multi_level_repo)
    
    # In Level 1, c5 is priority 0.0005 (0.05%), threshold 0.1% -> qualifies for demotion to Level 2
    impact = backend.get_priority_level_change_impact("level_down", 1, 0.1)
    assert impact['target_level'] == 2
    assert impact['qualifying_moves'] == 1
    assert impact['positions_changed'] >= 2  # p_c5 and p_nf3_c5
    assert impact['moves_changed'] >= 2      # m_c5 and m_nf3_c5
    
    # Last level (Level 3) cannot be demoted
    impact_l3 = backend.get_priority_level_change_impact("level_down", 3, 0.1)
    assert impact_l3['target_level'] is None
    assert impact_l3['qualifying_moves'] == 0
    assert impact_l3['positions_changed'] == 0
    
    # Apply demotion
    res = backend.apply_priority_level_change("level_down", 1, 0.1)
    assert res['target_level'] == 2
    assert res['positions_changed'] >= 2
    
    # After demotion, re-checking Level 1 should return 0 positions for c5
    impact_after = backend.get_priority_level_change_impact("level_down", 1, 0.1)
    assert impact_after['qualifying_moves'] == 0
    assert impact_after['positions_changed'] == 0
    
    backend.close()

def test_single_move_impact_and_apply(mock_user_dir, multi_level_repo):
    """Verifies get_single_move_level_change_impact and apply_single_move_level_change."""
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire(multi_level_repo)
    
    # Find move e5
    m_e5 = backend.session.query(Move).filter_by(san="e5").first()
    assert m_e5 is not None
    
    # Simulate single move promotion to Level 1
    impact = backend.get_single_move_level_change_impact(m_e5.id, target_level=1)
    assert impact['positions_changed'] >= 2
    assert impact['moves_changed'] >= 2
    assert impact['target_level'] == 1
    
    # Apply single move promotion
    res = backend.apply_single_move_level_change(m_e5.id, target_level=1)
    assert res['success'] is True
    assert res['positions_changed'] >= 2
    
    # Verify in DB that RepertoireMove for e5 is now Level 1
    rm_e5 = backend.session.query(RepertoireMove).filter_by(move_id=m_e5.id).first()
    assert rm_e5.level == 1
    
    backend.close()

def test_combo_level_filtering_in_ui(qapp, mock_user_dir, multi_level_repo):
    """Verifies that redundant levels are excluded in promotion and demotion search modes and table headers match."""
    win = CreatorWindow(multi_level_repo, is_test=True)
    win.show()
    
    # 1. Mode: "priority" (Promotion) -> Level 1 (first level) must NOT be selectable
    idx_prio = win.combo_hole_mode.findData("priority")
    assert idx_prio != -1
    win.combo_hole_mode.setCurrentIndex(idx_prio)
    
    levels_in_prio = [win.combo_hole_level.itemData(i) for i in range(win.combo_hole_level.count())]
    assert 1 not in levels_in_prio, "Level 1 must not be selectable for promotion!"
    assert 2 in levels_in_prio
    assert 3 in levels_in_prio
    
    # Mode priority has 4 columns: Pop, Status, Move, Level ändern
    assert win.table_holes.columnCount() == 4
    
    # 2. Mode: "level_down" (Demotion) -> Level 3 (last level) must NOT be selectable
    idx_down = win.combo_hole_mode.findData("level_down")
    assert idx_down != -1
    win.combo_hole_mode.setCurrentIndex(idx_down)
    
    levels_in_down = [win.combo_hole_level.itemData(i) for i in range(win.combo_hole_level.count())]
    assert 3 not in levels_in_down, "Last Level (Level 3) must not be selectable for demotion!"
    assert 1 in levels_in_down
    assert 2 in levels_in_down
    # Verify threshold label in demotion mode
    assert "Max." in win.lbl_hole_threshold.text()
    
    # 3. Mode: "unanswered" -> 2 columns; Level dropdown hidden
    idx_unans = win.combo_hole_mode.findData("unanswered")
    win.combo_hole_mode.setCurrentIndex(idx_unans)
    assert win.table_holes.columnCount() == 2
    assert not win.combo_hole_level.isVisible()
    
    # Verify threshold label in promotion mode
    win.combo_hole_mode.setCurrentIndex(idx_prio)
    assert "Min." in win.lbl_hole_threshold.text()
    
    win.close()

def test_row_action_button_and_apply_ui(qapp, mock_user_dir, multi_level_repo):
    """Verifies per-row promote button and position change info in the search table."""
    win = CreatorWindow(multi_level_repo, is_test=True)
    win.show()
    
    # Switch to promotion mode
    idx_prio = win.combo_hole_mode.findData("priority")
    win.combo_hole_mode.setCurrentIndex(idx_prio)
    
    # Select Level 2
    for i in range(win.combo_hole_level.count()):
        if win.combo_hole_level.itemData(i) == 2:
            win.combo_hole_level.setCurrentIndex(i)
            break
            
    # Find e5 move id
    m_e5 = win.backend.session.query(Move).filter_by(san="e5").first()
    assert m_e5 is not None
    
    fake_hole = {
        "fen": m_e5.from_position.fen,
        "move_san": "e5",
        "move_uci": "e7e5",
        "move_id": m_e5.id,
        "current_level": 2,
        "type": "priority_check",
        "popularity": 80.0,
    }
    
    # Feed into scan finished
    win._on_hole_scan_finished([fake_hole], mode="priority")
    
    assert win.table_holes.rowCount() == 1
    assert win.table_holes.columnCount() == 4
    
    # Check Col 3 cell widget
    cell_widget = win.table_holes.cellWidget(0, 3)
    assert cell_widget is not None
    
    btn = cell_widget.findChild(QPushButton)
    lbl = cell_widget.findChild(QLabel)
    assert btn is not None
    assert lbl is not None
    
    # Target level is 1
    assert "L1" in btn.text()
    assert "Stellung" in lbl.text() or "position" in lbl.text()
    assert btn.isEnabled()
    
    # Click promote button for this row
    btn.click()
    
    # After click, row should be removed from table_holes
    assert win.table_holes.rowCount() == 0
    
    # Move e5 should now be Level 1 in DB
    rm = win.backend.session.query(RepertoireMove).filter_by(move_id=m_e5.id).first()
    assert rm.level == 1
    
    win.close()

def test_demotion_row_action_button_and_apply_ui(qapp, mock_user_dir, multi_level_repo):
    """Verifies per-row demote button and position change info in the search table."""
    win = CreatorWindow(multi_level_repo, is_test=True)
    win.show()
    
    # Switch to demotion mode
    idx_down = win.combo_hole_mode.findData("level_down")
    win.combo_hole_mode.setCurrentIndex(idx_down)
    
    # Select Level 1
    for i in range(win.combo_hole_level.count()):
        if win.combo_hole_level.itemData(i) == 1:
            win.combo_hole_level.setCurrentIndex(i)
            break
            
    # Find c5 move id (currently Level 1, candidate to demote to Level 2)
    m_c5 = win.backend.session.query(Move).filter_by(san="c5").first()
    assert m_c5 is not None
    
    fake_hole = {
        "fen": m_c5.from_position.fen,
        "move_san": "c5",
        "move_uci": "c7c5",
        "move_id": m_c5.id,
        "current_level": 1,
        "type": "priority_check",
        "popularity": 0.05,
    }
    
    # Feed into scan finished
    win._on_hole_scan_finished([fake_hole], mode="level_down")
    
    assert win.table_holes.rowCount() == 1
    assert win.table_holes.columnCount() == 4
    
    # Check Col 3 cell widget
    cell_widget = win.table_holes.cellWidget(0, 3)
    assert cell_widget is not None
    
    btn = cell_widget.findChild(QPushButton)
    lbl = cell_widget.findChild(QLabel)
    assert btn is not None
    assert lbl is not None
    
    # Target level is 2
    assert "L2" in btn.text()
    assert "Stellung" in lbl.text() or "position" in lbl.text()
    assert btn.isEnabled()
    
    # Click demote button for this row
    btn.click()
    
    # After click, row should be removed from table_holes
    assert win.table_holes.rowCount() == 0
    
    # Move c5 should now be Level 2 in DB
    rm = win.backend.session.query(RepertoireMove).filter_by(move_id=m_c5.id).first()
    assert rm.level == 2
    
    win.close()


def test_click_row_does_not_switch_tab_in_promotion_or_demotion(qapp, mock_user_dir, multi_level_repo):
    """Verifies that clicking a move row in promotion or demotion mode stays on the Search tab."""
    win = CreatorWindow(multi_level_repo, is_test=True)
    active_tabs = win.config.get("creator_active_tabs", ["DETAILS", "ANALYSIS"])
    if "HOLES" not in active_tabs:
        active_tabs.append("HOLES")
        win.set_setting("creator_active_tabs", active_tabs)
        win.apply_tab_visibility()
    win.show()
    
    # 1. Test in promotion mode ("priority")
    idx_prio = win.combo_hole_mode.findData("priority")
    win.combo_hole_mode.setCurrentIndex(idx_prio)
    win.tabs.setCurrentWidget(win.tab_holes)
    assert win.tabs.currentWidget() == win.tab_holes
    
    m_e5 = win.backend.session.query(Move).filter_by(san="e5").first()
    fake_hole = {
        "fen": m_e5.from_position.fen,
        "move_san": "e5",
        "move_uci": "e7e5",
        "move_id": m_e5.id,
        "current_level": 2,
        "type": "priority_check",
        "popularity": 80.0,
    }
    win._on_hole_scan_finished([fake_hole], mode="priority")
    assert win.table_holes.rowCount() == 1
    
    # Activate / click row
    item = win.table_holes.item(0, 1)
    win._handle_hole_item_activated(item)
    # Tab MUST remain on search tab (tab_holes)!
    assert win.tabs.currentWidget() == win.tab_holes
    
    # 2. Test in demotion mode ("level_down")
    idx_down = win.combo_hole_mode.findData("level_down")
    win.combo_hole_mode.setCurrentIndex(idx_down)
    win.tabs.setCurrentWidget(win.tab_holes)
    
    m_c5 = win.backend.session.query(Move).filter_by(san="c5").first()
    fake_hole_down = {
        "fen": m_c5.from_position.fen,
        "move_san": "c5",
        "move_uci": "c7c5",
        "move_id": m_c5.id,
        "current_level": 1,
        "type": "priority_check",
        "popularity": 0.05,
    }
    win._on_hole_scan_finished([fake_hole_down], mode="level_down")
    item_down = win.table_holes.item(0, 1)
    win._handle_hole_item_activated(item_down)
    # Tab MUST remain on search tab (tab_holes)!
    assert win.tabs.currentWidget() == win.tab_holes
    
    # 3. Test that regular "holes" mode STILL switches to analysis tab as expected
    fake_hole_normal = {
        "fen": m_e5.from_position.fen,
        "move_san": "e5",
        "move_uci": "e7e5",
        "type": "opponent",
        "popularity": 50.0,
    }
    win.combo_hole_mode.setCurrentIndex(win.combo_hole_mode.findData("holes"))
    win.tabs.setCurrentWidget(win.tab_holes)
    win._on_hole_scan_finished([fake_hole_normal], mode="holes")
    item_normal = win.table_holes.item(0, 1)
    win._handle_hole_item_activated(item_normal)
    assert win.tabs.currentWidget() == win.tab_analysis
    
    win.close()


def test_demotion_finds_zero_prio_and_sorts_descending(mock_user_dir, multi_level_repo):
    """Verifies that level demotion finds moves with 0 or NULL priority and sorts them descending (highest prio to lowest)."""
    from opening_fenix.core.services.hole_finder_service import find_priority_mismatches
    backend = CreatorBackend(is_test=True)
    backend.load_repertoire(multi_level_repo)
    session = backend.session
    
    # Add a move with NULL priority score and a move with 0.0001 priority score in Level 1
    # Both are opponent replies from e4 (black moves)
    p_e4 = session.query(Position).filter(Position.fen.like("%4P3%")).first()
    
    def norm(f): return " ".join(f.split()[:4])
    p_e6 = Position(fen=norm("rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"))
    p_d6 = Position(fen=norm("rnbqkbnr/ppp1pppp/3p4/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"))
    session.add_all([p_e6, p_d6])
    session.flush()
    
    m_null = Move(from_position_id=p_e4.id, to_position_id=p_e6.id, uci="e7e6", san="e6", priority_score=None)
    m_tiny = Move(from_position_id=p_e4.id, to_position_id=p_d6.id, uci="d7d6", san="d6", priority_score=0.0001)
    session.add_all([m_null, m_tiny])
    session.flush()
    
    session.add(RepertoireMove(move_id=m_null.id, level=1, is_active=True))
    session.add(RepertoireMove(move_id=m_tiny.id, level=1, is_active=True))
    session.commit()
    
    # Run find_priority_mismatches for level demotion (find_rare=True) with threshold 0.1% (0.001)
    results = find_priority_mismatches(session, level=1, threshold_pct=0.1, find_rare=True)
    
    # We should have found m_null, m_tiny, and m_c5 (which has priority 0.0005)
    move_sans = [r['move_san'] for r in results]
    assert "e6" in move_sans
    assert "d6" in move_sans
    assert "c5" in move_sans
    
    # Results must be sorted descending by popularity (highest to lowest prio):
    # c5 (0.05%), d6 (0.01%), e6 (0.0%)
    pops = [r['popularity'] for r in results]
    assert pops == sorted(pops, reverse=True), f"Demotion results must be sorted descending by popularity, got {pops}"
    assert pops[0] == 0.05
    assert pops[-1] == 0.0
    
    # Verify that each result has precomputed impact with non-zero position count
    for r in results:
        assert 'impact' in r
        assert r['impact']['positions_changed'] >= 1
        assert r['impact']['moves_changed'] >= 1
        assert r['impact']['target_level'] == 2
        
    backend.close()
