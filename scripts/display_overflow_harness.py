#!/usr/bin/env python3
"""
Automated Display Test Harness & Overflow Inspector for Opening Fenix.
Simulates and tests every window, dialog, and widget across multiple screen
resolutions and DPI scale factors (from 768p budget laptops to 1080p Full HD
and 4K displays).

Detects:
  - Critical window overflows (minimumSize > available screen viewport)
  - Initial geometry overflows (widget.size > available screen viewport)
  - Unreachable action buttons (Save/Cancel/OK pushed below taskbar)
  - Missing scroll areas on constrained screens
  - Text clipping / truncation in labels and buttons
  - Chessboard aspect ratio and playable square size distortions
"""

import os
import sys
import json
import time
import argparse
from typing import Dict, List, Any, Optional, Tuple, Callable

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from PyQt6.QtWidgets import (
    QApplication, QWidget, QDialog, QMainWindow, QPushButton,
    QDialogButtonBox, QScrollArea, QLabel, QTabBar, QTabWidget
)
from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QFontMetrics

from opening_fenix.gui.scaling import (
    scaler,
    set_emulation,
    set_emulation_profile,
    reset_emulation,
    get_available_geometry,
    get_screen_geometry,
    DISPLAY_PROFILES,
)
from opening_fenix.core.translation import translator

OUTPUT_DIR = os.path.join(ROOT_DIR, "Output", "display_audit")
REPORTS_DIR = OUTPUT_DIR


# Standard action keywords that users must be able to click
ACTION_KEYWORDS = [
    "ok", "save", "speichern", "cancel", "abbrechen", "schließen", "close",
    "fertig", "done", "start", "starten", "import", "importieren",
    "anwenden", "apply", "löschen", "delete", "weiter", "next"
]


def create_qt_app() -> QApplication:
    """Ensures a single headless-safe QApplication instance exists."""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    QApplication.setStyle("Fusion")
    return app


