"""Business logic for the notifications app.

Three responsibilities, in the order they matter:

1. **One write path.** ``dispatch`` is the only function anywhere that creates a
   ``Notification``. The sweep calls it, the five signal receivers call it, and
   nothing else does — no view, no serializer, no other app. Everything it writes
   goes through ``get_or_create`` on ``(recipient, dedupe_key)``, which is where
   the app's idempotency actually lives.
2. **Routing.** ``recipients_for_*`` answers "who has to act", and it is a
   business question rather than a plumbing one: it decides who sees that an
   applicant is missing a bank statement. The rules are in
   ``docs/DATA_CONTRACT.md`` under Recipient Routing and implemented once here.
3. **Composition.** One ``build_*_alert`` per notification type, each turning a
   source record into an ``AlertSpec``. They are the only place in this app that
   reads another app's model attributes, which keeps the coupling to a single
   auditable region of one file.

**Nothing here compares an old field value to a new one.** The dedupe key
carries the value that changed — a journey's stage, an item's due date, an
assignee's id — so a save that changed nothing produces a key that already
exists and writes nothing. That is why there is no ``pre_save`` receiver in this
app and no ``__original_stage`` attribute stashed on any instance.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from authenticate.selectors import get_active_admins
from core.nepal.calendar import nepal_today
from django.db import transaction
from django.utils import timezone

from notifications.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_NOTIFICATION,
    TYPE_PRIORITY,
    DeliveryChannel,
    DeliveryState,
    GenerationSource,
    NotificationAuditAction,
    NotificationStatus,
    NotificationType,
    Priority,
    Resolution,
    SourceEntityType,
)
from notifications.exceptions import AlreadyTerminalError
from notifications.models import Notification

logger = logging.getLogger(__name__)

#: Authority types that map straight onto an audit actor type. Anything else —
#: including the sweep and the signal receivers, which act on behalf of nobody —
#: is recorded as ``system``. Declared locally rather than imported from
#: ``checklists``, which has the identical set for the identical reason: §4
#: permits importing another app's selectors and services, not its private
#: constants, and a shared tuple is what makes a later divergence invisible.
_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    """The audit actor type for a user, or ``system`` when nobody decided."""
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


@dataclass(frozen=True)
class AlertSpec:
    """One composed alert, before it is addressed to anybody.

    The payload contract between a ``build_*_alert`` composer and ``dispatch``.
    It exists because the alternative is a nine-argument function called from
    eleven places, where a transposed pair of strings is invisible at every one
    of them. Frozen, because the same spec is dispatched to several recipients
    and a composer that could be mutated per-recipient would let two people
    receive different text about the same fact.

    ``source_api_path`` is the nearest *retrievable* endpoint for the source, not
    always the entity itself — an expiring passport has no endpoint of its own,
    so its spec points at the applicant that holds it.
    """

    notification_type: str
    dedupe_key: str
    title: str
    body: str
    source_app: str
    source_entity_type: str
    source_entity_id: Any
    source_api_path: str = ""
    due_at: datetime | None = None


# ---------------------------------------------------------------------------
# 1. The single write path
# ---------------------------------------------------------------------------


def dispatch(
    spec: AlertSpec,
    recipients: Iterable[Any],
    *,
    generated_by: str = GenerationSource.SWEEP,
) -> list[Notification]:
    """Address one alert to each recipient. Returns only the rows actually created.

    Idempotent by construction, not by convention: ``get_or_create`` on
    ``(recipient, dedupe_key)`` runs against the unique constraint, so two
    concurrent sweeps race into the database rather than into each other.

    **An existing row is never touched** — not its title, not its priority, not
    its status. That is the concept file's "if the source record changes, the
    notification should not silently rewrite history", and it is also what makes
    dismissal stick: a dismissed alert still occupies its key, so tonight's sweep
    finds it, creates nothing, and leaves the user's decision alone.

    Returns the created rows so callers can report how many alerts are genuinely
    new. A caller that ignores the return value still gets correct behaviour.
    """
    created: list[Notification] = []
    priority = TYPE_PRIORITY.get(spec.notification_type, Priority.NORMAL)
    now = timezone.now()

    for recipient in recipients:
        notification, was_created = Notification.objects.get_or_create(
            recipient=recipient,
            dedupe_key=spec.dedupe_key,
            defaults={
                "notification_type": spec.notification_type,
                "priority": priority,
                "title": spec.title[:200],
                "body": spec.body,
                "source_app": spec.source_app,
                "source_entity_type": spec.source_entity_type,
                "source_entity_id": spec.source_entity_id,
                "source_api_path": spec.source_api_path[:255],
                "due_at": spec.due_at,
                "generated_by": generated_by,
                # In-app delivery completes the moment the row exists: there is
                # nothing between writing it and the feed being able to return
                # it. A channel with a real transport would leave this pending
                # and let its own sender advance it.
                "delivery_channel": DeliveryChannel.IN_APP,
                "delivery_state": DeliveryState.DELIVERED,
                "delivered_at": now,
            },
        )
        if was_created:
            created.append(notification)

    return created


# ---------------------------------------------------------------------------
# 2. Routing — who has to act
# ---------------------------------------------------------------------------


def _admins() -> list[Any]:
    """Every active Admin. The fallback for work nobody owns."""
    return list(get_active_admins())


def _finalize(candidates: Iterable[Any], *, exclude_actor: Any = None) -> list[Any]:
    """Deduplicate, drop deactivated accounts, and drop the actor.

    Three rules that would otherwise be repeated in every ``recipients_for_*``:

    * **Deduplicate.** A file's uploader who is also an Admin appears twice in
      the candidate list and must receive one alert. The unique constraint would
      catch it anyway; catching it here means the sweep's "created" count is the
      truth rather than one short.
    * **Drop deactivated accounts.** Writing to a queue nobody can log in to read
      is not delivery.
    * **Drop the actor.** Nobody is told about their own action. The Admin who
      rejects a file does not receive an alert saying it was rejected — that is
      not a notification, it is an echo, and an inbox full of echoes stops being
      read.

    Order is preserved so the caller's intent (uploader first, then Admins) shows
    up in the sweep's logs.
    """
    actor_id = getattr(exclude_actor, "id", None)
    seen: set[Any] = set()
    resolved: list[Any] = []

    for user in candidates:
        if user is None or not getattr(user, "is_active", False):
            continue
        if user.id in seen or (actor_id is not None and user.id == actor_id):
            continue
        seen.add(user.id)
        resolved.append(user)

    return resolved


def recipients_for_checklist_item(item: Any, *, exclude_actor: Any = None) -> list[Any]:
    """The item's assignee, else the checklist's, else every Admin.

    The two-step fallback is the whole reason item-level assignment exists: a
    checklist assigned to one Lead Manager may carry a single item somebody else
    is chasing, and alerting the checklist's owner about it would tell the wrong
    person.
    """
    assignee = item.assigned_to or item.checklist.assigned_to
    return _finalize([assignee] if assignee else _admins(), exclude_actor=exclude_actor)


def recipients_for_checklist(checklist: Any, *, exclude_actor: Any = None) -> list[Any]:
    """The checklist's assignee, else every Admin."""
    assignee = checklist.assigned_to
    return _finalize([assignee] if assignee else _admins(), exclude_actor=exclude_actor)


