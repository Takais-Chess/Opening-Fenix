"""
Dialog for configuring automatic level recommendation rules in Opening-Fenix.
Allows users to set minimum popularity thresholds per repertoire level and configure
the engine eval loss threshold (moves with loss >= X are automatically recommended for the highest level).
"""

from typing import Dict, Any, Callable, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QDoubleSpinBox, QCheckBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from opening_fenix.gui.styles import COLORS
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui


class HoleRecommendationSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        backend=None,
        current_rules: Optional[Dict[str, Any]] = None,
        on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        super().__init__(parent)
        self.backend = backend
        self.current_rules = current_rules or {}
        self.on_save_callback = on_save_callback
        self.level_spins: Dict[int, QDoubleSpinBox] = {}

        self.setWindowTitle(tr_ui("creator.hole_rec_dialog_title", "Regeln für Level-Empfehlungen"))
        self.setMinimumWidth(scale(480))
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['beige']};
                color: {COLORS['brown_text']};
            }}
            QGroupBox {{
                background-color: {COLORS['glass_bg']};
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(10)}px;
                margin-top: {scale(12)}px;
                padding: {scale(12)}px;
                font-weight: bold;
                font-size: {scale(13)}px;
                color: {COLORS['brown_text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {scale(12)}px;
                padding: 0 {scale(4)}px;
            }}
            QLabel {{
                color: {COLORS['brown_text']};
                font-size: {scale(12)}px;
            }}
            QDoubleSpinBox {{
                background-color: {COLORS['white']};
                border: 1px solid {COLORS['border']};
                border-radius: {scale(6)}px;
                padding: {scale(4)}px {scale(8)}px;
                font-size: {scale(12)}px;
                color: {COLORS['brown_text']};
                min-width: {scale(80)}px;
            }}
            QDoubleSpinBox:focus {{
                border-color: {COLORS['burnt_orange']};
            }}
            QCheckBox {{
                color: {COLORS['brown_text']};
                font-size: {scale(12)}px;
                font-weight: normal;
                spacing: {scale(6)}px;
            }}
            QPushButton {{
                border-radius: {scale(8)}px;
                padding: {scale(6)}px {scale(14)}px;
                font-size: {scale(12)}px;
                font-weight: 600;
            }}
        """)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(16), scale(16), scale(16), scale(16))
        layout.setSpacing(scale(12))

        # ── Header ──────────────────────────────────────────
        header_layout = QVBoxLayout()
        header_layout.setSpacing(scale(2))
        lbl_title = QLabel(f"⭐ {tr_ui('creator.hole_rec_dialog_title', 'Regeln für Level-Empfehlungen')}")
        f_title = QFont()
        f_title.setBold(True)
        f_title.setPixelSize(scale(15))
        lbl_title.setFont(f_title)
        lbl_title.setStyleSheet(f"color: {COLORS['brown_text']};")
        header_layout.addWidget(lbl_title)

        lbl_subtitle = QLabel(
            tr_ui(
                "creator.hole_rec_dialog_subtitle",
                "Passe an, nach welchen Kriterien unanalysierte Züge bestimmten Repertoire-Leveln empfohlen werden."
            )
        )
        lbl_subtitle.setStyleSheet(f"color: {COLORS['light_text']}; font-size: {scale(11)}px;")
        lbl_subtitle.setWordWrap(True)
        header_layout.addWidget(lbl_subtitle)
        layout.addLayout(header_layout)

        # ── Group 1: Popularity Thresholds per Level ────────
        grp_pop = QGroupBox(tr_ui("creator.hole_rec_group_pop", "Mindest-Popularität pro Repertoire-Level"))
        form_pop = QFormLayout(grp_pop)
        form_pop.setContentsMargins(scale(10), scale(12), scale(10), scale(8))
        form_pop.setSpacing(scale(8))

        levels = self.backend.get_repertoire_levels() if self.backend else []
        if not levels:
            levels = [{"name": "Level 1", "order": 1}]

        saved_threshs = self.current_rules.get("level_thresholds", {})

        for lvl in sorted(levels, key=lambda x: x.get("order", 1)):
            order = lvl.get("order", 1)
            name = lvl.get("name", f"Level {order}")

            spin = QDoubleSpinBox()
            spin.setRange(0.01, 100.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setSuffix(" %")

            # Default: L1 = 1.0%, L2 = 0.5%, L3 = 0.1%, L4+ = 0.05%
            default_val = 1.0 if order == 1 else (0.5 if order == 2 else (0.1 if order == 3 else 0.05))
            val = float(saved_threshs.get(str(order), default_val))
            spin.setValue(val)

            self.level_spins[order] = spin
            lbl_lvl = QLabel(f"<b>Level {order}</b> ({name}):")
            lbl_lvl.setStyleSheet(f"color: {COLORS['brown_text']};")
            form_pop.addRow(lbl_lvl, spin)

        layout.addWidget(grp_pop)

        # ── Group 2: Engine Eval Loss Rule ──────────────────
        grp_loss = QGroupBox(tr_ui("creator.hole_rec_group_loss", "Engine-Verlust Regel"))
        loss_layout = QVBoxLayout(grp_loss)
        loss_layout.setContentsMargins(scale(12), scale(14), scale(12), scale(14))
        loss_layout.setSpacing(scale(10))

        self.chk_loss = QCheckBox(
            tr_ui(
                "creator.hole_rec_loss_enable",
                "Züge mit hohem Engine-Verlust automatisch ins höchste Level einstufen"
            )
        )
        self.chk_loss.setChecked(bool(self.current_rules.get("max_engine_loss_enabled", True)))
        loss_layout.addWidget(self.chk_loss)

        row_thresh = QHBoxLayout()
        row_thresh.setSpacing(scale(8))
        lbl_loss_thresh = QLabel(tr_ui("creator.hole_rec_loss_thresh", "Schwellenwert für Verlust:"))
        self.spin_loss = QDoubleSpinBox()
        self.spin_loss.setRange(0.10, 10.00)
        self.spin_loss.setSingleStep(0.1)
        self.spin_loss.setDecimals(2)
        self.spin_loss.setSuffix(" Bauern")
        self.spin_loss.setValue(float(self.current_rules.get("max_engine_loss", 2.0)))
        row_thresh.addWidget(lbl_loss_thresh)
        row_thresh.addWidget(self.spin_loss)
        row_thresh.addStretch()
        loss_layout.addLayout(row_thresh)

        lbl_info = QLabel(
            tr_ui(
                "creator.hole_rec_loss_info",
                "💡 Züge mit großem Verlust (z.B. ≥ 2.00 Bauern) sind taktische Fehler oder schwache Nebenvarianten. Sie werden automatisch für das höchste Level empfohlen, um die Kernlevel kompakt zu halten."
            )
        )
        lbl_info.setStyleSheet(f"color: {COLORS['light_text']}; font-style: italic; font-size: {scale(10)}px;")
        lbl_info.setWordWrap(True)
        loss_layout.addWidget(lbl_info)

        layout.addWidget(grp_loss)

        # ── Buttons ──────────────────────────────────────────
        h_btns = QHBoxLayout()
        h_btns.setSpacing(scale(8))

        btn_defaults = QPushButton(tr_ui("creator.hole_rec_btn_defaults", "Standard"))
        btn_defaults.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_defaults.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {COLORS['border']};
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: rgba(0, 0, 0, 0.05);
            }}
        """)
        btn_defaults.clicked.connect(self.restore_defaults)
        h_btns.addWidget(btn_defaults)
        h_btns.addStretch()

        btn_cancel = QPushButton(tr_ui("creator.hole_rec_btn_cancel", "Abbrechen"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {COLORS['border']};
                color: {COLORS['brown_text']};
            }}
            QPushButton:hover {{
                background-color: rgba(0, 0, 0, 0.05);
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(btn_cancel)

        btn_save = QPushButton(tr_ui("creator.hole_rec_btn_save", "Speichern"))
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                border: 1px solid {COLORS['burnt_orange']};
                color: white;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
                border-color: #e67e22;
            }}
        """)
        btn_save.clicked.connect(self.save)
        h_btns.addWidget(btn_save)

        layout.addLayout(h_btns)

    def restore_defaults(self):
        """Restores default popularity and loss settings."""
        for order, spin in self.level_spins.items():
            default_val = 1.0 if order == 1 else (0.5 if order == 2 else (0.1 if order == 3 else 0.05))
            spin.setValue(default_val)
        self.chk_loss.setChecked(True)
        self.spin_loss.setValue(2.0)

    def save(self):
        """Collects values and calls save callback."""
        new_rules = {
            "max_engine_loss_enabled": self.chk_loss.isChecked(),
            "max_engine_loss": round(self.spin_loss.value(), 2),
            "level_thresholds": {
                str(order): round(spin.value(), 2)
                for order, spin in self.level_spins.items()
            }
        }
        if self.on_save_callback:
            self.on_save_callback(new_rules)
        self.accept()
