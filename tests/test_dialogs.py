import pytest
import os
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton, QGridLayout, QLabel, QVBoxLayout, QPlainTextEdit
from PyQt6.QtCore import Qt, QTimer
from opening_fenix.gui.dialogs.login_dialog import LoginDialog, RepertoireSelectionDialog, RepertoireButton
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
from opening_fenix.gui.dialogs.faq_dialog import FAQDialog

def test_login_dialog_basic(qapp, mock_user_dir):
    """Test login dialog initialization."""
    dialog = LoginDialog()
    assert dialog.windowTitle() == "Opening Fenix - Login"

def test_export_dialog_init(qtbot, complex_backend):
    """Test Course Export Dialog triggers."""
    dialog = ExportDialog(complex_backend)
    qtbot.addWidget(dialog)
    assert "Exportieren" in dialog.windowTitle()
    
    # Toggle DB format
    dialog.r_db.setChecked(True)
    assert not dialog.g_opt.isVisible()
    
    # Accept
    dialog.on_accept()
    assert dialog.result_data[0] == "db"

def test_faq_dialog_interaction(qtbot):
    """Test FAQ Dialog content and items."""
    dialog = FAQDialog()
    qtbot.addWidget(dialog)
    assert "FAQ" in dialog.windowTitle()
    
    # Check for FAQItem children
    from opening_fenix.gui.dialogs.faq_dialog import FAQItem
    items = dialog.findChildren(FAQItem)
    assert len(items) >= 4
    assert "training" in items[0].findChild(QLabel).text().lower() or "training" in items[1].findChild(QLabel).text().lower()
    all_texts = [label.text().lower() for item in items for label in item.findChildren(QLabel)]
    assert any("lichess" in t for t in all_texts)

def test_faq_dialog_english(qtbot):
    """Test FAQ items in English."""
    from opening_fenix.core.translation import translator
    old_lang = translator.current_lang
    try:
        translator.load_language("en")
        dialog = FAQDialog()
        qtbot.addWidget(dialog)
        from opening_fenix.gui.dialogs.faq_dialog import FAQItem
        items = dialog.findChildren(FAQItem)
        all_texts = [label.text().lower() for item in items for label in item.findChildren(QLabel)]
        assert any("will the lichess import for big courses ever get faster?" in t for t in all_texts)
    finally:
        translator.load_language(old_lang)

def test_repertoire_selection_dialog(qtbot, mock_user_dir):
    """Test the repertoire selection flow for new profiles."""
    from opening_fenix.core.utils import initialize_repertoire_assets, get_repertoire_dir, get_repertoire_db_path
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import Base
    
    repo_name = "NewRepo"
    repo_dir = get_repertoire_dir(repo_name)
    os.makedirs(repo_dir, exist_ok=True)
    initialize_repertoire_assets(repo_dir)
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path, base=Base)
    db.close()
    
    dialog = RepertoireSelectionDialog()
    qtbot.addWidget(dialog)
    
    # Check if buttons are there
    assert len(dialog.repo_buttons) > 0
    dialog.repo_buttons[0].setChecked(True)
    
    de_btn = dialog.findChild(QPushButton, "LangBtn_de")
    if de_btn: de_btn.setChecked(True)
    
    dialog.on_accept()
    assert dialog.selected_repos == [repo_name]

def test_creator_debug_info(creator_window, qtbot, complex_backend):
    """Test the debug position info from creator/new.py."""
    from opening_fenix.creator.new import show_debug_position_info
    try:
        def close_dialogs():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QDialog) and "Debug" in widget.windowTitle():
                    widget.accept()
        QTimer.singleShot(100, close_dialogs)
        show_debug_position_info(creator_window)
    except Exception as e:
        pytest.fail(f"show_debug_position_info failed: {e}")

def test_flash_widget_logic(qtbot, mock_user_dir):
    """Test the flash animation styling logic directly."""
    dialog = RepertoireSelectionDialog()
    qtbot.addWidget(dialog)
    
    # Trigger flash on scroll area
    target = dialog.scroll_area
    dialog.flash_widget(target)
    
    # Style should contain the red border
    assert "border: 4px solid #e74c3c" in target.styleSheet()
    
    # Wait for reset
    qtbot.waitUntil(lambda: "border: 4px solid #e74c3c" not in target.styleSheet(), timeout=1500)
    assert "border: 4px solid #e74c3c" not in target.styleSheet()

