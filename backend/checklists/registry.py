"""Core Policy Engine endpoint declarations for the checklists app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

**Three models are declared, and the split is the access model made
machine-readable.** ``template`` and ``template_item`` are the Admin-only
authoring surface; ``checklist`` and ``item`` are the shared daily work. Nothing
enforces that from this file — §9's interim inline pattern is still what runs —
but when the permissions app is wired into the request path, this graph is what
it will read, and the boundary is already drawn in the right place.

Risk ratings are argued from what each endpoint actually does, not from its verb:

* ``template.create``/``template.update`` and the two ``template_item``
  endpoints are ``high``. A template is not one record: it is the standing
  answer to "what does this country require", and it propagates automatically to
  every future applicant bound there. Editing one silently changes what dozens
  of files will be measured against — the largest blast radius of any write in
  this app, by a wide margin.
* ``checklist.complete`` is ``high``. It is the moment the office declares an
  applicant's paperwork done, and downstream that claim is what someone relies
  on before an application goes out.
* ``checklist.archive`` is ``medium``, and it carries a consequence worth
  naming: archiving is what frees a journey to receive a fresh copy of its
  country's list, so it is the closest thing this app has to a reset.
* ``item.status`` is ``medium`` — the daily act, performed dozens of times a day,
  but the one that decides whether a requirement counts as met.
* The reads are ``low`` except ``checklist.list``, which is ``medium``: the
  metadata alone reveals which applicants are missing financial documents, which
  is disclosure even without the documents.

The two cross-app dependencies are the app's whole premise, so they are declared
rather than assumed: a checklist attaches to a **journey**, and a template is
scoped to a **country**.
"""

from typing import Any

_APP: dict[str, Any] = {
    "app_key": "checklists",
    "app_display_name": "Checklists",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "checklist_management",
    "category_display_name": "Checklist Management",
}

_TEMPLATE: dict[str, Any] = {
    **_APP,
    "model_key": "template",
    "model_display_name": "Checklist Template",
}

_TEMPLATE_ITEM: dict[str, Any] = {
    **_APP,
    "model_key": "template_item",
    "model_display_name": "Checklist Template Item",
}

_CHECKLIST: dict[str, Any] = {
    **_APP,
    "model_key": "checklist",
    "model_display_name": "Checklist",
}

