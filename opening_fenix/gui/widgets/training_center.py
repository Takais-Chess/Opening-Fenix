import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout, 
    QPushButton, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtGui import QIcon, QColor, QFont
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from opening_fenix.gui.scaling import scale
from opening_fenix.gui.styles import COLORS
from opening_fenix.gui.widgets.common import ZoomableTextBrowser
from opening_fenix.gui.widgets.charts import PieChartWidget
from opening_fenix.core.data_tools import get_base_path
from opening_fenix.core.translation import tr_ui

class TrainingCenterWidget(QFrame):
    """
    The training center panel containing the notation view, 
    progress charts, and action buttons.
    """
    smart_clicked = pyqtSignal()
    learn_new_toggled = pyqtSignal(bool)
    auto_continue_toggled = pyqtSignal(bool)
    lichess_requested = pyqtSignal()
    creator_requested = pyqtSignal()
    notation_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        layout.addWidget(QLabel(tr_ui("training.lbl_notation", "NOTATION")), 0, Qt.AlignmentFlag.AlignLeft)
        self.txt_notation = ZoomableTextBrowser()
        self.txt_notation.setObjectName("NotationView")
        self.txt_notation.setOpenLinks(False)
        self.txt_notation.anchorClicked.connect(lambda url: self.notation_clicked.emit(url.toString()))
        layout.addWidget(self.txt_notation, 1)

        # Training Hub
        training_hub = QWidget()
        hub_layout = QVBoxLayout(training_hub)
        hub_layout.setContentsMargins(0, 0, 0, 0)
        hub_layout.setSpacing(20)

        stats_actions_row = QHBoxLayout()
        stats_actions_row.setSpacing(15)
        self.pie_chart = PieChartWidget()
        self.pie_chart.setMinimumSize(scale(160), scale(160))
        stats_actions_row.addWidget(self.pie_chart, 1)

        actions_grid = QGridLayout()
        actions_grid.setSpacing(8)
        
        self.btn_learn_new = QPushButton("🧠")
        self.btn_learn_new.setObjectName("ActionButton")
        self.btn_learn_new.setCheckable(True)
        self.btn_learn_new.clicked.connect(lambda: self.learn_new_toggled.emit(self.btn_learn_new.isChecked()))
        self.btn_learn_new.setToolTip(tr_ui("training.tooltip_learn_mode", "<b>Lern-Modus</b><br>Trainiere neue Züge, die du noch nicht kennst."))
        
        self.btn_auto_continue = QPushButton("⚡")
        self.btn_auto_continue.setObjectName("ActionButton")
        self.btn_auto_continue.setCheckable(True)
        self.btn_auto_continue.clicked.connect(lambda: self.auto_continue_toggled.emit(self.btn_auto_continue.isChecked()))
        self.btn_auto_continue.setToolTip(tr_ui("training.tooltip_auto_next", "<b>Auto-Weiter</b><br>Springe nach einem korrekten Zug automatisch zum nächsten."))
        
        self.btn_lichess = QPushButton()
        self.btn_lichess.setObjectName("ActionButton")
        lichess_icon_path = os.path.join(get_base_path(), "assets", "Icons", "lichess.png")
        if os.path.exists(lichess_icon_path):
            self.btn_lichess.setIcon(QIcon(lichess_icon_path))
            self.btn_lichess.setIconSize(QSize(scale(24), scale(24)))
        else:
            self.btn_lichess.setText("🔬")
        self.btn_lichess.clicked.connect(self.lichess_requested.emit)
        self.btn_lichess.setToolTip(tr_ui("training.tooltip_lichess", "<b>Lichess Analyse</b><br>Öffne die aktuelle Stellung in der Lichess-Analyse."))
        
        self.btn_creator = QPushButton("✏️")
        self.btn_creator.setObjectName("ActionButton")
        self.btn_creator.clicked.connect(self.creator_requested.emit)
        self.btn_creator.setToolTip(tr_ui("training.tooltip_creator", "<b>Repertoire Creator</b><br>Öffne den Creator an der aktuellen Position."))
        
        actions_grid.addWidget(self.btn_learn_new, 0, 0)
        actions_grid.addWidget(self.btn_auto_continue, 0, 1)
        actions_grid.addWidget(self.btn_lichess, 1, 0)
        actions_grid.addWidget(self.btn_creator, 1, 1)

        stats_actions_row.addLayout(actions_grid, 1)
        hub_layout.addLayout(stats_actions_row)

        self.btn_smart = QPushButton(tr_ui("training.btn_start_training", "TRAINING STARTEN"))
        self.btn_smart.setObjectName("StartButton")
        self.btn_smart.clicked.connect(self.smart_clicked.emit)
        hub_layout.addWidget(self.btn_smart)

        layout.addWidget(training_hub)

        # Card styling maintained cleanly via CSS

    def update_stats(self, new_c, due_c, dist):
        self.pie_chart.update_stats(new_c, due_c, dist)

    def set_button_state(self, state, training_mode):
        if state == 'start':
            self.btn_smart.setText(tr_ui("training.btn_start_training", "TRAINING STARTEN"))
            self.btn_smart.setEnabled(True)
        elif state == 'waiting_for_move':
            if training_mode == 'new':
                self.btn_smart.setText(tr_ui("training.status_play_move", "SPIELE DEN ZUG"))
                self.btn_smart.setEnabled(False)
            else:
                self.btn_smart.setText(tr_ui("training.status_your_turn", "DU BIST AM ZUG"))
                self.btn_smart.setEnabled(False)
        elif state == 'correct':
            self.btn_smart.setText(tr_ui("training.status_correct", "KORREKT!"))
            self.btn_smart.setEnabled(False)
        elif state == 'show_solution_prompt':
            self.btn_smart.setText(tr_ui("training.status_wrong_show_solution", "FALSCH! LÖSUNG ANZEIGEN"))
            self.btn_smart.setEnabled(True)

    def update_notation(self, html):
        self.txt_notation.setHtml(html)
        from PyQt6.QtGui import QTextCursor
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self.txt_notation.moveCursor(QTextCursor.MoveOperation.End))
