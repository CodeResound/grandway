from django.test import TestCase

from core.policy_engine.constants import CreatedByType, OperationType, RiskLevel
from core.policy_engine.lifecycle import run_endpoint_lifecycle
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
from core.policy_engine.services import register_application, register_endpoint

SAMPLE_CONFIG = {
    "app_key": "authenticate",
    "model_key": "user",
    "endpoint_key": "user-delete",
    "permission_key": "authenticate.user.delete",
    "http_method": "DELETE",
    "route_pattern": "/api/v1/auth/users/<id>/",
    "view_import_path": "authenticate.views.UserDeleteView",
    "operation_type": OperationType.DELETE,
    "display_name": "Delete User",
    "description": "Allows deleting or deactivating a user account.",
    "risk_level": RiskLevel.HIGH,
    "version": "1.0.0",
    "category_key": "user_management",
    "category_display_name": "User Management",
    "change_summary": "Initial registration of user deletion endpoint.",
    "change_reason": "Endpoint created by AI coding lifecycle.",
}


class RunEndpointLifecycleTest(TestCase):
    def setUp(self):
        # Pre-create read endpoint so dependency can be registered
        register_application(key="authenticate", display_name="Authentication")
        register_endpoint(
            app_key="authenticate",
            endpoint_key="user-read",
            permission_key="authenticate.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )

    def _config(self, **overrides):
        cfg = dict(SAMPLE_CONFIG)
        cfg["dependencies"] = [
            {
                "target_permission_key": "authenticate.user.read",
                "direction": "forward",
                "dependency_type": "requires",
                "enforcement_mode": "strict",
                "reason": "Read access required before delete.",
            }
        ]
        cfg.update(overrides)
        return cfg

    def test_registers_app(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(PolicyApplication.objects.filter(key="authenticate").exists())

    def test_registers_model(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(PolicyModel.objects.filter(application__key="authenticate", key="user").exists())

    def test_registers_endpoint(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(PolicyEndpoint.objects.filter(permission_key="authenticate.user.delete").exists())

    def test_registers_category(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(PermissionCategory.objects.filter(key="user_management").exists())

    def test_maps_endpoint_to_category(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(
            EndpointCategoryMap.objects.filter(
                endpoint__permission_key="authenticate.user.delete",
                category__key="user_management",
            ).exists()
        )

    def test_creates_version_record(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(
            PolicyEndpointVersion.objects.filter(endpoint__permission_key="authenticate.user.delete").exists()
        )

    def test_registers_dependency(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertTrue(
            PolicyDependency.objects.filter(
                source_endpoint__permission_key="authenticate.user.delete",
                target_endpoint__permission_key="authenticate.user.read",
            ).exists()
        )

    def test_creates_changelog_as_ai(self):
        run_endpoint_lifecycle(
            config=self._config(),
            created_by_type=CreatedByType.AI,
            created_by_identifier="claude-sonnet",
        )
        log = PolicyChangeLog.objects.filter(
            endpoint__permission_key="authenticate.user.delete",
            created_by_type=CreatedByType.AI,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.created_by_identifier, "claude-sonnet")

    def test_idempotent(self):
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertEqual(PolicyEndpoint.objects.filter(permission_key="authenticate.user.delete").count(), 1)
        self.assertEqual(PermissionCategory.objects.filter(key="user_management").count(), 1)
        self.assertEqual(
            EndpointCategoryMap.objects.filter(endpoint__permission_key="authenticate.user.delete").count(),
            1,
        )

    def test_summary_returned(self):
        result = run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        self.assertIn("endpoint", result)
        self.assertEqual(result["endpoint"], "authenticate.user.delete")
        self.assertIn("category", result)
        self.assertIn("dependencies", result)

    def test_change_summary_and_reason_reach_changelog(self):
        from core.policy_engine.constants import ChangeType

        run_endpoint_lifecycle(config=self._config(), created_by_type=CreatedByType.AI)
        log = PolicyChangeLog.objects.filter(
            endpoint__permission_key="authenticate.user.delete",
            change_type=ChangeType.CREATED,
        ).first()
        self.assertEqual(log.summary, SAMPLE_CONFIG["change_summary"])
        self.assertEqual(log.reason, SAMPLE_CONFIG["change_reason"])

    def test_default_changelog_text_without_change_metadata(self):
        from core.policy_engine.constants import ChangeType

        config = self._config()
        config.pop("change_summary")
        config.pop("change_reason")
        run_endpoint_lifecycle(config=config, created_by_type=CreatedByType.AI)
        log = PolicyChangeLog.objects.filter(
            endpoint__permission_key="authenticate.user.delete",
            change_type=ChangeType.CREATED,
        ).first()
        self.assertEqual(log.summary, "Endpoint 'authenticate.user.delete' registered.")
        self.assertEqual(log.reason, "Initial registration.")
