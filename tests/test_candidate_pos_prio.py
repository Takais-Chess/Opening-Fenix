import json
import pytest
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from opening_fenix.creator.creator_window import CreatorWindow, SortableTreeWidgetItem

@pytest.fixture
def qapp():
    """Fixture for QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def creator_window(qapp, mock_user_dir, sample_repertoire):
    """Fixture for CreatorWindow."""
    win = CreatorWindow(repertoire_name=sample_repertoire)
    win.show()
    yield win
    win.close()

def test_tree_widget_column_count_and_headers(creator_window):
    """Verify tree_widget has 6 columns with Pos-Prio placed to the right of Prio."""
    tree = creator_window.tree_widget
    assert tree.columnCount() == 6

    header = tree.headerItem()
    headers = [header.text(i) for i in range(6)]
    assert "Prio" in headers[1]
    assert "Pos-Prio" in headers[2]
    assert "Kommentar" in headers[3] or "Comment" in headers[3]
    assert "Level" in headers[4]
    assert "Aktiv" in headers[5] or "Active" in headers[5]

def test_compute_pos_prio_helper():
    """Test the _compute_pos_prio static method."""
    common_moves = [
        {"uci": "e2e4", "san": "e4", "total": 750},
        {"uci": "d2d4", "san": "d4", "total": 250},
    ]
    total_games = 1000

    # Found by UCI (75%)
    share, s_str = CreatorWindow._compute_pos_prio(common_moves, total_games, "e2e4", "e4")
    assert share == 0.75
    assert s_str == "75%"

    # Found by SAN (25%)
    share2, s_str2 = CreatorWindow._compute_pos_prio(common_moves, total_games, "d2d4_other", "d4")
    assert share2 == 0.25
    assert s_str2 == "25%"

    # Not found
    share_none, s_str_none = CreatorWindow._compute_pos_prio(common_moves, total_games, "c2c4", "c4")
    assert share_none is None
    assert s_str_none == "—"

    # Zero total games
    share_zero, s_str_zero = CreatorWindow._compute_pos_prio(common_moves, 0, "e2e4", "e4")
    assert share_zero is None
    assert s_str_zero == "—"

def test_format_transpos_pct_two_significant_digits():
    """Verify _format_transpos_pct formats numbers with 2 significant digits across all ranges."""
    fmt = CreatorWindow._format_transpos_pct
    # >= 10% (0 decimal places)
    assert fmt(100.0) == "100%"
    assert fmt(45.38) == "45%"
    assert fmt(14.13) == "14%"
    assert fmt(10.0) == "10%"
    assert fmt(9.96) == "10%"

    # 1.0% - 9.9% (1 decimal place)
    assert fmt(9.94) == "9.9%"
    assert fmt(3.47) == "3.5%"
    assert fmt(1.04) == "1.0%"
    assert fmt(0.996) == "1.0%"

    # 0.01% - 0.99% (2 decimal places)
    assert fmt(0.453) == "0.45%"
    assert fmt(0.187) == "0.19%"
    assert fmt(0.042) == "0.04%"
    assert fmt(0.0096) == "0.01%"

    # < 0.01%
    assert fmt(0.004) == "<0.01%"

    # <= 0 and None
    assert fmt(0.0) == "—"
    assert fmt(-1.5) == "—"
    assert fmt(None) == "—"

def test_candidate_moves_table_populates_pos_prio(creator_window, monkeypatch):
    """Verify that candidate moves table displays Pos-Prio in column 2 with user data."""
    # Add moves e4 and d4 to repository
    creator_window.backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=1)
    creator_window.backend.add_move(chess.STARTING_FEN, "d2d4", "d4", level_order=1)

    # Mock Lichess common moves
    mock_common = [
        {"uci": "e2e4", "san": "e4", "total": 600, "white_pct": 50, "draw_pct": 20, "black_pct": 30},
        {"uci": "d2d4", "san": "d4", "total": 400, "white_pct": 45, "draw_pct": 25, "black_pct": 30},
    ]
    monkeypatch.setattr(creator_window.backend, "get_lichess_common_moves", lambda fen, cat: mock_common)

    creator_window.refresh_candidate_moves_table()

    tree = creator_window.tree_widget
    assert tree.topLevelItemCount() == 2

    items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    e4_item = next(it for it in items if "e4" in it.text(0))
    d4_item = next(it for it in items if "d4" in it.text(0))

    # e4 has 600/1000 = 60%
    assert e4_item.text(2) == "60%"
    assert pytest.approx(e4_item.data(2, Qt.ItemDataRole.UserRole), 0.001) == 0.60

    # d4 has 400/1000 = 40%
    assert d4_item.text(2) == "40%"
    assert pytest.approx(d4_item.data(2, Qt.ItemDataRole.UserRole), 0.001) == 0.40

def test_sortable_tree_widget_item_sorting(creator_window):
    """Verify that SortableTreeWidgetItem sorts column 1 (Prio) and column 2 (Pos-Prio) numerically."""
    tree = creator_window.tree_widget
    tree.clear()

    it1 = SortableTreeWidgetItem(["1. e4", "50.00%", "20.0%", "comment", "1", ""])
    it1.setData(1, Qt.ItemDataRole.UserRole, 0.50)
    it1.setData(2, Qt.ItemDataRole.UserRole, 0.20)
    tree.addTopLevelItem(it1)

    it2 = SortableTreeWidgetItem(["1. d4", "30.00%", "80.0%", "comment", "1", ""])
    it2.setData(1, Qt.ItemDataRole.UserRole, 0.30)
    it2.setData(2, Qt.ItemDataRole.UserRole, 0.80)
    tree.addTopLevelItem(it2)

    it3 = SortableTreeWidgetItem(["1. c4", "20.00%", "—", "comment", "1", ""])
    it3.setData(1, Qt.ItemDataRole.UserRole, 0.20)
    it3.setData(2, Qt.ItemDataRole.UserRole, None)
    tree.addTopLevelItem(it3)

    # Sort by column 2 (Pos-Prio) Descending: 80% (d4), 20% (e4), — (c4)
    tree.sortItems(2, Qt.SortOrder.DescendingOrder)
    assert "d4" in tree.topLevelItem(0).text(0)
    assert "e4" in tree.topLevelItem(1).text(0)
    assert "c4" in tree.topLevelItem(2).text(0)

    # Sort by column 1 (Prio) Descending: 50% (e4), 30% (d4), 20% (c4)
    tree.sortItems(1, Qt.SortOrder.DescendingOrder)
    assert "e4" in tree.topLevelItem(0).text(0)
    assert "d4" in tree.topLevelItem(1).text(0)
    assert "c4" in tree.topLevelItem(2).text(0)

def test_toggle_active_column_5(creator_window):
    """Verify that clicking column 5 toggles move active status."""
    creator_window.backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=1)
    creator_window.backend.add_move(chess.STARTING_FEN, "d2d4", "d4", level_order=1)
    creator_window.refresh_candidate_moves_table()

    tree = creator_window.tree_widget
    it = tree.topLevelItem(0)
    mid = it.data(0, Qt.ItemDataRole.UserRole + 1)
    assert it.checkState(5) == Qt.CheckState.Checked

    # Click column 5 to toggle active
    creator_window.on_tree_click(it, 5)

    # After refresh, the toggled move should be unchecked
    items_after = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    toggled_item = next(item for item in items_after if item.data(0, Qt.ItemDataRole.UserRole + 1) == mid)
    assert toggled_item.checkState(5) == Qt.CheckState.Unchecked

def test_get_lichess_common_moves_limit(creator_window):
    """Verify get_lichess_common_moves respects limit parameter and defaults to returning all."""
    from opening_fenix.core.db.models import LichessData
    moves_data = {
        f"m{i}": {"white": 10, "draws": 5, "black": 5, "total": 20 - i, "san": f"N{i}"}
        for i in range(15)
    }
    clean_fen = " ".join(chess.STARTING_FEN.split()[:4])
    ld = LichessData(fen=clean_fen, elo_range="high", moves_json=json.dumps(moves_data))
    creator_window.backend.session.add(ld)
    creator_window.backend.session.commit()
    creator_window.backend.clear_cache()

    all_moves = creator_window.backend.get_lichess_common_moves(chess.STARTING_FEN, "high")
    assert len(all_moves) == 15

    top_10 = creator_window.backend.get_lichess_common_moves(chess.STARTING_FEN, "high", limit=10)
    assert len(top_10) == 10

def test_candidate_moves_past_10_pos_prio_and_backprop(creator_window, monkeypatch):
    """
    Verify that:
    1. Candidate moves past 10 present in Lichess show proper Pos-Prio (e.g. moves 11, 12).
    2. Rare candidate moves not in Lichess (moves 13+) use child back-propagation (priority_score / p_reach).
    3. The common moves table (bottom) is limited to 10 rows.
    """
    # Create opponent position (after 1. e4, black to move)
    board = chess.Board()
    board.push_san("e4")
    e4_fen = board.fen()
    creator_window.set_board_to_fen(e4_fen)

    # Mock repertoire color as 'w', so Black's turn is opponent's turn (not is_my_turn)
    monkeypatch.setattr(creator_window.backend, "get_repertoire_color", lambda: "w")

    # Set up 12 common moves in Lichess
    # Total games = 1000
    mock_common = [
        {"uci": f"m{i}", "san": f"mv{i}", "total": 100 - i * 5, "white_pct": 50, "draw_pct": 20, "black_pct": 30}
        for i in range(12)
    ]
    monkeypatch.setattr(creator_window.backend, "get_lichess_common_moves", lambda fen, cat, limit=None: mock_common[:limit] if limit else mock_common)

    # Add 14 candidate moves to the backend:
    # Moves 0..11 are in mock_common
    # Move 12 is a rare move with child back-prop priority (e.g. 1... a6 with 0.15% = 0.00147)
    # Move 13 is a rare move with child back-prop priority (e.g. 1... f6 with 0.03% = 0.00032)
    cand_moves = []
    for i in range(12):
        cand_moves.append({
            "id": i + 1, "uci": f"m{i}", "san": f"mv{i}", "is_repo": True, "level": 1, "is_active": True,
            "comment": "", "priority": mock_common[i]["total"] / 1000.0,
            "nag": 0, "eval": None, "to_pos_id": 100 + i
        })
    # Rare move 12 (mv12: 0.15% priority)
    cand_moves.append({
        "id": 13, "uci": "a7a6", "san": "a6", "is_repo": True, "level": 1, "is_active": True,
        "comment": "", "priority": 0.00147,
        "nag": 0, "eval": None, "to_pos_id": 112
    })
    # Rare move 13 (mv13: 0.03% priority)
    cand_moves.append({
        "id": 14, "uci": "f7f6", "san": "f6", "is_repo": True, "level": 1, "is_active": True,
        "comment": "", "priority": 0.00032,
        "nag": 0, "eval": None, "to_pos_id": 113
    })

    monkeypatch.setattr(creator_window.backend, "get_candidate_moves", lambda fen: cand_moves)

    creator_window.refresh_candidate_moves_table()

    tree = creator_window.tree_widget
    assert tree.topLevelItemCount() == 14

    items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]

    # Check move 10 (11th move, index 10) - was sliced out previously
    mv10_item = next(it for it in items if "mv10" in it.text(0))
    # mock_common total games sum = sum(100 - i*5 for i in range(12)) = 12*100 - 5*(11*12/2) = 1200 - 330 = 870
    # mv10 total = 50. 50 / 870 = 5.747% -> "5.7%"
    assert mv10_item.text(2) != "—"
    assert "%" in mv10_item.text(2)

    # Check move 11 (12th move, index 11) - was sliced out previously
    mv11_item = next(it for it in items if "mv11" in it.text(0))
    assert mv11_item.text(2) != "—"
    assert "%" in mv11_item.text(2)

    # Check rare move 12 (a6) - child back-prop fallback
    a6_item = next(it for it in items if "a6" in it.text(0))
    assert a6_item.text(1) == "0.15%"  # Prio
    assert a6_item.text(2) == "0.15%"  # Pos-Prio!
    assert pytest.approx(a6_item.data(2, Qt.ItemDataRole.UserRole), 0.0001) == 0.00147

    # Check rare move 13 (f6) - child back-prop fallback
    f6_item = next(it for it in items if "f6" in it.text(0))
    assert f6_item.text(1) == "0.03%"  # Prio
    assert f6_item.text(2) == "0.03%"  # Pos-Prio!
    assert pytest.approx(f6_item.data(2, Qt.ItemDataRole.UserRole), 0.00001) == 0.00032

    # Verify bottom common moves table is limited to exactly 10 rows
    assert creator_window.table_common_moves.rowCount() == 10

def test_candidate_moves_deep_line_pos_prio_normalization(creator_window, monkeypatch):
    """
    Verify that in a deep position on the opponent's turn:
    If one move is in Lichess with 1 game and another is a rare candidate move with 0 games,
    and both have equal backend priority (e.g. 50% split),
    both display 50% Pos-Prio (rather than 100% and 50%).
    """
    board = chess.Board()
    board.push_san("e4")  # Black's turn (opponent)
    e4_fen = board.fen()
    creator_window.backend.add_move(chess.STARTING_FEN, "e2e4", "e4", level_order=1)
    creator_window.set_board_to_fen(e4_fen)

    # User is White
    monkeypatch.setattr(creator_window.backend, "get_repertoire_color", lambda: "w")

    # Lichess only has 1 game for Ba6
    mock_common = [
        {"uci": "c8a6", "san": "Ba6", "total": 1, "white_pct": 0, "draw_pct": 0, "black_pct": 100}
    ]
    monkeypatch.setattr(creator_window.backend, "get_lichess_common_moves", lambda fen, cat, limit=None: mock_common)

    # Parent reach probability = 0.0001 (0.01%)
    p_reach = 0.0001
    monkeypatch.setattr(creator_window.backend, "_get_pos_prio", lambda pid: p_reach)

    # Both moves have priority = p_reach * 0.5 = 0.00005 (50% local share each)
    cand_moves = [
        {
            "id": 1, "uci": "c8a6", "san": "Ba6", "is_repo": True, "level": 1, "is_active": True,
            "comment": "", "priority": 0.00005,
            "nag": 0, "eval": None, "to_pos_id": 101
        },
        {
            "id": 2, "uci": "b7c3", "san": "bxc3", "is_repo": True, "level": 1, "is_active": True,
            "comment": "", "priority": 0.00005,
            "nag": 0, "eval": None, "to_pos_id": 102
        }
    ]
    monkeypatch.setattr(creator_window.backend, "get_candidate_moves", lambda fen: cand_moves)

    creator_window.refresh_candidate_moves_table()

    tree = creator_window.tree_widget
    items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    ba6_item = next(it for it in items if "Ba6" in it.text(0))
    bxc3_item = next(it for it in items if "bxc3" in it.text(0))

    # Both must show 50% Pos-Prio (Col 2)
    assert ba6_item.text(2) == "50%"
    assert bxc3_item.text(2) == "50%"
    assert pytest.approx(ba6_item.data(2, Qt.ItemDataRole.UserRole), 0.001) == 0.5
    assert pytest.approx(bxc3_item.data(2, Qt.ItemDataRole.UserRole), 0.001) == 0.5

