"""
Management command: validate_policy_engine

Validates the policy registry against 15 rules: rules 1-10 from
policy_engine_prompt.md §19 (database self-consistency), plus five drift/
integrity rules — rule 11 (registry declarations ↔ database state), rule 12
(registered route + method ↔ actual Django URL routes), rule 13 (each active
endpoint's current_version has a matching, content-consistent version
record), rule 14 (every routed /api/v1/ (path, method) pair is covered
by a registered endpoint — the reverse of rule 12; closes the gap where a
view wired into urls.py with no POLICY_ENDPOINTS entry previously passed
every check), and rule 15 (the denormalized lifecycle timestamps
deprecated_at/disabled_at agree with the is_deprecated/is_active booleans).

Rules 12 and 14 are method-aware, not just path-aware: a single URL path
routinely backs multiple registry entries (e.g. GET vs PATCH on the same
/roles/<id>/ path, each its own permission_key/risk_level/dependencies), so
"this path exists somewhere in the registry" is not the same claim as
"every HTTP verb this path responds to has its own registered permission."

Usage:
    python manage.py validate_policy_engine
    python manage.py validate_policy_engine --strict  # exit 1 on any error
"""

import re

from django.core.management.base import BaseCommand

from core.policy_engine.registry import load_registry_configs_from_installed_apps
from core.policy_engine.selectors import (
    get_all_active_endpoints,
    get_duplicate_permission_keys,
    get_endpoints_missing_categories,
    get_endpoints_missing_dependencies,
)

_PERMISSION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

# Routes under /api/v1/ that are deliberately NOT policy-engine-registered.
# Every entry needs a justification comment here — an empty set is the goal.
_ROUTE_COVERAGE_ALLOWLIST: set[str] = set()

# Matches one URL path parameter, with or without a converter prefix:
# "<uuid:organization_id>", "<str:app_key>", "<id>".
_ROUTE_PARAM_RE = re.compile(r"<[^<>]+>")


def _normalize_route(route: str) -> str:
    """Normalize a route pattern for comparison: every path parameter collapses
    to the same placeholder (param names and converters are not identity), and
    a leading slash is guaranteed."""
    route = _ROUTE_PARAM_RE.sub("{}", route)
    if not route.startswith("/"):
        route = "/" + route
    return route


def _view_methods(callback) -> set[str] | None:
    """Return the uppercase HTTP methods a resolved URL entry's view actually
    implements, or None if that can't be determined (e.g. a plain
    function-based view with no DRF/Django class-based-view metadata) —
    callers must treat None permissively (fall back to a path-only check)
    rather than treating it as "implements nothing".

    "options" is deliberately excluded: DRF's APIView.options() is inherited
    by every subclass, so hasattr(cls, "options") is True for every endpoint
    regardless of what the app author wrote — it is framework-level
    introspection, not a per-endpoint registerable action."""
    actions = getattr(callback, "actions", None)  # DRF ViewSet routed via a Router
    if actions:
        return {method.upper() for method in actions}
    cls = getattr(callback, "cls", None)  # Django/DRF class-based view (.as_view())
    if cls is None:
        return None
    verbs = ("get", "post", "put", "patch", "delete", "head", "trace")
    return {verb.upper() for verb in verbs if hasattr(cls, verb)}


def _collect_actual_route_methods() -> dict[str, set[str] | None]:
    """Walk Django's root URL resolver and return, for the normalized full
    path of every routable URL pattern, the set of HTTP methods its view
    implements (None = unknown/unresolvable — see _view_methods). Best-effort:
    regex-based re_path entries are included as their raw pattern string and
    will simply never match anything registered."""
    from django.urls import get_resolver

    routes: dict[str, set[str] | None] = {}

    def _walk(resolver, prefix: str) -> None:
        for entry in resolver.url_patterns:
            pattern = str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                _walk(entry, prefix + pattern)
            else:
                routes[_normalize_route(prefix + pattern)] = _view_methods(entry.callback)

    _walk(get_resolver(), "/")
    return routes


