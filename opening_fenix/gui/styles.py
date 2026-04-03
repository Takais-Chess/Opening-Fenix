import os
from PyQt6.QtGui import QIcon
from opening_fenix.core.data_tools import get_base_path
from opening_fenix.gui.scaling import scale


from opening_fenix.core.logger import logger

_cached_icon = None

def set_consistent_icon(window):
    """Sets the application icon for a window or app instance from centralized assets."""
    global _cached_icon
    if _cached_icon is not None:
        if not _cached_icon.isNull():
            window.setWindowIcon(_cached_icon)
        return

    icon = QIcon()
    base_path = get_base_path()
    
    # Path to ICO (Standard for Windows)
    ico_path = os.path.join(base_path, "assets", "Logo", "favicon.ico")
    if os.path.exists(ico_path):
        icon.addFile(ico_path)
        logger.debug(f"Loaded ICO icon from {ico_path}")
    else:
        logger.warning(f"ICO icon not found at {ico_path}")
        
    # Path to PNG (Fallback/Secondary for better scaling)
    png_path = os.path.join(base_path, "assets", "Logo", "Logo.png")
    if os.path.exists(png_path):
        icon.addFile(png_path)
        logger.debug(f"Loaded PNG icon from {png_path}")
    else:
        logger.warning(f"PNG icon not found at {png_path}")
    
    if not icon.isNull():
        _cached_icon = icon
        window.setWindowIcon(icon)
    else:
        logger.error("Failed to load any application icon!")

# Centralized Color Palette

COLORS = {
    "burnt_orange": "#d35400",
    "beige": "#fdf6e3",
    "dark_beige": "#efebe9",
    "white": "#ffffff",
    "brown_text": "#3e2723",
    "light_text": "#5d4037",
    "border": "#d7ccc8",
    "button_hover": "#e0e0e0",
    "error_red": "#e74c3c",
    "success_green": "#2ecc71",
    "arrow_blue": "rgba(20, 60, 150, 0.5)", # Deep rich blue with 50% opacity
    "glass_bg": "rgba(255, 255, 255, 0.4)",
    "glass_border": "rgba(255, 255, 255, 0.9)",
}

# Stylesheet for the MainWindow (Training Hub)
def get_main_window_style():
    return f"""
    QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['beige']}, stop:1 #d1bfae); }}
    QWidget {{ font-family: 'Segoe UI', 'Arial'; font-size: {scale(14)}px; color: {COLORS['brown_text']}; }}
    
    #CustomTitleBar {{ 
        background-color: transparent; 
        border: none;
    }}
    
    #TopBar {{ 
        background-color: transparent; 
        border: none; 
    }}
    
    *[class="GlassPill"] {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(15)}px;
        padding: {scale(5)}px {scale(20)}px;
    }}
    *[class="GlassPill"]:hover {{
        background-color: rgba(255, 255, 255, 0.7);
    }}
    
    QPushButton#RepoTab {{ 
        background-color: transparent; 
        border: none; 
        padding: {scale(10)}px {scale(10)}px; 
        font-size: {scale(14)}px; 
        font-weight: bold; 
        color: {COLORS['light_text']}; 
    }}
    QPushButton#RepoTab:hover {{ color: {COLORS['burnt_orange']}; background-color: {COLORS['glass_bg']}; border-radius: {scale(5)}px; }}
    QPushButton#RepoTab:checked {{ 
        color: {COLORS['burnt_orange']}; 
        border-bottom: {scale(3)}px solid {COLORS['burnt_orange']}; 
    }}
    
    #BoardPanel, #SidePanel {{ 
        background-color: {COLORS['glass_bg']}; 
        border-radius: {scale(15)}px; 
        border: 1px solid {COLORS['glass_border']}; 
    }}
    
    QTextBrowser#NotationView {{ 
        background-color: transparent; 
        border: none; 
        font-size: {scale(18)}px; 
        line-height: 1.5; 
    }}
    
    QPushButton#ActionButton {{ 
        background-color: {COLORS['dark_beige']}; 
        border: 1px solid {COLORS['border']}; 
        border-radius: {scale(25)}px; 
        padding: {scale(5)}px {scale(15)}px; 
        font-size: {scale(18)}px; 
        min-height: {scale(40)}px; 
    }}
    QPushButton#ActionButton:hover {{ background-color: {COLORS['button_hover']}; }}
    QPushButton#ActionButton:checked {{ 
        background-color: {COLORS['burnt_orange']}; 
        color: white; 
        border-color: {COLORS['burnt_orange']}; 
    }}
    
    QPushButton#StartButton {{ 
        background-color: {COLORS['burnt_orange']}; 
        color: white; 
        border-radius: {scale(25)}px; 
        font-size: {scale(18)}px; 
        font-weight: bold; 
        padding: {scale(15)}px; 
    }}
    QPushButton#StartButton:hover {{ background-color: #e67e22; }}
    QPushButton#StartButton:disabled {{ background-color: #bdc3c7; }}
    
    QToolTip {{ 
        background-color: {COLORS['white']}; 
        color: {COLORS['brown_text']}; 
        border: 1px solid {COLORS['border']}; 
        padding: {scale(5)}px; 
        border-radius: {scale(4)}px; 
    }}
    """



