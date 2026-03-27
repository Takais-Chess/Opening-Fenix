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
MAIN_WINDOW_STYLE = f"""
    QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['beige']}, stop:1 #d1bfae); }}
    QWidget {{ font-family: 'Segoe UI', 'Arial'; color: {COLORS['brown_text']}; }}
    
    #CustomTitleBar {{ 
        background-color: transparent; 
        border: none;
    }}
    
    #TopBar {{ 
        background-color: transparent; 
        border: none; 
    }}
    
    .GlassPill {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: 18px;
        padding: 5px 15px;
    }}
    .GlassPill:hover {{
        background-color: rgba(255, 255, 255, 0.7);
    }}
    
    QPushButton#RepoTab {{ 
        background-color: transparent; 
        border: none; 
        padding: 10px 10px; 
        font-size: 14px; 
        font-weight: bold; 
        color: {COLORS['light_text']}; 
    }}
    QPushButton#RepoTab:hover {{ color: {COLORS['burnt_orange']}; background-color: {COLORS['glass_bg']}; border-radius: 5px; }}
    QPushButton#RepoTab:checked {{ 
        color: {COLORS['burnt_orange']}; 
        border-bottom: 3px solid {COLORS['burnt_orange']}; 
    }}
    
    #BoardPanel, #SidePanel {{ 
        background-color: {COLORS['glass_bg']}; 
        border-radius: 15px; 
        border: 1px solid {COLORS['glass_border']}; 
    }}
    
    QTextBrowser#NotationView {{ 
        background-color: transparent; 
        border: none; 
        font-size: 18px; 
        line-height: 1.5; 
    }}
    
    QPushButton#ActionButton {{ 
        background-color: {COLORS['dark_beige']}; 
        border: 1px solid {COLORS['border']}; 
        border-radius: 8px; 
        padding: 5px; 
        font-size: 18px; 
        min-height: 40px; 
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
        border-radius: 25px; 
        font-size: 18px; 
        font-weight: bold; 
        padding: 15px; 
    }}
    QPushButton#StartButton:hover {{ background-color: #e67e22; }}
    QPushButton#StartButton:disabled {{ background-color: #bdc3c7; }}
    
    QToolTip {{ 
        background-color: {COLORS['white']}; 
        color: {COLORS['brown_text']}; 
        border: 1px solid {COLORS['border']}; 
        padding: 5px; 
        border-radius: 4px; 
    }}
"""

# Stylesheet for the CreatorWindow
CREATOR_WINDOW_STYLE = f"""
    QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['beige']}, stop:1 #d1bfae); }}
    QWidget {{ font-family: 'Segoe UI'; color: {COLORS['brown_text']}; }}
    
    #CustomTitleBar {{ 
        background-color: transparent; 
        border: none;
    }}
    
    #BoardPanel, #SidePanel {{ 
        background-color: {COLORS['glass_bg']}; 
        border-radius: 15px; 
        border: 1px solid {COLORS['glass_border']}; 
    }}

    .GlassPill {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: 18px;
        padding: 5px 15px;
    }}
    .GlassPill:hover {{
        background-color: rgba(255, 255, 255, 0.7);
    }}
    
    QGroupBox {{ 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: 12px; 
        margin-top: 1.5em; 
        font-weight: bold; 
        font-size: 13px;
        background-color: rgba(255, 255, 255, 0.1); 
        padding: 15px; 
    }}
    QGroupBox::title {{ 
        subcontrol-origin: margin; 
        left: 10px; 
        padding: 0 5px; 
        color: {COLORS['brown_text']};
    }}
    
    QTreeWidget, QTableWidget {{ 
        background-color: transparent; 
        border: none;
        outline: none;
    }}
    QTreeWidget::item, QTableWidget::item {{
        border-bottom: 1px solid rgba(0, 0, 0, 0.05);
        padding: 4px;
    }}
    QTreeWidget::item:hover, QTableWidget::item:hover {{
        background-color: rgba(211, 84, 0, 0.2);
    }}
    QTreeWidget::item:selected, QTableWidget::item:selected {{
        background-color: {COLORS['burnt_orange']};
        color: white;
        border-radius: 4px;
    }}

    QTabWidget::pane {{
        border: none;
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {COLORS['brown_text']};
        padding: 8px 16px;
        margin-right: 4px;
        border-radius: 12px;
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

    .SymbolButton {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: 4px;
        font-weight: bold;
        font-size: 16px;
        padding: 0px;
    }}
    .SymbolButton:hover {{
        background-color: rgba(255, 255, 255, 0.7);
    }}

    QHeaderView::section {{
        background-color: transparent;
        color: {COLORS['brown_text']};
        font-weight: bold;
        padding: 5px;
        border: none;
        border-bottom: 2px solid {COLORS['glass_border']};
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
        border-radius: 12px;
        padding: 5px 15px;
        min-height: 25px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 30px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid {COLORS['brown_text']};
        margin-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS['beige']};
        border: 1px solid {COLORS['glass_border']};
        selection-background-color: rgba(0, 0, 0, 0.1);
        selection-color: {COLORS['brown_text']};
        outline: none;
    }}

    QLineEdit, QPlainTextEdit, QSpinBox {{
        background-color: {COLORS['glass_bg']};
        border: 1px solid {COLORS['glass_border']};
        border-radius: 8px;
        padding: 5px;
        color: {COLORS['brown_text']};
        selection-background-color: rgba(211, 84, 0, 0.3);
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
CREATOR_TOOLBAR_STYLE = f"""
    QToolBar {{ 
        background: transparent; 
        border: none; 
        spacing: 10px; 
        padding: 5px; 
    }}
    QToolButton {{ 
        background: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        font-weight: bold; 
        color: {COLORS['brown_text']}; 
        padding: 5px 15px;
        border-radius: 15px;
    }}
    QToolButton:hover {{ 
        background: rgba(255, 255, 255, 0.7); 
    }}
