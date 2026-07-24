"""Core Policy Engine endpoint declarations for the document_templates app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

**Every endpoint here is rated lower than its equivalent in the other two
document apps, and that is the judgement worth recording.** ``documents`` rates
even its plain list ``medium`` because the list reveals which applicants have
financial documents on file; ``document_history`` rates its snapshot read
``high`` because it returns a frozen bank statement. This app holds **no
applicant data at all** — a signatory is a staff member's name and a link to
their signature image, a template is a slug and a label. Reads are ``low``,
writes are ``medium`` because they shape what the whole document workspace is
allowed to offer.

The access rule does **not** follow the risk rating: this app is Admin-only like
its two siblings, inherited from its consumer rather than its content. See
``access.py``.

Two models are registered rather than one — a signatory and a template are
unrelated entities that happen to share an app, and collapsing them would make
``template.list`` read as an action on a signatory.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "document_templates",
    "app_display_name": "Document Templates",
    "version": "1.0.0",
    "is_internal": False,
    # Shares the category used by ``documents`` and ``document_history`` so all
    # three appear together in a permission-management UI — to an operator they
    # are one feature.
    "category_key": "document_management",
    "category_display_name": "Document Management",
}

_SIGNATORY: dict[str, Any] = {
    **_BASE,
    "model_key": "signatory",
    "model_display_name": "Signatory",
}

_TEMPLATE: dict[str, Any] = {
    **_BASE,
    "model_key": "template",
    "model_display_name": "Document Template",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_SIGNATORY_READ = [
    _dep("document_templates.signatory.read", "The signatory must be readable before it can be acted on.")
]
_REQUIRES_TEMPLATE_READ = [
    _dep("document_templates.template.read", "The template must be readable before it can be acted on.")
]

_PHASE = "document_templates app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The signature library, and the one endpoint the frontend actually calls
    #    (with ?status=active, to populate the instructor/director selects).
    {
        **_SIGNATORY,
        "endpoint_key": "signatory-list",
        "permission_key": "document_templates.signatory.list",
        "operation_type": "list",
        "display_name": "List Signatories",
        "description": "List signatory records. Filter with ?status=active for the certificate signer picker.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-templates/signatories/",
        "view_import_path": "document_templates.views.SignatoryListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the signatory list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Add a signer. Medium: it shapes who may be named on an issued document.
    {
        **_SIGNATORY,
        "endpoint_key": "signatory-create",
        "permission_key": "document_templates.signatory.create",
        "operation_type": "create",
        "display_name": "Create Signatory",
        "description": "Add a person and signature image to the library. Created as draft.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-templates/signatories/",
        "view_import_path": "document_templates.views.SignatoryListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("document_templates.signatory.list", "Creating signatories requires the ability to list them.")
        ],
        "change_summary": "Initial registration of the signatory create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one signer — the dependency root for both per-signatory actions.
    {
        **_SIGNATORY,
        "endpoint_key": "signatory-read",
        "permission_key": "document_templates.signatory.read",
        "operation_type": "read",
        "display_name": "View Signatory",
        "description": "Retrieve one signatory record, including its signature image link.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-templates/signatories/<signatory_id>/",
        "view_import_path": "document_templates.views.SignatoryDetailView",
        "risk_level": "low",
        "dependencies": [_dep("document_templates.signatory.list", "Reading a signatory requires list access.")],
        "change_summary": "Initial registration of the signatory read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Correct a signer's name, title, role, or signature image.
    {
        **_SIGNATORY,
        "endpoint_key": "signatory-update",
        "permission_key": "document_templates.signatory.update",
        "operation_type": "update",
        "display_name": "Edit Signatory",
        "description": "Correct a signatory's names, title, role, or signature link. Status is unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/document-templates/signatories/<signatory_id>/",
        "view_import_path": "document_templates.views.SignatoryDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_SIGNATORY_READ,
        "change_summary": "Initial registration of the signatory update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Activate or retire a signer. The nearest thing to a delete this app has.
    {
        **_SIGNATORY,
        "endpoint_key": "signatory-change-status",
        "permission_key": "document_templates.signatory.change_status",
        "operation_type": "custom",
        "display_name": "Change Signatory Status",
        "description": "Move a signatory between draft, active, and inactive. Nothing is deleted.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-templates/signatories/<signatory_id>/status/",
        "view_import_path": "document_templates.views.SignatoryStatusView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_SIGNATORY_READ,
        "change_summary": "Initial registration of the signatory status endpoint.",
        "change_reason": _PHASE,
    },
    # 6. The template catalogue — the picker's backing list.
    {
        **_TEMPLATE,
        "endpoint_key": "template-list",
        "permission_key": "document_templates.template.list",
        "operation_type": "list",
        "display_name": "List Document Templates",
        "description": "List template catalogue rows. Filter by family and status to build the document picker.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-templates/templates/",
        "view_import_path": "document_templates.views.TemplateListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the template list endpoint.",
        "change_reason": _PHASE,
    },
    # 7. Register a slug. Medium: it decides what the workspace may offer.
    {
        **_TEMPLATE,
        "endpoint_key": "template-create",
        "permission_key": "document_templates.template.create",
        "operation_type": "create",
        "display_name": "Register Document Template",
        "description": "Register a template slug against a family. The key is immutable once created.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-templates/templates/",
        "view_import_path": "document_templates.views.TemplateListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("document_templates.template.list", "Creating templates requires the ability to list them.")
        ],
        "change_summary": "Initial registration of the template create endpoint.",
        "change_reason": _PHASE,
    },
    # 8. Read one catalogue row.
    {
        **_TEMPLATE,
        "endpoint_key": "template-read",
        "permission_key": "document_templates.template.read",
        "operation_type": "read",
        "display_name": "View Document Template",
        "description": "Retrieve one template catalogue row.",
        "http_method": "GET",
        "route_pattern": "/api/v1/document-templates/templates/<template_id>/",
        "view_import_path": "document_templates.views.TemplateDetailView",
        "risk_level": "low",
        "dependencies": [_dep("document_templates.template.list", "Reading a template requires list access.")],
        "change_summary": "Initial registration of the template read endpoint.",
        "change_reason": _PHASE,
    },
    # 9. Edit a row's label, description, family, or picker position.
    {
        **_TEMPLATE,
        "endpoint_key": "template-update",
        "permission_key": "document_templates.template.update",
        "operation_type": "update",
        "display_name": "Edit Document Template",
        "description": "Edit a template's label, description, family, or display order. The key is refused.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/document-templates/templates/<template_id>/",
        "view_import_path": "document_templates.views.TemplateDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_TEMPLATE_READ,
        "change_summary": "Initial registration of the template update endpoint.",
        "change_reason": _PHASE,
    },
    # 10. Retire a template from the picker. Never breaks an existing document,
    #     because `documents` does not consult this table.
    {
        **_TEMPLATE,
        "endpoint_key": "template-change-status",
        "permission_key": "document_templates.template.change_status",
        "operation_type": "custom",
        "display_name": "Change Document Template Status",
        "description": "Move a template between draft, active, and inactive. Existing documents are unaffected.",
        "http_method": "POST",
        "route_pattern": "/api/v1/document-templates/templates/<template_id>/status/",
        "view_import_path": "document_templates.views.TemplateStatusView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_TEMPLATE_READ,
        "change_summary": "Initial registration of the template status endpoint.",
        "change_reason": _PHASE,
    },
]
