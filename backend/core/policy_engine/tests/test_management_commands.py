from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.policy_engine.constants import OperationType, RiskLevel
from core.policy_engine.models import PolicyEndpoint
from core.policy_engine.services import (
    map_endpoint_to_category,
    register_application,
    register_category,
    register_endpoint,
)

_VALIDATE_LOADER = (
    "core.policy_engine.management.commands.validate_policy_engine.load_registry_configs_from_installed_apps"
)
_ROUTES_COLLECTOR = "core.policy_engine.management.commands.validate_policy_engine._collect_actual_route_methods"
_SYNC_LOADER = "core.policy_engine.management.commands.sync_policy_registry.load_registry_configs_from_installed_apps"


def _patched_registry(configs: list[dict]):
    """Pin the registry declarations the validate command compares against —
    rule 11 diffs registry ↔ DB, so tests must control both sides."""
    return patch(_VALIDATE_LOADER, return_value=configs)


def _patched_routes(routes: dict[str, set[str] | None]):
    """Pin the 'actual URL conf' rules 12/14 compare against — without this,
    every test would be flagged by rule 14 for the ~100 real /api/v1/ routes
    it doesn't register. Empty dict is the right pin for any test whose
    endpoints don't use real route_patterns at all. Keys are normalized
    paths; values are the set of HTTP methods that route's view implements
    (or None to simulate an unresolvable/unknown view type)."""
    return patch(_ROUTES_COLLECTOR, return_value=routes)


def _declared(permission_key: str, **extra) -> dict:
    return {"permission_key": permission_key, **extra}


