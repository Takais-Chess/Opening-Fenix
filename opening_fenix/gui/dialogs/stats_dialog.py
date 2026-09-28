import os
from typing import Optional, Dict, Any, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QScrollArea, QWidget, QProgressBar, QFrame,
    QSizePolicy, QGridLayout, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QRectF
from PyQt6.QtGui import QFont, QColor, QPainter, QPainterPath

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS, set_consistent_icon
from opening_fenix.core.translation import tr_ui, tr_widget
from opening_fenix.core.services.statistics_service import (
    calculate_repertoire_statistics,
    get_available_profiles,
    get_profile_box_statistics
)
from opening_fenix.core.utils import get_elo_display, get_last_active_profile_name


class BoxDistributionBar(QWidget):
    """
    A segmented horizontal bar showing proportions of moves across Boxes 1-7 and Unlearned.
    """
    BOX_COLORS = {
        1: QColor("#ef4444"),  # Red (Box 1)
        2: QColor("#f97316"),  # Orange (Box 2)
        3: QColor("#f59e0b"),  # Amber (Box 3)
        4: QColor("#eab308"),  # Yellow (Box 4)
        5: QColor("#84cc16"),  # Lime (Box 5)
        6: QColor("#22c55e"),  # Green (Box 6)
        7: QColor("#10b981"),  # Emerald (Box 7)
        "unlearned": QColor("#e2e8f0")  # Slate Gray (Unlearned)
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(scale(16))
        self.box_counts: Dict[int, int] = {i: 0 for i in range(1, 8)}
        self.unlearned_count: int = 0
        self.total_trainable: int = 0

    def update_distribution(self, box_counts: Dict[int, int], unlearned: int, total_trainable: int):
        self.box_counts = dict(box_counts)
        self.unlearned_count = max(0, unlearned)
        self.total_trainable = max(0, total_trainable)

        # Build informative tooltip
        total = sum(self.box_counts.values()) + self.unlearned_count
        parts = []
        if total > 0:
            for b in range(1, 8):
                c = self.box_counts.get(b, 0)
                if c > 0:
                    pct = (c / total) * 100.0
                    parts.append(f"Box {b}: {c:,} ({pct:.1f}%)")
            if self.unlearned_count > 0:
                pct = (self.unlearned_count / total) * 100.0
                parts.append(f"{tr_ui('stats.stat_unlearned', 'Ungelernt:')} {self.unlearned_count:,} ({pct:.1f}%)")
            self.setToolTip(" • ".join(parts))
        else:
            self.setToolTip(tr_ui("stats.no_training_data", "Noch keine Züge trainiert"))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        r = h / 2.0

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        painter.setClipPath(path)

        total = sum(self.box_counts.values()) + self.unlearned_count
        if total <= 0:
            painter.fillRect(QRectF(0, 0, w, h), QColor("#f1f5f9"))
            return

        cur_x = 0.0
        for b in range(1, 8):
            cnt = self.box_counts.get(b, 0)
            if cnt > 0:
                seg_w = (cnt / total) * w
                painter.fillRect(QRectF(cur_x, 0, seg_w, h), self.BOX_COLORS[b])
                cur_x += seg_w

        if self.unlearned_count > 0:
            seg_w = (self.unlearned_count / total) * w
            painter.fillRect(QRectF(cur_x, 0, seg_w, h), self.BOX_COLORS["unlearned"])


class StatisticsWorker(QThread):
    """Background worker to calculate statistics without blocking the GUI."""
    stats_ready = pyqtSignal(dict)

    def __init__(self, repo_name: str, is_test: Optional[bool] = None, elo_range: Optional[str] = None, profile_name: Optional[str] = None):
        super().__init__()
        self.repo_name = repo_name
        self.is_test = is_test
        self.elo_range = elo_range
        self.profile_name = profile_name

    def run(self):
        data = calculate_repertoire_statistics(self.repo_name, self.is_test, self.elo_range, self.profile_name)
        self.stats_ready.emit(data)


class RepertoireStatisticsDialog(QDialog):
    """
    Dedicated Pop-Up Dialog presenting comprehensive repertoire statistics:
    - Scope detection (e.g. specialized against 1.e4 vs complete repertoire)
    - 3 Key score badges: Effectiveness, Soundness, and Learnability
    - Repertoire size breakdown by Level (Level 1, Level 2, Level 3, Total)
    - Profile Leitner box breakdown (Boxes 1-7, unlearned, due moves)
    - 1-step interval opponent coverage curve (Move 1, 2, 3...)
    """
    def __init__(self, parent=None, repo_name: str = "", is_test: Optional[bool] = None, profile_name: Optional[str] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("stats.window_title", "Repertoire-Statistiken & Insights"))
        self.setMinimumSize(scale(820), scale(700))
        self.resize(scale(880), scale(760))

        self.repo_name = repo_name
        self.is_test = is_test
        self.selected_profile = profile_name or get_last_active_profile_name()
        self.worker: Optional[StatisticsWorker] = None
        self.box_tile_widgets: Dict[int, Tuple[QFrame, QLabel, QLabel, QLabel]] = {}

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

        # --- SCROLLABLE DASHBOARD CONTENT ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, scale(4), scale(6), 0)
        content_layout.setSpacing(scale(14))

        # --- 2. TOP METRIC SECTION ---
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(scale(12))

        # 1. Effectiveness Card (Blue accent)
        self.card_eff, self.lbl_eff_val, self.lbl_eff_sub = self._create_metric_card(
            title=tr_ui("stats.card_eff_title", "EFFEKTIVITÄT").upper(),
            default_val="--%",
            default_sub=tr_ui("stats.card_eff_sub", "Erwartete Punktzahl"),
            accent_color="#3b82f6"
        )
        cards_layout.addWidget(self.card_eff, 1)

        # 2. In-Progress / Placeholder Card (replaces Solidität & Lernaufwand)
        self.card_wip = QFrame()
        self.card_wip.setObjectName("WipCard")
        self.card_wip.setFixedHeight(scale(115))
        self.card_wip.setStyleSheet(f"""
            QFrame#WipCard {{
                background-color: #f8fafc;
                border: 1px dashed #cbd5e1;
                border-radius: {scale(10)}px;
                padding: {scale(12)}px;
            }}
            QFrame#WipCard QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        wip_layout = QVBoxLayout(self.card_wip)
        wip_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wip_layout.setSpacing(scale(6))

        lbl_wip_icon = QLabel("🚧")
        lbl_wip_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_wip_icon.setStyleSheet(f"font-size: {scale(22)}px; border: none; background: transparent;")
        wip_layout.addWidget(lbl_wip_icon)

        lbl_wip_text = QLabel(
            tr_ui(
                "stats.wip_notice",
                "(Diese Seite ist noch nicht vollständig und folgt in einem späteren Update)"
            )
        )
        lbl_wip_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_wip_text.setWordWrap(True)
        lbl_wip_text.setStyleSheet(f"""
            font-size: {scale(12)}px;
            font-weight: 600;
            color: #64748b;
        """)
        wip_layout.addWidget(lbl_wip_text)

        cards_layout.addWidget(self.card_wip, 2)

        content_layout.addLayout(cards_layout)

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

        content_layout.addWidget(grp_levels)

        # --- 4. PROFILE LEITNER BOXES GROUP ---
        self.grp_boxes = QGroupBox(f"🗃️  {tr_widget('stats.box_distribution_group', 'Trainings-Fortschritt & Leitner-Boxen nach Profil')}")
        layout_boxes = QVBoxLayout(self.grp_boxes)
        layout_boxes.setContentsMargins(scale(16), scale(14), scale(16), scale(14))
        layout_boxes.setSpacing(scale(10))

        # Top Profile, Level & KPI Row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(scale(8))

        lbl_prof = QLabel(tr_ui("stats.profile_label", "Profil:"))
        lbl_prof.setStyleSheet(f"font-size: {scale(12)}px; font-weight: 700; color: #334155; border: none; background: transparent;")
        ctrl_row.addWidget(lbl_prof)

        self.combo_profile = QComboBox()
        self.combo_profile.setFixedHeight(scale(32))
        self.combo_profile.setMinimumWidth(scale(130))
        self.combo_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_profile.setStyleSheet(f"""
            QComboBox {{
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: {scale(6)}px;
                padding: 0 {scale(10)}px;
                font-weight: 600;
                font-size: {scale(12)}px;
            }}
            QComboBox:hover {{
                border-color: #94a3b8;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {scale(20)}px;
            }}
        """)

        # Populate profiles
        available_profiles = get_available_profiles()
        self.combo_profile.addItems(available_profiles)

        if self.selected_profile and self.selected_profile in available_profiles:
            self.combo_profile.setCurrentText(self.selected_profile)
        elif available_profiles:
            self.selected_profile = available_profiles[0]
            self.combo_profile.setCurrentIndex(0)

        self.combo_profile.currentTextChanged.connect(self._on_profile_selected)
        ctrl_row.addWidget(self.combo_profile)

        # Level selector
        self.lbl_level = QLabel(tr_ui("stats.level_label", "Stufe:"))
        self.lbl_level.setStyleSheet(f"font-size: {scale(12)}px; font-weight: 700; color: #334155; border: none; background: transparent;")
        ctrl_row.addWidget(self.lbl_level)

        self.combo_level = QComboBox()
        self.combo_level.setFixedHeight(scale(32))
        self.combo_level.setMinimumWidth(scale(165))
        self.combo_level.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_level.setStyleSheet(f"""
            QComboBox {{
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: {scale(6)}px;
                padding: 0 {scale(10)}px;
                font-weight: 600;
                font-size: {scale(12)}px;
            }}
            QComboBox:hover {{
                border-color: #94a3b8;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {scale(20)}px;
            }}
        """)
        self.combo_level.currentIndexChanged.connect(self._on_level_selected)
        ctrl_row.addWidget(self.combo_level)

        ctrl_row.addSpacing(scale(4))

        # KPI Badges: Elo, Learned, Due, Unlearned
        self.lbl_stat_elo = self._create_kpi_badge("🎓", tr_ui("stats.stat_elo", "Elo:"), "--")
        self.lbl_stat_learned = self._create_kpi_badge("🎯", tr_ui("stats.stat_learned", "Gelernt:"), "--")
        self.lbl_stat_due = self._create_kpi_badge("⏳", tr_ui("stats.stat_due", "Fällig:"), "--")
        self.lbl_stat_unlearned = self._create_kpi_badge("⚪", tr_ui("stats.stat_unlearned", "Ungelernt:"), "--")

        ctrl_row.addWidget(self.lbl_stat_elo)
        ctrl_row.addWidget(self.lbl_stat_learned)
        ctrl_row.addWidget(self.lbl_stat_due)
        ctrl_row.addWidget(self.lbl_stat_unlearned)
        ctrl_row.addStretch()

        layout_boxes.addLayout(ctrl_row)

        # Leitner Box 1..7 Cards Row
        self.boxes_row = QHBoxLayout()
        self.boxes_row.setSpacing(scale(8))

        colors = [
            "#ef4444",  # Box 1 (Red)
            "#f97316",  # Box 2 (Orange)
            "#f59e0b",  # Box 3 (Amber)
            "#eab308",  # Box 4 (Yellow)
            "#84cc16",  # Box 5 (Lime)
            "#22c55e",  # Box 6 (Green)
            "#10b981",  # Box 7 (Emerald)
        ]
        default_intervals = ["5m", "1d", "3d", "9d", "21d", "63d", "180d"]

        for b in range(1, 8):
            tile, lbl_cnt, lbl_due, lbl_int = self._create_box_tile(
                box_num=b,
                default_interval=default_intervals[b-1],
                color_hex=colors[b-1]
            )
            self.box_tile_widgets[b] = (tile, lbl_cnt, lbl_due, lbl_int)
            self.boxes_row.addWidget(tile, 1)

        layout_boxes.addLayout(self.boxes_row)

        # Visual Segmented Distribution Bar
        self.dist_bar = BoxDistributionBar()
        layout_boxes.addWidget(self.dist_bar)

        content_layout.addWidget(self.grp_boxes)

        # --- 5. PRACTICAL REPERTOIRE COVERAGE PLACEHOLDER ---
        grp_cov = QGroupBox(f"📊  {tr_ui('stats.coverage_group', 'Repertoire-Abdeckung in der Praxis')}")
        layout_cov = QVBoxLayout(grp_cov)
        layout_cov.setContentsMargins(scale(16), scale(12), scale(16), scale(12))
        layout_cov.setSpacing(scale(6))

        card_placeholder = QFrame()
        card_placeholder.setObjectName("PlaceholderCard")
        card_placeholder.setStyleSheet(f"""
            QFrame#PlaceholderCard {{
                background-color: #f8fafc;
                border: 1px dashed #cbd5e1;
                border-radius: {scale(8)}px;
                padding: {scale(10)}px {scale(14)}px;
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
        content_layout.addWidget(grp_cov)

        self.scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.scroll_area, 1)

        # --- 6. BOTTOM BUTTON BAR ---
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
        tile.setMinimumHeight(scale(56))
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

    def _create_kpi_badge(self, icon: str, label_text: str, default_val: str) -> QLabel:
        lbl = QLabel(f"{icon} {label_text} <b>{default_val}</b>")
        lbl.setStyleSheet(f"""
            QLabel {{
                font-size: {scale(11)}px;
                color: #334155;
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: {scale(6)}px;
                padding: {scale(4)}px {scale(8)}px;
            }}
        """)
        return lbl

    def _create_box_tile(self, box_num: int, default_interval: str, color_hex: str):
        tile = QFrame()
        tile.setObjectName(f"BoxTile_{box_num}")
        tile.setFixedHeight(scale(76))
        tile.setStyleSheet(f"""
            QFrame#BoxTile_{box_num} {{
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: {scale(8)}px;
            }}
            QFrame#BoxTile_{box_num} QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(scale(8), 0, scale(8), scale(6))
        layout.setSpacing(scale(2))

        # Colored top bar
        top_bar = QFrame()
        top_bar.setFixedHeight(scale(3))
        top_bar.setStyleSheet(f"""
            background-color: {color_hex};
            border-top-left-radius: {scale(7)}px;
            border-top-right-radius: {scale(7)}px;
            border: none;
        """)
        layout.addWidget(top_bar)
        layout.addSpacing(scale(3))

        # Header: Box X on left, interval on right
        h_box = QHBoxLayout()
        h_box.setSpacing(scale(4))
        lbl_b = QLabel(f"Box {box_num}")
        lbl_b.setStyleSheet(f"font-size: {scale(11)}px; font-weight: 700; color: #475569;")
        h_box.addWidget(lbl_b)
        h_box.addStretch()
        lbl_int = QLabel(default_interval)
        lbl_int.setStyleSheet(f"font-size: {scale(10)}px; color: #94a3b8; font-weight: 500;")
        h_box.addWidget(lbl_int)
        layout.addLayout(h_box)

        # Main count
        lbl_cnt = QLabel("--")
        lbl_cnt.setStyleSheet(f"font-size: {scale(16)}px; font-weight: 800; color: #0f172a;")
        layout.addWidget(lbl_cnt)

        # Due sub-label
        lbl_due = QLabel("0 " + tr_ui("stats.due_suffix", "fällig"))
        lbl_due.setStyleSheet(f"font-size: {scale(10)}px; font-weight: 500; color: #94a3b8;")
        layout.addWidget(lbl_due)

        layout.addStretch()
        return tile, lbl_cnt, lbl_due, lbl_int

    def _on_profile_selected(self, profile_name: str):
        if not profile_name:
            return
        self.selected_profile = profile_name
        self.load_profile_box_statistics(profile_name, level_filter=None)

    def _on_level_selected(self, idx: int):
        if not hasattr(self, 'combo_level') or self.combo_level.signalsBlocked():
            return
        lvl = self.combo_level.currentData()
        active_prof = self.combo_profile.currentText() if hasattr(self, 'combo_profile') else self.selected_profile
        self.load_profile_box_statistics(active_prof, level_filter=lvl)

    def load_profile_box_statistics(self, profile_name: str, level_filter: Optional[int] = None):
        if not profile_name or not self.repo_name:
            return
        prof_data = get_profile_box_statistics(self.repo_name, profile_name, self.is_test, selected_level=level_filter)
        self.update_profile_box_ui(prof_data)

    def update_profile_box_ui(self, prof_data: Dict[str, Any]):
        if not prof_data:
            return

        tot_trainable = prof_data.get("total_trainable", 0)
        tot_learned = prof_data.get("total_learned", 0)
        tot_unlearned = prof_data.get("total_unlearned", 0)
        tot_due = prof_data.get("total_due", 0)
        learned_pct = prof_data.get("learned_pct", 0.0)
        box_counts = prof_data.get("box_counts", {})
        box_due_counts = prof_data.get("box_due_counts", {})
        box_intervals_short = prof_data.get("box_intervals_short", {})
        avail_levels = prof_data.get("available_levels", [])
        active_lvl = prof_data.get("active_level", 1)
        selected_lvl = prof_data.get("selected_level")
        rating = prof_data.get("rating", 800)

        # Update Level selector if available
        if hasattr(self, 'combo_level') and avail_levels:
            self.combo_level.blockSignals(True)
            prev_data = self.combo_level.currentData() if self.combo_level.count() > 0 else None
            self.combo_level.clear()
            self.combo_level.addItem(tr_ui("stats.all_levels", "Alle Stufen (Gesamt)"), None)
            
            select_idx = 0
            for i, ld in enumerate(avail_levels):
                ord_num = ld.get("order", 1)
                name = ld.get("name", f"Level {ord_num}")
                m_cnt = ld.get("moves", 0)
                item_label = tr_ui("stats.level_fmt", f"Stufe {ord_num}: {name} ({m_cnt} Züge)", order=ord_num, name=name, count=m_cnt)
                self.combo_level.addItem(item_label, ord_num)

                if selected_lvl is not None and selected_lvl == ord_num:
                    select_idx = i + 1
                elif selected_lvl is None and prev_data is not None and prev_data == ord_num:
                    select_idx = i + 1

            self.combo_level.setCurrentIndex(select_idx)
            self.combo_level.blockSignals(False)
            self.combo_level.setVisible(True)
            if hasattr(self, 'lbl_level'):
                self.lbl_level.setVisible(True)

        # KPI labels
        if hasattr(self, 'lbl_stat_elo'):
            self.lbl_stat_elo.setText(f"🎓 {tr_ui('stats.stat_elo', 'Elo:')} <b>{rating:,}</b>")
        self.lbl_stat_learned.setText(
            f"🎯 {tr_ui('stats.stat_learned', 'Gelernt:')} <b>{tot_learned:,}</b> / {tot_trainable:,} ({learned_pct:.1f}%)"
        )
        self.lbl_stat_due.setText(
            f"⏳ {tr_ui('stats.stat_due', 'Fällig:')} <b>{tot_due:,}</b>"
        )
        self.lbl_stat_unlearned.setText(
            f"⚪ {tr_ui('stats.stat_unlearned', 'Ungelernt:')} <b>{tot_unlearned:,}</b>"
        )

        # Update tiles 1..7
        due_suffix = tr_ui("stats.due_suffix", "fällig")
        for b in range(1, 8):
            if b in self.box_tile_widgets:
                _, lbl_cnt, lbl_due, lbl_int = self.box_tile_widgets[b]
                cnt = box_counts.get(b, 0)
                due = box_due_counts.get(b, 0)
                interval_str = box_intervals_short.get(b, "")
                if interval_str:
                    lbl_int.setText(interval_str)
                lbl_cnt.setText(f"{cnt:,}")
                if due > 0:
                    lbl_due.setText(f"{due:,} {due_suffix}")
                    lbl_due.setStyleSheet(f"font-size: {scale(10)}px; font-weight: 600; color: #d97706; border: none; background: transparent;")
                else:
                    lbl_due.setText(f"0 {due_suffix}")
                    lbl_due.setStyleSheet(f"font-size: {scale(10)}px; font-weight: 500; color: #94a3b8; border: none; background: transparent;")

        # Update distribution bar
        self.dist_bar.update_distribution(box_counts, tot_unlearned, tot_trainable)

    def load_statistics(self):
        """Starts background worker to calculate statistics."""
        self.btn_refresh.setEnabled(False)
        self.lbl_scope.setText(tr_ui("stats.calculating", "⏳ Statistiken werden berechnet..."))

        active_prof = self.combo_profile.currentText() if hasattr(self, 'combo_profile') else self.selected_profile
        self.worker = StatisticsWorker(self.repo_name, self.is_test, profile_name=active_prof)
        self.worker.stats_ready.connect(self.on_statistics_ready)
        self.worker.start()

        lvl = self.combo_level.currentData() if hasattr(self, 'combo_level') and self.combo_level.count() > 0 else None
        if active_prof:
            self.load_profile_box_statistics(active_prof, level_filter=lvl)

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

        # 4. Profile Box Stats (if included)
        if "profile_stats" in data and data["profile_stats"]:
            self.update_profile_box_ui(data["profile_stats"])