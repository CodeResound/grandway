from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.policy_engine.constants import OperationType, RiskLevel
from core.policy_engine.services import (
    add_dependency,
    map_endpoint_to_category,
    register_application,
    register_category,
    register_endpoint,
)

User = get_user_model()


class PolicyAPIAuthTest(APITestCase):
    """Test that all policy API endpoints require authentication and staff access."""

    ENDPOINTS = [
        "/api/v1/policy/apps/",
        "/api/v1/policy/apps/auth/",
        "/api/v1/policy/permissions/tree/",
        "/api/v1/policy/endpoints/auth.user.create/",
        "/api/v1/policy/endpoints/auth.user.create/dependencies/",
        "/api/v1/policy/endpoints/auth.user.create/versions/",
        "/api/v1/policy/endpoints/auth.user.create/changelog/",
    ]

    def test_unauthenticated_returns_401(self):
        for url in self.ENDPOINTS:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
                f"Expected 401 for {url}, got {response.status_code}",
            )

    def test_non_staff_returns_403(self):
        user = User.objects.create_user(username="regular", password="pass", is_staff=False)
        token = str(AccessToken.for_user(user))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        for url in self.ENDPOINTS:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected 403 for {url}, got {response.status_code}",
            )


class PolicyApplicationListViewTest(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        token = str(AccessToken.for_user(self.staff))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        register_application(key="auth", display_name="Authentication")

    def test_returns_app_list(self):
        response = self.client.get("/api/v1/policy/apps/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        apps = response.data["data"]
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["key"], "auth")

    def test_success_envelope(self):
        response = self.client.get("/api/v1/policy/apps/")
        self.assertIn("success", response.data)
        self.assertIn("data", response.data)


class PolicyApplicationDetailViewTest(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        token = str(AccessToken.for_user(self.staff))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        register_application(key="auth", display_name="Authentication")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )

    def test_returns_app_detail(self):
        response = self.client.get("/api/v1/policy/apps/auth/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["key"], "auth")

    def test_includes_endpoints(self):
        response = self.client.get("/api/v1/policy/apps/auth/")
        endpoints = response.data["data"]["endpoints"]
        self.assertEqual(len(endpoints), 1)
        self.assertEqual(endpoints[0]["permission_key"], "auth.user.create")

    def test_not_found_returns_404(self):
        response = self.client.get("/api/v1/policy/apps/nonexistent/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UIPermissionTreeViewTest(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        token = str(AccessToken.for_user(self.staff))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        register_application(key="auth", display_name="Authentication")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        map_endpoint_to_category("auth.user.create", "user_mgmt")

    def test_returns_tree(self):
        response = self.client.get("/api/v1/policy/permissions/tree/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tree = response.data["data"]
        self.assertIsInstance(tree, list)
        self.assertEqual(tree[0]["app"], "auth")

    def test_filtered_by_app(self):
        register_application(key="docs", display_name="Documents")
        response = self.client.get("/api/v1/policy/permissions/tree/?app=auth")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tree = response.data["data"]
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["app"], "auth")


class PolicyEndpointDetailViewTest(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        token = str(AccessToken.for_user(self.staff))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        register_application(key="auth", display_name="Authentication")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )

    def test_returns_endpoint_detail(self):
        response = self.client.get("/api/v1/policy/endpoints/auth.user.create/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["permission_key"], "auth.user.create")

    def test_not_found_returns_404(self):
        response = self.client.get("/api/v1/policy/endpoints/auth.user.nonexistent/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class EndpointDependencyViewTest(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff", password="pass", is_staff=True)
        token = str(AccessToken.for_user(self.staff))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        register_application(key="auth", display_name="Authentication")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
            risk_level=RiskLevel.HIGH,
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        add_dependency("auth.user.delete", "auth.user.read")

    def test_returns_forward_dependencies(self):
        response = self.client.get("/api/v1/policy/endpoints/auth.user.delete/dependencies/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertIn("forward", data)
        forward_keys = [d["target_endpoint__permission_key"] for d in data["forward"]]
        self.assertIn("auth.user.read", forward_keys)
