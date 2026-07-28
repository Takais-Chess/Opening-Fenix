import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QSize
from opening_fenix.gui.widgets.common import AutoAdjustButton

def test_auto_adjust_button_text_and_tooltip(qtbot):
    btn = AutoAdjustButton("📁 Aktuellen Repertoire-Ordner im Explorer öffnen")
    qtbot.addWidget(btn)
    assert btn.text() == "📁 Aktuellen Repertoire-Ordner im Explorer öffnen"
    assert btn.toolTip() == "📁 Aktuellen Repertoire-Ordner im Explorer öffnen"

def test_auto_adjust_button_set_text(qtbot):
    btn = AutoAdjustButton()
    qtbot.addWidget(btn)
    btn.setText("Neuer Button Text")
    assert btn.text() == "Neuer Button Text"
    assert btn.toolTip() == "Neuer Button Text"

def test_auto_adjust_button_resize_and_size_hint(qtbot):
    btn = AutoAdjustButton("📁 Alle Repertoires-Ordner im Explorer öffnen")
    qtbot.addWidget(btn)
    sh = btn.sizeHint()
    assert sh.width() > 0
    assert sh.height() > 0
    btn.resize(150, 45)
    btn.show()
    qtbot.waitExposed(btn)
