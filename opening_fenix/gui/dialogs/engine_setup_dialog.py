import os
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QProgressBar, QFileDialog, QWidget, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon, get_bw_glass_style
from opening_fenix.core.translation import tr_ui, tr_widget
from opening_fenix.core.services.engine_downloader_service import (
    StockfishDownloaderWorker, is_engine_valid, get_engines_dir
)
from opening_fenix.core.services.update_service import get_config_dict, save_config_dict


class EngineActionDialog(QDialog):
    """
    Actionable choice dialog presented when a chess engine is required but not configured.
    Offers 1-click automatic download of Stockfish or selecting a local engine executable.
    """
    ACTION_DOWNLOAD = 1
    ACTION_BROWSE = 2
    ACTION_CANCEL = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_action = self.ACTION_CANCEL

        self.setWindowTitle(tr_ui("engine_setup.dialog_title", "🤖 Schach-Engine einrichten"))
        self.setMinimumSize(scale(560), scale(460))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        set_consistent_icon(self)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(scale(24), scale(24), scale(24), scale(20))
        layout.setSpacing(scale(16))

        # Header Title
        lbl_title = QLabel(tr_ui("engine_setup.header_title", "Keine Schach-Engine eingerichtet"))
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(20)}px; font-weight: 900;")
        layout.addWidget(lbl_title)

        # Description
        lbl_desc = QLabel(
            tr_ui(
                "engine_setup.header_desc",
                "Für Stellungsanalysen, Zugbewertungen und die automatische Fehlersuche (Hole Finder) "
                "wird eine UCI-fähige Schach-Engine wie Stockfish benötigt.\n\n"
                "Wie möchtest du fortfahren?"
            )
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(13)}px; line-height: 1.4;")
        layout.addWidget(lbl_desc)

        # Card 1: Download Option
        dl_layout = QVBoxLayout()
        dl_layout.setContentsMargins(0, 0, 0, 0)
        dl_layout.setSpacing(scale(4))

        btn_download = QPushButton(tr_ui("engine_setup.btn_download", "⚡ Stockfish automatisch herunterladen (Empfohlen)"))
        btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_download.setMinimumHeight(scale(48))
        btn_download.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(10)}px;
                font-weight: bold;
                padding: {scale(12)}px {scale(16)}px;
                font-size: {scale(14)}px;
                text-align: left;
            }}
            QPushButton:hover {{ background-color: #e67e22; }}
        """)
        btn_download.clicked.connect(self._on_download_clicked)
        dl_layout.addWidget(btn_download)

        lbl_dl_hint = QLabel(tr_ui("engine_setup.download_hint", "Lädt die offizielle Universal-Version (~81 MB) direkt von GitHub herunter. 1-Klick Setup, keine manuelle Konfiguration."))
        lbl_dl_hint.setWordWrap(True)
        lbl_dl_hint.setStyleSheet(f"color: #777; font-size: {scale(11)}px; margin-left: {scale(8)}px;")
        dl_layout.addWidget(lbl_dl_hint)
        layout.addLayout(dl_layout)

        # Card 2: Browse Local Option
        browse_layout = QVBoxLayout()
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setSpacing(scale(4))

        btn_browse = QPushButton(tr_ui("engine_setup.btn_browse", "📁 Vorhandene lokale Engine auswählen (.exe)"))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setMinimumHeight(scale(48))
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {COLORS['brown_text']};
                border: 1px solid rgba(0,0,0,0.2);
                border-radius: {scale(10)}px;
                font-weight: bold;
                padding: {scale(12)}px {scale(16)}px;
                font-size: {scale(13)}px;
                text-align: left;
            }}
            QPushButton:hover {{ background-color: #f8f8f8; border-color: #999; }}
        """)
        btn_browse.clicked.connect(self._on_browse_clicked)
        browse_layout.addWidget(btn_browse)

        lbl_browse_hint = QLabel(tr_ui("engine_setup.browse_hint", "Wähle eine bereits installierte Engine auf deiner Festplatte (z.B. Stockfish, Leela Chess Zero, Komodo)."))
        lbl_browse_hint.setWordWrap(True)
        lbl_browse_hint.setStyleSheet(f"color: #777; font-size: {scale(11)}px; margin-left: {scale(8)}px;")
        browse_layout.addWidget(lbl_browse_hint)
        layout.addLayout(browse_layout)

        # Legal Note
        lbl_legal = QLabel(
            tr_ui(
                "engine_setup.legal_note",
                "ℹ️ Hinweis: Stockfish ist freie Open-Source-Software (GPLv3) vom Stockfish-Entwicklerteam. "
                "Der Download erfolgt direkt von official-stockfish/Stockfish."
            )
        )
        lbl_legal.setWordWrap(True)
        lbl_legal.setStyleSheet(f"color: #888; font-size: {scale(10)}px; margin-top: {scale(4)}px;")
        layout.addWidget(lbl_legal)

        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        btn_cancel = QPushButton(tr_ui("common.cancel", "Abbrechen"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #666;
                border: 1px solid rgba(0,0,0,0.15);
                border-radius: {scale(14)}px;
                padding: {scale(6)}px {scale(16)}px;
                font-size: {scale(12)}px;
            }}
            QPushButton:hover {{ background-color: rgba(0,0,0,0.05); color: #333; }}
        """)
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)

        layout.addLayout(bottom_layout)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['beige']}; }}")

    def _on_download_clicked(self):
        self.selected_action = self.ACTION_DOWNLOAD
        self.accept()

    def _on_browse_clicked(self):
        self.selected_action = self.ACTION_BROWSE
        self.accept()


class EngineDownloadProgressDialog(QDialog):
    """
    Modal dialog displaying the progress of downloading and extracting the official Stockfish binary.
    """
    def __init__(self, parent=None, target_dir: Optional[str] = None):
        super().__init__(parent)
        self.target_dir = target_dir
        self.worker: Optional[StockfishDownloaderWorker] = None
        self.engine_path: Optional[str] = None
        self.error_message: Optional[str] = None

        self.setWindowTitle(tr_ui("engine_setup.dl_window_title", "Stockfish herunterladen"))
        self.setFixedWidth(scale(480))
        set_consistent_icon(self)

        self.init_ui()
        self.start_download()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(24), scale(24), scale(24), scale(20))
        layout.setSpacing(scale(14))

        # Title
        self.lbl_title = QLabel(tr_ui("engine_setup.dl_title", "Stockfish wird eingerichtet..."))
        self.lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(16)}px; font-weight: bold;")
        layout.addWidget(self.lbl_title)

        # Status description
        self.lbl_status = QLabel(tr_ui("engine_setup.dl_connecting", "Verbindung zum offiziellen Server wird hergestellt..."))
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {COLORS['brown_text']}; font-size: {scale(12)}px;")
        layout.addWidget(self.lbl_status)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid rgba(0,0,0,0.15);
                border-radius: {scale(8)}px;
                text-align: center;
                background: white;
                height: {scale(22)}px;
                font-size: {scale(11)}px;
                font-weight: bold;
                color: #333;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['burnt_orange']};
                border-radius: {scale(7)}px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(scale(8))

        self.btn_retry = QPushButton(tr_ui("engine_setup.btn_retry", "🔄 Erneut versuchen"))
        self.btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retry.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(14)}px;
                padding: {scale(6)}px {scale(16)}px;
                font-size: {scale(12)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #e67e22; }}
        """)
        self.btn_retry.clicked.connect(self._on_retry_clicked)
        self.btn_retry.hide()
        btn_layout.addWidget(self.btn_retry)

        self.btn_browse_local = QPushButton(tr_ui("engine_setup.btn_browse_short", "📁 Lokale Engine wählen"))
        self.btn_browse_local.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_local.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {COLORS['brown_text']};
                border: 1px solid rgba(0,0,0,0.2);
                border-radius: {scale(14)}px;
                padding: {scale(6)}px {scale(14)}px;
                font-size: {scale(12)}px;
            }}
            QPushButton:hover {{ background-color: #f5f5f5; }}
        """)
        self.btn_browse_local.clicked.connect(self._on_browse_local_clicked)
        self.btn_browse_local.hide()
        btn_layout.addWidget(self.btn_browse_local)

        btn_layout.addStretch()

        self.btn_cancel = QPushButton(tr_ui("common.cancel", "Abbrechen"))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: #555;
                border: 1px solid rgba(0,0,0,0.2);
                border-radius: {scale(14)}px;
                padding: {scale(6)}px {scale(16)}px;
                font-size: {scale(12)}px;
            }}
            QPushButton:hover {{ background-color: #f5f5f5; }}
        """)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['beige']}; }}")

    def start_download(self):
        self.worker = StockfishDownloaderWorker(self, target_dir=self.target_dir)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._on_status)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            percent = int((downloaded / total) * 100)
            self.progress_bar.setValue(min(percent, 100))
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.lbl_status.setText(
                tr_ui(
                    "engine_setup.dl_progress",
                    "Stockfish wird heruntergeladen: {dl_mb:.1f} MB von {tot_mb:.1f} MB ({percent}%)",
                    dl_mb=dl_mb, tot_mb=tot_mb, percent=percent
                )
            )
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self.lbl_status.setText(tr_ui("engine_setup.dl_downloading", "Stockfish wird heruntergeladen..."))

    def _on_status(self, text: str):
        self.lbl_status.setText(text)

    def _on_finished(self, engine_path: str):
        self.engine_path = engine_path
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_title.setText(tr_ui("engine_setup.dl_success_title", "✅ Stockfish bereit!"))
        self.lbl_status.setText(tr_ui("engine_setup.dl_success_desc", "Die Schach-Engine wurde erfolgreich installiert und konfiguriert."))
        self.btn_cancel.setText(tr_ui("common.ok", "OK"))
        self.accept()

    def _on_error(self, err_msg: str):
        self.error_message = err_msg
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_title.setText(tr_ui("engine_setup.dl_error_title", "❌ Fehler beim Download"))
        self.lbl_title.setStyleSheet(f"color: {COLORS.get('error_red', '#c0392b')}; font-size: {scale(16)}px; font-weight: bold;")
        
        err_lower = err_msg.lower()
        is_offline = any(k in err_lower for k in ("getaddrinfo", "connection", "timed out", "timeout", "offline", "name resolution"))
        if is_offline:
            desc = tr_ui(
                "engine_setup.dl_error_offline",
                "Keine Internetverbindung erkannt oder Server nicht erreichbar.\n\n"
                "Bitte prüfe deine Netzwerkverbindung oder wähle eine lokale Engine aus."
            )
        else:
            desc = tr_ui(
                "engine_setup.dl_error_desc",
                "Der Download konnte nicht abgeschlossen werden:\n{err_msg}",
                err_msg=err_msg
            )
        self.lbl_status.setText(desc)
        self.btn_retry.show()
        self.btn_browse_local.show()
        self.btn_cancel.setText(tr_ui("common.cancel", "Abbrechen"))

    def _on_retry_clicked(self):
        self.btn_retry.hide()
        self.btn_browse_local.hide()
        self.lbl_title.setText(tr_ui("engine_setup.dl_title", "Stockfish wird eingerichtet..."))
        self.lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(16)}px; font-weight: bold;")
        self.lbl_status.setText(tr_ui("engine_setup.dl_connecting", "Verbindung zum offiziellen Server wird hergestellt..."))
        self.progress_bar.setRange(0, 0)
        self.start_download()

    def _on_browse_local_clicked(self):
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            tr_ui("engine_setup.browse_file_title", "Schach-Engine auswählen"),
            "",
            "Chess Engine (*.exe);;All Files (*.*)"
        )
        if chosen_file and is_engine_valid(chosen_file):
            self.engine_path = chosen_file
            cfg = get_config_dict()
            cfg["engine_path"] = chosen_file
            save_config_dict(cfg)
            self.accept()
        elif chosen_file:
            QMessageBox.warning(
                self,
                tr_ui("engine_setup.invalid_engine_title", "Ungültige Datei"),
                tr_ui("engine_setup.invalid_engine_desc", "Die ausgewählte Datei ist keine gültige ausführbare Datei.")
            )

    def _on_cancel_clicked(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1000)
        self.reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1000)
        super().closeEvent(event)


