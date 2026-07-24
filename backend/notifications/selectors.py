"""Read-only query logic for the notifications app (no side effects).

**Every function that returns notifications takes the actor and narrows by
``recipient`` first.** That is this app's access model, not a convenience: a
boolean "may this user read this row" check has to be *called* to work, and the
one call site that forgets is a silent cross-user disclosure. A selector that
cannot return another user's row has no such failure mode. See ``access.py`` for
why the feed is own-recipient only even for an Admin.

The one exception is ``get_sweep_candidates_to_resolve``, which is not a user
query at all — it runs inside the management command, on behalf of nobody, and
is the only function here that sees across recipients.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from core.querying import narrow_to_window
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from notifications.constants import (
    DEFAULT_DUE_WITHIN_DAYS,
    SWEEP_TYPES,
    DueBucket,
    GenerationSource,
    NotificationStatus,
    Priority,
)
from notifications.models import Notification


def _for_recipient(user: Any) -> QuerySet[Notification]:
    """Every notification addressed to this user, newest first.

    The root of every user-facing query in this module. ``select_related`` on the
    recipient is deliberate even though the caller already holds that user: the
    admin and the serializer both reach for it, and one join is cheaper than
    remembering which paths do.
    """
    return Notification.objects.select_related("recipient").filter(recipient=user)


def get_own_notification(user: Any, notification_id: str) -> Notification | None:
    """One notification from this user's own feed, or None.

    Returns ``None`` for a notification that exists but belongs to somebody else
    — indistinguishable, to the caller, from one that was never created. The view
    turns both into the same 404. A 403 would confirm the id exists on another
    person's feed, and a notification title names an applicant and the document
    they are missing.
    """
    return _for_recipient(user).filter(pk=notification_id).first()


def get_feed(user: Any) -> QuerySet[Notification]:
    """This user's whole notification history, newest first, unfiltered.

    Unfiltered by status on purpose: the concept file requires the history be
    preserved after the source issue is fixed, so ``?status=`` is the client's
    choice rather than a default this selector makes for it. ``filter_feed``
    applies the choice.
    """
    return _for_recipient(user)


def filter_feed(queryset: QuerySet[Notification], filters: dict[str, Any] | None = None) -> QuerySet[Notification]:
    """Apply the feed's query parameters to an already recipient-scoped queryset.

    Takes a queryset rather than a user, so it is impossible to call this without
    having scoped first — the type does not stop it, but the shape makes the
    mistake visible at the call site.

    ``due_bucket`` is resolved here rather than in the database as a stored
    column: the bucket a row falls in changes every hour on its own, and a
    nightly job whose only purpose was to move rows between buckets would be a
    second source of truth for a fact ``due_at`` already holds.
    """
    filters = filters or {}

    if status := filters.get("status"):
        queryset = queryset.filter(status=status)
    if (is_read := filters.get("is_read")) is not None:
        queryset = queryset.filter(read_at__isnull=not is_read)
    if notification_type := filters.get("notification_type"):
        queryset = queryset.filter(notification_type=notification_type)
    if priority := filters.get("priority"):
        queryset = queryset.filter(priority=priority)
    if source_app := filters.get("source_app"):
        queryset = queryset.filter(source_app=source_app)
    if source_entity_id := filters.get("source_entity_id"):
        queryset = queryset.filter(source_entity_id=source_entity_id)
    if bucket := filters.get("due_bucket"):
        queryset = queryset.filter(_due_bucket_condition(bucket, filters.get("due_within_days")))

    return narrow_to_window(
        queryset,
        field="created_at",
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
        fiscal_year=filters.get("fiscal_year"),
    )


def _due_bucket_condition(bucket: str, due_within_days: int | None = None) -> Q:
    """The database condition for one due bucket.

    Mirrors ``Notification.due_bucket`` exactly — the property renders what a row
    *is*, this renders which rows to fetch, and the two disagreeing would produce
    a list whose own rows contradict the filter that returned them. Both are
    derived from ``due_at`` and neither stores anything, so they can only drift
    if someone edits one and not the other; keeping them adjacent in the codebase
    is the mitigation.
    """
    now = timezone.now()
    horizon = now + timedelta(days=due_within_days or DEFAULT_DUE_WITHIN_DAYS)

    if bucket == DueBucket.OVERDUE:
        return Q(due_at__isnull=False, due_at__lt=now)
    if bucket == DueBucket.DUE_SOON:
        return Q(due_at__gte=now, due_at__lte=horizon)
    if bucket == DueBucket.LATER:
        return Q(due_at__gt=horizon)
    return Q(due_at__isnull=True)


def get_feed_summary(user: Any, *, due_within_days: int = DEFAULT_DUE_WITHIN_DAYS) -> dict[str, Any]:
    """The bell badge and the feed's grouping headers, in two queries.

    Exists so a client is not forced to page the whole feed to render a single
    number. Every count is zero-filled across the full vocabulary, because a
    missing key and a zero are the same fact to a human and different facts to a
    client that indexes into the dict.

    ``unread`` counts unread rows **in any status**, unlike everything else here:
    an alert that was resolved before anybody read it still deserves to be
    noticed once. Every other figure is scoped to ``active``, because they answer
    "what is on my desk".
    """
    scoped = _for_recipient(user)
    active = scoped.filter(status=NotificationStatus.ACTIVE)

    now = timezone.now()
    horizon = now + timedelta(days=due_within_days)

    aggregates = active.aggregate(
        total=Count("id"),
        low=Count("id", filter=Q(priority=Priority.LOW)),
        normal=Count("id", filter=Q(priority=Priority.NORMAL)),
        high=Count("id", filter=Q(priority=Priority.HIGH)),
        urgent=Count("id", filter=Q(priority=Priority.URGENT)),
        overdue=Count("id", filter=Q(due_at__isnull=False, due_at__lt=now)),
        due_soon=Count("id", filter=Q(due_at__gte=now, due_at__lte=horizon)),
        later=Count("id", filter=Q(due_at__gt=horizon)),
        no_due=Count("id", filter=Q(due_at__isnull=True)),
    )

    return {
        "unread": scoped.filter(read_at__isnull=True).count(),
        "active": aggregates["total"],
        "by_priority": {
            Priority.LOW: aggregates["low"],
            Priority.NORMAL: aggregates["normal"],
            Priority.HIGH: aggregates["high"],
            Priority.URGENT: aggregates["urgent"],
        },
        "by_due_bucket": {
            DueBucket.OVERDUE: aggregates["overdue"],
            DueBucket.DUE_SOON: aggregates["due_soon"],
            DueBucket.LATER: aggregates["later"],
            DueBucket.NONE: aggregates["no_due"],
        },
    }


def get_unread(user: Any) -> QuerySet[Notification]:
    """This user's unread notifications, whatever their status.

    Backs the bulk read-all action. Not narrowed to ``active``: marking the feed
    read must actually leave nothing unread, or the badge a user just cleared
    reappears on their next page load.
    """
    return _for_recipient(user).filter(read_at__isnull=True)


# ---------------------------------------------------------------------------
# The sweep's own query — the only one here that crosses recipients
# ---------------------------------------------------------------------------


def get_sweep_candidates_to_resolve(*, types: tuple[str, ...] = SWEEP_TYPES) -> QuerySet[Notification]:
    """Active, sweep-raised notifications of the given types, across every recipient.

    The resolve pass subtracts the keys that are still true from this set and
    resolves the remainder. Two narrowings carry the safety of that operation:

    * ``generated_by = sweep`` — a signal alert records that something *happened*
      and has no ongoing condition left to re-check. Auto-resolving one would
      mean deciding a stage change had un-happened.
    * ``types`` — scoped to exactly the generators that ran. A ``--type`` run
      examines one condition, and without this narrowing it would resolve every
      other type's alerts as "no longer true" purely because it never looked.
    """
    return Notification.objects.filter(
        status=NotificationStatus.ACTIVE,
        generated_by=GenerationSource.SWEEP,
        notification_type__in=types,
    )


def get_notifications_for_source(source_entity_type: str, source_entity_id: str) -> QuerySet[Notification]:
    """Every alert ever raised about one record, newest first, across recipients.

    Not exposed through any endpoint — the own-recipient rule would make it
    misleading, since a Lead Manager would see a partial history and have no way
    to know it was partial. Backed by ``notif_source_idx`` and used by the admin
    and by tests, which is what makes the retained history usable rather than
    merely stored.
    """
    return Notification.objects.select_related("recipient").filter(
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
    )
