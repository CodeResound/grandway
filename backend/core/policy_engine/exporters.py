"""Registry-derived export artifacts for the Core Policy Engine.

These functions turn the *declarative* registry (each app's `registry.py`
`POLICY_ENDPOINTS`, loaded via `load_registry_configs_from_installed_apps()`)
into deterministic, machine-readable artifacts:

- `build_registry_export()` — a canonical JSON view of every registered endpoint,
  its permission_key, routing/classification metadata, and dependency edges.
- `build_openapi_document()` — an OpenAPI 3.1 document describing the routed API
  surface (paths, methods, per-operation `x-permission-key`/`x-risk-level`).

Both are **pure functions of the registry declarations** — no database, no
timestamps, no UUIDs — so their output is stable across runs and suitable for a
committed artifact plus a CI drift check (`export_policy_registry --check`). The
live `/api/v1/policy/...` HTTP endpoints already serve full runtime state
(lifecycle timestamps, DB ids) for operational use; these artifacts are the
stable *contract*, not a live snapshot.

Request/response body schemas are intentionally generic here — the registry does
not model them. Integrators read field-level shapes from each app's
`docs/DATA_CONTRACT.md`; the OpenAPI doc cross-references that in each operation's
description.
"""

import re
from typing import Any

from core.policy_engine.constants import (
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    RiskLevel,
)
from core.policy_engine.registry import load_registry_configs_from_installed_apps

# Bumped when the *shape* of the export artifacts changes (not on every content
# change — content changes come from registry.py edits).
REGISTRY_EXPORT_SCHEMA_VERSION = "1.0.0"
OPENAPI_VERSION = "3.1.0"

# "<uuid:organization_id>", "<str:app_key>", "<id>" -> capture the param name.
_ROUTE_PARAM_RE = re.compile(r"<(?:[^<>:]+:)?([^<>]+)>")


def _normalize_dependency(dep: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_permission_key": dep.get("target_permission_key", ""),
        "direction": dep.get("direction", DependencyDirection.FORWARD),
        "dependency_type": dep.get("dependency_type", DependencyType.REQUIRES),
        "enforcement_mode": dep.get("enforcement_mode", EnforcementMode.STRICT),
        "reason": dep.get("reason", ""),
    }


def _normalize_endpoint(config: dict[str, Any]) -> dict[str, Any]:
    dependencies = [_normalize_dependency(d) for d in config.get("dependencies", []) if isinstance(d, dict)]
    dependencies.sort(key=lambda d: (d["target_permission_key"], d["dependency_type"], d["direction"]))
    return {
        "permission_key": config.get("permission_key", ""),
        "app_key": config.get("app_key", ""),
        "model_key": config.get("model_key", ""),
        "endpoint_key": config.get("endpoint_key", ""),
        "display_name": config.get("display_name", ""),
        "description": config.get("description", ""),
        "http_method": config.get("http_method", ""),
        "route_pattern": config.get("route_pattern", ""),
        "operation_type": config.get("operation_type", ""),
        "risk_level": config.get("risk_level", RiskLevel.LOW),
        "version": config.get("version", "1.0.0"),
        "category_key": config.get("category_key", ""),
        "is_dependency_root": bool(config.get("is_dependency_root", False)),
        "dependencies": dependencies,
    }


