import sys
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt
from PyQt6 import sip
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
        self.preloaded_window = None
        self.preloaded_profile = None

    def start_application(self, initial_profile=None):
        """Initial entry point to start the app lifecycle."""
        self.current_profile = initial_profile
        
        # If we don't have an initial profile, try to preload the last one from config
        if not self.current_profile:
            self.attempt_preload_last_profile()
            
        self.run_loop()

    def attempt_preload_last_profile(self):
        """Attempts to preload the last used profile in the background."""
        try:
            import os
            import json
            from opening_fenix.core.data_tools import get_user_dir
            config_path = os.path.join(get_user_dir(), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                    last_profile = config.get("last_profile")
                    if last_profile:
                        profile_path = os.path.join(get_user_dir(), "profiles", f"{last_profile}.db")
                        if os.path.exists(profile_path):
                            logger.info(f"Preloading last profile: {last_profile}")
                            self.preloaded_profile = last_profile
                            # We create the window but don't show it yet
                            self.preloaded_window = MainWindow(last_profile)
        except Exception as e:
            logger.warning(f"Failed to preload last profile: {e}")

    def run_loop(self):
        """Main application state machine loop."""
        while True:
            if not self.current_profile:
                if not self.show_login():
                    # User cancelled login
                    break
            
            if self.current_profile:
                # If we have an initial profile (auto-login) but no window is preloaded,
                # show a loading screen so the user doesn't see a "black hole".
                if not self.main_window and not self.preloaded_window:
                    self.login_dialog = LoginDialog()
                    self.login_dialog.show()
                    self.login_dialog.show_loading_state(self.current_profile)
                    QApplication.processEvents()

                self.show_main_window()
                
                # Check why main window closed
                if self.main_window and getattr(self.main_window, 'switch_requested', False):
                    self.current_profile = None
                    # Clean up old window
                    if not sip.isdeleted(self.main_window):
                        self.main_window.deleteLater()
                    self.main_window = None
                    continue
                else:
                    # User closed the app
                    break

    def show_login(self):
        """Shows login dialog and returns True if a profile was selected."""
        logger.info("Showing Login Dialog")
        self.login_dialog = LoginDialog()
        
        # Connect signal for transition
        self.login_dialog.profile_selected.connect(self.on_profile_selected)
        
        result = self.login_dialog.exec()
        
        if getattr(self.login_dialog, 'open_creator_requested', False):
            self.show_creator()
            return False 
            
        if result == QDialog.DialogCode.Accepted:
            self.current_profile = self.login_dialog.selected_profile
            logger.info(f"Login successful for profile: {self.current_profile}")
            return True
            
        return False

    def on_profile_selected(self, profile_name):
        """Handle profile selection from LoginDialog."""
        logger.info(f"Profile selected in dialog: {profile_name}")
        self.login_dialog.show_loading_state(profile_name)
        
        # If this profile is already preloaded, we are ready!
        if self.preloaded_profile == profile_name and self.preloaded_window:
            logger.info("Using preloaded window")
            self.main_window = self.preloaded_window
            self.preloaded_window = None
            self.preloaded_profile = None
        else:
            # Not preloaded or different profile, clean up preloaded if any
            if self.preloaded_window:
                self.preloaded_window.deleteLater()
                self.preloaded_window = None
                self.preloaded_profile = None
            
            # Create the main window (this will block the UI for a bit, but overlay is shown)
            self.main_window = MainWindow(profile_name)
            
        # Transition complete, accept the dialog
        self.login_dialog.accept()

    def show_main_window(self):
        """Shows main window and blocks until it closes."""
        logger.info(f"Opening Main Window for profile: {self.current_profile}")
        
        # If we don't have the window yet (e.g. auto-login without preload), create it now
        if not self.main_window:
             self.main_window = MainWindow(self.current_profile)
             
        self.main_window.showMaximized()
        
        # Ensure the window is on top and active
        self.main_window.raise_()
        self.main_window.activateWindow()
        
        # Close login if it was used as a splash or modal
        if self.login_dialog:
            self.login_dialog.close()
            self.login_dialog = None

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