def recipients_for_admins(*, exclude_actor: Any = None) -> list[Any]:
    """Every active Admin.

    Used for offers, passports, and journey lifecycle — none of which carry an
    owner anywhere in this project today. That is a fact about the current data
    model rather than a decision this app is making, and it will narrow on its
    own as ownership is introduced elsewhere, with no change here.
    """
    return _finalize(_admins(), exclude_actor=exclude_actor)


def recipients_for_file(uploaded_file: Any, *, exclude_actor: Any = None) -> list[Any]:
    """The uploader **and** every Admin.

    The only routing rule in this app that fans out to two audiences at once, and
    deliberately: the person who uploaded a rejected file is the one who can
    produce a corrected one, while an Admin needs to know that a file in the
    review queue came back rejected at all. Either alone leaves a real gap.
    """
    return _finalize([uploaded_file.uploaded_by, *_admins()], exclude_actor=exclude_actor)


# ---------------------------------------------------------------------------
# 3. Composition — one builder per type
# ---------------------------------------------------------------------------
#
# These are the only functions in this app that read another app's model
# attributes. Keeping them together means the whole cross-app coupling surface is
# one region of one file rather than scattered through selectors and views.


def _applicant_name(applicant: Any) -> str:
    """An applicant's name for display, English first (§39.1).

    Both forms are canonical identities rather than translations, so this picks
    the one a staff-facing alert reads best in and never claims the other does
    not exist. ``full_name`` is required on the model, so the fallback always
    resolves.
    """
    return applicant.full_name


