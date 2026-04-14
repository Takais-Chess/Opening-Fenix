from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QLabel, QPushButton

def show_debug_position_info(self):
    fen = self.board_widget.board.fen()
    incoming = self.backend.get_incoming_moves(fen)

    title = "Stellungs-Analyse (Debug)"
    msg = f"<b>Aktuelle FEN:</b><br><code style='background-color: #eee;'>{fen}</code><br><br>"
    msg += f"<b>Eingehende Pfade ({len(incoming)}):</b><br>"

    if not incoming:
        msg += "<i>Keine (Startstellung oder isolierte Stellung)</i>"
    else:
        for m in incoming:
            lvl = f"<b>L{m['level']}</b>" if m['level'] else "<span style='color: red;'>Kein Repertoire</span>"
            msg += f"<hr>• Zug: <b>{m['san']}</b> ({m['uci']}) -> Level: {lvl}<br>"
            msg += f"  Von FEN: <small>{m['parent_fen']}</small><br>"

    # Ein einfaches Info-Fenster mit kopierbarem Text
    d = QDialog(self)
    d.setWindowTitle(title)
    l = QVBoxLayout(d)
    text_edit = QPlainTextEdit()
    text_edit.setReadOnly(True)
    # Wir nutzen HTML für die Formatierung, konvertieren es aber für das Textfeld
    text_edit.appendHtml(msg)
    l.addWidget(QLabel("Details zu dieser Stellung:"))
    l.addWidget(text_edit)
    btn = QPushButton("Schließen")
    btn.clicked.connect(d.accept)
    l.addWidget(btn)
    d.resize(600, 400)
    d.exec()
