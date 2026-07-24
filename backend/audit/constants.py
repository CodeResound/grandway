"""Enums and error codes for the audit app."""

from django.db import models


class ActorType(models.TextChoices):
    SUPERADMIN = "superadmin", "Superadmin"
    ADMIN = "admin", "Admin"
    LEAD_MANAGER = "lead_manager", "Lead Manager"
    SYSTEM = "system", "System"
    AI = "ai", "AI"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the audit app (§7)."""

    EVENT_NOT_FOUND = "AUDIT_EVENT_NOT_FOUND"


# Query params supported by the event list endpoint.
LIST_FILTER_PARAMS = (
    "app",
    "action",
    "actor_type",
    "actor_id",
    "entity_type",
    "entity_id",
    "success",
    "fiscal_year",
    "search",
    "date_from",
    "date_to",
    "order",
)

#: Shortest accepted ``?search=`` term. One character matches nearly every row,
#: which costs a scan and tells the reader nothing.
SEARCH_MIN_LENGTH = 2

#: Accepted ``?order=`` values. ``desc`` (newest first) is the log's default;
#: ``asc`` serves the record-timeline flow, which reads oldest to newest and
#: cannot be produced by reversing a page client-side.
ORDER_DESC = "desc"
ORDER_ASC = "asc"
ORDER_CHOICES = (ORDER_DESC, ORDER_ASC)

#: Date format accepted by ``?date_from=`` / ``?date_to=``. Both bounds name a
#: calendar day in Nepal Standard Time (§39.5), not a UTC day.
DATE_FILTER_FORMAT = "%Y-%m-%d"
