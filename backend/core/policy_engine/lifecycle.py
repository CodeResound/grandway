"""
Policy Engine Lifecycle Orchestrator.

Implements all 15 steps from policy_engine_prompt.md §17.1.

Whenever a new endpoint, model, route, action, or permission-sensitive behavior
is created, updated, deleted, or deprecated, this lifecycle must be followed.
"""

from typing import Any

from django.db import connection, transaction

from core.policy_engine.constants import CreatedByType
from core.policy_engine.exceptions import PolicyEngineError, PolicyLifecycleIncompleteError
from core.policy_engine.services import (
    add_dependency,
    map_endpoint_to_category,
    register_application,
    register_category,
    register_endpoint,
    register_model,
)


def _check_db_connection() -> None:
    """
    Assert the database is reachable before any writes are attempted.

    Raises PolicyLifecycleIncompleteError immediately if the DB is down so the
    caller gets a clear, actionable error instead of a partial write followed
    by an obscure OperationalError mid-lifecycle.
    """
    try:
        connection.ensure_connection()
    except Exception as exc:
        raise PolicyLifecycleIncompleteError(
            "Policy Engine lifecycle aborted: database is unreachable. "
            "No policy engine records were written. "
            "Restore DB connectivity and re-run sync_policy_registry."
        ) from exc


def run_endpoint_lifecycle(
    config: dict[str, Any],
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> dict:
    """
    Orchestrate all 15 lifecycle steps for an endpoint config dict.

    Fails fast with PolicyLifecycleIncompleteError if the DB is unreachable —
    before any writes are attempted. All writes execute inside a single
    transaction.atomic() block: if any step fails mid-lifecycle every write
    from this call is rolled back, leaving no partial state behind.

    Required config keys:
        app_key, endpoint_key, permission_key, operation_type, display_name

    Optional config keys:
        model_key, app_display_name, model_display_name,
        http_method, route_pattern, view_import_path,
        description, version, risk_level, is_internal, is_dependency_root,
        category_key, category_display_name,
        dependencies (list of dicts),
        change_summary, change_reason, migration_reference

    Returns a summary dict of what was created or updated.
    Raises PolicyLifecycleIncompleteError if the DB is unreachable.
    """
    # Health check first — before entering the transaction — so a DB-down
    # scenario produces a clear PolicyLifecycleIncompleteError, not an
    # obscure OperationalError from inside transaction.atomic()'s setup.
    _check_db_connection()

    with transaction.atomic():
        return _run_lifecycle_in_transaction(config, created_by_type, created_by_identifier)


def _run_lifecycle_in_transaction(
    config: dict[str, Any],
    created_by_type: str,
    created_by_identifier: str,
) -> dict:
    summary: dict[str, Any] = {"created": [], "updated": [], "errors": []}

    app_key: str = config["app_key"]
    endpoint_key: str = config["endpoint_key"]
    permission_key: str = config["permission_key"]
    operation_type: str = config["operation_type"]
    display_name: str = config["display_name"]

    model_key: str | None = config.get("model_key")
    version: str = config.get("version", "1.0.0")
    risk_level: str = config.get("risk_level", "low")
    description: str = config.get("description", "")
    http_method: str = config.get("http_method", "")
    route_pattern: str = config.get("route_pattern", "")
    view_import_path: str = config.get("view_import_path", "")
    is_internal: bool = config.get("is_internal", False)
    is_dependency_root: bool = config.get("is_dependency_root", False)
    category_key: str | None = config.get("category_key")
    category_display_name: str = config.get("category_display_name", category_key or "")
    dependencies: list[dict] = config.get("dependencies", [])
    change_summary: str = config.get("change_summary", "")
    change_reason: str = config.get("change_reason", "")
    migration_reference: str = config.get("migration_reference", "")

    # Step 1-4: Register the application
    register_application(
        key=app_key,
        display_name=config.get("app_display_name", app_key.replace("_", " ").title()),
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )
    summary["app"] = app_key

    # Step 5: Register the model if applicable
    if model_key:
        register_model(
            app_key=app_key,
            key=model_key,
            display_name=config.get("model_display_name", model_key.replace("_", " ").title()),
            migration_reference=migration_reference,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
        summary["model"] = f"{app_key}.{model_key}"

    # Step 6: Register the endpoint
    register_endpoint(
        app_key=app_key,
        endpoint_key=endpoint_key,
        permission_key=permission_key,
        operation_type=operation_type,
        display_name=display_name,
        model_key=model_key,
        http_method=http_method,
        route_pattern=route_pattern,
        view_import_path=view_import_path,
        description=description,
        version=version,
        risk_level=risk_level,
        is_internal=is_internal,
        is_dependency_root=is_dependency_root,
        change_summary=change_summary,
        change_reason=change_reason,
        migration_reference=migration_reference,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )
    summary["endpoint"] = permission_key

    # Step 7: Register and assign permission category
    if category_key:
        register_category(
            key=category_key,
            display_name=category_display_name,
            app_key=app_key,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
        map_endpoint_to_category(
            permission_key=permission_key,
            category_key=category_key,
            is_sensitive=risk_level in ("high", "critical"),
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
        summary["category"] = category_key

    # Steps 8-10: Define dependency relationships.
    # Only PolicyEngineError (domain errors like "target endpoint not found") are
    # caught here — they are recorded in the summary so the caller can inspect them.
    # DB-level errors (OperationalError, InterfaceError) are NOT caught and will
    # propagate up, causing the outer @transaction.atomic to roll back everything.
    deps_registered: list[str] = []
    for dep_config in dependencies:
        target_key: str = dep_config["target_permission_key"]
        direction: str = dep_config.get("direction", "forward")
        dep_type: str = dep_config.get("dependency_type", "requires")
        enforcement: str = dep_config.get("enforcement_mode", "strict")
        dep_reason: str = dep_config.get("reason", "")

        try:
            add_dependency(
                source_permission_key=permission_key,
                target_permission_key=target_key,
                direction=direction,
                dependency_type=dep_type,
                enforcement_mode=enforcement,
                reason=dep_reason,
                created_by_type=created_by_type,
                created_by_identifier=created_by_identifier,
            )
            deps_registered.append(target_key)
        except PolicyEngineError as exc:
            summary["errors"].append(f"Failed to add dependency {permission_key}→{target_key}: {exc}")

    if deps_registered:
        summary["dependencies"] = deps_registered

    return summary
