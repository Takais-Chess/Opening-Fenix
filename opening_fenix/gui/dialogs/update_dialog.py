import os
import sys
import subprocess
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QProgressBar, QMenu, QWidget, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QAction, QColor

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon
from opening_fenix.core.translation import tr_ui
from opening_fenix.core.version import APP_VERSION
from opening_fenix.core.services.update_service import (
    DownloaderWorker, set_snooze_period
)
from opening_fenix.core.logger import logger

class UpdateDialog(QDialog):
    """
    Stylized popup dialog notifying the user about a new app version available on GitHub.
    Provides in-app downloading with progress bar and snooze/reminder options.
    """
    def __init__(self, release_info: dict, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.downloader_worker = None
        self.downloaded_installer_path = None

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(tr_ui("update.window_title", "Opening Fenix - Update verfügbar"))
        self.setMinimumSize(scale(640), scale(520))
        set_consistent_icon(self)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))
        layout.setSpacing(scale(18))

        # Title / Header
        remote_v = self.release_info.get("version", "")
        title_text = self.release_info.get("title", f"Version {remote_v}")
        
        lbl_title = QLabel(f"🎉 {title_text}")
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(22)}px; font-weight: 900;")
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(
            tr_ui("update.version_sub", "Eine neue Version ist verfügbar. (Deine Version: {current_v} ➔ Neu: {remote_v})", 
                  current_v=APP_VERSION, remote_v=remote_v)
        )
        lbl_sub.setStyleSheet("color: #666; font-size: 14px; font-weight: bold;")
        layout.addWidget(lbl_sub)

        # Release Notes Display Box
        lbl_notes_hdr = QLabel(tr_ui("update.release_notes_hdr", "📋 Neuerungen & Änderungen:"))
        lbl_notes_hdr.setStyleSheet(f"color: {COLORS['brown_text']}; font-weight: bold; font-size: 14px;")
        layout.addWidget(lbl_notes_hdr)

        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        body_text = self.release_info.get("body", "").strip() or tr_ui("update.no_notes", "Keine Versionshinweise angegeben.")
        self.txt_notes.setPlainText(body_text)
        self.txt_notes.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['glass_bg']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(10)}px;
                padding: {scale(12)}px;
                color: {COLORS['brown_text']};
                font-size: {scale(13)}px;
                line-height: 1.4;
            }}
        """)
        layout.addWidget(self.txt_notes, 1)

        # Progress bar layout (hidden initially)
        self.progress_container = QWidget()
        v_prog = QVBoxLayout(self.progress_container)
        v_prog.setContentsMargins(0, 0, 0, 0)
        v_prog.setSpacing(scale(6))

        self.lbl_progress_status = QLabel(tr_ui("update.downloading", "Wird heruntergeladen..."))
        self.lbl_progress_status.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: 13px; font-weight: bold;")
        v_prog.addWidget(self.lbl_progress_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                text-align: center;
                background: white;
                height: {scale(22)}px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['burnt_orange']};
                border-radius: {scale(7)}px;
            }}
        """)
        v_prog.addWidget(self.progress_bar)
        self.progress_container.hide()
        layout.addWidget(self.progress_container)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(scale(12))

        # Remind dropdown button
        self.btn_snooze = QPushButton(tr_ui("update.btn_snooze", "⏳ Später erinnern ▼"))
        self.btn_snooze.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_snooze.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: #555;
                border: 1px solid rgba(0,0,0,0.2);
                border-radius: {scale(18)}px;
                font-weight: bold;
                padding: {scale(10)}px {scale(20)}px;
            }}
            QPushButton:hover {{ background-color: #f5f5f5; border-color: #999; }}
        """)
        self.setup_snooze_menu()
        btn_layout.addWidget(self.btn_snooze)

        btn_layout.addStretch()

        # Primary download button
        self.btn_download = QPushButton(tr_ui("update.btn_download", "⬇️ Jetzt herunterladen & installieren"))
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(18)}px;
                font-weight: bold;
                padding: {scale(10)}px {scale(25)}px;
                font-size: {scale(14)}px;
            }}
            QPushButton:hover {{ background-color: #e67e22; }}
            QPushButton:disabled {{ background-color: #ccc; }}
        """)
        self.btn_download.clicked.connect(self.on_download_clicked)
        btn_layout.addWidget(self.btn_download)

        layout.addLayout(btn_layout)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['beige']}; }}")

    def setup_snooze_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: white;
                border: 1px solid rgba(0,0,0,0.15);
                border-radius: {scale(8)}px;
                padding: {scale(4)}px;
            }}
            QMenu::item {{
                padding: {scale(8)}px {scale(16)}px;
                font-size: {scale(13)}px;
                color: {COLORS['brown_text']};
            }}
            QMenu::item:selected {{
                background-color: {COLORS['beige']};
                color: {COLORS['burnt_orange']};
            }}
        """)

        act_next = QAction(tr_ui("update.snooze_next_start", "Beim nächsten Start"), self)
        act_next.triggered.connect(lambda: self.apply_snooze("next_start"))
        menu.addAction(act_next)

        act_week = QAction(tr_ui("update.snooze_1_week", "In 1 Woche"), self)
        act_week.triggered.connect(lambda: self.apply_snooze("1_week"))
        menu.addAction(act_week)

        act_month = QAction(tr_ui("update.snooze_1_month", "In 1 Monat"), self)
        act_month.triggered.connect(lambda: self.apply_snooze("1_month"))
        menu.addAction(act_month)

        act_year = QAction(tr_ui("update.snooze_1_year", "In 1 Jahr"), self)
        act_year.triggered.connect(lambda: self.apply_snooze("1_year"))
        menu.addAction(act_year)

        menu.addSeparator()

        act_ignore = QAction(tr_ui("update.snooze_ignore", "Diese Version ignorieren"), self)
        act_ignore.triggered.connect(lambda: self.apply_snooze("ignore"))
        menu.addAction(act_ignore)

        self.btn_snooze.setMenu(menu)

    def apply_snooze(self, snooze_type: str):
        tag_name = self.release_info.get("version", "")
        set_snooze_period(snooze_type, tag_name)
        self.accept()

    def on_download_clicked(self):
        if self.downloaded_installer_path and os.path.exists(self.downloaded_installer_path):
            self.launch_installer_and_exit()
            return

        download_url = self.release_info.get("download_url")
        asset_name = self.release_info.get("asset_name") or f"OpeningFenix_Setup_{self.release_info.get('version', '')}.exe"

        if not download_url:
            # Fall back to opening GitHub release page in browser
            html_url = self.release_info.get("html_url", "")
            if html_url:
                QDesktopServices.openUrl(QUrl(html_url))
            self.accept()
            return

        # Start in-app download
        self.btn_download.setEnabled(False)
        self.btn_snooze.setEnabled(False)
        self.progress_container.show()
        self.lbl_progress_status.setText(tr_ui("update.starting_download", "Download wird gestartet..."))

        self.downloader_worker = DownloaderWorker(download_url, asset_name, self)
        self.downloader_worker.progress.connect(self.on_download_progress)
        self.downloader_worker.finished.connect(self.on_download_finished)
        self.downloader_worker.error.connect(self.on_download_error)
        self.downloader_worker.start()

    def on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(pct)
            mb_down = downloaded / (1024 * 1024)
            mb_tot = total / (1024 * 1024)
            self.lbl_progress_status.setText(
                tr_ui("update.progress_fmt", "Wird heruntergeladen... {mb_down:.1f} MB / {mb_tot:.1f} MB ({pct}%)",
                      mb_down=mb_down, mb_tot=mb_tot, pct=pct)
            )
        else:
            self.progress_bar.setValue(0)
            mb_down = downloaded / (1024 * 1024)
            self.lbl_progress_status.setText(
                tr_ui("update.progress_unknown", "Wird heruntergeladen... {mb_down:.1f} MB", mb_down=mb_down)
            )

    def on_download_finished(self, local_path: str):
        self.downloaded_installer_path = local_path
        self.lbl_progress_status.setText(tr_ui("update.download_success", "Download erfolgreich abgeschlossen!"))
        self.progress_bar.setValue(100)
        self.btn_download.setEnabled(True)
        self.btn_download.setText(tr_ui("update.btn_install_now", "🚀 Jetzt installieren & neu starten"))
        self.btn_download.setStyleSheet(f"""
            QPushButton {{
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: {scale(18)}px;
                font-weight: bold;
                padding: {scale(10)}px {scale(25)}px;
                font-size: {scale(14)}px;
            }}
            QPushButton:hover {{ background-color: #2ea043; }}
        """)

    def on_download_error(self, err_msg: str):
        self.lbl_progress_status.setText(tr_ui("update.download_failed", "Download fehlgeschlagen: {err}", err=err_msg))
        self.lbl_progress_status.setStyleSheet("color: #e74c3c; font-size: 13px; font-weight: bold;")
        self.btn_download.setEnabled(True)
        self.btn_snooze.setEnabled(True)
        self.btn_download.setText(tr_ui("update.btn_retry_browser", "🌐 Im Browser herunterladen"))
        # Switch fallback click behavior to browser link
        self.release_info["download_url"] = None

    def launch_installer_and_exit(self):
        if self.downloaded_installer_path and os.path.exists(self.downloaded_installer_path):
            try:
                logger.info(f"Launching installer silently: {self.downloaded_installer_path}")
                subprocess.Popen([self.downloaded_installer_path, "/SILENT", "/SUPPRESSMSGBOXES"])
                QApplication.quit()
            except Exception as e:
                logger.error(f"Failed to launch installer: {e}")
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.downloaded_installer_path))
                self.accept()
        else:
            self.accept()

    def closeEvent(self, event):
        if self.downloader_worker and self.downloader_worker.isRunning():
            self.downloader_worker.cancel()
            self.downloader_worker.wait()
        super().closeEvent(event)
