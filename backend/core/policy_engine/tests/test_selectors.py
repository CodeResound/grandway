from django.test import TestCase

from core.policy_engine.constants import DependencyDirection, OperationType, RiskLevel
from core.policy_engine.exceptions import (
    PolicyEndpointNotFoundError,
)
from core.policy_engine.selectors import (
    get_endpoint_by_permission_key,
    get_endpoints_missing_categories,
    get_endpoints_missing_dependencies,
    get_registered_apps,
    get_ui_permission_tree,
)
from core.policy_engine.services import (
    add_dependency,
    map_endpoint_to_category,
    register_application,
    register_category,
    register_endpoint,
    register_model,
)


class GetRegisteredAppsTest(TestCase):
    def test_returns_active_apps(self):
        register_application(key="auth", display_name="Auth")
        register_application(key="documents", display_name="Documents")
        apps = get_registered_apps()
        self.assertEqual(apps.count(), 2)

    def test_excludes_inactive(self):
        register_application(key="auth", display_name="Auth")
        from core.policy_engine.models import PolicyApplication

        PolicyApplication.objects.filter(key="auth").update(is_active=False)
        apps = get_registered_apps()
        self.assertEqual(apps.count(), 0)


class GetEndpointByPermissionKeyTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )

    def test_returns_endpoint(self):
        ep = get_endpoint_by_permission_key("auth.user.create")
        self.assertEqual(ep.permission_key, "auth.user.create")

    def test_raises_not_found(self):
        with self.assertRaises(PolicyEndpointNotFoundError):
            get_endpoint_by_permission_key("auth.user.nonexistent")


class GetUIPermissionTreeTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_model(app_key="auth", key="user", display_name="User")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            model_key="user",
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
            model_key="user",
            risk_level=RiskLevel.HIGH,
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
            model_key="user",
        )
        register_category(key="user_management", display_name="User Management", app_key="auth")
        map_endpoint_to_category("auth.user.create", "user_management")
        map_endpoint_to_category("auth.user.delete", "user_management", is_sensitive=True)
        add_dependency("auth.user.delete", "auth.user.read", direction=DependencyDirection.FORWARD)

    def test_tree_structure(self):
        tree = get_ui_permission_tree(app_key="auth")
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["app"], "auth")
        groups = tree[0]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["key"], "user_management")

    def test_permission_entries(self):
        tree = get_ui_permission_tree(app_key="auth")
        perms = tree[0]["groups"][0]["permissions"]
        perm_keys = [p["key"] for p in perms]
        self.assertIn("auth.user.create", perm_keys)
        self.assertIn("auth.user.delete", perm_keys)

    def test_forward_dependencies_in_tree(self):
        tree = get_ui_permission_tree(app_key="auth")
        delete_perm = next(p for p in tree[0]["groups"][0]["permissions"] if p["key"] == "auth.user.delete")
        self.assertIn("auth.user.read", delete_perm["dependencies"])

    def test_sensitive_flag(self):
        tree = get_ui_permission_tree(app_key="auth")
        delete_perm = next(p for p in tree[0]["groups"][0]["permissions"] if p["key"] == "auth.user.delete")
        self.assertTrue(delete_perm["is_sensitive"])


class GetEndpointsMissingCategoriesTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )

    def test_endpoint_without_category_is_in_list(self):
        missing = get_endpoints_missing_categories()
        self.assertIn("auth.user.create", missing)

    def test_endpoint_with_category_not_in_list(self):
        register_category(key="user_mgmt", display_name="User Management")
        map_endpoint_to_category("auth.user.create", "user_mgmt")
        missing = get_endpoints_missing_categories()
        self.assertNotIn("auth.user.create", missing)


class GetEndpointsMissingDependenciesTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
            risk_level=RiskLevel.HIGH,
        )

    def test_high_risk_without_deps_is_in_list(self):
        missing = get_endpoints_missing_dependencies()
        self.assertIn("auth.user.delete", missing)

    def test_high_risk_with_deps_not_in_list(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        add_dependency("auth.user.delete", "auth.user.read")
        missing = get_endpoints_missing_dependencies()
        self.assertNotIn("auth.user.delete", missing)

    def test_high_risk_dependency_root_without_deps_not_in_list(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-login",
            permission_key="auth.user.login",
            operation_type=OperationType.CUSTOM,
            display_name="Login",
            risk_level=RiskLevel.HIGH,
            is_dependency_root=True,
        )
        missing = get_endpoints_missing_dependencies()
        self.assertNotIn("auth.user.login", missing)
        self.assertIn("auth.user.delete", missing)