"""

# Stylesheet for RepoSettingsDialog
REPO_SETTINGS_STYLE = f"""
    QDialog {{ background-color: {COLORS['beige']}; }}
    QWidget {{ font-family: 'Segoe UI'; color: {COLORS['brown_text']}; }}
    
    QListWidget#Sidebar {{ 
        background-color: {COLORS['glass_bg']}; 
        border: none; 
        border-right: 1px solid {COLORS['glass_border']}; 
        outline: none; 
    }}
    QListWidget#Sidebar::item {{ padding: 15px; font-weight: bold; border-bottom: 1px solid {COLORS['glass_border']}; }}
    QListWidget#Sidebar::item:selected {{ 
        background-color: {COLORS['glass_bg']}; 
        color: {COLORS['burnt_orange']}; 
    }}
    
    QGroupBox {{ 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: 10px; 
        margin-top: 1.5em; 
        font-weight: bold; 
        background-color: {COLORS['glass_bg']}; 
        padding: 15px; 
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
    
    QPushButton {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: 6px; 
        padding: 8px 15px; 
        font-weight: bold; 
    }}
    QPushButton:hover {{ 
        background-color: rgba(211, 84, 0, 0.1); 
        border-color: {COLORS['burnt_orange']};
    }}
    
    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: 4px; 
        padding: 5px; 
    }}
    
    QSplitter::handle {{ background-color: transparent; }}
"""

# Stylesheet for ExportDialog
EXPORT_DIALOG_STYLE = f"""
    QDialog {{ background-color: {COLORS['beige']}; }}
    QWidget {{ font-family: 'Segoe UI'; color: {COLORS['brown_text']}; }}
    
    QGroupBox {{ 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: 8px; 
        margin-top: 1.5em; 
        font-weight: bold; 
        background-color: {COLORS['glass_bg']}; 
        padding: 15px; 
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
    
    QPushButton {{ 
        background-color: {COLORS['glass_bg']}; 
        border: 1px solid {COLORS['glass_border']}; 
        border-radius: 6px; 
        padding: 8px 15px; 
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
        border-radius: 4px; 
        padding: 5px; 
    }}
"""

# Stylesheet for LoginDialog
LOGIN_DIALOG_STYLE = f"""
    QDialog {{ 
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['beige']}, stop:1 #d1bfae); 
    }}
    
    QLabel {{ 
        font-family: 'Inter', 'Segoe UI'; 
        color: {COLORS['brown_text']}; 
    }}
    
    #LoginTitle {{
        font-size: 36px;
        font-weight: 900;
        color: {COLORS['brown_text']};
        letter-spacing: 2px;
    }}
    
    #LoginSubtitle {{
        font-size: 16px;
        font-weight: 500;
        color: {COLORS['light_text']};
    }}
    
    #ProfileGridContainer {{
        background-color: rgba(255, 255, 255, 0.3);
        border: 1px solid {COLORS['glass_border']};
        border-radius: 25px;
    }}
    
    QPushButton.ProfileGridButton {{
        background-color: rgba(255, 255, 255, 0.5);
        border: 1px solid {COLORS['glass_border']};
        border-radius: 12px;
        padding: 12px;
        color: {COLORS['brown_text']};
        font-size: 14px;
        font-weight: 700;
        text-align: center;
        min-width: 160px;
    }}
    
    QPushButton.ProfileGridButton:hover {{
        background-color: rgba(255, 255, 255, 0.9);
        border-color: {COLORS['burnt_orange']};
        color: {COLORS['burnt_orange']};
    }}
    
    QPushButton.ProfileGridButton:pressed {{
        background-color: {COLORS['burnt_orange']};
        color: white;
    }}
    
    QPushButton {{
        background-color: rgba(255, 255, 255, 0.4);
        border: 1px solid {COLORS['glass_border']};
        border-radius: 15px;
        padding: 15px;
        color: {COLORS['brown_text']};
        font-size: 15px;
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
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.1);
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
"""