class ValidatePolicyEngineCommandTest(TestCase):
    def test_passes_when_registry_is_empty(self):
        out = StringIO()
        with _patched_registry([]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_passes_with_fully_registered_endpoint(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.read", "user_mgmt")

        out = StringIO()
        with _patched_registry([_declared("auth.user.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_fails_for_high_risk_without_dependencies(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
            risk_level=RiskLevel.HIGH,
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.delete", "user_mgmt")

        err = StringIO()
        with _patched_registry([_declared("auth.user.delete")]):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("no dependency metadata", err.getvalue())

    def test_passes_for_high_risk_dependency_root_without_dependencies(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-login",
            permission_key="auth.user.login",
            operation_type=OperationType.CUSTOM,
            display_name="Login",
            description="Authenticate with username/email and password.",
            risk_level=RiskLevel.HIGH,
            is_dependency_root=True,
        )
        register_category(key="account_access", display_name="Account Access")
        map_endpoint_to_category("auth.user.login", "account_access")

        out = StringIO()
        with _patched_registry([_declared("auth.user.login")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_fails_for_endpoint_without_category(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )

        err = StringIO()
        with _patched_registry([_declared("auth.user.create")]):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("no UI category mapping", err.getvalue())

    def test_fails_for_custom_endpoint_without_description(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
            description="",
        )
        register_category(key="security", display_name="Security")
        map_endpoint_to_category("auth.user.ban", "security")

        err = StringIO()
        with _patched_registry([_declared("auth.user.ban")]):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("no description", err.getvalue())

    def test_deprecated_active_endpoint_warns_with_disable_endpoint_nudge(self):
        from core.policy_engine.services import deprecate_endpoint

        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.read", "user_mgmt")
        deprecate_endpoint("auth.user.read", reason="Sunsetting.")

        out = StringIO()
        with _patched_registry([_declared("auth.user.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("schedule disablement via disable_endpoint()", out.getvalue())


class ValidateLifecycleConsistencyTest(TestCase):
    """Rule 15: the denormalized lifecycle timestamps must agree with the
    is_deprecated/is_active booleans."""

    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.read", "user_mgmt")

    def test_deprecated_without_deprecated_at_is_flagged(self):
        from core.policy_engine.services import deprecate_endpoint

        deprecate_endpoint("auth.user.read", reason="Sunsetting.")
        # Break the invariant behind the service layer's back.
        PolicyEndpoint.objects.filter(permission_key="auth.user.read").update(deprecated_at=None)

        err = StringIO()
        with _patched_registry([_declared("auth.user.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("no deprecated_at timestamp", err.getvalue())

    def test_consistent_deprecation_does_not_trip_rule_15(self):
        from core.policy_engine.services import deprecate_endpoint

        # deprecate_endpoint() sets deprecated_at, so rule 15 must stay silent
        # (the rule-5 sunset-window WARNING is expected and unrelated).
        deprecate_endpoint("auth.user.read", reason="Sunsetting.")

        err = StringIO()
        with _patched_registry([_declared("auth.user.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertNotIn("deprecated_at timestamp", err.getvalue())


class ValidateRegistryDriftTest(TestCase):
    """Rule 11: registry declarations ↔ database state."""

    def _register(self, route_pattern: str = "", http_method: str = "") -> None:
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
            route_pattern=route_pattern,
            http_method=http_method,
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.read", "user_mgmt")

    def test_stale_db_row_reported(self):
        self._register()
        err = StringIO()
        with _patched_registry([]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("declared in no", err.getvalue())
        self.assertIn("auth.user.read", err.getvalue())

    def test_unsynced_declaration_reported(self):
        err = StringIO()
        with _patched_registry([_declared("auth.user.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("missing from the", err.getvalue())
        self.assertIn("run sync_policy_registry", err.getvalue())

    def test_route_drift_reported(self):
        self._register(route_pattern="/api/v1/auth/users/")
        err = StringIO()
        with (
            _patched_registry([_declared("auth.user.read", route_pattern="/api/v1/auth/accounts/")]),
            _patched_routes({}),
        ):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("route drift", err.getvalue())

    def test_http_method_drift_reported(self):
        self._register(http_method="GET")
        err = StringIO()
        with _patched_registry([_declared("auth.user.read", http_method="POST")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("HTTP method drift", err.getvalue())


class ValidateRouteDriftTest(TestCase):
    """Rule 12: registered route + method ↔ actual Django URL routes."""

    def _register(self, route_pattern: str, http_method: str = "GET") -> None:
        register_application(key="policy_engine", display_name="Core Policy Engine")
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-read",
            permission_key="policy_engine.application.read",
            operation_type=OperationType.READ,
            display_name="View Policy Application Detail",
            route_pattern=route_pattern,
            http_method=http_method,
        )
        register_category(key="policy_admin", display_name="Policy Engine Administration")
        map_endpoint_to_category("policy_engine.application.read", "policy_admin")

    def test_registered_route_matching_real_url_passes(self):
        # Real route: core/policy_engine/urls.py registers apps/<str:app_key>/
        # under /api/v1/policy/ — param names/converters must not affect matching.
        # Pin the "actual routes" dict to just this one real route (already in
        # its normalized form, matching what _collect_actual_route_methods()
        # itself would produce) so rule 14 doesn't also flag the ~100 other
        # real /api/v1/ routes this test's single-endpoint fixture doesn't register.
        self._register("/api/v1/policy/apps/<app_key>/", http_method="GET")
        out = StringIO()
        with (
            _patched_registry(
                [_declared("policy_engine.application.read", route_pattern="/api/v1/policy/apps/<app_key>/")]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": {"GET"}}),
        ):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_registered_route_with_no_real_url_reported(self):
        self._register("/api/v1/policy/nonexistent/<app_key>/")
        err = StringIO()
        with _patched_registry([_declared("policy_engine.application.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("no actual URL pattern matches", err.getvalue())

    def test_registered_method_not_implemented_by_view_reported(self):
        # The real path exists, but the registry declares DELETE while the
        # patched view only actually implements GET — a mismatch rule 12
        # couldn't previously detect since it only ever checked the path.
        self._register("/api/v1/policy/apps/<app_key>/", http_method="DELETE")
        err = StringIO()
        with (
            _patched_registry(
                [
                    _declared(
                        "policy_engine.application.read",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="DELETE",
                    )
                ]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": {"GET"}}),
        ):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("only implements: GET", err.getvalue())

    def test_registered_method_matching_unknown_view_type_passes(self):
        # methods=None (collector couldn't introspect the view, e.g. a plain
        # function-based view) must fall back to a path-only check rather
        # than flagging every declared http_method as a mismatch.
        self._register("/api/v1/policy/apps/<app_key>/", http_method="DELETE")
        out = StringIO()
        with (
            _patched_registry(
                [
                    _declared(
                        "policy_engine.application.read",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="DELETE",
                    )
                ]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": None}),
        ):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())


class ValidateVersionIntegrityTest(TestCase):
    """Rule 13: current_version must have a matching, content-consistent version record."""

    def test_missing_version_record_reported(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.read", "user_mgmt")
        # Force a current_version with no matching version record.
        PolicyEndpoint.objects.filter(permission_key="auth.user.read").update(current_version="9.9.9")

        err = StringIO()
        with _patched_registry([_declared("auth.user.read")]), _patched_routes({}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("no matching version record", err.getvalue())

    def test_version_content_drift_reported(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
            route_pattern="/api/v1/auth/users/",
        )
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.read", "user_mgmt")
        # A route-only change with no version bump drifts the endpoint away
        # from its current version record's content.
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
            route_pattern="/api/v1/auth/accounts/",
        )

        err = StringIO()
        with (
            _patched_registry([_declared("auth.user.read", route_pattern="/api/v1/auth/accounts/")]),
            _patched_routes({}),
        ):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("current version record", err.getvalue())
        self.assertIn("drifted", err.getvalue())


class ValidateReverseRouteCoverageTest(TestCase):
    """Rule 14: every routed /api/v1/ (path, method) pair must be covered by
    a registered endpoint — the reverse of rule 12. This is the exact gap
    that let 5 endpoints ship without policy registration before the
    2026-07-12 audit (see .claude/FAILURE.md)."""

    def test_uncovered_real_route_reported(self):
        err = StringIO()
        with _patched_registry([]), _patched_routes({"/api/v1/policy/apps/{}/": {"GET"}}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("wired in the URL conf but no registered PolicyEndpoint covers it", err.getvalue())
        self.assertIn("/api/v1/policy/apps/{}/", err.getvalue())
        self.assertIn("method GET", err.getvalue())

    def test_registering_the_endpoint_clears_the_finding(self):
        register_application(key="policy_engine", display_name="Core Policy Engine")
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-list",
            permission_key="policy_engine.application.list",
            operation_type=OperationType.LIST,
            display_name="List Policy Applications",
            route_pattern="/api/v1/policy/apps/<app_key>/",
            http_method="GET",
        )
        register_category(key="policy_admin", display_name="Policy Engine Administration")
        map_endpoint_to_category("policy_engine.application.list", "policy_admin")

        out = StringIO()
        # _patched_routes must use the already-normalized form (matching what
        # _collect_actual_route_methods() itself would produce) since rule 14
        # compares it against _normalize_route(endpoint.route_pattern), not
        # the raw string.
        with (
            _patched_registry(
                [
                    _declared(
                        "policy_engine.application.list",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="GET",
                    )
                ]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": {"GET"}}),
        ):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_second_method_on_same_path_still_flagged(self):
        # The path is already covered for GET, but the same view also
        # implements PATCH with no matching registration — path-level
        # coverage alone would miss this; method-level coverage must not.
        register_application(key="policy_engine", display_name="Core Policy Engine")
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-list",
            permission_key="policy_engine.application.list",
            operation_type=OperationType.LIST,
            display_name="List Policy Applications",
            route_pattern="/api/v1/policy/apps/<app_key>/",
            http_method="GET",
        )
        register_category(key="policy_admin", display_name="Policy Engine Administration")
        map_endpoint_to_category("policy_engine.application.list", "policy_admin")

        err = StringIO()
        with (
            _patched_registry(
                [
                    _declared(
                        "policy_engine.application.list",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="GET",
                    )
                ]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": {"GET", "PATCH"}}),
        ):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertIn("method PATCH", err.getvalue())
        self.assertNotIn("method GET", err.getvalue())

    def test_registering_both_methods_clears_the_finding(self):
        register_application(key="policy_engine", display_name="Core Policy Engine")
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-list",
            permission_key="policy_engine.application.list",
            operation_type=OperationType.LIST,
            display_name="List Policy Applications",
            route_pattern="/api/v1/policy/apps/<app_key>/",
            http_method="GET",
        )
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-update",
            permission_key="policy_engine.application.update",
            operation_type=OperationType.UPDATE,
            display_name="Update Policy Application",
            route_pattern="/api/v1/policy/apps/<app_key>/",
            http_method="PATCH",
        )
        register_category(key="policy_admin", display_name="Policy Engine Administration")
        map_endpoint_to_category("policy_engine.application.list", "policy_admin")
        map_endpoint_to_category("policy_engine.application.update", "policy_admin")

        out = StringIO()
        with (
            _patched_registry(
                [
                    _declared(
                        "policy_engine.application.list",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="GET",
                    ),
                    _declared(
                        "policy_engine.application.update",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="PATCH",
                    ),
                ]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": {"GET", "PATCH"}}),
        ):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_allowlisted_route_is_skipped(self):
        from core.policy_engine.management.commands import validate_policy_engine as cmd

        route = "/api/v1/policy/apps/{}/"
        err = StringIO()
        with (
            _patched_registry([]),
            _patched_routes({route: {"GET"}}),
            patch.object(cmd, "_ROUTE_COVERAGE_ALLOWLIST", {route}),
        ):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertNotIn("no registered PolicyEndpoint covers it", err.getvalue())

    def test_non_api_v1_route_is_ignored(self):
        out = StringIO()
        with _patched_registry([]), _patched_routes({"/health/": {"GET"}, "/admin/login/": {"GET", "POST"}}):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())

    def test_disabled_endpoint_still_counts_as_covered(self):
        from core.policy_engine.services import deprecate_endpoint, disable_endpoint

        register_application(key="policy_engine", display_name="Core Policy Engine")
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-list",
            permission_key="policy_engine.application.list",
            operation_type=OperationType.LIST,
            display_name="List Policy Applications",
            route_pattern="/api/v1/policy/apps/<app_key>/",
            http_method="GET",
        )
        deprecate_endpoint("policy_engine.application.list", reason="Sunsetting.")
        disable_endpoint("policy_engine.application.list", reason="Sunset window ended.")

        err = StringIO()
        with _patched_registry([]), _patched_routes({"/api/v1/policy/apps/{}/": {"GET"}}):
            call_command("validate_policy_engine", stdout=StringIO(), stderr=err)
        self.assertNotIn("no registered PolicyEndpoint covers it", err.getvalue())

    def test_unknown_view_type_falls_back_to_path_only_check(self):
        # methods=None (collector couldn't introspect, e.g. a plain
        # function-based view) must fall back to a path-only check rather
        # than flagging every possible method as missing.
        register_application(key="policy_engine", display_name="Core Policy Engine")
        register_endpoint(
            app_key="policy_engine",
            endpoint_key="application-list",
            permission_key="policy_engine.application.list",
            operation_type=OperationType.LIST,
            display_name="List Policy Applications",
            route_pattern="/api/v1/policy/apps/<app_key>/",
            http_method="GET",
        )
        register_category(key="policy_admin", display_name="Policy Engine Administration")
        map_endpoint_to_category("policy_engine.application.list", "policy_admin")

        out = StringIO()
        with (
            _patched_registry(
                [
                    _declared(
                        "policy_engine.application.list",
                        route_pattern="/api/v1/policy/apps/<app_key>/",
                        http_method="GET",
                    )
                ]
            ),
            _patched_routes({"/api/v1/policy/apps/{}/": None}),
        ):
            call_command("validate_policy_engine", stdout=out, stderr=StringIO())
        self.assertIn("Validation Passed", out.getvalue())


class ViewMethodsUnitTest(TestCase):
    """Unit-level checks of _view_methods / _collect_actual_route_methods,
    independent of the management command — confirms the "options" exclusion
    and the None fallback for unresolvable/plain function-based views."""

    def test_options_excluded_for_a_real_get_only_apiview(self):
        from core.policy_engine.management.commands.validate_policy_engine import _view_methods
        from core.policy_engine.views import PolicyApplicationListView

        methods = _view_methods(PolicyApplicationListView.as_view())
        self.assertEqual(methods, {"GET"})
        self.assertNotIn("OPTIONS", methods)

    def test_api_view_decorated_function_view_is_introspected(self):
        # core.views.health/ready are DRF @api_view-decorated function views —
        # DRF's api_view() decorator builds a WrappedAPIView and sets .cls
        # just like a real class-based view, so these ARE introspectable
        # (not an example of the None fallback below).
        from core.policy_engine.management.commands.validate_policy_engine import _view_methods
        from core.views import health

        self.assertEqual(_view_methods(health), {"GET"})

    def test_unresolvable_callback_returns_none(self):
        # A genuinely bare callable with no DRF/Django CBV metadata at all
        # (no .actions, no .cls) — the case the None fallback exists for.
        from core.policy_engine.management.commands.validate_policy_engine import _view_methods

        def bare_view(request):
            return None

        self.assertIsNone(_view_methods(bare_view))


class SyncPolicyRegistryCommandTest(TestCase):
    _VALID_CONFIG = {
        "app_key": "auth",
        "endpoint_key": "user-read",
        "permission_key": "auth.user.read",
        "operation_type": "read",
        "display_name": "Read User",
        "category_key": "user_mgmt",
        "category_display_name": "User Management",
    }

    def test_runs_without_error_when_no_configs(self):
        """Simulate an empty registry to exercise the 'no configs' output path."""
        out = StringIO()
        with patch(_SYNC_LOADER, return_value=[]):
            call_command("sync_policy_registry", stdout=out, stderr=StringIO())
        self.assertIn("No POLICY_ENDPOINTS", out.getvalue())

    def test_dry_run_does_not_write(self):
        out = StringIO()
        call_command("sync_policy_registry", dry_run=True, stdout=out, stderr=StringIO())
        self.assertEqual(PolicyEndpoint.objects.count(), 0)

    def test_valid_config_syncs(self):
        out = StringIO()
        with patch(_SYNC_LOADER, return_value=[dict(self._VALID_CONFIG)]):
            call_command("sync_policy_registry", stdout=out, stderr=StringIO())
        self.assertTrue(PolicyEndpoint.objects.filter(permission_key="auth.user.read").exists())

    def test_invalid_config_aborts_before_any_write(self):
        bad_config = dict(self._VALID_CONFIG)
        bad_config["operation_type"] = "obliterate"
        err = StringIO()
        with patch(_SYNC_LOADER, return_value=[dict(self._VALID_CONFIG), bad_config]):
            with self.assertRaises(SystemExit):
                call_command("sync_policy_registry", stdout=StringIO(), stderr=err)
        self.assertIn("Invalid config", err.getvalue())
        self.assertIn("operation_type 'obliterate'", err.getvalue())
        # The valid config listed first must NOT have been written — validation
        # happens for all configs before any lifecycle write.
        self.assertEqual(PolicyEndpoint.objects.count(), 0)

    def test_missing_required_key_aborts(self):
        bad_config = dict(self._VALID_CONFIG)
        del bad_config["permission_key"]
        err = StringIO()
        with patch(_SYNC_LOADER, return_value=[bad_config]):
            with self.assertRaises(SystemExit):
                call_command("sync_policy_registry", stdout=StringIO(), stderr=err)
        self.assertIn("missing required key 'permission_key'", err.getvalue())
