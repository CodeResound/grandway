"""Field validators for the checklists app.

The template-key rule is declared here rather than imported from ``institutions``
or ``leads``. The three apps happen to agree on the pattern, but importing a
validator across an app boundary creates an undocumented runtime coupling for a
one-line regex (§4) — and would make this app's keys change silently the day
another app loosened its own rule.
"""

from __future__ import annotations

from django.core.validators import RegexValidator

__all__ = ["TEMPLATE_KEY_PATTERN", "validate_template_key"]

# Template keys are ASCII system identifiers (§39.7) — never Devanagari. They
# appear in URLs, logs, and seed data, so they follow the same shape as every
# other code field in the project: lowercase letters, digits, and _ - only,
# starting and ending alphanumeric.
TEMPLATE_KEY_PATTERN = r"^[a-z0-9](?:[a-z0-9_-]{0,48}[a-z0-9])?$"

validate_template_key = RegexValidator(
    regex=TEMPLATE_KEY_PATTERN,
    message=(
        "Key must be ASCII: lowercase letters, digits, and _ - only, starting and ending with a letter or digit."
    ),
    code="invalid_template_key",
)
