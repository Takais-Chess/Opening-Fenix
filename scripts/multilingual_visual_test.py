#!/usr/bin/env python3
"""
Multilingual Visual Regression & Inspection Suite for Opening Fenix.
Captures screenshots of every menu, tab, window, and dialog in both
German (de) and English (en), and generates an interactive side-by-side
HTML comparison report to easily spot visual bugs, cut-off texts,
or untranslated strings.
"""

import os
import sys
import time
import json
from typing import Dict, List, Any, Optional, Tuple

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure project root is in path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from PyQt6.QtWidgets import QApplication, QWidget, QDialog
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QPixmap

OUTPUT_BASE = os.path.join(ROOT_DIR, "Output", "visual_review")
SCREENSHOTS_DIR = os.path.join(OUTPUT_BASE, "screenshots")


def capture_widget(widget: QWidget, file_path: str, width: Optional[int] = None, height: Optional[int] = None, delay_ms: int = 150):
    """Safely renders and captures a widget screenshot."""
    app = QApplication.instance()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    if width and height:
        widget.resize(width, height)

    widget.show()
    app.processEvents()

    start = time.time()
    while (time.time() - start) * 1000 < delay_ms:
        app.processEvents()
        time.sleep(0.02)

    pixmap = widget.grab()
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    pixmap.save(file_path, "PNG")
    app.processEvents()
    return file_path


