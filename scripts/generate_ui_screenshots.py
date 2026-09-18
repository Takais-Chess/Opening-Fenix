#!/usr/bin/env python3
"""
Automated UI Screenshot Generator for Opening Fenix 1.0 Release Checkup.
Instantiates all major windows, dialogs, and tabs, rendering them
and saving high-resolution screenshots to Output/screenshots_v1.0/
for multimodal AI visual review.
"""

import os
import sys
import time

# Ensure project root is in path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from PyQt6.QtWidgets import QApplication, QWidget, QDialog
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QPixmap

OUTPUT_DIR = os.path.join(ROOT_DIR, "Output", "screenshots_v1.0")

def capture_widget(widget: QWidget, filename: str, width: int = None, height: int = None, delay_ms: int = 150):
    """Safely renders and captures a widget screenshot."""
    app = QApplication.instance()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    
    if width and height:
        widget.resize(width, height)
        
    widget.show()
    app.processEvents()
    
    # Allow layout stabilization and async timers to settle
    start = time.time()
    while (time.time() - start) * 1000 < delay_ms:
        app.processEvents()
        time.sleep(0.02)
        
    # Grab pixmap
    pixmap = widget.grab()
    out_path = os.path.join(OUTPUT_DIR, filename)
    pixmap.save(out_path, "PNG")
    print(f"  [SAVED] {filename} ({pixmap.width()}x{pixmap.height()})")
    widget.close()
    widget.deleteLater()
    app.processEvents()
    return out_path

