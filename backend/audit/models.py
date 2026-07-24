"""Data models for the audit app.

See ``audit/docs/DATA_CONTRACT.md`` for the authoritative contract.
"""

from __future__ import annotations

import uuid

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from audit.constants import ActorType
from audit.exceptions import ImmutabilityError
from audit.managers import AuditEventQuerySet


class AuditEvent(models.Model):
    """Immutable, append-only record of one important action anywhere in Grandway."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)

    actor_type = models.CharField(max_length=20, choices=ActorType.choices, db_index=True)
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_label = models.CharField(max_length=150, blank=True)

    app_label = models.CharField(max_length=100, db_index=True)
    action = models.CharField(max_length=100, db_index=True)

    entity_type = models.CharField(max_length=100, blank=True)
    entity_id = models.UUIDField(null=True, blank=True)

    reason = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField(default=True)
    summary = models.CharField(max_length=255, blank=True)

    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        db_table = "audit_auditevent"
        verbose_name = "Audit Event"
        verbose_name_plural = "Audit Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            # Supports the ``?search=`` filter, which is a leading-wildcard
            # ``summary__icontains``. A B-tree cannot serve ``LIKE '%…%'``;
            # the trigram index is what keeps the audit log's free-text search
            # viable as the table grows (§39.6, §20).
            GinIndex(fields=["summary"], name="audit_summary_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        outcome = "ok" if self.success else "fail"
        return f"{self.app_label}.{self.action}:{self.actor_label or '-'}:{outcome}"

    def delete(self, *args: object, **kwargs: object) -> None:
        raise ImmutabilityError("AuditEvent is append-only; delete is not allowed.")
