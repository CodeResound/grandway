"""Field validators shared across two or more apps (§2).

App-specific validators stay in their owning app's ``validators.py``. This file
holds only rules that genuinely apply in more than one app — §3 forbids
duplicating a validator across apps.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

from core.constants import (
    NOTE_BACKDATED_THRESHOLD,
    NOTE_FUTURE_TOLERANCE,
    AcademicScoreType,
    CalendarSystem,
    LanguageTestType,
)
from core.nepal.calendar import fiscal_year_gregorian_range, nepal_today, to_bs

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


def noted_at_is_in_future(noted_at: datetime, *, now: datetime | None = None) -> bool:
    """True when a note claims a time later than now, beyond clock-skew tolerance.

    ``noted_at`` is set by the user so a note can be backdated — a visit
    written up the next morning. It has no lower bound, but a note cannot
    record something that has not happened yet. Used by ``leads`` and
    ``applicants``, which raise their own error code.
    """
    return noted_at > (now or timezone.now()) + NOTE_FUTURE_TOLERANCE


def note_is_backdated(*, created_at: datetime | None, noted_at: datetime | None) -> bool:
    """True when a note was written well after the moment it records."""
    if created_at is None or noted_at is None:
        return False
    return created_at - noted_at > NOTE_BACKDATED_THRESHOLD


# ---------------------------------------------------------------------------
# Scores and years — shared by lead enquiries and applicant records, so the two
# can never disagree about what a valid IELTS band or pass year is (§4). Each
# returns an error message or ``None``; callers assemble per-field details.
# ---------------------------------------------------------------------------

#: (minimum, maximum, step) per language test. Section scores use the same range.
LANGUAGE_SCORE_RANGES: dict[str, tuple[Decimal, Decimal, Decimal | None]] = {
    LanguageTestType.IELTS: (Decimal("0"), Decimal("9"), Decimal("0.5")),
    LanguageTestType.PTE: (Decimal("10"), Decimal("90"), None),
    LanguageTestType.TOEFL: (Decimal("0"), Decimal("120"), None),
    LanguageTestType.DUOLINGO: (Decimal("10"), Decimal("160"), None),
}

ACADEMIC_SCORE_RANGES: dict[str, tuple[Decimal, Decimal]] = {
    AcademicScoreType.GPA: (Decimal("0"), Decimal("4")),
    AcademicScoreType.PERCENTAGE: (Decimal("0"), Decimal("100")),
}

#: Earliest accepted year per calendar. The latest is the current year + 1.
EARLIEST_YEAR: dict[str, int] = {CalendarSystem.BS: 2000, CalendarSystem.AD: 1950}


def _as_decimal(value: object) -> Decimal | None:
    """A number from a serializer (Decimal) or a direct service caller (int, float, str); None if not numeric."""
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def language_score_error(test_type: str, value: object) -> str | None:
    """Why ``value`` is not a valid score for ``test_type``, or None when it is (or is absent)."""
    if value is None:
        return None
    value = _as_decimal(value)
    if value is None:
        return "Must be a number."
    if value < 0:
        return "Must not be negative."
    bounds = LANGUAGE_SCORE_RANGES.get(test_type)
    if bounds is None:
        return None
    low, high, step = bounds
    if not low <= value <= high:
        return f"Must be between {low} and {high} for {LanguageTestType(test_type).label}."
    if step is not None and value % step != 0:
        return f"Must be in steps of {step} for {LanguageTestType(test_type).label}."
    return None


def academic_score_error(score_type: str, value: object) -> str | None:
    """Why ``value`` is not a valid score of ``score_type``, or None."""
    if value is None or score_type not in ACADEMIC_SCORE_RANGES:
        return None
    value = _as_decimal(value)
    if value is None:
        return "Must be a number."
    low, high = ACADEMIC_SCORE_RANGES[score_type]
    if not low <= value <= high:
        return f"Must be between {low} and {high} for {AcademicScoreType(score_type).label}."
    return None


def current_year(calendar: str) -> int:
    """This year in ``calendar``, taken in Nepal time (§39.5)."""
    today = nepal_today()
    return to_bs(today).year if calendar == CalendarSystem.BS else today.year


def year_error(year: int | None, calendar: str) -> str | None:
    """Why ``year`` is out of range for ``calendar``, or None. A year with no calendar is the caller's to reject."""
    if year is None or calendar not in EARLIEST_YEAR:
        return None
    low, high = EARLIEST_YEAR[calendar], current_year(calendar) + 1
    if not low <= year <= high:
        return f"Must be between {low} and {high} ({CalendarSystem(calendar).label})."
    return None


#: The score fields a language-test entry carries (lead certificate or applicant test).
LANGUAGE_SCORE_FIELDS = ("overall_score", "listening_score", "reading_score", "writing_score", "speaking_score")


def language_test_errors(entry: dict, path: str) -> dict[str, str]:
    """Every rule broken by one language-test entry, keyed ``<path>.<field>``.

    Shared by ``leads`` (certificates on an enquiry) and ``applicants``
    (language tests on a file) — conversion copies one into the other, so they
    must accept exactly the same values. ``test_date`` may not be in the future
    (Nepal time); ``expiry_date`` must follow ``test_date`` when both are set.
    """
    errors: dict[str, str] = {}
    test_type = entry.get("test_type", "")
    for field in LANGUAGE_SCORE_FIELDS:
        message = language_score_error(test_type, entry.get(field))
        if message:
            errors[f"{path}.{field}"] = message
    test_date, expiry_date = entry.get("test_date"), entry.get("expiry_date")
    if test_date and test_date > nepal_today():
        errors[f"{path}.test_date"] = "Must not be in the future."
    if test_date and expiry_date and expiry_date <= test_date:
        errors[f"{path}.expiry_date"] = "Must be after test_date."
    return errors
