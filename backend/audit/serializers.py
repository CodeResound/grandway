"""Read serializers for the audit app."""

from __future__ import annotations

from rest_framework import serializers

from audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    """Read shape for a single audit event (never exposes secrets)."""

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "actor_type",
            "actor_id",
            "actor_label",
            "app_label",
            "action",
            "entity_type",
            "entity_id",
            "reason",
            "source",
            "ip_address",
            "success",
            "summary",
            "changes",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields
