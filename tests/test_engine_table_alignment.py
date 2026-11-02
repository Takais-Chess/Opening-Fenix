from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from opening_fenix.creator.creator_window import CreatorWindow
from unittest.mock import MagicMock
import sys


def test_engine_table_alignment_consistency(qapp):
    """
    Regression test: Verifies that all evaluation lines in the engine table
    have consistent left alignment, and that row 0 does not inherit Center alignment
    from prior engine status messages.
    """
    backend = MagicMock()
    backend.active_repo_name = "Test"
    backend.get_repertoire_info.return_value = {"name": "Test", "description": "", "color": "white"}
    backend.get_meta.return_value = "white"
    backend.session = None

    win = CreatorWindow(backend)

    # 1. Verify header alignment: Move column header must be Left-aligned
    h0 = win.table_engine.horizontalHeaderItem(0).textAlignment()
    h1 = win.table_engine.horizontalHeaderItem(1).textAlignment()
    h2 = win.table_engine.horizontalHeaderItem(2).textAlignment()
    assert bool(h0 & int(Qt.AlignmentFlag.AlignHCenter))
    assert bool(h1 & int(Qt.AlignmentFlag.AlignHCenter))
    assert bool(h2 & int(Qt.AlignmentFlag.AlignLeft))

    # 2. Simulate status message ("Engine starting...") which centers text in column 2
    win.update_engine_output(["Engine wird gestartet..."])
    qapp.processEvents()
    status_item = win.table_engine.item(0, 2)
    assert status_item is not None
    assert bool(status_item.textAlignment() & int(Qt.AlignmentFlag.AlignHCenter))

    # 3. Simulate multi-PV engine output lines arriving
    lines = [
        {"score": "+0.29", "depth": 24, "pv": "Nf3 d5 d4 e6 c4 dxc4", "first_uci": "g1f3"},
        {"score": "+0.27", "depth": 24, "pv": "d4 d5 Nf3 e6 c4 dxc4", "first_uci": "d2d4"},
        {"score": "+0.19", "depth": 24, "pv": "e4 e5 Nf3 Nc6 Bc4 Bc5", "first_uci": "e2e4"}
    ]
    win.update_engine_output(lines)
    qapp.processEvents()

    # 4. Verify all rows are consistently left-aligned
    for r in range(3):
        item = win.table_engine.item(r, 2)
        assert item is not None
        align = item.textAlignment()
        assert bool(align & int(Qt.AlignmentFlag.AlignLeft)), f"Row {r} should be left-aligned, got {align}"
