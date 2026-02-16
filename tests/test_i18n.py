"""
Tests for i18n (internationalization) system.
"""

import pytest
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.lib.i18n import (
    load_translations,
    get_locale_from_path,
    get_translations,
    TranslationDict,
    SUPPORTED_LOCALES,
    DEFAULT_LOCALE,
    _translations_cache
)


class TestLoadTranslations:
    """Tests for load_translations function."""

    def teardown_method(self):
        """Clear translations cache after each test."""
        _translations_cache.clear()

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_load_translations_all_locales(self, locale):
        """Test loading translations for all supported locales."""
        translations = load_translations(locale)
        assert isinstance(translations, dict)
        assert len(translations) > 0

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_translations_have_required_keys(self, locale):
        """Test that all translations have required top-level keys."""
        translations = load_translations(locale)
        # Check for common keys that should exist
        assert "common" in translations
        assert "nav" in translations

    def test_load_invalid_locale_uses_default(self):
        """Test that invalid locale falls back to default."""
        translations = load_translations("xx")  # Invalid locale
        default_translations = load_translations(DEFAULT_LOCALE)
        assert translations == default_translations

    def test_translations_caching(self):
        """Test that translations are cached after first load."""
        _translations_cache.clear()
        
        # First load - should read from file
        translations1 = load_translations("de")
        assert "de" in _translations_cache
        
        # Second load - should use cache
        translations2 = load_translations("de")
        assert translations1 is translations2  # Same object reference

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_translations_contain_app_name(self, locale):
        """Test that each locale has app name defined."""
        translations = load_translations(locale)
        assert "common" in translations
        assert "app_name" in translations["common"]
        assert len(translations["common"]["app_name"]) > 0


class TestGetLocaleFromPath:
    """Tests for get_locale_from_path function."""

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_extract_locale_from_simple_path(self, locale):
        """Test extracting locale from simple paths."""
        path = f"/{locale}"
        assert get_locale_from_path(path) == locale

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_extract_locale_from_nested_path(self, locale):
        """Test extracting locale from nested paths."""
        paths = [
            f"/{locale}/clubs",
            f"/{locale}/leagues",
            f"/{locale}/teams",
            f"/{locale}/games",
            f"/{locale}/rankings"
        ]
        for path in paths:
            assert get_locale_from_path(path) == locale

    def test_extract_locale_from_path_with_trailing_slash(self):
        """Test extracting locale from path with trailing slash."""
        assert get_locale_from_path("/de/") == "de"
        assert get_locale_from_path("/en/clubs/") == "en"

    def test_extract_locale_from_path_without_leading_slash(self):
        """Test extracting locale from path without leading slash."""
        assert get_locale_from_path("de") == "de"
        assert get_locale_from_path("fr/clubs") == "fr"

    def test_invalid_locale_returns_default(self):
        """Test that invalid locale returns default."""
        assert get_locale_from_path("/xx") == DEFAULT_LOCALE
        assert get_locale_from_path("/invalid/path") == DEFAULT_LOCALE

    def test_empty_path_returns_default(self):
        """Test that empty path returns default locale."""
        assert get_locale_from_path("") == DEFAULT_LOCALE
        assert get_locale_from_path("/") == DEFAULT_LOCALE

    def test_path_without_locale_returns_default(self):
        """Test path without locale returns default."""
        assert get_locale_from_path("/clubs") == DEFAULT_LOCALE