def build_registry_export() -> dict[str, Any]:
    """Assemble the canonical, deterministically ordered registry export."""
    configs = load_registry_configs_from_installed_apps()
    endpoints = sorted((_normalize_endpoint(c) for c in configs), key=lambda e: e["permission_key"])

    applications: dict[str, str] = {}
    categories: dict[str, str] = {}
    for config in configs:
        app_key = config.get("app_key", "")
        if app_key:
            applications.setdefault(app_key, config.get("app_display_name", ""))
        category_key = config.get("category_key", "")
        if category_key:
            categories.setdefault(category_key, config.get("category_display_name", ""))

    return {
        "schema_version": REGISTRY_EXPORT_SCHEMA_VERSION,
        "generated_from": "registry",
        "applications": [{"app_key": key, "display_name": applications[key]} for key in sorted(applications)],
        "categories": [{"category_key": key, "display_name": categories[key]} for key in sorted(categories)],
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


def _route_to_openapi_path(route_pattern: str) -> str:
    """Convert a Django route pattern to OpenAPI path templating.

    "/api/v1/auth/users/<uuid:id>/" -> "/api/v1/auth/users/{id}/"
    """
    return _ROUTE_PARAM_RE.sub(r"{\1}", route_pattern)


def _path_parameters(openapi_path: str) -> list[dict[str, Any]]:
    names = re.findall(r"{([^{}]+)}", openapi_path)
    return [
        {
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
        for name in names
    ]


def _operation_object(endpoint: dict[str, Any], openapi_path: str) -> dict[str, Any]:
    op: dict[str, Any] = {
        "operationId": endpoint["permission_key"],
        "summary": endpoint["display_name"],
        "description": (
            f"{endpoint['description']}\n\n"
            f"Request/response field schemas: see the owning app's `docs/DATA_CONTRACT.md`."
        ).strip(),
        "tags": [endpoint["app_key"]] if endpoint["app_key"] else [],
        "security": [{"bearerAuth": []}],
        "x-permission-key": endpoint["permission_key"],
        "x-risk-level": endpoint["risk_level"],
        "x-operation-type": endpoint["operation_type"],
        "responses": {
            "200": {
                "description": "Success",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SuccessEnvelope"}}},
            },
            "400": {"$ref": "#/components/responses/Error"},
            "401": {"$ref": "#/components/responses/Error"},
            "403": {"$ref": "#/components/responses/Error"},
            "404": {"$ref": "#/components/responses/Error"},
        },
    }
    params = _path_parameters(openapi_path)
    if params:
        op["parameters"] = params
    return op


def _components() -> dict[str, Any]:
    return {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
        },
        "schemas": {
            "SuccessEnvelope": {
                "type": "object",
                "required": ["success", "message", "data"],
                "properties": {
                    "success": {"type": "boolean", "enum": [True]},
                    "message": {"type": "string"},
                    "data": {"description": "Resource payload — see the owning app's DATA_CONTRACT.md."},
                    "meta": {"$ref": "#/components/schemas/Meta"},
                },
            },
            "ErrorEnvelope": {
                "type": "object",
                "required": ["success", "error"],
                "properties": {
                    "success": {"type": "boolean", "enum": [False]},
                    "error": {
                        "type": "object",
                        "required": ["code", "message"],
                        "properties": {
                            "code": {"type": "string", "description": "APP_RESOURCE_REASON code."},
                            "message": {"type": "string"},
                            "details": {"type": "object"},
                        },
                    },
                    "meta": {"$ref": "#/components/schemas/Meta"},
                },
            },
            "Meta": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "page": {"type": "integer"},
                    "page_size": {"type": "integer"},
                    "next": {"type": ["string", "null"]},
                    "previous": {"type": ["string", "null"]},
                },
            },
        },
        "responses": {
            "Error": {
                "description": "Standard error envelope",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
            },
        },
    }


def build_openapi_document() -> dict[str, Any]:
    """Assemble an OpenAPI 3.1 document from the registry declarations.

    Endpoints with no `route_pattern` or `http_method` (service-only registrations)
    are omitted from `paths` — they have no HTTP surface to describe — but remain
    in `build_registry_export()`.
    """
    export = build_registry_export()
    paths: dict[str, dict[str, Any]] = {}

    for endpoint in export["endpoints"]:
        route = endpoint["route_pattern"]
        method = endpoint["http_method"]
        if not route or not method:
            continue
        openapi_path = _route_to_openapi_path(route)
        paths.setdefault(openapi_path, {})[method.lower()] = _operation_object(endpoint, openapi_path)

    # Deterministic ordering: sorted paths, sorted methods within each path.
    ordered_paths = {path: dict(sorted(paths[path].items())) for path in sorted(paths)}

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "Grandway Policy-Registered API",
            "version": REGISTRY_EXPORT_SCHEMA_VERSION,
            "description": (
                "Generated from the Core Policy Engine registry (source of truth for endpoints, "
                "permission keys, HTTP methods, and risk levels). Request/response body schemas are "
                "documented per app in `docs/DATA_CONTRACT.md`."
            ),
        },
        "servers": [{"url": "/"}],
        "security": [{"bearerAuth": []}],
        "paths": ordered_paths,
        "components": _components(),
    }
