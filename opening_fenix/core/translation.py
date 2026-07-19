import os
import json
from PyQt6.QtCore import QObject, pyqtSignal, QTranslator, QLibraryInfo
from PyQt6.QtWidgets import QApplication
from opening_fenix.core.utils import get_base_path, get_user_dir
from opening_fenix.core.logger import logger

class TranslationManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = object.__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.current_lang = "de"  # Default is German
        self.translations = {}
        self.qt_translator = QTranslator()
        self._initialized = True
        self.load_language(self.current_lang)

    def load_language(self, lang_code: str):
        """Loads custom JSON translations and registers the native Qt translator."""
        self.current_lang = lang_code
        
        # 1. Load Custom JSON Translations
        base_path = get_base_path()
        trans_file = os.path.join(base_path, "assets", "translations", f"{lang_code}.json")
        
        # Fallback for dev mode
        if not os.path.exists(trans_file):
            dev_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            trans_file = os.path.join(dev_path, "assets", "translations", f"{lang_code}.json")

        if os.path.exists(trans_file):
            try:
                with open(trans_file, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
                logger.info(f"Loaded translation file: {lang_code}.json")
            except Exception as e:
                logger.error(f"Failed to parse translation file {trans_file}: {e}")
                self.translations = {}
        else:
            logger.warning(f"Translation file not found: {trans_file}")
            self.translations = {}

        # 2. Load Native Qt translation for standard buttons/dialogs
        app = QApplication.instance()
        if app:
            from PyQt6 import sip
            if sip.isdeleted(self.qt_translator):
                self.qt_translator = QTranslator()
            else:
                try:
                    app.removeTranslator(self.qt_translator)
                except (RuntimeError, TypeError):
                    self.qt_translator = QTranslator()
                    
            qt_translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if self.qt_translator.load(f"qtbase_{lang_code}", qt_translations_path):
                app.installTranslator(self.qt_translator)
                logger.info(f"Installed native Qt translator: qtbase_{lang_code}")

    def translate(self, key: str, default: str = "", **kwargs) -> str:
        """Resolves dotted key references like 'login.title'."""
        parts = key.split('.')
        val = self.translations
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return default.format(**kwargs) if default else key

        if isinstance(val, str):
            try:
                return val.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Formatting placeholder error for key '{key}': {e}")
                return val
        return default if default else key

# Global access reference
translator = TranslationManager()

def tr_ui(key: str, default: str = "", **kwargs) -> str:
    """Translates a string, with safety fallback to a default value."""
    return translator.translate(key, default, **kwargs)
