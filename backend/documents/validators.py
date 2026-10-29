"""Field validators for the documents app.

``validate_template_key`` is declared here rather than imported from
``institutions``. The two rules look similar and are not the same: a catalogue
code allows underscores and caps at 50 characters, while a template key is
hyphen-only (the frontend's slugs are ``bank-mata-bageshwori-certificate``) and
needs 100. Importing a validator across an app boundary for a one-line regex
would create an undocumented runtime coupling (§4) and would break this app if
``institutions`` ever loosened its own rule — the same call ``institutions``
made about ``leads``.

``validate_template_content`` is the one place the backend looks inside a
document body, and only for ``student-certificate`` — see its docstring.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.validators import RegexValidator

from documents.constants import STUDENT_CERTIFICATE_TEMPLATE_KEY
from documents.exceptions import ContentInvalidError

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


# ---------------------------------------------------------------------------
# Per-template content rules
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_GENDERS = ("male", "female", "other", "")
_GRADE_SUBJECTS = ("grammar", "listening", "conversation", "reading", "composition")
_GRADES = ("A", "B", "C", "D", "")

_MAX_COURSE_BOOKS = 20
_MAX_MARKING_MONTHS = 12

ContentErrors = dict[str, str]


def validate_template_content(*, template_key: str, content: dict[str, Any], applicant_id: Any) -> None:
    """Check a document body against its template's rules, where it has any.

    Only ``student-certificate`` has rules. Every other template stays opaque,
    for the reasons ``services.assert_content_storable`` gives. The certificate
    is the exception because its form now covers every printed field and the
    frontend asked for those keys to be checked (``updates.md`` §7.1).

    Lenient by design, so documents saved by older clients keep saving:

    * nothing is required — an absent key or ``null`` skips that key's check,
      and inside a ``marking`` row too;
    * unknown keys pass, including the camelCase keys of the older contract
      (``studyType``, ``studentName``, ``coursehour``) — they are stored as sent.

    Raises ``ContentInvalidError`` whose ``fields`` names every failing path.
    """
    rules = _TEMPLATE_CONTENT_RULES.get(template_key)
    if rules is None:
        return
    errors: ContentErrors = {}
    rules(content, applicant_id, errors)
    if errors:
        raise ContentInvalidError(f"Document content does not satisfy the '{template_key}' template.", fields=errors)


def _check_string(value: Any, path: str, max_length: int, errors: ContentErrors) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        errors[path] = "Must be a string."
    elif len(value) > max_length:
        errors[path] = f"Must be at most {max_length} characters."


def _check_choice(value: Any, path: str, choices: tuple[str, ...], errors: ContentErrors) -> None:
    if value is not None and value not in choices:
        errors[path] = "Must be one of: " + ", ".join(repr(c) for c in choices) + "."


def _check_date(value: Any, path: str, errors: ContentErrors) -> date | None:
    """A ``YYYY-MM-DD`` date, or ``""``/``null`` for "not entered"."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and _DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    errors[path] = "Must be a date in YYYY-MM-DD format."
    return None


