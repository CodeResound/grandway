"""Core Policy Engine endpoint declarations for the documents app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

Every endpoint here carries a higher ``risk_level`` than its equivalent in other
apps. A document body may hold an applicant's bank balance, account number, and
full transaction history; even the plain list endpoint is rated ``medium``
rather than ``low`` because it exposes who has which financial documents on
file. The registry is where that judgement is recorded for whoever eventually
wires permission-key enforcement into the request path.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "documents",
    "app_display_name": "Documents",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "document_management",
    "category_display_name": "Document Management",
    "model_key": "document",
    "model_display_name": "Document",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_READ = [_dep("documents.document.read", "The document must be readable before it can be acted on.")]

_PHASE = "documents app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The worklist. Medium risk: it reveals which applicants have financial
    #    documents on file, even without returning the bodies.
    {
        **_BASE,
        "endpoint_key": "document-list",
        "permission_key": "documents.document.list",
        "operation_type": "list",
        "display_name": "List Documents",
        "description": "List document working records across applicants and standalone documents. Admin only.",
        "http_method": "GET",
        "route_pattern": "/api/v1/documents/",
        "view_import_path": "documents.views.DocumentListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the document list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Open a new working record.
    {
        **_BASE,
        "endpoint_key": "document-create",
        "permission_key": "documents.document.create",
        "operation_type": "create",
        "display_name": "Create Document",
        "description": "Open a new editable document against an applicant, or as a standalone record.",
        "http_method": "POST",
        "route_pattern": "/api/v1/documents/",
        "view_import_path": "documents.views.DocumentListCreateView",
        "risk_level": "medium",
        "dependencies": [_dep("documents.document.list", "Creating documents requires the ability to list them.")],
        "change_summary": "Initial registration of the document create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. The landing table — applicants with live document work.
    {
        **_BASE,
        "endpoint_key": "document-workspaces",
        "permission_key": "documents.document.list_workspaces",
        "operation_type": "list",
        "display_name": "List Document Workspaces",
        "description": "List applicants with live documents, each with a count and the most recent edit.",
        "http_method": "GET",
        "route_pattern": "/api/v1/documents/workspaces/",
        "view_import_path": "documents.views.WorkspaceListView",
        "risk_level": "medium",
        "dependencies": [_dep("documents.document.list", "The workspace summary is an aggregate of the list.")],
        "change_summary": "Initial registration of the document workspaces endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Read one document — the only endpoint that returns a body, and the
    #    dependency root for every per-document action.
    {
        **_BASE,
        "endpoint_key": "document-read",
        "permission_key": "documents.document.read",
        "operation_type": "read",
        "display_name": "View Document",
        "description": "Retrieve one document including its full body. The only endpoint that returns content.",
        "http_method": "GET",
        "route_pattern": "/api/v1/documents/<document_id>/",
        "view_import_path": "documents.views.DocumentDetailView",
        "risk_level": "high",
        "dependencies": [_dep("documents.document.list", "Reading a document requires list access.")],
        "change_summary": "Initial registration of the document read endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Save the workspace. High risk: this is the write path for the body.
    {
        **_BASE,
        "endpoint_key": "document-update",
        "permission_key": "documents.document.update",
        "operation_type": "update",
        "display_name": "Edit Document",
        "description": "Save the workspace — label, body, notes. Owner, family, template, and status are unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/documents/<document_id>/",
        "view_import_path": "documents.views.DocumentDetailView",
        "risk_level": "high",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the document update endpoint.",
        "change_reason": _PHASE,
    },
    # 6. Move between the two working statuses.
    {
        **_BASE,
        "endpoint_key": "document-change-status",
        "permission_key": "documents.document.change_status",
        "operation_type": "custom",
        "display_name": "Change Document Status",
        "description": "Move a document between draft and ready. Cannot set archived.",
        "http_method": "POST",
        "route_pattern": "/api/v1/documents/<document_id>/status/",
        "view_import_path": "documents.views.DocumentStatusView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the document status endpoint.",
        "change_reason": _PHASE,
    },
    # 7. Retire from active work. The nearest thing to a delete this app has.
    {
        **_BASE,
        "endpoint_key": "document-archive",
        "permission_key": "documents.document.archive",
        "operation_type": "custom",
        "display_name": "Archive Document",
        "description": "Retire a document from active work with a mandatory reason. Nothing is deleted.",
        "http_method": "POST",
        "route_pattern": "/api/v1/documents/<document_id>/archive/",
        "view_import_path": "documents.views.DocumentArchiveView",
        "risk_level": "high",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the document archive endpoint.",
        "change_reason": _PHASE,
    },
    # 8. Reverse the archive. Never erases the history of it.
    {
        **_BASE,
        "endpoint_key": "document-restore",
        "permission_key": "documents.document.restore",
        "operation_type": "custom",
        "display_name": "Restore Document",
        "description": "Return an archived document to draft so it can be edited again.",
        "http_method": "POST",
        "route_pattern": "/api/v1/documents/<document_id>/restore/",
        "view_import_path": "documents.views.DocumentRestoreView",
        "risk_level": "high",
        "dependencies": [
            _dep("documents.document.read", "The document must be readable before it can be restored."),
            _dep("documents.document.archive", "Restoring only applies to a document that was archived."),
        ],
        "change_summary": "Initial registration of the document restore endpoint.",
        "change_reason": _PHASE,
    },
    # 9. The document's history. Records that the body changed, never what it said.
    {
        **_BASE,
        "endpoint_key": "document-history",
        "permission_key": "documents.document.list_history",
        "operation_type": "list",
        "display_name": "View Document History",
        "description": "List a document's chronological history. Body changes appear as a marker, not as content.",
        "http_method": "GET",
        "route_pattern": "/api/v1/documents/<document_id>/history/",
        "view_import_path": "documents.views.DocumentHistoryView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "version": "1.1.0",
        "change_summary": "History entries now carry actor_id, and are serialized by audit's shared shape.",
        "change_reason": (
            "The six per-app history serializers were consolidated into audit's canonical "
            "AuditEventHistorySerializer; three of them, this one included, had omitted actor_id, so "
            "the same audit row looked different depending on which record you reached it from. "
            "Adding the field is backward compatible (§22, §29). Body content is still never "
            "included — only the fact that the body changed."
        ),
    },
]
