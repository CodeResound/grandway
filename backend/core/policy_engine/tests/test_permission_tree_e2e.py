"""
End-to-end test: UI Permission Tree for frontend permission assignment.

Simulates the real use case: an 'authenticate' app registers all its
user-management permissions via run_endpoint_lifecycle(), then the
frontend fetches GET /api/v1/policy/permissions/tree/ to render a
permission assignment UI.
"""

import json

from authenticate.services import build_access_token, issue_session
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from core.policy_engine.constants import CreatedByType, OperationType, RiskLevel
from core.policy_engine.lifecycle import run_endpoint_lifecycle
from core.policy_engine.selectors import get_ui_permission_tree

User = get_user_model()


def session_token(user) -> str:
    """Mint a session-bound access token (the project default auth requires a sid)."""
    session, _ = issue_session(user=user, device_id="test-device")
    return build_access_token(user, session, must_change_password=False)


def _register_authenticate_app():
    """Register a realistic set of permissions for an 'authenticate' app."""

    base = {
        "app_key": "authenticate",
        "app_display_name": "Authentication",
        "model_key": "user",
        "model_display_name": "User",
        "category_key": "user_management",
        "category_display_name": "User Management",
    }

    # 1. List users — no deps, low risk
    run_endpoint_lifecycle(
        config={
            **base,
            "endpoint_key": "user-list",
            "permission_key": "authenticate.user.list",
            "operation_type": OperationType.LIST,
            "display_name": "List Users",
            "description": "View all registered users.",
            "http_method": "GET",
            "route_pattern": "/api/v1/auth/users/",
            "risk_level": RiskLevel.LOW,
            "version": "1.0.0",
            "dependencies": [],
        },
        created_by_type=CreatedByType.AI,
        created_by_identifier="claude-sonnet-4-6",
    )

    # 2. Read user — no deps, low risk
    run_endpoint_lifecycle(
        config={
            **base,
            "endpoint_key": "user-read",
            "permission_key": "authenticate.user.read",
            "operation_type": OperationType.READ,
            "display_name": "View User",
            "description": "View a single user's profile and account details.",
            "http_method": "GET",
            "route_pattern": "/api/v1/auth/users/<id>/",
            "risk_level": RiskLevel.LOW,
            "version": "1.0.0",
            "dependencies": [],
        },
        created_by_type=CreatedByType.AI,
        created_by_identifier="claude-sonnet-4-6",
    )

    # 3. Create user — no deps, medium risk
    run_endpoint_lifecycle(
        config={
            **base,
            "endpoint_key": "user-create",
            "permission_key": "authenticate.user.create",
            "operation_type": OperationType.CREATE,
            "display_name": "Create User",
            "description": "Create a new user account.",
            "http_method": "POST",
            "route_pattern": "/api/v1/auth/users/",
            "risk_level": RiskLevel.MEDIUM,
            "version": "1.0.0",
            "dependencies": [],
        },
        created_by_type=CreatedByType.AI,
        created_by_identifier="claude-sonnet-4-6",
    )

    # 4. Update user — requires read, medium risk
    run_endpoint_lifecycle(
        config={
            **base,
            "endpoint_key": "user-update",
            "permission_key": "authenticate.user.update",
            "operation_type": OperationType.UPDATE,
            "display_name": "Edit User",
            "description": "Edit a user's profile or account settings.",
            "http_method": "PATCH",
            "route_pattern": "/api/v1/auth/users/<id>/",
            "risk_level": RiskLevel.MEDIUM,
            "version": "1.0.0",
            "dependencies": [
                {
                    "target_permission_key": "authenticate.user.read",
                    "direction": "forward",
                    "dependency_type": "requires",
                    "enforcement_mode": "strict",
                    "reason": "Must be able to view a user before editing them.",
                }
            ],
        },
        created_by_type=CreatedByType.AI,
        created_by_identifier="claude-sonnet-4-6",
    )

    # 5. Delete user — requires read, high risk, sensitive
    run_endpoint_lifecycle(
        config={
            **base,
            "endpoint_key": "user-delete",
            "permission_key": "authenticate.user.delete",
            "operation_type": OperationType.DELETE,
            "display_name": "Delete User",
            "description": "Permanently delete or deactivate a user account.",
            "http_method": "DELETE",
            "route_pattern": "/api/v1/auth/users/<id>/",
            "risk_level": RiskLevel.HIGH,
            "version": "1.0.0",
            "dependencies": [
                {
                    "target_permission_key": "authenticate.user.read",
                    "direction": "forward",
                    "dependency_type": "requires",
                    "enforcement_mode": "strict",
                    "reason": "Must be able to view a user before deleting them.",
                }
            ],
        },
        created_by_type=CreatedByType.AI,
        created_by_identifier="claude-sonnet-4-6",
    )

    # 6. Change password (custom) — requires read, high risk, sensitive
    run_endpoint_lifecycle(
        config={
            **base,
            "endpoint_key": "user-change-password",
            "permission_key": "authenticate.user.change_password",
            "operation_type": OperationType.CUSTOM,
            "display_name": "Change User Password",
            "description": "Reset or change a user's password on their behalf.",
            "http_method": "POST",
            "route_pattern": "/api/v1/auth/users/<id>/change-password/",
            "risk_level": RiskLevel.HIGH,
            "version": "1.0.0",
            "dependencies": [
                {
                    "target_permission_key": "authenticate.user.read",
                    "direction": "forward",
                    "dependency_type": "requires",
                    "enforcement_mode": "strict",
                    "reason": "Must be able to view a user before changing their password.",
                }
            ],
        },
        created_by_type=CreatedByType.AI,
        created_by_identifier="claude-sonnet-4-6",
    )


