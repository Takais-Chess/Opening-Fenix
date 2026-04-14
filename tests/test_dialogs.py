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
    assert len(items) >= 3
    assert "training" in items[0].findChild(QLabel).text().lower() or "training" in items[1].findChild(QLabel).text().lower()

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

def test_flash_widget_logic(qtbot):
    """Test the flash animation styling logic directly."""
    dialog = RepertoireSelectionDialog()
    qtbot.addWidget(dialog)
    
    # Trigger flash on scroll area
    target = dialog.scroll_area
    dialog.flash_widget(target)
    
    # Style should contain the red border
    assert "border: 4px solid #e74c3c" in target.styleSheet()
    
    # Wait for reset
    qtbot.wait(1000)
    assert "border: 4px solid #e74c3c" not in target.styleSheet()
