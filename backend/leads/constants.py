"""Enums, error codes, and audit-action names for the leads app.

Every choice field in ``leads.models`` draws its values from this module (§8);
no raw status strings are scattered across the codebase.
"""

from django.db import models


class LeadStage(models.TextChoices):
    """The eight V1 lead stages (``concepts/leads.txt`` — "Lead stages").

    ``CONVERTED`` and ``LOST`` are terminal and are never reachable through the
    ordinary stage dropdown — see ``ACTIVE_STAGES`` below and
    ``leads.services.change_stage``.
    """

    NEW = "new", "New"
    CONTACT_ATTEMPTED = "contact_attempted", "Contact Attempted"
    CONTACTED = "contacted", "Contacted"
    COUNSELLING = "counselling", "Counselling"
    FOLLOW_UP = "follow_up", "Follow-up"
    READY_FOR_CONVERSION = "ready_for_conversion", "Ready for Conversion"
    CONVERTED = "converted", "Converted"
    LOST = "lost", "Lost"


#: Stages a user may move between freely with the stage dropdown.
#: ``LOST`` is reachable only via ``mark_lost`` (a reason is mandatory) and
#: ``CONVERTED`` only via the Admin conversion action — never by dropdown.
ACTIVE_STAGES: tuple[str, ...] = (
    LeadStage.NEW,
    LeadStage.CONTACT_ATTEMPTED,
    LeadStage.CONTACTED,
    LeadStage.COUNSELLING,
    LeadStage.FOLLOW_UP,
    LeadStage.READY_FOR_CONVERSION,
)

#: Terminal stages. A lead here must be reopened before it can move again.
TERMINAL_STAGES: tuple[str, ...] = (LeadStage.CONVERTED, LeadStage.LOST)

#: Stage a reopened lead lands on unless the caller picks another active stage.
DEFAULT_REOPEN_STAGE: str = LeadStage.FOLLOW_UP


class StudyLevel(models.TextChoices):
    """Intended study level on a preliminary study interest."""

    SCHOOL = "school", "School"
    CERTIFICATE = "certificate", "Certificate"
    DIPLOMA = "diploma", "Diploma"
    BACHELORS = "bachelors", "Bachelor's"
    POSTGRADUATE_DIPLOMA = "postgraduate_diploma", "Postgraduate Diploma"
    MASTERS = "masters", "Master's"
    PHD = "phd", "PhD"
    OTHER = "other", "Other"


class LanguageTestStatus(models.TextChoices):
    """Where the person stands on a language test at enquiry time."""

    NOT_TAKEN = "not_taken", "Not Taken"
    PREPARING = "preparing", "Preparing"
    BOOKED = "booked", "Booked"
    TAKEN = "taken", "Taken"
    NOT_REQUIRED = "not_required", "Not Required"


class ContactNumberLabel(models.TextChoices):
    """What kind of number a lead contact entry is."""

    MOBILE = "mobile", "Mobile"
    HOME = "home", "Home"
    WORK = "work", "Work"
    WHATSAPP = "whatsapp", "WhatsApp"
    VIBER = "viber", "Viber"
    OTHER = "other", "Other"


class LeadAuditAction:
    """``audit.AuditEvent.action`` names written by this app.

    The lead's chronological history (``concepts/leads.txt`` — "Notes and
    history") is the central audit log filtered to one lead; this app owns no
    history table of its own. ``AuditEvent.action`` is a free CharField, so
    these are plain string constants rather than a choices enum.
    """

    LEAD_CREATED = "lead_created"
    LEAD_UPDATED = "lead_updated"
    LEAD_CONTACT_CHANGED = "lead_contact_changed"
    LEAD_SOURCE_CHANGED = "lead_source_changed"
    LEAD_INTEREST_CHANGED = "lead_interest_changed"
    LEAD_STAGE_CHANGED = "lead_stage_changed"
    LEAD_FOLLOWUP_RECORDED = "lead_followup_recorded"
    LEAD_MARKED_LOST = "lead_marked_lost"
    LEAD_REOPENED = "lead_reopened"
    LEAD_NOTE_ADDED = "lead_note_added"
    LEAD_CONVERTED = "lead_converted"
    LEAD_APPLICANT_CREATED = "lead_applicant_created"

    SOURCE_CREATED = "lead_source_created"
    SOURCE_UPDATED = "lead_source_updated"
    LOSS_REASON_CREATED = "loss_reason_created"
    LOSS_REASON_UPDATED = "loss_reason_updated"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "leads"

#: ``audit.AuditEvent.entity_type`` values.
AUDIT_ENTITY_LEAD = "lead"
AUDIT_ENTITY_SOURCE = "lead_source"
AUDIT_ENTITY_LOSS_REASON = "loss_reason"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the leads app (§7)."""

    # Lead
    LEAD_NOT_FOUND = "LEADS_LEAD_NOT_FOUND"
    LEAD_NOT_LOST = "LEADS_LEAD_NOT_LOST"
    CONTACT_REQUIRED = "LEADS_CONTACT_REQUIRED"

    # Stage transitions
    STAGE_INVALID_TRANSITION = "LEADS_STAGE_INVALID_TRANSITION"
    STAGE_NOT_EDITABLE = "LEADS_STAGE_NOT_EDITABLE"

    # Marking lost
    LOSS_REASON_REQUIRED = "LEADS_LOSS_REASON_REQUIRED"
    LOSS_DETAIL_REQUIRED = "LEADS_LOSS_DETAIL_REQUIRED"

    # Reference configuration
    SOURCE_NOT_FOUND = "LEADS_SOURCE_NOT_FOUND"
    SOURCE_INACTIVE = "LEADS_SOURCE_INACTIVE"
    SOURCE_DETAIL_REQUIRED = "LEADS_SOURCE_DETAIL_REQUIRED"
    SOURCE_CODE_TAKEN = "LEADS_SOURCE_CODE_TAKEN"
    LOSS_REASON_NOT_FOUND = "LEADS_LOSS_REASON_NOT_FOUND"
    LOSS_REASON_INACTIVE = "LEADS_LOSS_REASON_INACTIVE"
    LOSS_REASON_CODE_TAKEN = "LEADS_LOSS_REASON_CODE_TAKEN"

    # Access
    ACTOR_FORBIDDEN = "LEADS_ACTOR_FORBIDDEN"

    # Conversion (Phase 4 — endpoint not yet built)
    LEAD_ALREADY_CONVERTED = "LEADS_LEAD_ALREADY_CONVERTED"
    CONVERSION_NOT_READY = "LEADS_CONVERSION_NOT_READY"
