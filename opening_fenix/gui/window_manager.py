import sys
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt
from opening_fenix.gui.dialogs.login_dialog import LoginDialog
from opening_fenix.gui.main_window import MainWindow
from opening_fenix.creator.creator_window import CreatorWindow
from opening_fenix.core.logger import logger

class WindowManager:
    def __init__(self):
        self.current_profile = None
        self.login_dialog = None
        self.main_window = None
        self.creator_window = None

    def start_application(self, initial_profile=None):
        """Initial entry point to start the app lifecycle."""
        self.current_profile = initial_profile
        self.run_loop()

    def run_loop(self):
        """Main application state machine loop."""
        while True:
            if not self.current_profile:
                if not self.show_login():
                    # User cancelled login
                    break
            
            if self.current_profile:
                self.show_main_window()
                
                # Check why main window closed
                if self.main_window and getattr(self.main_window, 'switch_requested', False):
                    self.current_profile = None
                    continue
                else:
                    # User closed the app
                    break

    def show_login(self):
        """Shows login dialog and returns True if a profile was selected."""
        logger.info("Showing Login Dialog")
        self.login_dialog = LoginDialog()
        result = self.login_dialog.exec()
        
        if getattr(self.login_dialog, 'open_creator_requested', False):
            self.show_creator()
            return False # Creator handled its own loop for now, or we can exit
            
        if result == QDialog.DialogCode.Accepted:
            self.current_profile = self.login_dialog.selected_profile
            logger.info(f"Login successful for profile: {self.current_profile}")
            return True
            
        return False

    def show_main_window(self):
        """Shows main window and blocks until it closes."""
        logger.info(f"Opening Main Window for profile: {self.current_profile}")
        
        # Optional: update config last_profile here or in MainWindow
        self.main_window = MainWindow(self.current_profile)
        self.main_window.showMaximized()
        
        # Helper to ensure cursor is restored
        try:
            QApplication.restoreOverrideCursor()
        except: pass
            
        QApplication.instance().exec()
        
        # Cleanup
        while QApplication.overrideCursor():
            QApplication.restoreOverrideCursor()

    def show_creator(self):
        """Transition to Creator Window."""
        logger.info("Opening Creator Window")
        # In a real state machine, Creator might be its own state
        # For now, following existing logic
        self.creator_window = CreatorWindow()
        self.creator_window.showMaximized()
        
        try:
            QApplication.restoreOverrideCursor()
        except: pass
        
        QApplication.instance().exec()
