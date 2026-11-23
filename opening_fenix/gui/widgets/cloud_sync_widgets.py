import os
from typing import Optional, Dict, Any, List, Callable

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QFrame,
    QScrollArea,
    QWidget,
    QFileDialog,
    QMessageBox,
    QMenu,
    QApplication,
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QAction

from opening_fenix.core.translation import tr_ui
from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon, get_tooltip_style, get_cloud_sync_icon
from opening_fenix.core.services.cloud_sync_service import CloudSyncService, format_relative_time
from opening_fenix.core.services.cloud_sync_manager import CloudSyncManager
from opening_fenix.core.threads import CloudSyncThread


class CloudSyncProgressDialog(QDialog):
    """
    Modern non-blocking progress dialog backed by CloudSyncThread.
    Used for startup sync, shutdown push, manual sync, and initial cloud folder connection
    so the application never looks frozen or exits silently before pushing snapshots.
    """

    def __init__(
        self,
        direction: str = "both",
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        set_consistent_icon(self)
        self.direction = direction
        self.summary: Dict[str, Any] = {}
        self._worker: Optional[CloudSyncThread] = None

        self.setWindowTitle(title or tr_ui("cloud_sync.progress_title", "Cloud-Synchronisation"))
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setModal(True)
        self.setFixedWidth(scale(440))
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: {scale(12)}px;
            }}
            QLabel {{
                color: #0f172a;
                background: transparent;
            }}
            QProgressBar {{
                border: 1px solid #cbd5e1;
                border-radius: {scale(6)}px;
                background-color: #f1f5f9;
                height: {scale(12)}px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS.get('burnt_orange', '#d35400')};
                border-radius: {scale(5)}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))
        layout.setSpacing(scale(12))

        lbl_header = QLabel(title or tr_ui("cloud_sync.progress_title", "☁️ Cloud-Synchronisation"))
        lbl_header.setStyleSheet(f"font-size: {scale(16)}px; font-weight: 700; color: #0f172a;")
        layout.addWidget(lbl_header)

        self.lbl_status = QLabel(
            subtitle
            or tr_ui("cloud_sync.progress_starting", "Synchronisiere Daten mit dem Cloud-Ordner...")
        )
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"font-size: {scale(12)}px; color: #475569;")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate until first progress tick
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

    def run_sync(self) -> Dict[str, Any]:
        """Starts the worker thread and executes the dialog until completion."""
        self._worker = CloudSyncThread(direction=self.direction, parent=self)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        QTimer.singleShot(10, self._worker.start)
        self.exec()
        return self.summary

    def _on_progress(self, msg: str, cur: int, tot: int) -> None:
        if msg:
            self.lbl_status.setText(msg)
        if tot > 0:
            self.progress.setRange(0, tot)
            self.progress.setValue(min(cur, tot))

    def _on_finished(self, summary: dict) -> None:
        self.summary = summary or {}
        CloudSyncManager.instance().refresh_status(syncing=False)
        self.accept()


def run_sync_with_progress(
    direction: str = "both",
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    parent=None,
) -> Dict[str, Any]:
    """Convenience helper to run CloudSyncService.sync_now inside CloudSyncProgressDialog."""
    dlg = CloudSyncProgressDialog(direction=direction, title=title, subtitle=subtitle, parent=parent)
    return dlg.run_sync()


