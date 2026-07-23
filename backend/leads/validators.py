"""Field validators for the leads app.

Contact-number validation is shared with ``applicants`` and lives in
``core.validators`` (§2/§3); only the reference-code rule is specific to this
app's two configurable tables.
"""

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
