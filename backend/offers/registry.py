"""Core Policy Engine endpoint declarations for the offers app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

Two models are declared here, ``offer`` and ``condition``, because the
permission surface genuinely splits: a consultancy may want a user who can work
an offer's conditions without being able to record the decision that closes it.
"""

from typing import Any

_APP: dict[str, Any] = {
    "app_key": "offers",
    "app_display_name": "Offers",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "offer_management",
    "category_display_name": "Offer Management",
}

_OFFER: dict[str, Any] = {
    **_APP,
    "model_key": "offer",
    "model_display_name": "Offer",
}

_CONDITION: dict[str, Any] = {
    **_APP,
    "model_key": "condition",
    "model_display_name": "Offer Condition",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_OFFER_READ = [_dep("offers.offer.read", "The offer must be readable before it can be acted on.")]

_PHASE = "offers app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. List offers — the Offer List worklist and the Journey Detail panel.
    {
        **_OFFER,
        "endpoint_key": "offer-list",
        "permission_key": "offers.offer.list",
        "operation_type": "list",
        "display_name": "List Offers",
        "description": "List admission decisions across journeys. Shared, not owner-scoped.",
        "http_method": "GET",
        "route_pattern": "/api/v1/offers/",
        "view_import_path": "offers.views.OfferListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the offer list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Record an offer. Needs a journey to attach it to, and normally a
    #    catalogue program to snapshot from.
    {
        **_OFFER,
        "endpoint_key": "offer-create",
        "permission_key": "offers.offer.create",
        "operation_type": "create",
        "display_name": "Record Offer",
        "description": "Record an institution's admission decision against an applicant journey.",
        "http_method": "POST",
        "route_pattern": "/api/v1/offers/",
        "view_import_path": "offers.views.OfferListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("offers.offer.list", "Recording offers requires the ability to list them."),
            _dep("applicant_journeys.journey.read", "An offer must be attached to an existing journey."),
        ],
        "change_summary": "Initial registration of the offer create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one offer — the dependency root for every per-offer action.
    {
        **_OFFER,
        "endpoint_key": "offer-read",
        "permission_key": "offers.offer.read",
        "operation_type": "read",
        "display_name": "View Offer",
        "description": "Retrieve one offer with its snapshot, money figures, conditions, and decision.",
        "http_method": "GET",
        "route_pattern": "/api/v1/offers/<offer_id>/",
        "view_import_path": "offers.views.OfferDetailView",
        "risk_level": "low",
        "dependencies": [_dep("offers.offer.list", "Reading an offer requires list access.")],
        "change_summary": "Initial registration of the offer read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Correct decision details. The reference block and status are out of reach.
    {
        **_OFFER,
        "endpoint_key": "offer-update",
        "permission_key": "offers.offer.update",
        "operation_type": "update",
        "display_name": "Edit Offer",
        "description": "Correct dates, tuition, scholarship, deposit, or notes. Snapshot and status are unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/offers/<offer_id>/",
        "view_import_path": "offers.views.OfferDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_OFFER_READ,
        "change_summary": "Initial registration of the offer update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Draft becomes issued.
    {
        **_OFFER,
        "endpoint_key": "offer-issue",
        "permission_key": "offers.offer.issue",
        "operation_type": "custom",
        "display_name": "Issue Offer",
        "description": "Mark a drafted offer as issued and awaiting the applicant's response.",
        "http_method": "POST",
        "route_pattern": "/api/v1/offers/<offer_id>/issue/",
        "view_import_path": "offers.views.OfferIssueView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_OFFER_READ,
        "change_summary": "Initial registration of the offer issue endpoint.",
        "change_reason": _PHASE,
    },
    # 6. The decision itself — final, with no reopen counterpart.
    {
        **_OFFER,
        "endpoint_key": "offer-decision",
        "permission_key": "offers.offer.record_decision",
        "operation_type": "custom",
        "display_name": "Record Offer Decision",
        "description": "Record accept, reject, withdraw, defer, or expire. A decision is final and is never reopened.",
        "http_method": "POST",
        "route_pattern": "/api/v1/offers/<offer_id>/decision/",
        "view_import_path": "offers.views.OfferDecisionView",
        "risk_level": "high",
        "dependencies": [
            _dep("offers.offer.read", "The offer must be readable before a decision is recorded against it."),
            _dep("offers.offer.issue", "A decision follows the offer being issued."),
        ],
        "change_summary": "Initial registration of the offer decision endpoint.",
        "change_reason": _PHASE,
    },
    # 7. The offer's history, projected from the central audit log.
    {
        **_OFFER,
        "endpoint_key": "offer-history",
        "permission_key": "offers.offer.list_history",
        "operation_type": "list",
        "display_name": "View Offer History",
        "description": "List an offer's chronological history, including its condition events.",
        "http_method": "GET",
        "route_pattern": "/api/v1/offers/<offer_id>/history/",
        "view_import_path": "offers.views.OfferHistoryView",
        "risk_level": "low",
        "dependencies": _REQUIRES_OFFER_READ,
        "change_summary": "Initial registration of the offer history endpoint.",
        "change_reason": _PHASE,
    },
    # 8. Conditions attached to one offer.
    {
        **_CONDITION,
        "endpoint_key": "condition-list",
        "permission_key": "offers.condition.list",
        "operation_type": "list",
        "display_name": "List Offer Conditions",
        "description": "List the requirements attached to one offer, in display order.",
        "http_method": "GET",
        "route_pattern": "/api/v1/offers/<offer_id>/conditions/",
        "view_import_path": "offers.views.ConditionListCreateView",
        "risk_level": "low",
        "dependencies": _REQUIRES_OFFER_READ,
        "change_summary": "Initial registration of the offer condition list endpoint.",
        "change_reason": _PHASE,
    },
    # 9. Attach a requirement. Permitted after a decision — institutions do this.
    {
        **_CONDITION,
        "endpoint_key": "condition-create",
        "permission_key": "offers.condition.create",
        "operation_type": "create",
        "display_name": "Add Offer Condition",
        "description": "Attach a requirement to an offer. Allowed even after the offer has been decided.",
        "http_method": "POST",
        "route_pattern": "/api/v1/offers/<offer_id>/conditions/",
        "view_import_path": "offers.views.ConditionListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("offers.condition.list", "Adding conditions requires the ability to list them."),
            _dep("offers.offer.read", "A condition must be attached to a readable offer."),
        ],
        "change_summary": "Initial registration of the offer condition create endpoint.",
        "change_reason": _PHASE,
    },
    # 10. Correct a condition's wording. Status moves through endpoint 11.
    {
        **_CONDITION,
        "endpoint_key": "condition-update",
        "permission_key": "offers.condition.update",
        "operation_type": "update",
        "display_name": "Edit Offer Condition",
        "description": "Correct a condition's type, wording, due date, or ordering. Status is unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/offers/conditions/<condition_id>/",
        "view_import_path": "offers.views.ConditionDetailView",
        "risk_level": "medium",
        "dependencies": [_dep("offers.condition.list", "The condition must be readable before it can be edited.")],
        "change_summary": "Initial registration of the offer condition update endpoint.",
        "change_reason": _PHASE,
    },
    # 11. Resolve, waive, retire, or reopen a condition.
    {
        **_CONDITION,
        "endpoint_key": "condition-status",
        "permission_key": "offers.condition.change_status",
        "operation_type": "custom",
        "display_name": "Change Offer Condition Status",
        "description": "Mark a condition satisfied, waived, not applicable, or pending again.",
        "http_method": "POST",
        "route_pattern": "/api/v1/offers/conditions/<condition_id>/status/",
        "view_import_path": "offers.views.ConditionStatusView",
        "risk_level": "medium",
        "dependencies": [
            _dep("offers.condition.list", "The condition must be readable before its status can change."),
        ],
        "change_summary": "Initial registration of the offer condition status endpoint.",
        "change_reason": _PHASE,
    },
]
