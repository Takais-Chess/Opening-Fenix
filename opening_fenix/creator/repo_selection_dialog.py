import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget, QGridLayout, 
    QPushButton, QHBoxLayout, QApplication, QFormLayout, QLineEdit, QComboBox,
    QMessageBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QFont

from opening_fenix.core.services.repertoire_core_service import RepertoireService
from opening_fenix.gui.styles import get_login_dialog_style, COLORS, set_consistent_icon, get_tooltip_style
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui
from opening_fenix.gui.native_close_filter import install_taskbar_close_filter, uninstall_taskbar_close_filter

def get_repertoire_cover_path(name):
    from opening_fenix.core.data_tools import get_user_dir
    repo_base = os.path.join(get_user_dir(), "repertoires")
    
    # Try normal path
    normal_dir = os.path.join(repo_base, name)
    # Try test path
    test_dir = os.path.join(repo_base, "test", name)
    
    for folder in (normal_dir, test_dir):
        if os.path.isdir(folder):
            try:
                for f in os.listdir(folder):
                    f_lower = f.lower()
                    if f_lower.startswith("cover."):
                        ext = f_lower.split(".")[-1]
                        if ext in ("png", "jpg", "jpeg"):
                            return os.path.join(folder, f)
            except Exception:
                pass
    return None

class NewRepertoireDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr_ui("creator.new_repo_title", "Neues Repertoire"))
        self.setFixedWidth(scale(420))
        set_consistent_icon(self)
        self.setStyleSheet(get_login_dialog_style())
        self._taskbar_filter = install_taskbar_close_filter(self)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scale(15))
        layout.setContentsMargins(scale(25), scale(25), scale(25), scale(25))

        lbl_title = QLabel(tr_ui("creator.new_repo_title", "Neues Repertoire"))
        lbl_title.setObjectName("LoginTitle")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        form = QFormLayout()
        form.setSpacing(scale(12))
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr_ui("creator.new_repo_name_placeholder", "z.B. Caro-Kann für Fortgeschrittene"))
        self.name_input.setFixedHeight(scale(38))
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 0.7);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                padding: 0 {scale(10)}px;
                font-size: {scale(14)}px;
                color: {COLORS['brown_text']};
            }}
            QLineEdit:focus {{
                border: 2px solid {COLORS['burnt_orange']};
                background-color: rgba(255, 255, 255, 0.95);
            }}
        """)
        
        self.color_combo = QComboBox()
        self.color_combo.addItem(tr_ui("creator.new_repo_color_white", "Weiß"), "w")
        self.color_combo.addItem(tr_ui("creator.new_repo_color_black", "Schwarz"), "b")
        self.color_combo.setFixedHeight(scale(38))
        self.color_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: rgba(255, 255, 255, 0.7);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                padding: 0 {scale(10)}px;
                font-size: {scale(14)}px;
                color: {COLORS['brown_text']};
            }}
        """)
        
        lbl_name = QLabel(tr_ui("creator.new_repo_name_label", "Name:"))
        lbl_name.setStyleSheet(f"font-weight: bold; color: {COLORS['brown_text']};")
        lbl_color = QLabel(tr_ui("creator.new_repo_color_label", "Deine Farbe:"))
        lbl_color.setStyleSheet(f"font-weight: bold; color: {COLORS['brown_text']};")
        
        form.addRow(lbl_name, self.name_input)
        form.addRow(lbl_color, self.color_combo)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.setSpacing(scale(10))
        
        btn_cancel = QPushButton(tr_ui("creator.new_repo_btn_cancel", "Abbrechen"))
        btn_cancel.setFixedHeight(scale(40))
        btn_cancel.setFixedWidth(scale(120))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(8)}px;
                color: {COLORS['brown_text']};
                font-size: {scale(14)}px;
                font-weight: bold;
                padding: 0 {scale(16)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.8);
                border-color: {COLORS['burnt_orange']};
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton(tr_ui("creator.new_repo_btn_create", "Erstellen"))
        btn_ok.setDefault(True)
        btn_ok.setFixedHeight(scale(40))
        btn_ok.setFixedWidth(scale(140))
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(8)}px;
                font-weight: bold;
                font-size: {scale(14)}px;
                padding: 0 {scale(16)}px;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
        """)
        btn_ok.clicked.connect(self.accept)
        
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def get_data(self):
        return self.name_input.text().strip(), self.color_combo.currentData()

    # Windows-forbidden characters in file/directory names
    _FORBIDDEN_CHARS = set('\\/:*?"<>|')

    def accept(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                tr_ui("creator.new_repo_invalid_name_title", "Invalid Name"),
                tr_ui("creator.new_repo_invalid_name_empty", "The repertoire name cannot be empty.")
            )
            return
        bad = [c for c in name if c in self._FORBIDDEN_CHARS]
        if bad:
            bad_str = "  " + "  ".join(sorted(set(bad)))
            QMessageBox.warning(
                self,
                tr_ui("creator.new_repo_invalid_name_title", "Invalid Name"),
                tr_ui(
                    "creator.new_repo_invalid_name_chars",
                    "The repertoire name contains characters that are not allowed in file names:\n\n"
                    "{chars}\n\n"
                    "Please remove them and try again.",
                    chars=bad_str
                )
            )
            return
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None
        super().accept()

    def reject(self):
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None
        super().reject()

    def closeEvent(self, event):
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None
        super().closeEvent(event)


class RepoSelectionButton(QPushButton):
    def __init__(self, name, parent=None):
        super().__init__("", parent)
        self.repo_name = name
        self.setFixedSize(scale(160), scale(196))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
            }}

            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.8);
                border: 2px solid {COLORS['burnt_orange']};
            }}
            
            QPushButton:pressed {{
                background-color: rgba(211, 84, 0, 0.1);
                border: 2px solid {COLORS['burnt_orange']};
            }}
            {get_tooltip_style()}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(10), scale(8), scale(10), scale(8))
        layout.setSpacing(scale(4))
        
        self.lbl_image = QLabel()
        self.lbl_image.setFixedSize(scale(140), scale(140))
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        cover_path = get_repertoire_cover_path(name)
        if cover_path:
            pix = QPixmap(cover_path)
            self.lbl_image.setPixmap(pix.scaled(
                self.lbl_image.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            ))
            self.lbl_image.setStyleSheet(f"border-radius: {scale(8)}px; border: none;")
        else:
            self.lbl_image.setStyleSheet(f"""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 rgba(211, 84, 0, 0.3), 
                    stop:1 rgba(211, 84, 0, 0.05));
                border-radius: {scale(8)}px;
                border: 1px dashed rgba(211, 84, 0, 0.3);
            """)
            self.lbl_image.setText("♟")
            self.lbl_image.setFont(QFont("Segoe UI", 36))
            
        layout.addWidget(self.lbl_image)
        
        # Dynamic Auto-Shrink Font Size (supports 1 to 3 lines cleanly without wasted vertical space)
        font_size = self._calculate_font_size(name, max_width=scale(140), max_height=scale(36))

        self.lbl_title = QLabel(name)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setToolTip(name)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_title.setStyleSheet(f"font-size: {font_size}px; font-weight: bold; color: {COLORS['brown_text']}; border: none; background: transparent;")
        layout.addWidget(self.lbl_title)

    def _calculate_font_size(self, text: str, max_width: int, max_height: int) -> int:
        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QFontMetrics
        for size in [12, 11, 10, 9]:
            scaled_sz = scale(size)
            font = QFont("Segoe UI")
            font.setPixelSize(scaled_sz)
            font.setBold(True)
            fm = QFontMetrics(font)
            rect = fm.boundingRect(QRect(0, 0, max_width, 1000), int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter), text)
            if rect.height() <= max_height:
                return scaled_sz
        return scale(9)

class RepoSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("repo_selection.window_title", "Repertoire laden"))
        self.setMinimumSize(scale(800), scale(640))
        self.selected_repo = None
        self.is_new_repo = False
        self.new_color = 'w'
        
        self.setStyleSheet(get_login_dialog_style())
        self._taskbar_filter = install_taskbar_close_filter(self)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))
        layout.setSpacing(scale(10))

        lbl_title = QLabel(tr_ui("repo_selection.title", "Repertoire laden"))
        lbl_title.setObjectName("LoginTitle")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(tr_ui("repo_selection.subtitle", "Wähle ein Repertoire zum Bearbeiten aus:"))
        lbl_sub.setObjectName("LoginSubtitle")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_sub)
        
        layout.addSpacing(scale(15))

        # Scroll Area Container
        self.grid_container = QWidget()
        self.grid_container.setObjectName("ProfileGridContainer")
        self.grid_container.setStyleSheet(f"""
            #ProfileGridContainer {{
                background-color: rgba(255, 255, 255, 0.2);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(20)}px;
            }}
        """)
        container_layout = QVBoxLayout(self.grid_container)
        container_layout.setContentsMargins(scale(15), scale(15), scale(15), scale(15))

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("RepoSelectScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea#RepoSelectScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea#RepoSelectScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setObjectName("RepoSelectScrollContent")
        scroll_content.setStyleSheet("#RepoSelectScrollContent { background: transparent; }")
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(scale(15))
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        repo_names = RepertoireService().get_all_repertoires()
        row = 0
        if not repo_names:
            lbl_empty = QLabel(tr_ui("repo_selection.empty", "Keine Repertoires gefunden."))
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("font-style: italic; color: #666;")
            self.grid_layout.addWidget(lbl_empty, 0, 0)
        else:
            col = 0
            for name in sorted(repo_names):
                btn = RepoSelectionButton(name)
                btn.clicked.connect(lambda checked, n=name: self.on_repo_selected(n))
                self.grid_layout.addWidget(btn, row, col)
                col += 1
                if col > 3: # 4 columns
                    col = 0
                    row += 1
                        
        self.grid_layout.setRowStretch(row + 1, 1)
        self.scroll_area.setWidget(scroll_content)
        container_layout.addWidget(self.scroll_area)
        layout.addWidget(self.grid_container, 1)
        
        layout.addSpacing(scale(15))

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        
        self.btn_import_course = QPushButton(tr_ui("repo_selection.btn_import_course", "⚡ Kurs-Import (PGN)"))
        self.btn_import_course.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_course.setMinimumWidth(scale(190))
        self.btn_import_course.setFixedHeight(scale(45))
        self.btn_import_course.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.65);
                border: 2px solid {COLORS['burnt_orange']};
                border-radius: {scale(12)}px;
                color: {COLORS['burnt_orange']};
                font-size: {scale(14)}px;
                font-weight: bold;
                padding: 0 {scale(15)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(211, 84, 0, 0.15);
            }}
        """)
        self.btn_import_course.clicked.connect(self.on_import_course)
        h_btns.addWidget(self.btn_import_course)
        h_btns.addSpacing(scale(12))

        self.btn_new = QPushButton(tr_ui("repo_selection.btn_new", "➕ Neues Repertoire"))
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setMinimumWidth(scale(180))
        self.btn_new.setFixedHeight(scale(45))
        self.btn_new.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                color: white;
                border: none;
                border-radius: {scale(12)}px;
                font-size: {scale(14)}px;
                font-weight: bold;
                padding: 0 {scale(15)}px;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
            QPushButton:pressed {{
                background-color: #d35400;
            }}
        """)
        self.btn_new.clicked.connect(self.on_create_new_repertoire)
        h_btns.addWidget(self.btn_new)
        h_btns.addSpacing(scale(15))

        self.btn_cancel = QPushButton(tr_ui("repo_selection.btn_cancel", "Abbrechen"))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setFixedWidth(scale(150))
        self.btn_cancel.setFixedHeight(scale(45))
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
                color: {COLORS['brown_text']};
                font-size: {scale(14)}px;
                font-weight: bold;
                padding: 0 {scale(15)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.8);
            }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(self.btn_cancel)
        h_btns.addStretch()
        layout.addLayout(h_btns)

    def on_import_course(self):
        from opening_fenix.gui.dialogs.course_import_dialog import CourseImportDialog
        dlg = CourseImportDialog(self)
        if dlg.exec():
            if dlg.imported_repo_name:
                self.selected_repo = dlg.imported_repo_name
                self.is_new_repo = False
                self.accept()

    def on_create_new_repertoire(self):
        dlg = NewRepertoireDialog(self)
        if dlg.exec():
            name, color = dlg.get_data()
            if name:
                self.selected_repo = name
                self.is_new_repo = True
                self.new_color = color
                self.accept()

    def on_repo_selected(self, name):
        self.selected_repo = name
        self.is_new_repo = False
        self.accept()

    def closeEvent(self, event):
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None
        super().closeEvent(event)

    def reject(self):
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None
        super().reject()

    def accept(self):
        uninstall_taskbar_close_filter(self._taskbar_filter)
        self._taskbar_filter = None
        super().accept()

