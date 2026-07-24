"""Core Policy Engine endpoint declarations for the uploaded_files app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

**This app contains the first `critical` endpoint in the project.** Every risk
rating here is argued from what the endpoint actually exposes, not from its HTTP
verb:

* ``file.download`` is ``critical`` — it is the only route in Grandway that
  returns an applicant's passport scan, transcript, or bank statement as bytes.
  Nothing else in the system reaches that far. ``documents`` rates its *snapshot
  read* ``high`` for returning a frozen bank statement as JSON; this returns the
  original document itself.
* ``file.upload`` and ``file.replace`` are ``high`` — they put bytes on the
  platform's disk. A replacement additionally supersedes an existing record.
* ``file.verify`` and ``file.archive`` are ``high`` — the two acts that decide
  whether a file is trusted and whether it stays in active use.
* ``file.list`` and ``file.read`` are ``medium``, matching ``documents``: the
  metadata alone reveals which applicants have passports and financial records
  on file, which is disclosure even without the bytes.
* ``file.update`` is ``low`` — it edits a category and a note.

**The dependency graph mirrors the access split, and this is the one place it is
machine-readable.** ``verify``, ``archive``, and ``restore`` are Admin-only in
``access.py``; here they are the endpoints whose forward dependencies run
through ``file.read``. Nothing enforces the split from this file — §9's interim
inline pattern is still what runs — but when the permissions app is wired into
the request path, this graph is what it will read.

One model is registered, not five: a file is one entity that happens to point at
five different owners.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "uploaded_files",
    "app_display_name": "Uploaded Files",
    "model_key": "file",
    "model_display_name": "Uploaded File",
    "version": "1.0.0",
    "is_internal": False,
    # Its own category rather than `document_management`. To an operator these
    # are not the document workspace: a passport scan on an applicant and a
    # transcript on a journey have nothing to do with preparing a bank
    # statement, and the two groups have different access rules.
    "category_key": "file_management",
    "category_display_name": "File Management",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_READ = [_dep("uploaded_files.file.read", "The file must be readable before it can be acted on.")]
_REQUIRES_LIST = [_dep("uploaded_files.file.list", "Acting on files requires the ability to list them.")]

_PHASE = "uploaded_files app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The ledger. Every per-record file panel and the review queue are this
    #    endpoint with a filter, so it is the root of the whole graph.
    {
        **_BASE,
        "endpoint_key": "file-list",
        "permission_key": "uploaded_files.file.list",
        "operation_type": "list",
        "display_name": "List Files",
        "description": (
            "List file records. Filter by owner (applicant, journey, offer, document, snapshot), "
            "category, verification status, archive state, or checksum."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/files/",
        "view_import_path": "uploaded_files.views.FileListUploadView",
        "risk_level": "medium",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the file list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Upload. The first endpoint in the project that writes bytes to disk.
    {
        **_BASE,
        "endpoint_key": "file-upload",
        "permission_key": "uploaded_files.file.upload",
        "operation_type": "create",
        "display_name": "Upload File",
        "description": (
            "Store one file against exactly one business record. Multipart. "
            "Validated for size, extension, and leading bytes; created as pending."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/files/",
        "view_import_path": "uploaded_files.views.FileListUploadView",
        "risk_level": "high",
        "dependencies": _REQUIRES_LIST,
        "change_summary": "Initial registration of the file upload endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one file's metadata — the dependency root for every per-file action.
    {
        **_BASE,
        "endpoint_key": "file-read",
        "permission_key": "uploaded_files.file.read",
        "operation_type": "read",
        "display_name": "View File",
        "description": "Retrieve one file's metadata. Never returns the bytes or the storage path.",
        "http_method": "GET",
        "route_pattern": "/api/v1/files/<file_id>/",
        "view_import_path": "uploaded_files.views.FileDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_LIST,
        "change_summary": "Initial registration of the file read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Edit the two fields a stored file has that can change.
    {
        **_BASE,
        "endpoint_key": "file-update",
        "permission_key": "uploaded_files.file.update",
        "operation_type": "update",
        "display_name": "Edit File",
        "description": "Correct a file's category or notes. Every other field is refused.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/files/<file_id>/",
        "view_import_path": "uploaded_files.views.FileDetailView",
        "risk_level": "low",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the file update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. The bytes. The only route in the project rated `critical`.
    {
        **_BASE,
        "endpoint_key": "file-download",
        "permission_key": "uploaded_files.file.download",
        "operation_type": "custom",
        "display_name": "Download File",
        "description": (
            "Stream the stored bytes as an attachment. The only path from the storage volume to a "
            "client, and the only read in the project that writes an audit event."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/files/<file_id>/download/",
        "view_import_path": "uploaded_files.views.FileDownloadView",
        "risk_level": "critical",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the file download endpoint.",
        "change_reason": _PHASE,
    },
    # 6. The replacement chain, read from any member of it.
    {
        **_BASE,
        "endpoint_key": "file-versions",
        "permission_key": "uploaded_files.file.versions",
        "operation_type": "custom",
        "display_name": "List File Versions",
        "description": "Return the whole replacement chain containing this file, oldest first. Unpaginated.",
        "http_method": "GET",
        "route_pattern": "/api/v1/files/<file_id>/versions/",
        "view_import_path": "uploaded_files.views.FileVersionsView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the file versions endpoint.",
        "change_reason": _PHASE,
    },
    # 7. Replace. Writes a new row and supersedes the old one; deletes nothing.
    {
        **_BASE,
        "endpoint_key": "file-replace",
        "permission_key": "uploaded_files.file.replace",
        "operation_type": "custom",
        "display_name": "Replace File",
        "description": (
            "Supersede this file with a newer one. Multipart. Creates a new record inheriting the "
            "owner and category, starting pending; the predecessor is kept."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/files/<file_id>/replace/",
        "view_import_path": "uploaded_files.views.FileReplaceView",
        "risk_level": "high",
        "dependencies": [
            *_REQUIRES_READ,
            _dep("uploaded_files.file.upload", "Replacing a file is an upload against an existing record."),
        ],
        "change_summary": "Initial registration of the file replace endpoint.",
        "change_reason": _PHASE,
    },
    # 8. The verdict. Admin-only in access.py.
    {
        **_BASE,
        "endpoint_key": "file-verify",
        "permission_key": "uploaded_files.file.verify",
        "operation_type": "custom",
        "display_name": "Review File",
        "description": (
            "Record a verdict on a file: verified or rejected. Rejecting requires a reason. " "Admin authority only."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/files/<file_id>/verify/",
        "view_import_path": "uploaded_files.views.FileReviewView",
        "risk_level": "high",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the file review endpoint.",
        "change_reason": _PHASE,
    },
    # 9. Archive. The nearest thing to a delete this app has, and it deletes
    #    nothing — the bytes stay and the file stays downloadable.
    {
        **_BASE,
        "endpoint_key": "file-archive",
        "permission_key": "uploaded_files.file.archive",
        "operation_type": "custom",
        "display_name": "Archive File",
        "description": (
            "Retire a file from active work. A reason is required. Nothing is deleted and the "
            "version chain is unaffected. Admin authority only."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/files/<file_id>/archive/",
        "view_import_path": "uploaded_files.views.FileArchiveView",
        "risk_level": "high",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the file archive endpoint.",
        "change_reason": _PHASE,
    },
    # 10. Restore. Reverses archival; clears all three archive columns.
    {
        **_BASE,
        "endpoint_key": "file-restore",
        "permission_key": "uploaded_files.file.restore",
        "operation_type": "custom",
        "display_name": "Restore File",
        "description": "Return an archived file to active work. Admin authority only.",
        "http_method": "POST",
        "route_pattern": "/api/v1/files/<file_id>/restore/",
        "view_import_path": "uploaded_files.views.FileRestoreView",
        "risk_level": "medium",
        "dependencies": [
            *_REQUIRES_READ,
            _dep("uploaded_files.file.archive", "Restoring reverses archival, so it presupposes it."),
        ],
        "change_summary": "Initial registration of the file restore endpoint.",
        "change_reason": _PHASE,
    },
]
