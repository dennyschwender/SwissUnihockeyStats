"""
Translations for player biographical fields sourced from the SwissUnihockey API.

The API returns German strings for position and license type.
These mappings translate known values to the app's four supported locales.
Unknown strings fall back to the raw API value.
"""
from typing import Optional

# Position strings as returned by the API (German)
_POSITION_MAP: dict[str, dict[str, str]] = {
    "Stürmer": {
        "de": "Stürmer",
        "en": "Forward",
        "fr": "Attaquant",
        "it": "Attaccante",
    },
    "Verteidiger": {
        "de": "Verteidiger",
        "en": "Defender",
        "fr": "Défenseur",
        "it": "Difensore",
    },
    "Torhüter": {
        "de": "Torhüter",
        "en": "Goalkeeper",
        "fr": "Gardien",
        "it": "Portiere",
    },
}

# License prefix replacements (order matters — longest first)
# Each tuple: (German prefix, locale → replacement)
_LICENSE_PREFIX_MAP: list[tuple[str, dict[str, str]]] = [
    (
        "Herren Aktive",
        {"de": "Herren Aktive", "en": "Men Active", "fr": "Hommes Actifs", "it": "Uomini Attivi"},
    ),
    (
        "Damen Aktive",
        {"de": "Damen Aktive", "en": "Women Active", "fr": "Femmes Actives", "it": "Donne Attive"},
    ),
]


def translate_position(raw: Optional[str], locale: str) -> Optional[str]:
    """Translate a raw API position string to the given locale.

    Returns the raw string if no mapping exists. Returns None if raw is None.
    """
    if raw is None:
        return None
    entry = _POSITION_MAP.get(raw)
    if entry is None:
        return raw
    return entry.get(locale, raw)


def translate_license(raw: Optional[str], locale: str) -> Optional[str]:
    """Translate a raw API license string to the given locale.

    Only the known prefix is translated; the remainder of the string is kept as-is.
    Returns the raw string if no prefix matches. Returns None if raw is None.
    """
    if raw is None:
        return None
    for german_prefix, translations in _LICENSE_PREFIX_MAP:
        if raw.startswith(german_prefix):
            translated_prefix = translations.get(locale, german_prefix)
            suffix = raw[len(german_prefix):]
            return translated_prefix + suffix
    return raw