# Stylesheet for the CreatorWindow
def get_creator_window_style():
    return f"""
    QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['beige']}, stop:1 #d1bfae); }}
    QWidget {{ font-family: 'Segoe UI'; font-size: {scale(14)}px; color: {COLORS['brown_text']}; }}
    
    #CustomTitleBar {{ 
        background-color: transparent; 
        border: none;
    }}
    
    #BoardPanel, #SidePanel {{ 
        background-color: {COLORS['glass_bg']}; 
        border-radius: {scale(15)}px; 
        border: 1px solid {COLORS['glass_border']}; 
    }}

    *[class="GlassPill"] {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(15)}px;
        padding: {scale(4)}px {scale(20)}px;
        min-height: {scale(32)}px;
    }}
    *[class="GlassPill"]:hover {{
        background-color: rgba(255, 255, 255, 0.7);
    }}
    
    QGroupBox {{ 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(12)}px; 
        margin-top: 1.5em; 
        font-weight: bold; 
        font-size: {scale(13)}px;
        background-color: rgba(255, 255, 255, 0.1); 
        padding: {scale(15)}px; 
    }}
    QGroupBox::title {{ 
        subcontrol-origin: margin; 
        left: {scale(10)}px; 
        padding: 0 {scale(5)}px; 
        color: {COLORS['brown_text']};
    }}
    
    QTreeWidget, QTableWidget {{ 
        background-color: transparent; 
        border: none;
        outline: none;
    }}
    QTreeWidget::item, QTableWidget::item {{
        border-bottom: 1px solid rgba(0, 0, 0, 0.05);
        padding: {scale(4)}px;
    }}
    QTreeWidget::item:hover, QTableWidget::item:hover {{
        background-color: rgba(211, 84, 0, 0.2);
    }}
    QTreeWidget::item:selected, QTableWidget::item:selected {{
        background-color: {COLORS['burnt_orange']};
        color: white;
        border-radius: {scale(4)}px;
    }}

    QTabWidget::pane {{
        border: none;
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {COLORS['brown_text']};
        padding: {scale(8)}px {scale(16)}px;
        margin-right: {scale(4)}px;
        border-radius: {scale(12)}px;
        font-weight: bold;
    }}
    QTabBar::tab:selected {{
        background: rgba(255, 255, 255, 0.5);
        color: {COLORS['brown_text']};
        border: 1px solid {COLORS['glass_border']};
    }}
    QTabBar::tab:hover:!selected {{
        background: rgba(255, 255, 255, 0.3);
    }}

    *[class="SymbolButton"] {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(4)}px;
        font-weight: bold;
        font-size: {scale(16)}px;
        padding: 0px;
    }}
    *[class="SymbolButton"]:hover {{
        background-color: rgba(255, 255, 255, 0.7);
    }}

    QHeaderView::section {{
        background-color: transparent;
        color: {COLORS['brown_text']};
        font-weight: bold;
        padding: {scale(5)}px;
        border: none;
        border-bottom: {scale(2)}px solid {COLORS['glass_border']};
    }}
    QTreeWidget::item:selected, QTableWidget::item:selected {{
        background-color: {COLORS['burnt_orange']};
        color: {COLORS['white']};
    }}
    
    QFrame {{ /* Affects self.tree_group and other inner container frames */
        background-color: transparent; 
        border: none;
    }}
    
    QComboBox {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(15)}px;
        padding-left: {scale(10)}px;
        padding-right: {scale(10)}px;
        min-height: {scale(32)}px;
    }}
    *[class="SmallCombo"] {{
        border-radius: {scale(10)}px;
        padding-right: {scale(8)}px;
        padding-left: {scale(8)}px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: {scale(20)}px;
        subcontrol-origin: padding;
        subcontrol-position: top right;
    }}
    QComboBox::down-arrow {{
        /* Remove image: none to allow default arrow */
        width: {scale(12)}px;
        height: {scale(12)}px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS['beige']};
        border: 1px solid {COLORS['glass_border']};
        selection-background-color: rgba(0, 0, 0, 0.1);
        selection-color: {COLORS['brown_text']};
        outline: none;
    }}

    QLineEdit, QSpinBox {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(15)}px;
        padding-left: {scale(12)}px;
        padding-right: {scale(12)}px;
        min-height: {scale(32)}px;
        color: {COLORS['brown_text']};
        selection-background-color: rgba(211, 84, 0, 0.3);
    }}
    
    QSpinBox::up-button, QSpinBox::down-button {{
        width: {scale(30)}px;
        background: transparent;
        border: none;
        subcontrol-origin: padding;
        padding-right: {scale(10)}px;
    }}
    
    QPlainTextEdit {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(12)}px;
        padding: {scale(8)}px;
        color: {COLORS['brown_text']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
        border: 1px solid {COLORS['burnt_orange']};
        background-color: rgba(255, 255, 255, 0.6);
    }}

    QTableWidget {{
        background-color: transparent;
        alternate-background-color: rgba(0, 0, 0, 0.02);
        gridline-color: rgba(0, 0, 0, 0.05);
    }}

    QSplitter::handle {{ background-color: transparent; }}
"""



