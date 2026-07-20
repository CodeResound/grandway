from django.test import TestCase

from core.policy_engine.constants import (
    ChangeType,
    CreatedByType,
    DependencyDirection,
    DependencyType,
    ObjectType,
    OperationType,
    RiskLevel,
)
from core.policy_engine.models import (
    PolicyApplication,
    PolicyChangeLog,
    PolicyDependency,
    PolicyEndpoint,
    PolicyModel,
)


class PolicyApplicationModelTest(TestCase):
    def test_str(self):
        app = PolicyApplication(key="authenticate")
        self.assertEqual(str(app), "authenticate")

    def test_defaults(self):
        app = PolicyApplication.objects.create(key="test-app", display_name="Test App")
        self.assertEqual(app.current_version, "1.0.0")
        self.assertTrue(app.is_active)
        self.assertFalse(app.is_deprecated)

    def test_key_unique(self):
        PolicyApplication.objects.create(key="myapp", display_name="My App")
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            PolicyApplication.objects.create(key="myapp", display_name="Duplicate")


class PolicyModelModelTest(TestCase):
    def setUp(self):
        self.app = PolicyApplication.objects.create(key="auth", display_name="Auth")

    def test_str(self):
        pm = PolicyModel(application=self.app, key="user")
        pm.application = self.app
        self.assertEqual(str(pm), "auth.user")

    def test_unique_together(self):
        PolicyModel.objects.create(application=self.app, key="user", display_name="User")
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            PolicyModel.objects.create(application=self.app, key="user", display_name="Dup")


class PolicyEndpointModelTest(TestCase):
    def setUp(self):
        self.app = PolicyApplication.objects.create(key="auth", display_name="Auth")
        self.model = PolicyModel.objects.create(application=self.app, key="user", display_name="User")

    def test_str(self):
        ep = PolicyEndpoint(
            application=self.app,
            key="user-create",
            permission_key="auth.user.create",
        )
        self.assertEqual(str(ep), "auth.user.create")

    def test_permission_key_unique(self):
        PolicyEndpoint.objects.create(
            application=self.app,
            key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            PolicyEndpoint.objects.create(
                application=self.app,
                key="user-create-dup",
                permission_key="auth.user.create",
                operation_type=OperationType.CREATE,
                display_name="Create User Dup",
            )

    def test_operation_types(self):
        for op in OperationType.values:
            ep = PolicyEndpoint.objects.create(
                application=self.app,
                key=f"user-{op}",
                permission_key=f"auth.user.{op}",
                operation_type=op,
                display_name=f"{op} User",
            )
            self.assertEqual(ep.operation_type, op)
            ep.delete()

    def test_risk_levels(self):
        for idx, risk in enumerate(RiskLevel.values):
            ep = PolicyEndpoint.objects.create(
                application=self.app,
                key=f"ep-{idx}",
                permission_key=f"auth.user.action{idx}",
                operation_type=OperationType.CUSTOM,
                display_name="Action",
                risk_level=risk,
            )
            self.assertEqual(ep.risk_level, risk)
            ep.delete()

    def test_default_risk_level_is_low(self):
        ep = PolicyEndpoint.objects.create(
            application=self.app,
            key="user-list",
            permission_key="auth.user.list",
            operation_type=OperationType.LIST,
            display_name="List Users",
        )
        self.assertEqual(ep.risk_level, RiskLevel.LOW)

    def test_default_is_dependency_root_is_false(self):
        ep = PolicyEndpoint.objects.create(
            application=self.app,
            key="user-login",
            permission_key="auth.user.login",
            operation_type=OperationType.CUSTOM,
            display_name="Login",
        )
        self.assertFalse(ep.is_dependency_root)


class PolicyChangeLogModelTest(TestCase):
    def test_is_append_only_by_convention(self):
        PolicyApplication.objects.create(key="myapp", display_name="My App")
        log = PolicyChangeLog.objects.create(
            object_type=ObjectType.APPLICATION,
            object_key="myapp",
            change_type=ChangeType.CREATED,
            summary="Created",
            created_by_type=CreatedByType.AI,
        )
        self.assertEqual(log.created_by_type, CreatedByType.AI)
        self.assertEqual(log.change_type, ChangeType.CREATED)

    def test_str(self):
        log = PolicyChangeLog(
            object_key="auth.user.delete",
            change_type=ChangeType.CREATED,
        )
        self.assertIn("created", str(log))


class PolicyDependencyModelTest(TestCase):
    def setUp(self):
        self.app = PolicyApplication.objects.create(key="auth", display_name="Auth")
        self.src = PolicyEndpoint.objects.create(
            application=self.app,
            key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
        )
        self.tgt = PolicyEndpoint.objects.create(
            application=self.app,
            key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )

    def test_str(self):
        dep = PolicyDependency(
            source_endpoint=self.src,
            target_endpoint=self.tgt,
            direction=DependencyDirection.FORWARD,
            dependency_type=DependencyType.REQUIRES,
        )
        self.assertIn("requires", str(dep))

    def test_unique_together(self):
        PolicyDependency.objects.create(
            source_endpoint=self.src,
            target_endpoint=self.tgt,
            direction=DependencyDirection.FORWARD,
            dependency_type=DependencyType.REQUIRES,
        )
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            PolicyDependency.objects.create(
                source_endpoint=self.src,
                target_endpoint=self.tgt,
                direction=DependencyDirection.FORWARD,
                dependency_type=DependencyType.REQUIRES,
            )
