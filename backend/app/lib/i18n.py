"""
i18n (Internationalization) utilities for SwissUnihockey.
Provides multi-language support for DE, EN, FR, IT.
"""

import json
from pathlib import Path
from typing import Dict, Any

# Supported languages
SUPPORTED_LOCALES = ["de", "en", "fr", "it"]
DEFAULT_LOCALE = "de"

# Cache for loaded translations
_translations_cache: Dict[str, Dict[str, Any]] = {}


def load_translations(locale: str) -> Dict[str, Any]:
    """
    Load translations for a given locale from JSON file.
    
    Args:
        locale: Language code (de, en, fr, it)
        
    Returns:
        Dictionary containing all translations for the locale
    """
    if locale not in SUPPORTED_LOCALES:
        locale = DEFAULT_LOCALE
    
    # Check cache first
    if locale in _translations_cache:
        return _translations_cache[locale]
    
    # Load from file
    locales_dir = Path(__file__).parent.parent / "locales"
    locale_file = locales_dir / locale / "messages.json"
    
    try:
        with open(locale_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
            _translations_cache[locale] = translations
            return translations
    except FileNotFoundError:
        # Fall back to default locale
        if locale != DEFAULT_LOCALE:
            return load_translations(DEFAULT_LOCALE)
        raise


def get_locale_from_path(path: str) -> str:
    """
    Extract locale from URL path.
    
    Args:
        path: URL path (e.g., "/de/clubs" or "/en")
        
    Returns:
        Locale code (de, en, fr, it) or default
    """
    parts = path.strip("/").split("/")
    if parts and parts[0] in SUPPORTED_LOCALES:
        return parts[0]
    return DEFAULT_LOCALE


class TranslationDict(dict):
    """
    Nested dictionary that allows accessing values with dot notation.
    Example: t.common.app_name instead of t["common"]["app_name"]
    """
    
    def __init__(self, data: dict):
        super().__init__()
        for key, value in data.items():
            if isinstance(value, dict):
                self[key] = TranslationDict(value)
            else:
                self[key] = value
    
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"Translation key '{key}' not found")


def get_translations(locale: str) -> TranslationDict:
    """
    Get translations for a locale as a nested object with dot notation access.
    
    Args:
        locale: Language code
        
    Returns:
        TranslationDict object allowing t.common.app_name syntax
    """
    translations = load_translations(locale)
    return TranslationDict(translations)
