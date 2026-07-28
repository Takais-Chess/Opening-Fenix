import os
import json
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, 
    QPushButton, QGroupBox, QFrame, QInputDialog, QMessageBox,
    QHBoxLayout, QCheckBox, QScrollArea, QWidget, QGridLayout, QMenu,
    QGraphicsDropShadowEffect, QButtonGroup
)
from PyQt6.QtGui import QPixmap, QColor, QAction, QFont, QIcon
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, QTimer, pyqtSignal
from PyQt6.QtWidgets import QGraphicsOpacityEffect

from opening_fenix.core.utils import get_base_path, get_user_dir
# Import centralized styles
from opening_fenix.gui.styles import get_login_dialog_style, COLORS, set_consistent_icon
from opening_fenix.gui.scaling import scale
from opening_fenix.core.translation import tr_ui


class RepertoireButton(QPushButton):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.repo_name = name
        self.setCheckable(True)
        self.setChecked(False)
        self.setFixedHeight(scale(50))
        self.update_style()

        self.toggled.connect(self.update_style)

    def update_style(self):
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['burnt_orange']};
                    color: white;
                    border: 2px solid #e67e22;
                    border-radius: {scale(12)}px;
                    font-size: {scale(16)}px;
                    font-weight: bold;
                    padding: {scale(2)}px 0;
                }}

            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.3);
                    color: black;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: {scale(12)}px;
                    font-size: {scale(16)}px;
                    font-weight: bold;
                    padding: {scale(2)}px 0;
                }}

                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.2);
                }}
            """)

class RepertoireSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_consistent_icon(self)
        self.setWindowTitle(tr_ui("login.repertoire_selection_title", "Repertoires wählen"))
        self.setMinimumSize(scale(560), scale(600))
        self.selected_repos = []
        self.selected_language = None

        self.repo_buttons = []
        
        # Reuse Login Style for consistency
        self.setStyleSheet(get_login_dialog_style())
        
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))

        
        lbl_title = QLabel(tr_ui("login.repertoire_selection_title", "Repertoires wählen"))
        lbl_title.setObjectName("LoginTitle")
        lbl_title.setStyleSheet(f"font-size: {scale(24)}px;")
        layout.addWidget(lbl_title)

        
        lbl_sub = QLabel(tr_ui("login.repertoire_selection_subtitle", "Wähle die Repertoires für dein neues Profil:"))
        lbl_sub.setObjectName("LoginSubtitle")
        layout.addWidget(lbl_sub)
        
        layout.addSpacing(scale(20))


        # Scroll Area for Buttons
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("RepoScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea#RepoScrollArea { background: transparent; border: none; }")
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setSpacing(scale(15))

        
        from opening_fenix.core.services.repertoire_core_service import RepertoireService
        repo_names = RepertoireService().get_all_repertoires()
        
        row, col = 0, 0
        for name in sorted(repo_names):
            btn = RepertoireButton(name)
            self.repo_buttons.append(btn)
            self.grid_layout.addWidget(btn, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1
                        
        self.grid_layout.setRowStretch(self.grid_layout.rowCount(), 1)
        self.scroll_area.setWidget(scroll_widget)
        layout.addWidget(self.scroll_area)
        
        layout.addSpacing(scale(20))

        # Notation Language Selection
        lang_layout = QHBoxLayout()
        lbl_lang = QLabel(tr_ui("login.notation_language", "Notation Sprache:"))
        lbl_lang.setStyleSheet(f"font-size: {scale(16)}px; color: black; font-weight: bold;")
        
        self.lang_group = QButtonGroup(self)
        btn_en = QPushButton("English (EN)")
        btn_en.setObjectName("LangBtn_en")
        btn_de = QPushButton("Deutsch (DE)")
        btn_de.setObjectName("LangBtn_de")
        
        for btn, code in [(btn_en, "en"), (btn_de, "de")]:
            btn.setCheckable(True)
            btn.setProperty("lang_code", code)
            btn.setFixedHeight(scale(50))
            btn.setMinimumWidth(scale(140))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            # Apply similar style to RepertoireButton
            style = f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.3);
                    color: black;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: {scale(12)}px;
                    font-size: {scale(16)}px;
                    font-weight: bold;
                    padding: {scale(2)}px {scale(15)}px;
                }}
                QPushButton:checked {{
                    background-color: {COLORS['burnt_orange']};
                    color: white;
                    border: 2px solid #e67e22;
                }}
                QPushButton:hover:!checked {{
                    background-color: rgba(255, 255, 255, 0.2);
                }}
            """
            btn.setStyleSheet(style)
            self.lang_group.addButton(btn)
            lang_layout.addWidget(btn)
            
        self.lang_group.buttonClicked.connect(self.validate_selection)
        
        lang_layout.insertWidget(0, lbl_lang)
        lang_layout.addStretch()
        layout.addLayout(lang_layout)
        
        layout.addSpacing(scale(20))

        self.btn_ok = QPushButton("✔  " + tr_ui("login.create", "Profil erstellen"))
        self.btn_ok.setObjectName("PrimaryAction")
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ok.setEnabled(True) # Always enabled, validate on click
        self.btn_ok.clicked.connect(self.on_accept)
        layout.addWidget(self.btn_ok)

    def flash_widget(self, widget):
        """Creates a bold red flash effect to draw attention."""
        original_style = widget.styleSheet()
        obj_name = widget.objectName()
        class_name = widget.metaObject().className()
        
        # Use selector if objectName exists, otherwise fallback to class name
        selector = f"#{obj_name}" if obj_name else class_name
        
        # Flash: Bold red border using !important to override existing styles
        flash_style = original_style + f" {selector} {{ border: 4px solid #e74c3c !important; }}"
        widget.setStyleSheet(flash_style)
        
        # Reset after a short delay (slightly longer for visibility)
        QTimer.singleShot(800, lambda: widget.setStyleSheet(original_style))

    def validate_selection(self):
        """Visual feedback when language is selected."""
        # We could add a checkmark or something here later
        pass

    def on_accept(self):
        selected_repos = []
        for btn in self.repo_buttons:
            if btn.isChecked():
                selected_repos.append(btn.repo_name)
        
        checked_lang = self.lang_group.checkedButton()
        
        # VALIDATION
        has_error = False
        if not selected_repos:
            # Flash the scroll area or buttons
            self.flash_widget(self.scroll_area)
            has_error = True
            
        if not checked_lang:
            # Flash the language buttons (we'll find the buttons in the group)
            for btn in self.lang_group.buttons():
                self.flash_widget(btn)
            has_error = True
            
        if has_error:
            return

        self.selected_repos = selected_repos
        self.selected_language = checked_lang.property("lang_code")
        self.accept()