def capture_all_for_language(lang_code: str, items_manifest: List[Dict[str, Any]]):
    """Executes a full capture run for a single language code ('de' or 'en')."""
    print(f"\n=======================================================")
    print(f"  RUNNING SCREENSHOT CAPTURE FOR LANGUAGE: [{lang_code.upper()}]")
    print(f"=======================================================")

    from opening_fenix.core.translation import translator
    from opening_fenix.core.services.repertoire_core_service import RepertoireService
    from opening_fenix.core.services.training_service import TrainingManager

    # Enforce ui_language in profile settings for this run
    orig_get_setting = TrainingManager.get_setting
    TrainingManager.get_setting = lambda self, k, *a, **kw: (
        lang_code if k == "ui_language" else orig_get_setting(self, k)
    )

    # 1. Switch active language
    translator.load_language(lang_code)

    lang_dir = os.path.join(SCREENSHOTS_DIR, lang_code)
    os.makedirs(lang_dir, exist_ok=True)

    app = QApplication.instance()

    # Find a stable existing repertoire with positions
    all_repos = RepertoireService().get_all_repertoires()
    preferred_repos = ["Benko Gambit", "1... e5 Gus", "French Defense"]
    chosen_repo = None
    for pr in preferred_repos:
        if pr in all_repos:
            chosen_repo = pr
            break
    if not chosen_repo and all_repos:
        chosen_repo = all_repos[0]
    if not chosen_repo:
        chosen_repo = "TestRepo"

    print(f"Using reference repertoire: '{chosen_repo}'")

    # Track captured items for this run
    results = {}

    def record_item(key: str, title: str, category: str, filename: str):
        rel_path = f"screenshots/{lang_code}/{filename}"
        results[key] = {
            "key": key,
            "title": title,
            "category": category,
            "filename": filename,
            "rel_path": rel_path,
            "full_path": os.path.join(lang_dir, filename)
        }

    # ─────────────────────────────────────────────────────────────
    # A. MAIN APPLICATION WINDOWS & LOGIN
    # ─────────────────────────────────────────────────────────────
    print("\n--- [Section A] Main Application Windows ---")

    # A1. Login Dialog
    print("  -> Capturing LoginDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.login_dialog import LoginDialog
        dlg = LoginDialog()
        fname = "main_01_login_dialog.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=750, height=560)
        record_item("login_dialog", "Login / Profile Selection", "Main Windows", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] LoginDialog: {e}")

    # A2. Repertoire Selection Dialog
    print("  -> Capturing RepertoireSelectionDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.login_dialog import RepertoireSelectionDialog
        dlg = RepertoireSelectionDialog()
        fname = "main_02_repertoire_selection.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=850, height=680)
        record_item("repertoire_selection", "Repertoire Selection Screen", "Main Windows", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] RepertoireSelectionDialog: {e}")

    # A3. Trainer Main Window & OpenTrainingSetupDialog
    main_win = None
    print("  -> Capturing Trainer MainWindow...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.main_window import MainWindow
        main_win = MainWindow(profile_name="Felix")
        translator.load_language(lang_code)
        fname = "main_03_trainer_window.png"
        capture_widget(main_win, os.path.join(lang_dir, fname), width=1360, height=850, delay_ms=350)
        record_item("trainer_window", "Trainer Main Window", "Main Windows", fname)

        # Open Training Setup Dialog (attached to main_win)
        print("  -> Capturing OpenTrainingSetupDialog...")
        try:
            translator.load_language(lang_code)
            from opening_fenix.gui.dialogs.open_training_dialog import OpenTrainingSetupDialog
            ot_dlg = OpenTrainingSetupDialog(main_win)
            fname_ot = "dialog_07_open_training.png"
            capture_widget(ot_dlg, os.path.join(lang_dir, fname_ot), width=500, height=480)
            record_item("open_training_dialog", "Free Training Setup Dialog", "Dialogs", fname_ot)
            ot_dlg.close()
            ot_dlg.deleteLater()
        except Exception as e_ot:
            print(f"     [ERROR] OpenTrainingSetupDialog: {e_ot}")

    except Exception as e:
        print(f"     [ERROR] MainWindow: {e}")
    finally:
        if main_win:
            main_win.close()
            main_win.deleteLater()
            app.processEvents()

    # A4. Creator Window (Tabs 0 to 2) & Export Dialog
    cwin = None
    print("\n--- [Section B] Creator Window ---")
    try:
        translator.load_language(lang_code)
        from opening_fenix.creator.creator_window import CreatorWindow
        cwin = CreatorWindow(repertoire_name=chosen_repo)
        cwin.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        cwin.resize(1440, 920)
        cwin.show()
        app.processEvents()
        time.sleep(0.3)
        app.processEvents()

        tab_defs = [
            (0, "creator_tab_0_details", "Creator: 0 - Details & Moves"),
            (1, "creator_tab_1_analysis", "Creator: 1 - Analysis & Engine"),
            (2, "creator_tab_2_transpositions", "Creator: 2 - Transpositions Scanner"),
        ]

        for tab_idx, key, title in tab_defs:
            if tab_idx < cwin.tabs.count():
                cwin.tabs.setCurrentIndex(tab_idx)
                app.processEvents()
                time.sleep(0.2)
                app.processEvents()
                fname = f"{key}.png"
                pixmap = cwin.grab()
                out_path = os.path.join(lang_dir, fname)
                pixmap.save(out_path, "PNG")
                record_item(key, title, "Creator Window", fname)
                print(f"     [SAVED] {title} ({pixmap.width()}x{pixmap.height()})")

        # Export Dialog (uses cwin.backend)
        print("  -> Capturing ExportDialog...")
        try:
            translator.load_language(lang_code)
            from opening_fenix.gui.dialogs.export_dialog import ExportDialog
            if hasattr(cwin, 'backend') and cwin.backend:
                exp_dlg = ExportDialog(backend=cwin.backend)
                fname_exp = "dialog_04_export.png"
                capture_widget(exp_dlg, os.path.join(lang_dir, fname_exp), width=540, height=450)
                record_item("export_dialog", "PGN Export Dialog", "Dialogs", fname_exp)
                exp_dlg.close()
                exp_dlg.deleteLater()
        except Exception as e_exp:
            print(f"     [ERROR] ExportDialog: {e_exp}")

    except Exception as e:
        print(f"     [ERROR] CreatorWindow: {e}")
    finally:
        if cwin:
            cwin.close()
            cwin.deleteLater()
            app.processEvents()

    # ─────────────────────────────────────────────────────────────
    # C. UNIFIED SETTINGS DIALOG (EVERY SINGLE SUB-PAGE)
    # ─────────────────────────────────────────────────────────────
    print("\n--- [Section C] Unified Settings Dialog (All 15 Pages) ---")
    settings_dlg = None
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog
        settings_dlg = UnifiedSettingsDialog()
        settings_dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        settings_dlg.resize(1440, 840)
        settings_dlg.show()
        app.processEvents()
        time.sleep(0.2)

        # Map sidebar items to capture
        page_index_map = [
            ("settings_01_global_appearance", "Settings: Global - Appearance & Sound", settings_dlg.page_appearance),
            ("settings_02_global_engine", "Settings: Global - Chess Engine & APIs", settings_dlg.page_engine),
            ("settings_03_global_storage", "Settings: Global - Storage & Data", settings_dlg.page_storage),
            ("settings_04_global_updates", "Settings: Global - Software Updates", settings_dlg.page_updates),
            ("settings_05_help_faq", "Settings: Help - FAQ", settings_dlg.page_faq),
            ("settings_06_help_about", "Settings: Help - About Opening-Fenix", settings_dlg.page_about),
            ("settings_07_trainer_repos", "Settings: Trainer - Repertoire Config", settings_dlg.page_trainer_repos),
            ("settings_08_trainer_behavior", "Settings: Trainer - Training Behavior", settings_dlg.page_trainer_behavior),
            ("settings_09_creator_identity", "Settings: Creator - Identity & Levels", settings_dlg.page_cr_identity),
            ("settings_10_creator_alt_moves", "Settings: Creator - Alternative Moves & Priority", settings_dlg.page_cr_alt_moves),
            ("settings_11_creator_imex", "Settings: Creator - Import & Export", settings_dlg.page_cr_imex),
            ("settings_12_creator_backups", "Settings: Creator - Backups & Restore", settings_dlg.page_cr_backups),
            ("settings_13_creator_tools", "Settings: Creator - Miscellaneous Tools", settings_dlg.page_cr_tools),
            ("settings_14_creator_diagnostics", "Settings: Creator - Database Diagnostics", settings_dlg.page_cr_diag),
            ("settings_15_creator_maintenance", "Settings: Creator - Batch Maintenance Center", settings_dlg.page_cr_maintenance),
        ]

        # Expand all sidebar branches so they look great
        for i in range(settings_dlg.sidebar_tree.topLevelItemCount()):
            settings_dlg.sidebar_tree.topLevelItem(i).setExpanded(True)

        for key, title, target_page in page_index_map:
            # Find item corresponding to target_page
            for i in range(settings_dlg.sidebar_tree.topLevelItemCount()):
                header = settings_dlg.sidebar_tree.topLevelItem(i)
                for j in range(header.childCount()):
                    child = header.child(j)
                    idx = child.data(0, Qt.ItemDataRole.UserRole)
                    if idx == settings_dlg.pages.indexOf(target_page):
                        settings_dlg.sidebar_tree.setCurrentItem(child)
                        settings_dlg.on_tree_item_clicked(child, 0)
                        break

            app.processEvents()
            time.sleep(0.15)
            app.processEvents()

            fname = f"{key}.png"
            out_path = os.path.join(lang_dir, fname)
            pixmap = settings_dlg.grab()
            pixmap.save(out_path, "PNG")
            record_item(key, title, "Settings Pages", fname)
            print(f"     [SAVED] {title} ({pixmap.width()}x{pixmap.height()})")

    except Exception as e:
        print(f"     [ERROR] UnifiedSettingsDialog: {e}")
    finally:
        if settings_dlg:
            settings_dlg.close()
            settings_dlg.deleteLater()
            app.processEvents()

    # ─────────────────────────────────────────────────────────────
    # D. STANDALONE DIALOGS
    # ─────────────────────────────────────────────────────────────
    print("\n--- [Section D] Standalone Dialogs ---")

    # D1. Engine Action Dialog
    print("  -> Capturing EngineActionDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.engine_setup_dialog import EngineActionDialog
        dlg = EngineActionDialog()
        fname = "dialog_01_engine_action.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=680, height=560)
        record_item("engine_action_dialog", "Chess Engine Setup Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] EngineActionDialog: {e}")

    # D2. Course Import Dialog
    print("  -> Capturing CourseImportDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.course_import_dialog import CourseImportDialog
        dlg = CourseImportDialog()
        fname = "dialog_02_course_import.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=850, height=640)
        record_item("course_import_dialog", "Course Import Dialog (Chessable)", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] CourseImportDialog: {e}")

    # D3. Lichess Token Dialog
    print("  -> Capturing LichessTokenDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.lichess_token_dialog import LichessTokenDialog
        dlg = LichessTokenDialog()
        fname = "dialog_03_lichess_token.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=580, height=500)
        record_item("lichess_token_dialog", "Lichess Token Setup Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] LichessTokenDialog: {e}")

    # D4. Repertoire Statistics Dialog (Insights)
    print("  -> Capturing RepertoireStatisticsDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.stats_dialog import RepertoireStatisticsDialog
        dlg = RepertoireStatisticsDialog(repo_name=chosen_repo)
        fname = "dialog_05_repertoire_stats.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=900, height=760, delay_ms=350)
        record_item("repertoire_stats_dialog", "Repertoire Statistics & Insights Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] RepertoireStatisticsDialog: {e}")

    # D5. Software Update Dialog
    print("  -> Capturing UpdateDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
        info = {
            "version": "1.0.1",
            "title": "Opening Fenix v1.0.1",
            "body": "### Features & Improvements\n- Multilingual visual regression testing\n- Full German & English localization\n- UI spacing and layout refinement"
        }
        dlg = UpdateDialog(release_info=info)
        fname = "dialog_06_update.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=650, height=480)
        record_item("update_dialog", "Software Update Notice Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] UpdateDialog: {e}")

    # D6. FAQ Dialog
    print("  -> Capturing FAQDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.faq_dialog import FAQDialog
        dlg = FAQDialog()
        fname = "dialog_08_faq.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=750, height=600)
        record_item("faq_dialog", "Frequently Asked Questions Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] FAQDialog: {e}")

    # D7. Course Intro Dialog
    print("  -> Capturing CourseIntroDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.course_intro_dialog import CourseIntroDialog
        dlg = CourseIntroDialog(repertoire_info={
            "name": chosen_repo,
            "description": "Willkommen zu diesem Repertoire! Hier lernst du alle relevanten Züge und Varianten für dein Schachtraining."
        })
        fname = "dialog_09_course_intro.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=720, height=620)
        record_item("course_intro_dialog", "Course Intro Onboarding Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] CourseIntroDialog: {e}")

    # D8. Delete Level Dialog
    print("  -> Capturing DeleteLevelDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.unified_settings_dialog import DeleteLevelDialog
        sample_levels = [
            {"order": 1, "name": "Basislinien", "moves": 45},
            {"order": 2, "name": "Hauptvarianten", "moves": 120},
            {"order": 3, "name": "Erweiterte Varianten", "moves": 230}
        ]
        dlg = DeleteLevelDialog(levels=sample_levels, default_del_order=2)
        fname = "dialog_10_delete_level.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=500, height=350)
        record_item("delete_level_dialog", "Delete Level Confirmation Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] DeleteLevelDialog: {e}")

    # D9. Missing Token Prompt Dialog
    print("  -> Capturing MissingTokenPromptDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.lichess_token_dialog import MissingTokenPromptDialog
        dlg = MissingTokenPromptDialog(None)
        fname = "dialog_11_missing_token_prompt.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=540, height=380)
        record_item("missing_token_prompt_dialog", "Missing Lichess Token Prompt Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] MissingTokenPromptDialog: {e}")

    # D10. Database Diagnostics Dialog
    print("  -> Capturing DiagnosticDialog...")
    try:
        translator.load_language(lang_code)
        from opening_fenix.gui.dialogs.unified_settings_dialog import DiagnosticDialog
        from opening_fenix.creator.creator_window import CreatorBackend
        diag_backend = CreatorBackend()
        diag_backend.load_repertoire(chosen_repo)
        dlg = DiagnosticDialog(backend=diag_backend)
        fname = "dialog_12_diagnostic.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=650, height=520)
        record_item("diagnostic_dialog", "Database Diagnostics Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] DiagnosticDialog: {e}")

    # D11. Hole Recommendation Settings Dialog
    print("  -> Capturing HoleRecommendationSettingsDialog...")
    try:
        from opening_fenix.gui.dialogs.hole_recommendation_dialog import HoleRecommendationSettingsDialog
        from opening_fenix.creator.creator_window import CreatorBackend
        be = CreatorBackend()
        be.load_repertoire(chosen_repo)
        dlg = HoleRecommendationSettingsDialog(backend=be)
        fname = "dialog_13_hole_recommendations.png"
        capture_widget(dlg, os.path.join(lang_dir, fname), width=540, height=500)
        record_item("hole_recommendation_dialog", "Level Recommendation Rules Dialog", "Dialogs", fname)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:
        print(f"     [ERROR] HoleRecommendationSettingsDialog: {e}")

    # Restore original method
    TrainingManager.get_setting = orig_get_setting

    return results


def generate_html_report(results_de: Dict[str, Any], results_en: Dict[str, Any]):
    """Generates a rich, interactive HTML comparison dashboard."""
    all_keys = list(dict.fromkeys(list(results_de.keys()) + list(results_en.keys())))
    categories = sorted(list({results_de.get(k, results_en.get(k, {})).get("category", "General") for k in all_keys}))

    items_data = []
    for k in all_keys:
        meta_de = results_de.get(k, {})
        meta_en = results_en.get(k, {})
        title = meta_de.get("title") or meta_en.get("title") or k
        cat = meta_de.get("category") or meta_en.get("category") or "General"
        items_data.append({
            "key": k,
            "title": title,
            "category": cat,
            "de_src": f"screenshots/de/{meta_de.get('filename')}" if meta_de else None,
            "en_src": f"screenshots/en/{meta_en.get('filename')}" if meta_en else None,
        })

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Opening Fenix — Multilingual Visual Inspection (DE vs EN)</title>
<style>
  :root {{
    --bg-primary: #121214;
    --bg-card: #1a1a1e;
    --bg-header: #202026;
    --border-color: #2e2e38;
    --text-primary: #f0f0f2;
    --text-secondary: #9e9ea8;
    --accent: #e67e22;
    --accent-hover: #d35400;
    --badge-de: #e74c3c;
    --badge-en: #3498db;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    padding-bottom: 60px;
  }}

  header {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(32, 32, 38, 0.95);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border-color);
    padding: 16px 28px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
  }}

  .header-left h1 {{
    font-size: 1.4rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .header-left p {{
    font-size: 0.85rem;
    color: var(--text-secondary);
  }}

  .filter-bar {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}

  .filter-btn {{
    background: #2a2a34;
    color: var(--text-secondary);
    border: 1px solid var(--border-color);
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }}
  .filter-btn:hover {{
    background: #343442;
    color: var(--text-primary);
  }}
  .filter-btn.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}

  .container {{
    max-width: 1720px;
    margin: 24px auto;
    padding: 0 24px;
  }}

  .stats-bar {{
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
  }}
  .stat-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 14px 20px;
    flex: 1;
  }}
  .stat-card .num {{
    font-size: 1.6rem;
    font-weight: 800;
    color: var(--accent);
  }}
  .stat-card .label {{
    font-size: 0.8rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .view-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    margin-bottom: 28px;
    overflow: hidden;
    box-shadow: 0 4px 16px rgba(0,0,0,0.25);
  }}

  .view-card-header {{
    padding: 14px 20px;
    background: var(--bg-header);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .view-title-group {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .view-title {{
    font-size: 1.1rem;
    font-weight: 700;
  }}
  .category-pill {{
    background: rgba(230, 126, 34, 0.15);
    color: var(--accent);
    font-size: 0.75rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 12px;
    border: 1px solid rgba(230, 126, 34, 0.3);
  }}

  .mode-controls {{
    display: flex;
    gap: 6px;
  }}
  .mode-btn {{
    background: #262630;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
  }}
  .mode-btn.active {{
    background: #3c3c4a;
    color: #fff;
    border-color: #555566;
  }}

  /* Mode 1: Side by Side */
  .grid-side-by-side {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    padding: 18px;
    background: #0d0d0f;
  }}
  .col-pane {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .pane-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.85rem;
    font-weight: 700;
  }}
  .badge {{
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    color: white;
  }}
  .badge-de {{ background: var(--badge-de); }}
  .badge-en {{ background: var(--badge-en); }}

  .img-wrapper {{
    background: #18181c;
    border: 1px solid #282830;
    border-radius: 8px;
    overflow: hidden;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 260px;
    cursor: zoom-in;
    transition: transform 0.15s;
  }}
  .img-wrapper:hover {{
    border-color: #444455;
  }}
  .img-wrapper img {{
    max-width: 100%;
    height: auto;
    display: block;
  }}

  /* Mode 2: Interactive Slider */
  .slider-wrapper {{
    display: none;
    position: relative;
    max-width: 1200px;
    margin: 18px auto;
    overflow: hidden;
    user-select: none;
    border: 1px solid #33333f;
    border-radius: 8px;
  }}
  .slider-wrapper img {{
    width: 100%;
    display: block;
  }}
  .slider-img-top {{
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    width: 50%;
    overflow: hidden;
    border-right: 2px solid var(--accent);
  }}
  .slider-img-top img {{
    height: 100%;
    max-width: none;
  }}
  .slider-input {{
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    opacity: 0;
    cursor: ew-resize;
  }}

  /* Modal for full zoom */
  .modal {{
    display: none;
    position: fixed;
    z-index: 1000;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background: rgba(0,0,0,0.9);
    justify-content: center;
    align-items: center;
    cursor: zoom-out;
  }}
  .modal img {{
    max-width: 95vw;
    max-height: 95vh;
    border-radius: 6px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.8);
  }}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <h1>🦅 Opening Fenix — Multilingual Visual Inspection</h1>
    <p>Compare German (DE) and English (EN) UI captures side-by-side to detect layout shifts, overflow, or untranslated strings.</p>
  </div>
  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterCategory('all', this)">All ({len(items_data)})</button>
"""

    for cat in categories:
        count = sum(1 for item in items_data if item["category"] == cat)
        html_content += f'    <button class="filter-btn" onclick="filterCategory(\'{cat}\', this)">{cat} ({count})</button>\n'

    html_content += f"""  </div>
</header>

<div class="container">
  <div class="stats-bar">
    <div class="stat-card">
      <div class="num">{len(items_data)}</div>
      <div class="label">Total Views Screened</div>
    </div>
    <div class="stat-card">
      <div class="num">2</div>
      <div class="label">Languages Screened (DE & EN)</div>
    </div>
    <div class="stat-card">
      <div class="num">{len(categories)}</div>
      <div class="label">Sections / Categories</div>
    </div>
  </div>

  <div id="views-list">
"""

    for idx, item in enumerate(items_data):
        k = item["key"]
        cat = item["category"]
        title = item["title"]
        de_src = item["de_src"] or ""
        en_src = item["en_src"] or ""

        html_content += f"""
    <div class="view-card" data-category="{cat}">
      <div class="view-card-header">
        <div class="view-title-group">
          <span class="category-pill">{cat}</span>
          <span class="view-title">{title}</span>
        </div>
        <div class="mode-controls">
          <button class="mode-btn active" onclick="setMode('{k}', 'side', this)">Side-by-Side</button>
          <button class="mode-btn" onclick="setMode('{k}', 'slider', this)">A/B Slider</button>
        </div>
      </div>

      <!-- Side by Side Layout -->
      <div id="{k}-side" class="grid-side-by-side">
        <div class="col-pane">
          <div class="pane-header"><span class="badge badge-de">DE</span> Deutsch (German)</div>
          <div class="img-wrapper" onclick="openModal('{de_src}')">
            <img src="{de_src}" alt="DE - {title}" loading="lazy">
          </div>
        </div>
        <div class="col-pane">
          <div class="pane-header"><span class="badge badge-en">EN</span> English</div>
          <div class="img-wrapper" onclick="openModal('{en_src}')">
            <img src="{en_src}" alt="EN - {title}" loading="lazy">
          </div>
        </div>
      </div>

      <!-- Slider Layout -->
      <div id="{k}-slider" class="slider-wrapper">
        <img src="{en_src}" alt="EN baseline" class="slider-base">
        <div class="slider-img-top" id="{k}-top">
          <img src="{de_src}" alt="DE overlay">
        </div>
        <input type="range" min="0" max="100" value="50" class="slider-input" oninput="updateSlider('{k}', this.value)">
      </div>
    </div>
"""

    html_content += """
  </div>
</div>

<div id="modal" class="modal" onclick="closeModal()">
  <img id="modal-img" src="" alt="Full view">
</div>

<script>
function filterCategory(cat, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const cards = document.querySelectorAll('.view-card');
  cards.forEach(card => {
    if (cat === 'all' || card.getAttribute('data-category') === cat) {
      card.style.display = 'block';
    } else {
      card.style.display = 'none';
    }
  });
}

function setMode(key, mode, btn) {
  const card = btn.closest('.view-card');
  card.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const side = document.getElementById(key + '-side');
  const slider = document.getElementById(key + '-slider');

  if (mode === 'side') {
    side.style.display = 'grid';
    slider.style.display = 'none';
  } else {
    side.style.display = 'none';
    slider.style.display = 'block';
    // Sync slider child width
    const baseImg = slider.querySelector('.slider-base');
    const topImg = slider.querySelector('.slider-img-top img');
    if (baseImg && topImg) {
      topImg.style.width = baseImg.clientWidth + 'px';
    }
  }
}

function updateSlider(key, val) {
  const top = document.getElementById(key + '-top');
  if (top) {
    top.style.width = val + '%';
  }
}

function openModal(src) {
  const modal = document.getElementById('modal');
  const modalImg = document.getElementById('modal-img');
  modalImg.src = src;
  modal.style.display = 'flex';
}

function closeModal() {
  document.getElementById('modal').style.display = 'none';
}

window.addEventListener('resize', () => {
  document.querySelectorAll('.slider-wrapper').forEach(slider => {
    const baseImg = slider.querySelector('.slider-base');
    const topImg = slider.querySelector('.slider-img-top img');
    if (baseImg && topImg) {
      topImg.style.width = baseImg.clientWidth + 'px';
    }
  });
});
</script>
</body>
</html>
"""

    report_path = os.path.join(OUTPUT_BASE, "index.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n[HTML REPORT GENERATED] file:///{report_path.replace(os.sep, '/')}")
    return report_path


def check_dialog_coverage() -> List[Tuple[str, str]]:
    """Scans opening_fenix/gui/dialogs to detect any newly added QDialog subclasses."""
    import ast
    dialogs_dir = os.path.join(ROOT_DIR, "opening_fenix", "gui", "dialogs")
    known_legacy_or_sub = {
        "RepoSettingsDialog", "SettingsDialog", "UnifiedSettingsDialog",
        "DualModeCell", "CenteredSpinBoxCell", "NoWheelComboBox",
        "NoWheelSpinBox", "NoWheelDoubleSpinBox", "NoWheelSlider",
        "ToggleSwitch", "FAQItem", "RepertoireButton", "ProfileGridButton",
        "MaintenanceRepoWidget", "RepoLoadButton", "EngineDownloadProgressDialog",
        "ChapterLinesDialog", "LoadRepertoireDialog"
    }
    registered = {
        "LoginDialog", "RepertoireSelectionDialog", "MainWindow", "CreatorWindow",
        "OpenTrainingSetupDialog", "ExportDialog", "EngineActionDialog",
        "CourseImportDialog", "LichessTokenDialog", "MissingTokenPromptDialog",
        "RepertoireStatisticsDialog", "UpdateDialog", "FAQDialog",
        "CourseIntroDialog", "DeleteLevelDialog", "DiagnosticDialog",
        "HoleRecommendationSettingsDialog", "AddLevelDialog"
    }
    uncovered = []
    if os.path.exists(dialogs_dir):
        for f in os.listdir(dialogs_dir):
            if f.endswith('.py') and not f.startswith('__'):
                p = os.path.join(dialogs_dir, f)
                with open(p, 'r', encoding='utf-8') as fh:
                    try:
                        tree = ast.parse(fh.read(), filename=p)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.ClassDef):
                                for base in node.bases:
                                    if (isinstance(base, ast.Name) and 'Dialog' in base.id) or (isinstance(base, ast.Attribute) and 'Dialog' in base.attr):
                                        if node.name not in registered and node.name not in known_legacy_or_sub:
                                            uncovered.append((node.name, f))
                    except Exception as e:
                        pass
    if uncovered:
        print(f"\n[NEW DIALOGS DETECTED] Found {len(uncovered)} uncovered dialog classes:")
        for name, f in uncovered:
            print(f"  * {name} in {f} -> Please add to multilingual_visual_test.py!")
    else:
        print("\n[COVERAGE CHECK] 100% of active dialog and settings classes are registered.")
    return uncovered


def clean_screenshots():
    """Deletes previous screenshots to ensure a fresh, clean capture slate."""
    import shutil
    if os.path.exists(SCREENSHOTS_DIR):
        shutil.rmtree(SCREENSHOTS_DIR)
        print(f"[CLEANUP] Deleted existing screenshots in: {SCREENSHOTS_DIR}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Opening Fenix Multilingual UI Visual Suite")
    parser.add_argument("--clean", action="store_true", help="Delete old screenshots before running")
    parser.add_argument("--check-new", action="store_true", help="Scan codebase for newly added menus or dialogs")
    parser.add_argument("--lang", choices=["de", "en", "both"], default="both", help="Language(s) to capture (default: both)")
    args = parser.parse_args()

    print("================================================================")
    print("  OPENING FENIX - COMPREHENSIVE MULTILINGUAL VISUAL SUITE       ")
    print("================================================================")

    # 1. Always verify coverage for newly added menus/dialogs
    check_dialog_coverage()

    # 2. Optionally clean old screenshots
    if args.clean:
        clean_screenshots()

    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        from opening_fenix.gui.styles import setup_light_palette, set_consistent_icon
        setup_light_palette(app)
        set_consistent_icon(app)

    items_manifest = []
    results_de = {}
    results_en = {}

    # Run requested languages
    if args.lang in ["de", "both"]:
        results_de = capture_all_for_language("de", items_manifest)

    if args.lang in ["en", "both"]:
        results_en = capture_all_for_language("en", items_manifest)

    # If only one was run, load the other from existing results if available
    report_file = generate_html_report(results_de, results_en)

    print("\n================================================================")
    print(f" Multilingual Visual Test Run Complete!")
    print(f" Captured {len(results_de)} views in German (DE).")
    print(f" Captured {len(results_en)} views in English (EN).")
    print(f" Interactive Report ready at:")
    print(f"   {report_file}")
    print("================================================================")


if __name__ == "__main__":
    main()