def main():
    print("==================================================")
    print("  OPENING FENIX - AUTOMATED UI SCREENSHOT GENERATOR")
    print("==================================================")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Initialize QApplication
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        from opening_fenix.gui.styles import setup_light_palette, set_consistent_icon
        setup_light_palette(app)
        set_consistent_icon(app)

    from opening_fenix.core.translation import translator
    from opening_fenix.core.utils import get_user_dir
    translator.load_language("de")

    screenshots = []

    # 1. Login Dialog
    print("\n[1/12] Capturing LoginDialog...")
    try:
        from opening_fenix.gui.dialogs.login_dialog import LoginDialog
        dlg = LoginDialog()
        capture_widget(dlg, "01_login_dialog.png", width=720, height=540)
    except Exception as e:
        print(f"  [ERROR] LoginDialog failed: {e}")

    # 2. Repertoire Selection Dialog
    print("\n[2/12] Capturing RepertoireSelectionDialog...")
    try:
        from opening_fenix.gui.dialogs.login_dialog import RepertoireSelectionDialog
        dlg = RepertoireSelectionDialog()
        capture_widget(dlg, "02_repertoire_selection_dialog.png", width=750, height=650)
    except Exception as e:
        print(f"  [ERROR] RepertoireSelectionDialog failed: {e}")

    # 3. Main Window (Trainer)
    print("\n[3/12] Capturing MainWindow (Trainer)...")
    try:
        from opening_fenix.gui.main_window import MainWindow
        # Use existing profile or default
        main_win = MainWindow(profile_name="Felix")
        capture_widget(main_win, "03_main_window_trainer.png", width=1280, height=800, delay_ms=300)
    except Exception as e:
        print(f"  [ERROR] MainWindow failed: {e}")

    # 4. Creator Window (Tabs 0 to 4)
    print("\n[4/12] Capturing CreatorWindow Tabs...")
    cwin = None
    try:
        from opening_fenix.creator.creator_window import CreatorWindow
        
        # Get first available repertoire
        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        repos = RepertoireService().get_all_repertoires()
        repo_name = repos[0] if repos else "TestRepo"
        
        cwin = CreatorWindow(repertoire_name=repo_name)
        cwin.resize(1400, 900)
        cwin.show()
        app.processEvents()
        time.sleep(0.3)
        
        tab_names = ["details", "analysis", "transpositions", "holes", "tree"]
        for idx in range(min(5, cwin.tabs.count())):
            cwin.tabs.setCurrentIndex(idx)
            app.processEvents()
            time.sleep(0.2)
            app.processEvents()
            fname = f"04_creator_tab_{idx}_{tab_names[idx] if idx < len(tab_names) else 'tab'}.png"
            pixmap = cwin.grab()
            out_path = os.path.join(OUTPUT_DIR, fname)
            pixmap.save(out_path, "PNG")
            print(f"  [SAVED] {fname} ({pixmap.width()}x{pixmap.height()})")
    except Exception as e:
        print(f"  [ERROR] CreatorWindow failed: {e}")

    # 5. Unified Settings Dialog (Trainer Section)
    print("\n[5/12] Capturing UnifiedSettingsDialog (Trainer)...")
    try:
        from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
        dlg = UnifiedSettingsDialog(initial_section="trainer")
        capture_widget(dlg, "05_settings_trainer.png", width=950, height=700)
    except Exception as e:
        print(f"  [ERROR] UnifiedSettingsDialog (Trainer) failed: {e}")

    # 6. Unified Settings Dialog (Creator Section)
    print("\n[6/12] Capturing UnifiedSettingsDialog (Creator)...")
    try:
        from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
        dlg = UnifiedSettingsDialog(initial_section="creator")
        capture_widget(dlg, "06_settings_creator.png", width=950, height=700)
    except Exception as e:
        print(f"  [ERROR] UnifiedSettingsDialog (Creator) failed: {e}")

    # 7. Unified Settings Dialog (General/Profile Section)
    print("\n[7/12] Capturing UnifiedSettingsDialog (General)...")
    try:
        from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
        dlg = UnifiedSettingsDialog(initial_section="general")
        capture_widget(dlg, "07_settings_general.png", width=950, height=700)
    except Exception as e:
        print(f"  [ERROR] UnifiedSettingsDialog (General) failed: {e}")

    # 8. Engine Setup Dialog
    print("\n[8/12] Capturing EngineActionDialog...")
    try:
        from opening_fenix.gui.dialogs.engine_setup_dialog import EngineActionDialog
        dlg = EngineActionDialog()
        capture_widget(dlg, "08_engine_action_dialog.png", width=650, height=540)
    except Exception as e:
        print(f"  [ERROR] EngineActionDialog failed: {e}")

    # 9. Course Import Dialog
    print("\n[9/12] Capturing CourseImportDialog...")
    try:
        from opening_fenix.gui.dialogs.course_import_dialog import CourseImportDialog
        dlg = CourseImportDialog()
        capture_widget(dlg, "09_course_import_dialog.png", width=800, height=600)
    except Exception as e:
        print(f"  [ERROR] CourseImportDialog failed: {e}")

    # 10. Stats Dialog (Insights)
    print("\n[10/12] Capturing RepertoireStatisticsDialog (Insights)...")
    try:
        from opening_fenix.gui.dialogs.stats_dialog import RepertoireStatisticsDialog
        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        repos = RepertoireService().get_all_repertoires()
        repo_name = repos[0] if repos else "TestRepo"
        dlg = RepertoireStatisticsDialog(repo_name=repo_name)
        capture_widget(dlg, "10_stats_insights_dialog.png", width=850, height=720, delay_ms=400)
    except Exception as e:
        print(f"  [ERROR] RepertoireStatisticsDialog failed: {e}")

    # 11. Export Dialog
    print("\n[11/12] Capturing ExportDialog...")
    try:
        from opening_fenix.gui.dialogs.export_dialog import ExportDialog
        if cwin and hasattr(cwin, 'backend'):
            dlg = ExportDialog(backend=cwin.backend)
            capture_widget(dlg, "11_export_dialog.png", width=500, height=400)
        else:
            print("  [SKIP] ExportDialog requires active backend")
    except Exception as e:
        print(f"  [ERROR] ExportDialog failed: {e}")

    # Clean up cwin if created
    if cwin:
        cwin.close()
        cwin.deleteLater()
        app.processEvents()

    # 12. Update Dialog
    print("\n[12/12] Capturing UpdateDialog...")
    try:
        from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
        info = {
            "version": "1.0.0",
            "title": "Opening Fenix 1.0.0 Release",
            "body": "### Opening Fenix 1.0.0 Release\n- Production Ready!\n- Multi-profile support\n- Transposition Scanner"
        }
        dlg = UpdateDialog(release_info=info)
        capture_widget(dlg, "12_update_dialog.png", width=600, height=450)
    except Exception as e:
        print(f"  [ERROR] UpdateDialog failed: {e}")

    print("\n==================================================")
    print(f"Screenshot generation finished! Files saved in:\n{OUTPUT_DIR}")
    print("==================================================")

if __name__ == "__main__":
    main()
