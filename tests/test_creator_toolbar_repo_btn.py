import os
import pytest
from unittest.mock import patch, MagicMock
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QPushButton

from opening_fenix.creator.creator_window import ActiveRepoButton, CreatorWindow
from opening_fenix.creator.repo_selection_dialog import RepoSelectionDialog

def test_active_repo_button_init_empty(qtbot):
    btn = ActiveRepoButton()
    qtbot.addWidget(btn)
    
    assert btn.lbl_name.text() == "Kein Repertoire"
    assert btn.lbl_cover.text() == "♟"
    assert "Laden" in btn.lbl_load.text()
    assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor

def test_active_repo_button_update_repo(qtbot, tmp_path):
    btn = ActiveRepoButton()
    qtbot.addWidget(btn)
    
    btn.update_repo("Sicilian Dragon")
    assert btn.lbl_name.text() == "Sicilian Dragon"
    assert "Laden" in btn.lbl_load.text()

def test_active_repo_button_with_cover_image(qtbot, tmp_path):
    btn = ActiveRepoButton()
    qtbot.addWidget(btn)

    # Create dummy cover image
    cover_file = str(tmp_path / "cover.png")
    pix = QPixmap(100, 100)
    pix.fill(Qt.GlobalColor.blue)
    pix.save(cover_file)

    with patch("opening_fenix.creator.creator_window.get_repertoire_cover_path", return_value=cover_file):
        btn.update_repo("TestRepoWithCover")
        assert btn.lbl_name.text() == "TestRepoWithCover"
        assert not btn.lbl_cover.pixmap().isNull()

def test_creator_window_toolbar_has_active_repo_button(creator_window):
    assert hasattr(creator_window, "btn_load_repo")
    assert isinstance(creator_window.btn_load_repo, ActiveRepoButton)
    assert creator_window.btn_load_repo.isVisible()
    
    # Check that ActiveRepoButton is in the toolbar
    toolbar_buttons = creator_window.toolbar.findChildren(QPushButton)
    assert creator_window.btn_load_repo in toolbar_buttons

def test_active_repo_button_updates_on_load(creator_window, tmp_path):
    creator_window.load_repertoire("NewActiveRepo")
    assert creator_window.btn_load_repo.lbl_name.text() == "NewActiveRepo"

def test_active_repo_button_dynamic_width(qtbot):
    btn = ActiveRepoButton()
    qtbot.addWidget(btn)
    
    btn.update_repo("1.")
    short_width = btn.minimumWidth()
    
    btn.update_repo("1.d4 Ben Finegold - Aggressives und Solides Repertoire gegen alles")
    long_width = btn.minimumWidth()
    
    assert long_width > short_width + 100
    assert btn.sizeHint().width() >= long_width
