"""
Devanagari text utilities: Unicode normalization, script detection,
and romanization for search indexing.

Design rules:
- NFC normalization is applied to ALL user-entered text on write, not just
  Nepali-labelled fields. Devanagari has multiple Unicode representations for
  the same visual character; normalizing on ingest ensures consistent storage
  and search behaviour.
- `romanize_devanagari()` produces a consistent, lowercase ASCII representation
  of a Devanagari string. It is used to auto-populate `name_romanized` fields
  so that Roman-script search queries can find Devanagari-primary records via
  PostgreSQL trigram indexes.
- The romanized form is a search aid, not a display field. Staff may manually
  override it (e.g. to prefer "Griha" over the generated "grha").
"""

from __future__ import annotations

import unicodedata

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

# Unicode ranges for Devanagari (U+0900–U+097F) and Devanagari Extended
_DEVANAGARI_RANGES = [(0x0900, 0x097F), (0xA8E0, 0xA8FF), (0x1CD0, 0x1CFF)]


def normalize_unicode(text: str) -> str:
    """NFC-normalize a string. Apply to all user-entered text on write."""
    if not text:
        return text
    return unicodedata.normalize("NFC", text)


def contains_devanagari(text: str) -> bool:
    """Return True if the text contains any Devanagari Unicode characters."""
    if not text:
        return False
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _DEVANAGARI_RANGES):
            return True
    return False


def contains_latin(text: str) -> bool:
    """Return True if the text contains any Latin Unicode characters."""
    if not text:
        return False
    for ch in text:
        if unicodedata.category(ch).startswith("L") and ord(ch) < 0x0370:
            return True
    return False


def romanize_devanagari(text: str) -> str:
    """Transliterate Devanagari text to lowercase ASCII for search indexing.

    Uses IAST transliteration then strips diacritical marks to produce clean
    ASCII. The output is lowercased and whitespace-normalized.

    Non-Devanagari segments (already Latin) are preserved as-is in lowercase.

    Example:
        "गृह मन्त्रालय" → "grha mantralaya"
        "Ministry of Home Affairs" → "ministry of home affairs"
        "MoHA" → "moha"
    """
    if not text:
        return ""

    text = normalize_unicode(text)

    if not contains_devanagari(text):
        return text.lower().strip()

    # Transliterate to IAST then decompose diacritics
    iast = transliterate(text, sanscript.DEVANAGARI, sanscript.IAST)
    nfd = unicodedata.normalize("NFD", iast)
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn" and ord(c) < 128)
    return " ".join(ascii_text.lower().split())
