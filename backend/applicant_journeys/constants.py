"""Enums, error codes, and audit-action names for the applicant_journeys app.

``StudyLevel`` is not defined here — it is shared with ``leads`` and lives in
``core.constants`` (§2/§3).
"""

from django.db import models


class JourneyStage(models.TextChoices):
    """The V1 journey stages (``concepts/applicant_journeys.txt``).

    ``COMPLETED`` and ``CLOSED`` are terminal and ``DEFERRED`` is paused; none
    of the three is reachable through the ordinary stage dropdown, because each
    demands information a stage change alone does not capture.
    """

    PLANNING = "planning", "Planning"
    PROFILE_BUILDING = "profile_building", "Profile Building"
    SHORTLISTING = "shortlisting", "Shortlisting"
    APPLYING = "applying", "Applying"
    OFFER_STAGE = "offer_stage", "Offer Stage"
    VISA_STAGE = "visa_stage", "Visa Stage"
    COMPLETED = "completed", "Completed"
    CLOSED = "closed", "Closed"
    DEFERRED = "deferred", "Deferred"


#: Stages a user may move between freely with the stage dropdown.
ACTIVE_STAGES: tuple[str, ...] = (
    JourneyStage.PLANNING,
    JourneyStage.PROFILE_BUILDING,
    JourneyStage.SHORTLISTING,
    JourneyStage.APPLYING,
    JourneyStage.OFFER_STAGE,
    JourneyStage.VISA_STAGE,
)

#: Stages a journey must be reopened out of before it can move again.
TERMINAL_STAGES: tuple[str, ...] = (
    JourneyStage.COMPLETED,
    JourneyStage.CLOSED,
    JourneyStage.DEFERRED,
)

#: Stage a reopened journey lands on unless the caller picks another active one.
DEFAULT_REOPEN_STAGE: str = JourneyStage.PLANNING

#: Stage a journey created by lead conversion starts at.
INITIAL_STAGE: str = JourneyStage.PLANNING


class JourneyOutcome(models.TextChoices):
    """Why a journey ended.

    Taken from ``concepts/project_overview.txt``'s "Final outcome" glossary
    entry. Closing with ``SUCCESSFUL`` sets the stage to ``completed``; every
    other outcome sets it to ``closed``.
    """

    SUCCESSFUL = "successful", "Successful"
    WITHDRAWN = "withdrawn", "Withdrawn"
    REJECTED = "rejected", "Rejected"
    NOT_QUALIFIED = "not_qualified", "Not Qualified"
    CANCELLED = "cancelled", "Cancelled"
    OTHER = "other", "Other"


class CreationSource(models.TextChoices):
    """How the journey came into existence."""

    LEAD_CONVERSION = "lead_conversion", "Lead Conversion"
    MANUAL = "manual", "Manual"


class JourneyAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    JOURNEY_CREATED = "journey_created"
    JOURNEY_UPDATED = "journey_updated"
    JOURNEY_STAGE_CHANGED = "journey_stage_changed"
    JOURNEY_DEFERRED = "journey_deferred"
    JOURNEY_CLOSED = "journey_closed"
    JOURNEY_REOPENED = "journey_reopened"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "applicant_journeys"

#: ``audit.AuditEvent.entity_type`` value.
AUDIT_ENTITY_JOURNEY = "applicant_journey"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the applicant_journeys app (§7)."""

    JOURNEY_NOT_FOUND = "JOURNEYS_JOURNEY_NOT_FOUND"
    APPLICANT_NOT_FOUND = "JOURNEYS_APPLICANT_NOT_FOUND"
    COUNTRY_NOT_FOUND = "JOURNEYS_COUNTRY_NOT_FOUND"
    ACTOR_FORBIDDEN = "JOURNEYS_ACTOR_FORBIDDEN"
    STAGE_INVALID_TRANSITION = "JOURNEYS_STAGE_INVALID_TRANSITION"
    STAGE_NOT_EDITABLE = "JOURNEYS_STAGE_NOT_EDITABLE"
    OUTCOME_REQUIRED = "JOURNEYS_OUTCOME_REQUIRED"
    OUTCOME_DETAIL_REQUIRED = "JOURNEYS_OUTCOME_DETAIL_REQUIRED"
    DEFER_INTAKE_REQUIRED = "JOURNEYS_DEFER_INTAKE_REQUIRED"
    JOURNEY_NOT_TERMINAL = "JOURNEYS_JOURNEY_NOT_TERMINAL"
