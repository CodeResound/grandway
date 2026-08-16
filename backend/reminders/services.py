"""Business logic for the reminders app.

Services receive already-validated data, own every rule that spans more than
one field, and return model instances — never HTTP responses.

Every mutation appends one event to the central audit log; that log *is* a
reminder's history. The concept asks that creation, completion, dismissal, and
rescheduling "remain traceable ... so staff can see what was set, when it was
set, and what happened to it later" — delivered by recording a ``from``/``to``
pair for every changed field, not by versioning rows.

There is no delete service. A reminder ends as ``completed`` or ``dismissed``
and is retained forever. This app never dispatches the due alert itself —
``notifications`` raises it from ``selectors.get_due_reminders`` on its
nightly sweep, and this module imports nothing from ``notifications``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone

from reminders.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_REMINDER,
    OWNER_FIELDS,
    OwnerType,
    ReminderAuditAction,
    ReminderStatus,
)
from reminders.exceptions import (
    OwnerNotFoundError,
    OwnerNotResolvedError,
    ReminderAlreadyClosedError,
)
from reminders.models import Reminder

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _owner_lookups() -> dict[str, Any]:
    """Owner-field → selector, resolved lazily to keep app import order loose.

    Importing another app's ``selectors.py`` is the documented §4 boundary;
    doing it inside the function keeps this module importable before the
    owner apps' registries are ready (the same reason selectors lazy-import
    ``fiscal_year_gregorian_range``).
    """
    from applicants.selectors import get_applicant_by_id
    from clients.selectors import get_client_by_id

    return {
        OwnerType.APPLICANT: get_applicant_by_id,
        OwnerType.CLIENT: get_client_by_id,
    }


def resolve_owner(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve the single owner reference in ``data`` to ``{field: instance}``.

    The serializer checks the *count* too, for a field-level error message;
    the database constraint makes it a schema rule; the business layer states
    it as well rather than assuming two other layers caught it — the same
    three-layer reasoning as ``uploaded_files``.

    Returns an instance rather than an id so a nonexistent owner is caught
    here — as a 400 naming the field — instead of at the database as an
    integrity error.
    """
    supplied = {field: data[field] for field in OWNER_FIELDS if data.get(field) is not None}
    if len(supplied) != 1:
        raise OwnerNotResolvedError("Exactly one of applicant or client must be supplied.")

    field, value = next(iter(supplied.items()))
    instance = _owner_lookups()[field](str(value))
    if instance is None:
        raise OwnerNotFoundError(field, f"No {field} with that id.")
    return {field: instance}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    reminder: Reminder,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one reminder audit event. Never pass secrets or full record dumps."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=AUDIT_ENTITY_REMINDER,
        entity_id=str(reminder.id),
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
    from writing a misleading "rescheduled" event into the history.
    """
    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(instance, name)
        if previous != value:
            changes[name] = {"from": str(previous), "to": str(value)}
            setattr(instance, name, value)
    return changes


def _require_open(reminder: Reminder) -> None:
    """Terminal states are final — the concept replaces reopening with a new reminder."""
    if reminder.status != ReminderStatus.ACTIVE:
        raise ReminderAlreadyClosedError(f"This reminder is already {reminder.status}.")


# ---------------------------------------------------------------------------
# Creation and editing
# ---------------------------------------------------------------------------


@transaction.atomic
def create_reminder(
    *,
    actor: Any,
    due_date: date,
    note: str,
    applicant: Any = None,
    client: Any = None,
    ip_address: str | None = None,
) -> Reminder:
    """Set a future follow-up against one applicant or client.

    Exactly-one-owner and the due-date floor are validated by the serializer
    and re-enforced by the ``reminder_single_owner`` database constraint; the
    note is normalized here as well (§39.2) so a direct service caller — a
    management command, a test, a future import — cannot bypass it.
    """
    reminder = Reminder.objects.create(
        applicant=applicant,
        client=client,
        due_date=due_date,
        note=normalize_unicode(note),
        created_by=actor,
    )

    _record(
        action=ReminderAuditAction.REMINDER_CREATED,
        actor=actor,
        reminder=reminder,
        summary=f"Reminder set on {reminder.owner_type} record, due {reminder.due_date}.",
        metadata={
            "owner_type": reminder.owner_type,
            "owner_id": str(reminder.owner_id),
            "due_date": reminder.due_date.isoformat(),
        },
        ip_address=ip_address,
    )
    return reminder


@transaction.atomic
def update_reminder(
    *,
    actor: Any,
    reminder: Reminder,
    due_date: date | None = None,
    note: str | None = None,
    ip_address: str | None = None,
) -> Reminder:
    """Reschedule an open reminder or correct its note.

    The owner is immutable — a reminder about the wrong record is dismissed
    and recreated. Moving the due date is the event the concept most wants
    traceable, so it is audited as ``reminder_rescheduled`` with the old and
    new date; a note-only correction is the quieter ``reminder_updated``.
    """
    _require_open(reminder)

    fields: dict[str, Any] = {}
    if due_date is not None:
        fields["due_date"] = due_date
    if note is not None:
        fields["note"] = normalize_unicode(note)

    changes = _diff(reminder, fields)
    if not changes:
        return reminder

    reminder.save(update_fields=[*changes.keys(), "updated_at"])

    rescheduled = "due_date" in changes
    _record(
        action=(ReminderAuditAction.REMINDER_RESCHEDULED if rescheduled else ReminderAuditAction.REMINDER_UPDATED),
        actor=actor,
        reminder=reminder,
        summary=(f"Reminder rescheduled to {reminder.due_date}." if rescheduled else "Reminder note updated."),
        changes=changes,
        ip_address=ip_address,
    )
    return reminder


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------


def _close(
    *,
    actor: Any,
    reminder: Reminder,
    status: str,
    action: str,
    summary: str,
    reason: str,
    ip_address: str | None,
) -> Reminder:
    """Shared terminal transition: stamp who closed it, when, and why."""
    _require_open(reminder)

    reminder.status = status
    reminder.closed_at = timezone.now()
    reminder.closed_by = actor
    reminder.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])

    _record(
        action=action,
        actor=actor,
        reminder=reminder,
        summary=summary,
        reason=normalize_unicode(reason) if reason else "",
        changes={"status": {"from": ReminderStatus.ACTIVE, "to": status}},
        ip_address=ip_address,
    )
    return reminder


@transaction.atomic
def complete_reminder(
    *,
    actor: Any,
    reminder: Reminder,
    reason: str = "",
    ip_address: str | None = None,
) -> Reminder:
    """Mark a follow-up as done. The optional reason lives on the audit event only."""
    return _close(
        actor=actor,
        reminder=reminder,
        status=ReminderStatus.COMPLETED,
        action=ReminderAuditAction.REMINDER_COMPLETED,
        summary="Reminder completed.",
        reason=reason,
        ip_address=ip_address,
    )


@transaction.atomic
def dismiss_reminder(
    *,
    actor: Any,
    reminder: Reminder,
    reason: str = "",
    ip_address: str | None = None,
) -> Reminder:
    """Drop a follow-up that is no longer relevant, without deleting anything."""
    return _close(
        actor=actor,
        reminder=reminder,
        status=ReminderStatus.DISMISSED,
        action=ReminderAuditAction.REMINDER_DISMISSED,
        summary="Reminder dismissed.",
        reason=reason,
        ip_address=ip_address,
    )
