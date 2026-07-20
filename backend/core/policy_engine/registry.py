"""
Policy endpoint registry declaration pattern.

Apps declare their endpoints by defining POLICY_ENDPOINTS in their registry.py file.

Example declaration (in <app>/registry.py):

    from core.policy_engine.registry import register_from_config
    from core.policy_engine.constants import CreatedByType

    POLICY_ENDPOINTS = [
        {
            "app_key": "authenticate",
            "model_key": "user",
            "endpoint_key": "user-delete",
            "permission_key": "authenticate.user.delete",
            "http_method": "DELETE",
            "route_pattern": "/api/v1/auth/users/<id>/",
            "view_import_path": "authenticate.views.UserDeleteView",
            "operation_type": "delete",
            "display_name": "Delete User",
            "description": "Allows deleting or deactivating a user account.",
            "risk_level": "high",
            "version": "1.0.0",
            "category_key": "user_management",
            "category_display_name": "User Management",
            "dependencies": [
                {
                    "target_permission_key": "authenticate.user.read",
                    "direction": "forward",
                    "dependency_type": "requires",
                    "enforcement_mode": "strict",
                    "reason": "User must be readable before delete access is meaningful.",
                }
            ],
            "change_summary": "Initial registration of user deletion endpoint.",
            "change_reason": "Endpoint created by AI coding lifecycle.",
        }
    ]
"""

from typing import Any

from core.policy_engine.constants import CreatedByType
from core.policy_engine.lifecycle import run_endpoint_lifecycle


