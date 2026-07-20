"""
Language detection for user-entered text.

Returns ISO 639-1 language codes: "ne" (Nepali), "en" (English), "mixed".

Used by:
- Search routing: determine which fields to search primarily
- AI context assembly: tag input language for AI orchestration layer
- Event log tagging: record what language an entry was written in

This is a lightweight heuristic detector — it does not load any ML model.
It works by character-script analysis, which is sufficient for the primary
use case (Devanagari vs Latin discrimination).
"""

from __future__ import annotations

from core.nepal.constants import LANG_ENGLISH, LANG_MIXED, LANG_NEPALI
from core.nepal.text import contains_devanagari, contains_latin


def detect_language(text: str) -> str:
    """Detect the dominant language of a text string.

    Returns:
        "ne"    — text is primarily Devanagari (Nepali)
        "en"    — text is primarily Latin (English or romanized)
        "mixed" — text contains both Devanagari and Latin characters

    Empty or whitespace-only text returns "en" as the safe default.
    """
    if not text or not text.strip():
        return LANG_ENGLISH

    has_dev = contains_devanagari(text)
    has_lat = contains_latin(text)

    if has_dev and has_lat:
        return LANG_MIXED
    if has_dev:
        return LANG_NEPALI
    return LANG_ENGLISH


def is_nepali(text: str) -> bool:
    """Return True if the text is primarily Devanagari."""
    return detect_language(text) == LANG_NEPALI


def is_english(text: str) -> bool:
    """Return True if the text is primarily Latin-script."""
    return detect_language(text) == LANG_ENGLISH
