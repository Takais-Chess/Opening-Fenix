import datetime
import io
import json
import os
import platform
import re
import sys
import zipfile

import requests
from PyQt6.QtCore import Qt, QThread, QUrl, PYQT_VERSION_STR, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from opening_fenix.core.logger import logger
from opening_fenix.core.services.update_service import get_config_dict
from opening_fenix.core.translation import tr_ui, tr_widget
from opening_fenix.core.utils import get_user_dir
from opening_fenix.core.version import APP_VERSION
from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, get_indicator_style

BUG_REPORT_ENDPOINT = "https://opening-fenix-bugs.felix-brunner12.workers.dev"
GITHUB_ISSUES_URL = "https://github.com/Takais-Chess/Opening-Fenix/issues/new"
DISCORD_INVITE_URL = "https://discord.gg/TevW5Wfkc"

_SENSITIVE_KEY_TOKENS = ("token", "secret", "password", "passwd", "api_key", "apikey", "auth")
_LICHESS_TOKEN_RE = re.compile(r"\blip_[A-Za-z0-9_-]{8,}\b")
_BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._-]{8,}", re.IGNORECASE)


def sanitize_config_for_diagnostics(cfg: dict) -> dict:
    """Returns a deep-sanitized copy of config.json with tokens/secrets redacted."""
    if not isinstance(cfg, dict):
        return {}
    sanitized = {}
    for k, v in cfg.items():
        key_lower = str(k).lower()
        if any(tok in key_lower for tok in _SENSITIVE_KEY_TOKENS):
            sanitized[k] = "[REDACTED]" if v else ""
        elif isinstance(v, dict):
            sanitized[k] = sanitize_config_for_diagnostics(v)
        elif isinstance(v, str):
            cleaned = _LICHESS_TOKEN_RE.sub("lip_[REDACTED]", v)
            cleaned = _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", cleaned)
            sanitized[k] = cleaned
        else:
            sanitized[k] = v
    return sanitized


def sanitize_log_text(text: str) -> str:
    """Scrubs known API tokens and bearer credentials from log output."""
    if not text:
        return ""
    cleaned = _LICHESS_TOKEN_RE.sub("lip_[REDACTED]", text)
    cleaned = _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", cleaned)
    return cleaned


def collect_system_info(window=None) -> dict:
    """Collects non-sensitive environment & display diagnostics."""
    info = {
        "app_version": APP_VERSION,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "pyqt_version": PYQT_VERSION_STR,
        "active_window": type(window).__name__ if window is not None else None,
    }
    try:
        cfg = get_config_dict()
        info["ui_language"] = cfg.get("ui_language", "de")
        info["notation_language"] = cfg.get("notation_language", "en")
        info["theme"] = cfg.get("theme", "Braun (Klassisch)")
    except Exception:
        pass

    try:
        app = QApplication.instance()
        screen = None
        if window is not None and hasattr(window, "screen"):
            screen = window.screen()
        if screen is None and app is not None:
            screen = app.primaryScreen()
        if screen is not None:
            geom = screen.geometry()
            info["screen_resolution"] = f"{geom.width()}x{geom.height()}"
            info["device_pixel_ratio"] = round(float(screen.devicePixelRatio()), 2)
    except Exception:
        pass

    return info


def read_sanitized_log_tail(max_bytes: int = 512 * 1024) -> str:
    """Reads up to `max_bytes` from the end of app.log and scrubs sensitive tokens."""
    log_path = os.path.join(get_user_dir(), "app.log")
    if not os.path.exists(log_path):
        return ""
    try:
        file_size = os.path.getsize(log_path)
        with open(log_path, "rb") as f:
            if file_size > max_bytes:
                f.seek(file_size - max_bytes)
                raw = f.read()
                nl = raw.find(b"\n")
                if nl != -1:
                    raw = raw[nl + 1:]
            else:
                raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        return sanitize_log_text(text)
    except Exception as e:
        logger.warning(f"Failed reading app.log for diagnostics: {e}")
        return f"[Could not read app.log: {e}]"


