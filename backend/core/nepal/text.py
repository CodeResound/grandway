"""
Text utilities for user-entered values.

Design rules:
- NFC normalization is applied to ALL user-entered text on write. Even in an
  English-only system this matters: accented characters in a transliterated
  name ("Bhattarai" vs a composed/decomposed "Bhattaraï") have multiple Unicode
  representations that look identical but compare and index differently.

This module previously also held Devanagari script detection and romanization,
which existed to support the bilingual `_np`/`_romanized` field pattern. Names
are now stored once, in English, so there is nothing to transliterate.
"""

from __future__ import annotations

import unicodedata


def normalize_unicode(text: str) -> str:
    """NFC-normalize a string. Apply to all user-entered text on write."""
    if not text:
        return text
    return unicodedata.normalize("NFC", text)