_ITEM: dict[str, Any] = {
    **_APP,
    "model_key": "item",
    "model_display_name": "Checklist Item",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_TEMPLATE_READ = [_dep("checklists.template.read", "The template must be readable before it can be edited.")]
_REQUIRES_TEMPLATE_LIST = [_dep("checklists.template.list", "Authoring templates requires the ability to list them.")]
_REQUIRES_CHECKLIST_READ = [
    _dep("checklists.checklist.read", "The checklist must be readable before it can be acted on.")
]
_REQUIRES_CHECKLIST_LIST = [
    _dep("checklists.checklist.list", "Acting on checklists requires the ability to list them.")
]

_PHASE = "checklists app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # Templates — the Admin-only authoring surface.
    # -----------------------------------------------------------------------
    # 1. The catalogue of country requirement lists. Root of the authoring graph.
    {
        **_TEMPLATE,
        "endpoint_key": "template-list",
        "permission_key": "checklists.template.list",
        "operation_type": "list",
        "display_name": "List Checklist Templates",
        "description": (
            "List the country requirement lists. Filter by country, status, default flag, or label. "
            "Readable by Admin and Lead Manager; only an Admin may author one."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/checklists/templates/",
        "view_import_path": "checklists.views.TemplateListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the checklist template list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Authoring a country's requirements. The highest-leverage write here.
    {
        **_TEMPLATE,
        "endpoint_key": "template-create",
        "permission_key": "checklists.template.create",
        "operation_type": "create",
        "display_name": "Create Checklist Template",
        "description": (
            "Author a country's requirement list. Marking it the active default makes it the list every "
            "future applicant bound for that country inherits automatically. Admin authority only."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/templates/",
        "view_import_path": "checklists.views.TemplateListCreateView",
        "risk_level": "high",
        "dependencies": [
            *_REQUIRES_TEMPLATE_LIST,
            _dep("institutions.country.read", "A template is scoped to a catalogue country."),
        ],
        "change_summary": "Initial registration of the checklist template create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one template with its requirements — the dependency root per record.
    {
        **_TEMPLATE,
        "endpoint_key": "template-read",
        "permission_key": "checklists.template.read",
        "operation_type": "read",
        "display_name": "View Checklist Template",
        "description": "Retrieve one template with every requirement it defines, retired ones included.",
        "http_method": "GET",
        "route_pattern": "/api/v1/checklists/templates/<template_id>/",
        "view_import_path": "checklists.views.TemplateDetailView",
        "risk_level": "low",
        "dependencies": _REQUIRES_TEMPLATE_LIST,
        "change_summary": "Initial registration of the checklist template read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Editing a template. Never rewrites checklists already inherited from it.
    {
        **_TEMPLATE,
        "endpoint_key": "template-update",
        "permission_key": "checklists.template.update",
        "operation_type": "update",
        "display_name": "Edit Checklist Template",
        "description": (
            "Correct a template's label, country, default flag, or status. Applicants already holding a "
            "copy are untouched — instantiation is a snapshot. The key is immutable. Admin authority only."
        ),
        "http_method": "PATCH",
        "route_pattern": "/api/v1/checklists/templates/<template_id>/",
        "view_import_path": "checklists.views.TemplateDetailView",
        "risk_level": "high",
        "dependencies": _REQUIRES_TEMPLATE_READ,
        "change_summary": "Initial registration of the checklist template update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Adding a requirement definition.
    {
        **_TEMPLATE_ITEM,
        "endpoint_key": "template-item-create",
        "permission_key": "checklists.template_item.create",
        "operation_type": "create",
        "display_name": "Add Template Requirement",
        "description": (
            "Add one requirement to a country's list — a document to collect, a stage to reach, or a task "
            "to perform. Affects who inherits it next, never anyone already holding a copy. Admin only."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/templates/<template_id>/items/",
        "view_import_path": "checklists.views.TemplateItemCreateView",
        "risk_level": "high",
        "dependencies": _REQUIRES_TEMPLATE_READ,
        "change_summary": "Initial registration of the template requirement create endpoint.",
        "change_reason": _PHASE,
    },
    # 6. Editing or retiring a requirement definition. There is no delete.
    {
        **_TEMPLATE_ITEM,
        "endpoint_key": "template-item-update",
        "permission_key": "checklists.template_item.update",
        "operation_type": "update",
        "display_name": "Edit Template Requirement",
        "description": (
            "Correct a requirement definition, or retire it with is_active=false. Never deleted: live "
            "checklist items point back at the definition they were copied from. Admin authority only."
        ),
        "http_method": "PATCH",
        "route_pattern": "/api/v1/checklists/templates/<template_id>/items/<item_id>/",
        "view_import_path": "checklists.views.TemplateItemDetailView",
        "risk_level": "high",
        "dependencies": [
            *_REQUIRES_TEMPLATE_READ,
            _dep("checklists.template_item.create", "A requirement must exist before it can be edited."),
        ],
        "change_summary": "Initial registration of the template requirement update endpoint.",
        "change_reason": _PHASE,
    },
    # -----------------------------------------------------------------------
    # Checklists — the shared daily work.
    # -----------------------------------------------------------------------
    # 7. The worklist. Every per-applicant panel and the safety net are this
    #    endpoint with a filter, so it is the root of the operational graph.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-list",
        "permission_key": "checklists.checklist.list",
        "operation_type": "list",
        "display_name": "List Checklists",
        "description": (
            "List checklists with their progress counts. Filter by applicant, journey, status, origin, "
            "assignee, country, template, or overdue. journey_missing_checklist=true switches to the "
            "safety net: journeys naming a country nobody has authored requirements for."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/checklists/",
        "view_import_path": "checklists.views.ChecklistListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the checklist list endpoint.",
        "change_reason": _PHASE,
    },
    # 8. Manual creation — the override beside the automation.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-create",
        "permission_key": "checklists.checklist.create",
        "operation_type": "create",
        "display_name": "Create Checklist",
        "description": (
            "Apply a template to a journey by hand, or start a blank checklist. The automatic path needs "
            "no endpoint — setting a journey's country inherits its country's list on its own."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/",
        "view_import_path": "checklists.views.ChecklistListCreateView",
        "risk_level": "medium",
        "dependencies": [
            *_REQUIRES_CHECKLIST_LIST,
            _dep("applicant_journeys.journey.read", "A checklist must be attached to an existing journey."),
        ],
        "change_summary": "Initial registration of the checklist create endpoint.",
        "change_reason": _PHASE,
    },
    # 9. Read one checklist with its items — the dependency root per record.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-read",
        "permission_key": "checklists.checklist.read",
        "operation_type": "read",
        "display_name": "View Checklist",
        "description": "Retrieve one checklist with every item, its progress counts, and its lifecycle stamps.",
        "http_method": "GET",
        "route_pattern": "/api/v1/checklists/<checklist_id>/",
        "view_import_path": "checklists.views.ChecklistDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_CHECKLIST_LIST,
        "change_summary": "Initial registration of the checklist read endpoint.",
        "change_reason": _PHASE,
    },
    # 10. Editing the descriptive fields. Status is deliberately not among them.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-update",
        "permission_key": "checklists.checklist.update",
        "operation_type": "update",
        "display_name": "Edit Checklist",
        "description": (
            "Correct a checklist's title, owner, due date, or notes. Status is refused here — it moves "
            "only through the lifecycle actions, so completion cannot bypass the required-items check."
        ),
        "http_method": "PATCH",
        "route_pattern": "/api/v1/checklists/<checklist_id>/",
        "view_import_path": "checklists.views.ChecklistDetailView",
        "risk_level": "low",
        "dependencies": _REQUIRES_CHECKLIST_READ,
        "change_summary": "Initial registration of the checklist update endpoint.",
        "change_reason": _PHASE,
    },
    # 11. Draft -> active.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-activate",
        "permission_key": "checklists.checklist.activate",
        "operation_type": "custom",
        "display_name": "Activate Checklist",
        "description": "Put a draft checklist into active work. Inherited checklists arrive active already.",
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/activate/",
        "view_import_path": "checklists.views.ChecklistActivateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_CHECKLIST_READ,
        "change_summary": "Initial registration of the checklist activate endpoint.",
        "change_reason": _PHASE,
    },
    # 12. The claim that the paperwork is done. Refused unless the items agree.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-complete",
        "permission_key": "checklists.checklist.complete",
        "operation_type": "custom",
        "display_name": "Complete Checklist",
        "description": (
            "Declare an applicant's requirements met. Refused while any required item is pending or "
            "blocked, and the refusal names every offending item. Completion is derived, never asserted."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/complete/",
        "view_import_path": "checklists.views.ChecklistCompleteView",
        "risk_level": "high",
        "dependencies": [
            *_REQUIRES_CHECKLIST_READ,
            _dep("checklists.item.status", "Completion presupposes the ability to resolve the items."),
        ],
        "change_summary": "Initial registration of the checklist complete endpoint.",
        "change_reason": _PHASE,
    },
    # 13. Taking a completed checklist back into work.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-reopen",
        "permission_key": "checklists.checklist.reopen",
        "operation_type": "custom",
        "display_name": "Reopen Checklist",
        "description": (
            "Return a completed checklist to active work and clear its completion stamps. The completion "
            "itself survives in the audit log."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/reopen/",
        "view_import_path": "checklists.views.ChecklistReopenView",
        "risk_level": "medium",
        "dependencies": [
            *_REQUIRES_CHECKLIST_READ,
            _dep("checklists.checklist.complete", "Reopening reverses completion, so it presupposes it."),
        ],
        "change_summary": "Initial registration of the checklist reopen endpoint.",
        "change_reason": _PHASE,
    },
    # 14. Archive. Also the reset: it frees the journey to inherit a fresh copy.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-archive",
        "permission_key": "checklists.checklist.archive",
        "operation_type": "custom",
        "display_name": "Archive Checklist",
        "description": (
            "Take a checklist out of active work. A reason is required. An archived checklist no longer "
            "blocks re-applying its template, so this is also how staff ask for a fresh copy."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/archive/",
        "view_import_path": "checklists.views.ChecklistArchiveView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_CHECKLIST_READ,
        "change_summary": "Initial registration of the checklist archive endpoint.",
        "change_reason": _PHASE,
    },
    # 15. Restore. Reverses archival.
    {
        **_CHECKLIST,
        "endpoint_key": "checklist-restore",
        "permission_key": "checklists.checklist.restore",
        "operation_type": "custom",
        "display_name": "Restore Checklist",
        "description": "Return an archived checklist to work — active if it was ever activated, draft otherwise.",
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/restore/",
        "view_import_path": "checklists.views.ChecklistRestoreView",
        "risk_level": "low",
        "dependencies": [
            *_REQUIRES_CHECKLIST_READ,
            _dep("checklists.checklist.archive", "Restoring reverses archival, so it presupposes it."),
        ],
        "change_summary": "Initial registration of the checklist restore endpoint.",
        "change_reason": _PHASE,
    },
    # -----------------------------------------------------------------------
    # Items — one applicant's requirements.
    # -----------------------------------------------------------------------
    # 16. One extra requirement, this applicant only. Never travels to the template.
    {
        **_ITEM,
        "endpoint_key": "checklist-item-create",
        "permission_key": "checklists.item.create",
        "operation_type": "create",
        "display_name": "Add Checklist Item",
        "description": (
            "Add a requirement to one applicant's checklist for the case the template did not anticipate. "
            "It never travels back to the template, so the next applicant is unaffected."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/items/",
        "view_import_path": "checklists.views.ChecklistItemCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_CHECKLIST_READ,
        "change_summary": "Initial registration of the checklist item create endpoint.",
        "change_reason": _PHASE,
    },
    # 17. Editing an item's descriptive fields. Status is deliberately not here.
    {
        **_ITEM,
        "endpoint_key": "checklist-item-update",
        "permission_key": "checklists.item.update",
        "operation_type": "update",
        "display_name": "Edit Checklist Item",
        "description": (
            "Correct an item's label, owner, due date, or description. Status is refused here — it moves "
            "only through the status endpoint, where the note and evidence rules live."
        ),
        "http_method": "PATCH",
        "route_pattern": "/api/v1/checklists/<checklist_id>/items/<item_id>/",
        "view_import_path": "checklists.views.ChecklistItemDetailView",
        "risk_level": "low",
        "dependencies": [
            *_REQUIRES_CHECKLIST_READ,
            _dep("checklists.item.create", "An item must exist before it can be edited."),
        ],
        "change_summary": "Initial registration of the checklist item update endpoint.",
        "change_reason": _PHASE,
    },
    # 18. The daily act: recording what happened to one requirement.
    {
        **_ITEM,
        "endpoint_key": "checklist-item-status",
        "permission_key": "checklists.item.status",
        "operation_type": "custom",
        "display_name": "Set Checklist Item Status",
        "description": (
            "Mark a requirement completed, waived, blocked, or not applicable, with an optional uploaded "
            "file as evidence. Waiving or blocking requires a note; evidence must belong to this applicant."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/checklists/<checklist_id>/items/<item_id>/status/",
        "view_import_path": "checklists.views.ChecklistItemStatusView",
        "risk_level": "medium",
        "dependencies": [
            *_REQUIRES_CHECKLIST_READ,
            _dep(
                "uploaded_files.file.read",
                "An item may cite an uploaded file as evidence, which must be resolvable.",
            ),
        ],
        "change_summary": "Initial registration of the checklist item status endpoint.",
        "change_reason": _PHASE,
    },
]
