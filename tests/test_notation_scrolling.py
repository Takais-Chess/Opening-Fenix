import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from opening_fenix.gui.main_window import MainWindow

@pytest.fixture
def main_window(qtbot, mock_user_dir, sample_repertoire):
    """Fixture to create a MainWindow instance for testing notation."""
    profile_name = "TestUser"
    win = MainWindow(profile_name)
    qtbot.add_widget(win)
    win.show()
    return win

def test_notation_auto_scrolling_to_bottom(qtbot, main_window):
    """
    Verify that the notation view automatically scrolls to the bottom after an update.
    """
    # 1. Setup a long history to ensure the content exceeds the view height
    # Each entry has a comment to add vertical bulk.
    history = []
    for i in range(100):
        history.append({
            'san': f'm{i}',
            'fen': 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3',
            'comment': f'Detailed comment for move {i} to increase height.'
        })
    
    # 2. Trigger the notation display update
    # This calls QTimer.singleShot(50, ...) inside.
    main_window.update_notation_display(temp_hist=history, reveal_move=True)
    
    # 3. Wait for the asynchronous layout and the 50ms timer to fire
    # 200ms should be plenty for any system to reflow the HTML.
    qtbot.wait(200)
    
    # 4. Verify scrolling state
    # moveCursor(End) ensures the cursor is at the document end. 
    # In a QTextBrowser, this usually means the scrollbar is at its maximum.
    sb = main_window.txt_notation.verticalScrollBar()
    
    # We allow a small tolerance (e.g. 5 pixels) in case of rounding errors 
    # between display coordinates and scrollbar units, though it should be exact.
    assert sb.value() >= sb.maximum() - 5, (
        f"Notation scrollbar should be at the bottom. "
        f"Value: {sb.value()}, Maximum: {sb.maximum()}"
    )