class DisplayOverflowHarness:
    """
    Test harness that runs UI components against emulated screen resolutions
    and audits them for physical overflow, unreachable buttons, and clipping.
    """

    def __init__(self, profiles: Optional[List[str]] = None, lang_code: str = "de"):
        self.app = create_qt_app()
        self.lang_code = lang_code
        translator.load_language(lang_code)
        
        # Default test matrix: HD 768p, FHD 1080p Laptop (125% DPI), FHD 1080p Desktop (100% DPI)
        self.test_profiles = profiles or ["768p", "1080p_laptop", "1080p"]
        self.results: List[Dict[str, Any]] = []

    def get_component_catalog(self) -> List[Tuple[str, str, Callable[[], QWidget]]]:
        """Returns catalog of (key, title, factory_callable)."""
        from opening_fenix.gui.dialogs.login_dialog import LoginDialog, RepertoireSelectionDialog
        from opening_fenix.gui.dialogs.course_import_dialog import CourseImportDialog
        from opening_fenix.gui.dialogs.course_intro_dialog import CourseIntroDialog
        from opening_fenix.gui.dialogs.engine_setup_dialog import EngineActionDialog
        from opening_fenix.gui.dialogs.export_dialog import ExportDialog
        from opening_fenix.gui.dialogs.faq_dialog import FAQDialog
        from opening_fenix.gui.dialogs.hole_recommendation_dialog import HoleRecommendationSettingsDialog
        from opening_fenix.gui.dialogs.lichess_token_dialog import LichessTokenDialog, MissingTokenPromptDialog
        from opening_fenix.gui.dialogs.open_training_dialog import OpenTrainingSetupDialog
        from opening_fenix.gui.dialogs.settings_dialog import LoadRepertoireDialog
        from opening_fenix.gui.dialogs.stats_dialog import RepertoireStatisticsDialog
        from opening_fenix.gui.dialogs.task_center_dialog import TaskCenterDialog
        from opening_fenix.gui.dialogs.unified_settings_dialog import UnifiedSettingsDialog, DeleteLevelDialog
        from opening_fenix.gui.dialogs.update_dialog import UpdateDialog
        from opening_fenix.creator.repo_selection_dialog import NewRepertoireDialog, RepoSelectionDialog
        from opening_fenix.gui.main_window import MainWindow
        from opening_fenix.creator.creator_window import CreatorWindow

        catalog = [
            ("login_dialog", "Login / Profile Selection", lambda: LoginDialog()),
            ("repertoire_selection", "Repertoire Selection", lambda: RepertoireSelectionDialog()),
            ("main_window", "Trainer Main Window", lambda: MainWindow(profile_name="Freies Training")),
            ("creator_window", "Repertoire Creator Window", lambda: CreatorWindow(repertoire_name=None, is_test=True)),
            ("course_import_dialog", "Course Import Dialog (Chessable)", lambda: CourseImportDialog()),
            ("course_intro_dialog", "Course Intro Dialog", lambda: CourseIntroDialog(repertoire_info={"name": "Test", "description": "Intro"})),
            ("engine_action_dialog", "Chess Engine Action Dialog", lambda: EngineActionDialog()),
            ("faq_dialog", "FAQ Dialog", lambda: FAQDialog()),
            ("lichess_token_dialog", "Lichess Token Dialog", lambda: LichessTokenDialog()),
            ("missing_token_dialog", "Missing Token Prompt", lambda: MissingTokenPromptDialog(None)),
            ("load_repertoire_dialog", "Load Repertoire Dialog", lambda: LoadRepertoireDialog()),
            ("stats_dialog", "Repertoire Statistics Dialog", lambda: RepertoireStatisticsDialog()),
            ("task_center_dialog", "Task Center Dialog", lambda: TaskCenterDialog()),
            ("unified_settings_dialog", "Unified Settings Dialog", lambda: UnifiedSettingsDialog()),
            ("delete_level_dialog", "Delete Level Dialog", lambda: DeleteLevelDialog([{"order": 1, "name": "Basis", "moves": 10}], 1)),
            ("update_dialog", "Software Update Notice", lambda: UpdateDialog({"version": "1.0.1", "title": "Update", "body": "Notes"})),
            ("new_repertoire_dialog", "Creator New Repertoire Dialog", lambda: NewRepertoireDialog()),
            ("creator_repo_selection", "Creator Repertoire Loader Dialog", lambda: RepoSelectionDialog()),
        ]
        return catalog

    def inspect_widget(
        self,
        widget: QWidget,
        comp_key: str,
        comp_title: str,
        profile_key: str,
        avail_w: int,
        avail_h: int
    ) -> Dict[str, Any]:
        """Audits a single instantiated widget against available screen geometry."""
        # Render offscreen
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        widget.show()
        self.app.processEvents()

        min_w = widget.minimumSize().width()
        min_h = widget.minimumSize().height()
        cur_w = widget.width()
        cur_h = widget.height()
        hint_w = widget.sizeHint().width()
        hint_h = widget.sizeHint().height()

        issues = []
        severity = "PASS"

        # 1. Critical Minimum Size Check (Can the window even be shrunk to fit the display?)
        if min_h > avail_h:
            overflow_px = min_h - avail_h
            issues.append({
                "type": "MIN_HEIGHT_OVERFLOW",
                "severity": "CRITICAL",
                "msg": f"Minimum height ({min_h}px) exceeds available screen height ({avail_h}px) by {overflow_px}px. Window cannot fit screen!",
                "overflow_px": overflow_px,
            })
            severity = "CRITICAL"

        if min_w > avail_w:
            overflow_px = min_w - avail_w
            issues.append({
                "type": "MIN_WIDTH_OVERFLOW",
                "severity": "CRITICAL",
                "msg": f"Minimum width ({min_w}px) exceeds available screen width ({avail_w}px) by {overflow_px}px.",
                "overflow_px": overflow_px,
            })
            severity = "CRITICAL"

        # 2. Initial / Requested Geometry Check
        if cur_h > avail_h:
            overflow_px = cur_h - avail_h
            issues.append({
                "type": "INITIAL_HEIGHT_OVERFLOW",
                "severity": "WARNING",
                "msg": f"Initial/requested height ({cur_h}px) exceeds available height ({avail_h}px) by {overflow_px}px.",
                "overflow_px": overflow_px,
            })
            if severity != "CRITICAL":
                severity = "WARNING"

        if cur_w > avail_w:
            overflow_px = cur_w - avail_w
            issues.append({
                "type": "INITIAL_WIDTH_OVERFLOW",
                "severity": "WARNING",
                "msg": f"Initial/requested width ({cur_w}px) exceeds available width ({avail_w}px) by {overflow_px}px.",
                "overflow_px": overflow_px,
            })
            if severity != "CRITICAL":
                severity = "WARNING"

        # 3. Action Buttons Inaccessibility Check (Simulate clamping window to available viewport)
        clamped_w = min(cur_w, avail_w)
        clamped_h = min(cur_h, avail_h)
        widget.resize(clamped_w, clamped_h)
        self.app.processEvents()

        # If widget contains QTabWidgets, cycle through all tabs so each tab lays out
        tab_widgets = widget.findChildren(QTabWidget)
        tab_states = []
        for tw in tab_widgets:
            tab_states.append((tw, tw.currentIndex()))

        def audit_visible_buttons():
            for btn in widget.findChildren(QPushButton):
                if not btn.isVisibleTo(widget):
                    continue
                txt = (btn.text() or "").strip().lower()
                if any(k in txt for k in ACTION_KEYWORDS) or isinstance(btn.parent(), QDialogButtonBox):
                    # Check whether button is enclosed in a scrollable container
                    is_in_scroll = False
                    p = btn.parent()
                    while p and p != widget:
                        if isinstance(p, QScrollArea):
                            is_in_scroll = True
                            break
                        p = p.parent()

                    btn_pos = btn.mapTo(widget, btn.rect().topLeft())
                    btn_bottom = btn_pos.y() + btn.height()
                    btn_right = btn_pos.x() + btn.width()
                    
                    # Critical cutoff: pushed below bottom edge with NO scroll area to reach it
                    if not is_in_scroll and btn_bottom > clamped_h:
                        overflow_px = btn_bottom - clamped_h
                        issues.append({
                            "type": "ACTION_BUTTON_CUTOFF",
                            "severity": "CRITICAL",
                            "msg": f"Action button '{btn.text()}' is pushed below viewport by {overflow_px}px and is unclickable (no scroll area)!",
                            "button": btn.text(),
                            "overflow_px": overflow_px,
                        })
                        nonlocal severity
                        severity = "CRITICAL"
                    action_buttons.append({
                        "text": btn.text(),
                        "y_bottom": btn_bottom,
                        "visible": True,
                        "in_scroll": is_in_scroll,
                    })

        action_buttons = []
        if tab_widgets:
            for tw in tab_widgets:
                for t_idx in range(tw.count()):
                    tw.setCurrentIndex(t_idx)
                    self.app.processEvents()
                    audit_visible_buttons()
            # Restore initial tab states
            for tw, orig_idx in tab_states:
                tw.setCurrentIndex(orig_idx)
                self.app.processEvents()
        else:
            audit_visible_buttons()

        # 4. ScrollArea Presence Check
        scroll_areas = widget.findChildren(QScrollArea)
        has_scroll = len(scroll_areas) > 0
        if hint_h > avail_h and not has_scroll and not isinstance(widget, (QMainWindow, )):
            issues.append({
                "type": "MISSING_SCROLL_AREA",
                "severity": "WARNING",
                "msg": f"Content height hint ({hint_h}px) exceeds available height ({avail_h}px), but dialog lacks a QScrollArea.",
            })
            if severity != "CRITICAL":
                severity = "WARNING"

        # 5. Text Clipping / Truncation Check
        clipped_labels = []
        for lbl in widget.findChildren(QLabel):
            if not lbl.isVisible():
                continue
            text = lbl.text()
            if not text or "<" in text:  # skip HTML
                continue
            fm = lbl.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            lbl_w = lbl.width()
            if lbl_w > 0 and text_width > lbl_w + 5 and not lbl.wordWrap():
                clipped_labels.append({
                    "text": text[:30] + ("..." if len(text) > 30 else ""),
                    "text_px": text_width,
                    "widget_px": lbl_w,
                })
        
        if clipped_labels:
            issues.append({
                "type": "TEXT_TRUNCATION",
                "severity": "WARNING",
                "msg": f"Found {len(clipped_labels)} clipped text labels.",
                "clipped_items": clipped_labels[:5],
            })
            if severity != "CRITICAL":
                severity = "WARNING"

        # 6. Chess Board Geometry Check (if present)
        from opening_fenix.gui.widgets.board_widget import ChessBoardWidget
        boards = widget.findChildren(ChessBoardWidget)
        board_info = None
        if boards:
            b = boards[0]
            side, sq_size, x_off, y_off = b.get_metrics()
            board_info = {
                "side_px": side,
                "square_px": sq_size,
                "playable": sq_size >= 32.0,
            }
            if sq_size < 32.0:
                issues.append({
                    "type": "BOARD_TOO_SMALL",
                    "severity": "WARNING",
                    "msg": f"Chessboard square size ({sq_size:.1f}px) is below minimum comfortable playable threshold (32px).",
                })
                if severity != "CRITICAL":
                    severity = "WARNING"

        return {
            "key": comp_key,
            "title": comp_title,
            "profile": profile_key,
            "available_w": avail_w,
            "available_h": avail_h,
            "scale_factor": scaler.factor,
            "min_w": min_w,
            "min_h": min_h,
            "cur_w": cur_w,
            "cur_h": cur_h,
            "hint_w": hint_w,
            "hint_h": hint_h,
            "has_scroll": has_scroll,
            "board_info": board_info,
            "severity": severity,
            "issues": issues,
        }

    def run_audit(self) -> List[Dict[str, Any]]:
        """Executes full audit matrix across all components and display profiles."""
        catalog = self.get_component_catalog()
        self.results = []

        print("\n" + "=" * 70)
        print("  OPENING FENIX - AUTOMATED MULTI-DISPLAY OVERFLOW HARNESS")
        print("=" * 70)
        print(f"Testing Profiles: {', '.join(self.test_profiles)}")
        print(f"Total Components to Audit: {len(catalog)}")
        print("=" * 70)

        for prof_key in self.test_profiles:
            set_emulation_profile(prof_key)
            avail_w, avail_h = get_available_geometry()
            prof_meta = DISPLAY_PROFILES.get(prof_key, {})
            prof_name = prof_meta.get("name", prof_key)

            print(f"\n>>> AUDITING DISPLAY PROFILE: [{prof_name}]")
            print(f"    Available Viewport: {avail_w}x{avail_h}px | Scale Factor: {scaler.factor:.3f}")
            print("-" * 70)

            for comp_key, comp_title, factory in catalog:
                try:
                    # Invalidate scale cache and re-render under emulated profile
                    scaler._scale_factor = None
                    inst = factory()
                    res = self.inspect_widget(inst, comp_key, comp_title, prof_key, avail_w, avail_h)
                    self.results.append(res)
                    
                    # Print CLI summary per component
                    status_badge = f"[{res['severity']}]"
                    if res['severity'] == "PASS":
                        print(f"  OK   {comp_title:<36} Size: {res['cur_w']}x{res['cur_h']} | Min: {res['min_w']}x{res['min_h']}")
                    elif res['severity'] == "WARNING":
                        print(f"  WARN {comp_title:<36} {status_badge} ({len(res['issues'])} warnings)")
                        for iss in res['issues']:
                            print(f"        -> {iss['msg']}")
                    else:
                        print(f"  FAIL {comp_title:<36} {status_badge} ({len(res['issues'])} issues)")
                        for iss in res['issues']:
                            print(f"        -> [CRITICAL] {iss['msg']}")

                    inst.close()
                    inst.deleteLater()
                    self.app.processEvents()

                except Exception as e:
                    print(f"  ERR  {comp_title:<36} Exception during audit: {e}")
                    self.results.append({
                        "key": comp_key,
                        "title": comp_title,
                        "profile": prof_key,
                        "severity": "CRITICAL",
                        "issues": [{"type": "EXCEPTION", "severity": "CRITICAL", "msg": str(e)}],
                        "available_w": avail_w,
                        "available_h": avail_h,
                    })

        reset_emulation()
        return self.results

    def generate_html_report(self, output_path: Optional[str] = None) -> str:
        """Generates an interactive, styled HTML dashboard of the audit findings."""
        if not output_path:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            output_path = os.path.join(OUTPUT_DIR, "index.html")

        total_checks = len(self.results)
        critical_count = sum(1 for r in self.results if r["severity"] == "CRITICAL")
        warning_count = sum(1 for r in self.results if r["severity"] == "WARNING")
        pass_count = sum(1 for r in self.results if r["severity"] == "PASS")

        cards_html = []
        for r in self.results:
            badge_class = "badge-pass" if r["severity"] == "PASS" else ("badge-crit" if r["severity"] == "CRITICAL" else "badge-warn")
            prof_name = DISPLAY_PROFILES.get(r["profile"], {}).get("name", r["profile"])
            
            issues_list_html = ""
            if r["issues"]:
                issues_list_html = "<ul class='issues-list'>" + "".join(
                    f"<li class='issue-{iss['severity'].lower()}'><strong>[{iss['type']}]</strong> {iss['msg']}</li>"
                    for iss in r["issues"]
                ) + "</ul>"
            else:
                issues_list_html = "<p class='no-issues'>Perfect viewport fit. No clipping or button cutoff detected.</p>"

            board_html = ""
            if r.get("board_info"):
                bi = r["board_info"]
                board_html = f"<div class='board-stat'>Chessboard: {bi['side_px']}px (Square: {bi['square_px']:.1f}px) - {'Playable' if bi['playable'] else 'CRUSHED'}</div>"

            card = f"""
            <div class="audit-card {r['severity'].lower()}" data-severity="{r['severity']}" data-profile="{r['profile']}">
                <div class="card-header">
                    <div>
                        <span class="comp-title">{r['title']}</span>
                        <span class="profile-tag">{prof_name}</span>
                    </div>
                    <span class="badge {badge_class}">{r['severity']}</span>
                </div>
                <div class="card-metrics">
                    <div class="metric"><span class="m-lbl">Screen Viewport</span><span class="m-val">{r['available_w']} × {r['available_h']}</span></div>
                    <div class="metric"><span class="m-lbl">Current Size</span><span class="m-val">{r.get('cur_w', 0)} × {r.get('cur_h', 0)}</span></div>
                    <div class="metric"><span class="m-lbl">Minimum Size</span><span class="m-val">{r.get('min_w', 0)} × {r.get('min_h', 0)}</span></div>
                    <div class="metric"><span class="m-lbl">Scale Factor</span><span class="m-val">{r.get('scale_factor', 1.0):.2f}x</span></div>
                </div>
                {board_html}
                {issues_list_html}
            </div>
            """
            cards_html.append(card)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Opening Fenix — Multi-Display Overflow & Visual Audit</title>
    <style>
        :root {{
            --bg: #121417;
            --surface: #1e2227;
            --border: #2d333b;
            --text: #e6edf3;
            --text-dim: #8b949e;
            --crit: #f85149;
            --crit-bg: rgba(248, 81, 73, 0.15);
            --warn: #d29922;
            --warn-bg: rgba(210, 153, 34, 0.15);
            --pass: #3fb950;
            --pass-bg: rgba(63, 185, 80, 0.15);
            --accent: #58a6ff;
        }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
        }}
        .header {{
            max-width: 1200px;
            margin: 0 auto 24px auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
        }}
        h1 {{ margin: 0; font-size: 24px; font-weight: 600; }}
        .subtitle {{ color: var(--text-dim); font-size: 14px; margin-top: 4px; }}
        .stats-bar {{
            display: flex;
            gap: 16px;
        }}
        .stat-box {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 18px;
            text-align: center;
        }}
        .stat-num {{ font-size: 22px; font-weight: 700; display: block; }}
        .stat-num.crit {{ color: var(--crit); }}
        .stat-num.warn {{ color: var(--warn); }}
        .stat-num.pass {{ color: var(--pass); }}
        .stat-lbl {{ font-size: 12px; color: var(--text-dim); text-transform: uppercase; }}
        .filter-bar {{
            max-width: 1200px;
            margin: 0 auto 20px auto;
            display: flex;
            gap: 10px;
        }}
        .filter-btn {{
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.15s ease;
        }}
        .filter-btn.active {{
            background: var(--accent);
            color: #fff;
            border-color: var(--accent);
        }}
        .grid {{
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(580px, 1fr));
            gap: 16px;
        }}
        .audit-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .audit-card.critical {{ border-color: var(--crit); }}
        .audit-card.warning {{ border-color: var(--warn); }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}
        .comp-title {{ font-size: 16px; font-weight: 600; display: block; }}
        .profile-tag {{
            font-size: 12px;
            color: var(--accent);
            background: rgba(88, 166, 255, 0.1);
            padding: 2px 8px;
            border-radius: 4px;
            margin-top: 4px;
            display: inline-block;
        }}
        .badge {{
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}
        .badge-pass {{ background: var(--pass-bg); color: var(--pass); }}
        .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
        .badge-crit {{ background: var(--crit-bg); color: var(--crit); }}
        .card-metrics {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            background: rgba(0,0,0,0.2);
            border-radius: 6px;
            padding: 8px;
        }}
        .metric {{ text-align: center; }}
        .m-lbl {{ font-size: 10px; color: var(--text-dim); display: block; }}
        .m-val {{ font-size: 13px; font-weight: 600; margin-top: 2px; }}
        .board-stat {{
            font-size: 12px;
            background: rgba(255,255,255,0.05);
            padding: 6px 10px;
            border-radius: 4px;
            color: #d1d5db;
        }}
        .issues-list {{
            margin: 0;
            padding-left: 20px;
            font-size: 13px;
            line-height: 1.5;
        }}
        .issue-critical {{ color: var(--crit); }}
        .issue-warning {{ color: var(--warn); }}
        .no-issues {{
            margin: 0;
            color: var(--pass);
            font-size: 13px;
        }}
    </style>
    <script>
        function filterCards(severity) {{
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.audit-card').forEach(c => {{
                if (severity === 'ALL' || c.getAttribute('data-severity') === severity) {{
                    c.style.display = 'flex';
                }} else {{
                    c.style.display = 'none';
                }}
            }});
        }}
    </script>
