"""Business logic for the checklists app.

Services receive already-validated data, own every state transition, and return
model instances — never HTTP responses.

``instantiate_checklist`` is the module's centre of gravity. It is called from
exactly two places — the inheritance receiver in ``signals.py`` and the manual
apply route — and both go through it precisely so that an automatically
inherited checklist and a hand-applied one are the same thing. If the two paths
ever diverged, "why does this applicant's list look different" would become a
question with no answer.

Every mutation appends one event to the central audit log; that log *is* a
checklist's history.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone

from checklists.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_CHECKLIST,
    AUDIT_ENTITY_ITEM,
    AUDIT_ENTITY_TEMPLATE,
    NOTE_REQUIRED_STATUSES,
    ChecklistAuditAction,
    ChecklistOrigin,
    ChecklistStatus,
    ItemStatus,
    TemplateStatus,
)
from checklists.exceptions import (
    ArchiveReasonRequiredError,
    ChecklistArchivedError,
    ChecklistNotArchivedError,
    DefaultRequiresCountryError,
    DefaultTemplateExistsError,
    EvidenceNotAllowedError,
    InvalidTransitionError,
    RequiredItemsPendingError,
    StatusNoteRequiredError,
    TemplateAlreadyAppliedError,
    TemplateHasNoItemsError,
    TemplateNotActiveError,
)
from checklists.models import Checklist, ChecklistItem, ChecklistTemplate, ChecklistTemplateItem
from checklists.selectors import (
    get_active_template_items,
    get_default_template_for_country,
    get_live_checklist_from_template,
    get_unresolved_required_items,
)

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    entity_type: str,
    entity_id: Any,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    success: bool = True,
) -> None:
    """Append one checklist audit event. Never pass secrets or full record dumps.

    ``actor`` is ``None`` for an inherited checklist — nobody decided it, which
    is the point — and ``_actor_type`` renders that as ``system`` rather than
    attributing it to whoever happened to be saving the journey.
    """
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", ""),
        entity_type=entity_type,
        entity_id=str(entity_id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
        success=success,
    )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def _assert_default_is_coherent(*, is_default: bool, country: Any, exclude_pk: Any = None) -> None:
    """Refuse an ambiguous or unusable default before the database has to.

    Two rules, both of which the schema also enforces. They are re-checked here
    so an Admin gets a message naming the template already holding the slot,
    rather than a constraint name.
    """
    if not is_default:
        return
    if country is None:
        raise DefaultRequiresCountryError("A default checklist must name the country it applies to.")

    clash = ChecklistTemplate.objects.filter(
        country=country,
        is_default=True,
        status=TemplateStatus.ACTIVE,
    ).exclude(pk=exclude_pk)
    existing = clash.first()
    if existing is not None:
        raise DefaultTemplateExistsError(
            existing,
            f"'{existing.label}' is already the active default for this country.",
        )


@transaction.atomic
def create_template(
    *,
    actor: Any,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> ChecklistTemplate:
    """Author a new country requirement list.

    Starts as a ``draft`` unless the caller says otherwise: a template with no
    items yet would otherwise be inheritable the moment it was saved, and the
    first applicant to reach that country would receive an empty list.
    """
    data = dict(data)
    _assert_default_is_coherent(
        is_default=bool(data.get("is_default")),
        country=data.get("country"),
    )

    template = ChecklistTemplate.objects.create(created_by=actor, **data)
    _record(
        action=ChecklistAuditAction.TEMPLATE_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_TEMPLATE,
        entity_id=template.id,
        summary=f"Checklist template '{template.label}' created.",
        metadata={
            "key": template.key,
            "country_id": str(template.country_id) if template.country_id else None,
            "is_default": template.is_default,
        },
        ip_address=ip_address,
    )
    return template


@transaction.atomic
def update_template(
    *,
    actor: Any,
    template: ChecklistTemplate,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> ChecklistTemplate:
    """Correct a template. Never touches checklists already inherited from it."""
    merged_default = fields.get("is_default", template.is_default)
    merged_country = fields.get("country", template.country)
    merged_status = fields.get("status", template.status)
    if merged_status == TemplateStatus.ACTIVE:
        _assert_default_is_coherent(
            is_default=bool(merged_default),
            country=merged_country,
            exclude_pk=template.pk,
        )
    elif merged_default and merged_country is None:
        raise DefaultRequiresCountryError("A default checklist must name the country it applies to.")

    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(template, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(template, field, value)

    if changes:
        template.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=ChecklistAuditAction.TEMPLATE_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_TEMPLATE,
            entity_id=template.id,
            summary=f"Checklist template '{template.label}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return template


@transaction.atomic
def add_template_item(
    *,
    actor: Any,
    template: ChecklistTemplate,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> ChecklistTemplateItem:
    """Add one requirement definition to a template.

    Affects who inherits it *next*. Applicants already holding a copy are
    untouched — see the module docstring in ``models.py``.
    """
    item = ChecklistTemplateItem.objects.create(template=template, **data)
    _record(
        action=ChecklistAuditAction.TEMPLATE_ITEM_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_TEMPLATE,
        entity_id=template.id,
        summary=f"Requirement '{item.label}' added to '{template.label}'.",
        metadata={"item_id": str(item.id), "item_type": item.item_type, "is_required": item.is_required},
        ip_address=ip_address,
    )
    return item


@transaction.atomic
def update_template_item(
    *,
    actor: Any,
    item: ChecklistTemplateItem,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> ChecklistTemplateItem:
    """Correct or retire one requirement definition.

    Retirement is ``is_active=False``, never a delete: live checklist items point
    back at the definition they were copied from, and that provenance has to keep
    resolving.
    """
    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(item, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(item, field, value)

    if changes:
        item.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=ChecklistAuditAction.TEMPLATE_ITEM_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_TEMPLATE,
            entity_id=item.template_id,
            summary=f"Requirement '{item.label}' updated.",
            changes=changes,
            metadata={"item_id": str(item.id)},
            ip_address=ip_address,
        )
    return item


# ---------------------------------------------------------------------------
# Instantiation — the applicant's copy
# ---------------------------------------------------------------------------


def _due_from_offset(offset_days: int | None, *, base: Any) -> Any | None:
    """Turn a template's "due N days after start" into a real date on one copy."""
    return base + timedelta(days=offset_days) if offset_days is not None else None


