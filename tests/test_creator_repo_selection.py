import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton
from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog, RepoSelectionButton

@pytest.fixture
def repo_selection_dialog(qtbot):
    with patch("opening_fenix.creator.repo_selection_dialog.RepertoireService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.get_all_repertoires.return_value = ["Repo1", "Repo2"]
        
        dialog = RepoSelectionDialog()
        qtbot.addWidget(dialog)
        return dialog

def test_repo_selection_button_style(qtbot):
    # 1. Long name
    long_name = "Jonas Ruy Lopez Dark Archangel Masterclass"
    btn_long = RepoSelectionButton(long_name)
    qtbot.add_widget(btn_long)
    assert btn_long.repo_name == long_name
    assert btn_long.height() > 0
    assert btn_long.toolTip() == long_name
    assert btn_long.lbl_title.wordWrap() is True
    assert btn_long.lbl_title.toolTip() == long_name

    # 2. Short name (clean, compact)
    short_name = "Der Noori Grand Prix"
    btn_short = RepoSelectionButton(short_name)
    qtbot.add_widget(btn_short)
    assert btn_short.repo_name == short_name
    assert btn_short.lbl_title.wordWrap() is True

def test_dialog_lists_repos(qtbot, repo_selection_dialog):
    # Verify that buttons were created
    buttons = repo_selection_dialog.findChildren(RepoSelectionButton)
    assert len(buttons) == 2
    names = [b.repo_name for b in buttons]
    assert "Repo1" in names
    assert "Repo2" in names

def test_on_repo_selected(qtbot, repo_selection_dialog):
    # Click one of the buttons
    buttons = repo_selection_dialog.findChildren(RepoSelectionButton)
    repo1_btn = next(b for b in buttons if b.repo_name == "Repo1")
    
    with qtbot.waitSignal(repo_selection_dialog.accepted, timeout=1000):
        qtbot.mouseClick(repo1_btn, Qt.MouseButton.LeftButton)
    
    assert repo_selection_dialog.selected_repo == "Repo1"

def test_dialog_empty_repos(qtbot):
    with patch("opening_fenix.creator.repo_selection_dialog.RepertoireService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.get_all_repertoires.return_value = []
        
        dialog = RepoSelectionDialog()
        qtbot.addWidget(dialog)
        
        from PyQt6.QtWidgets import QLabel
        labels = dialog.findChildren(QLabel)
        assert any("Keine Repertoires gefunden" in l.text() for l in labels)

def test_dialog_cancel(qtbot, repo_selection_dialog):
    with qtbot.waitSignal(repo_selection_dialog.rejected, timeout=1000):
        qtbot.mouseClick(repo_selection_dialog.btn_cancel, Qt.MouseButton.LeftButton)

def test_dialog_has_new_button(qtbot, repo_selection_dialog):
    assert hasattr(repo_selection_dialog, "btn_new")
    assert not repo_selection_dialog.btn_new.isHidden()
    assert "Neu" in repo_selection_dialog.btn_new.text()

def test_dialog_create_new_repertoire(qtbot, repo_selection_dialog):
    from opening_fenix.creator.repo_selection_dialog import NewRepertoireDialog
    with patch.object(NewRepertoireDialog, "exec", return_value=1), \
         patch.object(NewRepertoireDialog, "get_data", return_value=("BrandNewRepo", "b")):
        with qtbot.waitSignal(repo_selection_dialog.accepted, timeout=1000):
            qtbot.mouseClick(repo_selection_dialog.btn_new, Qt.MouseButton.LeftButton)
            
    assert repo_selection_dialog.selected_repo == "BrandNewRepo"
    assert repo_selection_dialog.is_new_repo is True
    assert repo_selection_dialog.new_color == "b"


def test_new_repertoire_dialog_button_styling(qtbot):
    from opening_fenix.creator.repo_selection_dialog import NewRepertoireDialog
    from opening_fenix.gui.styles import scale
    from PyQt6.QtWidgets import QPushButton

    dialog = NewRepertoireDialog()
    qtbot.addWidget(dialog)

    buttons = dialog.findChildren(QPushButton)
    assert len(buttons) >= 2
    for btn in buttons:
        assert "padding: 0" in btn.styleSheet()
        assert btn.height() == scale(40) or btn.maximumHeight() == scale(40)


def test_dialog_no_redundant_close_button(repo_selection_dialog):
    # Ensure the redundant in-dialog '✕' close button was removed since the window frame has a close button
    assert not hasattr(repo_selection_dialog, "btn_close")
    buttons = repo_selection_dialog.findChildren(QPushButton)
    assert all(btn.text() != "✕" for btn in buttons)


def test_repo_selection_taskbar_close_filter(qtbot):
    from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog
    import sys

    dlg = RepoSelectionDialog()
    qtbot.addWidget(dlg)

    if sys.platform == "win32":
        assert getattr(dlg, "_taskbar_filter", None) is not None

    dlg.reject()
    assert getattr(dlg, "_taskbar_filter", None) is None


def test_repo_selection_native_close_does_not_quit_app(qtbot):
    from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog
    import sys
    if sys.platform != "win32":
        return

    import ctypes
    from opening_fenix.gui.native_close_filter import _WindowsMSG, _WM_SYSCOMMAND, _SC_CLOSE

    dlg = RepoSelectionDialog()
    qtbot.addWidget(dlg)

    filter_obj = getattr(dlg, "_taskbar_filter", None)
    assert filter_obj is not None

    msg = _WindowsMSG()
    msg.hwnd = int(dlg.winId())
    msg.message = _WM_SYSCOMMAND
    msg.wParam = _SC_CLOSE

    handled, result = filter_obj.nativeEventFilter("windows_generic_MSG", ctypes.addressof(msg))
    assert handled is False
    assert result == 0
    assert filter_obj._triggered is False
    dlg.reject()


def test_load_repertoire_dialog_cancel_when_no_repo_closes_creator(qtbot, monkeypatch):
    from opening_fenix.creator.creator_window import CreatorWindow
    from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog

    cw = CreatorWindow()
    qtbot.addWidget(cw)
    cw.backend.active_repo_name = None
    cw.active_repo_name = None

    monkeypatch.setattr(RepoSelectionDialog, "exec", lambda self: 0)

    closed_called = []
    monkeypatch.setattr(cw, "close", lambda: closed_called.append(True))

    cw._real_load_repertoire_dialog()
    assert closed_called == [True]


def test_load_repertoire_dialog_cancel_when_repo_active_keeps_creator(qtbot, monkeypatch):
    from opening_fenix.creator.creator_window import CreatorWindow
    from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog

    cw = CreatorWindow()
    qtbot.addWidget(cw)
    cw.backend.active_repo_name = "ActiveTestRepo"
    cw.active_repo_name = "ActiveTestRepo"

    monkeypatch.setattr(RepoSelectionDialog, "exec", lambda self: 0)

    closed_called = []
    monkeypatch.setattr(cw, "close", lambda: closed_called.append(True))

    cw._real_load_repertoire_dialog()
    assert closed_called == []


def test_repo_selection_button_tooltip_not_blacked_out(qtbot, repo_selection_dialog):
    from PyQt6.QtWidgets import QToolTip, QLabel, QApplication
    from PyQt6.QtCore import QPoint

    buttons = repo_selection_dialog.findChildren(RepoSelectionButton)
    assert len(buttons) > 0
    btn = buttons[0]

    repo_selection_dialog.show()
    QToolTip.showText(btn.mapToGlobal(QPoint(10, 10)), btn.toolTip(), btn)
    
    app = QApplication.instance()
    app.processEvents()

    found_tooltip = False
    for w in app.allWidgets():
        if isinstance(w, QLabel) and w.windowType().name == "ToolTip":
            found_tooltip = True
            bg_color = w.palette().window().color().name().lower()
            text_color = w.palette().windowText().color().name().lower()
            assert bg_color != "#000000", f"Tooltip background is blacked out: {bg_color}"
            assert bg_color == "#ffffff"
            assert text_color != "#000000"
            break
    assert found_tooltip, "Tooltip widget was not created"