def _key(notification_type: str, entity_type: str, entity_id: Any, discriminator: str = "") -> str:
    """Build a dedupe key. The discriminator is what makes a *new* instance raisable.

    Without one, a rescheduled checklist item or a renewed passport could never
    raise a second alert, because the first one occupies the key forever. With
    one, "the same condition again" and "a genuinely new condition" are different
    strings and the database tells them apart.
    """
    suffix = f":{discriminator}" if discriminator else ""
    return f"{notification_type}:{entity_type}:{entity_id}{suffix}"


def _days_between(target: date, today: date) -> int:
    return (target - today).days


def build_checklist_item_alert(item: Any, *, overdue: bool) -> AlertSpec:
    """Alert for one checklist requirement that is due or already late.

    The due date is part of the key, so pushing an item's deadline back raises a
    fresh alert rather than silently reusing the one that was resolved when the
    old deadline was met.
    """
    notification_type = NotificationType.CHECKLIST_ITEM_OVERDUE if overdue else NotificationType.CHECKLIST_ITEM_DUE
    applicant = _applicant_name(item.checklist.journey.applicant)
    due_date = item.due_at.date() if item.due_at else None
    days = _days_between(due_date, nepal_today()) if due_date else None

    if overdue:
        title = f"Overdue: {item.label}"
        timing = f"was due {abs(days)} day{'s' if abs(days) != 1 else ''} ago" if days is not None else "is overdue"
    else:
        title = f"Due soon: {item.label}"
        timing = f"is due in {days} day{'s' if days != 1 else ''}" if days is not None else "is due"

    return AlertSpec(
        notification_type=notification_type,
        dedupe_key=_key(notification_type, SourceEntityType.CHECKLIST_ITEM, item.id, str(due_date)),
        title=title,
        body=f"Required for {applicant} on '{item.checklist.title}'. It {timing}.",
        source_app="checklists",
        source_entity_type=SourceEntityType.CHECKLIST_ITEM,
        source_entity_id=item.id,
        source_api_path=f"/api/v1/checklists/{item.checklist_id}/items/{item.id}/",
        due_at=item.due_at,
    )


def build_missing_documents_alert(checklist: Any) -> AlertSpec:
    """Alert for document requirements nobody put a date on.

    Carries **no discriminator**, which is a real limitation recorded in
    ``docs/DATA_CONTRACT.md``: once resolved for a checklist this never fires
    again for that checklist. Putting the pending count in the key was considered
    and rejected — collecting one of five documents would resolve the old alert
    and raise a new one on every sweep, which is precisely the noise the design
    exists to prevent.

    The count in the body is a snapshot taken when the alert was raised. It is
    not updated later, for the same reason nothing else here is: the live number
    is on the source record, and an alert that rewrote itself would stop being
    evidence of what somebody was told.
    """
    applicant = _applicant_name(checklist.journey.applicant)
    count = getattr(checklist, "pending_document_count", 0)
    plural = "s" if count != 1 else ""

    return AlertSpec(
        notification_type=NotificationType.MISSING_DOCUMENTS,
        dedupe_key=_key(NotificationType.MISSING_DOCUMENTS, SourceEntityType.CHECKLIST, checklist.id),
        title=f"{count} document{plural} still outstanding for {applicant}",
        body=(
            f"'{checklist.title}' has {count} document requirement{plural} with no due date set "
            f"and nothing collected. Nobody is being chased for these."
        ),
        source_app="checklists",
        source_entity_type=SourceEntityType.CHECKLIST,
        source_entity_id=checklist.id,
        source_api_path=f"/api/v1/checklists/{checklist.id}/",
        due_at=None,
    )


