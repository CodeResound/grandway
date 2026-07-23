"""Core Policy Engine endpoint declarations for the leads app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.
"""

from typing import Any

_LEAD: dict[str, Any] = {
    "app_key": "leads",
    "app_display_name": "Leads",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "lead_management",
    "category_display_name": "Lead Management",
    "model_key": "lead",
    "model_display_name": "Lead",
}

# Source and loss-reason administration is a separate UI concern from working a
# lead, so it gets its own permission category.
_CONFIG: dict[str, Any] = {
    "app_key": "leads",
    "app_display_name": "Leads",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "lead_configuration",
    "category_display_name": "Lead Configuration",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_LOGIN = [
    _dep("authenticate.session.login", "A session must be established by login before this endpoint is usable.")
]

_REQUIRES_LEAD_READ = [_dep("leads.lead.read", "The lead must be readable before it can be acted on.")]

_PHASE_1 = "leads app Phase 1 (reference configuration)."
_PHASE_2 = "leads app Phase 2 (lead core)."
_PHASE_3 = "leads app Phase 3 (lifecycle)."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # --- Phase 1: reference configuration ----------------------------------
    # 1. List lead sources — the root of this app's dependency chain: a lead
    #    cannot be created without choosing a source, so every other lead
    #    endpoint ultimately depends on being able to read this list.
    {
        **_CONFIG,
        "model_key": "lead_source",
        "model_display_name": "Lead Source",
        "endpoint_key": "source-list",
        "permission_key": "leads.source.list",
        "operation_type": "list",
        "display_name": "List Lead Sources",
        "description": "List the configurable lead sources a lead may be attributed to.",
        "http_method": "GET",
        "route_pattern": "/api/v1/leads/sources/",
        "view_import_path": "leads.views.LeadSourceListCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the lead-source list endpoint.",
        "change_reason": _PHASE_1,
    },
    # 2. Create a lead source (Admin).
    {
        **_CONFIG,
        "model_key": "lead_source",
        "model_display_name": "Lead Source",
        "endpoint_key": "source-create",
        "permission_key": "leads.source.create",
        "operation_type": "create",
        "display_name": "Create Lead Source",
        "description": "Add a configurable lead source. Admin only.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/sources/",
        "view_import_path": "leads.views.LeadSourceListCreateView",
        "risk_level": "medium",
        "dependencies": [_dep("leads.source.list", "Managing sources requires the ability to list them.")],
        "change_summary": "Initial registration of the lead-source create endpoint.",
        "change_reason": _PHASE_1,
    },
    # 3. Edit or deactivate a lead source (Admin). Sources are never deleted.
    {
        **_CONFIG,
        "model_key": "lead_source",
        "model_display_name": "Lead Source",
        "endpoint_key": "source-update",
        "permission_key": "leads.source.update",
        "operation_type": "update",
        "display_name": "Edit Lead Source",
        "description": "Edit or deactivate a lead source. Admin only; entries are never deleted.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/leads/sources/<source_id>/",
        "view_import_path": "leads.views.LeadSourceDetailView",
        "risk_level": "medium",
        "dependencies": [_dep("leads.source.list", "Editing a source requires the ability to list them.")],
        "change_summary": "Initial registration of the lead-source update endpoint.",
        "change_reason": _PHASE_1,
    },
    # 4. List loss reasons.
    {
        **_CONFIG,
        "model_key": "loss_reason",
        "model_display_name": "Loss Reason",
        "endpoint_key": "loss-reason-list",
        "permission_key": "leads.loss_reason.list",
        "operation_type": "list",
        "display_name": "List Loss Reasons",
        "description": "List the configurable reasons a lead may be closed with.",
        "http_method": "GET",
        "route_pattern": "/api/v1/leads/loss-reasons/",
        "view_import_path": "leads.views.LossReasonListCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the loss-reason list endpoint.",
        "change_reason": _PHASE_1,
    },
    # 5. Create a loss reason (Admin).
    {
        **_CONFIG,
        "model_key": "loss_reason",
        "model_display_name": "Loss Reason",
        "endpoint_key": "loss-reason-create",
        "permission_key": "leads.loss_reason.create",
        "operation_type": "create",
        "display_name": "Create Loss Reason",
        "description": "Add a configurable loss reason. Admin only.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/loss-reasons/",
        "view_import_path": "leads.views.LossReasonListCreateView",
        "risk_level": "medium",
        "dependencies": [_dep("leads.loss_reason.list", "Managing loss reasons requires the ability to list them.")],
        "change_summary": "Initial registration of the loss-reason create endpoint.",
        "change_reason": _PHASE_1,
    },
    # 6. Edit or deactivate a loss reason (Admin).
    {
        **_CONFIG,
        "model_key": "loss_reason",
        "model_display_name": "Loss Reason",
        "endpoint_key": "loss-reason-update",
        "permission_key": "leads.loss_reason.update",
        "operation_type": "update",
        "display_name": "Edit Loss Reason",
        "description": "Edit or deactivate a loss reason. Admin only; entries are never deleted.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/leads/loss-reasons/<reason_id>/",
        "view_import_path": "leads.views.LossReasonDetailView",
        "risk_level": "medium",
        "dependencies": [_dep("leads.loss_reason.list", "Editing a loss reason requires the ability to list them.")],
        "change_summary": "Initial registration of the loss-reason update endpoint.",
        "change_reason": _PHASE_1,
    },
    # --- Phase 2: lead core -------------------------------------------------
    # 7. List leads — owner-scoped for a Lead Manager, unrestricted for an Admin.
    {
        **_LEAD,
        "endpoint_key": "lead-list",
        "permission_key": "leads.lead.list",
        "operation_type": "list",
        "display_name": "List Leads",
        "description": "List leads in the caller's scope: own leads for a Lead Manager, all for an Admin.",
        "http_method": "GET",
        "route_pattern": "/api/v1/leads/",
        "view_import_path": "leads.views.LeadListCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LOGIN,
        "change_summary": "Initial registration of the lead list endpoint.",
        "change_reason": _PHASE_2,
    },
    # 8. Create a lead. Requires a source, hence the dependency on source.list.
    {
        **_LEAD,
        "endpoint_key": "lead-create",
        "permission_key": "leads.lead.create",
        "operation_type": "create",
        "display_name": "Create Lead",
        "description": "Record a new enquiry. The creator owns the lead permanently.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/",
        "view_import_path": "leads.views.LeadListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("leads.lead.list", "Creating leads requires the ability to list them."),
            _dep("leads.source.list", "A lead must be attributed to a source chosen from the source list."),
        ],
        "change_summary": "Initial registration of the lead create endpoint.",
        "change_reason": _PHASE_2,
    },
    # 9. Read one lead — the dependency root for every per-lead action below.
    {
        **_LEAD,
        "endpoint_key": "lead-read",
        "permission_key": "leads.lead.read",
        "operation_type": "read",
        "display_name": "View Lead",
        "description": "Retrieve a single in-scope lead with its contact numbers and study interest.",
        "http_method": "GET",
        "route_pattern": "/api/v1/leads/<lead_id>/",
        "view_import_path": "leads.views.LeadDetailView",
        "risk_level": "low",
        "dependencies": [_dep("leads.lead.list", "Reading a lead requires list access to its scope.")],
        "change_summary": "Initial registration of the lead read endpoint.",
        "change_reason": _PHASE_2,
    },
    # 10. Correct a lead's information. Stage is not editable here.
    {
        **_LEAD,
        "endpoint_key": "lead-update",
        "permission_key": "leads.lead.update",
        "operation_type": "update",
        "display_name": "Edit Lead",
        "description": "Correct identity, contact, source, or study-interest information. Stage is unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/leads/<lead_id>/",
        "view_import_path": "leads.views.LeadDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_LEAD_READ,
        "change_summary": "Initial registration of the lead update endpoint.",
        "change_reason": _PHASE_2,
    },
    # --- Phase 3: lifecycle -------------------------------------------------
    # 11. Move between active stages.
    {
        **_LEAD,
        "endpoint_key": "lead-change-stage",
        "permission_key": "leads.lead.change_stage",
        "operation_type": "custom",
        "display_name": "Change Lead Stage",
        "description": "Move a lead between active stages. Cannot set lost or converted.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/<lead_id>/stage/",
        "view_import_path": "leads.views.LeadStageView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_LEAD_READ,
        "change_summary": "Initial registration of the lead stage-change endpoint.",
        "change_reason": _PHASE_3,
    },
    # 12. Record a manual follow-up.
    {
        **_LEAD,
        "endpoint_key": "lead-record-followup",
        "permission_key": "leads.lead.record_followup",
        "operation_type": "custom",
        "display_name": "Record Lead Follow-up",
        "description": "Record that manual follow-up occurred, optionally with a note and a stage change.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/<lead_id>/follow-up/",
        "view_import_path": "leads.views.LeadFollowUpView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LEAD_READ,
        "change_summary": "Initial registration of the lead follow-up endpoint.",
        "change_reason": _PHASE_3,
    },
    # 13. Close a lead. A reason is mandatory, so this depends on loss_reason.list.
    {
        **_LEAD,
        "endpoint_key": "lead-mark-lost",
        "permission_key": "leads.lead.mark_lost",
        "operation_type": "custom",
        "display_name": "Mark Lead Lost",
        "description": "Close a lead as lost with a mandatory reason. Nothing is deleted.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/<lead_id>/lost/",
        "view_import_path": "leads.views.LeadMarkLostView",
        "risk_level": "high",
        "dependencies": [
            _dep("leads.lead.read", "The lead must be readable before it can be closed."),
            _dep("leads.loss_reason.list", "Closing a lead requires a reason chosen from the loss-reason list."),
        ],
        "change_summary": "Initial registration of the mark-lost endpoint.",
        "change_reason": _PHASE_3,
    },
    # 14. Reopen. Never undoes a conversion.
    {
        **_LEAD,
        "endpoint_key": "lead-reopen",
        "permission_key": "leads.lead.reopen",
        "operation_type": "custom",
        "display_name": "Reopen Lead",
        "description": "Return a lost or converted lead to an active stage, preserving all history.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/<lead_id>/reopen/",
        "view_import_path": "leads.views.LeadReopenView",
        "risk_level": "high",
        "dependencies": [
            _dep("leads.lead.read", "The lead must be readable before it can be reopened."),
            _dep("leads.lead.mark_lost", "Reopening only applies to a lead that was closed or converted."),
        ],
        "change_summary": "Initial registration of the lead reopen endpoint.",
        "change_reason": _PHASE_3,
    },
    # 15. List a lead's notes.
    {
        **_LEAD,
        "model_key": "lead_note",
        "model_display_name": "Lead Note",
        "endpoint_key": "lead-note-list",
        "permission_key": "leads.note.list",
        "operation_type": "list",
        "display_name": "List Lead Notes",
        "description": "List the notes recorded against a lead, newest first.",
        "http_method": "GET",
        "route_pattern": "/api/v1/leads/<lead_id>/notes/",
        "view_import_path": "leads.views.LeadNoteListCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LEAD_READ,
        "change_summary": "Initial registration of the lead-note list endpoint.",
        "change_reason": _PHASE_3,
    },
    # 16. Append a note. Notes are never edited or deleted.
    {
        **_LEAD,
        "model_key": "lead_note",
        "model_display_name": "Lead Note",
        "endpoint_key": "lead-note-create",
        "permission_key": "leads.note.create",
        "operation_type": "create",
        "display_name": "Add Lead Note",
        "description": "Append a note to a lead. Notes are append-only — there is no edit or delete.",
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/<lead_id>/notes/",
        "view_import_path": "leads.views.LeadNoteListCreateView",
        "risk_level": "low",
        "dependencies": [_dep("leads.note.list", "Adding a note requires the ability to read the lead's notes.")],
        "change_summary": "Initial registration of the lead-note create endpoint.",
        "change_reason": _PHASE_3,
    },
    # 17. The lead's history, projected from the central audit log.
    {
        **_LEAD,
        "endpoint_key": "lead-history",
        "permission_key": "leads.lead.list_history",
        "operation_type": "list",
        "display_name": "View Lead History",
        "description": "List a lead's chronological action history from the central audit log.",
        "http_method": "GET",
        "route_pattern": "/api/v1/leads/<lead_id>/history/",
        "view_import_path": "leads.views.LeadHistoryView",
        "risk_level": "low",
        "dependencies": _REQUIRES_LEAD_READ,
        "change_summary": "Initial registration of the lead history endpoint.",
        "change_reason": _PHASE_3,
    },
    # --- Phase 4: conversion ------------------------------------------------
    # 18. The one point where the lead cycle meets the applicant cycle.
    {
        **_LEAD,
        "endpoint_key": "lead-convert",
        "permission_key": "leads.lead.convert",
        "operation_type": "custom",
        "display_name": "Convert Lead to Applicant",
        "description": (
            "Create an applicant and an initial journey from the lead, link both permanently, "
            "and move the lead to its terminal converted stage. Admin only; idempotent."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/leads/<lead_id>/convert/",
        "view_import_path": "leads.views.LeadConvertView",
        "risk_level": "critical",
        "dependencies": [
            _dep("leads.lead.read", "The lead must be readable before it can be converted."),
            _dep("applicants.applicant.create", "Conversion creates the applicant record."),
            _dep("applicant_journeys.journey.create", "Conversion creates the initial journey."),
        ],
        "change_summary": "Initial registration of the lead conversion endpoint.",
        "change_reason": "leads app Phase 4 (conversion), unblocked by applicants + applicant_journeys.",
    },
]
