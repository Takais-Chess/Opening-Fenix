import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt
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
    btn = RepoSelectionButton("Test")
    qtbot.add_widget(btn)
    assert btn.repo_name == "Test"
    assert btn.height() > 0

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


