"""Core Policy Engine endpoint declarations for the clients app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

One model, seven endpoints. Contact numbers have no permission keys of their own
because they have no endpoints — they are replaced wholesale through the client
payload, so ``clients.client.update`` is the right thing to gate them on.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "clients",
    "app_display_name": "Clients",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "client_management",
    "category_display_name": "Client Management",
    "model_key": "client",
    "model_display_name": "Client",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_READ = [_dep("clients.client.read", "The client must be readable before it can be acted on.")]

_PHASE = "clients app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The directory itself — the app's primary screen.
    {
        **_BASE,
        "endpoint_key": "client-list",
        "permission_key": "clients.client.list",
        "operation_type": "list",
        "display_name": "List Clients",
        "description": "Browse the B2B partner directory. Shared — every Admin and Lead Manager may read it.",
        "http_method": "GET",
        "route_pattern": "/api/v1/clients/",
        "view_import_path": "clients.views.ClientListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the client list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Add a partner. Admin only — the directory is shared reference data.
    {
        **_BASE,
        "endpoint_key": "client-create",
        "permission_key": "clients.client.create",
        "operation_type": "create",
        "display_name": "Add Client",
        "description": "Add a partner organization to the directory, with its spokesperson and contact numbers.",
        "http_method": "POST",
        "route_pattern": "/api/v1/clients/",
        "view_import_path": "clients.views.ClientListCreateView",
        "risk_level": "medium",
        "dependencies": [_dep("clients.client.list", "Adding clients requires the ability to list them.")],
        "change_summary": "Initial registration of the client create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one client — the dependency root for the per-client actions.
    {
        **_BASE,
        "endpoint_key": "client-read",
        "permission_key": "clients.client.read",
        "operation_type": "read",
        "display_name": "View Client",
        "description": "Retrieve one client with its full contact details, numbers, and standing.",
        "http_method": "GET",
        "route_pattern": "/api/v1/clients/<client_id>/",
        "view_import_path": "clients.views.ClientDetailView",
        "risk_level": "low",
        "dependencies": [_dep("clients.client.list", "Reading a client requires list access.")],
        "change_summary": "Initial registration of the client read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Correct the directory entry. Standing is out of reach here.
    {
        **_BASE,
        "endpoint_key": "client-update",
        "permission_key": "clients.client.update",
        "operation_type": "update",
        "display_name": "Edit Client",
        "description": "Correct a client's name, spokesperson, contact details, or notes. Standing is unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/clients/<client_id>/",
        "view_import_path": "clients.views.ClientDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the client update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Withdraw from current use. The nearest thing to a delete this app has.
    {
        **_BASE,
        "endpoint_key": "client-retire",
        "permission_key": "clients.client.retire",
        "operation_type": "custom",
        "display_name": "Retire Client",
        "description": "Withdraw a partner from current use, recording why. Nothing is deleted.",
        "http_method": "POST",
        "route_pattern": "/api/v1/clients/<client_id>/retire/",
        "view_import_path": "clients.views.ClientRetireView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the client retire endpoint.",
        "change_reason": _PHASE,
    },
    # 6. Reverse the retirement. Never erases the history of it.
    {
        **_BASE,
        "endpoint_key": "client-restore",
        "permission_key": "clients.client.restore",
        "operation_type": "custom",
        "display_name": "Restore Client",
        "description": "Return a retired partner to current use, clearing the retirement state.",
        "http_method": "POST",
        "route_pattern": "/api/v1/clients/<client_id>/restore/",
        "view_import_path": "clients.views.ClientRestoreView",
        "risk_level": "medium",
        "dependencies": [
            _dep("clients.client.read", "The client must be readable before it can be restored."),
            _dep("clients.client.retire", "Restoring only applies to a client that was retired."),
        ],
        "change_summary": "Initial registration of the client restore endpoint.",
        "change_reason": _PHASE,
    },
    # 7. The client's history, projected from the central audit log.
    {
        **_BASE,
        "endpoint_key": "client-history",
        "permission_key": "clients.client.list_history",
        "operation_type": "list",
        "display_name": "View Client History",
        "description": "List a client's chronological change history from the central audit log.",
        "http_method": "GET",
        "route_pattern": "/api/v1/clients/<client_id>/history/",
        "view_import_path": "clients.views.ClientHistoryView",
        "risk_level": "low",
        "dependencies": _REQUIRES_READ,
        "version": "1.1.0",
        "change_summary": "History entries now carry actor_id, and are serialized by audit's shared shape.",
        "change_reason": (
            "The six per-app history serializers were consolidated into audit's canonical "
            "AuditEventHistorySerializer; three of them, this one included, had omitted actor_id, so "
            "the same audit row looked different depending on which record you reached it from. "
            "Adding the field is backward compatible (§22, §29)."
        ),
    },
]
