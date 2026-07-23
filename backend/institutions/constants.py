"""Enums, error codes, and audit-action names for the institutions app.

``StudyLevel`` is not defined here — it is shared with ``leads`` and
``applicant_journeys`` and lives in ``core.constants`` (§2/§3). A program's
qualification level and a journey's study level are the same vocabulary
deliberately, so "programs matching this objective" stays an equality check.
"""

from django.db import models


class AvailabilityStatus(models.TextChoices):
    """Whether a catalogue record can currently be offered.

    The catalogue's central distinction is between *exists* and *currently
    usable* (``concepts/institutions.txt`` — "Availability note"). A record is
    never deleted; it stops being offered.
    """

    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    SEASONAL = "seasonal", "Seasonal"
    INACTIVE = "inactive", "Inactive"


#: Statuses a record must hold to appear in shortlisting search by default.
#: ``SEASONAL`` is included: it is offered, just not year-round, and hiding it
#: would remove genuine options from counselling.
USABLE_STATUSES: tuple[str, ...] = (
    AvailabilityStatus.ACTIVE,
    AvailabilityStatus.SEASONAL,
)

#: Statuses that require the author to explain themselves in ``availability_note``.
NOTE_REQUIRED_STATUSES: tuple[str, ...] = (
    AvailabilityStatus.PAUSED,
    AvailabilityStatus.SEASONAL,
    AvailabilityStatus.INACTIVE,
)


class InstitutionType(models.TextChoices):
    """What kind of provider an institution is."""

    UNIVERSITY = "university", "University"
    COLLEGE = "college", "College"
    POLYTECHNIC = "polytechnic", "Polytechnic"
    LANGUAGE_SCHOOL = "language_school", "Language School"
    OTHER = "other", "Other"


class FeePeriod(models.TextChoices):
    """What a tuition amount actually covers.

    Recorded because "49,824" means nothing without it, and the same program
    is quoted per-year by one institution and per-program by the next.
    """

    PER_YEAR = "per_year", "Per Year"
    PER_SEMESTER = "per_semester", "Per Semester"
    TOTAL_PROGRAM = "total_program", "Total Program"


class CatalogueAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    FIELD_CREATED = "catalogue_field_created"
    FIELD_UPDATED = "catalogue_field_updated"
    COUNTRY_CREATED = "catalogue_country_created"
    COUNTRY_UPDATED = "catalogue_country_updated"
    INSTITUTION_CREATED = "catalogue_institution_created"
    INSTITUTION_UPDATED = "catalogue_institution_updated"
    CAMPUS_CREATED = "catalogue_campus_created"
    CAMPUS_UPDATED = "catalogue_campus_updated"
    PROGRAM_CREATED = "catalogue_program_created"
    PROGRAM_UPDATED = "catalogue_program_updated"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "institutions"

#: ``audit.AuditEvent.entity_type`` values.
#:
#: All five carry the ``catalogue_`` prefix. The audit log is shared across
#: every app, so a bare ``field`` or ``country`` would be ambiguous the moment
#: another app records an entity of the same name — and a set where only some
#: members are prefixed is worse than either convention applied consistently.
AUDIT_ENTITY_FIELD = "catalogue_field"
AUDIT_ENTITY_COUNTRY = "catalogue_country"
AUDIT_ENTITY_INSTITUTION = "catalogue_institution"
AUDIT_ENTITY_CAMPUS = "catalogue_campus"
AUDIT_ENTITY_PROGRAM = "catalogue_program"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the institutions app (§7)."""

    ACTOR_FORBIDDEN = "INSTITUTIONS_ACTOR_FORBIDDEN"

    FIELD_NOT_FOUND = "INSTITUTIONS_FIELD_NOT_FOUND"
    COUNTRY_NOT_FOUND = "INSTITUTIONS_COUNTRY_NOT_FOUND"
    INSTITUTION_NOT_FOUND = "INSTITUTIONS_INSTITUTION_NOT_FOUND"
    CAMPUS_NOT_FOUND = "INSTITUTIONS_CAMPUS_NOT_FOUND"
    PROGRAM_NOT_FOUND = "INSTITUTIONS_PROGRAM_NOT_FOUND"

    CODE_DUPLICATE = "INSTITUTIONS_CODE_DUPLICATE"
    CAMPUS_DUPLICATE = "INSTITUTIONS_CAMPUS_DUPLICATE"
    CAMPUS_INSTITUTION_MISMATCH = "INSTITUTIONS_CAMPUS_INSTITUTION_MISMATCH"
    AVAILABILITY_NOTE_REQUIRED = "INSTITUTIONS_AVAILABILITY_NOTE_REQUIRED"
    TUITION_INCOMPLETE = "INSTITUTIONS_TUITION_INCOMPLETE"
