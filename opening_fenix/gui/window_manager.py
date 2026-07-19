import sys
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt
from PyQt6 import sip
from opening_fenix.core.logger import logger

class LoginDialog:
    def __new__(cls, *args, **kwargs):
        from opening_fenix.gui.dialogs.login_dialog import LoginDialog as RealLoginDialog
        return RealLoginDialog(*args, **kwargs)

class MainWindow:
    def __new__(cls, *args, **kwargs):
        from opening_fenix.gui.main_window import MainWindow as RealMainWindow
        return RealMainWindow(*args, **kwargs)

class CreatorWindow:
    def __new__(cls, *args, **kwargs):
        from opening_fenix.creator.creator_window import CreatorWindow as RealCreatorWindow
        return RealCreatorWindow(*args, **kwargs)

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
                # If we have an initial profile (auto-login) but no window is preloaded,
                # show a loading screen so the user doesn't see a "black hole".
                if not self.main_window:
                    from PyQt6.QtCore import QEventLoop, QTimer
                    self.login_dialog = LoginDialog()
                    self.login_dialog.show()
                    self.login_dialog.show_loading_state(self.current_profile)
                    
                    # Spin a short event loop to let the dialog map, layout and paint itself
                    loop = QEventLoop()
                    QTimer.singleShot(150, loop.quit)
                    loop.exec()

                self.show_main_window()
                
                # Check why main window closed
                if self.main_window and getattr(self.main_window, 'switch_requested', False):
                    self.current_profile = None
                    # Clear auto-login on profile switch
                    try:
                        import os
                        import json
                        from opening_fenix.core.utils import get_user_dir
                        config_path = os.path.join(get_user_dir(), "config.json")
                        if os.path.exists(config_path):
                            with open(config_path, "r") as f:
                                config = json.load(f)
                            config["auto_login_profile"] = None
                            with open(config_path, "w") as f:
                                json.dump(config, f, indent=4)
                    except Exception as e:
                        logger.warning(f"Could not clear auto_login_profile on switch: {e}")
                    # Clean up old window
                    is_mock = hasattr(self.main_window, "__unittest_mock__") or "Mock" in str(type(self.main_window))
                    if is_mock or not sip.isdeleted(self.main_window):
                        self.main_window.close() # Trigger closeEvent for cleanup
                        self.main_window.deleteLater()
                    
                    self.main_window = None
                    
                    # Force event processing to ensure deletion of C++ objects (and DB sessions)
                    # on Windows before the next loop starts the same DB connection.
                    for _ in range(5):
                        QApplication.processEvents()
                    import time
                    time.sleep(0.1) # Small buffer for Windows file locks
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
