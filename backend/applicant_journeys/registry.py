"""Core Policy Engine endpoint declarations for the applicant_journeys app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "applicant_journeys",
    "app_display_name": "Applicant Journeys",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "journey_management",
    "category_display_name": "Journey Management",
    "model_key": "journey",
    "model_display_name": "Applicant Journey",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_READ = [_dep("applicant_journeys.journey.read", "The journey must be readable before it can be acted on.")]

_PHASE = "applicant_journeys app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. List journeys — the operational worklist across all applicants.
    {
        **_BASE,
        "endpoint_key": "journey-list",
        "permission_key": "applicant_journeys.journey.list",
        "operation_type": "list",
        "display_name": "List Journeys",
        "description": "List study objectives across all applicants. Shared, not owner-scoped.",
        "http_method": "GET",
        "route_pattern": "/api/v1/journeys/",
        "view_import_path": "applicant_journeys.views.JourneyListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login", "A session must be established by login before this endpoint is usable."
            )
        ],
        "change_summary": "Initial registration of the journey list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Create a journey. Requires an applicant to attach it to.
    {
        **_BASE,
        "endpoint_key": "journey-create",
        "permission_key": "applicant_journeys.journey.create",
        "operation_type": "create",
        "display_name": "Create Journey",
        "description": "Record a new overseas-study objective for an existing applicant.",
        "http_method": "POST",
        "route_pattern": "/api/v1/journeys/",
        "view_import_path": "applicant_journeys.views.JourneyListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("applicant_journeys.journey.list", "Creating journeys requires the ability to list them."),
            _dep("applicants.applicant.read", "A journey must be attached to an existing applicant."),
        ],
        "change_summary": "Initial registration of the journey create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one journey — the dependency root for the per-journey actions.
    {
        **_BASE,
        "endpoint_key": "journey-read",
        "permission_key": "applicant_journeys.journey.read",
        "operation_type": "read",
        "display_name": "View Journey",
        "description": "Retrieve one journey with its objective details and lifecycle state.",
        "http_method": "GET",
        "route_pattern": "/api/v1/journeys/<journey_id>/",
        "view_import_path": "applicant_journeys.views.JourneyDetailView",
        "risk_level": "low",
        "dependencies": [_dep("applicant_journeys.journey.list", "Reading a journey requires list access.")],
        "change_summary": "Initial registration of the journey read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Correct a journey's objective. Stage is not editable here.
    {
        **_BASE,
        "endpoint_key": "journey-update",
        "permission_key": "applicant_journeys.journey.update",
        "operation_type": "update",
        "display_name": "Edit Journey",
        "description": "Correct destination, level, field, intake, budget, or notes. Stage is unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/journeys/<journey_id>/",
        "view_import_path": "applicant_journeys.views.JourneyDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the journey update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Move between active stages.
    {
        **_BASE,
        "endpoint_key": "journey-change-stage",
        "permission_key": "applicant_journeys.journey.change_stage",
        "operation_type": "custom",
        "display_name": "Change Journey Stage",
        "description": "Move a journey between active stages. Cannot set completed, closed, or deferred.",
        "http_method": "POST",
        "route_pattern": "/api/v1/journeys/<journey_id>/stage/",
        "view_import_path": "applicant_journeys.views.JourneyStageView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the journey stage-change endpoint.",
        "change_reason": _PHASE,
    },
    # 6. Pause to a later intake. Not an outcome; closes nothing.
    {
        **_BASE,
        "endpoint_key": "journey-defer",
        "permission_key": "applicant_journeys.journey.defer",
        "operation_type": "custom",
        "display_name": "Defer Journey",
        "description": "Pause a journey to a later intake, recording the target intake and reason.",
        "http_method": "POST",
        "route_pattern": "/api/v1/journeys/<journey_id>/defer/",
        "view_import_path": "applicant_journeys.views.JourneyDeferView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the journey defer endpoint.",
        "change_reason": _PHASE,
    },
    # 7. End the journey with a mandatory outcome.
    {
        **_BASE,
        "endpoint_key": "journey-close",
        "permission_key": "applicant_journeys.journey.close",
        "operation_type": "custom",
        "display_name": "Close Journey",
        "description": "End a journey with a mandatory outcome. Successful completes it; anything else closes it.",
        "http_method": "POST",
        "route_pattern": "/api/v1/journeys/<journey_id>/close/",
        "view_import_path": "applicant_journeys.views.JourneyCloseView",
        "risk_level": "high",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the journey close endpoint.",
        "change_reason": _PHASE,
    },
    # 8. Reopen. Never erases the history of the closure it undoes.
    {
        **_BASE,
        "endpoint_key": "journey-reopen",
        "permission_key": "applicant_journeys.journey.reopen",
        "operation_type": "custom",
        "display_name": "Reopen Journey",
        "description": "Return a completed, closed, or deferred journey to an active stage.",
        "http_method": "POST",
        "route_pattern": "/api/v1/journeys/<journey_id>/reopen/",
        "view_import_path": "applicant_journeys.views.JourneyReopenView",
        "risk_level": "high",
        "dependencies": [
            _dep("applicant_journeys.journey.read", "The journey must be readable before it can be reopened."),
            _dep(
                "applicant_journeys.journey.close", "Reopening only applies to a journey that was closed or deferred."
            ),
        ],
        "change_summary": "Initial registration of the journey reopen endpoint.",
        "change_reason": _PHASE,
    },
    # 9. The journey's history, projected from the central audit log.
    {
        **_BASE,
        "endpoint_key": "journey-history",
        "permission_key": "applicant_journeys.journey.list_history",
        "operation_type": "list",
        "display_name": "View Journey History",
        "description": "List a journey's chronological action history from the central audit log.",
        "http_method": "GET",
        "route_pattern": "/api/v1/journeys/<journey_id>/history/",
        "view_import_path": "applicant_journeys.views.JourneyHistoryView",
        "risk_level": "low",
        "dependencies": _REQUIRES_READ,
        "change_summary": "Initial registration of the journey history endpoint.",
        "change_reason": _PHASE,
    },
]
