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
)