def build_offer_deadline_alert(offer: Any, *, expired: bool) -> AlertSpec:
    """Alert for an issued offer whose response deadline is near or passed.

    ``expired`` is the only ``urgent`` alert this app raises. Every other overdue
    thing here can still be fixed by doing the work today; a missed offer
    deadline may have already cost the applicant the place.
    """
    notification_type = NotificationType.OFFER_EXPIRED if expired else NotificationType.OFFER_RESPONSE_DUE
    applicant = _applicant_name(offer.journey.applicant)
    deadline = offer.response_deadline
    days = _days_between(deadline, nepal_today()) if deadline else None

    if expired:
        title = f"Offer response overdue: {applicant}"
        timing = f"passed {abs(days)} day{'s' if abs(days) != 1 else ''} ago" if days is not None else "has passed"
    else:
        title = f"Offer response due: {applicant}"
        timing = f"is in {days} day{'s' if days != 1 else ''}" if days is not None else "is approaching"

    return AlertSpec(
        notification_type=notification_type,
        dedupe_key=_key(notification_type, SourceEntityType.OFFER, offer.id, str(deadline)),
        title=title,
        body=(
            f"{offer.program_title} at {offer.institution_name} is still awaiting a response. "
            f"The deadline {timing}."
        ),
        source_app="offers",
        source_entity_type=SourceEntityType.OFFER,
        source_entity_id=offer.id,
        source_api_path=f"/api/v1/offers/{offer.id}/",
        # A response deadline is a calendar date, not an instant. Rendered as
        # Kathmandu midnight so the due bucket agrees with the day staff read off
        # the screen (§39.5) rather than shifting by 5¾ hours.
        due_at=_nepal_midnight(deadline) if deadline else None,
    )


def build_passport_alert(passport: Any) -> AlertSpec:
    """Alert for a passport that has expired or is close to it.

    ``high`` despite a six-month horizon, because it is the one blocker on this
    list that cannot be resolved inside the office at any speed. The expiry date
    is the discriminator, so a renewed passport raises a fresh alert on its new
    date rather than inheriting the resolved one.

    The passport number is deliberately absent from both the title and the body.
    It is not a secret, but it is an identity document number, and a feed is the
    one place in this system where a record's details are copied out of the app
    that owns them.
    """
    applicant = _applicant_name(passport.applicant)
    expiry = passport.expiry_date
    days = _days_between(expiry, nepal_today())

    if days < 0:
        title = f"Passport expired: {applicant}"
        timing = f"expired {abs(days)} day{'s' if abs(days) != 1 else ''} ago"
    else:
        title = f"Passport expiring: {applicant}"
        timing = f"expires in {days} day{'s' if days != 1 else ''}"

    return AlertSpec(
        notification_type=NotificationType.PASSPORT_EXPIRING,
        dedupe_key=_key(
            NotificationType.PASSPORT_EXPIRING,
            SourceEntityType.PASSPORT_DETAIL,
            passport.id,
            str(expiry),
        ),
        title=title,
        body=f"The passport on file {timing}. A visa application cannot be lodged on it much later than that.",
        source_app="applicants",
        source_entity_type=SourceEntityType.PASSPORT_DETAIL,
        source_entity_id=passport.id,
        # A passport detail has no endpoint of its own — the applicant is the
        # nearest retrievable record.
        source_api_path=f"/api/v1/applicants/{passport.applicant_id}/",
        due_at=_nepal_midnight(expiry),
    )


def build_assignment_alert(record: Any, *, entity_type: str) -> AlertSpec:
    """Alert telling somebody work has landed on their desk.

    The assignee's id is the discriminator, so reassigning the same checklist
    alerts the new owner while a re-save alerts nobody. The previous owner is not
    told the work left them — that is a different notification with a different
    audience, and the concept file does not ask for it.
    """
    is_item = entity_type == SourceEntityType.CHECKLIST_ITEM
    label = record.label if is_item else record.title
    checklist = record.checklist if is_item else record
    applicant = _applicant_name(checklist.journey.applicant)
    path = (
        f"/api/v1/checklists/{record.checklist_id}/items/{record.id}/"
        if is_item
        else f"/api/v1/checklists/{record.id}/"
    )

    return AlertSpec(
        notification_type=NotificationType.ASSIGNMENT_RECEIVED,
        dedupe_key=_key(
            NotificationType.ASSIGNMENT_RECEIVED,
            entity_type,
            record.id,
            str(record.assigned_to_id),
        ),
        title=f"Assigned to you: {label}",
        body=f"On {applicant}'s file ('{checklist.title}').",
        source_app="checklists",
        source_entity_type=entity_type,
        source_entity_id=record.id,
        source_api_path=path,
        due_at=record.due_at,
    )


def build_file_rejected_alert(uploaded_file: Any) -> AlertSpec:
    """Alert that a file came back rejected and a replacement is needed.

    The rejection reason is included because it is the entire actionable content
    — "your file was rejected" without it sends the recipient to another screen
    to learn anything. The stored path on disk is not included and must never be
    (§17).
    """
    reason = (uploaded_file.rejection_reason or "").strip()
    return AlertSpec(
        notification_type=NotificationType.FILE_REJECTED,
        dedupe_key=_key(NotificationType.FILE_REJECTED, SourceEntityType.UPLOADED_FILE, uploaded_file.id),
        title=f"File rejected: {uploaded_file.original_filename}",
        body=reason or "No reason was recorded. A replacement is needed before this can be accepted.",
        source_app="uploaded_files",
        source_entity_type=SourceEntityType.UPLOADED_FILE,
        source_entity_id=uploaded_file.id,
        source_api_path=f"/api/v1/files/{uploaded_file.id}/",
        due_at=None,
    )


