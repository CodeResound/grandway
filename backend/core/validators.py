"""Field validators shared across two or more apps (§2).

App-specific validators stay in their owning app's ``validators.py``. This file
holds only rules that genuinely apply in more than one app — §3 forbids
duplicating a validator across apps.
"""

from __future__ import annotations

from django.core.validators import RegexValidator

# Contact numbers are stored as entered, minus surrounding whitespace. Nepali
# mobile numbers, landlines with area codes, and +country-code forms must all
# fit, so the rule is deliberately permissive: digits, spaces, and + - ( ).
# Permissive is not the same as absent — free text is still refused.
CONTACT_NUMBER_PATTERN = r"^\+?[0-9][0-9 ()\-]{4,31}$"

validate_contact_number = RegexValidator(
    regex=CONTACT_NUMBER_PATTERN,
    message="Contact number may contain digits, spaces, and + - ( ) only.",
    code="invalid_contact_number",
)
