"""Business logic for the leads app.

Services receive already-validated data, own every state transition, and return
model instances — never HTTP responses. Multi-table writes run inside
``atomic()``.

Every mutation appends one event to the central audit log through
``audit.services.record_event``. That log *is* the lead's chronological history
(``concepts/leads.txt`` — "Notes and history"); this app owns no history table.
"""

from __future__ import annotations

from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.constants import ContactNumberLabel
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone

from leads.constants import (
    ACTIVE_STAGES,
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_LEAD,
    AUDIT_ENTITY_LOSS_REASON,
    AUDIT_ENTITY_SOURCE,
    DEFAULT_REOPEN_STAGE,
    LeadAuditAction,
    LeadStage,
)
from leads.exceptions import (
    ContactNumberRequiredError,
    ConversionNotReadyError,
    InvalidStageTransitionError,
    LeadAlreadyConvertedError,
    LeadNotLostError,
    LossDetailRequiredError,
    LossReasonRequiredError,
    ReferenceCodeTakenError,
    ReferenceInactiveError,
    SourceDetailRequiredError,
    StageNotEditableError,
)
from leads.models import (
    Lead,
    LeadContactNumber,
    LeadNote,
    LeadSource,
    LeadStudyInterest,
    LossReason,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: Authority types map 1:1 onto audit actor types; anything unexpected is
#: recorded as ``system`` rather than guessed.
_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    entity_type: str,
    entity_id: str,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one leads audit event. Never pass secrets or full record dumps."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", ""),
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
    )


def _apply_name_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the lead's name (§39.2).

    Applied in the service layer as well as the serializer so a direct service
    caller — a management command, a test, a future import — cannot bypass it.
    """
    if data.get("full_name"):
        data["full_name"] = normalize_unicode(data["full_name"])
    return data


def _apply_reference_name_fields(data: dict[str, Any]) -> dict[str, Any]:
    """The ``_apply_name_fields`` equivalent for the two reference tables."""
    if data.get("name"):
        data["name"] = normalize_unicode(data["name"])
    return data


def _check_source(source: LeadSource, source_detail: str) -> None:
    """A source must be active, and a catch-all source must carry an explanation."""
    if not source.is_active:
        raise ReferenceInactiveError("That lead source is no longer available.")
    if source.requires_detail and not (source_detail or "").strip():
        raise SourceDetailRequiredError("This lead source requires a short description.")


def _replace_contact_numbers(lead: Lead, numbers: list[dict[str, Any]]) -> None:
    """Replace a lead's contact numbers wholesale.

    Replacement (rather than per-row patching) keeps the write predictable: the
    payload is the complete set of numbers the lead should have afterwards.
    """
    if not numbers:
        raise ContactNumberRequiredError("A lead needs at least one contact number.")
    lead.contact_numbers.all().delete()
    LeadContactNumber.objects.bulk_create(
        [
            LeadContactNumber(
                lead=lead,
                number=entry["number"],
                label=entry.get("label") or ContactNumberLabel.MOBILE,
                is_primary=entry.get("is_primary", False),
            )
            for entry in numbers
        ]
    )


def _upsert_study_interest(lead: Lead, interest: dict[str, Any]) -> None:
    """Create or update the lead's optional preliminary study interest."""
    LeadStudyInterest.objects.update_or_create(lead=lead, defaults=interest)


# ---------------------------------------------------------------------------
# Reference configuration (Admin)
# ---------------------------------------------------------------------------