def build_diagnostics_zip_bytes(
    user_description: str = "",
    window=None,
    max_log_bytes: int = 512 * 1024,
) -> tuple[bytes, dict]:
    """Builds a sanitized diagnostics ZIP in memory and returns (zip_bytes, sys_info)."""
    sys_info = collect_system_info(window=window)
    try:
        raw_cfg = get_config_dict()
    except Exception:
        raw_cfg = {}
    safe_cfg = sanitize_config_for_diagnostics(raw_cfg)
    log_tail = read_sanitized_log_tail(max_bytes=max_log_bytes)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system_info.json", json.dumps(sys_info, indent=2, ensure_ascii=False))
        zf.writestr("config_sanitized.json", json.dumps(safe_cfg, indent=2, ensure_ascii=False))
        if user_description and user_description.strip():
            zf.writestr("user_report.txt", user_description.strip() + "\n")
        zf.writestr("app_log_tail.txt", log_tail or "[app.log is empty or not found]\n")

    return buf.getvalue(), sys_info


def export_diagnostics_zip(
    output_path: str,
    user_description: str = "",
    window=None,
    max_log_bytes: int = 512 * 1024,
) -> str:
    """Writes a sanitized diagnostics ZIP bundle to disk."""
    zip_bytes, _ = build_diagnostics_zip_bytes(
        user_description=user_description,
        window=window,
        max_log_bytes=max_log_bytes,
    )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(zip_bytes)
    return output_path


def submit_bug_report(
    user_description: str = "",
    window=None,
    include_diagnostics: bool = True,
    endpoint: str = BUG_REPORT_ENDPOINT,
    timeout: int = 15,
) -> tuple[bool, str]:
    """Submits a bug report (with optional sanitized diagnostics ZIP) to the Cloudflare Worker."""
    sys_info = collect_system_info(window=window)
    files = None
    if include_diagnostics:
        zip_bytes, sys_info = build_diagnostics_zip_bytes(
            user_description=user_description,
            window=window,
        )
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        files = {
            "file": (f"OpeningFenix_Diagnostics_{stamp}.zip", zip_bytes, "application/zip"),
        }

    data = {
        "description": (user_description or "").strip()[:1800],
        "system_info": json.dumps(sys_info, ensure_ascii=False),
    }

    try:
        resp = requests.post(endpoint, data=data, files=files, timeout=timeout)
    except requests.RequestException as e:
        logger.warning(f"Bug report network error: {e}")
        return False, str(e)

    if resp.status_code == 429:
        return False, tr_ui(
            "bug_report.rate_limited",
            "Zu viele Berichte in kurzer Zeit. Bitte versuche es später erneut oder speichere das Diagnose-ZIP lokal.",
        )

    try:
        payload = resp.json()
    except Exception:
        payload = {}

    if resp.ok and payload.get("ok", True):
        return True, ""

    err = payload.get("error") or f"HTTP {resp.status_code}"
    return False, str(err)


class _BugReportUploadThread(QThread):
    finished_result = pyqtSignal(bool, str)

    def __init__(self, description: str, include_diagnostics: bool, source_window=None, parent=None):
        super().__init__(parent)
        self._description = description
        self._include_diagnostics = include_diagnostics
        self._source_window = source_window

    def run(self):
        ok, err = submit_bug_report(
            user_description=self._description,
            window=self._source_window,
            include_diagnostics=self._include_diagnostics,
        )
        self.finished_result.emit(ok, err)


