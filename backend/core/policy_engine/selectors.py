from typing import Any

from django.db.models import QuerySet

from core.policy_engine.exceptions import (
    PolicyApplicationNotFoundError,
    PolicyCategoryNotFoundError,
    PolicyEndpointNotFoundError,
    PolicyModelNotFoundError,
)
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


def get_registered_apps() -> QuerySet[PolicyApplication]:
    return PolicyApplication.objects.filter(is_active=True).order_by("key")


def get_all_apps() -> QuerySet[PolicyApplication]:
    return PolicyApplication.objects.all().order_by("key")


def get_application_by_key(app_key: str) -> PolicyApplication:
    try:
        return PolicyApplication.objects.get(key=app_key)
    except PolicyApplication.DoesNotExist as exc:
        raise PolicyApplicationNotFoundError(f"PolicyApplication '{app_key}' not found.") from exc


def get_policy_models(app_key: str | None = None) -> QuerySet[PolicyModel]:
    qs = PolicyModel.objects.select_related("application").filter(is_active=True)
    if app_key:
        qs = qs.filter(application__key=app_key)
    return qs.order_by("application__key", "key")


def get_policy_model_by_key(app_key: str, model_key: str) -> PolicyModel:
    try:
        return PolicyModel.objects.select_related("application").get(
            application__key=app_key,
            key=model_key,
        )
    except PolicyModel.DoesNotExist as exc:
        raise PolicyModelNotFoundError(f"PolicyModel '{app_key}.{model_key}' not found.") from exc


def get_policy_endpoints(
    app_key: str | None = None,
    model_key: str | None = None,
) -> QuerySet[PolicyEndpoint]:
    qs = PolicyEndpoint.objects.select_related("application", "policy_model").filter(is_active=True)
    if app_key:
        qs = qs.filter(application__key=app_key)
    if model_key:
        qs = qs.filter(policy_model__key=model_key)
    return qs.order_by("application__key", "key")


def get_endpoint_by_permission_key(permission_key: str) -> PolicyEndpoint:
    try:
        return PolicyEndpoint.objects.select_related("application", "policy_model").get(permission_key=permission_key)
    except PolicyEndpoint.DoesNotExist as exc:
        raise PolicyEndpointNotFoundError(f"PolicyEndpoint '{permission_key}' not found.") from exc


def get_permission_categories(app_key: str | None = None) -> QuerySet[PermissionCategory]:
    qs = PermissionCategory.objects.select_related("application", "policy_model", "parent").filter(is_active=True)
    if app_key:
        qs = qs.filter(application__key=app_key)
    return qs.order_by("sort_order", "key")


def get_category_by_key(category_key: str) -> PermissionCategory:
    try:
        return PermissionCategory.objects.select_related("application").get(key=category_key)
    except PermissionCategory.DoesNotExist as exc:
        raise PolicyCategoryNotFoundError(f"PermissionCategory '{category_key}' not found.") from exc


def get_ui_permission_tree(app_key: str | None = None, include_inactive: bool = False) -> list[dict]:
    """
    Returns a structured permission tree suitable for UI rendering.

    Shape:
    [
      {
        "app": "authenticate",
        "groups": [
          {
            "key": "user_management",
            "label": "User Management",
            "permissions": [ { "key": ..., "label": ..., "operation": ..., ... } ]
          }
        ]
      }
    ]
    """
    apps_qs = get_registered_apps()
    if app_key:
        apps_qs = apps_qs.filter(key=app_key)
    apps = list(apps_qs)
    app_ids = [app.id for app in apps]

    # Two queries for the whole tree rather than two per app. The category maps
    # and the dependency edges are both fetched for every app at once and
    # grouped in Python, so adding an app to the project no longer adds a pair
    # of round trips to this endpoint (§6, N+1 prevention).
    filters: dict = {
        "endpoint__application_id__in": app_ids,
        "is_visible_in_ui": True,
    }
    if not include_inactive:
        filters["endpoint__is_active"] = True
        filters["category__is_active"] = True
    all_category_maps = (
        EndpointCategoryMap.objects.select_related(
            "endpoint",
            "endpoint__application",
            "endpoint__policy_model",
            "category",
        )
        .filter(**filters)
        .order_by("category__sort_order", "category__key", "sort_order")
    )
    maps_by_app: dict[Any, list[EndpointCategoryMap]] = {}
    for cm in all_category_maps:
        maps_by_app.setdefault(cm.endpoint.application_id, []).append(cm)

    forward_deps_by_endpoint: dict[Any, list[str]] = {}
    for source_id, target_key in PolicyDependency.objects.filter(
        source_endpoint__application_id__in=app_ids,
        direction__in=["forward", "bidirectional"],
        is_active=True,
    ).values_list("source_endpoint_id", "target_endpoint__permission_key"):
        forward_deps_by_endpoint.setdefault(source_id, []).append(target_key)

    tree = []
    for app in apps:
        groups: dict[str, dict] = {}
        for cm in maps_by_app.get(app.id, []):
            cat_key = cm.category.key
            if cat_key not in groups:
                groups[cat_key] = {
                    "key": cat_key,
                    "label": cm.category.display_name,
                    "permissions": [],
                }
            ep = cm.endpoint
            forward_deps = forward_deps_by_endpoint.get(ep.id, [])
            groups[cat_key]["permissions"].append(
                {
                    "key": ep.permission_key,
                    "label": cm.display_label or ep.display_name,
                    "operation": ep.operation_type,
                    "description": ep.description,
                    "risk_level": ep.risk_level,
                    "is_sensitive": cm.is_sensitive,
                    "is_active": ep.is_active,
                    "is_deprecated": ep.is_deprecated,
                    "deprecated_at": ep.deprecated_at,
                    "disabled_at": ep.disabled_at,
                    "sunset_at": ep.sunset_at,
                    "replaced_by_permission_key": ep.replaced_by_permission_key,
                    "removal_ticket": ep.removal_ticket,
                    "removal_reason": ep.removal_reason,
                    "dependencies": forward_deps,
                }
            )

        tree.append({"app": app.key, "groups": list(groups.values())})

    return tree