class UIPermissionTreeE2ETest(APITestCase):
    """
    End-to-end: register realistic permissions, then fetch the tree
    via the HTTP endpoint as a frontend would.
    """

    def setUp(self):
        _register_authenticate_app()
        self.staff = User.objects.create_user(username="admin", password="pass", is_staff=True)
        token = session_token(self.staff)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_tree_endpoint_returns_200(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        self.assertEqual(response.status_code, 200)

    def test_response_envelope(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("data", body)

    def test_tree_contains_authenticate_app(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        data = response.json()["data"]
        app_keys = [entry["app"] for entry in data]
        self.assertIn("authenticate", app_keys)

    def test_user_management_group_present(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        data = response.json()["data"]
        auth_entry = next(e for e in data if e["app"] == "authenticate")
        group_keys = [g["key"] for g in auth_entry["groups"]]
        self.assertIn("user_management", group_keys)

    def test_all_six_permissions_present(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        data = response.json()["data"]
        auth_entry = next(e for e in data if e["app"] == "authenticate")
        user_mgmt = next(g for g in auth_entry["groups"] if g["key"] == "user_management")
        perm_keys = {p["key"] for p in user_mgmt["permissions"]}
        self.assertIn("authenticate.user.list", perm_keys)
        self.assertIn("authenticate.user.read", perm_keys)
        self.assertIn("authenticate.user.create", perm_keys)
        self.assertIn("authenticate.user.update", perm_keys)
        self.assertIn("authenticate.user.delete", perm_keys)
        self.assertIn("authenticate.user.change_password", perm_keys)

    def test_delete_is_sensitive(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        data = response.json()["data"]
        auth_entry = next(e for e in data if e["app"] == "authenticate")
        user_mgmt = next(g for g in auth_entry["groups"] if g["key"] == "user_management")
        delete_perm = next(p for p in user_mgmt["permissions"] if p["key"] == "authenticate.user.delete")
        self.assertTrue(delete_perm["is_sensitive"])

    def test_delete_has_forward_dependency_on_read(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        data = response.json()["data"]
        auth_entry = next(e for e in data if e["app"] == "authenticate")
        user_mgmt = next(g for g in auth_entry["groups"] if g["key"] == "user_management")
        delete_perm = next(p for p in user_mgmt["permissions"] if p["key"] == "authenticate.user.delete")
        self.assertIn("authenticate.user.read", delete_perm["dependencies"])

    def test_list_has_no_dependencies(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        data = response.json()["data"]
        auth_entry = next(e for e in data if e["app"] == "authenticate")
        user_mgmt = next(g for g in auth_entry["groups"] if g["key"] == "user_management")
        list_perm = next(p for p in user_mgmt["permissions"] if p["key"] == "authenticate.user.list")
        self.assertEqual(list_perm["dependencies"], [])

    def test_app_filter_query_param(self):
        response = self.client.get("/api/v1/policy/permissions/tree/?app=authenticate")
        data = response.json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["app"], "authenticate")

    def test_full_tree_shape_for_inspection(self):
        """Prints the full tree JSON — useful for manual review."""
        response = self.client.get("/api/v1/policy/permissions/tree/")
        print("\n\n=== UI Permission Tree (full response) ===")
        print(json.dumps(response.json(), indent=2))
        print("==========================================\n")
        self.assertEqual(response.status_code, 200)


class UIPermissionTreeSelectorTest(APITestCase):
    """Verifies the selector layer directly, independent of HTTP."""

    def setUp(self):
        _register_authenticate_app()

    def test_selector_returns_correct_shape(self):
        tree = get_ui_permission_tree()
        self.assertIsInstance(tree, list)
        self.assertEqual(len(tree), 1)
        app = tree[0]
        self.assertEqual(app["app"], "authenticate")
        self.assertIn("groups", app)
        group = app["groups"][0]
        self.assertIn("key", group)
        self.assertIn("label", group)
        self.assertIn("permissions", group)
        perm = group["permissions"][0]
        for field in ("key", "label", "operation", "description", "risk_level", "is_sensitive", "dependencies"):
            self.assertIn(field, perm)

    def test_change_password_has_dependency(self):
        tree = get_ui_permission_tree()
        perms = tree[0]["groups"][0]["permissions"]
        cp = next(p for p in perms if p["key"] == "authenticate.user.change_password")
        self.assertIn("authenticate.user.read", cp["dependencies"])

    def test_query_count_does_not_scale_with_endpoint_count(self):
        """Regression test: get_ui_permission_tree() issues one dependency
        query per app, not one per endpoint — the query count for a single
        app must stay fixed as its endpoint count grows."""
        with self.assertNumQueries(3):
            get_ui_permission_tree(app_key="authenticate")

        extra_base = {
            "app_key": "extra",
            "app_display_name": "Extra",
            "operation_type": OperationType.READ,
            "risk_level": RiskLevel.LOW,
            "version": "1.0.0",
            "category_key": "extra_category",
            "category_display_name": "Extra Category",
        }
        for i in range(10):
            run_endpoint_lifecycle(
                config={
                    **extra_base,
                    "endpoint_key": f"item-{i}",
                    "permission_key": f"extra.item.read{i}",
                    "display_name": f"Read Item {i}",
                },
                created_by_type=CreatedByType.SYSTEM,
            )

        with self.assertNumQueries(3):
            get_ui_permission_tree(app_key="extra")

    def test_query_count_does_not_scale_with_app_count(self):
        """Regression test: the unfiltered tree costs the same as one app's.

        The per-app fan-out is the one that actually grows in this project —
        ``INSTALLED_APPS`` gains a module far more often than a single app gains
        an endpoint. Fetching the category maps and the dependency edges once
        for every app and grouping them in Python keeps this at three queries;
        looping the two queries per app made the admin permission screen cost
        two round trips for every module ever added (§6, N+1 prevention).
        """
        for app_index in range(5):
            run_endpoint_lifecycle(
                config={
                    "app_key": f"app{app_index}",
                    "app_display_name": f"App {app_index}",
                    "endpoint_key": "thing-read",
                    "permission_key": f"app{app_index}.thing.read",
                    "display_name": "Read Thing",
                    "operation_type": OperationType.READ,
                    "risk_level": RiskLevel.LOW,
                    "version": "1.0.0",
                    "category_key": f"app{app_index}_category",
                    "category_display_name": f"App {app_index} Category",
                },
                created_by_type=CreatedByType.SYSTEM,
            )

        with self.assertNumQueries(3):
            tree = get_ui_permission_tree()

        self.assertGreaterEqual(len(tree), 5)
