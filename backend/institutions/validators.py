"""Field validators for the institutions app.

The reference-code rule is declared here rather than imported from ``leads``.
The two apps happen to agree on the pattern, but importing a validator across
an app boundary would create an undocumented runtime coupling for a two-line
regex (§4) — and would make ``institutions`` break if ``leads`` ever loosened
its own rule.
"""

from __future__ import annotations

from django.core.validators import RegexValidator

# Catalogue codes are ASCII system identifiers (§39.7) — never Devanagari.
# Lowercase letters, digits and _ - only, starting and ending alphanumeric.
REFERENCE_CODE_PATTERN = r"^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$"

validate_reference_code = RegexValidator(
    regex=REFERENCE_CODE_PATTERN,
    message=(
        "Code must be ASCII: lowercase letters, digits, and _ - only, starting and ending with a letter or digit."
    ),
    code="invalid_code",
)

# ISO 4217 alpha-3, upper-cased before validation.
CURRENCY_CODE_PATTERN = r"^[A-Z]{3}$"

validate_currency_code = RegexValidator(
    regex=CURRENCY_CODE_PATTERN,
    message="Currency must be a three-letter ISO 4217 code, e.g. AUD.",
    code="invalid_currency",
)
