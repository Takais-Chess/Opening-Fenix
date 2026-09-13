import os
import json
from typing import Optional, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QWidget, QMessageBox, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon, get_bw_glass_style
from opening_fenix.core.translation import tr_ui, tr_widget
from opening_fenix.core.services.lichess_service import (
    verify_lichess_token, clean_lichess_token, is_valid_token_string
)
from opening_fenix.core.utils import get_user_dir


class TokenVerificationWorker(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    def run(self):
        success, msg = verify_lichess_token(self.token)
        self.finished_signal.emit(success, msg)


class LichessTokenDialog(QDialog):
    """
    Dedicated dialog for viewing, entering, testing, and saving a Lichess API token.
    Provides direct link to lichess.org token creation, live verification,
    and clear user feedback.
    """
    def __init__(self, parent=None, current_token: Optional[str] = None, allow_skip: bool = False):
        super().__init__(parent)
        self.current_token = current_token or ""
        self.allow_skip = allow_skip
        self.verified_username: Optional[str] = None
        self.skip_chosen = False
        self._worker: Optional[TokenVerificationWorker] = None

        self.setWindowTitle(tr_ui("lichess_token.dialog_title", "🌐 Lichess API-Token einrichten"))
        self.setFixedWidth(scale(560))
        set_consistent_icon(self)
        self.setStyleSheet(get_bw_glass_style())

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(24), scale(24), scale(24), scale(20))
        layout.setSpacing(scale(16))

        # Title
        lbl_title = QLabel(tr_ui("lichess_token.header_title", "Lichess API-Token konfigurieren"))
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(19)}px; font-weight: 800;")
        layout.addWidget(lbl_title)

        # Explanatory card
        desc_card = QFrame()
        desc_card.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.7);
                border: 1px solid rgba(0, 0, 0, 0.1);
                border-radius: 8px;
                padding: 10px;
            }
        """)
        v_desc = QVBoxLayout(desc_card)
        v_desc.setSpacing(scale(8))
        v_desc.setContentsMargins(scale(10), scale(10), scale(10), scale(10))

        lbl_desc = QLabel(
            tr_ui(
                "lichess_token.desc_main",
                "Ein persönliches Lichess-Token ist <b>100% kostenlos</b> und wird empfohlen, "
                "um die Lichess-Eröffnungsdatenbank ohne strenge Abfragelimits (Rate Limits) herunterzuladen."
            )
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: {scale(13)}px; line-height: 1.4;")
        v_desc.addWidget(lbl_desc)

        # Instructions / Link button
        btn_open_web = QPushButton(tr_widget("lichess_token.btn_open_lichess", "🌐 Kostenloses Token auf Lichess erstellen"))
        btn_open_web.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_web.setStyleSheet(f"""
            QPushButton {{
                background-color: #34495e;
                color: white;
                font-weight: 600;
                font-size: {scale(12)}px;
                padding: {scale(7)}px {scale(14)}px;
                border-radius: {scale(6)}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #2c3e50;
            }}
        """)
        btn_open_web.clicked.connect(self.open_lichess_token_page)
        v_desc.addWidget(btn_open_web)

        lbl_hint = QLabel(
            tr_ui(
                "lichess_token.step_hint",
                "💡 Tipp: Auf der Lichess-Seite einfach auf <b>'Generate'</b> klicken (keine speziellen Berechtigungen nötig) und das Token kopieren."
            )
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        v_desc.addWidget(lbl_hint)

        layout.addWidget(desc_card)

        # Token Input Field Row
        lbl_input = QLabel(tr_ui("lichess_token.input_label", "Persönliches API-Token (lip_...):"))
        lbl_input.setStyleSheet(f"font-weight: 700; font-size: {scale(13)}px; color: {COLORS['dark_accent']};")
        layout.addWidget(lbl_input)

        h_input = QHBoxLayout()
        h_input.setSpacing(scale(8))

        self.txt_token = QLineEdit(self.current_token)
        self.txt_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_token.setPlaceholderText("lip_xxxxxxxxxxxxxxxxxxxxxxxx")
        self.txt_token.textChanged.connect(self._on_token_text_changed)
        self.txt_token.setStyleSheet(f"""
            QLineEdit {{
                padding: {scale(8)}px {scale(12)}px;
                border-radius: {scale(6)}px;
                border: 1px solid rgba(0,0,0,0.2);
                background: white;
                font-family: monospace;
                font-size: {scale(13)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS['burnt_orange']};
            }}
        """)
        h_input.addWidget(self.txt_token, stretch=1)

        self.btn_toggle_eye = QPushButton("👁️")
        self.btn_toggle_eye.setFixedWidth(scale(44))
        self.btn_toggle_eye.setFixedHeight(scale(38))
        self.btn_toggle_eye.setCheckable(True)
        self.btn_toggle_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_eye.toggled.connect(
            lambda c: self.txt_token.setEchoMode(QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password)
        )
        h_input.addWidget(self.btn_toggle_eye)

        self.btn_test = QPushButton(tr_widget("lichess_token.btn_test", "🧪 Verbindung testen"))
        self.btn_test.setFixedHeight(scale(38))
        self.btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['dark_accent']};
                color: white;
                font-weight: 600;
                font-size: {scale(12)}px;
                padding: {scale(6)}px {scale(14)}px;
                border-radius: {scale(6)}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #1a252f;
            }}
            QPushButton:disabled {{
                background-color: #bdc3c7;
            }}
        """)
        self.btn_test.clicked.connect(self.test_connection)
        h_input.addWidget(self.btn_test)

        layout.addLayout(h_input)

        # Status feedback label
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 12px; padding: 4px 0;")
        layout.addWidget(self.lbl_status)

        layout.addSpacing(scale(8))

        # Bottom Buttons
        h_bottom = QHBoxLayout()
        h_bottom.setSpacing(scale(10))

        if self.allow_skip:
            btn_skip = QPushButton(tr_widget("lichess_token.btn_skip", "Ohne Token fortfahren"))
            btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_skip.clicked.connect(self._on_skip_clicked)
            h_bottom.addWidget(btn_skip)

        h_bottom.addStretch()

        btn_cancel = QPushButton(tr_widget("common.cancel", "Abbrechen"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        h_bottom.addWidget(btn_cancel)

        self.btn_save = QPushButton(tr_widget("common.save", "💾 Speichern & Übernehmen"))
        self.btn_save.setProperty("class", "Primary")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                font-weight: bold;
                font-size: {scale(13)}px;
                padding: {scale(8)}px {scale(18)}px;
                border-radius: {scale(6)}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #d35400;
            }}
        """)
        self.btn_save.clicked.connect(self.save_and_accept)
        h_bottom.addWidget(self.btn_save)

        layout.addLayout(h_bottom)

        # Initial status update
        self._update_initial_status()

    def _update_initial_status(self):
        token = self.txt_token.text().strip()
        if not is_valid_token_string(token):
            self.lbl_status.setText(
                tr_ui("lichess_token.status_none", "⚠️ Noch kein Lichess-Token hinterlegt.")
            )
            self.lbl_status.setStyleSheet("color: #e67e22; font-size: 12px;")
        else:
            self.lbl_status.setText(
                tr_ui("lichess_token.status_ready_to_test", "Klicke auf 'Verbindung testen', um dieses Token zu prüfen.")
            )
            self.lbl_status.setStyleSheet("color: #7f8c8d; font-size: 12px;")

    def _on_token_text_changed(self, text: str):
        self.verified_username = None
        cleaned = text.strip()
        if not cleaned:
            self.lbl_status.setText(tr_ui("lichess_token.status_none", "⚠️ Noch kein Lichess-Token hinterlegt."))
            self.lbl_status.setStyleSheet("color: #e67e22; font-size: 12px;")
        else:
            self.lbl_status.setText(tr_ui("lichess_token.status_ready_to_test", "Klicke auf 'Verbindung testen', um dieses Token zu prüfen."))
            self.lbl_status.setStyleSheet("color: #7f8c8d; font-size: 12px;")

    def open_lichess_token_page(self):
        QDesktopServices.openUrl(QUrl("https://lichess.org/account/oauth/token"))

    def test_connection(self):
        token = self.txt_token.text().strip()
        if not token:
            self.lbl_status.setText("❌ " + tr_ui("lichess_token.err_empty", "Bitte gib zuerst ein Token ein."))
            self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 12px;")
            return

        self.btn_test.setEnabled(False)
        self.lbl_status.setText("⏳ " + tr_ui("lichess_token.checking", "Prüfe Token bei Lichess..."))
        self.lbl_status.setStyleSheet("color: #2980b9; font-weight: 500; font-size: 12px;")

        self._worker = TokenVerificationWorker(token)
        self._worker.finished_signal.connect(self._on_verification_done)
        self._worker.start()

    def _on_verification_done(self, success: bool, msg: str):
        self.btn_test.setEnabled(True)
        if success:
            self.lbl_status.setText("✅ " + msg)
            self.lbl_status.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_status.setText("❌ " + msg)
            self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 12px;")

    def _on_skip_clicked(self):
        self.skip_chosen = True
        self.accept()

    def save_and_accept(self):
        token = clean_lichess_token(self.txt_token.text())
        
        # Save to config.json
        config_path = os.path.join(get_user_dir(), "config.json")
        cfg = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        cfg["lichess_token"] = token
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Konnte config.json nicht schreiben: {e}")
            return

        self.current_token = token
        self.accept()

    def get_token(self) -> str:
        return self.current_token


class MissingTokenPromptDialog(QDialog):
    ACTION_SETUP = 1
    ACTION_CONTINUE = 2
    ACTION_CANCEL = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_action = self.ACTION_CANCEL
        self.setWindowTitle(tr_ui("lichess_token.missing_title", "Kein Lichess API-Token eingerichtet"))
        self.setFixedWidth(scale(580))
        set_consistent_icon(self)
        self.setStyleSheet(get_bw_glass_style())
        self.init_ui()

    def init_ui(self):
        from PyQt6.QtWidgets import QCheckBox
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(24), scale(22), scale(24), scale(20))
        layout.setSpacing(scale(16))

        lbl_title = QLabel(tr_ui("lichess_token.missing_header", "Kein Lichess API-Token eingerichtet"))
        lbl_title.setStyleSheet(f"color: {COLORS['burnt_orange']}; font-size: {scale(18)}px; font-weight: 800;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel()
        lbl_desc.setTextFormat(Qt.TextFormat.RichText)
        desc_text = tr_ui(
            "lichess_token.missing_body",
            "Du hast noch kein persönliches Lichess API-Token eingerichtet.<br><br>"
            "Mit einem Token laufen Downloads mit höherer Geschwindigkeit und ohne Blockaden. "
            "Ein Token ist <b>100% kostenlos</b> in 1 Minute erstellt.<br><br>"
            "Wie möchtest du fortfahren?"
        ).replace("\n\n", "<br><br>").replace("\n", "<br>")
        lbl_desc.setText(desc_text)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {COLORS['dark_accent']}; font-size: {scale(13)}px; line-height: 1.5;")
        layout.addWidget(lbl_desc)

        self.chk_dont_ask = QCheckBox(tr_ui("lichess_token.dont_ask_again", "Diese Warnung nicht mehr anzeigen"))
        self.chk_dont_ask.setStyleSheet("font-size: 12px; color: #555;")
        layout.addWidget(self.chk_dont_ask)

        layout.addSpacing(scale(6))

        h_buttons = QHBoxLayout()
        h_buttons.setSpacing(scale(10))

        btn_cancel = QPushButton(tr_widget("common.cancel", "Abbrechen"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        h_buttons.addWidget(btn_cancel)

        btn_continue = QPushButton(tr_widget("lichess_token.btn_continue_no_token", "🌐 Ohne Token fortfahren"))
        btn_continue.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_continue.clicked.connect(self._on_continue)
        h_buttons.addWidget(btn_continue)

        btn_setup = QPushButton(tr_widget("lichess_token.btn_setup_now", "🔑 Token jetzt einrichten"))
        btn_setup.setProperty("class", "Primary")
        btn_setup.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_setup.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                font-weight: bold;
                font-size: {scale(13)}px;
                padding: {scale(8)}px {scale(16)}px;
                border-radius: {scale(6)}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #d35400;
            }}
        """)
        btn_setup.clicked.connect(self._on_setup)
        h_buttons.addWidget(btn_setup)

        layout.addLayout(h_buttons)

    def _on_continue(self):
        self.selected_action = self.ACTION_CONTINUE
        self._save_dont_ask()
        self.accept()

    def _on_setup(self):
        self.selected_action = self.ACTION_SETUP
        self._save_dont_ask()
        self.accept()

    def _save_dont_ask(self):
        if self.chk_dont_ask.isChecked():
            config_path = os.path.join(get_user_dir(), "config.json")
            cfg = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    pass
            cfg["suppress_missing_token_warning"] = True
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
            except Exception:
                pass


def prompt_lichess_token_if_missing(parent, config: dict) -> Tuple[bool, bool]:
    """
    Checks if a valid Lichess token is configured.
    If missing, prompts the user.
    Returns (proceed: bool, token_configured: bool).
    """
    token = config.get("lichess_token", "")
    if is_valid_token_string(token):
        return True, True

    if config.get("suppress_missing_token_warning", False):
        return True, False

    dlg = MissingTokenPromptDialog(parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False, False

    if dlg.selected_action == MissingTokenPromptDialog.ACTION_SETUP:
        tok_dlg = LichessTokenDialog(parent, current_token=token)
        if tok_dlg.exec() == QDialog.DialogCode.Accepted:
            new_token = tok_dlg.get_token()
            if is_valid_token_string(new_token):
                config["lichess_token"] = new_token
                return True, True
            return True, False
        return False, False

    elif dlg.selected_action == MissingTokenPromptDialog.ACTION_CONTINUE:
        return True, False

    return False, False