def _as_decimal(value: Any) -> Decimal | None:
    """A JSON number or numeric string as a Decimal; None if it is neither.

    Floats go through ``str`` so ``0.1 + 0.2`` style binary noise cannot fail an
    ``present + absent <= class_hr`` comparison the user would read as equal.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        value = str(value)
    if isinstance(value, str) and value.strip():
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            return None
        return number if number.is_finite() else None
    return None


def _check_number(
    value: Any, path: str, errors: ContentErrors, *, minimum: Decimal, maximum: Decimal | None = None
) -> Decimal | None:
    if value is None:
        return None
    number = _as_decimal(value)
    if number is None:
        errors[path] = "Must be a number."
        return None
    if number < minimum or (maximum is not None and number > maximum):
        bound = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        errors[path] = f"Must be {bound}."
        return None
    return number


def _check_int(value: Any, path: str, errors: ContentErrors, *, minimum: int, maximum: int | None = None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        errors[path] = "Must be a whole number."
    elif value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        errors[path] = f"Must be {bound}."


def _check_marking(value: Any, errors: ContentErrors) -> None:
    """The 12-month attendance grid. ``present``/``absent`` are hours, not days."""
    if value is None:
        return
    if not isinstance(value, list):
        errors["marking"] = "Must be a list."
        return
    if len(value) > _MAX_MARKING_MONTHS:
        errors["marking"] = f"Must have at most {_MAX_MARKING_MONTHS} months."
        return
    seen_months: set[str] = set()
    for index, row in enumerate(value):
        path = f"marking[{index}]"
        if not isinstance(row, dict):
            errors[path] = "Must be an object."
            continue
        month = row.get("month")
        if month is not None:
            if not isinstance(month, str) or not _MONTH_RE.match(month):
                errors[f"{path}.month"] = "Must be a month in YYYY-MM format."
            elif month in seen_months:
                errors[f"{path}.month"] = "Each month may appear only once."
            else:
                seen_months.add(month)
        _check_int(row.get("total_days"), f"{path}.total_days", errors, minimum=0)
        class_hr = _check_number(row.get("class_hr"), f"{path}.class_hr", errors, minimum=Decimal(0))
        present = _check_number(row.get("present"), f"{path}.present", errors, minimum=Decimal(0))
        absent = _check_number(row.get("absent"), f"{path}.absent", errors, minimum=Decimal(0))
        _check_number(
            row.get("attendance_percentage"),
            f"{path}.attendance_percentage",
            errors,
            minimum=Decimal(0),
            maximum=Decimal(100),
        )
        if class_hr is not None and present is not None and absent is not None and present + absent > class_hr:
            errors[f"{path}.present"] = "Present and absent hours together cannot exceed class hours."


def _check_photo(value: Any, applicant_id: Any, errors: ContentErrors) -> None:
    """The printed photo must be a photograph uploaded for this same applicant.

    Read through ``uploaded_files``' selector — a documented runtime dependency
    (``docs/INTEGRATION.md`` §2). Imported here rather than at module level
    because ``uploaded_files`` already depends on this app, and a module-level
    import in both directions would be a cycle at import time.
    """
    if value is None:
        return
    try:
        file_id = uuid.UUID(str(value)) if isinstance(value, str) else None
    except ValueError:
        file_id = None
    if file_id is None:
        errors["photo_media_id"] = "Must be a file id (UUID) or null."
        return
    if applicant_id is None:
        errors["photo_media_id"] = "A photo can only be attached to a document that belongs to an applicant."
        return

    from uploaded_files.constants import FileCategory
    from uploaded_files.selectors import get_file_by_id

    photo = get_file_by_id(str(file_id))
    if photo is None or str(photo.applicant_id) != str(applicant_id):
        errors["photo_media_id"] = "No file with this id is on record for this document's applicant."
    elif photo.category != FileCategory.PHOTOGRAPH:
        errors["photo_media_id"] = "The file must be a photograph."
    elif photo.archived_at is not None:
        errors["photo_media_id"] = "The photograph has been archived."


def _student_certificate_rules(content: dict[str, Any], applicant_id: Any, errors: ContentErrors) -> None:
    for key in ("firstname", "middlename", "lastname", "course_name", "branch_name"):
        _check_string(content.get(key), key, 150, errors)
    _check_string(content.get("address"), "address", 300, errors)
    _check_string(content.get("course_level"), "course_level", 50, errors)
    _check_string(content.get("branch_no"), "branch_no", 50, errors)
    _check_choice(content.get("gender"), "gender", _GENDERS, errors)

    _check_date(content.get("date_of_birth"), "date_of_birth", errors)
    _check_date(content.get("issue"), "issue", errors)
    admitted = _check_date(content.get("date_of_admission"), "date_of_admission", errors)
    completed = _check_date(content.get("date_of_completion"), "date_of_completion", errors)
    if admitted and completed and completed < admitted:
        errors["date_of_completion"] = "Must be on or after date_of_admission."

    books = content.get("course_books")
    if books is not None:
        if not isinstance(books, list):
            errors["course_books"] = "Must be a list."
        elif len(books) > _MAX_COURSE_BOOKS:
            errors["course_books"] = f"Must have at most {_MAX_COURSE_BOOKS} items."
        else:
            for index, book in enumerate(books):
                _check_string(book, f"course_books[{index}]", 150, errors)

    _check_int(content.get("course_total_days"), "course_total_days", errors, minimum=0, maximum=1000)
    _check_number(
        content.get("course_hours_per_day"),
        "course_hours_per_day",
        errors,
        minimum=Decimal(0),
        maximum=Decimal(24),
    )
    _check_marking(content.get("marking"), errors)

    grades = content.get("grades")
    if grades is not None:
        if not isinstance(grades, dict):
            errors["grades"] = "Must be an object."
        else:
            for subject in _GRADE_SUBJECTS:
                _check_choice(grades.get(subject), f"grades.{subject}", _GRADES, errors)

    study_type = content.get("study_type")
    if study_type is not None and (isinstance(study_type, bool) or study_type not in (0, 1)):
        errors["study_type"] = "Must be 0 (studying) or 1 (completed)."

    _check_photo(content.get("photo_media_id"), applicant_id, errors)


_TEMPLATE_CONTENT_RULES: dict[str, Callable[[dict[str, Any], Any, ContentErrors], None]] = {
    STUDENT_CERTIFICATE_TEMPLATE_KEY: _student_certificate_rules,
}