@transaction.atomic
def instantiate_checklist(
    *,
    journey: Any,
    template: ChecklistTemplate,
    origin: str = ChecklistOrigin.MANUAL,
    actor: Any = None,
    ip_address: str | None = None,
) -> Checklist:
    """Give one applicant their own copy of a country's requirement list.

    The single write path for both automatic inheritance and manual application.
    Every field the checklist needs is **copied**, not referenced: the title from
    the template's label, the country from the template's country, and one real
    row per active item. What the applicant is measured against is fixed at this
    moment and does not move afterwards.
    """
    if not template.is_active:
        raise TemplateNotActiveError("Only an active template can be applied to an applicant.")

    definitions = list(get_active_template_items(template))
    if not definitions:
        raise TemplateHasNoItemsError("This template has no active requirements to copy.")

    if get_live_checklist_from_template(journey.pk, template.pk) is not None:
        raise TemplateAlreadyAppliedError("This applicant already holds a checklist from this template.")

    now = timezone.now()
    checklist = Checklist.objects.create(
        journey=journey,
        source_template=template,
        country=template.country,
        title=template.label,
        description=template.description,
        origin=origin,
        status=ChecklistStatus.ACTIVE,
        activated_at=now,
        created_by=actor,
    )

    ChecklistItem.objects.bulk_create(
        [
            ChecklistItem(
                checklist=checklist,
                source_template_item=definition,
                label=definition.label,
                description=definition.description,
                item_type=definition.item_type,
                is_required=definition.is_required,
                display_order=definition.display_order,
                due_at=_due_from_offset(definition.default_due_offset_days, base=now),
            )
            for definition in definitions
        ]
    )

    inherited = origin == ChecklistOrigin.AUTO
    _record(
        action=(ChecklistAuditAction.CHECKLIST_INHERITED if inherited else ChecklistAuditAction.CHECKLIST_CREATED),
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary=(
            f"Checklist '{checklist.title}' inherited for this applicant."
            if inherited
            else f"Checklist '{checklist.title}' applied to this applicant."
        ),
        metadata={
            "journey_id": str(journey.pk),
            "applicant_id": str(journey.applicant_id),
            "template_id": str(template.id),
            "template_key": template.key,
            "country_id": str(template.country_id) if template.country_id else None,
            "item_count": len(definitions),
            "origin": origin,
        },
        ip_address=ip_address,
    )
    return checklist


