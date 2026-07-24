"""Core Policy Engine endpoint declarations for the document_history app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

Two judgements are recorded here for whoever eventually wires permission-key
enforcement into the request path.

**Risk mirrors ``documents``, because the data is the same data.** A snapshot
holds the same bank statement the working document does. ``snapshot.read`` is
``high`` for the same reason ``documents.document.read`` is: it is the only
endpoint that returns a frozen body.

**``snapshot.recover`` depends on ``documents.document.update``.** It is the one
endpoint in this app that writes into another app's record, and the dependency
edge says so — granting someone the ability to recover a snapshot without the
ability to edit the document it recovers into would be incoherent. The
``permissions`` app enforces strict ``requires`` edges at grant time, so this
edge is what stops that grant being made.

Two models are registered rather than one: a snapshot and a print event are
separate entities (see ``constants.PrintEventType``), and collapsing them would
make ``print_event.list`` read as an action on a snapshot.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "document_history",
    "app_display_name": "Document History",
    "version": "1.0.0",
    "is_internal": False,
    # Shares the ``documents`` category so the two appear together in a
    # permission-management UI — to an operator they are one feature.
    "category_key": "document_management",
    "category_display_name": "Document Management",
}

_SNAPSHOT: dict[str, Any] = {
    **_BASE,
    "model_key": "snapshot",
    "model_display_name": "Document Snapshot",
}

_PRINT_EVENT: dict[str, Any] = {
    **_BASE,
    "model_key": "print_event",
    "model_display_name": "Print Event",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_DOCUMENT_READ = [
    _dep(
        "documents.document.read",
        "History is always scoped to one document, which must be readable first.",
    )
]

_REQUIRES_SNAPSHOT_READ = [
    _dep(
        "document_history.snapshot.read",
        "The snapshot must be readable before it can be acted on.",
    )
]

_PHASE = "document_history app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The version chain. Medium risk: it reveals how often a document was
    #    printed and by whom, without returning any frozen body.
    {
        **_SNAPSHOT,
        "endpoint_key": "snapshot-list",
        "permission_key": "document_history.snapshot.list",
        "operation_type": "list",
        "display_name": "List Document Snapshots",
        "description": "List one document's print snapshots, newest version first. Bodies are omitted.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-history/documents/<document_id>/snapshots/",
        "view_import_path": "document_history.views.SnapshotListCreateView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_DOCUMENT_READ,
        "change_summary": "Initial registration of the snapshot list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Freeze the document. Medium rather than high: it writes a copy of data
    #    the caller must already be able to read, and changes nothing.
    {
        **_SNAPSHOT,
        "endpoint_key": "snapshot-capture",
        "permission_key": "document_history.snapshot.capture",
        "operation_type": "create",
        "display_name": "Capture Document Snapshot",
        "description": "Freeze the document's current body and render context as a new immutable version.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-history/documents/<document_id>/snapshots/",
        "view_import_path": "document_history.views.SnapshotListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep(
                "document_history.snapshot.list",
                "Capturing snapshots requires the ability to list them.",
            )
        ],
        "change_summary": "Initial registration of the snapshot capture endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one snapshot — the only endpoint that returns a frozen body, and
    #    the dependency root for both per-snapshot actions.
    {
        **_SNAPSHOT,
        "endpoint_key": "snapshot-read",
        "permission_key": "document_history.snapshot.read",
        "operation_type": "read",
        "display_name": "View Document Snapshot",
        "description": "Retrieve one frozen snapshot in full. The only endpoint that returns a snapshot body.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-history/snapshots/<snapshot_id>/",
        "view_import_path": "document_history.views.SnapshotDetailView",
        "risk_level": "high",
        "dependencies": [
            _dep(
                "document_history.snapshot.list",
                "Reading a snapshot requires list access to the chain it belongs to.",
            )
        ],
        "change_summary": "Initial registration of the snapshot read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. The timeline — every capture, reprint, and recovery for one document.
    {
        **_PRINT_EVENT,
        "endpoint_key": "print-event-list",
        "permission_key": "document_history.print_event.list",
        "operation_type": "list",
        "display_name": "List Print Events",
        "description": "List one document's print timeline: captures, reprints, and recoveries, newest first.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-history/documents/<document_id>/timeline/",
        "view_import_path": "document_history.views.TimelineView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_DOCUMENT_READ,
        "change_summary": "Initial registration of the print event timeline endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Record that a past snapshot was printed again. Writes an event only.
    {
        **_PRINT_EVENT,
        "endpoint_key": "print-event-reprint",
        "permission_key": "document_history.print_event.reprint",
        "operation_type": "custom",
        "display_name": "Reprint Document Snapshot",
        "description": "Record a reprint of an existing snapshot. Creates a print event, never a new snapshot.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-history/snapshots/<snapshot_id>/reprint/",
        "view_import_path": "document_history.views.SnapshotReprintView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_SNAPSHOT_READ,
        "change_summary": "Initial registration of the snapshot reprint endpoint.",
        "change_reason": _PHASE,
    },
    # 6. The one endpoint that writes into another app's record. High risk, and
    #    the only one carrying a cross-app dependency edge.
    {
        **_SNAPSHOT,
        "endpoint_key": "snapshot-recover",
        "permission_key": "document_history.snapshot.recover",
        "operation_type": "custom",
        "display_name": "Recover Document Snapshot",
        "description": "Restore a frozen body into the working document. The snapshot itself is never altered.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-history/snapshots/<snapshot_id>/recover/",
        "view_import_path": "document_history.views.SnapshotRecoverView",
        "risk_level": "high",
        "dependencies": [
            _dep(
                "document_history.snapshot.read",
                "The snapshot must be readable before its body can be recovered.",
            ),
            _dep(
                "documents.document.update",
                "Recovery writes the frozen body into the working document through the documents app.",
            ),
        ],
        "change_summary": "Initial registration of the snapshot recover endpoint.",
        "change_reason": _PHASE,
    },
]
