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
        "description": "List document working records across applicants and standalone documents; archived ones only on request. Admin only.",
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
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.1.0",
        "change_summary": "Archived documents are hidden unless status=archived or include_archived=true.",
        "change_reason": (
            "Removed (archived) documents kept coming back in an applicant's list, so users believed "
            "remove did not work. In-place default-filter change on /api/v1/ approved by the product "
            "owner 2026-10-29 (§29); archived documents stay reachable through both parameters."
        ),
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
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.1.0",
        "change_summary": "Accepts template_version; validates student-certificate content keys.",
        "change_reason": (
            "The frontend needs the layout version stored per document (Woda letters moved to layout 2) "
            "and asked for the expanded student-certificate form to be checked. Additive: template_version "
            "defaults to 1; certificate checks are lenient (nothing required, unknown keys kept); other "
            "templates unchanged. Failures use the existing DOCUMENTS_CONTENT_INVALID with a new "
            "details.fields map."
        ),
    },
    # 3. The landing table — applicants with live document work.
    {
        **_BASE,
        "endpoint_key": "document-workspaces",
        "permission_key": "documents.document.list_workspaces",
        "operation_type": "list",
        "display_name": "List Document Workspaces",
        "description": "List applicants with documents, each with live and archived counts and the most recent edit.",
        "http_method": "GET",
        "route_pattern": "/api/v1/documents/workspaces/",
        "view_import_path": "documents.views.WorkspaceListView",
        "risk_level": "medium",
        "dependencies": [_dep("documents.document.list", "The workspace summary is an aggregate of the list.")],
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.1.0",
        "change_summary": "Adds archived_count; applicants whose documents are all archived keep a row.",
        "change_reason": (
            "Removed documents must stay reachable from the workspace screen. Additive field; the row set "
            "widens to applicants with only archived documents (document_count 0)."
        ),
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
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.1.0",
        "change_summary": "Response gains template_version.",
        "change_reason": ("The frontend renders with the layout the document was authored for. Additive field (§22)."),
    },
    # 5. Save the workspace. High risk: this is the write path for the body.
    {
        **_BASE,
        "endpoint_key": "document-update",
        "permission_key": "documents.document.update",
        "operation_type": "update",
        "display_name": "Edit Document",
        "description": "Save the workspace — label, body, notes, layout version. Owner, family, template, and status are unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/documents/<document_id>/",
        "view_import_path": "documents.views.DocumentDetailView",
        "risk_level": "high",
        "dependencies": _REQUIRES_READ,
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.1.0",
        "change_summary": "Accepts template_version; validates student-certificate content keys.",
        "change_reason": (
            "As for create. template_version is PATCH-able like the label; archived documents stay frozen. "
            "status_before_archive is rejected like the other status fields."
        ),
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
        "version": "1.1.0",
        "change_summary": "Moving a document to ready now raises a document_ready notification to the other Admins.",
        "change_reason": "Document notifications (frontend updates.md §4, 2026-10-29). Additive side effect.",
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
        "description": "Return an archived document to the status it held before archiving (draft if unknown).",
        "http_method": "POST",
        "route_pattern": "/api/v1/documents/<document_id>/restore/",
        "view_import_path": "documents.views.DocumentRestoreView",
        "risk_level": "high",
        "dependencies": [
            _dep("documents.document.read", "The document must be readable before it can be restored."),
            _dep("documents.document.archive", "Restoring only applies to a document that was archived."),
        ],
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.1.0",
        "change_summary": "Restores the status held before archiving; accepts an optional reason.",
        "change_reason": (
            "Always returning draft demoted finished documents, and read to users as the restore not working. "
            "Documents archived before the prior status was stored still return draft. Optional reason is "
            "recorded on the audit event. Same route, same codes."
        ),
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
    # --- 2026-10-29: document prefill -------------------------------------------
    {
        **_BASE,
        "model_key": "document_prefill",
        "model_display_name": "Document Prefill",
        "endpoint_key": "document-prefill",
        "permission_key": "documents.prefill.read",
        "operation_type": "read",
        "display_name": "Read Document Prefill",
        "description": (
            "The applicant's names, identity numbers, addresses, parents and grandparents, education, "
            "language tests, and current photo, shaped for document forms. Admin only; read-only."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/documents/prefill/<applicant_id>/",
        "view_import_path": "documents.views.DocumentPrefillView",
        "risk_level": "high",
        "dependencies": [
            _dep("documents.document.list", "Prefill serves the document workspace."),
            _dep("applicants.applicant.read", "Prefill is a projection of the applicant record."),
        ],
        "change_summary": "Initial registration of the document prefill endpoint.",
        "change_reason": "Typed prefill for Woda letters and certificates (frontend updates.md §7.2, 2026-10-29).",
    },
]