def inherit_for_journey(journey: Any, *, ip_address: str | None = None) -> Checklist | None:
    """Apply this journey's destination checklist, if there is one to apply.

    The whole promise of the module, in one function: a journey that names a
    country gets that country's list without anyone asking for it.

    Returns ``None`` — quietly and on purpose — in the two cases that are not
    failures: the journey names no country, or the country has no authored
    default. Neither is an error a member of staff can act on at that moment;
    both are visible through ``selectors.get_journeys_missing_checklist``.

    Idempotent. Called on every save of a journey that names a country, and does
    nothing on all but the first.
    """
    template = get_default_template_for_country(journey.target_country_ref_id)
    if template is None:
        return None
    if get_live_checklist_from_template(journey.pk, template.pk) is not None:
        return None
    return instantiate_checklist(
        journey=journey,
        template=template,
        origin=ChecklistOrigin.AUTO,
        actor=None,
        ip_address=ip_address,
    )


@transaction.atomic
def create_blank_checklist(
    *,
    actor: Any,
    journey: Any,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> Checklist:
    """Start an empty checklist staff will fill in themselves.

    Created as a ``draft``, unlike an instantiated one: it has no items yet, and
    an active checklist with nothing on it reads as "nothing is required".
    """
    checklist = Checklist.objects.create(
        journey=journey,
        origin=ChecklistOrigin.MANUAL,
        status=ChecklistStatus.DRAFT,
        created_by=actor,
        **data,
    )
    _record(
        action=ChecklistAuditAction.CHECKLIST_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary=f"Blank checklist '{checklist.title}' created.",
        metadata={"journey_id": str(journey.pk), "applicant_id": str(journey.applicant_id)},
        ip_address=ip_address,
    )
    return checklist


# ---------------------------------------------------------------------------
# Checklist lifecycle
# ---------------------------------------------------------------------------


def _assert_not_archived(checklist: Checklist) -> None:
    if checklist.is_archived:
        raise ChecklistArchivedError("This checklist is archived; restore it before editing.")


def _assert_editable(checklist: Checklist) -> None:
    """Items move only while the checklist is a draft or active."""
    _assert_not_archived(checklist)
    if not checklist.is_editable:
        raise InvalidTransitionError("This checklist is completed; reopen it before changing its items.")


@transaction.atomic
def update_checklist(
    *,
    actor: Any,
    checklist: Checklist,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Checklist:
    """Correct a checklist's title, owner, due date, or notes.

    Status is deliberately not editable here — it moves only through the
    lifecycle actions below.
    """
    _assert_not_archived(checklist)

    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(checklist, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(checklist, field, value)

    if changes:
        checklist.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=ChecklistAuditAction.CHECKLIST_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_CHECKLIST,
            entity_id=checklist.id,
            summary="Checklist updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return checklist


@transaction.atomic
def activate_checklist(
    *,
    actor: Any,
    checklist: Checklist,
    ip_address: str | None = None,
) -> Checklist:
    """Put a draft checklist into active work."""
    _assert_not_archived(checklist)
    if checklist.status != ChecklistStatus.DRAFT:
        raise InvalidTransitionError("Only a draft checklist can be activated.")

    checklist.status = ChecklistStatus.ACTIVE
    checklist.activated_at = timezone.now()
    checklist.save(update_fields=["status", "activated_at", "updated_at"])
    _record(
        action=ChecklistAuditAction.CHECKLIST_ACTIVATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary="Checklist activated.",
        ip_address=ip_address,
    )
    return checklist


@transaction.atomic
def complete_checklist(
    *,
    actor: Any,
    checklist: Checklist,
    ip_address: str | None = None,
) -> Checklist:
    """Declare the work finished — but only if the items agree.

    Completion is **derived, never asserted** (``concepts/checklists.txt`` —
    "Item model"). Every required item must be completed, waived, or marked not
    applicable; a blocked one still counts as outstanding, because "blocked" is
    precisely the state that means the work did not happen.
    """
    _assert_not_archived(checklist)
    if checklist.status != ChecklistStatus.ACTIVE:
        raise InvalidTransitionError("Only an active checklist can be completed.")

    outstanding = list(get_unresolved_required_items(checklist))
    if outstanding:
        raise RequiredItemsPendingError(
            outstanding,
            f"{len(outstanding)} required item(s) are still outstanding.",
        )

    checklist.status = ChecklistStatus.COMPLETED
    checklist.completed_at = timezone.now()
    checklist.completed_by = actor
    checklist.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
    _record(
        action=ChecklistAuditAction.CHECKLIST_COMPLETED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary="Checklist completed.",
        ip_address=ip_address,
    )
    return checklist


@transaction.atomic
def reopen_checklist(
    *,
    actor: Any,
    checklist: Checklist,
    reason: str = "",
    ip_address: str | None = None,
) -> Checklist:
    """Take a completed checklist back into active work.

    The completion stamps are cleared rather than kept: leaving them would make
    a reopened checklist look finished to every query that reads
    ``completed_at``. The act itself survives in the audit log, which is where a
    "this was completed on the 3rd and reopened on the 7th" question is answered.
    """
    _assert_not_archived(checklist)
    if checklist.status != ChecklistStatus.COMPLETED:
        raise InvalidTransitionError("Only a completed checklist can be reopened.")

    checklist.status = ChecklistStatus.ACTIVE
    checklist.completed_at = None
    checklist.completed_by = None
    checklist.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
    _record(
        action=ChecklistAuditAction.CHECKLIST_REOPENED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary="Checklist reopened.",
        reason=reason,
        ip_address=ip_address,
    )
    return checklist


@transaction.atomic
def archive_checklist(
    *,
    actor: Any,
    checklist: Checklist,
    reason: str,
    ip_address: str | None = None,
) -> Checklist:
    """Take a checklist out of active work without erasing it.

    A reason is required. Archiving is also how staff ask for a fresh copy of a
    country's list — an archived checklist no longer blocks re-application — so
    "why is this one gone" needs an answer on the record.
    """
    if not reason.strip():
        raise ArchiveReasonRequiredError("A reason is required to archive a checklist.")
    if checklist.is_archived:
        raise InvalidTransitionError("This checklist is already archived.")

    checklist.status_before_archive = checklist.status
    checklist.status = ChecklistStatus.ARCHIVED
    checklist.archive_reason = normalize_unicode(reason)
    checklist.archived_at = timezone.now()
    checklist.archived_by = actor
    checklist.save(
        update_fields=[
            "status",
            "status_before_archive",
            "archive_reason",
            "archived_at",
            "archived_by",
            "updated_at",
        ]
    )
    _record(
        action=ChecklistAuditAction.CHECKLIST_ARCHIVED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary="Checklist archived.",
        reason=checklist.archive_reason,
        ip_address=ip_address,
    )
    return checklist


@transaction.atomic
def restore_checklist(
    *,
    actor: Any,
    checklist: Checklist,
    ip_address: str | None = None,
) -> Checklist:
    """Bring an archived checklist back to exactly the state it was archived in.

    Restores ``status_before_archive`` rather than inferring a state. Inferring
    was the first implementation and it was wrong: a *completed* checklist that
    was archived came back ``active`` while still carrying ``completed_at`` and
    ``completed_by``, so a screen showed "completed on the 3rd" above unfinished
    work. The archive is a pause, not a reset, and it is not a reopen either.

    Falls back to ``draft`` only for a row archived before this field existed.
    """
    if not checklist.is_archived:
        raise ChecklistNotArchivedError("This checklist is not archived.")

    checklist.status = checklist.status_before_archive or (
        ChecklistStatus.ACTIVE if checklist.activated_at else ChecklistStatus.DRAFT
    )
    checklist.status_before_archive = ""
    checklist.archive_reason = ""
    checklist.archived_at = None
    checklist.archived_by = None
    checklist.save(
        update_fields=[
            "status",
            "status_before_archive",
            "archive_reason",
            "archived_at",
            "archived_by",
            "updated_at",
        ]
    )
    _record(
        action=ChecklistAuditAction.CHECKLIST_RESTORED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CHECKLIST,
        entity_id=checklist.id,
        summary="Checklist restored.",
        ip_address=ip_address,
    )
    return checklist


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def _resolve_evidence(checklist: Checklist, file_id: Any) -> Any | None:
    """Resolve an evidence file id and refuse anything that is not this applicant's.

    The check that keeps this module from becoming a way to cite somebody else's
    passport as proof. A file qualifies only when it belongs to this checklist's
    journey or to the applicant that journey is for.

    It carries a second consequence that is worth stating plainly: files owned by
    a ``document`` or a print snapshot are never owned by a journey or an
    applicant, so they can never be cited here — which is what keeps a Lead
    Manager from reaching, through this module, material that ``documents`` holds
    Admin-only.

    Returns ``None`` when the caller is clearing the reference.
    """
    if file_id is None:
        return None

    from uploaded_files.selectors import get_file_by_id

    evidence = get_file_by_id(str(file_id))
    if evidence is None:
        raise EvidenceNotAllowedError("No such file.")

    belongs_to_journey = evidence.journey_id == checklist.journey_id
    belongs_to_applicant = evidence.applicant_id == checklist.journey.applicant_id
    if not (belongs_to_journey or belongs_to_applicant):
        raise EvidenceNotAllowedError("That file does not belong to this applicant.")
    return evidence


@transaction.atomic
def add_checklist_item(
    *,
    actor: Any,
    checklist: Checklist,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> ChecklistItem:
    """Add a requirement to one applicant's checklist only.

    For the case the template did not anticipate — an institution asking this
    applicant for one extra thing. It never travels back to the template, so the
    next applicant bound for the same country is unaffected.
    """
    _assert_editable(checklist)

    item = ChecklistItem.objects.create(checklist=checklist, **data)
    _record(
        action=ChecklistAuditAction.ITEM_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_ITEM,
        entity_id=item.id,
        summary=f"Item '{item.label}' added.",
        metadata={"checklist_id": str(checklist.id), "item_type": item.item_type},
        ip_address=ip_address,
    )
    return item


@transaction.atomic
def update_checklist_item(
    *,
    actor: Any,
    item: ChecklistItem,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> ChecklistItem:
    """Correct an item's label, owner, due date, or description.

    Status is deliberately not editable here — it moves only through
    ``set_item_status``, which is where the note and evidence rules live.
    """
    _assert_editable(item.checklist)

    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(item, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(item, field, value)

    if changes:
        item.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=ChecklistAuditAction.ITEM_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_ITEM,
            entity_id=item.id,
            summary=f"Item '{item.label}' updated.",
            changes=changes,
            metadata={"checklist_id": str(item.checklist_id)},
            ip_address=ip_address,
        )
    return item


@transaction.atomic
def set_item_status(
    *,
    actor: Any,
    item: ChecklistItem,
    status: str,
    status_note: str = "",
    evidence_file_id: Any = None,
    evidence_note: str = "",
    clear_evidence: bool = False,
    ip_address: str | None = None,
) -> ChecklistItem:
    """Record what happened to one requirement.

    The single place an item's status moves, so three rules hold everywhere at
    once: waiving or blocking demands an explanation, evidence must belong to
    this applicant, and the completion stamps track the status instead of
    drifting from it.
    """
    _assert_editable(item.checklist)

    note = normalize_unicode(status_note or "")
    if status in NOTE_REQUIRED_STATUSES and not note.strip():
        raise StatusNoteRequiredError("A note is required when an item is waived or blocked.")

    previous = item.status
    update_fields = ["status", "status_note", "updated_at"]
    item.status = status
    item.status_note = note

    if clear_evidence:
        item.evidence_file = None
        update_fields.append("evidence_file")
    elif evidence_file_id is not None:
        item.evidence_file = _resolve_evidence(item.checklist, evidence_file_id)
        update_fields.append("evidence_file")

    if evidence_note:
        item.evidence_note = normalize_unicode(evidence_note)
        update_fields.append("evidence_note")

    # The completion stamps follow the status rather than accumulating. An item
    # moved back to pending that kept a "completed by" would report work nobody
    # is now claiming.
    if status == ItemStatus.COMPLETED:
        item.completed_at = timezone.now()
        item.completed_by = actor
    else:
        item.completed_at = None
        item.completed_by = None
    update_fields.extend(["completed_at", "completed_by"])

    item.save(update_fields=update_fields)
    _record(
        action=ChecklistAuditAction.ITEM_STATUS_CHANGED,
        actor=actor,
        entity_type=AUDIT_ENTITY_ITEM,
        entity_id=item.id,
        summary=f"Item '{item.label}' moved from {previous} to {status}.",
        reason=note,
        changes={"status": {"from": previous, "to": status}},
        metadata={
            "checklist_id": str(item.checklist_id),
            "evidence_file_id": str(item.evidence_file_id) if item.evidence_file_id else None,
        },
        ip_address=ip_address,
    )
    return item
