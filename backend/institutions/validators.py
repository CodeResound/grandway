"""Field validators for the institutions app.

The reference-code rule is declared here rather than imported from ``leads``.
The two apps happen to agree on the pattern, but importing a validator across
an app boundary would create an undocumented runtime coupling for a two-line
regex (§4) — and would make ``institutions`` break if ``leads`` ever loosened
its own rule.
"""

from __future__ import annotations

from core.validators import validate_currency_code
from django.core.validators import RegexValidator

#: Re-exported so this app's models keep a single import site. The rule itself
#: moved to ``core.validators`` when ``offers`` began quoting currency amounts
#: too — a second app needing it makes it shared vocabulary (§2), and copying
#: the regex would have duplicated a validator across apps (§3).
__all__ = ["validate_currency_code", "validate_reference_code"]

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
