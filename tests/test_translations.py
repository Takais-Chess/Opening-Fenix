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
