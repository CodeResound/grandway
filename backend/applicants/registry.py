"""Core Policy Engine endpoint declarations for the applicants app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "applicants",
    "app_display_name": "Applicants",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "applicant_management",
    "category_display_name": "Applicant Management",
    "model_key": "applicant",
    "model_display_name": "Applicant",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_READ = [_dep("applicants.applicant.read", "The applicant must be readable before it can be acted on.")]

_PHASE = "applicants app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. List applicants — shared across the consultancy, not owner-scoped.
    {
        **_BASE,
        "endpoint_key": "applicant-list",
        "permission_key": "applicants.applicant.list",
        "operation_type": "list",
        "display_name": "List Applicants",
        "description": (
            "List every applicant. Shared across the consultancy — not owner-scoped. "
            "Searchable by name, email, contact number, and passport number, and filterable "
            "by destination country and journey stage."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/applicants/",
        "view_import_path": "applicants.views.ApplicantListCreateView",
        "risk_level": "low",
        # The route and method are unchanged; the contract behind them is not.
        # A version bump appends a record — it never edits the 1.0.0 one (§35 item 10).
        "dependencies": [
            _dep(
                "authenticate.session.login", "A session must be established by login before this endpoint is usable."
            ),
            _dep(
                "applicant_journeys.journey.list",
                "The country and journey-stage filters resolve through the applicant's journeys, "
                "and the response projects each journey's destination.",
            ),
        ],
        "version": "1.2.0",
        "change_summary": "Rows add assigned_to (UserBrief or null); new filter ?assigned_to=me|none|<user id>.",
        "change_reason": "Optional applicant assignment for personalised notifications (frontend updates.md §4, 2026-10-29). Additive.",
    },
    # 2. Create an applicant directly, with no preceding lead. Admin only.
    {
        **_BASE,
        "endpoint_key": "applicant-create",
        "permission_key": "applicants.applicant.create",
        "operation_type": "create",
        "display_name": "Create Applicant",
        "description": "Create an applicant directly, with no preceding lead. Admin only.",
        "http_method": "POST",
        "route_pattern": "/api/v1/applicants/",
        "view_import_path": "applicants.views.ApplicantListCreateView",
        "risk_level": "high",
        "dependencies": [_dep("applicants.applicant.list", "Creating applicants requires the ability to list them.")],
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.2.0",
        "change_summary": "Detail shape adds assigned_to. Conversion assigns the lead's owner.",
        "change_reason": "Optional applicant assignment for personalised notifications (frontend updates.md §4, 2026-10-29). Additive.",
    },
    # 3. Read one applicant — the dependency root for the per-applicant actions.
    {
        **_BASE,
        "endpoint_key": "applicant-read",
        "permission_key": "applicants.applicant.read",
        "operation_type": "read",
        "display_name": "View Applicant",
        "description": "Retrieve one applicant with contacts, addresses, passport, family, and emergency contacts.",
        "http_method": "GET",
        "route_pattern": "/api/v1/applicants/<applicant_id>/",
        "view_import_path": "applicants.views.ApplicantDetailView",
        "risk_level": "low",
        "dependencies": [_dep("applicants.applicant.list", "Reading an applicant requires list access.")],
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.2.0",
        "change_summary": "Detail shape adds assigned_to (UserBrief or null).",
        "change_reason": "Optional applicant assignment for personalised notifications (frontend updates.md §4, 2026-10-29). Additive.",
    },
    # 4. Correct an applicant's information. Status is not editable here.
    {
        **_BASE,
        "endpoint_key": "applicant-update",
        "permission_key": "applicants.applicant.update",
        "operation_type": "update",
        "display_name": "Edit Applicant",
        "description": "Correct identity, contact, address, passport, family, or emergency-contact information.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/applicants/<applicant_id>/",
        "view_import_path": "applicants.views.ApplicantDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.2.0",
        "change_summary": "Detail shape adds assigned_to; assignment itself is not writable here (POST /assign/).",
        "change_reason": "Optional applicant assignment for personalised notifications (frontend updates.md §4, 2026-10-29). Additive.",
    },
    # 5. Set the applicant's standing. Never changed automatically by a journey.
    {
        **_BASE,
        "endpoint_key": "applicant-change-status",
        "permission_key": "applicants.applicant.change_status",
        "operation_type": "custom",
        "display_name": "Change Applicant Status",
        "description": "Set the applicant's standing: active, dormant, or archived. Always manual.",
        "http_method": "POST",
        "route_pattern": "/api/v1/applicants/<applicant_id>/status/",
        "view_import_path": "applicants.views.ApplicantStatusView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        # Route and method unchanged; a version bump appends a record (§35 item 10).
        "version": "1.2.0",
        "change_summary": "Detail shape adds assigned_to; a status change now raises an applicant_status_changed notification.",
        "change_reason": "Notifications for applicant status (frontend updates.md §4, 2026-10-29). Additive side effect.",
    },
    # 6. The applicant's history, projected from the central audit log.
    {
        **_BASE,
        "endpoint_key": "applicant-history",
        "permission_key": "applicants.applicant.list_history",
        "operation_type": "list",
        "display_name": "View Applicant History",
        "description": "List an applicant's chronological change history from the central audit log.",
        "http_method": "GET",
        "route_pattern": "/api/v1/applicants/<applicant_id>/history/",
        "view_import_path": "applicants.views.ApplicantHistoryView",
        "risk_level": "low",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the applicant history endpoint.",
        "change_reason": _PHASE,
    },
    # --- 2026-10-29: restore and notes ----------------------------------------
    # 7. Restore an archived applicant to the status held before. Admin only.
    {
        **_BASE,
        "endpoint_key": "applicant-restore",
        "permission_key": "applicants.applicant.restore",
        "operation_type": "custom",
        "display_name": "Restore Applicant",
        "description": "Un-archive an applicant back to the status held before archiving. Admin only.",
        "http_method": "POST",
        "route_pattern": "/api/v1/applicants/<applicant_id>/restore/",
        "view_import_path": "applicants.views.ApplicantRestoreView",
        "risk_level": "medium",
        "dependencies": [
            _dep("applicants.applicant.read", "The applicant must be readable before it can be restored."),
            _dep(
                "applicants.applicant.change_status", "Restoring only applies to an applicant archived through status."
            ),
        ],
        "version": "1.1.0",
        "change_summary": "Detail shape adds assigned_to; a restore now raises an applicant_restored notification.",
        "change_reason": "Notifications for applicant status (frontend updates.md §4, 2026-10-29). Additive side effect.",
    },
    # --- 2026-10-29: optional assignment (Phase 5) ----------------------------
    # 7a. Set or clear who is notified about an applicant. Routing only.
    {
        **_BASE,
        "endpoint_key": "applicant-assign",
        "permission_key": "applicants.applicant.assign",
        "operation_type": "custom",
        "display_name": "Assign Applicant",
        "description": (
            "Set or clear the staff member notified about an applicant. Admins assign anyone; a Lead Manager "
            "may only take an unassigned applicant or release their own. Never changes who can see the file."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/applicants/<applicant_id>/assign/",
        "view_import_path": "applicants.views.ApplicantAssignView",
        "risk_level": "medium",
        "dependencies": [
            _dep("applicants.applicant.read", "The applicant must be readable before it can be assigned."),
        ],
        "change_summary": "Initial registration of the applicant assign endpoint.",
        "change_reason": "Optional applicant assignment for personalised notifications (frontend updates.md §4, 2026-10-29).",
    },
    # 8. List an applicant's notes.
    {
        **_BASE,
        "model_key": "applicant_note",
        "model_display_name": "Applicant Note",
        "endpoint_key": "applicant-note-list",
        "permission_key": "applicants.note.list",
        "operation_type": "list",
        "display_name": "List Applicant Notes",
        "description": "List an applicant's live notes, most recent noted_at first, with per-category counts.",
        "http_method": "GET",
        "route_pattern": "/api/v1/applicants/<applicant_id>/notes/",
        "view_import_path": "applicants.views.ApplicantNoteListCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the applicant-note list endpoint.",
        "change_reason": "Applicant notes (frontend updates.md §2, 2026-10-29).",
    },
    # 9. Write a note (categorised, backdatable).
    {
        **_BASE,
        "model_key": "applicant_note",
        "model_display_name": "Applicant Note",
        "endpoint_key": "applicant-note-create",
        "permission_key": "applicants.note.create",
        "operation_type": "create",
        "display_name": "Add Applicant Note",
        "description": "Write a general or visit note on an applicant, optionally backdated.",
        "http_method": "POST",
        "route_pattern": "/api/v1/applicants/<applicant_id>/notes/",
        "view_import_path": "applicants.views.ApplicantNoteListCreateView",
        "risk_level": "low",
        "dependencies": [_dep("applicants.note.list", "Adding a note requires the ability to read the notes.")],
        "version": "1.1.0",
        "change_summary": "A visit note now raises a visit_note_added notification.",
        "change_reason": "Visit-note notifications (frontend updates.md §4, 2026-10-29). Additive side effect.",
    },
    # 10. Correct a note. Author or Admin.
    {
        **_BASE,
        "model_key": "applicant_note",
        "model_display_name": "Applicant Note",
        "endpoint_key": "applicant-note-update",
        "permission_key": "applicants.note.update",
        "operation_type": "update",
        "display_name": "Edit Applicant Note",
        "description": "Correct a note's category, text, or noted_at. The author or an Admin only; audited.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/applicants/<applicant_id>/notes/<note_id>/",
        "view_import_path": "applicants.views.ApplicantNoteDetailView",
        "risk_level": "medium",
        "dependencies": [_dep("applicants.note.list", "A note must be listed before it can be edited.")],
        "change_summary": "Initial registration of the applicant-note update endpoint.",
        "change_reason": "Applicant notes (frontend updates.md §2, 2026-10-29).",
    },
    # 11. Remove a note (soft). Author or Admin.
    {
        **_BASE,
        "model_key": "applicant_note",
        "model_display_name": "Applicant Note",
        "endpoint_key": "applicant-note-delete",
        "permission_key": "applicants.note.delete",
        "operation_type": "delete",
        "display_name": "Delete Applicant Note",
        "description": "Soft-delete a note: it leaves the feed, the row and its audit trail stay. Author or Admin.",
        "http_method": "DELETE",
        "route_pattern": "/api/v1/applicants/<applicant_id>/notes/<note_id>/",
        "view_import_path": "applicants.views.ApplicantNoteDetailView",
        "risk_level": "medium",
        "dependencies": [_dep("applicants.note.list", "A note must be listed before it can be deleted.")],
        "change_summary": "Initial registration of the applicant-note delete endpoint.",
        "change_reason": "Applicant notes (frontend updates.md §2, 2026-10-29).",
    },
]
