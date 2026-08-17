"""Field validators shared across two or more apps (§2).

App-specific validators stay in their owning app's ``validators.py``. This file
holds only rules that genuinely apply in more than one app — §3 forbids
duplicating a validator across apps.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from core.nepal.calendar import fiscal_year_gregorian_range

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

# ISO 4217 alpha-3, upper-cased before validation. Used by ``institutions``
# (catalogue tuition) and ``offers`` (the tuition, scholarship, and deposit
# figures an institution actually quoted).
CURRENCY_CODE_PATTERN = r"^[A-Z]{3}$"

validate_currency_code = RegexValidator(
    regex=CURRENCY_CODE_PATTERN,
    message="Currency must be a three-letter ISO 4217 code, e.g. AUD.",
    code="invalid_currency",
)


def validate_fiscal_year_label(value: str) -> None:
    """A Nepali fiscal-year label must actually resolve to a Gregorian range.

    Matching ``YYYY/YY`` is not enough: a format-valid label like ``9999/99``
    still raises inside ``fiscal_year_gregorian_range``, and a selector is the
    wrong place for that to surface (it becomes a 500 instead of a 400). Used
    by every list endpoint that accepts ``?fiscal_year=`` — §39.4.
    """
    try:
        fiscal_year_gregorian_range(value)
    except Exception as exc:
        raise ValidationError(
            "Must be a Nepali fiscal year as 'YYYY/YY', e.g. '2081/82'.",
            code="invalid_fiscal_year",
        ) from exc
