"""Read-only query logic for the audit app (no side effects)."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from audit.models import AuditEvent


def get_event_by_id(event_id: str) -> AuditEvent | None:
    """A single audit event by id, or None."""
    return AuditEvent.objects.filter(pk=event_id).first()


def get_events(filters: dict[str, Any] | None = None) -> QuerySet[AuditEvent]:
    """Audit events, newest first, narrowed by the supported filters.

    Recognised keys: ``app`` (→ app_label), ``action``, ``actor_type``,
    ``actor_id``, ``entity_type``, ``entity_id``, ``success``, and a
    ``fiscal_year`` range (``YYYY/YY``, Nepali fiscal year).
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

    return queryset.order_by("-created_at")
