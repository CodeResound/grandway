"""Field and password validators for the authenticate app."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import RegexValidator

# Usernames are ASCII system identifiers (§39.7): lowercase letters, digits, and
# the separators . _ - only. Never Devanagari, never uppercase (normalized first).
USERNAME_PATTERN = r"^[a-z0-9](?:[a-z0-9._-]{0,148}[a-z0-9])?$"

validate_username_format = RegexValidator(
    regex=USERNAME_PATTERN,
    message=(
        "Username must be ASCII: lowercase letters, digits, and . _ - only, "
        "starting and ending with a letter or digit."
    ),
    code="invalid_username",
)


def validate_password_strength(password: str, user: object | None = None) -> None:
    """Run Django's configured password validators, raising DjangoValidationError.

    Callers translate the raised error into the standard API error envelope.
    """
    from django.contrib.auth.password_validation import validate_password

    validate_password(password, user=user)


def is_ascii(value: str) -> bool:
    return bool(re.fullmatch(r"[\x00-\x7F]*", value or ""))


def ensure_username_ascii(value: str) -> None:
    if not is_ascii(value):
        raise DjangoValidationError("Username must contain ASCII characters only.")
