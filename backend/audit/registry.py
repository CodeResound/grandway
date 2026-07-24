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
        "description": "List, search, and filter the central audit log (Admin/Superadmin).",
        "http_method": "GET",
        "route_pattern": "/api/v1/audit/events/",
        "view_import_path": "audit.views.AuditEventListView",
        "risk_level": "medium",
        "is_dependency_root": True,
        "dependencies": [],
        "version": "1.1.0",
        "change_summary": (
            "Added ?search=, ?date_from=, ?date_to= and ?order= filters; responses now carry created_at_bs."
        ),
        "change_reason": (
            "Closes the read-side gaps between concepts/audit.txt's audit-log screen and the shipped "
            "endpoint: free-text search, an arbitrary date range, chronological ordering for the "
            "record-timeline flow, and the BS date the UI displays (§39.4). Backward compatible — "
            "every new filter is optional and created_at_bs is additive (§22, §29)."
        ),
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
        "version": "1.1.0",
        "change_summary": "Response now carries created_at_bs alongside created_at.",
        "change_reason": (
            "The event-detail screen shows the event time in BS as well as Gregorian (§39.4); the "
            "field is additive and breaks no existing consumer (§22, §29)."
        ),
    },
    # 3. Distinct filter values for the audit log UI — requires list.
    {
        **_BASE,
        "endpoint_key": "event-facets",
        "permission_key": "audit.event.facets",
        "operation_type": "custom",
        "display_name": "List Audit Filter Values",
        "description": (
            "Return the distinct app, action, entity type, and actor type values present in the "
            "audit log, for populating the log screen's filter controls (Admin/Superadmin)."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/audit/events/facets/",
        "view_import_path": "audit.views.AuditEventFacetsView",
        "risk_level": "low",
        "dependencies": [
            {
                "target_permission_key": "audit.event.list",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Filter values exist only to narrow the list; they are useless without it.",
            }
        ],
        "change_summary": "Initial registration of the audit filter-values endpoint.",
        "change_reason": (
            "action, app_label and entity_type are open strings owned by the emitting apps, so no "
            "enum exists for a client to read them from; the audit-log screen's filter dropdowns "
            "have to be populated from the data itself."
        ),
    },
]
