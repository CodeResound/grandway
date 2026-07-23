"""Field validators for the leads app."""

from __future__ import annotations

from django.core.validators import RegexValidator

# Reference codes are ASCII system identifiers (§39.7) — never Devanagari.
# Lowercase letters, digits and _ - only, starting and ending alphanumeric.
REFERENCE_CODE_PATTERN = r"^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$"

validate_reference_code = RegexValidator(
    regex=REFERENCE_CODE_PATTERN,
    message=(
        "Code must be ASCII: lowercase letters, digits, and _ - only, " "starting and ending with a letter or digit."
    ),
    code="invalid_code",
)

# Contact numbers are stored as entered, minus surrounding whitespace. Nepal
# mobile numbers, landlines with area codes, and +country-code forms must all
# fit, so the rule is deliberately permissive: digits, spaces, and + - ( ).
CONTACT_NUMBER_PATTERN = r"^\+?[0-9][0-9 ()\-]{4,31}$"

validate_contact_number = RegexValidator(
    regex=CONTACT_NUMBER_PATTERN,
    message="Contact number may contain digits, spaces, and + - ( ) only.",
    code="invalid_contact_number",
)
