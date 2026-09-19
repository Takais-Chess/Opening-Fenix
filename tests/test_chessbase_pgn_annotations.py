import pytest
import chess
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor
from opening_fenix.core.utils import (
    parse_chessbase_annotations, clean_chessbase_annotations,
    serialize_chessbase_annotations, update_comment_with_annotations,
    CHESSBASE_COLOR_MAP, COLOR_TO_CHESSBASE_CODE
)
from opening_fenix.gui.widgets.board_widget import (
    ChessBoardWidget, USER_ARROW_COLORS, USER_HIGHLIGHT_COLORS
)


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def board_widget(qapp):
    widget = ChessBoardWidget()
    widget.resize(600, 600)
    yield widget
    widget.close()


def test_parse_user_screenshot_csl():
    """Test the exact case from the user's screenshot: [%csl Re5]."""
    comment = "[%csl Re5]"
    parsed = parse_chessbase_annotations(comment)
    assert parsed["clean_text"] == ""
    assert len(parsed["highlights"]) == 1
    sq, color = parsed["highlights"][0]
    assert sq == chess.E5
    assert color == "red"
    assert len(parsed["arrows"]) == 0


def test_parse_multiple_csl_and_cal():
    """Test parsing multiple squares and arrows with different colors."""
    comment = "[%csl Re5,Gd4,Yf3,Bc6] [%cal Ge2e4,Re7e5,Yg1f3,Bb1c3] Strong central control."
    parsed = parse_chessbase_annotations(comment)
    
    assert parsed["clean_text"] == "Strong central control."
    
    # Check highlights
    hl_dict = {sq: col for sq, col in parsed["highlights"]}
    assert hl_dict[chess.E5] == "red"
    assert hl_dict[chess.D4] == "green"
    assert hl_dict[chess.F3] == "yellow"
    assert hl_dict[chess.C6] == "blue"
    
    # Check arrows
    arr_dict = {(f, t): col for f, t, col in parsed["arrows"]}
    assert arr_dict[(chess.E2, chess.E4)] == "green"
    assert arr_dict[(chess.E7, chess.E5)] == "red"
    assert arr_dict[(chess.G1, chess.F3)] == "yellow"
    assert arr_dict[(chess.B1, chess.C3)] == "blue"


def test_clean_chessbase_annotations():
    """Test that [%csl ...] and [%cal ...] tags are cleanly stripped from user text."""
    raw = "[%csl Re5] [%cal Ge2e4]\nImportant position!\n[%csl Gd5] Watch out for d5."
    clean = clean_chessbase_annotations(raw)
    assert "[%csl" not in clean
    assert "[%cal" not in clean
    assert "Important position!\nWatch out for d5." in clean


def test_serialize_annotations():
    """Test serializing highlights and arrows into standard ChessBase PGN format."""
    highlights = {chess.E5: "red", chess.D4: "green"}
    arrows = {(chess.E2, chess.E4): "green", (chess.G1, chess.F3): "yellow"}
    
    tag_str = serialize_chessbase_annotations(arrows, highlights, clean_text="White has an advantage.")
    assert "[%csl Gd4,Re5]" in tag_str
    assert "[%cal Ge2e4,Yg1f3]" in tag_str
    assert "White has an advantage." in tag_str


def test_roundtrip_annotations():
    """Test round-trip fidelity: parse -> serialize -> parse."""
    original = "[%csl Gd4,Re5] [%cal Ge2e4,Yg1f3] Good square for the knight."
    p1 = parse_chessbase_annotations(original)
    serialized = serialize_chessbase_annotations(
        arrows={(f, t): col for f, t, col in p1["arrows"]},
        highlights={sq: col for sq, col in p1["highlights"]},
        clean_text=p1["clean_text"]
    )
    p2 = parse_chessbase_annotations(serialized)
    
    assert p1["highlights"] == p2["highlights"]
    assert p1["arrows"] == p2["arrows"]
    assert p1["clean_text"] == p2["clean_text"]


def test_board_widget_load_user_drawings_from_comment(board_widget):
    """Test that board_widget retroactively loads [%csl ...] and [%cal ...] tags."""
    comment = "[%csl Re5] [%cal Ge2e4] Critical juncture."
    board_widget.load_user_drawings_from_comment(comment)
    
    assert chess.E5 in board_widget.user_highlights
    assert board_widget.user_highlights[chess.E5] == USER_HIGHLIGHT_COLORS["red"]
    
    assert (chess.E2, chess.E4) in board_widget.user_arrows
    assert board_widget.user_arrows[(chess.E2, chess.E4)] == USER_ARROW_COLORS["green"]
    
    # Check serialization from board
    tags = board_widget.get_chessbase_annotation_tags()
    assert "[%csl Re5]" in tags
    assert "[%cal Ge2e4]" in tags


def test_board_widget_drawings_changed_signal(board_widget):
    """Test that board_widget emits drawings_changed when annotations change."""
    signal_fired = []
    board_widget.drawings_changed.connect(lambda: signal_fired.append(True))
    
    board_widget.add_user_arrow(chess.E2, chess.E4, "green")
    assert len(signal_fired) == 1
    
    board_widget.add_user_highlight(chess.E5, "red")
    assert len(signal_fired) == 2
    
    board_widget.remove_user_arrow(chess.E2, chess.E4)
    assert len(signal_fired) == 3
    
    board_widget.clear_user_drawings()
    assert len(signal_fired) == 4


def test_update_comment_with_annotations_multilingual():
    """Test updating multilingual JSON comments with new board drawings."""
    multilingual_json = '{"de": "[%csl Re5] Alter Text", "en": "[%csl Re5] Old text"}'
    new_arrows = {(chess.D2, chess.D4): "green"}
    new_highlights = {chess.D5: "yellow"}
    
    updated = update_comment_with_annotations(multilingual_json, new_arrows, new_highlights)
    assert "[%csl Yd5]" in updated
    assert "[%cal Gd2d4]" in updated
    assert "Alter Text" in updated
    assert "Old text" in updated


def test_trainer_variation_end_drawings_reveal(board_widget):
    """Test that Trainer reveals drawings from concluding position at variation end."""
    from unittest.mock import MagicMock
    from opening_fenix.gui.main_window import MainWindow
    
    # Create mock MainWindow instance
    main_win = MagicMock(spec=MainWindow)
    main_win.board_widget = board_widget
    
    # Bind the actual method to mock instance
    main_win._reveal_variation_end_drawings = MainWindow._reveal_variation_end_drawings.__get__(main_win, MainWindow)
    
    # Mock last move with concluding position comment
    mock_move = MagicMock()
    mock_move.to_position = MagicMock()
    mock_move.to_position.comment = "[%csl Gc4][%cal Ge2e4] End of line conclusion"
    mock_move.comment = None
    
    # Ensure board starts clean
    board_widget.clear_user_drawings()
    assert len(board_widget.user_arrows) == 0
    assert len(board_widget.user_highlights) == 0
    
    # Trigger variation end drawings reveal
    main_win._reveal_variation_end_drawings(mock_move)
    
    assert (chess.E2, chess.E4) in board_widget.user_arrows
    assert chess.C4 in board_widget.user_highlights

