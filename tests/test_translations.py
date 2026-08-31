import os
import json
import pytest
from opening_fenix.core.utils import get_base_path
from opening_fenix.core.translation import translator, tr_ui

def get_keys_recursive(d, prefix=""):
    """Recursively retrieves all dotted keys from a dictionary."""
    keys = set()
    for k, v in d.items():
        key_name = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(get_keys_recursive(v, key_name))
        else:
            keys.add(key_name)
    return keys

def test_translation_files_exist():
    """Verify that German and English translation files exist in the assets directory."""
    base_path = get_base_path()
    de_path = os.path.join(base_path, "assets", "translations", "de.json")
    en_path = os.path.join(base_path, "assets", "translations", "en.json")
    
    # Dev path fallback check
    if not os.path.exists(de_path):
        de_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "translations", "de.json")
        en_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "translations", "en.json")
        
    assert os.path.exists(de_path), f"German translation file not found at {de_path}"
    assert os.path.exists(en_path), f"English translation file not found at {en_path}"

def test_translation_keys_parity():
    """Verify that German and English translations have the exact same set of translation keys."""
    base_path = get_base_path()
    de_path = os.path.join(base_path, "assets", "translations", "de.json")
    en_path = os.path.join(base_path, "assets", "translations", "en.json")
    
    if not os.path.exists(de_path):
        de_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "translations", "de.json")
        en_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "translations", "en.json")

    with open(de_path, "r", encoding="utf-8") as f:
        de_data = json.load(f)
    with open(en_path, "r", encoding="utf-8") as f:
        en_data = json.load(f)

    de_keys = get_keys_recursive(de_data)
    en_keys = get_keys_recursive(en_data)

    missing_in_en = de_keys - en_keys
    missing_in_de = en_keys - de_keys

    assert not missing_in_en, f"Keys present in de.json but missing from en.json: {missing_in_en}"
    assert not missing_in_de, f"Keys present in en.json but missing from de.json: {missing_in_de}"

def test_translation_manager_loading_and_fallback():
    """Test TranslationManager loading languages and resolving keys correctly."""
    # Load German
    translator.load_language("de")
    assert translator.current_lang == "de"
    
    # Translate existing German key
    title = tr_ui("login.title", "Default Title")
    assert title == "OPENING FENIX"

    # Load English
    translator.load_language("en")
    assert translator.current_lang == "en"
    
    # Translate existing English key
    subtitle = tr_ui("login.subtitle", "Who's training?")
    assert subtitle == "Who is training today?"

    # Fallback to default if key not found
    fallback = tr_ui("non_existent_key", "Default Fallback")
    assert fallback == "Default Fallback"

def test_translation_formatting():
    """Test formatting and placeholder resolution in translations."""
    translator.load_language("de")
    loading_text = tr_ui("login.loading_trainer", "Loading...", profile_name="Magnus")
    assert "Magnus" in loading_text
    
    translator.load_language("en")
    loading_text_en = tr_ui("login.loading_trainer", "Loading...", profile_name="Hikaru")
    assert "Hikaru" in loading_text_en

    # Reset back to German default for other test suites
    translator.load_language("de")

def test_no_double_ampersands_in_translations():
    """Verify that no translation file stores raw double ampersands (&&).
    
    Translation strings should always contain natural human language (single '&').
    Escaping for Qt widgets (QGroupBox, QPushButton, etc.) is handled at the UI layer via tr_widget().
    """
    base_path = get_base_path()
    for lang in ["de", "en"]:
        path = os.path.join(base_path, "assets", "translations", f"{lang}.json")
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "translations", f"{lang}.json")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        def check_no_double_amp(d, prefix=""):
            violations = []
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    violations.extend(check_no_double_amp(v, full_key))
                elif isinstance(v, str) and "&&" in v:
                    violations.append((full_key, v))
            return violations

        violations = check_no_double_amp(data)
        assert not violations, f"Found double ampersands in {lang}.json: {violations}"

def test_escape_mnemonic_helper():
    """Test escape_mnemonic helper for Qt widgets."""
    from opening_fenix.core.translation import escape_mnemonic
    
    # Single & should be escaped to &&
    assert escape_mnemonic("Speicherort & Cloud") == "Speicherort && Cloud"
    assert escape_mnemonic("Sound & Sprache") == "Sound && Sprache"
    assert escape_mnemonic("&File") == "&&File"
    assert escape_mnemonic("A & B & C") == "A && B && C"
    
    # Already escaped && should not be double escaped
    assert escape_mnemonic("Speicherort && Cloud") == "Speicherort && Cloud"
    
    # Strings without & or empty
    assert escape_mnemonic("No ampersands") == "No ampersands"
    assert escape_mnemonic("") == ""
    assert escape_mnemonic(None) is None

def test_tr_widget_helper():
    """Test tr_widget helper which translates and escapes mnemonics automatically."""
    from opening_fenix.core.translation import tr_widget
    
    translator.load_language("de")
    # settings.storage_title in de.json is "📁 Speicherort & Cloud-Synchronisation"
    res = tr_widget("settings.storage_title", "📁 Speicherort & Cloud-Synchronisation")
    assert res == "📁 Speicherort && Cloud-Synchronisation"
    
    # Fallback default should also be escaped
    fallback_res = tr_widget("non_existent_key", "Custom & Fallback")
    assert fallback_res == "Custom && Fallback"