def register_from_config(
    config: dict[str, Any],
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> dict:
    """
    Register a single endpoint config dict through the full lifecycle.
    Returns a summary dict of created/updated objects.
    """
    return run_endpoint_lifecycle(
        config=config,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )


def load_registry_configs_from_installed_apps() -> list[dict[str, Any]]:
    """
    Discover and return all POLICY_ENDPOINTS lists from installed apps' registry.py files.
    Returns a flat list of all endpoint config dicts.
    """
    import importlib

    from django.apps import apps

    all_configs: list[dict[str, Any]] = []

    for app_config in apps.get_app_configs():
        registry_module_name = f"{app_config.name}.registry"
        try:
            module = importlib.import_module(registry_module_name)
        except ModuleNotFoundError:
            continue

        policy_endpoints: list | None = getattr(module, "POLICY_ENDPOINTS", None)
        if policy_endpoints and isinstance(policy_endpoints, list):
            all_configs.extend(policy_endpoints)

    return all_configs


# ---------------------------------------------------------------------------
# Core Policy Engine — self-registration of its own read-only API endpoints.
# Declared in dependency order so that deps are committed before the endpoints
# that reference them (each lifecycle call is atomic per endpoint).
# ---------------------------------------------------------------------------

_BASE: dict[str, Any] = {
    "app_key": "policy_engine",
    "app_display_name": "Core Policy Engine",
    "risk_level": "low",
    "version": "1.0.0",
    "is_internal": True,
    "category_key": "policy_engine_administration",
    "category_display_name": "Policy Engine Administration",
}

POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. List all registered policy applications — no forward deps
    {
        **_BASE,
        "endpoint_key": "application-list",
        "permission_key": "policy_engine.application.list",
        "model_key": "application",
        "model_display_name": "Policy Application",
        "operation_type": "list",
        "display_name": "List Policy Applications",
        "description": "List all registered policy applications in the Core Policy Engine.",
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/apps/",
        "view_import_path": "core.policy_engine.views.PolicyApplicationListView",
        "dependencies": [],
    },
    # 2. Read a single application — requires list
    {
        **_BASE,
        "endpoint_key": "application-read",
        "permission_key": "policy_engine.application.read",
        "model_key": "application",
        "model_display_name": "Policy Application",
        "operation_type": "read",
        "display_name": "View Policy Application Detail",
        "description": "Retrieve a single policy application with its models and endpoints.",
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/apps/<app_key>/",
        "view_import_path": "core.policy_engine.views.PolicyApplicationDetailView",
        "dependencies": [
            {
                "target_permission_key": "policy_engine.application.list",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Reading a specific application is only meaningful when list access is granted.",
            }
        ],
    },
    # 3. UI permission tree — requires application list (aggregates across apps)
    {
        **_BASE,
        "endpoint_key": "permission-tree",
        "permission_key": "policy_engine.permission.tree",
        "model_key": "application",
        "model_display_name": "Policy Application",
        "operation_type": "list",
        "display_name": "View UI Permission Tree",
        "description": ("Return the full categorised permission tree for frontend permission assignment UIs."),
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/permissions/tree/",
        "view_import_path": "core.policy_engine.views.UIPermissionTreeView",
        "dependencies": [
            {
                "target_permission_key": "policy_engine.application.list",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "The permission tree aggregates data across all registered applications.",
            }
        ],
    },
    # 4. Read a single endpoint by permission key — requires application read
    {
        **_BASE,
        "endpoint_key": "endpoint-read",
        "permission_key": "policy_engine.endpoint.read",
        "model_key": "endpoint",
        "model_display_name": "Policy Endpoint",
        "operation_type": "read",
        "display_name": "View Endpoint Detail",
        "description": "Retrieve metadata for a single endpoint by its permission key.",
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/endpoints/<permission_key>/",
        "view_import_path": "core.policy_engine.views.PolicyEndpointDetailView",
        "dependencies": [
            {
                "target_permission_key": "policy_engine.application.read",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Every endpoint belongs to an application; application read access is a prerequisite.",
            }
        ],
    },
    # 5. Read endpoint dependency graph — requires endpoint read
    {
        **_BASE,
        "endpoint_key": "endpoint-read-dependencies",
        "permission_key": "policy_engine.endpoint.read_dependencies",
        "model_key": "endpoint",
        "model_display_name": "Policy Endpoint",
        "operation_type": "custom",
        "display_name": "View Endpoint Dependencies",
        "description": "Retrieve the forward and backward dependency graph for a specific endpoint.",
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/endpoints/<permission_key>/dependencies/",
        "view_import_path": "core.policy_engine.views.EndpointDependencyView",
        "dependencies": [
            {
                "target_permission_key": "policy_engine.endpoint.read",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Dependency data is scoped to an endpoint; endpoint read access is required first.",
            }
        ],
    },
    # 6. Read endpoint version history — requires endpoint read
    {
        **_BASE,
        "endpoint_key": "endpoint-read-versions",
        "permission_key": "policy_engine.endpoint.read_versions",
        "model_key": "endpoint",
        "model_display_name": "Policy Endpoint",
        "operation_type": "custom",
        "display_name": "View Endpoint Version History",
        "description": "Retrieve the immutable version history for a specific endpoint.",
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/endpoints/<permission_key>/versions/",
        "view_import_path": "core.policy_engine.views.EndpointVersionListView",
        "dependencies": [
            {
                "target_permission_key": "policy_engine.endpoint.read",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Version history is scoped to an endpoint; endpoint read access is required first.",
            }
        ],
    },
    # 7. Read endpoint audit changelog — requires endpoint read
    {
        **_BASE,
        "endpoint_key": "endpoint-read-changelog",
        "permission_key": "policy_engine.endpoint.read_changelog",
        "model_key": "endpoint",
        "model_display_name": "Policy Endpoint",
        "operation_type": "custom",
        "display_name": "View Endpoint Changelog",
        "description": "Retrieve the immutable audit changelog for a specific endpoint.",
        "http_method": "GET",
        "route_pattern": "/api/v1/policy/endpoints/<permission_key>/changelog/",
        "view_import_path": "core.policy_engine.views.EndpointChangelogView",
        "dependencies": [
            {
                "target_permission_key": "policy_engine.endpoint.read",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Changelog data is scoped to an endpoint; endpoint read access is required first.",
            }
        ],
    },
]
