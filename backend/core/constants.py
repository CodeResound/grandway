"""Global constants shared across two or more apps (§2).

App-specific enums stay in their owning app's ``constants.py``. Only vocabulary
that genuinely belongs to more than one app lives here — §3 forbids duplicating
an enum across apps, and a shared enum owned by one app would invert the
dependency (``applicant_journeys`` must not import from ``leads``).
"""

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
