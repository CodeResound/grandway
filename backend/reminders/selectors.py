"""Read-only query logic for the reminders app (no side effects).

Reminders are shared across the consultancy like the records they point at —
there is no owner scoping here; every Admin and Lead Manager sees every
reminder.

``get_due_reminders`` is consumed by the ``notifications`` nightly sweep. The
coupling runs inward to ``notifications`` (it imports this module); this app
imports nothing from ``notifications``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from audit.selectors import get_events_for_entity
from core.nepal.calendar import nepal_today
from django.db.models import QuerySet

from reminders.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_REMINDER, ReminderStatus
from reminders.models import Reminder

if TYPE_CHECKING:
    # Annotation only. Importing another app's model at runtime for anything but
    # a ForeignKey is the coupling §4 forbids; the audit selector returns the
    # queryset, this app never touches the model.
    from audit.models import AuditEvent


def get_reminders() -> QuerySet[Reminder]:
    """Every reminder, newest first, with the relations the list shape reads.

    The ``select_related`` set is required, not an optimisation: the list rows
    show the owner's name and who set the reminder, so without it the list is
    N+1 (§6).
    """
    return Reminder.objects.select_related("applicant", "client", "created_by", "closed_by")


def get_reminder_by_id(reminder_id: str) -> Reminder | None:
    """One reminder with its detail relations, or None."""
    return (
        Reminder.objects.select_related("applicant", "client", "created_by", "closed_by")
        .filter(pk=reminder_id)
        .first()
    )


def filter_reminders(queryset: QuerySet[Reminder], filters: dict[str, Any] | None = None) -> QuerySet[Reminder]:
    """Apply the documented list filters.

    Recognised keys: ``applicant``, ``client``, ``status``, ``due_before``,
    ``due_after``, and ``fiscal_year`` (``YYYY/YY``, Nepali fiscal year over
    ``due_date`` — §39.4).

    Omitting ``status`` returns open and closed reminders alike — whether a
    record panel hides finished follow-ups is a presentation decision, so the
    API does not silently make it.
    """
    filters = filters or {}

    applicant = filters.get("applicant")
    if applicant:
        queryset = queryset.filter(applicant_id=applicant)

    client = filters.get("client")
    if client:
        queryset = queryset.filter(client_id=client)

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    due_before = filters.get("due_before")
    if due_before:
        queryset = queryset.filter(due_date__lte=due_before)

    due_after = filters.get("due_after")
    if due_after:
        queryset = queryset.filter(due_date__gte=due_after)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        # ``fiscal_year_gregorian_range`` returns plain dates, start-inclusive
        # and end-exclusive (see ``core.querying.resolve_window``).
        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(due_date__gte=start, due_date__lt=end)

    return queryset


def get_due_reminders() -> QuerySet[Reminder]:
    """Every open reminder whose day has arrived, for the notification sweep.

    "Due" is date-only against Nepal's today (§39.5) — never
    ``date.today()``, which flips a day early or late around midnight UTC.
    ``due_date__lte`` rather than an equality: an overdue reminder that nobody
    has acted on stays due, which is what keeps its alert alive (and
    idempotent) across successive sweeps.

    ``select_related`` carries the owner rows so the alert composer can name
    the applicant or client without one query per reminder.
    """
    return (
        Reminder.objects.filter(status=ReminderStatus.ACTIVE, due_date__lte=nepal_today())
        .select_related("applicant", "client")
        .order_by("due_date", "created_at")
    )


def get_history_for_reminder(reminder: Reminder) -> QuerySet[AuditEvent]:
    """A reminder's chronological history, newest first, from the central audit log."""
    return get_events_for_entity(
        entity_type=AUDIT_ENTITY_REMINDER,
        entity_id=str(reminder.id),
        app_label=AUDIT_APP_LABEL,
    )
