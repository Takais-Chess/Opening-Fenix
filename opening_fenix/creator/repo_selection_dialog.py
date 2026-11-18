import json
import os
from collections import OrderedDict
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget, QGridLayout, 
    QPushButton, QHBoxLayout, QApplication, QFormLayout, QLineEdit, QComboBox,
    QMessageBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont, QImageReader

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


_REPO_THUMB_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()
_MAX_REPO_THUMB_CACHE = 64


def _load_repo_thumb_pixmap(path: str, width: int, height: int) -> QPixmap:
    key = (path, width, height)
    cached = _REPO_THUMB_CACHE.get(key)
    if cached is not None and not cached.isNull():
        _REPO_THUMB_CACHE.move_to_end(key)
        return cached
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    orig_size = reader.size()
    if orig_size.isValid() and not orig_size.isEmpty():
        reader.setScaledSize(orig_size.scaled(QSize(width, height), Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        img = reader.read()
        pix = QPixmap.fromImage(img) if not img.isNull() else QPixmap(path).scaled(
            width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
        )
    else:
        pix = QPixmap(path).scaled(
            width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
        )
    _REPO_THUMB_CACHE[key] = pix
    _REPO_THUMB_CACHE.move_to_end(key)
    while len(_REPO_THUMB_CACHE) > _MAX_REPO_THUMB_CACHE:
        _REPO_THUMB_CACHE.popitem(last=False)
    return pix


def _get_config_path() -> str:
    from opening_fenix.core.data_tools import get_user_dir
    return os.path.join(get_user_dir(), "config.json")


def _load_favorite_repertoires(parent=None) -> set:
    if parent is not None and isinstance(getattr(parent, "config", None), dict):
        favs = parent.config.get("creator_favorite_repertoires", [])
        return set(favs) if isinstance(favs, list) else set()
    cfg_path = _get_config_path()
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            favs = cfg.get("creator_favorite_repertoires", [])
            return set(favs) if isinstance(favs, list) else set()
        except Exception:
            pass
    return set()


def _save_favorite_repertoires(favorites: set, parent=None) -> None:
    sorted_favs = sorted(favorites, key=str.lower)
    if parent is not None and isinstance(getattr(parent, "config", None), dict):
        parent.config["creator_favorite_repertoires"] = sorted_favs
        if hasattr(parent, "save_config"):
            parent.save_config()
            return
    cfg_path = _get_config_path()
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                cfg = loaded
        except Exception:
            pass
    cfg["creator_favorite_repertoires"] = sorted_favs
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


class RepoSelectionButton(QPushButton):
    favorite_toggled = pyqtSignal(str, bool)

    def __init__(self, name, parent=None, is_favorite=False):
        super().__init__("", parent)
        self.repo_name = name
        self.is_favorite = bool(is_favorite)
        self.setObjectName("RepoSelectionCard")
        self.setFixedSize(scale(160), scale(196))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(10), scale(8), scale(10), scale(8))
        layout.setSpacing(scale(4))
        
        self.lbl_image = QLabel()
        self.lbl_image.setFixedSize(scale(140), scale(140))
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        cover_path = get_repertoire_cover_path(name)
        if cover_path:
            pix = _load_repo_thumb_pixmap(cover_path, scale(140), scale(140))
            self.lbl_image.setPixmap(pix)
            self.lbl_image.setObjectName("RepoThumbImage")
        else:
            self.lbl_image.setObjectName("RepoThumbPlaceholder")
            self.lbl_image.setText("♟")
            self.lbl_image.setFont(QFont("Segoe UI", scale(36)))
            
        layout.addWidget(self.lbl_image)
        
        # Dynamic Auto-Shrink Font Size (down to 50% / 6px) + ellipsis fallback
        font_size, display_text = self._fit_title_text(name, max_width=scale(136), max_height=scale(34))

        self.lbl_title = QLabel(display_text)
        self.lbl_title.setObjectName("RepoSelectionTitle")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setFixedHeight(scale(36))
        self.lbl_title.setToolTip(name)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_font = QFont("Segoe UI")
        title_font.setPixelSize(font_size)
        title_font.setBold(True)
        self.lbl_title.setFont(title_font)
        self.lbl_title.setStyleSheet(f"font-family: 'Segoe UI'; font-size: {font_size}px; font-weight: bold;")
        layout.addWidget(self.lbl_title)

        star_sz = scale(26)
        self.btn_favorite = QPushButton(self)
        self.btn_favorite.setObjectName("RepoFavoriteStar")
        self.btn_favorite.setFixedSize(star_sz, star_sz)
        self.btn_favorite.move(scale(10) + scale(140) - star_sz - scale(4), scale(8) + scale(4))
        self.btn_favorite.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_favorite.clicked.connect(self._on_favorite_clicked)
        self.btn_favorite.raise_()
        self._update_favorite_ui()

    def _on_favorite_clicked(self):
        self.set_favorite(not self.is_favorite)
        self.favorite_toggled.emit(self.repo_name, self.is_favorite)

    def set_favorite(self, is_fav: bool):
        self.is_favorite = bool(is_fav)
        self._update_favorite_ui()

    def _update_favorite_ui(self):
        radius = scale(13)
        font_px = scale(15)
        if self.is_favorite:
            self.btn_favorite.setText("\u2605")
            self.btn_favorite.setToolTip(tr_ui("repo_selection.favorite_remove", "Aus Favoriten entfernen"))
            self.btn_favorite.setStyleSheet(f"""
                QPushButton#RepoFavoriteStar {{
                    background-color: rgba(255, 255, 255, 0.88);
                    color: #f39c12;
                    border: 1px solid rgba(243, 156, 18, 0.55);
                    border-radius: {radius}px;
                    font-family: "Segoe UI Symbol", "Segoe UI";
                    font-size: {font_px}px;
                    padding: 0px;
                }}
                QPushButton#RepoFavoriteStar:hover {{
                    background-color: rgba(255, 255, 255, 1.0);
                    border-color: #e67e22;
                }}
            """)
        else:
            self.btn_favorite.setText("\u2606")
            self.btn_favorite.setToolTip(tr_ui("repo_selection.favorite_add", "Als Favorit markieren"))
            self.btn_favorite.setStyleSheet(f"""
                QPushButton#RepoFavoriteStar {{
                    background-color: rgba(255, 255, 255, 0.72);
                    color: rgba(93, 64, 55, 0.75);
                    border: 1px solid rgba(0, 0, 0, 0.12);
                    border-radius: {radius}px;
                    font-family: "Segoe UI Symbol", "Segoe UI";
                    font-size: {font_px}px;
                    padding: 0px;
                }}
                QPushButton#RepoFavoriteStar:hover {{
                    background-color: rgba(255, 255, 255, 0.95);
                    color: #f39c12;
                    border-color: rgba(243, 156, 18, 0.55);
                }}
            """)

    _FONT_METRICS_CACHE = {}

    @classmethod
    def _get_font_metrics(cls, scaled_sz: int):
        fm = cls._FONT_METRICS_CACHE.get(scaled_sz)
        if fm is None:
            from PyQt6.QtGui import QFontMetrics
            font = QFont("Segoe UI")
            font.setPixelSize(scaled_sz)
            font.setBold(True)
            fm = QFontMetrics(font)
            cls._FONT_METRICS_CACHE[scaled_sz] = fm
        return fm

    def _fit_title_text(self, text: str, max_width: int, max_height: int) -> tuple[int, str]:
        from PyQt6.QtCore import QRect
        flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter)
        bounds = QRect(0, 0, max_width, 1000)
        for size in (12, 11, 10, 9, 8, 7, 6):
            scaled_sz = scale(size)
            fm = self._get_font_metrics(scaled_sz)
            rect = fm.boundingRect(bounds, flags, text)
            if rect.height() <= max_height and rect.width() <= max_width:
                return scaled_sz, text

        min_sz = scale(6)
        fm = self._get_font_metrics(min_sz)
        lo, hi, best = 0, len(text), 0
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = text[:mid].rstrip() + "..."
            rect = fm.boundingRect(bounds, flags, candidate)
            if rect.height() <= max_height and rect.width() <= max_width:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return min_sz, text[:best].rstrip() + "..."

    def _calculate_font_size(self, text: str, max_width: int, max_height: int) -> int:
        return self._fit_title_text(text, max_width, max_height)[0]

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
        
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("RepoSelectScrollContent")
        self.scroll_content.setStyleSheet(f"""
            #RepoSelectScrollContent {{ background: transparent; }}
            QPushButton#RepoSelectionCard {{
                background-color: rgba(255, 255, 255, 0.4);
                border: 1px solid {COLORS['glass_border']};
                border-radius: {scale(12)}px;
            }}
            QPushButton#RepoSelectionCard:hover {{
                background-color: rgba(255, 255, 255, 0.8);
                border: 2px solid {COLORS['burnt_orange']};
            }}
            QPushButton#RepoSelectionCard:pressed {{
                background-color: rgba(211, 84, 0, 0.1);
                border: 2px solid {COLORS['burnt_orange']};
            }}
            QLabel#RepoThumbImage {{
                border-radius: {scale(8)}px;
                border: none;
            }}
            QLabel#RepoThumbPlaceholder {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(211, 84, 0, 0.3),
                    stop:1 rgba(211, 84, 0, 0.05));
                border-radius: {scale(8)}px;
                border: 1px dashed rgba(211, 84, 0, 0.3);
            }}
            QLabel#RepoSelectionTitle {{
                color: {COLORS['brown_text']};
                border: none;
                background: transparent;
            }}
            {get_tooltip_style()}
        """)
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.grid_layout.setSpacing(scale(15))
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area.setWidget(self.scroll_content)

        self.repo_buttons = []
        self._current_cols = None
        self._favorites = _load_favorite_repertoires(parent)

        repo_names = RepertoireService().get_all_repertoires()
        if not repo_names:
            lbl_empty = QLabel(tr_ui("repo_selection.empty", "Keine Repertoires gefunden."))
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setStyleSheet("font-style: italic; color: #666;")
            self.grid_layout.addWidget(lbl_empty, 0, 0)
        else:
            sorted_names = sorted(repo_names, key=lambda n: (0 if n in self._favorites else 1, n.lower()))
            for name in sorted_names:
                btn = RepoSelectionButton(name, parent=self.scroll_content, is_favorite=(name in self._favorites))
                btn.clicked.connect(lambda checked, n=name: self.on_repo_selected(n))
                btn.favorite_toggled.connect(self.on_favorite_toggled)
                self.repo_buttons.append(btn)
            self._reflow_grid(force=True)
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

    def _reflow_grid(self, force=False):
        if not hasattr(self, "repo_buttons") or not self.repo_buttons:
            return

        viewport = self.scroll_area.viewport()
        available_width = viewport.width()
        if available_width <= 1:
            available_width = max(self.width(), scale(800)) - scale(70)

        card_width = scale(160)
        card_height = scale(196)
        spacing = self.grid_layout.spacing()

        # If vertical scrollbar is not currently visible, account for it if rows exceed viewport height
        if not self.scroll_area.verticalScrollBar().isVisible():
            sb_width = max(self.scroll_area.verticalScrollBar().sizeHint().width(), scale(16))
            initial_cols = max(1, (available_width + spacing) // (card_width + spacing))
            total_items = len(self.repo_buttons)
            rows = (total_items + initial_cols - 1) // initial_cols
            needed_height = rows * card_height + max(0, rows - 1) * spacing
            if needed_height > viewport.height() > 0:
                available_width -= sb_width

        cols = max(4, (available_width + spacing) // (card_width + spacing))

        if not force and cols == self._current_cols:
            return

        self._current_cols = cols

        self.scroll_content.setUpdatesEnabled(False)
        try:
            while self.grid_layout.count():
                self.grid_layout.takeAt(0)

            for idx, btn in enumerate(self.repo_buttons):
                row = idx // cols
                col = idx % cols
                self.grid_layout.addWidget(btn, row, col)
        finally:
            self.scroll_content.setUpdatesEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_grid()

    def showEvent(self, event):
        super().showEvent(event)
        self._reflow_grid(force=False)

    def on_favorite_toggled(self, name, is_fav):
        if is_fav:
            self._favorites.add(name)
        else:
            self._favorites.discard(name)
        _save_favorite_repertoires(self._favorites, self.parent())
        self.repo_buttons.sort(key=lambda b: (0 if b.is_favorite else 1, b.repo_name.lower()))
        self._reflow_grid(force=True)

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

