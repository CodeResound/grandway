"""Global constants shared across two or more apps (§2).

App-specific enums stay in their owning app's ``constants.py``. Only vocabulary
that genuinely belongs to more than one app lives here — §3 forbids duplicating
an enum across apps, and a shared enum owned by one app would invert the
dependency (``applicant_journeys`` must not import from ``leads``).
"""

from datetime import timedelta

from django.db import models


class ErrorCode:
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


class StudyLevel(models.TextChoices):
    """Level of study a person is aiming at.

    Used by ``leads`` (preliminary study interest) and ``applicant_journeys``
    (the authoritative objective); ``education`` will use it too.
    """

    SCHOOL = "school", "School"
    CERTIFICATE = "certificate", "Certificate"
    DIPLOMA = "diploma", "Diploma"
    BACHELORS = "bachelors", "Bachelor's"
    POSTGRADUATE_DIPLOMA = "postgraduate_diploma", "Postgraduate Diploma"
    MASTERS = "masters", "Master's"
    PHD = "phd", "PhD"
    OTHER = "other", "Other"


class LanguageTestStatus(models.TextChoices):
    """Where a person stands on a language test.

    Used by ``leads`` at enquiry time; ``test_scores`` will own the actual
    attempts.
    """

    NOT_TAKEN = "not_taken", "Not Taken"
    PREPARING = "preparing", "Preparing"
    BOOKED = "booked", "Booked"
    TAKEN = "taken", "Taken"
    NOT_REQUIRED = "not_required", "Not Required"


class FeePeriod(models.TextChoices):
    """What a quoted fee amount actually covers.

    Recorded because "49,824" means nothing without it, and the same program is
    quoted per-year by one institution and per-program by the next. Owned here
    rather than by ``institutions`` because ``offers`` records the tuition the
    institution actually quoted in its decision letter, which is a separate
    fact from the catalogue's indicative figure and must use one vocabulary.
    """

    PER_YEAR = "per_year", "Per Year"
    PER_SEMESTER = "per_semester", "Per Semester"
    TOTAL_PROGRAM = "total_program", "Total Program"


class ContactNumberLabel(models.TextChoices):
    """What kind of number a stored contact entry is.

    Used by ``leads`` and ``applicants``, which model contact numbers
    identically.
    """

    MOBILE = "mobile", "Mobile"
    HOME = "home", "Home"
    WORK = "work", "Work"
    WHATSAPP = "whatsapp", "WhatsApp"
    VIBER = "viber", "Viber"
    OTHER = "other", "Other"


class NoteCategory(models.TextChoices):
    """What kind of note a staff member wrote.

    Shared by ``leads`` (notes on an enquiry) and ``applicants`` (notes on the
    person), because a lead's notes are carried onto the applicant at
    conversion and must mean the same thing on both sides. ``visit`` is a
    record of an in-person office visit; everything else is ``general``.
    Extensible — a ``call`` category is the obvious next one.
    """

    GENERAL = "general", "General"
    VISIT = "visit", "Visit"


#: Longest note body accepted, in characters.
NOTE_BODY_MAX_LENGTH = 10_000

#: How far ahead of the server clock ``noted_at`` may be. A note records
#: something that already happened; a few minutes absorbs client clock skew.
NOTE_FUTURE_TOLERANCE = timedelta(minutes=5)

#: A note whose ``noted_at`` is this much earlier than when it was saved is
#: reported as backdated — written after the fact.
NOTE_BACKDATED_THRESHOLD = timedelta(minutes=15)

#: Orderings a notes list accepts (``?ordering=``). ``-noted_at`` is the default.
NOTE_ORDERINGS = ("-noted_at", "noted_at", "-created_at")


class HighestQualification(models.TextChoices):
    """A person's highest completed qualification, on the Nepali ladder.

    Shared by ``leads`` (what an enquirer reports) and ``applicants`` (the
    education record it becomes at conversion), which map 1:1. Distinct from
    ``StudyLevel``, which is the level a person is *aiming at*.
    """

    SEE = "see", "SEE / SLC"
    PLUS_TWO = "plus_two", "+2 / NEB"
    DIPLOMA = "diploma", "Diploma"
    BACHELOR = "bachelor", "Bachelor"
    MASTER = "master", "Master"
    PHD = "phd", "PhD"
    OTHER = "other", "Other"


class LanguageTestType(models.TextChoices):
    """Which language test a score belongs to.

    Shared by lead certificates and applicant language tests, which are copied
    1:1 at conversion. A fixed enum by decision (2026-10-29): SAT, GRE, and a
    configurable test catalogue are out of scope; ``other`` is unvalidated.
    """

    IELTS = "ielts", "IELTS"
    PTE = "pte", "PTE"
    TOEFL = "toefl", "TOEFL"
    DUOLINGO = "duolingo", "Duolingo"
    OTHER = "other", "Other"


class AcademicScoreType(models.TextChoices):
    """How an academic score is expressed. Divisions and letter grades go in a free-text label."""

    GPA = "gpa", "GPA"
    PERCENTAGE = "percentage", "Percentage"


class CalendarSystem(models.TextChoices):
    """Which calendar a bare year is in. A BS year spans two AD years, so it cannot be converted after the fact."""

    BS = "bs", "Bikram Sambat"
    AD = "ad", "Gregorian (AD)"
