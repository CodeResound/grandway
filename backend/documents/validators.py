"""Field validators for the documents app.

``validate_template_key`` is declared here rather than imported from
``institutions``. The two rules look similar and are not the same: a catalogue
code allows underscores and caps at 50 characters, while a template key is
hyphen-only (the frontend's slugs are ``bank-mata-bageshwori-certificate``) and
needs 100. Importing a validator across an app boundary for a one-line regex
would create an undocumented runtime coupling (§4) and would break this app if
``institutions`` ever loosened its own rule — the same call ``institutions``
made about ``leads``.
"""

from __future__ import annotations

from django.core.validators import RegexValidator

# Template keys are ASCII slugs (§39.7) — never Devanagari. Lowercase letters
# and digits in hyphen-separated segments, with no leading, trailing, or
# doubled hyphen.
TEMPLATE_KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

validate_template_key = RegexValidator(
    regex=TEMPLATE_KEY_PATTERN,
    message=(
        "Template key must be a lowercase ASCII slug: letters and digits in hyphen-separated "
        "segments, e.g. 'bank-vyas-statement'."
    ),
    code="invalid_template_key",
)