def build_journey_alert(journey: Any, *, closed: bool) -> AlertSpec:
    """Alert for a journey reaching a new stage, or reaching the end of one.

    The stage is the discriminator, which has one consequence worth knowing: a
    journey moved *back* to a stage it already held raises nothing, because the
    key it would use is already taken. Recorded as a known limitation in
    ``docs/DATA_CONTRACT.md`` rather than fixed with a timestamp in the key,
    which would make every save a new alert.
    """
    notification_type = NotificationType.JOURNEY_CLOSED if closed else NotificationType.JOURNEY_STAGE_CHANGED
    applicant = _applicant_name(journey.applicant)
    stage_label = journey.get_stage_display()

    if closed:
        outcome = journey.get_outcome_display() if journey.outcome else "no outcome recorded"
        title = f"Journey {stage_label.lower()}: {applicant}"
        body = f"{journey.destination_label} — {outcome}."
    else:
        title = f"{applicant} moved to {stage_label}"
        body = f"Journey to {journey.destination_label} is now at the {stage_label.lower()} stage."

    return AlertSpec(
        notification_type=notification_type,
        dedupe_key=_key(
            notification_type,
            SourceEntityType.APPLICANT_JOURNEY,
            journey.id,
            journey.stage,
        ),
        title=title,
        body=body,
        source_app="applicant_journeys",
        source_entity_type=SourceEntityType.APPLICANT_JOURNEY,
        source_entity_id=journey.id,
        source_api_path=f"/api/v1/journeys/{journey.id}/",
        due_at=None,
    )


def build_offer_decided_alert(offer: Any) -> AlertSpec:
    """Alert that an issued offer reached a decision.

    The status is the discriminator, so an offer that is declined and later
    reissued and accepted produces two alerts, which is correct — those are two
    different facts about the applicant's file.
    """
    applicant = _applicant_name(offer.journey.applicant)
    decision = offer.get_status_display()

    return AlertSpec(
        notification_type=NotificationType.OFFER_DECIDED,
        dedupe_key=_key(NotificationType.OFFER_DECIDED, SourceEntityType.OFFER, offer.id, offer.status),
        title=f"Offer {decision.lower()}: {applicant}",
        body=f"{offer.program_title} at {offer.institution_name}.",
        source_app="offers",
        source_entity_type=SourceEntityType.OFFER,
        source_entity_id=offer.id,
        source_api_path=f"/api/v1/offers/{offer.id}/",
        due_at=None,
    )


def _nepal_midnight(value: date) -> datetime:
    """The instant a calendar date begins in Kathmandu, as an aware datetime (§39.5).

    Deadlines in the source apps are ``DateField``s — a response deadline is a
    day where the staff work, not an instant. Anchoring them at UTC midnight
    would shift every one by 5¾ hours and put a due-today alert in yesterday's
    bucket for the first quarter of the working morning.
    """
    from datetime import time

    from core.nepal.constants import NEPAL_TZ

    return datetime.combine(value, time.min, tzinfo=NEPAL_TZ)


# ---------------------------------------------------------------------------
# 4. Recipient-facing state changes
# ---------------------------------------------------------------------------


def mark_read(notification: Notification) -> Notification:
    """Mark one notification read. Idempotent — a second call keeps the first timestamp.

    Keeping the original timestamp matters: "when did they first see this" is
    the question a read receipt answers, and refreshing it on every page load
    would make it answer "when did they last look at the list" instead.
    """
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    return notification


def mark_unread(notification: Notification) -> Notification:
    """Return one notification to unread.

    Offered because an inbox without it punishes the reflex of clicking through a
    list — the user who opens something they cannot deal with right now needs a
    way to put it back.
    """
    if notification.read_at is not None:
        notification.read_at = None
        notification.save(update_fields=["read_at", "updated_at"])
    return notification


