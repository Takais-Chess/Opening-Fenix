from typing import Iterable, List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton

from opening_fenix.core.utils import ELO_DISPLAY_MAP, get_elo_display, parse_elo_list
from opening_fenix.gui.scaling import scale


class EloPills(QWidget):
    """
    Compact row of checkable pills for choosing one or more Lichess Elo brackets.
    Used for "additional Elos" when importing, so the default single-Elo flow stays untouched.
    """
    changed = pyqtSignal()

    def __init__(self, parent=None, keys: Optional[Iterable[str]] = None):
        super().__init__(parent)
        self._buttons = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(scale(6))
        for key in (list(keys) if keys is not None else list(ELO_DISPLAY_MAP.keys())):
            btn = QPushButton(get_elo_display(key))
            btn.setCheckable(True)
            btn.setFixedHeight(scale(26))
            btn.setStyleSheet(
                f"QPushButton {{ background: #ffffff; border: 1px solid #cbd5e1; border-radius: {scale(13)}px;"
                f" padding: 0 {scale(10)}px; font-size: {scale(11)}px; color: #334155; }}"
                f"QPushButton:checked {{ background: #dbeafe; border: 1px solid #3b82f6; color: #1d4ed8; font-weight: 600; }}"
                f"QPushButton:disabled {{ color: #94a3b8; background: #f1f5f9; }}"
            )
            btn.toggled.connect(lambda _checked: self.changed.emit())
            self._buttons[key] = btn
            lay.addWidget(btn)
        lay.addStretch()

    def selected(self) -> List[str]:
        return parse_elo_list([k for k, b in self._buttons.items() if b.isChecked()])

    def set_selected(self, keys: Iterable[str]) -> None:
        wanted = set(parse_elo_list(list(keys or [])))
        for k, b in self._buttons.items():
            b.blockSignals(True)
            b.setChecked(k in wanted)
            b.blockSignals(False)
        self.changed.emit()

    def set_key_hidden(self, key: str, hidden: bool) -> None:
        """Hides a pill (e.g. the primary Elo that is already chosen elsewhere) and unchecks it."""
        b = self._buttons.get(key)
        if b is not None:
            if hidden:
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            b.setVisible(not hidden)