def test_repertoire_selection_soft_tint_styling(qtbot, mock_user_dir):
    """Verify soft tinted selection + accent border on repertoire and language buttons, keeping solid CTA."""
    from opening_fenix.gui.styles import COLORS

    dialog = RepertoireSelectionDialog()
    qtbot.addWidget(dialog)

    btn = RepertoireButton("Tarrasch Example Course")
    qtbot.addWidget(btn)

    # Unchecked state uses neutral fill and no checkmark prefix
    assert COLORS["burnt_orange"] not in btn.styleSheet() or "rgba(211, 84, 0, 0.45)" in btn.styleSheet()
    assert f"background-color: {COLORS['burnt_orange']}" not in btn.styleSheet()
    assert not btn.text().startswith("✓")

    # Checked state uses soft warm tint, burnt orange border, and checkmark prefix while preserving repo_name
    btn.setChecked(True)
    checked_ss = btn.styleSheet()
    assert "background-color: #fde8d3" in checked_ss
    assert f"border: 2px solid {COLORS['burnt_orange']}" in checked_ss
    assert f"background-color: {COLORS['burnt_orange']}" not in checked_ss
    assert btn.text().startswith("✓  ")
    assert btn.repo_name == "Tarrasch Example Course"

    # Unchecking restores neutral style and removes prefix
    btn.setChecked(False)
    unchecked_ss = btn.styleSheet()
    assert "background-color: #fde8d3" not in unchecked_ss
    assert "rgba(255, 255, 255, 0.48)" in unchecked_ss
    assert not btn.text().startswith("✓")

    # Language selection buttons use soft tint for :checked, not solid burnt orange fill
    for obj_name in ("LangBtn_en", "LangBtn_de"):
        lang_btn = dialog.findChild(QPushButton, obj_name)
        assert lang_btn is not None
        ss = lang_btn.styleSheet()
        assert "background-color: #fde8d3" in ss
        assert f"border: 2px solid {COLORS['burnt_orange']}" in ss
        assert f"background-color: {COLORS['burnt_orange']}" not in ss

    # Primary CTA retains solid burnt orange
    assert f"background-color: {COLORS['burnt_orange']}" in dialog.btn_ok.styleSheet()


def test_create_empty_repertoire_service(mock_user_dir):
    """Verify create_empty_repertoire initializes assets, 3 default levels, color metadata, and validation."""
    from opening_fenix.core.services.repertoire_core_service import (
        RepertoireService,
        create_empty_repertoire,
        invalidate_all_repertoires_cache,
    )
    from opening_fenix.core.utils import get_repertoire_dir, get_repertoire_db_path
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.db.models import RepertoireLevel
    from opening_fenix.core.db.meta_utils import get_meta

    invalidate_all_repertoires_cache()

    white_name = create_empty_repertoire("My White Course", "w")
    black_name = create_empty_repertoire("My Black Course", "b")
    assert white_name == "My White Course"
    assert black_name == "My Black Course"

    repos = RepertoireService().get_all_repertoires()
    assert "My White Course" in repos
    assert "My Black Course" in repos

    for repo_name, expected_color in [("My White Course", "w"), ("My Black Course", "b")]:
        repo_dir = get_repertoire_dir(repo_name)
        db_path = get_repertoire_db_path(repo_name)
        assert os.path.exists(db_path)
        assert os.path.exists(os.path.join(repo_dir, "Model Games.pgn"))
        assert os.path.exists(os.path.join(repo_dir, "Typical Motives.pgn"))
        assert os.path.exists(os.path.join(repo_dir, "Tactics", "Tactics.pgn"))

        db = DatabaseManager(db_path)
        session = db.get_session()
        try:
            levels = session.query(RepertoireLevel).order_by(RepertoireLevel.order).all()
            assert len(levels) == 3
            assert [lvl.order for lvl in levels] == [1, 2, 3]
            assert get_meta(session, "color") == expected_color
        finally:
            session.close()
            db.close()

    # Duplicate checks (exact and case-insensitive)
    with pytest.raises(FileExistsError):
        create_empty_repertoire("My White Course", "w")
    with pytest.raises(FileExistsError):
        create_empty_repertoire("my white course", "b")

    # Invalid / reserved name checks
    for bad_name in ("", "   ", ".", "..", "test", "bad/name", "bad:name"):
        with pytest.raises(ValueError):
            create_empty_repertoire(bad_name, "w")


def test_repertoire_selection_create_empty_repertoire_flow(qtbot, mock_user_dir, monkeypatch):
    """When 0 repertoires exist, users can create an empty repertoire directly in profile creation."""
    from opening_fenix.core.services.repertoire_core_service import invalidate_all_repertoires_cache

    invalidate_all_repertoires_cache()

    dialog = RepertoireSelectionDialog()
    qtbot.addWidget(dialog)

    assert len(dialog.repo_buttons) == 0
    assert dialog.empty_repos_label is not None
    assert dialog.btn_create_empty_repo is not None

    class StubNewRepertoireDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_data(self):
            return "My First Opening", "b"

    monkeypatch.setattr(
        "opening_fenix.creator.repo_selection_dialog.NewRepertoireDialog",
        StubNewRepertoireDialog,
    )

    created = dialog.create_empty_repertoire_dialog()
    assert created == "My First Opening"
    assert dialog.empty_repos_label is None
    assert len(dialog.repo_buttons) == 1
    assert dialog.repo_buttons[0].repo_name == "My First Opening"
    assert dialog.repo_buttons[0].isChecked() is True

    de_btn = dialog.findChild(QPushButton, "LangBtn_de")
    if de_btn:
        de_btn.setChecked(True)

    dialog.on_accept()
    assert dialog.selected_repos == ["My First Opening"]