def mark_all_read(user: Any) -> int:
    """Mark every unread notification on this user's feed read. Returns how many.

    One ``UPDATE``, deliberately: a loop calling ``mark_read`` would be a query
    per row on the one action a user takes when their feed has got away from
    them, which is exactly when it is longest.

    Not narrowed to ``active``. Clearing the badge must actually leave nothing
    unread, or the number the user just cleared returns on their next page load.
    """
    from notifications.selectors import get_unread

    return get_unread(user).update(read_at=timezone.now(), updated_at=timezone.now())


@transaction.atomic
def dismiss(notification: Notification, *, actor: Any, ip_address: str | None = None) -> Notification:
    """Dismiss one notification — the user's decision that this needs no action.

    Refuses an already-terminal notification rather than returning a cheerful
    200 for a write it did not perform: two clients on the same feed, or one
    holding a stale list, otherwise never learn the server disagrees with them.

    **Audited, unlike every other action in this app.** Creating a notification
    is not audited (the row *is* the record, and auditing each one would double
    the nightly sweep's write volume to say the system told somebody something),
    and reading one is not either. Dismissal is audited because it is a human
    deciding that a flagged piece of work does not need doing — the one judgement
    made here that somebody may be asked about later.

    A dismissed alert keeps its dedupe key forever, which is what makes the
    decision stick: tonight's sweep finds the row, creates nothing, and does not
    argue.
    """
    if notification.status != NotificationStatus.ACTIVE:
        raise AlreadyTerminalError(f"This notification is already {notification.status}.")

    now = timezone.now()
    notification.status = NotificationStatus.DISMISSED
    notification.resolution = Resolution.DISMISSED_BY_USER
    notification.resolved_at = now
    notification.dismissed_by = actor
    notification.save(
        update_fields=["status", "resolution", "resolved_at", "dismissed_by", "updated_at"],
    )

    record_event(
        app_label=AUDIT_APP_LABEL,
        action=NotificationAuditAction.NOTIFICATION_DISMISSED,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id),
        actor_label=getattr(actor, "username", ""),
        entity_type=AUDIT_ENTITY_NOTIFICATION,
        entity_id=str(notification.id),
        ip_address=ip_address,
        summary=f"Dismissed a {notification.notification_type} alert.",
        metadata={
            "notification_type": notification.notification_type,
            "source_app": notification.source_app,
            "source_entity_type": notification.source_entity_type,
            "source_entity_id": str(notification.source_entity_id) if notification.source_entity_id else None,
        },
    )
    return notification


# ---------------------------------------------------------------------------
# 5. Auto-resolution — the sweep's second pass
# ---------------------------------------------------------------------------


def resolve_cleared(live_keys: set[str], *, types: tuple[str, ...]) -> int:
    """Resolve sweep alerts whose source condition is no longer true. Returns how many.

    ``live_keys`` is every key the raise pass just produced — the complete set of
    conditions that hold right now. Anything active, sweep-raised, and of a type
    that was examined, whose key is *not* in that set, has been dealt with in the
    source app: the item was completed, the offer was answered, the passport was
    renewed.

    **The caller must pass the types it actually examined.** A ``--type`` run
    looks at one condition, and without that narrowing it would resolve every
    other type's alerts as "no longer true" purely because it never looked for
    them. The same argument is why a generator that raised an exception must
    exclude its types from this call — a transient database error must not read
    as "nothing is overdue any more".

    One ``UPDATE``. A loop would be a query per resolved row on the pass that
    runs nightly across every recipient.
    """
    from notifications.selectors import get_sweep_candidates_to_resolve

    stale = get_sweep_candidates_to_resolve(types=types).exclude(dedupe_key__in=live_keys)
    now = timezone.now()
    return stale.update(
        status=NotificationStatus.RESOLVED,
        resolution=Resolution.SOURCE_CLEARED,
        resolved_at=now,
        updated_at=now,
    )


def record_generation_failure(notification_type: str, error: Exception) -> None:
    """Log and audit a generator that failed, so the gap is not silent.

    A failed generator produces no alerts, and no alerts is exactly what a quiet
    night looks like. Without this, "the passport sweep has been broken for a
    week" and "no passports are expiring" are the same observation.

    Never re-raises. The sweep runs the remaining generators, and the caller
    excludes this generator's types from ``resolve_cleared``.
    """
    logger.exception("notification generation failed", extra={"notification_type": notification_type})
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=NotificationAuditAction.GENERATION_FAILED,
        entity_type=AUDIT_ENTITY_NOTIFICATION,
        success=False,
        summary=f"Notification generation failed for {notification_type}.",
        metadata={"notification_type": notification_type, "error": type(error).__name__},
    )
