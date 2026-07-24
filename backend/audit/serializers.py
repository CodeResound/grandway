"""Read serializers for the audit app."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.nepal.calendar import to_bs
from rest_framework import serializers

from audit.models import AuditEvent


def _bs(value: datetime | None) -> dict[str, Any] | None:
    """The BS projection of a stored UTC timestamp, or None (§39.4)."""
    return to_bs(value).to_dict() if value else None


class AuditEventSerializer(serializers.ModelSerializer):
    """Read shape for a single audit event (never exposes secrets)."""

    created_at_bs = serializers.SerializerMethodField()

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
            "created_at_bs",
        ]
        read_only_fields = fields

    def get_created_at_bs(self, obj: AuditEvent) -> dict[str, Any] | None:
        return _bs(obj.created_at)


class AuditEventHistorySerializer(serializers.ModelSerializer):
    """One audit event projected as an entry in a single record's history.

    The canonical shape behind every app's ``/history/`` endpoint. Owned here
    rather than redeclared per app: six near-identical copies had already
    drifted apart on whether they exposed ``actor_id``, which made the same
    underlying row look like a different object depending on which record you
    reached it from (§4 — no duplicated serializers across apps).

    Deliberately narrower than ``AuditEventSerializer``: ``app_label`` and
    ``entity_type`` are constant within one record's history, and ``ip_address``
    stays on the central log, which is Admin/Superadmin only.
    """

    created_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "action",
            "actor_type",
            "actor_id",
            "actor_label",
            "summary",
            "reason",
            "changes",
            "metadata",
            "created_at",
            "created_at_bs",
        ]
        read_only_fields = fields

    def get_created_at_bs(self, obj: AuditEvent) -> dict[str, Any] | None:
        return _bs(obj.created_at)


class AuditFacetsSerializer(serializers.Serializer):
    """The distinct filter values present in the log, for the audit UI's dropdowns."""

    apps = serializers.ListField(child=serializers.CharField(), read_only=True)
    actions = serializers.ListField(child=serializers.CharField(), read_only=True)
    entity_types = serializers.ListField(child=serializers.CharField(), read_only=True)
    actor_types = serializers.ListField(child=serializers.CharField(), read_only=True)
