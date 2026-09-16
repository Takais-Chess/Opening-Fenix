import os
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QScrollArea, QWidget, QProgressBar, QFrame,
    QSizePolicy, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon
from opening_fenix.core.translation import tr_ui
from opening_fenix.core.services.statistics_service import calculate_repertoire_statistics
from opening_fenix.core.utils import get_elo_display


class StatisticsWorker(QThread):
    """Background worker to calculate statistics without blocking the GUI."""
    stats_ready = pyqtSignal(dict)

    def __init__(self, repo_name: str, is_test: Optional[bool] = None, elo_range: Optional[str] = None):
        super().__init__()
        self.repo_name = repo_name
        self.is_test = is_test
        self.elo_range = elo_range

    def run(self):
        data = calculate_repertoire_statistics(self.repo_name, self.is_test, self.elo_range)
        self.stats_ready.emit(data)


class RepertoireStatisticsDialog(QDialog):
    """
    Dedicated Pop-Up Dialog presenting comprehensive repertoire statistics:
    - Scope detection (e.g. specialized against 1.e4 vs complete repertoire)
    - 3 Key score badges: Effectiveness, Soundness, and Learnability
    - Repertoire size breakdown by Level (Level 1, Level 2, Level 3, Total)
    - 1-step interval opponent coverage curve (Move 1, 2, 3...)
    """
    def __init__(self, parent=None, repo_name: str = "", is_test: Optional[bool] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("stats.window_title", "Repertoire-Statistiken & Insights"))
        self.setMinimumSize(scale(660), scale(540))
        self.resize(scale(700), scale(580))

        self.repo_name = repo_name
        self.is_test = is_test
        self.worker: Optional[StatisticsWorker] = None

        self.init_ui()
        self.load_statistics()

    def init_ui(self):
        # Global stylesheet scoped strictly to specific widgets to prevent CSS inheritance bugs
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #f8fafc;
            }}
            QGroupBox {{
                font-weight: 700;
                font-size: {scale(13)}px;
                border: 1px solid #e2e8f0;
                border-radius: {scale(10)}px;
                margin-top: {scale(12)}px;
                padding-top: {scale(16)}px;
                background-color: #ffffff;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {scale(14)}px;
                padding: 0 {scale(8)}px;
                color: #1e293b;
            }}
            QProgressBar {{
                border: 1px solid #e2e8f0;
                border-radius: {scale(5)}px;
                text-align: center;
                background-color: #f1f5f9;
            }}
            QProgressBar::chunk {{
                border-radius: {scale(4)}px;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                border: none;
                background: #f1f5f9;
                width: 8px;
                border-radius: 4px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: #cbd5e1;
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #94a3b8;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scale(24), scale(20), scale(24), scale(20))
        main_layout.setSpacing(scale(14))

        # --- 1. HEADER SECTION ---
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(scale(6))

        self.lbl_title = QLabel(f"📊 {self.repo_name}")
        self.lbl_title.setStyleSheet(f"""
            QLabel {{
                font-size: {scale(22)}px;
                font-weight: 800;
                color: #0f172a;
                border: none;
                background: transparent;
            }}
        """)
        header_layout.addWidget(self.lbl_title)

        # Sleek Scope Tag (Pill style)
        self.scope_frame = QFrame()
        self.scope_frame.setObjectName("ScopeFrame")
        self.scope_frame.setStyleSheet(f"""
            QFrame#ScopeFrame {{
                background-color: #eff6ff;
                border: 1px solid #bfdbfe;
                border-radius: {scale(8)}px;
            }}
            QFrame#ScopeFrame QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        scope_layout = QHBoxLayout(self.scope_frame)
        scope_layout.setContentsMargins(scale(12), scale(6), scale(12), scale(6))
        
        self.lbl_scope = QLabel(tr_ui("stats.scope_detecting", "🎯 Eröffnungs-Fokus: Wird analysiert..."))
        self.lbl_scope.setStyleSheet(f"font-size: {scale(12)}px; color: #1d4ed8; font-weight: 600;")
        scope_layout.addWidget(self.lbl_scope)
        scope_layout.addStretch()
        header_layout.addWidget(self.scope_frame)

        main_layout.addWidget(header_widget)

        # --- 2. THE 3 TOP METRIC CARDS ---
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(scale(12))

        # 1. Effectiveness Card (Blue accent)
        self.card_eff, self.lbl_eff_val, self.lbl_eff_sub = self._create_metric_card(
            title=tr_ui("stats.card_eff_title", "EFFEKTIVITÄT").upper(),
            default_val="--%",
            default_sub=tr_ui("stats.card_eff_sub", "Erwartete Punktzahl"),
            accent_color="#3b82f6"
        )
        cards_layout.addWidget(self.card_eff)

        # 2. Soundness Card (Green accent)
        self.card_snd, self.lbl_snd_val, self.lbl_snd_sub = self._create_metric_card(
            title=tr_ui("stats.card_snd_title", "SOLIDITÄT").upper(),
            default_val="-- / 100",
            default_sub=tr_ui("stats.card_snd_sub", "Stockfish-Qualität"),
            accent_color="#10b981"
        )
        cards_layout.addWidget(self.card_snd)

        # 3. Learnability Card (Purple accent)
        self.card_lrn, self.lbl_lrn_val, self.lbl_lrn_sub = self._create_metric_card(
            title=tr_ui("stats.card_lrn_title", "LERNAUFWAND").upper(),
            default_val="--",
            default_sub=tr_ui("stats.card_lrn_sub", "Speicherumfang"),
            accent_color="#8b5cf6"
        )
        cards_layout.addWidget(self.card_lrn)

        main_layout.addLayout(cards_layout)

        # --- 3. REPERTOIRE SIZE BY LEVEL (Dynamic level tiles + summary) ---
        grp_levels = QGroupBox(f"📁  {tr_ui('stats.levels_group', 'Repertoire-Größe nach Stufen')}")
        layout_levels = QVBoxLayout(grp_levels)
        layout_levels.setContentsMargins(scale(16), scale(14), scale(16), scale(14))
        layout_levels.setSpacing(scale(10))

        # Tiles layout for dynamic Level 1, 2, 3...
        self.tiles_layout = QHBoxLayout()
        self.tiles_layout.setSpacing(scale(10))

        self.tile_l1, self.lbl_l1_val = self._create_level_tile("Level 1")
        self.tile_l2, self.lbl_l2_val = self._create_level_tile("Level 2")
        self.tile_l3, self.lbl_l3_val = self._create_level_tile("Level 3")

        self.tiles_layout.addWidget(self.tile_l1)
        self.tiles_layout.addWidget(self.tile_l2)
        self.tiles_layout.addWidget(self.tile_l3)
        layout_levels.addLayout(self.tiles_layout)

        # Summary footer bar
        self.lbl_total_summary = QLabel("• <b>Gesamt-Stellungen:</b> --")
        self.lbl_total_summary.setStyleSheet(f"""
            QLabel {{
                font-size: {scale(12)}px;
                color: #334155;
                padding: {scale(4)}px {scale(8)}px;
                border: none;
                background: transparent;
            }}
        """)
        layout_levels.addWidget(self.lbl_total_summary)

        main_layout.addWidget(grp_levels)

        # --- 4. PRACTICAL REPERTOIRE COVERAGE PLACEHOLDER ---
        grp_cov = QGroupBox(f"📊  {tr_ui('stats.coverage_group', 'Repertoire-Abdeckung in der Praxis')}")
        layout_cov = QVBoxLayout(grp_cov)
        layout_cov.setContentsMargins(scale(16), scale(16), scale(16), scale(16))
        layout_cov.setSpacing(scale(8))

        card_placeholder = QFrame()
        card_placeholder.setObjectName("PlaceholderCard")
        card_placeholder.setStyleSheet(f"""
            QFrame#PlaceholderCard {{
                background-color: #f8fafc;
                border: 1px dashed #cbd5e1;
                border-radius: {scale(8)}px;
                padding: {scale(16)}px;
            }}
            QFrame#PlaceholderCard QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        ph_layout = QVBoxLayout(card_placeholder)
        ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_layout.setSpacing(scale(6))

        lbl_ph_icon = QLabel("🛡️")
        lbl_ph_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_ph_icon.setStyleSheet(f"font-size: {scale(26)}px; border: none; background: transparent;")
        ph_layout.addWidget(lbl_ph_icon)

        lbl_ph_title = QLabel(tr_ui("stats.coverage_placeholder_title", "Praxis-Abdeckung & Lückenerkennung"))
        lbl_ph_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_ph_title.setStyleSheet(f"font-size: {scale(13)}px; font-weight: 700; color: #1e293b;")
        ph_layout.addWidget(lbl_ph_title)

        desc_text = tr_ui(
            "stats.coverage_placeholder_desc",
            "Hier kommen demnächst Statistiken dazu, wie abdeckend dein Repertoire in der Praxis ist..."
        )
        note_text = tr_ui(
            "stats.coverage_placeholder_note",
            "Analysiert reale Gegner-Häufigkeiten für deine Varianten und hebt die wichtigsten Ausbau-Züge hervor."
        )

        lbl_ph_body = QLabel(
            f"<div style='font-size: {scale(12)}px; color: #64748b; line-height: 140%; margin-top: {scale(2)}px;'>"
            f"{desc_text}</div>"
            f"<div style='font-size: {scale(11)}px; color: #94a3b8; font-style: italic; line-height: 140%; margin-top: {scale(6)}px;'>"
            f"{note_text}</div>"
        )
        lbl_ph_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_ph_body.setWordWrap(True)
        lbl_ph_body.setStyleSheet("border: none; background: transparent;")
        ph_layout.addWidget(lbl_ph_body)

        layout_cov.addWidget(card_placeholder)
        main_layout.addWidget(grp_cov)

        # --- 5. BOTTOM BUTTON BAR ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(scale(12))

        self.btn_refresh = QPushButton(f"🔄  {tr_ui('stats.btn_refresh', 'Neu berechnen')}")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setFixedHeight(scale(38))
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: #ffffff;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: {scale(8)}px;
                font-weight: 600;
                font-size: {scale(13)}px;
                padding: 0 {scale(16)}px;
            }}
            QPushButton:hover {{
                background-color: #f1f5f9;
                border-color: #94a3b8;
            }}
        """)
        self.btn_refresh.clicked.connect(self.load_statistics)
        btn_layout.addWidget(self.btn_refresh)

        btn_layout.addStretch()

        self.btn_close = QPushButton(tr_ui("stats.btn_close", "Schließen"))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFixedHeight(scale(38))
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: #0f172a;
                color: #ffffff;
                border: none;
                border-radius: {scale(8)}px;
                font-weight: 600;
                font-size: {scale(13)}px;
                padding: 0 {scale(26)}px;
            }}
            QPushButton:hover {{
                background-color: #1e293b;
            }}
        """)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)

        main_layout.addLayout(btn_layout)

    def _create_metric_card(self, title: str, default_val: str, default_sub: str, accent_color: str):
        """Creates a modern elevated metric card with top color strip and no inner label borders."""
        card = QFrame()
        card.setObjectName("MetricCard")
        card.setFixedHeight(scale(115))
        card.setStyleSheet(f"""
            QFrame#MetricCard {{
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: {scale(10)}px;
            }}
            QFrame#MetricCard QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(scale(14), 0, scale(14), scale(12))
        layout.setSpacing(scale(2))

        # Colored top bar
        top_bar = QFrame()
        top_bar.setFixedHeight(scale(4))
        top_bar.setStyleSheet(f"""
            background-color: {accent_color};
            border-top-left-radius: {scale(9)}px;
            border-top-right-radius: {scale(9)}px;
            border: none;
        """)
        layout.addWidget(top_bar)
        layout.addSpacing(scale(6))

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(f"font-size: {scale(11)}px; font-weight: 700; color: #64748b; letter-spacing: 0.5px;")
        layout.addWidget(lbl_t)

        lbl_v = QLabel(default_val)
        lbl_v.setStyleSheet(f"font-size: {scale(24)}px; font-weight: 800; color: #0f172a;")
        layout.addWidget(lbl_v)

        lbl_s = QLabel(default_sub)
        lbl_s.setStyleSheet(f"font-size: {scale(11)}px; color: #94a3b8;")
        layout.addWidget(lbl_s)

        layout.addStretch()
        return card, lbl_v, lbl_s

    def _create_level_tile(self, level_name: str):
        """Creates a clean sub-tile for a level without charts."""
        tile = QFrame()
        tile.setObjectName("LevelTile")
        tile.setStyleSheet(f"""
            QFrame#LevelTile {{
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: {scale(8)}px;
            }}
            QFrame#LevelTile QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(scale(12), scale(8), scale(12), scale(8))
        layout.setSpacing(scale(2))

        lbl_title = QLabel(level_name)
        lbl_title.setStyleSheet(f"font-size: {scale(11)}px; font-weight: 600; color: #64748b;")
        layout.addWidget(lbl_title)

        lbl_val = QLabel("--")
        lbl_val.setStyleSheet(f"font-size: {scale(15)}px; font-weight: 700; color: #1e293b;")
        layout.addWidget(lbl_val)

        return tile, lbl_val

    def load_statistics(self):
        """Starts background worker to calculate statistics."""
        self.btn_refresh.setEnabled(False)
        self.lbl_scope.setText(tr_ui("stats.calculating", "⏳ Statistiken werden berechnet..."))

        self.worker = StatisticsWorker(self.repo_name, self.is_test)
        self.worker.stats_ready.connect(self.on_statistics_ready)
        self.worker.start()

    def on_statistics_ready(self, data: Dict[str, Any]):
        """Populates the dialog UI with the calculated statistics data."""
        self.btn_refresh.setEnabled(True)

        # 1. Scope Banner
        scope = data.get("scope", {})
        scope_name = scope.get("name", tr_ui("stats.scope_full", "Gesamtes Repertoire"))
        freq = scope.get("global_freq", 100.0)
        is_spec = scope.get("is_specialized", False)

        if is_spec:
            self.lbl_scope.setText(
                f"🎯 <b>{tr_ui('stats.scope_focus', 'Eröffnungs-Fokus:')}</b> {scope_name} "
                f"<span style='color: #64748b; font-size: {scale(11)}px;'>• {tr_ui('stats.all_games_fmt', '{freq}% aller Lichess-Partien', freq=freq)}</span>"
            )
        else:
            self.lbl_scope.setText(f"🌐 <b>{tr_ui('stats.scope_focus', 'Repertoire-Umfang:')}</b> {scope_name}")

        # 2. Metric Badges
        eff = data.get("effectiveness", {})
        win_rate = eff.get("win_rate", 50.0)
        self.lbl_eff_val.setText(f"{win_rate:.1f}%")
        self.lbl_eff_sub.setText(f"{tr_ui('stats.expected_score', 'Erwartete Punktzahl')} (Lichess)")

        snd = data.get("soundness", {})
        score = snd.get("score", 90)
        self.lbl_snd_val.setText(f"{score} / 100")
        eval_count = snd.get("evaluated_count", 0)
        self.lbl_snd_sub.setText(f"{eval_count} {tr_ui('stats.positions_evaluated', 'Stellungen bewertet')}")

        lrn = data.get("learnability", {})
        tier = lrn.get("tier", tr_ui("stats.learn_moderate", "Moderat"))
        self.lbl_lrn_val.setText(tier)
        total_p = data.get("levels", {}).get("total_positions", 0)
        self.lbl_lrn_sub.setText(f"{total_p:,} {tr_ui('stats.total_pos_sub', 'Repertoire-Stellungen')}")

        # 3. Levels Breakdown (Dynamic Tiles + Summary footer)
        lvls = data.get("levels", {})
        levels_list = lvls.get("list", [])
        tot_pos = lvls.get("total_positions", 0)
        tot_moves = lvls.get("total_moves", 0)
        pos_str = tr_ui('stats.positions', 'Stellungen')

        # Rebuild dynamic tiles in layout
        while self.tiles_layout.count() > 0:
            child = self.tiles_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if levels_list:
            for lvl_item in levels_list:
                display_name = lvl_item.get("display_name", f"Level {lvl_item.get('order', 1)}")
                tile, lbl_val = self._create_level_tile(display_name)
                lbl_val.setText(f"{lvl_item.get('count', 0):,} {pos_str}")
                self.tiles_layout.addWidget(tile)
        else:
            l1 = lvls.get("level_1", 0)
            l2 = lvls.get("level_2", 0)
            l3 = lvls.get("level_3", 0)
            for order, name, cnt in [
                (1, tr_ui("repo_settings.level_default_1", "Grundlagen"), l1),
                (2, tr_ui("repo_settings.level_default_2", "Tiefe Theorie"), l2),
                (3, tr_ui("repo_settings.level_default_3", "Nachschlagewerk und Erklärungen"), l3)
            ]:
                tile, lbl_val = self._create_level_tile(f"Level {order} (\"{name}\")")
                lbl_val.setText(f"{cnt:,} {pos_str}")
                self.tiles_layout.addWidget(tile)

        self.lbl_total_summary.setText(
            f"📦 <b>{tr_ui('stats.total_positions', 'Gesamt-Stellungen:')}</b> {tot_pos:,} {pos_str}  "
            f"<span style='color: #64748b;'>({tot_moves:,} {tr_ui('stats.active_moves', 'aktive Züge')})</span>"
        )