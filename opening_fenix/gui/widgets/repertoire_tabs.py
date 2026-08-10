import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QScrollArea, QFrame, QButtonGroup, 
    QLabel, QMenu, QGraphicsDropShadowEffect, QScroller
)
from PyQt6.QtGui import QIcon, QAction, QColor
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QSize, QTimer

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS

class RepertoireTabsWidget(QWidget):
    """
    The top bar widget containing repertoire selection tabs, 
    filter, elo display, profile switch, and settings.
    """
    repertoire_changed = pyqtSignal(str)
    filter_changed = pyqtSignal(str)
    settings_requested = pyqtSignal()
    profile_switch_requested = pyqtSignal()
    resources_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sorted_repo_names = None
        self.init_ui()

    def init_ui(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 6, 20, 6)
        self.layout.setSpacing(scale(14))

        # --- Repertoire Scroll Area ---
        self.btn_scroll_left = QPushButton("◄")
        self.btn_scroll_left.setFixedSize(scale(30), scale(40))
        self.btn_scroll_left.setStyleSheet(f"border: none; background: transparent; color: #8d6e63; font-size: {scale(18)}px;")
        self.btn_scroll_left.clicked.connect(self.scroll_tabs_left)
        self.btn_scroll_left.hide()

        self.btn_scroll_right = QPushButton("►")
        self.btn_scroll_right.setFixedSize(scale(30), scale(40))
        self.btn_scroll_right.setStyleSheet(f"border: none; background: transparent; color: #8d6e63; font-size: {scale(18)}px;")
        self.btn_scroll_right.clicked.connect(self.scroll_tabs_right)
        self.btn_scroll_right.hide()

        self.repo_scroll = QScrollArea()
        self.repo_scroll.setWidgetResizable(True)
        self.repo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.repo_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.repo_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.repo_scroll.setProperty("class", "GlassPill")
        
        self.repo_tabs_widget = QWidget()
        self.repo_tabs_widget.setStyleSheet("background: transparent;")
        self.repo_tabs_layout = QHBoxLayout(self.repo_tabs_widget)
        self.repo_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.repo_tabs_layout.setSpacing(15)
        
        self.repo_button_group = QButtonGroup(self)
        self.repo_button_group.buttonClicked.connect(self._on_button_clicked)
        
        self.repo_scroll.setWidget(self.repo_tabs_widget)
        QScroller.grabGesture(self.repo_scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        self.repo_scroll.horizontalScrollBar().valueChanged.connect(self.update_tab_scroll_arrows)

        self.layout.addWidget(self.btn_scroll_left)
        self.layout.addWidget(self.repo_scroll, 1)
        self.layout.addWidget(self.btn_scroll_right)

        # --- Right Side Actions ---
        self.right_container = QWidget()
        self.right_container.setProperty("class", "GlassPill")
        self.right_layout = QHBoxLayout(self.right_container)
        self.right_layout.setSpacing(15)
        self.right_layout.setContentsMargins(15, 0, 15, 0)

        self.btn_filter = QPushButton(tr_ui("main.btn_filter", "Filter ▾"))
        self.btn_filter.setFlat(True)
        self.btn_filter.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: {scale(14)}px; border-radius: {scale(18)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)

        self.lbl_elo = QLabel("🎓 800")
        self.lbl_elo.setStyleSheet(f"font-size: {scale(20)}px; color: {COLORS['burnt_orange']}; font-weight: bold;")

        self.btn_profile = QPushButton(tr_ui("main.btn_profile", "Profil"))
        self.btn_profile.setFlat(True)
        self.btn_profile.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: {scale(14)}px; border-radius: {scale(18)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_profile.clicked.connect(self.profile_switch_requested.emit)

        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setFixedSize(scale(40), scale(40))
        self.btn_settings.setStyleSheet(f"""
            QPushButton {{ font-size: {scale(24)}px; border: none; background: transparent; border-radius: {scale(20)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_settings.clicked.connect(self.settings_requested.emit)

        self.right_layout.addWidget(self.btn_filter)
        self.right_layout.addWidget(self.lbl_elo)
        self.right_layout.addWidget(self.btn_profile)
        self.right_layout.addWidget(self.btn_settings)
        self.layout.addWidget(self.right_container)

        # --- Resources Pill ---
        self.res_pill = QWidget()
        self.res_pill.setProperty("class", "GlassPill")
        res_layout = QHBoxLayout(self.res_pill)
        res_layout.setContentsMargins(scale(15), 0, scale(15), 0)
        
        self.btn_resources = QPushButton(tr_ui("main.btn_resources", "📁 Ressourcen"))
        self.btn_resources.setFlat(True)
        self.btn_resources.setStyleSheet(f"""
            QPushButton {{ font-weight: bold; color: {COLORS['brown_text']}; font-size: {scale(14)}px; border-radius: {scale(18)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.7); }}
        """)
        self.btn_resources.setFixedHeight(scale(40))
        self.btn_resources.clicked.connect(self.resources_requested.emit)
        res_layout.addWidget(self.btn_resources)
        
        self.layout.addWidget(self.res_pill)

        # Pill styling maintained cleanly via CSS

    def _on_button_clicked(self, button):
        self.repertoire_changed.emit(button.property("repo_name"))

    def scroll_tabs_left(self):
        sb = self.repo_scroll.horizontalScrollBar()
        sb.setValue(sb.value() - scale(100))

    def scroll_tabs_right(self):
        sb = self.repo_scroll.horizontalScrollBar()
        sb.setValue(sb.value() + scale(100))

    def update_tab_scroll_arrows(self):
        sb = self.repo_scroll.horizontalScrollBar()
        self.btn_scroll_left.setVisible(sb.value() > 0)
        self.btn_scroll_right.setVisible(sb.value() < sb.maximum())

    def set_elo(self, elo):
        self.lbl_elo.setText(f"🎓 {elo}")

    def set_profile_name(self, name):
        self.btn_profile.setText(name)

    def set_filter_text(self, text):
        self.btn_filter.setText(text)