class BugReportDialog(QDialog):
    """Compact dialog for 1-click bug reporting with automatic fallback to local diagnostics ZIP."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_window = parent
        self._upload_thread = None
        self.setWindowTitle(tr_ui("bug_report.title", "Fehler melden & Diagnose"))
        self.setMinimumWidth(scale(490))
        self.setModal(True)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: #faf7f2;
                color: {COLORS['brown_text']};
            }}
            QLabel {{
                color: {COLORS['brown_text']};
                background: transparent;
            }}
            QCheckBox {{
                color: {COLORS['brown_text']};
                font-size: {scale(12)}px;
                background: transparent;
            }}
            QPlainTextEdit {{
                background-color: #ffffff;
                border: 1px solid #d6ccc2;
                border-radius: {scale(8)}px;
                padding: {scale(8)}px;
                font-size: {scale(13)}px;
                color: {COLORS['brown_text']};
            }}
            QPlainTextEdit:focus {{
                border: 1px solid {COLORS['burnt_orange']};
            }}
            QPushButton#PrimaryDiagBtn {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(8)}px;
                padding: {scale(9)}px {scale(16)}px;
                font-weight: bold;
                font-size: {scale(13)}px;
            }}
            QPushButton#PrimaryDiagBtn:hover {{
                background-color: #c25e00;
            }}
            QPushButton#PrimaryDiagBtn:disabled {{
                background-color: #d6ccc2;
                color: #7c6f64;
            }}
            QPushButton#SecondaryDiagBtn {{
                background-color: #ffffff;
                color: {COLORS['brown_text']};
                border: 1px solid #d6ccc2;
                border-radius: {scale(8)}px;
                padding: {scale(7)}px {scale(11)}px;
                font-weight: 600;
                font-size: {scale(12)}px;
            }}
            QPushButton#SecondaryDiagBtn:hover {{
                background-color: #f3ede4;
                border-color: #b58863;
            }}
            {get_indicator_style()}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(20), scale(18), scale(20), scale(18))
        layout.setSpacing(scale(11))

        lbl_title = QLabel(tr_ui("bug_report.heading", "Fehler melden & Diagnose"))
        lbl_title.setStyleSheet(f"font-size: {scale(16)}px; font-weight: bold;")
        layout.addWidget(lbl_title)

        lbl_intro = QLabel(
            tr_ui(
                "bug_report.intro",
                "Beschreibe kurz, was passiert ist, und sende den Bericht mit einem Klick direkt an das Entwicklerteam. "
                "Persönliche API-Tokens werden automatisch entfernt."
            )
        )
        lbl_intro.setWordWrap(True)
        lbl_intro.setStyleSheet(f"font-size: {scale(12)}px; color: #6b5b4e;")
        layout.addWidget(lbl_intro)

        lbl_desc = QLabel(tr_ui("bug_report.desc_label", "Was ist passiert?"))
        lbl_desc.setStyleSheet(f"font-size: {scale(12)}px; font-weight: 600;")
        layout.addWidget(lbl_desc)

        self.txt_description = QPlainTextEdit()
        self.txt_description.setPlaceholderText(
            tr_ui("bug_report.desc_placeholder", "Kurze Beschreibung oder Schritte zum Reproduzieren...")
        )
        self.txt_description.setMinimumHeight(scale(105))
        layout.addWidget(self.txt_description, 1)

        self.chk_include_diag = QCheckBox(
            tr_widget(
                "bug_report.chk_include_diag",
                "Diagnose-ZIP anhängen (App-Version, System-Infos & bereinigtes Log)"
            )
        )
        self.chk_include_diag.setChecked(True)
        layout.addWidget(self.chk_include_diag)

        # Primary 1-click submit button
        self.btn_send = QPushButton(tr_ui("bug_report.btn_send", "🚀 Fehlerbericht senden"))
        self.btn_send.setObjectName("PrimaryDiagBtn")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self.on_send_clicked)
        layout.addWidget(self.btn_send)

        # Bottom row: offline ZIP fallback + community links + close
        links_row = QHBoxLayout()
        links_row.setSpacing(scale(8))

        self.btn_export = QPushButton(tr_ui("bug_report.btn_export_short", "📦 ZIP speichern"))
        self.btn_export.setObjectName("SecondaryDiagBtn")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.clicked.connect(self.on_export_clicked)
        links_row.addWidget(self.btn_export)

        self.btn_github = QPushButton(tr_ui("bug_report.btn_github", "GitHub"))
        self.btn_github.setObjectName("SecondaryDiagBtn")
        self.btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_ISSUES_URL)))
        links_row.addWidget(self.btn_github)

        self.btn_discord = QPushButton(tr_ui("bug_report.btn_discord", "Discord"))
        self.btn_discord.setObjectName("SecondaryDiagBtn")
        self.btn_discord.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_discord.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL)))
        links_row.addWidget(self.btn_discord)

        links_row.addStretch()

        self.btn_close = QPushButton(tr_ui("common.close", "Schließen"))
        self.btn_close.setObjectName("SecondaryDiagBtn")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)
        links_row.addWidget(self.btn_close)

        layout.addLayout(links_row)

    def on_send_clicked(self):
        desc = self.txt_description.toPlainText().strip()
        if not desc and not self.chk_include_diag.isChecked():
            QMessageBox.information(
                self,
                tr_ui("bug_report.empty_title", "Beschreibung fehlt"),
                tr_ui(
                    "bug_report.empty_msg",
                    "Bitte gib eine kurze Beschreibung ein oder aktiviere das Diagnose-ZIP."
                ),
            )
            return

        self.btn_send.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_send.setText(tr_ui("bug_report.btn_sending", "⏳ Wird gesendet..."))

        self._upload_thread = _BugReportUploadThread(
            description=desc,
            include_diagnostics=self.chk_include_diag.isChecked(),
            source_window=self._source_window,
            parent=self,
        )
        self._upload_thread.finished_result.connect(self._on_upload_finished)
        self._upload_thread.start()

    def _on_upload_finished(self, ok: bool, err: str):
        self.btn_send.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_send.setText(tr_ui("bug_report.btn_send", "🚀 Fehlerbericht senden"))

        if ok:
            QMessageBox.information(
                self,
                tr_ui("bug_report.send_success_title", "Bericht gesendet"),
                tr_ui(
                    "bug_report.send_success_msg",
                    "Vielen Dank! Dein Fehlerbericht wurde erfolgreich übermittelt."
                ),
            )
            self.accept()
        else:
            QMessageBox.warning(
                self,
                tr_ui("bug_report.send_error_title", "Senden fehlgeschlagen"),
                tr_ui(
                    "bug_report.send_error_msg",
                    "Der Bericht konnte nicht direkt gesendet werden ({error}).\n\n"
                    "Du kannst stattdessen auf '📦 ZIP speichern' klicken und die Datei auf Discord oder GitHub teilen."
                ).format(error=err),
            )

    def on_export_clicked(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"OpeningFenix_Diagnostics_{stamp}.zip"
        default_dir = os.path.expanduser("~/Desktop")
        if not os.path.isdir(default_dir):
            default_dir = get_user_dir()
        suggested = os.path.join(default_dir, default_name)

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr_ui("bug_report.save_dialog_title", "Diagnose-ZIP speichern"),
            suggested,
            "ZIP Archive (*.zip)",
        )
        if not out_path:
            return
        if not out_path.lower().endswith(".zip"):
            out_path += ".zip"

        try:
            export_diagnostics_zip(
                output_path=out_path,
                user_description=self.txt_description.toPlainText(),
                window=self._source_window,
            )
            QMessageBox.information(
                self,
                tr_ui("bug_report.export_success_title", "Diagnose gespeichert"),
                tr_ui(
                    "bug_report.export_success_msg",
                    "Diagnose-Paket wurde erfolgreich gespeichert:\n{path}"
                ).format(path=out_path),
            )
        except Exception as e:
            logger.error(f"Diagnostics export failed: {e}")
            QMessageBox.warning(
                self,
                tr_ui("bug_report.export_error_title", "Fehler beim Export"),
                tr_ui(
                    "bug_report.export_error_msg",
                    "Das Diagnose-Paket konnte nicht erstellt werden:\n{error}"
                ).format(error=str(e)),
            )