class Command(BaseCommand):
    help = "Validate the Core Policy Engine registry for completeness and consistency."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="Exit with code 1 if any validation errors are found.",
        )

    def handle(self, *args, **options):
        errors: list[str] = []

        # Rule 1: Check for duplicate permission keys
        duplicate_keys = get_duplicate_permission_keys()
        for key in duplicate_keys:
            errors.append(f"ERROR: Permission key '{key}' is duplicated.")

        # Rule 2: Endpoints without UI category mapping
        missing_categories = get_endpoints_missing_categories()
        for perm_key in missing_categories:
            errors.append(f"ERROR: Endpoint '{perm_key}' has no UI category mapping.")

        # Rule 3: High/critical endpoints without dependency metadata
        missing_deps = get_endpoints_missing_dependencies(risk_levels=["high", "critical"])
        for perm_key in missing_deps:
            errors.append(f"ERROR: Endpoint '{perm_key}' has no dependency metadata.")

        # Rule 4: Endpoints without operation type (should never happen via services, but check)
        from core.policy_engine.models import PolicyEndpoint

        no_operation = PolicyEndpoint.objects.filter(is_active=True, operation_type="")
        for ep in no_operation:
            errors.append(f"ERROR: Endpoint '{ep.permission_key}' has no operation type.")

        # Rule 5: Deprecated endpoints still marked is_active=True — an intentional
        # nudge, not an error: deprecated-but-active is the expected sunset window
        # between deprecate_endpoint() and disable_endpoint().
        deprecated_active = PolicyEndpoint.objects.filter(is_deprecated=True, is_active=True)
        for ep in deprecated_active:
            errors.append(
                f"WARNING: Endpoint '{ep.permission_key}' is deprecated but still active — "
                "schedule disablement via disable_endpoint() once its sunset window ends."
            )

        # Rule 6: Broken dependency references (target endpoint not active)
        from core.policy_engine.models import PolicyDependency

        broken_deps = PolicyDependency.objects.filter(
            is_active=True,
            target_endpoint__is_active=False,
        ).select_related("source_endpoint", "target_endpoint")
        for dep in broken_deps:
            errors.append(
                f"ERROR: Dependency from '{dep.source_endpoint.permission_key}' "
                f"references inactive target '{dep.target_endpoint.permission_key}'."
            )

        # Rule 7: Missing version records for active endpoints
        from core.policy_engine.models import PolicyEndpointVersion

        endpoints_with_versions = PolicyEndpointVersion.objects.values_list("endpoint_id", flat=True)
        missing_versions = (
            get_all_active_endpoints().exclude(id__in=endpoints_with_versions).values_list("permission_key", flat=True)
        )
        for perm_key in missing_versions:
            errors.append(f"ERROR: Endpoint '{perm_key}' has no version record.")

        # Rule 8: Missing changelog records for active endpoints
        from core.policy_engine.models import PolicyChangeLog

        endpoints_with_changelogs = PolicyChangeLog.objects.filter(endpoint__isnull=False).values_list(
            "endpoint_id", flat=True
        )
        missing_changelogs = (
            get_all_active_endpoints()
            .exclude(id__in=endpoints_with_changelogs)
            .values_list("permission_key", flat=True)
        )
        for perm_key in missing_changelogs:
            errors.append(f"ERROR: Endpoint '{perm_key}' has no changelog record.")

        # Rule 9: Custom endpoints without a description
        no_description = PolicyEndpoint.objects.filter(
            is_active=True,
            operation_type="custom",
            description="",
        )
        for ep in no_description:
            errors.append(f"ERROR: Custom endpoint '{ep.permission_key}' has no description.")

        # Rule 10: Endpoints with invalid permission key format
        for ep in get_all_active_endpoints():
            if not _PERMISSION_KEY_RE.match(ep.permission_key):
                errors.append(f"ERROR: Endpoint '{ep.permission_key}' has an invalid permission key format.")

        # Rule 11: Registry ↔ database drift
        declared_configs = load_registry_configs_from_installed_apps()
        declared_by_key = {c["permission_key"]: c for c in declared_configs if c.get("permission_key")}
        db_endpoints = {ep.permission_key: ep for ep in get_all_active_endpoints()}

        for perm_key in sorted(set(db_endpoints) - set(declared_by_key)):
            errors.append(
                f"ERROR: Endpoint '{perm_key}' is active in the database but declared in no "
                "registry.py — stale row; deprecate it or restore its declaration."
            )
        for perm_key in sorted(set(declared_by_key) - set(db_endpoints)):
            errors.append(
                f"ERROR: Endpoint '{perm_key}' is declared in a registry.py but missing from the "
                "database — run sync_policy_registry."
            )
        for perm_key, config in declared_by_key.items():
            ep = db_endpoints.get(perm_key)
            if ep is None:
                continue
            declared_route = config.get("route_pattern", "")
            declared_method = config.get("http_method", "")
            if declared_route and declared_route != ep.route_pattern:
                errors.append(
                    f"ERROR: Endpoint '{perm_key}' route drift — registry declares "
                    f"'{declared_route}' but the database has '{ep.route_pattern}'."
                )
            if declared_method and declared_method != ep.http_method:
                errors.append(
                    f"ERROR: Endpoint '{perm_key}' HTTP method drift — registry declares "
                    f"'{declared_method}' but the database has '{ep.http_method}'."
                )

        # Rule 12: Registered route + method ↔ actual Django URL routes
        actual_route_methods = _collect_actual_route_methods()
        for ep in get_all_active_endpoints():
            if not ep.route_pattern:
                continue
            normalized = _normalize_route(ep.route_pattern)
            if normalized not in actual_route_methods:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' registers route "
                    f"'{ep.route_pattern}' but no actual URL pattern matches it."
                )
                continue
            methods = actual_route_methods[normalized]
            if ep.http_method and methods is not None and ep.http_method.upper() not in methods:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' registers route '{ep.route_pattern}' "
                    f"with method '{ep.http_method}', but the actual view at that path only "
                    f"implements: {', '.join(sorted(methods)) or '(none)'}."
                )

        # Rule 13: current_version must have a matching, content-consistent version record
        from core.policy_engine.models import PolicyEndpointVersion as _Version

        for ep in get_all_active_endpoints():
            current = _Version.objects.filter(endpoint=ep, version=ep.current_version).first()
            if current is None:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' has current_version "
                    f"'{ep.current_version}' but no matching version record exists."
                )
                continue
            content_fields = ("route_pattern", "http_method", "operation_type")
            drift = [f for f in content_fields if getattr(current, f) != getattr(ep, f)]
            if drift:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' current version record "
                    f"'{ep.current_version}' has drifted from the live endpoint on: {', '.join(drift)}."
                )

        # Rule 14: reverse of rule 12 — every routed /api/v1/ (path, method)
        # pair must be covered by *some* registered PolicyEndpoint (regardless
        # of is_active — a disabled endpoint mid-sunset-window whose URL
        # hasn't been removed yet must not false-positive here).
        covered_pairs: set[tuple[str, str]] = set()
        for route_pattern, http_method in PolicyEndpoint.objects.exclude(route_pattern="").values_list(
            "route_pattern", "http_method"
        ):
            if not http_method:
                continue
            covered_pairs.add((_normalize_route(route_pattern), http_method.upper()))

        for route, methods in sorted(actual_route_methods.items()):
            if not route.startswith("/api/v1/"):
                continue
            if route in _ROUTE_COVERAGE_ALLOWLIST:
                continue
            if methods is None:
                # Unknown view type (no DRF/Django CBV metadata) — fall back to
                # path-only coverage to avoid false positives on views this
                # command cannot introspect.
                if not any(covered_route == route for covered_route, _method in covered_pairs):
                    errors.append(
                        f"ERROR: Route '{route}' is wired in the URL conf but no registered "
                        "PolicyEndpoint covers it — add a POLICY_ENDPOINTS entry (CLAUDE.md §35)."
                    )
                continue
            for method in sorted(methods):
                if (route, method) not in covered_pairs:
                    errors.append(
                        f"ERROR: Route '{route}' method {method} is wired in the URL conf but no "
                        "registered PolicyEndpoint covers it — add a POLICY_ENDPOINTS entry (CLAUDE.md §35)."
                    )

        # Rule 15: lifecycle boolean ↔ timestamp consistency. The denormalized
        # retirement fields on PolicyEndpoint must agree with is_deprecated/
        # is_active — otherwise an audit query over the timestamps is wrong.
        # deprecate_endpoint/disable_endpoint/restore_endpoint keep them in sync;
        # this rule catches any drift introduced outside those service functions.
        for ep in PolicyEndpoint.objects.all():
            if ep.is_deprecated and ep.deprecated_at is None:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' is deprecated but has no " "deprecated_at timestamp."
                )
            if not ep.is_deprecated and ep.deprecated_at is not None:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' is not deprecated but still has a "
                    "deprecated_at timestamp — restore_endpoint() should have cleared it."
                )
            if not ep.is_active and ep.disabled_at is None:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' is disabled (is_active=False) but has "
                    "no disabled_at timestamp."
                )
            if ep.is_active and ep.disabled_at is not None:
                errors.append(
                    f"ERROR: Endpoint '{ep.permission_key}' is active but still has a disabled_at "
                    "timestamp — restore_endpoint() should have cleared it."
                )

        # Output results
        if errors:
            for error in errors:
                if error.startswith("ERROR"):
                    self.stderr.write(self.style.ERROR(error))
                else:
                    self.stdout.write(self.style.WARNING(error))
            self.stderr.write(self.style.ERROR(f"\nPolicy Engine Validation Failed: {len(errors)} issue(s) found."))
            if options["strict"]:
                raise SystemExit(1)
        else:
            self.stdout.write(self.style.SUCCESS("Policy Engine Validation Passed"))
