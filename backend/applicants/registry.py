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
        "version": "1.1.0",
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
        "change_summary": (
            "Widened search to email, contact number, and passport number; added relevance ordering; "
            "added the country, country_code, and journey_stage filters; added the destinations "
            "response field."
        ),
        "change_reason": (
            "Staff could not find an applicant by destination country at all — the destination lives on "
            "the journey, not the applicant — and search matched names only. Backward compatible: "
            "every previous filter behaves unchanged, no field was removed or renamed, and the new "
            "response field is additive (§22, §29)."
        ),
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
        "change_summary": "Initial registration of the direct applicant-create endpoint.",
        "change_reason": _PHASE,
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
        "change_summary": "Initial registration of the applicant read endpoint.",
        "change_reason": _PHASE,
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
        "change_summary": "Initial registration of the applicant update endpoint.",
        "change_reason": _PHASE,
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
        "change_summary": "Initial registration of the applicant status endpoint.",
        "change_reason": _PHASE,
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
]