class TestTranslationDict:
    """Tests for TranslationDict class."""

    def test_translation_dict_basic_access(self):
        """Test basic dictionary access."""
        data = {"key1": "value1", "key2": "value2"}
        t = TranslationDict(data)
        assert t["key1"] == "value1"
        assert t["key2"] == "value2"

    def test_translation_dict_dot_notation(self):
        """Test dot notation access."""
        data = {"key1": "value1", "key2": "value2"}
        t = TranslationDict(data)
        assert t.key1 == "value1"
        assert t.key2 == "value2"

    def test_translation_dict_nested_access(self):
        """Test nested dictionary access."""
        data = {
            "common": {
                "app_name": "SwissUnihockey",
                "language": "English"
            },
            "nav": {
                "home": "Home",
                "clubs": "Clubs"
            }
        }
        t = TranslationDict(data)
        
        # Bracket notation
        assert t["common"]["app_name"] == "SwissUnihockey"
        
        # Dot notation
        assert t.common.app_name == "SwissUnihockey"
        assert t.nav.home == "Home"
        assert t.nav.clubs == "Clubs"

    def test_translation_dict_missing_key_raises_error(self):
        """Test that accessing missing key raises AttributeError."""
        data = {"key1": "value1"}
        t = TranslationDict(data)
        
        with pytest.raises(AttributeError, match="Translation key.*not found"):
            _ = t.nonexistent_key

    def test_translation_dict_deeply_nested(self):
        """Test deeply nested structures."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "deep value"
                    }
                }
            }
        }
        t = TranslationDict(data)
        assert t.level1.level2.level3.value == "deep value"


class TestGetTranslations:
    """Tests for get_translations function."""

    def teardown_method(self):
        """Clear translations cache after each test."""
        _translations_cache.clear()

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_get_translations_returns_translation_dict(self, locale):
        """Test that get_translations returns TranslationDict instance."""
        t = get_translations(locale)
        assert isinstance(t, TranslationDict)

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_get_translations_dot_notation_works(self, locale):
        """Test dot notation access works on returned object."""
        t = get_translations(locale)
        # Should be able to access with dot notation
        assert hasattr(t, "common")
        assert hasattr(t.common, "app_name")

    def test_get_translations_invalid_locale_uses_default(self):
        """Test that invalid locale uses default translations."""
        t_invalid = get_translations("xx")
        t_default = get_translations(DEFAULT_LOCALE)
        
        # Should have same structure
        assert t_invalid.common.app_name == t_default.common.app_name


class TestSupportedLocales:
    """Tests for supported locales configuration."""

    def test_supported_locales_list(self):
        """Test that supported locales list is correct."""
        assert SUPPORTED_LOCALES == ["de", "en", "fr", "it"]
        assert len(SUPPORTED_LOCALES) == 4

    def test_default_locale(self):
        """Test that default locale is German."""
        assert DEFAULT_LOCALE == "de"

    def test_default_locale_in_supported(self):
        """Test that default locale is in supported list."""
        assert DEFAULT_LOCALE in SUPPORTED_LOCALES


class TestTranslationContent:
    """Tests for actual translation content."""

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_common_section_exists(self, locale):
        """Test that common section exists in all locales."""
        t = get_translations(locale)
        assert hasattr(t, "common")
        assert hasattr(t.common, "app_name")

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_nav_section_exists(self, locale):
        """Test that nav section exists in all locales."""
        t = get_translations(locale)
        assert hasattr(t, "nav")

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_page_specific_sections_exist(self, locale):
        """Test that page-specific sections exist (home, clubs, etc.)."""
        t = get_translations(locale)
        # Translation files use individual page sections, not a parent "pages" section
        assert hasattr(t, "home")
        assert hasattr(t, "clubs")
        assert hasattr(t, "games")
        assert hasattr(t, "rankings")

    def test_german_translations(self):
        """Test specific German translations."""
        t = get_translations("de")
        assert "SwissUnihockey" in t.common.app_name

    def test_english_translations(self):
        """Test specific English translations."""
        t = get_translations("en")
        assert "SwissUnihockey" in t.common.app_name

    def test_french_translations(self):
        """Test specific French translations."""
        t = get_translations("fr")
        assert "SwissUnihockey" in t.common.app_name

    def test_italian_translations(self):
        """Test specific Italian translations."""
        t = get_translations("it")
        assert "SwissUnihockey" in t.common.app_name


class TestTranslationsConsistency:
    """Tests to ensure translation files are consistent across locales."""

    def get_all_keys(self, d, prefix=''):
        """Recursively get all keys from nested dict."""
        keys = []
        for k, v in d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, TranslationDict)):
                keys.extend(self.get_all_keys(dict(v), new_key))
            else:
                keys.append(new_key)
        return set(keys)

    def test_all_locales_have_same_structure(self):
        """Test that all locale files have the same key structure."""
        base_keys = None
        
        for locale in SUPPORTED_LOCALES:
            translations = load_translations(locale)
            current_keys = self.get_all_keys(translations)
            
            if base_keys is None:
                base_keys = current_keys
            else:
                # All locales should have the same keys
                missing_keys = base_keys - current_keys
                extra_keys = current_keys - base_keys
                
                assert len(missing_keys) == 0, f"{locale} missing keys: {missing_keys}"
                assert len(extra_keys) == 0, f"{locale} has extra keys: {extra_keys}"

    @pytest.mark.parametrize("locale", ["de", "en", "fr", "it"])
    def test_no_empty_translations(self, locale):
        """Test that no translation values are empty strings."""
        def check_values(d, path=''):
            for k, v in d.items():
                current_path = f"{path}.{k}" if path else k
                if isinstance(v, dict):
                    check_values(v, current_path)
                else:
                    assert v != "", f"Empty translation at {locale}:{current_path}"
        
        translations = load_translations(locale)
        check_values(translations)