def create_lead_source(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> LeadSource:
    """Add a configurable lead source."""
    data = _apply_reference_name_fields(dict(data))
    if LeadSource.objects.filter(code=data["code"]).exists():
        raise ReferenceCodeTakenError("A lead source with that code already exists.")
    source = LeadSource.objects.create(**data)
    _record(
        action=LeadAuditAction.SOURCE_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_SOURCE,
        entity_id=str(source.id),
        summary=f"Lead source '{source.code}' created.",
        ip_address=ip_address,
    )
    return source


def update_lead_source(
    *,
    actor: Any,
    source: LeadSource,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> LeadSource:
    """Edit a lead source. Deactivate via ``is_active`` — entries are never deleted."""
    fields = _apply_reference_name_fields(dict(fields))
    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(source, field)
        if previous != value:
            changes[field] = {"from": previous, "to": value}
            setattr(source, field, value)
    if changes:
        source.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=LeadAuditAction.SOURCE_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_SOURCE,
            entity_id=str(source.id),
            summary=f"Lead source '{source.code}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return source


def create_loss_reason(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> LossReason:
    """Add a configurable loss reason."""
    data = _apply_reference_name_fields(dict(data))
    if LossReason.objects.filter(code=data["code"]).exists():
        raise ReferenceCodeTakenError("A loss reason with that code already exists.")
    reason = LossReason.objects.create(**data)
    _record(
        action=LeadAuditAction.LOSS_REASON_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LOSS_REASON,
        entity_id=str(reason.id),
        summary=f"Loss reason '{reason.code}' created.",
        ip_address=ip_address,
    )
    return reason


def update_loss_reason(
    *,
    actor: Any,
    reason: LossReason,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> LossReason:
    """Edit a loss reason. Deactivate via ``is_active`` — entries are never deleted."""
    fields = _apply_reference_name_fields(dict(fields))
    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(reason, field)
        if previous != value:
            changes[field] = {"from": previous, "to": value}
            setattr(reason, field, value)
    if changes:
        reason.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=LeadAuditAction.LOSS_REASON_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_LOSS_REASON,
            entity_id=str(reason.id),
            summary=f"Loss reason '{reason.code}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return reason


# ---------------------------------------------------------------------------
# Lead creation and editing
# ---------------------------------------------------------------------------


@transaction.atomic
def create_lead(
    *,
    actor: Any,
    data: dict[str, Any],
    contact_numbers: list[dict[str, Any]],
    study_interest: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> Lead:
    """Record a new enquiry, owned by its creator from this moment on."""
    data = _apply_name_fields(dict(data))
    _check_source(data["source"], data.get("source_detail", ""))

    lead = Lead.objects.create(**data, created_by=actor, stage=LeadStage.NEW)
    _replace_contact_numbers(lead, contact_numbers)
    if study_interest:
        _upsert_study_interest(lead, study_interest)

    _record(
        action=LeadAuditAction.LEAD_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary=f"Lead '{lead.full_name}' created.",
        metadata={"source": lead.source.code, "stage": lead.stage},
        ip_address=ip_address,
    )
    return lead


@transaction.atomic
def update_lead(
    *,
    actor: Any,
    lead: Lead,
    fields: dict[str, Any],
    contact_numbers: list[dict[str, Any]] | None = None,
    study_interest: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> Lead:
    """Correct a lead's identity, contact, source, or study-interest information.

    Stage is deliberately not editable here — it moves only through
    ``change_stage``, ``mark_lost``, ``reopen_lead``, or conversion.
    """
    fields = _apply_name_fields(dict(fields))

    source_changed = "source" in fields and fields["source"] != lead.source
    if "source" in fields:
        _check_source(fields["source"], fields.get("source_detail", lead.source_detail))

    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(lead, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(lead, field, value)

    if changes:
        lead.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=LeadAuditAction.LEAD_SOURCE_CHANGED if source_changed else LeadAuditAction.LEAD_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_LEAD,
            entity_id=str(lead.id),
            summary=f"Lead '{lead.full_name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )

    if contact_numbers is not None:
        _replace_contact_numbers(lead, contact_numbers)
        _record(
            action=LeadAuditAction.LEAD_CONTACT_CHANGED,
            actor=actor,
            entity_type=AUDIT_ENTITY_LEAD,
            entity_id=str(lead.id),
            summary="Contact numbers updated.",
            metadata={"count": len(contact_numbers)},
            ip_address=ip_address,
        )

    if study_interest is not None:
        _upsert_study_interest(lead, study_interest)
        _record(
            action=LeadAuditAction.LEAD_INTEREST_CHANGED,
            actor=actor,
            entity_type=AUDIT_ENTITY_LEAD,
            entity_id=str(lead.id),
            summary="Preliminary study interest updated.",
            ip_address=ip_address,
        )

    return lead


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


def _assert_stage_movable(lead: Lead) -> None:
    """A lost or converted lead must be reopened before its stage can move."""
    if lead.is_terminal:
        raise StageNotEditableError("This lead is lost or converted; reopen it before changing its stage.")


def _assert_selectable_stage(stage: str) -> None:
    """The dropdown may only set active stages.

    ``lost`` needs a mandatory reason and ``converted`` is a deliberate Admin
    action — neither is reachable by picking it from a list.
    """
    if stage not in ACTIVE_STAGES:
        raise InvalidStageTransitionError(
            "This stage cannot be selected directly; use the mark-lost or convert action."
        )


def change_stage(*, actor: Any, lead: Lead, stage: str, ip_address: str | None = None) -> Lead:
    """Move a lead between active stages."""
    _assert_stage_movable(lead)
    _assert_selectable_stage(stage)

    previous = lead.stage
    if previous == stage:
        return lead

    lead.stage = stage
    lead.save(update_fields=["stage", "updated_at"])
    _record(
        action=LeadAuditAction.LEAD_STAGE_CHANGED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary=f"Stage changed from {previous} to {stage}.",
        changes={"stage": {"from": previous, "to": stage}},
        ip_address=ip_address,
    )
    return lead


@transaction.atomic
def record_followup(
    *,
    actor: Any,
    lead: Lead,
    note: str = "",
    stage: str | None = None,
    followed_up_at: Any = None,
    ip_address: str | None = None,
) -> Lead:
    """Record that a manual follow-up happened outside Grandway.

    Grandway does not schedule, remind, or integrate with any communication
    channel — it only records that contact occurred, by whom, and optionally
    what came of it (``concepts/leads.txt`` — "Manual follow-up tracking").
    """
    _assert_stage_movable(lead)

    lead.last_followed_up_at = followed_up_at or timezone.now()
    lead.last_followed_up_by = actor
    lead.save(update_fields=["last_followed_up_at", "last_followed_up_by", "updated_at"])

    _record(
        action=LeadAuditAction.LEAD_FOLLOWUP_RECORDED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary="Follow-up recorded.",
        metadata={"followed_up_at": lead.last_followed_up_at.isoformat()},
        ip_address=ip_address,
    )

    if note.strip():
        add_note(actor=actor, lead=lead, body=note, ip_address=ip_address)
    if stage is not None:
        change_stage(actor=actor, lead=lead, stage=stage, ip_address=ip_address)

    return lead


@transaction.atomic
def mark_lost(
    *,
    actor: Any,
    lead: Lead,
    loss_reason: LossReason | None,
    detail: str = "",
    ip_address: str | None = None,
) -> Lead:
    """Close a lead as ``lost``. A reason is always mandatory.

    Nothing is deleted — the record and its history stay intact, and the lead
    can be reopened later.
    """
    if lead.is_terminal:
        raise StageNotEditableError("This lead is already lost or converted.")
    if loss_reason is None:
        raise LossReasonRequiredError("A loss reason is required to close a lead.")
    if not loss_reason.is_active:
        raise ReferenceInactiveError("That loss reason is no longer available.")
    if loss_reason.requires_detail and not detail.strip():
        raise LossDetailRequiredError("This loss reason requires an explanation.")

    previous = lead.stage
    lead.stage_before_loss = previous
    lead.stage = LeadStage.LOST
    lead.lost_reason = loss_reason
    lead.lost_detail = detail
    lead.lost_at = timezone.now()
    lead.lost_by = actor
    lead.save(
        update_fields=[
            "stage",
            "stage_before_loss",
            "lost_reason",
            "lost_detail",
            "lost_at",
            "lost_by",
            "updated_at",
        ]
    )

    _record(
        action=LeadAuditAction.LEAD_MARKED_LOST,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary=f"Lead marked lost ({loss_reason.code}).",
        reason=loss_reason.code,
        changes={"stage": {"from": previous, "to": LeadStage.LOST}},
        metadata={"loss_reason": loss_reason.code, "has_detail": bool(detail.strip())},
        ip_address=ip_address,
    )
    return lead


@transaction.atomic
def reopen_lead(*, actor: Any, lead: Lead, stage: str | None = None, ip_address: str | None = None) -> Lead:
    """Return a lost or converted lead to an active stage.

    Reopening never undoes a conversion: the ``converted_*`` fields are left
    untouched so the lead stays linked to its applicant and no second applicant
    can be created from it (``concepts/leads.txt`` — "Reopening a lead").
    """
    if not lead.is_terminal:
        raise LeadNotLostError("Only a lost or converted lead can be reopened.")

    target = stage or DEFAULT_REOPEN_STAGE
    _assert_selectable_stage(target)

    previous = lead.stage
    was_converted = lead.is_converted

    lead.stage = target
    lead.lost_reason = None
    lead.lost_detail = ""
    lead.lost_at = None
    lead.lost_by = None
    lead.stage_before_loss = ""
    lead.save(
        update_fields=[
            "stage",
            "lost_reason",
            "lost_detail",
            "lost_at",
            "lost_by",
            "stage_before_loss",
            "updated_at",
        ]
    )

    _record(
        action=LeadAuditAction.LEAD_REOPENED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary=f"Lead reopened from {previous} to {target}.",
        changes={"stage": {"from": previous, "to": target}},
        metadata={"reopened_from_converted": was_converted},
        ip_address=ip_address,
    )
    return lead


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def add_note(*, actor: Any, lead: Lead, body: str, ip_address: str | None = None) -> LeadNote:
    """Append a note. Notes are never edited or deleted once written."""
    note = LeadNote.objects.create(lead=lead, body=normalize_unicode(body), author=actor)
    _record(
        action=LeadAuditAction.LEAD_NOTE_ADDED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary="Note added.",
        metadata={"note_id": str(note.id)},
        ip_address=ip_address,
    )
    return note


# ---------------------------------------------------------------------------
# Conversion — the one point where the lead cycle meets the applicant cycle
# ---------------------------------------------------------------------------

#: Study-interest fields copied straight into the initial journey.
#: ``concepts/leads.txt`` names six; the rest are handled below.
_INTEREST_TO_JOURNEY = (
    "study_level",
    "field_of_study",
    "preferred_intake",
    "budget_amount",
    "budget_currency",
    "scholarship_interest",
)


def _build_journey_data(lead: Lead) -> dict[str, Any]:
    """Map a lead's preliminary study interest onto an initial journey.

    ``LeadStudyInterest`` carries ten fields but only six map directly. The
    other four have no column on the journey and would otherwise be silently
    dropped at the one moment the information stops being visible to staff, so
    each is preserved in the journey's notes:

    * ``interested_countries`` is a list while a journey targets **one**
      country. Exactly one entry is copied to ``target_country``; two or more
      is a real ambiguity that only a human can resolve, so the field is left
      blank and the full list is recorded for them.
    * ``highest_qualification`` belongs to the ``education`` module and
      ``language_test_status`` to ``test_scores`` — neither exists yet.
    """
    interest = getattr(lead, "study_interest", None)
    if interest is None:
        return {"notes": ""}

    data: dict[str, Any] = {field: getattr(interest, field) for field in _INTEREST_TO_JOURNEY}

    countries = interest.interested_countries or []
    if len(countries) == 1:
        data["target_country"] = countries[0]

    carried: list[str] = []
    if len(countries) > 1:
        carried.append(f"Interested countries: {', '.join(countries)}.")
    if interest.highest_qualification:
        carried.append(f"Highest qualification: {interest.highest_qualification}.")
    if interest.language_test_status:
        carried.append(f"Language test status: {interest.language_test_status}.")
    if interest.interest_notes:
        carried.append(interest.interest_notes)

    data["notes"] = "\n".join(carried)
    return data


@transaction.atomic
def convert_lead(*, actor: Any, lead: Lead, ip_address: str | None = None) -> Lead:
    """Turn a lead into an applicant plus an initial journey. Admin-only.

    Conversion is a deliberate action, not a dropdown stage change
    (``concepts/leads.txt`` — "Lead conversion"). It creates the two records by
    calling the owning apps' services — never their models (§4) — links them to
    the lead permanently, and moves the lead to its terminal ``converted`` stage.

    Idempotency (§15) is enforced twice over: this guard, and the OneToOne on
    ``converted_applicant`` which makes a second applicant per lead impossible
    at the database level even if this check were bypassed.
    """
    # Imported here rather than at module scope: leads is usable without either
    # app loaded, and a top-level import would make that untrue.
    from applicant_journeys import services as journey_services
    from applicant_journeys.constants import CreationSource as JourneyCreationSource
    from applicants import services as applicant_services
    from applicants.constants import CreationSource as ApplicantCreationSource

    if lead.converted_applicant_id is not None:
        raise LeadAlreadyConvertedError("This lead has already been converted into an applicant.")
    if lead.is_terminal:
        raise ConversionNotReadyError("A lost or converted lead must be reopened before it can be converted.")

    applicant = applicant_services.create_applicant(
        actor=actor,
        data={
            "full_name": lead.full_name,
            "email": lead.email,
        },
        contact_numbers=[
            {"number": entry.number, "label": entry.label, "is_primary": entry.is_primary}
            for entry in lead.contact_numbers.all()
        ],
        addresses=([{"address_type": "permanent", "street_address": lead.address}] if lead.address else None),
        creation_source=ApplicantCreationSource.LEAD_CONVERSION,
        ip_address=ip_address,
    )

    journey = journey_services.create_journey(
        actor=actor,
        applicant=applicant,
        data=_build_journey_data(lead),
        creation_source=JourneyCreationSource.LEAD_CONVERSION,
        ip_address=ip_address,
    )

    previous = lead.stage
    lead.converted_applicant = applicant
    lead.converted_journey = journey
    lead.converted_at = timezone.now()
    lead.converted_by = actor
    lead.stage = LeadStage.CONVERTED
    lead.save(
        update_fields=[
            "converted_applicant",
            "converted_journey",
            "converted_at",
            "converted_by",
            "stage",
            "updated_at",
        ]
    )

    _record(
        action=LeadAuditAction.LEAD_CONVERTED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary=f"Lead converted to applicant '{applicant.full_name}'.",
        changes={"stage": {"from": previous, "to": LeadStage.CONVERTED}},
        metadata={"applicant_id": str(applicant.id), "journey_id": str(journey.id)},
        ip_address=ip_address,
    )
    _record(
        action=LeadAuditAction.LEAD_APPLICANT_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        summary="Applicant and initial journey created from this lead.",
        metadata={"applicant_id": str(applicant.id), "journey_id": str(journey.id)},
        ip_address=ip_address,
    )
    return lead