class CloudSyncConflictDialog(QDialog):
    """
    Clear, actionable conflict resolution dialog shown whenever:
    - A repertoire had simultaneous offline edits on two devices (lets user Keep Cloud or Restore Local Backup)
    - A profile was automatically smart-merged (reassures user nothing was lost)
    - Google Drive / OneDrive conflict duplicate files (e.g. sync_manifest (1).json) were detected
    """

    def __init__(
        self,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        merged_profiles: Optional[List[str]] = None,
        provider_conflict_files: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        set_consistent_icon(self)
        self.conflicts = list(conflicts or [])
        self.merged_profiles = list(merged_profiles or [])
        self.provider_conflict_files = list(provider_conflict_files or [])
        self.restored_repertoires: List[str] = []

        self.setWindowTitle(tr_ui("cloud_sync.conflict_title", "Cloud-Sync Hinweise & Konflikte"))
        self.setMinimumWidth(scale(560))
        self.setMaximumHeight(scale(620))
        self.setStyleSheet("""
            QDialog { background-color: #f8fafc; }
            QLabel { color: #0f172a; background: transparent; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(scale(22), scale(20), scale(22), scale(18))
        root.setSpacing(scale(14))

        hdr = QLabel(tr_ui("cloud_sync.conflict_header", "☁️ Cloud-Synchronisation: Hinweise"))
        hdr.setStyleSheet(f"font-size: {scale(17)}px; font-weight: 700; color: #0f172a;")
        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, scale(4), 0)
        v.setSpacing(scale(12))

        # 1. Repertoire conflicts (cloud won + local backup saved)
        repo_conflicts = [c for c in self.conflicts if c.get("kind") == "repertoire"]
        if repo_conflicts:
            sec_lbl = QLabel(
                tr_ui(
                    "cloud_sync.conflict_repos_intro",
                    "Folgende Repertoires wurden auf zwei Geräten gleichzeitig geändert. "
                    "Die Cloud-Version wurde übernommen und deine lokale Version sicher als Backup gespeichert:",
                )
            )
            sec_lbl.setWordWrap(True)
            sec_lbl.setStyleSheet(f"font-size: {scale(12)}px; color: #334155;")
            v.addWidget(sec_lbl)

            for c in repo_conflicts:
                card = QFrame()
                card.setStyleSheet(
                    f"QFrame {{ background: #fffbeb; border: 1px solid #fcd34d; border-radius: {scale(8)}px; }}"
                )
                cl = QVBoxLayout(card)
                cl.setContentsMargins(scale(14), scale(12), scale(14), scale(12))
                cl.setSpacing(scale(8))

                name = c.get("name", "")
                dev = c.get("cloud_updated_by") or "?"
                rel_t = format_relative_time(c.get("cloud_updated_at"))
                title_lbl = QLabel(f"📚 <b>{name}</b>  •  Cloud: {dev} ({rel_t})")
                title_lbl.setWordWrap(True)
                title_lbl.setStyleSheet(f"font-size: {scale(13)}px; color: #92400e;")
                cl.addWidget(title_lbl)

                btn_row = QHBoxLayout()
                status_lbl = QLabel(
                    tr_ui("cloud_sync.conflict_status_cloud_active", "Aktuell aktiv: Cloud-Version (Lokales Backup gespeichert)")
                )
                status_lbl.setStyleSheet(f"font-size: {scale(11)}px; color: #78350f;")
                btn_row.addWidget(status_lbl, 1)

                bk_path = c.get("backup_path")
                if bk_path and os.path.isfile(bk_path):
                    btn_restore = QPushButton(
                        tr_ui("cloud_sync.btn_restore_local", "↩️ Meine lokale Version wiederherstellen")
                    )
                    btn_restore.setMinimumHeight(scale(32))
                    btn_restore.setStyleSheet(
                        f"QPushButton {{ background: #ffffff; border: 1px solid #d97706; color: #92400e; "
                        f"border-radius: {scale(6)}px; padding: {scale(4)}px {scale(10)}px; font-weight: 600; }}"
                        f"QPushButton:hover {{ background: #fef3c7; }}"
                    )
                    btn_restore.clicked.connect(
                        lambda _=False, r=name, bp=bk_path, b=btn_restore, sl=status_lbl: self._restore_local(r, bp, b, sl)
                    )
                    btn_row.addWidget(btn_restore)
                cl.addLayout(btn_row)
                v.addWidget(card)

        # 2. Smart-merged profiles notice
        merged_list = list(self.merged_profiles) or [
            c.get("name") for c in self.conflicts if c.get("kind") == "profile" and c.get("resolution") == "auto_merged"
        ]
        if merged_list:
            m_card = QFrame()
            m_card.setStyleSheet(
                f"QFrame {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: {scale(8)}px; }}"
            )
            ml = QVBoxLayout(m_card)
            ml.setContentsMargins(scale(14), scale(12), scale(14), scale(12))
            ml.setSpacing(scale(6))
            m_lbl = QLabel(
                tr_ui(
                    "cloud_sync.profiles_merged_msg",
                    "✅ <b>Profile automatisch zusammengeführt ({profiles}):</b><br>"
                    "Offline-Trainingsfortschritte von beiden Geräten wurden verlustfrei kombiniert "
                    "(zusätzlich wurde ein Sicherheits-Backup angelegt).",
                    profiles=", ".join(merged_list),
                )
            )
            m_lbl.setWordWrap(True)
            m_lbl.setStyleSheet(f"font-size: {scale(12)}px; color: #166534;")
            ml.addWidget(m_lbl)
            v.addWidget(m_card)

        # 3. Cloud provider conflict duplicate files
        if self.provider_conflict_files:
            p_card = QFrame()
            p_card.setStyleSheet(
                f"QFrame {{ background: #fef2f2; border: 1px solid #fca5a5; border-radius: {scale(8)}px; }}"
            )
            pl = QVBoxLayout(p_card)
            pl.setContentsMargins(scale(14), scale(12), scale(14), scale(12))
            pl.setSpacing(scale(8))
            files_preview = "<br>".join(f"• {f}" for f in self.provider_conflict_files[:8])
            p_lbl = QLabel(
                tr_ui(
                    "cloud_sync.provider_conflicts_msg",
                    "⚠️ <b>Cloud-Konfliktdateien erkannt (Google Drive / OneDrive):</b><br>"
                    "Dein Cloud-Dienst hat Konfliktkopien angelegt. Bitte prüfe/entferne sie im Cloud-Ordner:<br>{files}",
                    files=files_preview,
                )
            )
            p_lbl.setWordWrap(True)
            p_lbl.setStyleSheet(f"font-size: {scale(12)}px; color: #991b1b;")
            pl.addWidget(p_lbl)

            btn_open = QPushButton(tr_ui("settings.storage_btn_open_cloud", "📁 Cloud-Ordner öffnen"))
            btn_open.setFixedHeight(scale(32))
            btn_open.clicked.connect(self._open_cloud_folder)
            pl.addWidget(btn_open, alignment=Qt.AlignmentFlag.AlignLeft)
            v.addWidget(p_card)

        v.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        btn_close = QPushButton(tr_ui("common.ok", "OK"))
        btn_close.setMinimumHeight(scale(38))
        btn_close.setMinimumWidth(scale(120))
        btn_close.setStyleSheet(
            f"QPushButton {{ background: {COLORS.get('burnt_orange', '#d35400')}; color: white; "
            f"border: none; border-radius: {scale(8)}px; font-weight: 700; padding: {scale(6)}px {scale(18)}px; }}"
            f"QPushButton:hover {{ background: #e67e22; }}"
        )
        btn_close.clicked.connect(self.accept)
        h_foot = QHBoxLayout()
        h_foot.addStretch()
        h_foot.addWidget(btn_close)
        root.addLayout(h_foot)

    def _restore_local(self, repo_name: str, backup_path: str, btn: QPushButton, status_lbl: QLabel) -> None:
        btn.setEnabled(False)
        QApplication.processEvents()
        ok, msg = CloudSyncService.restore_repertoire_conflict_backup(repo_name, backup_path)
        if ok:
            self.restored_repertoires.append(repo_name)
            status_lbl.setText(
                tr_ui("cloud_sync.conflict_restored_local", "✅ Lokale Version wiederhergestellt & in Cloud hochgeladen.")
            )
            status_lbl.setStyleSheet(f"font-size: {scale(11)}px; color: #166534; font-weight: 600;")
            btn.setText(tr_ui("cloud_sync.btn_restored", "✓ Wiederhergestellt"))
        else:
            btn.setEnabled(True)
            QMessageBox.warning(self, tr_ui("common.error", "Fehler"), str(msg))

    def _open_cloud_folder(self) -> None:
        c_dir = CloudSyncService.get_cloud_dir()
        if c_dir and os.path.exists(c_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(c_dir))


class CloudFolderSetupDialog(QDialog):
    """
    1-Click Cloud Sync Setup Dialog with auto-detection of Google Drive, OneDrive,
    Dropbox, iCloud Drive, and Nextcloud, plus manual folder browsing.
    Usable from both LoginDialog (fresh second PC!) and Settings -> Storage.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.selected_folder: Optional[str] = None
        self.setWindowTitle(tr_ui("cloud_sync.setup_title", "☁️ Cloud-Ordner verbinden"))
        self.setMinimumWidth(scale(540))
        self.setStyleSheet("""
            QDialog { background-color: #f8fafc; }
            QLabel { color: #0f172a; background: transparent; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(22), scale(20), scale(22), scale(18))
        layout.setSpacing(scale(12))

        lbl_title = QLabel(tr_ui("cloud_sync.setup_header", "☁️ Cloud-Synchronisation einrichten"))
        lbl_title.setStyleSheet(f"font-size: {scale(17)}px; font-weight: 700; color: #0f172a;")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(
            tr_ui(
                "cloud_sync.setup_subtitle",
                "Wähle einen erkannten Cloud-Ordner (Google Drive, OneDrive, Dropbox) oder wähle manuell einen eigenen Ordner. "
                "Bestehende Repertoires & Profile werden automatisch abgeglichen.",
            )
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet(f"font-size: {scale(12)}px; color: #475569;")
        layout.addWidget(lbl_sub)

        detected = CloudSyncService.detect_cloud_folders()
        if detected:
            lbl_det = QLabel(tr_ui("cloud_sync.detected_providers", "Erkannte Cloud-Ordner auf diesem Gerät:"))
            lbl_det.setStyleSheet(f"font-size: {scale(12)}px; font-weight: 700; color: #334155;")
            layout.addWidget(lbl_det)

            for entry in detected:
                card = QPushButton()
                card.setCursor(Qt.CursorShape.PointingHandCursor)
                card.setMinimumHeight(scale(64))
                provider = entry["provider"]
                icon = entry["icon"]
                suggested = entry["suggested_path"]
                if entry["has_existing_sync"]:
                    badge = tr_ui(
                        "cloud_sync.existing_data_badge",
                        "✨ Vorhandene Daten gefunden ({repos} Repertoires, {profs} Profile)",
                        repos=entry["repertoire_count"],
                        profs=entry["profile_count"],
                    )
                    card_text = f"{icon}  {provider}  —  {badge}\n     {suggested}"
                    border_col = "#16a34a"
                    bg_col = "#f0fdf4"
                    hover_col = "#dcfce7"
                else:
                    card_text = f"{icon}  {provider}\n     {suggested}"
                    border_col = "#cbd5e1"
                    bg_col = "#ffffff"
                    hover_col = "#f1f5f9"

                card.setText(card_text)
                card.setStyleSheet(f"""
                    QPushButton {{
                        text-align: left;
                        padding: {scale(10)}px {scale(14)}px;
                        background-color: {bg_col};
                        border: 1px solid {border_col};
                        border-radius: {scale(9)}px;
                        color: #0f172a;
                        font-size: {scale(12)}px;
                        font-weight: 600;
                    }}
                    QPushButton:hover {{
                        background-color: {hover_col};
                        border-color: {COLORS.get('burnt_orange', '#d35400')};
                    }}
                """)
                card.clicked.connect(lambda _=False, p=suggested: self._pick_folder(p))
                layout.addWidget(card)
        else:
            lbl_none = QLabel(
                tr_ui(
                    "cloud_sync.no_providers_detected",
                    "Keine Standard-Cloud-Ordner automatisch erkannt. Wähle unten einfach manuell einen Ordner aus.",
                )
            )
            lbl_none.setWordWrap(True)
            lbl_none.setStyleSheet(
                f"background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: {scale(8)}px; "
                f"padding: {scale(10)}px; font-size: {scale(12)}px; color: #475569;"
            )
            layout.addWidget(lbl_none)

        h_actions = QHBoxLayout()
        h_actions.setSpacing(scale(10))

        btn_browse = QPushButton(tr_ui("cloud_sync.btn_browse_custom", "📁 Anderen Ordner wählen..."))
        btn_browse.setMinimumHeight(scale(40))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self._browse_manual)
        h_actions.addWidget(btn_browse)

        h_actions.addStretch()

        btn_cancel = QPushButton(tr_ui("common.cancel", "Abbrechen"))
        btn_cancel.setMinimumHeight(scale(40))
        btn_cancel.clicked.connect(self.reject)
        h_actions.addWidget(btn_cancel)
        layout.addLayout(h_actions)

    def _pick_folder(self, folder_path: str) -> None:
        self.selected_folder = os.path.abspath(folder_path)
        self.accept()

    def _browse_manual(self) -> None:
        start_dir = CloudSyncService.get_configured_cloud_dir() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(
            self,
            tr_ui("settings.storage_title", "📁 Cloud-Sync-Ordner wählen"),
            start_dir,
        )
        if chosen:
            self._pick_folder(chosen)


class CloudSyncStatusPill(QPushButton):
    """
    Subtle, theme-matched Cloud Sync indicator for MainWindow & CreatorWindow.
    - `icon_only=True` (MainWindow): 40x40 flat circular icon matching btn_settings (⚙️),
      sits inside the top-right GlassPill with zero distracting colors.
    - `icon_only=False` (CreatorWindow): neutral GlassPill button matching Resources/Statistics.
    Automatically hides when Cloud Sync is not configured.
    """

    open_settings_requested = pyqtSignal()
    sync_now_requested = pyqtSignal()

    def __init__(self, parent=None, compact_height: int = 40, icon_only: bool = False):
        super().__init__(parent)
        self._compact_height = compact_height
        self._icon_only = icon_only
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_only:
            self.setFixedSize(scale(compact_height), scale(compact_height))
        else:
            self.setFixedHeight(scale(compact_height))
            self.setProperty("class", "GlassPill")
        self.setFlat(True)
        self.clicked.connect(self._show_menu)

        self._mgr = CloudSyncManager.instance()
        self._mgr.status_changed.connect(self.apply_status)
        self.apply_status(self._mgr.get_ui_status_snapshot())

    def apply_status(self, info: Dict[str, Any]) -> None:
        configured = info.get("configured", False)
        self.setVisible(bool(configured))
        if not configured:
            return

        state = info.get("state", "synced")
        rel = info.get("last_sync_rel") or tr_ui("settings.cloud_status_ready", "Bereit")
        dev = info.get("last_sync_device") or ""
        cloud_dir = info.get("cloud_dir") or ""

        icon_px = 20 if self._icon_only else 18
        self.setIconSize(QSize(scale(icon_px), scale(icon_px)))

        # Calm, non-distracting palette matching the settings gear (#a49dae) & warm brown text
        brown_fg = COLORS.get("brown_text", "#3e2723")
        muted_neutral = "#9b93a6"

        if state == "syncing":
            text = "" if self._icon_only else " " + tr_ui("cloud_sync.pill_syncing", "Sync...").replace("☁️", "").strip()
            icon_color = "#64748b"
            fg = brown_fg
            icon_state = "syncing"
            tip = tr_ui("cloud_sync.tip_syncing", "Cloud-Synchronisation läuft...")
        elif state == "offline":
            text = "" if self._icon_only else " " + tr_ui("cloud_sync.pill_offline", "Offline").replace("☁️", "").strip()
            icon_color = "#b45309"
            fg = "#92400e"
            icon_state = "offline"
            tip = tr_ui(
                "cloud_sync.tip_offline",
                "Cloud-Ordner aktuell nicht erreichbar ({path}).\n"
                "Du arbeitest sicher im lokalen Arbeitsordner — es wird automatisch synchronisiert, sobald der Ordner wieder verfügbar ist.",
                path=cloud_dir,
            )
        elif state in ("warning", "other_device"):
            text = "" if self._icon_only else " Sync"
            icon_color = "#b91c1c" if state == "warning" else "#a16207"
            fg = icon_color
            icon_state = state
            if state == "other_device":
                other_dev = (info.get("other_active_session") or {}).get("device_name", "?")
                tip = tr_ui(
                    "cloud_sync.tip_other_device",
                    "Anderes Gerät aktiv: {device}\nKlicken für Optionen & Einstellungen.",
                    device=other_dev,
                )
            else:
                errs = info.get("last_errors") or info.get("provider_conflict_files") or []
                tip = tr_ui(
                    "cloud_sync.tip_warning",
                    "Cloud-Sync Hinweis:\n{details}\nKlicken für Details.",
                    details="\n".join(str(e) for e in errs[:3]),
                )
        else:
            text = "" if self._icon_only else " Sync"
            icon_color = muted_neutral
            fg = brown_fg
            icon_state = "synced"
            dev_str = f" ({dev})" if dev else ""
            tip = tr_ui(
                "cloud_sync.tip_synced",
                "Sicherer Cloud-Sync aktiv\nLetzte Synchronisation: {rel}{dev}\nOrdner: {path}\nKlicken für Sync & Einstellungen.",
                rel=rel,
                dev=dev_str,
                path=cloud_dir,
            )

        self.setIcon(get_cloud_sync_icon(icon_state, size=icon_px, color=icon_color))
        self.setText(text)
        self.setToolTip(tip)

        if self._icon_only:
            self.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    background: transparent;
                    border-radius: {scale(self._compact_height // 2)}px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.7);
                }}
                {get_tooltip_style()}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    font-weight: bold;
                    color: {fg};
                    background-color: {COLORS.get('glass_bg', 'rgba(255, 255, 255, 0.55)')};
                    border: 1px solid {COLORS.get('glass_border', 'rgba(255, 255, 255, 0.75)')};
                    border-radius: {scale(15)}px;
                    padding: 0px {scale(14)}px;
                    font-size: {scale(13)}px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.78);
                }}
                {get_tooltip_style()}
            """)

    def _show_menu(self) -> None:
        menu = QMenu(self)
        act_sync = QAction(tr_ui("settings.storage_btn_sync_now", "🔄 Jetzt synchronisieren"), self)
        act_sync.setEnabled(CloudSyncService.is_enabled() and not self._mgr.is_syncing())
        act_sync.triggered.connect(self._on_sync_clicked)
        menu.addAction(act_sync)

        act_folder = QAction(tr_ui("settings.storage_btn_open_cloud", "📁 Cloud-Ordner öffnen"), self)
        act_folder.setEnabled(CloudSyncService.is_enabled())
        act_folder.triggered.connect(self._open_cloud_folder)
        menu.addAction(act_folder)

        menu.addSeparator()
        act_settings = QAction(tr_ui("cloud_sync.menu_open_settings", "⚙️ Cloud-Sync Einstellungen..."), self)
        act_settings.triggered.connect(self.open_settings_requested.emit)
        menu.addAction(act_settings)

        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _on_sync_clicked(self) -> None:
        self.sync_now_requested.emit()
        self._mgr.trigger_sync(direction="both")

    def _open_cloud_folder(self) -> None:
        c_dir = CloudSyncService.get_cloud_dir()
        if c_dir and os.path.exists(c_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(c_dir))