class ProfileGridButton(QPushButton):
    """Compact button for profile grid with centered text."""
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.profile_name = name
        self.setProperty("class", "ProfileGridButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(scale(50))


class LoginDialog(QDialog):
    profile_selected = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Opening Fenix - Login")
        set_consistent_icon(self)
        self.setMinimumSize(scale(700), scale(520))
        self.selected_profile = None
        self.login_in_progress = False

        self.open_creator_requested = False
        self._auto_create_checked = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setStyleSheet(get_login_dialog_style())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale(30), scale(30), scale(30), scale(30))
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Top bar for language switcher
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.addStretch()
        
        from opening_fenix.core.translation import translator
        current_lang = translator.current_lang
        
        self.btn_lang_de = QPushButton("DE")
        self.btn_lang_de.setObjectName("LangBtn_DE")
        self.btn_lang_de.setCheckable(True)
        self.btn_lang_de.setChecked(current_lang == "de")
        self.btn_lang_de.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_lang_en = QPushButton("EN")
        self.btn_lang_en.setObjectName("LangBtn_EN")
        self.btn_lang_en.setCheckable(True)
        self.btn_lang_en.setChecked(current_lang == "en")
        self.btn_lang_en.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.lang_group = QButtonGroup(self)
        self.lang_group.addButton(self.btn_lang_de)
        self.lang_group.addButton(self.btn_lang_en)
        
        self.btn_lang_de.clicked.connect(lambda: self.change_language("de"))
        self.btn_lang_en.clicked.connect(lambda: self.change_language("en"))
        
        top_bar.addWidget(self.btn_lang_de)
        top_bar.addWidget(self.btn_lang_en)
        layout.addLayout(top_bar)
        layout.addSpacing(scale(5))

        # Header Section (Tightened)
        header_layout = QVBoxLayout()
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.setSpacing(scale(5))


        logo_label = QLabel()
        logo_path = os.path.join(get_base_path(), "assets", "Logo", "Logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(pixmap.scaledToWidth(scale(80), Qt.TransformationMode.SmoothTransformation))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_layout.addWidget(logo_label)

        self.title_label = QLabel(tr_ui("login.title", "OPENING FENIX"))
        self.title_label.setObjectName("LoginTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(tr_ui("login.subtitle", "Wer trainiert heute?"))
        self.subtitle_label.setObjectName("LoginSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.subtitle_label)

        layout.addLayout(header_layout)
        layout.addSpacing(scale(25))


        # Profile Grid Container
        self.grid_container = QFrame()
        self.grid_container.setObjectName("ProfileGridContainer")
        grid_container_layout = QVBoxLayout(self.grid_container)
        grid_container_layout.setContentsMargins(scale(20), scale(20), scale(20), scale(20))


        # Scroll Area for the Grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.profile_grid = QGridLayout(self.scroll_content)
        self.profile_grid.setSpacing(scale(15))
        self.profile_grid.setContentsMargins(0, 0, 0, 0)

        
        self.scroll_area.setWidget(self.scroll_content)
        grid_container_layout.addWidget(self.scroll_area)
        
        layout.addWidget(self.grid_container, 1)

        layout.addSpacing(scale(10))

        # Checkbox for automatic login
        self.chk_auto_login = QCheckBox(tr_ui("login.auto_login_checkbox", "Beim nächsten Start dieses Profil wieder verwenden"))
        self.chk_auto_login.setObjectName("AutoLoginCheckbox")
        self.chk_auto_login.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.chk_auto_login)

        layout.addSpacing(scale(15))

        # Buttons in a horizontal layout at the bottom
        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.setSpacing(scale(15))

        
        # Primary Action: Repertoire Creator
        self.btn_creator = QPushButton(tr_ui("login.creator_mode", "🛠  REPERTOIRE CREATOR"))
        self.btn_creator.setObjectName("PrimaryAction")
        self.btn_creator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_creator.setFixedHeight(scale(60))
        self.btn_creator.clicked.connect(self.request_creator)

        bottom_button_layout.addWidget(self.btn_creator, 1)

        # Secondary Action: New Profile
        self.btn_new = QPushButton(tr_ui("login.create_profile", "+  NEUES PROFIL ERSTELLEN"))
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setFixedHeight(scale(60))
        self.btn_new.clicked.connect(self.create_new_profile)

        bottom_button_layout.addWidget(self.btn_new, 1)

        layout.addLayout(bottom_button_layout)

        # Load initial profiles
        self.load_profiles()
        
        # Loading Overlay (initially hidden)
        self.loading_overlay = QFrame(self)
        self.loading_overlay.setObjectName("LoadingOverlay")
        self.loading_overlay.setStyleSheet(f"""
            QFrame#LoadingOverlay {{
                background-color: rgba(255, 255, 255, 0.85);
                border-radius: {scale(15)}px;
            }}
        """)
        overlay_layout = QVBoxLayout(self.loading_overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_loading = QLabel(tr_ui("login.loading", "Wird geladen..."))
        self.lbl_loading.setStyleSheet(f"font-size: {scale(22)}px; font-weight: bold; color: {COLORS['brown_text']};")
        overlay_layout.addWidget(self.lbl_loading)
        
        self.loading_overlay.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(self.rect())

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_auto_create_checked', False):
            self._auto_create_checked = True
            profiles_dir = os.path.join(get_user_dir(), "profiles")
            has_profiles = False
            if os.path.exists(profiles_dir):
                has_profiles = any(
                    (f.endswith(".db") or (f.endswith(".json") and not f.endswith("_settings.json")))
                    for f in os.listdir(profiles_dir)
                )
            if not has_profiles:
                QTimer.singleShot(0, self.create_new_profile)

    def show_loading_state(self, profile_name):
        """Displays a loading message and disables interaction."""
        self.login_in_progress = True
        self.lbl_loading.setText(tr_ui("login.loading_trainer", "Trainer wird geladen...\n({profile_name})", profile_name=profile_name))
        self.loading_overlay.show()
        self.loading_overlay.raise_()
        self.setEnabled(True) # Ensure dialog is enabled to show overlay, but we'll block buttons
        
        # Disable all buttons manually for safety
        self.btn_creator.setEnabled(False)
        self.btn_new.setEnabled(False)
        for btn in self.findChildren(QPushButton):
            btn.setEnabled(False)
            
        QApplication.processEvents()

    def _get_relative_time(self, iso_date_str):
        """Helper to format ISO date string into a relative time like 'Vor 2 Stunden'."""
        if not iso_date_str: return None
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(iso_date_str)
            now = datetime.datetime.now()
            diff = now - dt
            
            if diff.days > 0:
                if diff.days == 1: return tr_ui("login.relative_time_yesterday", "Gestern")
                return tr_ui("login.relative_time_days", "Vor {days} Tagen", days=diff.days)
            
            seconds = diff.seconds
            if seconds < 60: return tr_ui("login.relative_time_now", "Gerade eben")
            if seconds < 3600: return tr_ui("login.relative_time_minutes", "Vor {minutes} Min.", minutes=seconds // 60)
            return tr_ui("login.relative_time_hours", "Vor {hours} Std.", hours=seconds // 3600)
        except: return None

    def load_profiles(self):
        # Clear existing grid
        while self.profile_grid.count():
            child = self.profile_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        profiles_dir = os.path.join(get_user_dir(), "profiles")
        
        if not os.path.exists(profiles_dir):
            os.makedirs(profiles_dir)
            
        config_path = os.path.join(get_user_dir(), "config.json")
        last_used_map = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    last_used_map = config.get("profile_last_used", {})
            except: pass

        # Get all profile names
        all_profile_names = {f.replace(".db", "") for f in os.listdir(profiles_dir) if f.endswith(".db")}
        all_profile_names.update({f.replace(".json", "") for f in os.listdir(profiles_dir) if f.endswith(".json") and not f.endswith("_settings.json")})
        
        # Create profile data list for sorting
        profile_data = []
        for name in all_profile_names:
            ts = last_used_map.get(name, "1970-01-01T00:00:00")
            profile_data.append((name, ts))

        # Sort by timestamp descending (most recent first)
        profile_data.sort(key=lambda x: x[1], reverse=True)

        # 1. Add special "Freies Training" button first
        free_btn = ProfileGridButton(tr_ui("login.free_training", "Freies Training"))
        # Special styling for the free training button
        free_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['burnt_orange']};
                border: 2px solid #e67e22;
                font-weight: bold;
                color: white;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
        """)
        free_btn.clicked.connect(lambda: self.select_profile("Freies Training"))
        self.profile_grid.addWidget(free_btn, 0, 0)

        row, col = 0, 1
        for name, ts in profile_data:
            btn = ProfileGridButton(name)
            btn.clicked.connect(lambda checked, n=name: self.select_profile(n))
            
            # Context menu for deletion
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, n=name: self.show_context_menu(pos, n))
            
            self.profile_grid.addWidget(btn, row, col)
            
            col += 1
            if col > 2: # 3 columns
                col = 0
                row += 1
        
        # Add stretch to fill rows if needed
        self.profile_grid.setRowStretch(row + 1, 1)

    def select_profile(self, name):
        if self.login_in_progress: return
        
        # Save auto-login setting and current profile choice to config.json
        try:
            import datetime
            from opening_fenix.core.translation import translator
            
            config_path = os.path.join(get_user_dir(), "config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
            
            # Save the language selection globally
            config["ui_language"] = translator.current_lang
            config["last_profile"] = name
            
            # Save or clear auto-login preference
            if self.chk_auto_login.isChecked():
                config["auto_login_profile"] = name
            else:
                config["auto_login_profile"] = None
                
            # Update last used timestamp
            last_used_map = config.setdefault("profile_last_used", {})
            last_used_map[name] = datetime.datetime.now().isoformat()
            
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)
                
            # Write profile-specific UI language setting (so MainWindow loads correctly)
            settings_path = os.path.join(get_user_dir(), "profiles", f"{name}_settings.json")
            profile_settings = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, "r") as f:
                        profile_settings = json.load(f)
                except:
                    pass
            
            profile_settings["ui_language"] = translator.current_lang
            try:
                with open(settings_path, "w") as f:
                    json.dump(profile_settings, f, indent=4)
            except:
                pass
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Failed to save profile selections on login: {e}")
            
        self.selected_profile = name
        self.profile_selected.emit(name)

    def change_language(self, lang_code):
        from opening_fenix.core.translation import translator
        # Update translator
        translator.load_language(lang_code)
        
        # Save globally immediately in config.json
        try:
            config_path = os.path.join(get_user_dir(), "config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
            config["ui_language"] = lang_code
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            from opening_fenix.core.logger import logger
            logger.error(f"Failed to save language setting: {e}")
            
        # Re-translate dialog UI elements
        self.retranslate_ui()

    def retranslate_ui(self):
        # Update switcher button checks just in case
        from opening_fenix.core.translation import translator
        self.btn_lang_de.setChecked(translator.current_lang == "de")
        self.btn_lang_en.setChecked(translator.current_lang == "en")
        
        # Retranslate texts
        self.title_label.setText(tr_ui("login.title", "OPENING FENIX"))
        self.subtitle_label.setText(tr_ui("login.subtitle", "Wer trainiert heute?"))
        self.chk_auto_login.setText(tr_ui("login.auto_login_checkbox", "Beim nächsten Start dieses Profil wieder verwenden"))
        self.btn_creator.setText(tr_ui("login.creator_mode", "🛠  REPERTOIRE CREATOR"))
        self.btn_new.setText(tr_ui("login.create_profile", "+  NEUES PROFIL ERSTELLEN"))
        self.lbl_loading.setText(tr_ui("login.loading", "Wird geladen..."))
        
        # Rebuild grid so the "Freies Training" button and layout update
        self.load_profiles()

    def show_context_menu(self, pos, name):
        # We need to find the button that sent the event to map coordinates
        sender = self.sender()
        
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #2c3e50; color: white; border: 1px solid rgba(255,255,255,0.2); } QMenu::item:selected { background-color: rgba(255,255,255,0.1); }")
        
        delete_action = QAction(tr_ui("login.delete_profile_action", "'{name}' löschen", name=name), self)
        delete_action.triggered.connect(lambda: self.delete_profile(name))
        menu.addAction(delete_action)
        
        menu.exec(sender.mapToGlobal(pos))

    def delete_profile(self, name):
        reply = QMessageBox.question(
            self, 
            tr_ui("login.delete_profile_title", "Profil löschen"),
            tr_ui("login.delete_profile_confirm", "Bist du sicher, dass du das Profil '{name}' löschen möchtest?\nAlle Trainingsdaten gehen verloren.", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            profiles_dir = os.path.join(get_user_dir(), "profiles")
            for ext in [".db", ".json", "_settings.json"]:
                path = os.path.join(profiles_dir, f"{name}{ext}")
                if os.path.exists(path):
                    try: os.remove(path)
                    except: pass
            
            self.load_profiles()

    def create_new_profile(self):
        name, ok = QInputDialog.getText(
            self, 
            tr_ui("login.profile_name_prompt_title", "Neues Profil"), 
            tr_ui("login.profile_name_prompt_label", "Name des neuen Profils:")
        )
        if ok and name.strip():
            name = name.strip()
            # Basic validation
            if any(c in name for c in '/\\:*?"<>|'):
                QMessageBox.warning(
                    self, 
                    tr_ui("login.invalid_name_error", "Ungültiger Name"), 
                    tr_ui("login.invalid_name_error_msg", "Der Profilname darf nicht leer sein und keine Sonderzeichen enthalten.")
                )
                return
            
            sel_dialog = RepertoireSelectionDialog(self)
            if sel_dialog.exec() == QDialog.DialogCode.Accepted:
                from opening_fenix.core.models import DatabaseManager, UserBase, UserRepertoireSettings
                path = os.path.join(get_user_dir(), "profiles", f"{name}.db")
                db = DatabaseManager(path, base=UserBase)
                session = db.get_session()
                for repo in sel_dialog.selected_repos:
                    session.add(UserRepertoireSettings(repertoire_name=repo, active_level=1))
                session.commit()
                session.close()
                db.close()
                
                # Create initial settings file with selected notation language
                settings_path = os.path.join(get_user_dir(), "profiles", f"{name}_settings.json")
                initial_settings = {
                    "notation_language": sel_dialog.selected_language,
                    "stop_at_variation_end": True
                }
                try:
                    with open(settings_path, "w") as f:
                        json.dump(initial_settings, f, indent=4)
                except Exception as e:
                    from opening_fenix.core.logger import logger
                    logger.error(f"Failed to create profile settings: {e}")
                
                self.load_profiles()
                self.select_profile(name)

    def request_creator(self):
        self.open_creator_requested = True
        self.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        self.accept()
