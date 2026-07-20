import functools
import subprocess
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.nepal.text import normalize_unicode
from core.policy_engine.constants import (
    ChangeType,
    CreatedByType,
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    ObjectType,
    RiskLevel,
)
from core.policy_engine.exceptions import PolicyIdentityConflictError
from core.policy_engine.models import (
    EndpointCategoryMap,
    PermissionCategory,
    PolicyApplication,
    PolicyChangeLog,
    PolicyDependency,
    PolicyEndpoint,
    PolicyEndpointVersion,
    PolicyModel,
)
from core.policy_engine.selectors import (
    get_application_by_key,
    get_category_by_key,
    get_endpoint_by_permission_key,
    get_policy_model_by_key,
)
from core.policy_engine.validators import validate_permission_key_format, validate_semantic_version


@transaction.atomic
def register_application(
    key: str,
    display_name: str,
    description: str = "",
    version: str = "1.0.0",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyApplication:
    validate_semantic_version(version)

    app, created = PolicyApplication.objects.get_or_create(
        key=key,
        defaults={
            "display_name": display_name,
            "description": description,
            "current_version": version,
        },
    )

    if created:
        log_change(
            object_type=ObjectType.APPLICATION,
            object_key=key,
            change_type=ChangeType.CREATED,
            summary=f"Application '{key}' registered.",
            reason="Initial registration.",
            new_version=version,
            application=app,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
    else:
        changed = False
        version_changed = version != app.current_version
        prev_version = app.current_version
        if app.display_name != display_name:
            app.display_name = display_name
            changed = True
        if description and app.description != description:
            app.description = description
            changed = True
        if version_changed:
            app.current_version = version
            changed = True
        if changed:
            app.save()
            log_change(
                object_type=ObjectType.APPLICATION,
                object_key=key,
                change_type=ChangeType.METADATA_UPDATE,
                summary=f"Application '{key}' metadata updated.",
                previous_version=prev_version if version_changed else "",
                new_version=version if version_changed else "",
                application=app,
                created_by_type=created_by_type,
                created_by_identifier=created_by_identifier,
            )

    return app


@transaction.atomic
def register_model(
    app_key: str,
    key: str,
    display_name: str,
    import_path: str = "",
    description: str = "",
    version: str = "1.0.0",
    migration_reference: str = "",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyModel:
    validate_semantic_version(version)
    app = get_application_by_key(app_key)

    policy_model, created = PolicyModel.objects.get_or_create(
        application=app,
        key=key,
        defaults={
            "display_name": display_name,
            "import_path": import_path,
            "description": description,
            "current_version": version,
        },
    )

    if created:
        log_change(
            object_type=ObjectType.MODEL,
            object_key=f"{app_key}.{key}",
            change_type=ChangeType.CREATED,
            summary=f"Model '{app_key}.{key}' registered.",
            reason="Initial registration.",
            migration_reference=migration_reference,
            new_version=version,
            application=app,
            policy_model=policy_model,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
    else:
        changed = False
        version_changed = version != policy_model.current_version
        prev_version = policy_model.current_version
        if policy_model.display_name != display_name:
            policy_model.display_name = display_name
            changed = True
        if import_path and policy_model.import_path != import_path:
            policy_model.import_path = import_path
            changed = True
        if version_changed:
            policy_model.current_version = version
            changed = True
        if changed:
            policy_model.save()
            log_change(
                object_type=ObjectType.MODEL,
                object_key=f"{app_key}.{key}",
                change_type=ChangeType.METADATA_UPDATE,
                summary=f"Model '{app_key}.{key}' metadata updated.",
                migration_reference=migration_reference,
                previous_version=prev_version if version_changed else "",
                new_version=version if version_changed else "",
                application=app,
                policy_model=policy_model,
                created_by_type=created_by_type,
                created_by_identifier=created_by_identifier,
            )

    return policy_model


@transaction.atomic
def register_endpoint(
    app_key: str,
    endpoint_key: str,
    permission_key: str,
    operation_type: str,
    display_name: str,
    model_key: str | None = None,
    http_method: str = "",
    route_pattern: str = "",
    view_import_path: str = "",
    description: str = "",
    version: str = "1.0.0",
    risk_level: str = RiskLevel.LOW,
    is_internal: bool = False,
    is_dependency_root: bool = False,
    change_summary: str = "",
    change_reason: str = "",
    migration_reference: str = "",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyEndpoint:
    validate_permission_key_format(permission_key)
    validate_semantic_version(version)

    app = get_application_by_key(app_key)
    policy_model = get_policy_model_by_key(app_key, model_key) if model_key else None

    _check_endpoint_identity(app, endpoint_key, permission_key)

    endpoint, created = PolicyEndpoint.objects.get_or_create(
        application=app,
        key=endpoint_key,
        defaults={
            "permission_key": permission_key,
            "policy_model": policy_model,
            "http_method": http_method,
            "route_pattern": route_pattern,
            "view_import_path": view_import_path,
            "operation_type": operation_type,
            "display_name": display_name,
            "description": description,
            "current_version": version,
            "risk_level": risk_level,
            "is_internal": is_internal,
            "is_dependency_root": is_dependency_root,
        },
    )

    if created:
        _create_version_record(
            endpoint=endpoint,
            version=version,
            http_method=http_method,
            route_pattern=route_pattern,
            view_import_path=view_import_path,
            operation_type=operation_type,
        )
        log_change(
            object_type=ObjectType.ENDPOINT,
            object_key=permission_key,
            change_type=ChangeType.CREATED,
            summary=change_summary or f"Endpoint '{permission_key}' registered.",
            reason=change_reason or "Initial registration.",
            migration_reference=migration_reference,
            new_version=version,
            application=app,
            policy_model=policy_model,
            endpoint=endpoint,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
    else:
        _update_endpoint_if_changed(
            endpoint=endpoint,
            display_name=display_name,
            description=description,
            http_method=http_method,
            route_pattern=route_pattern,
            view_import_path=view_import_path,
            operation_type=operation_type,
            risk_level=risk_level,
            is_internal=is_internal,
            is_dependency_root=is_dependency_root,
            version=version,
            policy_model=policy_model,
            change_summary=change_summary,
            change_reason=change_reason,
            migration_reference=migration_reference,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )

    return endpoint


def _check_endpoint_identity(
    app: PolicyApplication,
    endpoint_key: str,
    permission_key: str,
) -> None:
    """An endpoint's identity is the pair ((application, key), permission_key).
    Changing either half of an already-registered pair is a rename — a breaking
    change for permission consumers (role bindings reference permission_key) —
    and must never happen implicitly during sync."""
    existing_by_key = PolicyEndpoint.objects.filter(application=app, key=endpoint_key).first()
    if existing_by_key and existing_by_key.permission_key != permission_key:
        raise PolicyIdentityConflictError(
            f"Endpoint '{app.key}.{endpoint_key}' is registered with permission_key "
            f"'{existing_by_key.permission_key}' but this declaration says '{permission_key}'. "
            "Renaming a permission_key cannot happen implicitly during sync — register the new "
            "key as a new endpoint and deprecate the old one explicitly."
        )

    existing_by_permission = (
        PolicyEndpoint.objects.filter(permission_key=permission_key).exclude(application=app, key=endpoint_key).first()
    )
    if existing_by_permission:
        raise PolicyIdentityConflictError(
            f"permission_key '{permission_key}' is already registered by endpoint "
            f"'{existing_by_permission.application.key}.{existing_by_permission.key}', but this "
            f"declaration uses endpoint key '{app.key}.{endpoint_key}'. Renaming an endpoint key "
            "cannot happen implicitly during sync — deprecate the old endpoint explicitly first."
        )


def _update_endpoint_if_changed(
    endpoint: PolicyEndpoint,
    display_name: str,
    description: str,
    http_method: str,
    route_pattern: str,
    view_import_path: str,
    operation_type: str,
    risk_level: str,
    is_internal: bool,
    is_dependency_root: bool,
    version: str,
    policy_model: PolicyModel | None,
    created_by_type: str,
    created_by_identifier: str,
    change_summary: str = "",
    change_reason: str = "",
    migration_reference: str = "",
) -> None:
    route_changed = route_pattern and endpoint.route_pattern != route_pattern
    method_changed = http_method and endpoint.http_method != http_method
    version_changed = version != endpoint.current_version
    dependency_root_changed = endpoint.is_dependency_root != is_dependency_root
    internal_changed = endpoint.is_internal != is_internal
    policy_model_changed = policy_model is not None and endpoint.policy_model_id != policy_model.id
    metadata_changed = (
        (display_name and endpoint.display_name != display_name)
        or (description and endpoint.description != description)
        or (operation_type and endpoint.operation_type != operation_type)
        or (risk_level and endpoint.risk_level != risk_level)
        or (view_import_path and endpoint.view_import_path != view_import_path)
        or dependency_root_changed
        or internal_changed
        or policy_model_changed
    )

    if not any([route_changed, method_changed, version_changed, metadata_changed]):
        return

    prev_version = endpoint.current_version

    if route_pattern:
        endpoint.route_pattern = route_pattern
    if http_method:
        endpoint.http_method = http_method
    if display_name:
        endpoint.display_name = display_name
    if description:
        endpoint.description = description
    if operation_type:
        endpoint.operation_type = operation_type
    if risk_level:
        endpoint.risk_level = risk_level
    if view_import_path:
        endpoint.view_import_path = view_import_path
    if dependency_root_changed:
        endpoint.is_dependency_root = is_dependency_root
    if internal_changed:
        endpoint.is_internal = is_internal
    if policy_model_changed:
        endpoint.policy_model = policy_model
    if version_changed:
        endpoint.current_version = version
    endpoint.save()

    if version_changed:
        _create_version_record(
            endpoint=endpoint,
            version=version,
            http_method=http_method or endpoint.http_method,
            route_pattern=route_pattern or endpoint.route_pattern,
            view_import_path=view_import_path or endpoint.view_import_path,
            operation_type=operation_type or endpoint.operation_type,
        )

    change_type = ChangeType.UPDATED
    if route_changed:
        change_type = ChangeType.ROUTE_CHANGED
    elif method_changed:
        change_type = ChangeType.METHOD_CHANGED

    log_change(
        object_type=ObjectType.ENDPOINT,
        object_key=endpoint.permission_key,
        change_type=change_type,
        summary=change_summary or f"Endpoint '{endpoint.permission_key}' updated.",
        reason=change_reason,
        migration_reference=migration_reference,
        previous_version=prev_version,
        new_version=version if version_changed else prev_version,
        application=endpoint.application,
        endpoint=endpoint,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )


def _create_version_record(
    endpoint: PolicyEndpoint,
    version: str,
    http_method: str,
    route_pattern: str,
    view_import_path: str,
    operation_type: str,
    snapshot: dict | None = None,
) -> PolicyEndpointVersion:
    computed_snapshot = snapshot or {
        "permission_key": endpoint.permission_key,
        "http_method": http_method,
        "route_pattern": route_pattern,
        "view_import_path": view_import_path,
        "operation_type": operation_type,
        "risk_level": endpoint.risk_level,
        "display_name": endpoint.display_name,
    }

    existing = PolicyEndpointVersion.objects.filter(endpoint=endpoint, version=version).first()
    if existing is not None:
        content_fields = {
            "http_method": http_method,
            "route_pattern": route_pattern,
            "view_import_path": view_import_path,
            "operation_type": operation_type,
        }
        drift = {
            field: (getattr(existing, field), value)
            for field, value in content_fields.items()
            if getattr(existing, field) != value
        }
        if drift:
            from core.policy_engine.exceptions import PolicyVersionConflictError

            raise PolicyVersionConflictError(
                f"Version '{version}' already exists for endpoint '{endpoint.permission_key}' with "
                f"different content ({drift}). Version records are immutable — bump the version "
                "instead of reusing one with changed content."
            )
        return existing

    return PolicyEndpointVersion.objects.create(
        endpoint=endpoint,
        version=version,
        http_method=http_method,
        route_pattern=route_pattern,
        view_import_path=view_import_path,
        operation_type=operation_type,
        snapshot=computed_snapshot,
    )


@transaction.atomic
def register_category(
    key: str,
    display_name: str,
    description: str = "",
    app_key: str | None = None,
    model_key: str | None = None,
    parent_key: str | None = None,
    icon_key: str = "",
    sort_order: int = 0,
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PermissionCategory:
    app = get_application_by_key(app_key) if app_key else None
    policy_model = get_policy_model_by_key(app_key, model_key) if (app_key and model_key) else None
    parent = get_category_by_key(parent_key) if parent_key else None

    category, created = PermissionCategory.objects.get_or_create(
        key=key,
        defaults={
            "display_name": display_name,
            "description": description,
            "application": app,
            "policy_model": policy_model,
            "parent": parent,
            "icon_key": icon_key,
            "sort_order": sort_order,
        },
    )

    if created:
        log_change(
            object_type=ObjectType.CATEGORY,
            object_key=key,
            change_type=ChangeType.CREATED,
            summary=f"Category '{key}' registered.",
            application=app,
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
    else:
        changed = False
        if category.display_name != display_name:
            category.display_name = display_name
            changed = True
        if description and category.description != description:
            category.description = description
            changed = True
        if icon_key and category.icon_key != icon_key:
            category.icon_key = icon_key
            changed = True
        if app is not None and category.application_id != app.id:
            category.application = app
            changed = True
        if policy_model is not None and category.policy_model_id != policy_model.id:
            category.policy_model = policy_model
            changed = True
        if parent is not None and category.parent_id != parent.id:
            category.parent = parent
            changed = True
        if category.sort_order != sort_order:
            category.sort_order = sort_order
            changed = True
        if changed:
            category.save()
            log_change(
                object_type=ObjectType.CATEGORY,
                object_key=key,
                change_type=ChangeType.METADATA_UPDATE,
                summary=f"Category '{key}' metadata updated.",
                application=app,
                created_by_type=created_by_type,
                created_by_identifier=created_by_identifier,
            )

    return category


@transaction.atomic
def map_endpoint_to_category(
    permission_key: str,
    category_key: str,
    display_label: str = "",
    help_text: str = "",
    sort_order: int = 0,
    is_visible_in_ui: bool = True,
    is_sensitive: bool = False,
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> EndpointCategoryMap:
    endpoint = get_endpoint_by_permission_key(permission_key)
    category = get_category_by_key(category_key)

    mapping, created = EndpointCategoryMap.objects.get_or_create(
        endpoint=endpoint,
        category=category,
        defaults={
            "display_label": display_label or endpoint.display_name,
            "help_text": help_text,
            "sort_order": sort_order,
            "is_visible_in_ui": is_visible_in_ui,
            "is_sensitive": is_sensitive,
        },
    )

    if created:
        log_change(
            object_type=ObjectType.ENDPOINT,
            object_key=permission_key,
            change_type=ChangeType.CATEGORY_CHANGED,
            summary=f"Endpoint '{permission_key}' mapped to category '{category_key}'.",
            application=endpoint.application,
            endpoint=endpoint,
            affected_categories=[category_key],
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
    else:
        changed = False
        resolved_label = display_label or endpoint.display_name
        if resolved_label and mapping.display_label != resolved_label:
            mapping.display_label = resolved_label
            changed = True
        if help_text and mapping.help_text != help_text:
            mapping.help_text = help_text
            changed = True
        if mapping.sort_order != sort_order:
            mapping.sort_order = sort_order
            changed = True
        if mapping.is_visible_in_ui != is_visible_in_ui:
            mapping.is_visible_in_ui = is_visible_in_ui
            changed = True
        if mapping.is_sensitive != is_sensitive:
            mapping.is_sensitive = is_sensitive
            changed = True
        if changed:
            mapping.save()
            log_change(
                object_type=ObjectType.ENDPOINT,
                object_key=permission_key,
                change_type=ChangeType.CATEGORY_CHANGED,
                summary=f"Endpoint '{permission_key}' category mapping to '{category_key}' updated.",
                application=endpoint.application,
                endpoint=endpoint,
                affected_categories=[category_key],
                created_by_type=created_by_type,
                created_by_identifier=created_by_identifier,
            )

    return mapping


@transaction.atomic
def add_dependency(
    source_permission_key: str,
    target_permission_key: str,
    direction: str = DependencyDirection.FORWARD,
    dependency_type: str = DependencyType.REQUIRES,
    enforcement_mode: str = EnforcementMode.STRICT,
    reason: str = "",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyDependency:
    from core.policy_engine.dependency_resolver import detect_circular_dependencies

    source = get_endpoint_by_permission_key(source_permission_key)
    target = get_endpoint_by_permission_key(target_permission_key)

    if detect_circular_dependencies(source_permission_key, target_permission_key, direction):
        from core.policy_engine.exceptions import PolicyCircularDependencyError

        raise PolicyCircularDependencyError(
            f"Adding dependency from '{source_permission_key}' to '{target_permission_key}' "
            "would create a circular dependency."
        )

    dep, created = PolicyDependency.objects.get_or_create(
        source_endpoint=source,
        target_endpoint=target,
        direction=direction,
        dependency_type=dependency_type,
        defaults={
            "enforcement_mode": enforcement_mode,
            "reason": reason,
        },
    )

    if created:
        log_change(
            object_type=ObjectType.DEPENDENCY,
            object_key=f"{source_permission_key} → {target_permission_key}",
            change_type=ChangeType.DEPENDENCY_ADDED,
            summary=f"Dependency added: '{source_permission_key}' {dependency_type} '{target_permission_key}'.",
            reason=reason,
            application=source.application,
            endpoint=source,
            affected_dependencies=[target_permission_key],
            created_by_type=created_by_type,
            created_by_identifier=created_by_identifier,
        )
    else:
        changed = False
        prev_enforcement_mode = dep.enforcement_mode
        if dep.enforcement_mode != enforcement_mode:
            dep.enforcement_mode = enforcement_mode
            changed = True
        if reason and dep.reason != reason:
            dep.reason = reason
            changed = True
        if changed:
            dep.save()
            log_change(
                object_type=ObjectType.DEPENDENCY,
                object_key=f"{source_permission_key} → {target_permission_key}",
                change_type=ChangeType.METADATA_UPDATE,
                summary=(
                    f"Dependency metadata updated: '{source_permission_key}' {dependency_type} "
                    f"'{target_permission_key}'."
                ),
                detail=(
                    f"enforcement_mode: '{prev_enforcement_mode}' -> '{dep.enforcement_mode}'."
                    if prev_enforcement_mode != dep.enforcement_mode
                    else ""
                ),
                reason=reason,
                application=source.application,
                endpoint=source,
                affected_dependencies=[target_permission_key],
                created_by_type=created_by_type,
                created_by_identifier=created_by_identifier,
            )

    return dep


@transaction.atomic
def create_version(
    permission_key: str,
    version: str,
    http_method: str = "",
    route_pattern: str = "",
    view_import_path: str = "",
    operation_type: str = "",
    snapshot: dict | None = None,
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyEndpointVersion:
    validate_semantic_version(version)
    endpoint = get_endpoint_by_permission_key(permission_key)

    prev_version = endpoint.current_version

    version_obj = _create_version_record(
        endpoint=endpoint,
        version=version,
        http_method=http_method or endpoint.http_method,
        route_pattern=route_pattern or endpoint.route_pattern,
        view_import_path=view_import_path or endpoint.view_import_path,
        operation_type=operation_type or endpoint.operation_type,
        snapshot=snapshot,
    )

    # endpoint.current_version is the single writable currency pointer — the new
    # record only becomes "current" once the endpoint points at it.
    endpoint.current_version = version
    endpoint.save()

    log_change(
        object_type=ObjectType.ENDPOINT,
        object_key=permission_key,
        change_type=ChangeType.UPDATED,
        summary=f"Version '{version}' created for endpoint '{permission_key}'.",
        previous_version=prev_version,
        new_version=version,
        application=endpoint.application,
        endpoint=endpoint,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )

    return version_obj


@functools.lru_cache(maxsize=1)
def _git_provenance() -> tuple[str, str]:
    """(branch_name, based_on_commit_sha) for the working tree this process
    is running from — best-effort, never raises. Returns ("", "") if git
    isn't available (e.g. a deployed build with no .git) or the calls fail
    for any reason — provenance capture must never block a registry write.
    Memoized per-process: a single sync_policy_registry run can write
    hundreds of changelog rows and the branch/commit can't change mid-run.

    Note: this is the commit the tree was *based on* when the row was
    written, not the commit that will eventually ship it — that commit
    doesn't exist yet at write time (CLAUDE.md §34: commit happens after
    code+tests+docs), and PolicyChangeLog is append-only so it could never
    be retroactively stamped once the real commit exists anyway. See
    docs/DATA_CONTRACT.md §8 "Provenance rule"."""
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
        return branch, sha
    except Exception:
        return "", ""


def log_change(
    object_type: str,
    object_key: str,
    change_type: str,
    summary: str,
    detail: str = "",
    reason: str = "",
    issue_reference: str = "",
    migration_reference: str = "",
    previous_version: str = "",
    new_version: str = "",
    affected_dependencies: list | None = None,
    affected_categories: list | None = None,
    backward_compatibility_notes: str = "",
    forward_compatibility_notes: str = "",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
    application: PolicyApplication | None = None,
    policy_model: PolicyModel | None = None,
    endpoint: PolicyEndpoint | None = None,
) -> PolicyChangeLog:
    branch_name, based_on_commit_sha = _git_provenance()
    return PolicyChangeLog.objects.create(
        object_type=object_type,
        object_key=object_key,
        change_type=change_type,
        summary=summary,
        detail=detail,
        reason=reason,
        issue_reference=issue_reference,
        migration_reference=migration_reference,
        branch_name=branch_name,
        based_on_commit_sha=based_on_commit_sha,
        previous_version=previous_version,
        new_version=new_version,
        affected_dependencies=affected_dependencies or [],
        affected_categories=affected_categories or [],
        backward_compatibility_notes=backward_compatibility_notes,
        forward_compatibility_notes=forward_compatibility_notes,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
        application=application,
        policy_model=policy_model,
        endpoint=endpoint,
    )


@transaction.atomic
def deprecate_endpoint(
    permission_key: str,
    reason: str,
    sunset_at: datetime | None = None,
    replaced_by_permission_key: str = "",
    removal_ticket: str = "",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyEndpoint:
    """First stage of the staged deletion lifecycle. Marks the endpoint deprecated
    (stays active — the sunset window) and records the current-state retirement
    metadata directly on the endpoint: when it was deprecated, the planned sunset
    date, the successor permission key, the removal ticket, and the reason. The
    append-only PolicyChangeLog still records the event; these fields are the
    denormalized current state for cheap audit queries."""
    endpoint = get_endpoint_by_permission_key(permission_key)
    endpoint.is_deprecated = True
    endpoint.deprecated_at = timezone.now()
    endpoint.removal_reason = normalize_unicode(reason) if reason else ""
    if sunset_at is not None:
        endpoint.sunset_at = sunset_at
    if replaced_by_permission_key:
        endpoint.replaced_by_permission_key = replaced_by_permission_key
    if removal_ticket:
        endpoint.removal_ticket = removal_ticket
    endpoint.save()

    log_change(
        object_type=ObjectType.ENDPOINT,
        object_key=permission_key,
        change_type=ChangeType.DEPRECATED,
        summary=f"Endpoint '{permission_key}' marked as deprecated.",
        reason=reason,
        issue_reference=removal_ticket,
        application=endpoint.application,
        endpoint=endpoint,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )

    return endpoint


@transaction.atomic
def disable_endpoint(
    permission_key: str,
    reason: str,
    removal_ticket: str = "",
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyEndpoint:
    """Second stage of the staged deletion lifecycle: deprecate -> disable ->
    (future) archive. An endpoint must already be deprecated before it can be
    disabled — this enforces the sunset-window stage rather than allowing an
    endpoint to disappear from the registry in one step. Records disabled_at and,
    if the removal reason/ticket were not already captured at deprecation time (or
    have changed), updates removal_reason/removal_ticket."""
    endpoint = get_endpoint_by_permission_key(permission_key)

    if not endpoint.is_deprecated:
        from core.policy_engine.exceptions import PolicyLifecycleIncompleteError

        raise PolicyLifecycleIncompleteError(
            f"Endpoint '{permission_key}' must be deprecated before it can be disabled. "
            "Call deprecate_endpoint() first to start the sunset window."
        )

    endpoint.is_active = False
    endpoint.disabled_at = timezone.now()
    if reason:
        endpoint.removal_reason = normalize_unicode(reason)
    if removal_ticket:
        endpoint.removal_ticket = removal_ticket
    endpoint.save()

    log_change(
        object_type=ObjectType.ENDPOINT,
        object_key=permission_key,
        change_type=ChangeType.REMOVED,
        summary=f"Endpoint '{permission_key}' disabled.",
        reason=reason,
        issue_reference=removal_ticket,
        application=endpoint.application,
        endpoint=endpoint,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )

    return endpoint


@transaction.atomic
def restore_endpoint(
    permission_key: str,
    reason: str,
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyEndpoint:
    """Reverses deprecate_endpoint()/disable_endpoint() — brings a disabled or
    deprecated-only endpoint back to fully active status. Clears the denormalized
    retirement metadata so current state stays accurate (there is no active
    retirement after restore); the full history remains in PolicyChangeLog."""
    endpoint = get_endpoint_by_permission_key(permission_key)
    endpoint.is_active = True
    endpoint.is_deprecated = False
    endpoint.deprecated_at = None
    endpoint.disabled_at = None
    endpoint.sunset_at = None
    endpoint.replaced_by_permission_key = ""
    endpoint.removal_ticket = ""
    endpoint.removal_reason = ""
    endpoint.save()

    log_change(
        object_type=ObjectType.ENDPOINT,
        object_key=permission_key,
        change_type=ChangeType.RESTORED,
        summary=f"Endpoint '{permission_key}' restored.",
        reason=reason,
        application=endpoint.application,
        endpoint=endpoint,
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )

    return endpoint


@transaction.atomic
def remove_dependency(
    source_permission_key: str,
    target_permission_key: str,
    direction: str,
    dependency_type: str,
    reason: str,
    created_by_type: str = CreatedByType.SYSTEM,
    created_by_identifier: str = "system",
) -> PolicyDependency:
    """Soft-removes a dependency edge. Never hard-deletes — PolicyDependency
    rows are part of the audit trail (referenced by prior PolicyChangeLog
    entries' affected_dependencies), so this only flips is_active=False."""
    from core.policy_engine.exceptions import PolicyDependencyNotFoundError

    source = get_endpoint_by_permission_key(source_permission_key)
    target = get_endpoint_by_permission_key(target_permission_key)

    dep = PolicyDependency.objects.filter(
        source_endpoint=source,
        target_endpoint=target,
        direction=direction,
        dependency_type=dependency_type,
    ).first()
    if dep is None:
        raise PolicyDependencyNotFoundError(
            f"No '{dependency_type}' dependency ({direction}) from '{source_permission_key}' "
            f"to '{target_permission_key}' exists."
        )

    dep.is_active = False
    dep.save()

    log_change(
        object_type=ObjectType.DEPENDENCY,
        object_key=f"{source_permission_key} → {target_permission_key}",
        change_type=ChangeType.DEPENDENCY_REMOVED,
        summary=f"Dependency removed: '{source_permission_key}' {dependency_type} '{target_permission_key}'.",
        reason=reason,
        application=source.application,
        endpoint=source,
        affected_dependencies=[target_permission_key],
        created_by_type=created_by_type,
        created_by_identifier=created_by_identifier,
    )

    return dep