def get_endpoint_dependencies(permission_key: str) -> dict:
    endpoint = get_endpoint_by_permission_key(permission_key)
    forward = list(
        PolicyDependency.objects.select_related("target_endpoint")
        .filter(source_endpoint=endpoint, direction__in=["forward", "bidirectional"], is_active=True)
        .values(
            "target_endpoint__permission_key",
            "dependency_type",
            "enforcement_mode",
            "reason",
        )
    )
    backward = list(
        PolicyDependency.objects.select_related("source_endpoint")
        .filter(target_endpoint=endpoint, direction__in=["backward", "bidirectional"], is_active=True)
        .values(
            "source_endpoint__permission_key",
            "dependency_type",
            "enforcement_mode",
            "reason",
        )
    )
    return {"forward": forward, "backward": backward}


def get_forward_dependencies(permission_key: str) -> QuerySet[PolicyDependency]:
    endpoint = get_endpoint_by_permission_key(permission_key)
    return PolicyDependency.objects.select_related("source_endpoint", "target_endpoint").filter(
        source_endpoint=endpoint,
        direction__in=["forward", "bidirectional"],
        is_active=True,
    )


def get_backward_dependencies(permission_key: str) -> QuerySet[PolicyDependency]:
    endpoint = get_endpoint_by_permission_key(permission_key)
    return PolicyDependency.objects.select_related("source_endpoint", "target_endpoint").filter(
        target_endpoint=endpoint,
        direction__in=["backward", "bidirectional"],
        is_active=True,
    )


def get_endpoint_versions(permission_key: str) -> QuerySet[PolicyEndpointVersion]:
    endpoint = get_endpoint_by_permission_key(permission_key)
    return PolicyEndpointVersion.objects.select_related("endpoint").filter(endpoint=endpoint).order_by("-created_at")


def get_endpoint_changelog(permission_key: str) -> QuerySet[PolicyChangeLog]:
    endpoint = get_endpoint_by_permission_key(permission_key)
    return PolicyChangeLog.objects.filter(endpoint=endpoint).order_by("-created_at")


def get_all_active_endpoints() -> QuerySet[PolicyEndpoint]:
    return PolicyEndpoint.objects.select_related("application", "policy_model").filter(is_active=True)


def get_endpoints_missing_categories() -> list[str]:
    endpoints_with_cats = EndpointCategoryMap.objects.values_list("endpoint_id", flat=True)
    missing = PolicyEndpoint.objects.filter(is_active=True).exclude(id__in=endpoints_with_cats)
    return list(missing.values_list("permission_key", flat=True))


def get_endpoints_missing_dependencies(risk_levels: list[str] | None = None) -> list[str]:
    if risk_levels is None:
        risk_levels = ["high", "critical"]
    endpoints_with_deps = PolicyDependency.objects.values_list("source_endpoint_id", flat=True)
    missing = PolicyEndpoint.objects.filter(
        is_active=True,
        risk_level__in=risk_levels,
        is_dependency_root=False,
    ).exclude(id__in=endpoints_with_deps)
    return list(missing.values_list("permission_key", flat=True))


def get_duplicate_permission_keys() -> list[str]:
    from django.db.models import Count

    return list(
        PolicyEndpoint.objects.values("permission_key")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
        .values_list("permission_key", flat=True)
    )
