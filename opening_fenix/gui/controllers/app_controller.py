import os
import json
from PyQt6.QtWidgets import QMessageBox
from opening_fenix.gui.dialogs.course_intro_dialog import CourseIntroDialog
from opening_fenix.gui.widgets.tour_overlay import GuidedTourOverlay

class AppController:
    """
    Handles high-level application logic such as tours, course intros, 
    and session-wide state management.
    """
    def __init__(self, main_window):
        self.main_window = main_window

    def check_for_course_intro(self, repo_name):
        if not repo_name or not self.main_window.repertoire_manager.repo_session:
            return
            
        from opening_fenix.core.db.meta_utils import get_meta, set_meta
        repo_session = self.main_window.repertoire_manager.repo_session
        
        intro_text = get_meta(repo_session, "course_intro", "")
        has_seen = get_meta(repo_session, "seen_intro", "0") == "1"
        
        if intro_text and not has_seen:
            # Show intro
            dlg = CourseIntroDialog(intro_text, self.main_window)
            if dlg.exec():
                set_meta(repo_session, "seen_intro", "1")
                repo_session.commit()

    def start_tour(self, version):
        """Starts a UI tour if the user hasn't seen it for this version."""
        # Simple implementation for now
        pass

    def handle_repertoire_error(self, message):
        QMessageBox.critical(self.main_window, tr_ui("main.dlg_error_title", "Fehler"), message)