# Stylesheet for the Main Toolbar in CreatorWindow
def get_creator_toolbar_style():
    return f"""
    QToolBar {{ 
        background: transparent; 
        border: none; 
        spacing: {scale(10)}px; 
        padding: {scale(5)}px; 
    }}
    QToolButton {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        font-weight: bold; 
        color: {COLORS['brown_text']}; 
        padding: {scale(8)}px {scale(24)}px;
        border-radius: {scale(25)}px;
        margin: {scale(2)}px;
    }}
    QToolButton:hover {{ 
        background-color: rgba(255, 255, 255, 0.7); 
    }}
"""



# Stylesheet for RepoSettingsDialog
def get_repo_settings_style():
    return f"""
    QDialog {{ background-color: {COLORS['beige']}; }}
    QWidget {{ font-family: 'Segoe UI'; font-size: {scale(14)}px; color: {COLORS['brown_text']}; }}
    
    QListWidget#Sidebar {{ 
        background-color: {COLORS['glass_bg']}; 
        border: none; 
        border-right: 1px solid {COLORS['glass_border']}; 
        outline: none; 
    }}
    QListWidget#Sidebar::item {{ padding: {scale(15)}px; font-weight: bold; border-bottom: 1px solid {COLORS['glass_border']}; }}
    QListWidget#Sidebar::item:selected {{ 
        background-color: {COLORS['glass_bg']}; 
        color: {COLORS['burnt_orange']}; 
    }}
    
    QGroupBox {{ 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(10)}px; 
        margin-top: 1.5em; 
        font-weight: bold; 
        background-color: {COLORS['glass_bg']}; 
        padding: {scale(15)}px; 
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: {scale(10)}px; padding: 0 {scale(5)}px; }}
    
    QPushButton {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(20)}px; 
        padding: {scale(8)}px {scale(15)}px; 
        font-weight: bold; 
    }}
    QPushButton:hover {{ 
        background-color: rgba(211, 84, 0, 0.1); 
        border-color: {COLORS['burnt_orange']};
    }}
    
    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(15)}px; 
        padding: {scale(5)}px; 
    }}
    
    QSplitter::handle {{ background-color: transparent; }}
"""


