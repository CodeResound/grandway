"""Business logic for the offers app.

Services receive already-validated data, own every rule that spans more than one
field, and return model instances — never HTTP responses.

Every mutation appends one event to the central audit log; that log *is* an
offer's history. Condition events are recorded against the parent offer so the
offer's history reads as one continuous trail.

**This app never writes to another app.** It reads a journey to attach an offer
to it and reads the catalogue to build a snapshot, but recording an offer does
not move the journey's stage and satisfying a condition does not touch the
applicant. Journey stage, offer status, and applicant status are separate
lifecycles by project rule (``concepts/project_overview.txt`` — "Explicit
lifecycle states").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone

from offers.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_OFFER,
    CONDITION_NOTE_REQUIRED_STATUSES,
    DECIDABLE_STATUSES,
    REASON_REQUIRED_OUTCOMES,
    RESOLVED_CONDITION_STATUSES,
    DecisionOutcome,
    OfferAuditAction,
    OfferSource,
    OfferStatus,
)
from offers.exceptions import (
    AcceptedOfferExistsError,
    AmountIncompleteError,
    CatalogueReferenceInvalidError,
    ConditionNoteRequiredError,
    DecisionReasonRequiredError,
    DeferIntakeRequiredError,
    OfferNotDecidableError,
    OfferNotIssuableError,
    ProgramReferenceRequiredError,
)
from offers.models import Offer, OfferCondition
from offers.selectors import get_accepted_offer_for_journey

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}

#: The copied text that outlives the catalogue record it came from. Writable
#: at creation (a manual offer has nothing else), fixed forever after.
SNAPSHOT_FIELDS: frozenset[str] = frozenset(
    {
        "institution_name_en",
        "institution_name_np",
        "campus_name",
        "program_title",
        "country_name",
        "qualification_level",
        "intake_label",
    }
)

#: Fields fixed at creation. The concept's central rule is that an offer
#: preserves what was true when the decision was made; letting an edit reach
#: these would rewrite history rather than correct a record.
IMMUTABLE_FIELDS: frozenset[str] = SNAPSHOT_FIELDS | {
    "journey",
    "institution",
    "campus",
    "program",
    "reference_source",
}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    offer: Offer,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one offer audit event. Never pass secrets or full record dumps."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=AUDIT_ENTITY_OFFER,
        entity_id=str(offer.id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
        source="api",
    )


def _diff(instance: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply ``fields`` to ``instance`` and return only what actually changed.

    Returning the empty dict when nothing moved is what keeps a no-op PATCH
    from writing a misleading "record updated" event into the history.
    """
    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(instance, name)
        if previous != value:
            changes[name] = {"from": str(previous), "to": str(value)}
            setattr(instance, name, value)
    return changes


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


def assert_amount_complete(amount: Decimal | None, currency: str, label: str) -> None:
    """An amount is not money until its currency is known.

    Applied to tuition, scholarship, and deposit alike — "5000" on an offer
    letter is meaningless when the institution is in Australia and the
    applicant budgets in rupees.
    """
    if amount is not None and not currency:
        raise AmountIncompleteError(f"Recording a {label} amount requires its currency.")


def assert_catalogue_references_agree(institution: Any, campus: Any, program: Any) -> None:
    """A campus and program must belong to the institution they are recorded under.

    A mismatch means the client's pickers were not filtered to the chosen
    institution — a UI bug rather than user error.
    """
    if institution is None:
        return
    if campus is not None and campus.institution_id != institution.id:
        raise CatalogueReferenceInvalidError("The selected campus does not belong to the selected institution.")
    if program is not None and program.institution_id != institution.id:
        raise CatalogueReferenceInvalidError("The selected program does not belong to the selected institution.")


