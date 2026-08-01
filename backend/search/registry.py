"""Core Policy Engine endpoint declarations for the search app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

**The dependencies are the substantive part of this file, and they are derived
rather than typed.** Every searchable type contributes two forward dependencies
to the query endpoint: the ``read`` permission that opens one result, and the
``list`` permission that the bucket's "see all" link hands off to. Both are
already recorded in ``search/constants.py`` because the response needs them, so
generating them here means the two can never disagree — a tenth searchable type
declares its policy dependencies by existing.

The dependency direction matters for what the engine can then answer. Granting
someone global search without ``applicants.applicant.read`` produces a panel of
results none of which will open: exactly the screen of dead ends that
``dashboards/registry.py`` explains its own dependencies to prevent, and the
reason those are ``strict``.

``model_key`` names the *concept*, not a table. This app owns no tables at all;
``query`` and ``type`` are the two resources it exposes, and ``app.model.action``
needs each to be addressable.
"""

from typing import Any

from search.constants import SEARCHABLE_TYPES

_BASE: dict[str, Any] = {
    "app_key": "search",
    "app_display_name": "Search",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "global_search",
    "category_display_name": "Global Search",
    "http_method": "GET",
    "operation_type": "read",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_LOGIN = _dep("authenticate.session.login", "A session must be established by login before this endpoint is usable.")

_PHASE = "search app initial build."


def _type_dependencies() -> list[dict[str, Any]]:
    """One read and one list dependency per searchable type, in catalogue order."""
    dependencies: list[dict[str, Any]] = []
    for entry in SEARCHABLE_TYPES:
        dependencies.append(
            _dep(
                entry.detail_permission_key,
                f"A {entry.key} hit is unopenable without permission to read the record it points at.",
            )
        )
        dependencies.append(
            _dep(
                entry.list_permission_key,
                f"The {entry.key} bucket's 'see all' link hands off to that list endpoint.",
            )
        )
    return dependencies


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The query itself. High dependency count by design — it is a door into
    #    nine other resources, and the registry should say so.
    {
        **_BASE,
        "model_key": "query",
        "model_display_name": "Global Search Query",
        "endpoint_key": "search-query",
        "permission_key": "search.query.read",
        "display_name": "Run Global Search",
        "description": (
            "One query answered across every searchable record type — applicants, leads, clients, "
            "documents, files, institutions, programs, templates, and signatories — grouped by type. "
            "Results are narrowed by the owning apps' own scoping: a Lead Manager sees only their own "
            "leads and no Admin-only files."
        ),
        "route_pattern": "/api/v1/search/",
        "view_import_path": "search.views.GlobalSearchView",
        # Medium, not low. Each hit is a named person, partner, or file, and the
        # box names them in response to a guess rather than to a chosen filter.
        # That is a sharper disclosure than any single list endpoint, even though
        # every individual row is one the caller could already have reached.
        "risk_level": "medium",
        "dependencies": [_LOGIN, *_type_dependencies()],
        "change_summary": "Initial registration of the global search endpoint.",
        "change_reason": _PHASE,
    },
    # 2. The catalogue. Depends only on a session: it returns no business data
    #    at all, only the shape of what search covers.
    {
        **_BASE,
        "model_key": "type",
        "model_display_name": "Searchable Type",
        "endpoint_key": "search-types",
        "permission_key": "search.type.list",
        "operation_type": "list",
        "display_name": "List Searchable Types",
        "description": (
            "The catalogue of record types global search covers, with the fields each is matched on "
            "and the permission keys needed to open a result or follow its list link. Static per "
            "deployment; a client fetches it once to build its filter chips."
        ),
        "route_pattern": "/api/v1/search/types/",
        "view_import_path": "search.views.SearchableTypesView",
        "risk_level": "low",
        "dependencies": [_LOGIN],
        "change_summary": "Initial registration of the searchable-type catalogue endpoint.",
        "change_reason": _PHASE,
    },
]