</head>
<body>
    <div class="header">
        <div>
            <h1>Opening Fenix — Multi-Display Overflow Audit</h1>
            <div class="subtitle">Simulated layout testing across HD 768p, Full HD Laptop (125% DPI), and Desktop monitors</div>
        </div>
        <div class="stats-bar">
            <div class="stat-box"><span class="stat-num">{total_checks}</span><span class="stat-lbl">Audits</span></div>
            <div class="stat-box"><span class="stat-num crit">{critical_count}</span><span class="stat-lbl">Critical</span></div>
            <div class="stat-box"><span class="stat-num warn">{warning_count}</span><span class="stat-lbl">Warnings</span></div>
            <div class="stat-box"><span class="stat-num pass">{pass_count}</span><span class="stat-lbl">Passed</span></div>
        </div>
    </div>

    <div class="filter-bar">
        <button class="filter-btn active" onclick="filterCards('ALL')">All Results ({total_checks})</button>
        <button class="filter-btn" onclick="filterCards('CRITICAL')">Critical Overflows ({critical_count})</button>
        <button class="filter-btn" onclick="filterCards('WARNING')">Warnings ({warning_count})</button>
        <button class="filter-btn" onclick="filterCards('PASS')">Passed ({pass_count})</button>
    </div>

    <div class="grid">
        {"".join(cards_html)}
    </div>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        print(f"\n[HTML REPORT] Generated at: {output_path}")
        return output_path


def main():
    parser = argparse.ArgumentParser(description="Opening Fenix Multi-Display Overflow Test Harness")
    parser.add_argument("--profiles", nargs="+", default=["768p", "1080p_laptop", "1080p"],
                        help="List of profiles to test (e.g. 768p 1080p_laptop 1080p 1440p 4k)")
    parser.add_argument("--html", action="store_true", default=True, help="Generate HTML report")
    parser.add_argument("--fail-on-critical", action="store_true", help="Exit with code 1 if critical issues found")
    args = parser.parse_args()

    harness = DisplayOverflowHarness(profiles=args.profiles)
    results = harness.run_audit()

    if args.html:
        harness.generate_html_report()

    crit_count = sum(1 for r in results if r["severity"] == "CRITICAL")
    warn_count = sum(1 for r in results if r["severity"] == "WARNING")

    print("\n" + "=" * 70)
    print(f"  AUDIT SUMMARY: {crit_count} Critical Overflows, {warn_count} Layout Warnings")
    print("=" * 70)

    if crit_count > 0 and args.fail_on_critical:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
