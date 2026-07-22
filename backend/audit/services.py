"""Business logic for the audit app.

The single write path for the central audit log. Other apps call
``record_event`` to append one immutable event; they never write the table
directly. No secrets or full record contents may be passed in (§17).
"""

from __future__ import annotations

from typing import Any

from audit.constants import ActorType
from audit.models import AuditEvent


def record_event(
    *,
    app_label: str,
    action: str,
    actor_type: str = ActorType.SYSTEM,
    actor_id: str | None = None,
    actor_label: str = "",
    entity_type: str = "",
    entity_id: str | None = None,
    reason: str = "",
    source: str = "",
    ip_address: str | None = None,
    success: bool = True,
    summary: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one immutable audit event. Never pass secrets in any field."""
    return AuditEvent.objects.create(
        app_label=app_label[:100],
        action=action[:100],
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label[:150],
        entity_type=entity_type[:100],
        entity_id=entity_id,
        reason=reason[:255],
        source=source[:100],
        ip_address=ip_address,
        success=success,
        summary=summary[:255],
        changes=changes or {},
        metadata=metadata or {},
    )
