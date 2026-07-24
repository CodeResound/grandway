"""Read-only query logic for the audit app (no side effects)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from core.nepal.constants import NEPAL_TZ
from django.db.models import QuerySet

from audit.constants import ORDER_ASC, ORDER_DESC, ActorType
from audit.models import AuditEvent


def _npt_day_start(day: date) -> datetime:
    """The instant a Nepali calendar day begins, as an aware datetime (§39.5).

    Date filters name a day in Nepal, not in UTC. The +05:45 offset means a
    UTC-day boundary would move events between days for anyone reading the log
    locally — an event at 05:00 NPT belongs to the previous UTC day.
    """
    return datetime.combine(day, time.min, tzinfo=NEPAL_TZ)


def get_event_by_id(event_id: str) -> AuditEvent | None:
    """A single audit event by id, or None."""
    return AuditEvent.objects.filter(pk=event_id).first()


def get_events(filters: dict[str, Any] | None = None) -> QuerySet[AuditEvent]:
    """Audit events, narrowed by the supported filters.

    Recognised keys: ``app`` (→ app_label), ``action``, ``actor_type``,
    ``actor_id``, ``entity_type``, ``entity_id``, ``success``, a ``fiscal_year``
    range (``YYYY/YY``, Nepali fiscal year), a ``date_from``/``date_to`` range
    (``date`` objects, both bounds inclusive, read as NPT calendar days), a
    ``search`` term matched against ``summary``, and ``order`` (``desc``, the
    default, or ``asc``).

    Callers pass already-validated values — the view layer owns parsing.
    """
    filters = filters or {}
    queryset = AuditEvent.objects.all()

    field_map = {
        "app": "app_label",
        "action": "action",
        "actor_type": "actor_type",
        "actor_id": "actor_id",
        "entity_type": "entity_type",
        "entity_id": "entity_id",
        "success": "success",
    }
    for param, field in field_map.items():
        value = filters.get(param)
        if value not in (None, ""):
            queryset = queryset.filter(**{field: value})

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    date_from = filters.get("date_from")
    if date_from:
        queryset = queryset.filter(created_at__gte=_npt_day_start(date_from))

    date_to = filters.get("date_to")
    if date_to:
        # End-exclusive against the *next* NPT day, so ``date_to`` includes
        # everything that happened on the day the caller actually named.
        queryset = queryset.filter(created_at__lt=_npt_day_start(date_to + timedelta(days=1)))

    search = filters.get("search")
    if search:
        # Served by ``audit_summary_trgm_idx`` (migration 0002).
        queryset = queryset.filter(summary__icontains=search)

    order = filters.get("order")
    return queryset.order_by("created_at" if order == ORDER_ASC else "-created_at")


def get_events_for_entity(
    *,
    entity_type: str,
    entity_id: str,
    app_label: str | None = None,
    order: str = ORDER_DESC,
) -> QuerySet[AuditEvent]:
    """Every event recorded against one record — the canonical record timeline.

    The single query behind every app's ``/history/`` endpoint. It lives here so
    those apps consume audit's selector rather than each rebuilding the same
    filter dict against a table they do not own (§4).

    ``order`` defaults to newest-first, matching how a history pane reads; pass
    ``asc`` for a chronological reconstruction.
    """
    return get_events(
        {
            "app": app_label,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "order": order,
        }
    )


def get_event_facets() -> dict[str, list[str]]:
    """The distinct filter values currently present in the log.

    ``app_label``, ``action`` and ``entity_type`` are open strings owned by the
    emitting apps — there is no enum a client could read them from, so the audit
    UI's filter dropdowns have to be populated from the data itself.
    ``actor_type`` is a closed choice set and is returned in full, including
    values not yet observed, so the filter offers them before the first such
    event exists.

    Query access pattern: one ``DISTINCT`` per column, each over an indexed
    column, no joins. See ``docs/API.md §1.3``.
    """

    def distinct(field: str) -> list[str]:
        values = AuditEvent.objects.order_by().values_list(field, flat=True).distinct()
        return sorted(value for value in values if value)

    return {
        "apps": distinct("app_label"),
        "actions": distinct("action"),
        "entity_types": distinct("entity_type"),
        "actor_types": [choice for choice, _ in ActorType.choices],
    }
