import sys
import pytest
from PyQt6.QtWidgets import QApplication
from opening_fenix.gui.dialogs.login_dialog import LoginDialog, RepertoireSelectionDialog
from opening_fenix.creator.repo_selection_dialog import NewRepertoireDialog


def test_login_dialog_taskbar_close_filter(qtbot):
    dlg = LoginDialog()
    qtbot.addWidget(dlg)

    if sys.platform == "win32":
        assert getattr(dlg, "_taskbar_filter", None) is not None

    dlg.reject()
    assert getattr(dlg, "_taskbar_filter", None) is None


def test_login_dialog_taskbar_close_accept(qtbot):
    dlg = LoginDialog()
    qtbot.addWidget(dlg)

    if sys.platform == "win32":
        assert getattr(dlg, "_taskbar_filter", None) is not None

    dlg.accept()
    assert getattr(dlg, "_taskbar_filter", None) is None


def test_repertoire_selection_dialog_taskbar_close_filter(qtbot):
    dlg = RepertoireSelectionDialog()
    qtbot.addWidget(dlg)

    if sys.platform == "win32":
        assert getattr(dlg, "_taskbar_filter", None) is not None

    dlg.reject()
    assert getattr(dlg, "_taskbar_filter", None) is None


def test_new_repertoire_dialog_taskbar_close_filter(qtbot):
    dlg = NewRepertoireDialog()
    qtbot.addWidget(dlg)

    if sys.platform == "win32":
        assert getattr(dlg, "_taskbar_filter", None) is not None

    dlg.reject()
    assert getattr(dlg, "_taskbar_filter", None) is None