def build_reference_block(
    *,
    institution: Any = None,
    campus: Any = None,
    program: Any = None,
    manual: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the catalogue links and the snapshot that will outlive them.

    Copying the catalogue's names into the offer is the whole mechanism behind
    "later catalogue edits must not rewrite the historical offer record". The
    foreign keys stay as the original reference point; the copied text is what
    the offer actually means once the catalogue moves on.

    Caller-supplied snapshot values win over the catalogue's, so a manually
    corrected program title on a catalogue-sourced offer is preserved rather
    than silently overwritten at creation.
    """
    manual = dict(manual or {})
    assert_catalogue_references_agree(institution, campus, program)

    # A program implies its institution and campus; accepting the program alone
    # is what makes the Program Search → "record an offer" path a single click.
    if program is not None:
        institution = institution or program.institution
        campus = campus or program.campus

    if campus is not None:
        institution = institution or campus.institution

    snapshot: dict[str, Any] = {
        "institution_name_en": "",
        "institution_name_np": "",
        "campus_name": "",
        "program_title": "",
        "country_name": "",
        "qualification_level": "",
        "intake_label": "",
    }

    if institution is not None:
        snapshot["institution_name_en"] = institution.name_en
        snapshot["institution_name_np"] = institution.name_np
        snapshot["country_name"] = institution.country.name_en
    if campus is not None:
        snapshot["campus_name"] = campus.name_en
    if program is not None:
        snapshot["program_title"] = program.title
        snapshot["qualification_level"] = program.qualification_level
        snapshot["intake_label"] = program.intake_pattern

    for key in SNAPSHOT_FIELDS:
        if manual.get(key):
            snapshot[key] = manual[key]

    if not snapshot["program_title"] or not snapshot["institution_name_en"]:
        raise ProgramReferenceRequiredError(
            "An offer must name both the institution and the program, "
            "either by catalogue reference or as manual entry.",
        )

    source = OfferSource.CATALOGUE if program is not None or institution is not None else OfferSource.MANUAL
    return {
        "institution": institution,
        "campus": campus,
        "program": program,
        "reference_source": source,
        **snapshot,
    }


def _assert_amounts_complete(data: dict[str, Any]) -> None:
    """Check all three money pairs at once, in the order the form shows them."""
    assert_amount_complete(data.get("tuition_amount"), data.get("tuition_currency", ""), "tuition")
    assert_amount_complete(data.get("scholarship_amount"), data.get("scholarship_currency", ""), "scholarship")
    assert_amount_complete(data.get("deposit_amount"), data.get("deposit_currency", ""), "deposit")


# ---------------------------------------------------------------------------
# Creation and editing
# ---------------------------------------------------------------------------


@transaction.atomic
def create_offer(
    *,
    actor: Any,
    journey: Any,
    data: dict[str, Any],
    institution: Any = None,
    campus: Any = None,
    program: Any = None,
    conditions: list[dict[str, Any]] | None = None,
    ip_address: str | None = None,
) -> Offer:
    """Record an institution's decision against a journey.

    The offer and its conditions are created together so that a conditional
    offer never exists for even a moment without the conditions that make it
    conditional.
    """
    manual = {field: data.pop(field) for field in list(data) if field in SNAPSHOT_FIELDS}
    reference = build_reference_block(institution=institution, campus=campus, program=program, manual=manual)
    _assert_amounts_complete(data)

    offer = Offer.objects.create(journey=journey, created_by=actor, **reference, **data)

    for order, condition in enumerate(conditions or []):
        OfferCondition.objects.create(offer=offer, display_order=condition.pop("display_order", order), **condition)

    _record(
        action=OfferAuditAction.OFFER_CREATED,
        actor=actor,
        offer=offer,
        summary=f"Offer recorded from {offer.institution_name_en} for {offer.program_title}.",
        metadata={
            "journey_id": str(journey.id),
            "reference_source": offer.reference_source,
            "offer_type": offer.offer_type,
            "condition_count": len(conditions or []),
        },
        ip_address=ip_address,
    )
    return offer


@transaction.atomic
def update_offer(
    *,
    actor: Any,
    offer: Offer,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Offer:
    """Correct an offer's decision details.

    The reference block and the status are both out of reach here: the first is
    historical fact, the second moves only through ``issue_offer`` and
    ``record_decision``. Everything else — dates, money, notes — is ordinary
    correctable data.
    """
    merged = {
        "tuition_amount": offer.tuition_amount,
        "tuition_currency": offer.tuition_currency,
        "scholarship_amount": offer.scholarship_amount,
        "scholarship_currency": offer.scholarship_currency,
        "deposit_amount": offer.deposit_amount,
        "deposit_currency": offer.deposit_currency,
        **fields,
    }
    _assert_amounts_complete(merged)

    changes = _diff(offer, fields)
    if changes:
        offer.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=OfferAuditAction.OFFER_UPDATED,
            actor=actor,
            offer=offer,
            summary="Offer details updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return offer


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@transaction.atomic
def issue_offer(*, actor: Any, offer: Offer, ip_address: str | None = None) -> Offer:
    """Mark a drafted offer as issued and awaiting the applicant's response."""
    if offer.status != OfferStatus.DRAFT:
        raise OfferNotIssuableError("Only a draft offer can be issued.")

    offer.status = OfferStatus.ISSUED
    offer.save(update_fields=["status", "updated_at"])
    _record(
        action=OfferAuditAction.OFFER_ISSUED,
        actor=actor,
        offer=offer,
        summary="Offer issued; awaiting the applicant's response.",
        changes={"status": {"from": OfferStatus.DRAFT, "to": OfferStatus.ISSUED}},
        ip_address=ip_address,
    )
    return offer


@transaction.atomic
def record_decision(
    *,
    actor: Any,
    offer: Offer,
    outcome: str,
    reason: str = "",
    to_intake: str = "",
    ip_address: str | None = None,
) -> Offer:
    """Record how the offer ended — the concept's Decision Dialog.

    A decision is final. There is no reopen action: an institution that changes
    its position has issued a *new* offer, and recording it as one is what keeps
    the journey's decision trail readable rather than a single mutable row.
    """
    if offer.status not in DECIDABLE_STATUSES:
        raise OfferNotDecidableError("This offer has already been decided.")
    if outcome in REASON_REQUIRED_OUTCOMES and not reason.strip():
        raise DecisionReasonRequiredError("This outcome requires a reason.")
    if outcome == DecisionOutcome.DEFERRED and not to_intake.strip():
        raise DeferIntakeRequiredError("Deferring an offer requires the intake it is deferred to.")
    if outcome == DecisionOutcome.ACCEPTED:
        existing = get_accepted_offer_for_journey(str(offer.journey_id), exclude_offer_id=str(offer.id))
        if existing is not None:
            raise AcceptedOfferExistsError("This journey already has an accepted offer.")

    previous = offer.status
    offer.status = outcome
    offer.decided_at = timezone.now()
    offer.decision_reason = normalize_unicode(reason)
    offer.decided_by = actor
    offer.deferred_to_intake = to_intake if outcome == DecisionOutcome.DEFERRED else ""
    offer.save(
        update_fields=[
            "status",
            "decided_at",
            "decision_reason",
            "decided_by",
            "deferred_to_intake",
            "updated_at",
        ]
    )
    _record(
        action=OfferAuditAction.OFFER_DECISION_RECORDED,
        actor=actor,
        offer=offer,
        summary=f"Offer {outcome}.",
        reason=outcome,
        changes={"status": {"from": previous, "to": outcome}},
        metadata={
            "outcome": outcome,
            "has_reason": bool(reason.strip()),
            "deferred_to_intake": offer.deferred_to_intake,
        },
        ip_address=ip_address,
    )
    return offer


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


@transaction.atomic
def create_condition(
    *,
    actor: Any,
    offer: Offer,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> OfferCondition:
    """Attach a requirement to an offer.

    Permitted on a decided offer: institutions routinely add a condition after
    an applicant has already accepted, and refusing it would push the record
    back into the spreadsheet this app exists to replace.
    """
    condition = OfferCondition.objects.create(offer=offer, **data)
    _record(
        action=OfferAuditAction.CONDITION_CREATED,
        actor=actor,
        offer=offer,
        summary=f"Condition added: {condition.get_condition_type_display()}.",
        metadata={"condition_id": str(condition.id), "condition_type": condition.condition_type},
        ip_address=ip_address,
    )
    return condition


@transaction.atomic
def update_condition(
    *,
    actor: Any,
    condition: OfferCondition,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> OfferCondition:
    """Correct a condition's wording, type, due date, or ordering.

    Status is not editable here — it moves only through
    ``change_condition_status``, which stamps who resolved it and when.
    """
    changes = _diff(condition, fields)
    if changes:
        condition.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=OfferAuditAction.CONDITION_UPDATED,
            actor=actor,
            offer=condition.offer,
            summary=f"Condition updated: {condition.get_condition_type_display()}.",
            changes=changes,
            metadata={"condition_id": str(condition.id)},
            ip_address=ip_address,
        )
    return condition


@transaction.atomic
def change_condition_status(
    *,
    actor: Any,
    condition: OfferCondition,
    status: str,
    note: str = "",
    ip_address: str | None = None,
) -> OfferCondition:
    """Mark a condition satisfied, waived, not applicable, or pending again.

    Waiving an institution's requirement and declaring one inapplicable are both
    judgement calls someone will have to defend later, so both demand a note.
    Satisfying one is a fact and needs none.

    Moving back to ``pending`` is allowed — a document rejected on review is a
    real event — and clears the resolution stamp while leaving the audit trail
    of both transitions intact.
    """
    if status in CONDITION_NOTE_REQUIRED_STATUSES and not note.strip():
        raise ConditionNoteRequiredError("Waiving a condition, or marking it not applicable, requires a note.")

    previous = condition.status
    if previous == status and not note.strip():
        return condition

    condition.status = status
    condition.resolution_note = normalize_unicode(note)
    if status in RESOLVED_CONDITION_STATUSES:
        condition.resolved_at = timezone.now()
        condition.resolved_by = actor
    else:
        condition.resolved_at = None
        condition.resolved_by = None
    condition.save(update_fields=["status", "resolution_note", "resolved_at", "resolved_by", "updated_at"])

    _record(
        action=OfferAuditAction.CONDITION_STATUS_CHANGED,
        actor=actor,
        offer=condition.offer,
        summary=f"Condition {status}: {condition.get_condition_type_display()}.",
        changes={"status": {"from": previous, "to": status}},
        metadata={
            "condition_id": str(condition.id),
            "condition_type": condition.condition_type,
            "has_note": bool(note.strip()),
        },
        ip_address=ip_address,
    )
    return condition
