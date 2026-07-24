"""Business logic for the applicant_journeys app.

Services receive already-validated data, own every state transition, and return
model instances — never HTTP responses.

``create_journey`` is this app's public creation path and is called by ``leads``
during conversion (§4: another app imports services, never models).

Every mutation appends one event to the central audit log; that log *is* the
journey's chronological history.
"""

from __future__ import annotations

from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone

from applicant_journeys.constants import (
    ACTIVE_STAGES,
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_JOURNEY,
    DEFAULT_REOPEN_STAGE,
    CreationSource,
    JourneyAuditAction,
    JourneyOutcome,
    JourneyStage,
)
from applicant_journeys.exceptions import (
    DeferIntakeRequiredError,
    InvalidStageTransitionError,
    JourneyNotTerminalError,
    OutcomeDetailRequiredError,
    OutcomeRequiredError,
    StageNotEditableError,
)
from applicant_journeys.models import ApplicantJourney

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    journey: ApplicantJourney,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one journey audit event. Never pass secrets or full record dumps."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", ""),
        entity_type=AUDIT_ENTITY_JOURNEY,
        entity_id=str(journey.id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Creation and editing
# ---------------------------------------------------------------------------


def create_journey(
    *,
    actor: Any,
    applicant: Any,
    data: dict[str, Any],
    creation_source: str = CreationSource.MANUAL,
    ip_address: str | None = None,
) -> ApplicantJourney:
    """Record a new study objective for an applicant.

    Nothing beyond the applicant is required: a journey often begins as little
    more than "Australia, sometime next year."
    """
    journey = ApplicantJourney.objects.create(
        applicant=applicant,
        created_by=actor,
        creation_source=creation_source,
        stage=JourneyStage.PLANNING,
        **data,
    )
    _record(
        action=JourneyAuditAction.JOURNEY_CREATED,
        actor=actor,
        journey=journey,
        summary=f"Journey created for {journey.destination_label}.",
        metadata={"creation_source": creation_source, "applicant_id": str(applicant.id)},
        ip_address=ip_address,
    )
    return journey


def update_journey(
    *,
    actor: Any,
    journey: ApplicantJourney,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> ApplicantJourney:
    """Correct a journey's objective information.

    Stage is deliberately not editable here — it moves only through
    ``change_stage``, ``defer_journey``, ``close_journey``, or ``reopen_journey``.
    """
    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(journey, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(journey, field, value)

    if changes:
        journey.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=JourneyAuditAction.JOURNEY_UPDATED,
            actor=actor,
            journey=journey,
            summary="Journey information updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return journey


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


def _assert_stage_movable(journey: ApplicantJourney) -> None:
    """A terminal or deferred journey must be reopened before its stage moves."""
    if journey.is_terminal:
        raise StageNotEditableError("This journey is completed, closed, or deferred; reopen it first.")


def _assert_selectable_stage(stage: str) -> None:
    """The dropdown may only set active stages."""
    if stage not in ACTIVE_STAGES:
        raise InvalidStageTransitionError("This stage cannot be selected directly; use the close or defer action.")


def change_stage(
    *,
    actor: Any,
    journey: ApplicantJourney,
    stage: str,
    ip_address: str | None = None,
) -> ApplicantJourney:
    """Move a journey between active stages."""
    _assert_stage_movable(journey)
    _assert_selectable_stage(stage)

    previous = journey.stage
    if previous == stage:
        return journey

    journey.stage = stage
    journey.save(update_fields=["stage", "updated_at"])
    _record(
        action=JourneyAuditAction.JOURNEY_STAGE_CHANGED,
        actor=actor,
        journey=journey,
        summary=f"Stage changed from {previous} to {stage}.",
        changes={"stage": {"from": previous, "to": stage}},
        ip_address=ip_address,
    )
    return journey


@transaction.atomic
def defer_journey(
    *,
    actor: Any,
    journey: ApplicantJourney,
    to_intake: str,
    reason: str = "",
    ip_address: str | None = None,
) -> ApplicantJourney:
    """Pause a journey to a later intake.

    Deferment is not an outcome and closes nothing — the applicant intends to
    continue, just not on the current timeline.
    """
    if journey.is_terminal:
        raise StageNotEditableError("This journey is already completed, closed, or deferred.")
    if not (to_intake or "").strip():
        raise DeferIntakeRequiredError("Deferring requires the intake being deferred to.")

    previous = journey.stage
    journey.stage_before_terminal = previous
    journey.stage = JourneyStage.DEFERRED
    journey.deferred_at = timezone.now()
    journey.deferred_to_intake = to_intake
    journey.deferment_reason = normalize_unicode(reason)
    journey.deferred_by = actor
    journey.save(
        update_fields=[
            "stage",
            "stage_before_terminal",
            "deferred_at",
            "deferred_to_intake",
            "deferment_reason",
            "deferred_by",
            "updated_at",
        ]
    )
    _record(
        action=JourneyAuditAction.JOURNEY_DEFERRED,
        actor=actor,
        journey=journey,
        summary=f"Journey deferred to {to_intake}.",
        changes={"stage": {"from": previous, "to": JourneyStage.DEFERRED}},
        metadata={"deferred_to_intake": to_intake},
        ip_address=ip_address,
    )
    return journey


@transaction.atomic
def close_journey(
    *,
    actor: Any,
    journey: ApplicantJourney,
    outcome: str | None,
    reason: str = "",
    ip_address: str | None = None,
) -> ApplicantJourney:
    """End a journey, recording why.

    Closing with ``successful`` sets the stage to ``completed``; every other
    outcome sets it to ``closed``. This keeps "how did it end" a single recorded
    fact rather than something inferred from where the journey stopped.
    """
    if journey.is_terminal:
        raise StageNotEditableError("This journey is already completed, closed, or deferred.")
    if not outcome:
        raise OutcomeRequiredError("An outcome is required to close a journey.")
    if outcome == JourneyOutcome.OTHER and not reason.strip():
        raise OutcomeDetailRequiredError("The 'other' outcome requires an explanation.")

    previous = journey.stage
    target = JourneyStage.COMPLETED if outcome == JourneyOutcome.SUCCESSFUL else JourneyStage.CLOSED

    journey.stage_before_terminal = previous
    journey.stage = target
    journey.outcome = outcome
    journey.closure_reason = normalize_unicode(reason)
    journey.closed_at = timezone.now()
    journey.closed_by = actor
    journey.save(
        update_fields=[
            "stage",
            "stage_before_terminal",
            "outcome",
            "closure_reason",
            "closed_at",
            "closed_by",
            "updated_at",
        ]
    )
    _record(
        action=JourneyAuditAction.JOURNEY_CLOSED,
        actor=actor,
        journey=journey,
        summary=f"Journey closed as {outcome}.",
        reason=outcome,
        changes={"stage": {"from": previous, "to": target}},
        metadata={"outcome": outcome, "has_reason": bool(reason.strip())},
        ip_address=ip_address,
    )
    return journey


@transaction.atomic
def reopen_journey(
    *,
    actor: Any,
    journey: ApplicantJourney,
    stage: str | None = None,
    ip_address: str | None = None,
) -> ApplicantJourney:
    """Return a completed, closed, or deferred journey to active work.

    Clears the closure and deferment state but preserves the complete history —
    reopening a completed journey does not undo the fact that it was completed,
    which remains in the audit log.
    """
    if not journey.is_terminal:
        raise JourneyNotTerminalError("Only a completed, closed, or deferred journey can be reopened.")

    target = stage or DEFAULT_REOPEN_STAGE
    _assert_selectable_stage(target)

    previous = journey.stage
    journey.stage = target
    journey.outcome = ""
    journey.closure_reason = ""
    journey.closed_at = None
    journey.closed_by = None
    journey.deferred_at = None
    journey.deferred_to_intake = ""
    journey.deferment_reason = ""
    journey.deferred_by = None
    journey.stage_before_terminal = ""
    journey.save(
        update_fields=[
            "stage",
            "outcome",
            "closure_reason",
            "closed_at",
            "closed_by",
            "deferred_at",
            "deferred_to_intake",
            "deferment_reason",
            "deferred_by",
            "stage_before_terminal",
            "updated_at",
        ]
    )
    _record(
        action=JourneyAuditAction.JOURNEY_REOPENED,
        actor=actor,
        journey=journey,
        summary=f"Journey reopened from {previous} to {target}.",
        changes={"stage": {"from": previous, "to": target}},
        ip_address=ip_address,
    )
    return journey