def prompt_engine_if_missing(parent=None, config_dict: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Checks if a valid chess engine path is configured.
    If valid, returns the path immediately.
    If missing or invalid, presents the EngineActionDialog to the user.
    Handles automatic downloading or browsing, updates config, and returns the valid path.
    Returns None if the user cancels.
    """
    cfg = config_dict if config_dict is not None else get_config_dict()
    current_path = cfg.get("engine_path", "")

    if is_engine_valid(current_path):
        return current_path

    dlg = EngineActionDialog(parent)
    result = dlg.exec()

    if result != QDialog.DialogCode.Accepted:
        return None

    if dlg.selected_action == EngineActionDialog.ACTION_DOWNLOAD:
        dl_dlg = EngineDownloadProgressDialog(parent)
        if dl_dlg.exec() == QDialog.DialogCode.Accepted and dl_dlg.engine_path:
            valid_path = dl_dlg.engine_path
            cfg["engine_path"] = valid_path
            if config_dict is not None:
                config_dict["engine_path"] = valid_path
            save_config_dict(cfg)
            return valid_path

    elif dlg.selected_action == EngineActionDialog.ACTION_BROWSE:
        chosen_file, _ = QFileDialog.getOpenFileName(
            parent,
            tr_ui("engine_setup.browse_file_title", "Schach-Engine auswählen"),
            "",
            "Chess Engine (*.exe);;All Files (*.*)"
        )
        if chosen_file and is_engine_valid(chosen_file):
            cfg["engine_path"] = chosen_file
            if config_dict is not None:
                config_dict["engine_path"] = chosen_file
            save_config_dict(cfg)
            return chosen_file
        elif chosen_file:
            QMessageBox.warning(
                parent,
                tr_ui("engine_setup.invalid_engine_title", "Ungültige Datei"),
                tr_ui("engine_setup.invalid_engine_desc", "Die ausgewählte Datei ist keine gültige ausführbare Datei.")
            )

    return None