# Stylesheet for ExportDialog
def get_export_dialog_style():
    return f"""
    QDialog {{ background-color: {COLORS['beige']}; }}
    QWidget {{ font-family: 'Segoe UI'; font-size: {scale(14)}px; color: {COLORS['brown_text']}; }}
    
    QGroupBox {{ 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(15)}px; 
        margin-top: 1.5em; 
        font-weight: bold; 
        background-color: {COLORS['glass_bg']}; 
        padding: {scale(15)}px; 
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: {scale(10)}px; padding: 0 {scale(5)}px; }}
    
    QPushButton {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(20)}px; 
        padding: {scale(8)}px {scale(15)}px; 
        font-weight: bold; 
    }}
    QPushButton:hover {{ 
        background-color: rgba(211, 84, 0, 0.1); 
        border-color: {COLORS['burnt_orange']};
    }}
    
    QPushButton#PrimaryButton {{
        background-color: {COLORS['burnt_orange']};
        color: white;
        border: none;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: #e67e22;
    }}
    
    QSpinBox {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: {scale(15)}px; 
        padding: {scale(5)}px; 
    }}
"""


# Stylesheet for LoginDialog
def get_login_dialog_style():
    return f"""
    QDialog {{ 
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['beige']}, stop:1 #d1bfae); 
    }}
    
    QLabel {{ 
        font-family: 'Inter', 'Segoe UI'; 
        color: {COLORS['brown_text']}; 
    }}
    
    #LoginTitle {{
        font-size: {scale(36)}px;
        font-weight: 900;
        color: {COLORS['brown_text']};
        letter-spacing: {scale(2)}px;
    }}
    
    #LoginSubtitle {{
        font-size: {scale(16)}px;
        font-weight: 500;
        color: {COLORS['light_text']};
    }}
    
    #ProfileGridContainer {{
        background-color: rgba(255, 255, 255, 0.3);
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(25)}px;
    }}
    
    QPushButton[class="ProfileGridButton"] {{
        background-color: rgba(255, 255, 255, 0.5);
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(12)}px;
        padding: {scale(12)}px;
        color: {COLORS['brown_text']};
        font-size: {scale(14)}px;
        font-weight: 700;
        text-align: center;
        min-width: {scale(160)}px;
    }}
    
    QPushButton[class="ProfileGridButton"]:hover {{
        background-color: rgba(255, 255, 255, 0.9);
        border-color: {COLORS['burnt_orange']};
        color: {COLORS['burnt_orange']};
    }}
    
    QPushButton[class="ProfileGridButton"]:pressed {{
        background-color: {COLORS['burnt_orange']};
        color: white;
    }}
    
    QPushButton {{
        background-color: rgba(255, 255, 255, 0.4);
        border: 1px solid {COLORS['glass_border']};
        border-radius: {scale(20)}px;
        padding: {scale(15)}px;
        color: {COLORS['brown_text']};
        font-size: {scale(15)}px;
        font-weight: bold;
    }}
    
    QPushButton:hover {{
        background-color: rgba(255, 255, 255, 0.8);
        border-color: {COLORS['burnt_orange']};
    }}
    
    QPushButton#PrimaryAction {{
        background-color: {COLORS['burnt_orange']};
        color: white;
        border: none;
    }}
    
    QPushButton#PrimaryAction:hover {{
        background-color: #e67e22;
    }}
    
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: {scale(8)}px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.1);
        min-height: {scale(20)}px;
        border-radius: {scale(4)}px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
"""
