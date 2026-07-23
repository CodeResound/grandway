"""Enums, error codes, and audit-action names for the applicants app.

``ContactNumberLabel`` is not defined here — it is shared with ``leads`` and
lives in ``core.constants`` (§2/§3).
"""

from django.db import models


class ApplicantStatus(models.TextChoices):
    """The person's standing with the consultancy.

    Deliberately separate from any journey stage: a person may have one journey
    that succeeded and another that was abandoned, and neither of those is the
    person's status (``concepts/applicants.txt`` — "Applicant status").
    """

    ACTIVE = "active", "Active"
    DORMANT = "dormant", "Dormant"
    ARCHIVED = "archived", "Archived"


class CreationSource(models.TextChoices):
    """How the applicant record came into existence.

    There are exactly two paths and the record remembers which one was used
    (``concepts/applicants.txt`` — "How an applicant comes into existence").
    """

    LEAD_CONVERSION = "lead_conversion", "Lead Conversion"
    DIRECT_ADMIN = "direct_admin", "Direct Admin Creation"


class Gender(models.TextChoices):
    MALE = "male", "Male"
    FEMALE = "female", "Female"
    OTHER = "other", "Other"
    UNDISCLOSED = "undisclosed", "Prefer not to say"


class AddressType(models.TextChoices):
    PERMANENT = "permanent", "Permanent"
    CURRENT = "current", "Current"


class FamilyRelationship(models.TextChoices):
    FATHER = "father", "Father"
    MOTHER = "mother", "Mother"
    SPOUSE = "spouse", "Spouse"
    SIBLING = "sibling", "Sibling"
    CHILD = "child", "Child"
    GUARDIAN = "guardian", "Guardian"
    OTHER = "other", "Other"


class ApplicantAuditAction:
    """``audit.AuditEvent.action`` names written by this app.

    The applicant's chronological history is the central audit log filtered to
    one applicant; this app owns no history table of its own.
    """

    APPLICANT_CREATED = "applicant_created"
    APPLICANT_UPDATED = "applicant_updated"
    APPLICANT_CONTACT_CHANGED = "applicant_contact_changed"
    APPLICANT_ADDRESS_CHANGED = "applicant_address_changed"
    APPLICANT_PASSPORT_CHANGED = "applicant_passport_changed"
    APPLICANT_FAMILY_CHANGED = "applicant_family_changed"
    APPLICANT_EMERGENCY_CONTACT_CHANGED = "applicant_emergency_contact_changed"
    APPLICANT_STATUS_CHANGED = "applicant_status_changed"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "applicants"

#: ``audit.AuditEvent.entity_type`` value.
AUDIT_ENTITY_APPLICANT = "applicant"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the applicants app (§7)."""

    APPLICANT_NOT_FOUND = "APPLICANTS_APPLICANT_NOT_FOUND"
    ACTOR_FORBIDDEN = "APPLICANTS_ACTOR_FORBIDDEN"
    CONTACT_REQUIRED = "APPLICANTS_CONTACT_REQUIRED"
    STATUS_UNCHANGED = "APPLICANTS_STATUS_UNCHANGED"
    PASSPORT_EXPIRY_INVALID = "APPLICANTS_PASSPORT_EXPIRY_INVALID"
