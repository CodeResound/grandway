"""Core Policy Engine endpoint declarations for the audit app (§35).

Run ``python manage.py sync_policy_registry`` after editing, then
``python manage.py validate_policy_engine``.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "audit",
    "app_display_name": "Audit",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "audit_review",
    "category_display_name": "Audit Review",
    "model_key": "event",
    "model_display_name": "Audit Event",
}

POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. List/filter audit events — root (requires only a session, staff-gated in the view).
    {
        **_BASE,
        "endpoint_key": "event-list",
        "permission_key": "audit.event.list",
        "operation_type": "list",
        "display_name": "List Audit Events",
        "description": "List and filter the central audit log (Admin/Superadmin).",
        "http_method": "GET",
        "route_pattern": "/api/v1/audit/events/",
        "view_import_path": "audit.views.AuditEventListView",
        "risk_level": "medium",
        "is_dependency_root": True,
        "dependencies": [],
        "change_summary": "Initial registration of the audit event list endpoint.",
        "change_reason": "audit app Phase 4 (central audit).",
    },
    # 2. Read a single audit event — requires list.
    {
        **_BASE,
        "endpoint_key": "event-read",
        "permission_key": "audit.event.read",
        "operation_type": "read",
        "display_name": "View Audit Event",
        "description": "Retrieve a single audit event by id (Admin/Superadmin).",
        "http_method": "GET",
        "route_pattern": "/api/v1/audit/events/<event_id>/",
        "view_import_path": "audit.views.AuditEventDetailView",
        "risk_level": "low",
        "dependencies": [
            {
                "target_permission_key": "audit.event.list",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Reading one event is meaningful only alongside list access.",
            }
        ],
        "change_summary": "Initial registration of the audit event read endpoint.",
        "change_reason": "audit app Phase 4 (central audit).",
    },
]
