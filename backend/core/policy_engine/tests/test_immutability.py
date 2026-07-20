"""
Immutability and DB-connectivity tests for the Core Policy Engine.

Covers:
  - PolicyChangeLog: cannot be updated or deleted via any ORM path
  - PolicyEndpointVersion: cannot be updated or deleted via any ORM path
  - PolicyEndpointVersion.endpoint FK is PROTECT (deleting an endpoint that
    has version records is rejected at the DB level)
  - run_endpoint_lifecycle() is fully atomic: a mid-lifecycle failure rolls
    back all writes (no partial state left behind)
  - run_endpoint_lifecycle() raises PolicyLifecycleIncompleteError when the
    DB connection is simulated as down
"""

from unittest.mock import patch

from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from core.policy_engine.constants import ChangeType, CreatedByType, ObjectType, OperationType
from core.policy_engine.exceptions import (
    PolicyImmutabilityError,
    PolicyLifecycleIncompleteError,
)
from core.policy_engine.lifecycle import run_endpoint_lifecycle
from core.policy_engine.models import (
    PolicyApplication,
    PolicyChangeLog,
    PolicyEndpoint,
    PolicyEndpointVersion,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(key: str = "auth") -> PolicyApplication:
    return PolicyApplication.objects.create(key=key, display_name=key.title())


def _make_endpoint(app: PolicyApplication, suffix: str = "read") -> PolicyEndpoint:
    return PolicyEndpoint.objects.create(
        application=app,
        key=f"user-{suffix}",
        permission_key=f"auth.user.{suffix}",
        operation_type=OperationType.READ,
        display_name=f"{suffix.title()} User",
    )


def _make_changelog(**kwargs) -> PolicyChangeLog:
    defaults = {
        "object_type": ObjectType.APPLICATION,
        "object_key": "auth",
        "change_type": ChangeType.CREATED,
        "summary": "Created",
        "created_by_type": CreatedByType.SYSTEM,
    }
    defaults.update(kwargs)
    return PolicyChangeLog.objects.create(**defaults)


def _make_version(endpoint: PolicyEndpoint, version: str = "1.0.0") -> PolicyEndpointVersion:
    return PolicyEndpointVersion.objects.create(
        endpoint=endpoint,
        version=version,
        operation_type=endpoint.operation_type,
    )


# ---------------------------------------------------------------------------
# PolicyChangeLog immutability
# ---------------------------------------------------------------------------


class PolicyChangeLogImmutabilityTest(TestCase):
    def setUp(self):
        self.app = _make_app()
        self.log = _make_changelog()

    def test_update_via_save_raises(self):
        self.log.summary = "Tampered"
        with self.assertRaises(PolicyImmutabilityError):
            self.log.save()

    def test_delete_via_instance_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            self.log.delete()

    def test_bulk_update_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            PolicyChangeLog.objects.filter(pk=self.log.pk).update(summary="Tampered")

    def test_bulk_delete_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            PolicyChangeLog.objects.filter(pk=self.log.pk).delete()

    def test_queryset_all_delete_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            PolicyChangeLog.objects.all().delete()

    def test_new_record_can_still_be_created(self):
        new_log = _make_changelog(object_key="other")
        self.assertIsNotNone(new_log.pk)

    def test_deleting_app_with_changelogs_raises_protected_error(self):
        """You cannot delete a PolicyApplication that has changelog entries (PROTECT)."""
        _make_changelog(application=self.app)
        with self.assertRaises(ProtectedError):
            self.app.delete()


# ---------------------------------------------------------------------------
# PolicyEndpointVersion immutability
# ---------------------------------------------------------------------------


class PolicyEndpointVersionImmutabilityTest(TestCase):
    def setUp(self):
        self.app = _make_app()
        self.endpoint = _make_endpoint(self.app)
        self.ver = _make_version(self.endpoint)

    def test_update_via_save_raises(self):
        self.ver.route_pattern = "/api/v1/tampered/"
        with self.assertRaises(PolicyImmutabilityError):
            self.ver.save()

    def test_delete_via_instance_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            self.ver.delete()

    def test_bulk_update_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            PolicyEndpointVersion.objects.filter(pk=self.ver.pk).update(route_pattern="/api/v1/tampered/")

    def test_bulk_delete_raises(self):
        with self.assertRaises(PolicyImmutabilityError):
            PolicyEndpointVersion.objects.filter(pk=self.ver.pk).delete()

    def test_new_version_can_still_be_created(self):
        ver2 = _make_version(self.endpoint, version="1.1.0")
        self.assertIsNotNone(ver2.pk)


# ---------------------------------------------------------------------------
# PolicyEndpointVersion FK is PROTECT
# ---------------------------------------------------------------------------


class PolicyEndpointVersionProtectFKTest(TestCase):
    def setUp(self):
        self.app = _make_app()
        self.endpoint = _make_endpoint(self.app)
        _make_version(self.endpoint)

    def test_deleting_endpoint_with_versions_raises_protected_error(self):
        """DB-level PROTECT prevents cascade-deletion of version history."""
        with self.assertRaises(ProtectedError):
            self.endpoint.delete()

    def test_endpoint_without_versions_can_be_deleted(self):
        bare = _make_endpoint(self.app, suffix="list")
        bare.delete()
        from core.policy_engine.models import PolicyEndpoint

        self.assertFalse(PolicyEndpoint.objects.filter(pk=bare.pk).exists())


# ---------------------------------------------------------------------------
# run_endpoint_lifecycle() atomicity
# ---------------------------------------------------------------------------


class LifecycleAtomicityTest(TestCase):
    def test_full_lifecycle_is_committed(self):
        run_endpoint_lifecycle(
            config={
                "app_key": "auth",
                "endpoint_key": "user-read",
                "permission_key": "auth.user.read",
                "operation_type": OperationType.READ,
                "display_name": "Read User",
                "category_key": "user_mgmt",
                "category_display_name": "User Management",
            },
            created_by_type=CreatedByType.AI,
            created_by_identifier="test",
        )
        from core.policy_engine.models import PolicyApplication, PolicyEndpoint

        self.assertTrue(PolicyApplication.objects.filter(key="auth").exists())
        self.assertTrue(PolicyEndpoint.objects.filter(permission_key="auth.user.read").exists())
        self.assertTrue(PolicyChangeLog.objects.filter(object_key="auth.user.read").exists())

    def test_failed_lifecycle_step_rolls_back_all_writes(self):
        """
        If register_endpoint() raises mid-lifecycle (simulated), no app or
        changelog rows should remain — the outer @transaction.atomic rolls
        back everything.
        """
        from core.policy_engine.exceptions import PolicyEngineError

        with patch(
            "core.policy_engine.lifecycle.register_endpoint",
            side_effect=PolicyEngineError("simulated failure"),
        ):
            with self.assertRaises(PolicyEngineError):
                run_endpoint_lifecycle(
                    config={
                        "app_key": "auth",
                        "endpoint_key": "user-create",
                        "permission_key": "auth.user.create",
                        "operation_type": OperationType.CREATE,
                        "display_name": "Create User",
                    }
                )

        # register_application ran before the failure — but the atomic rollback
        # must have undone it
        self.assertFalse(PolicyApplication.objects.filter(key="auth").exists())
        self.assertEqual(PolicyChangeLog.objects.count(), 0)


# ---------------------------------------------------------------------------
# DB connectivity guard
# ---------------------------------------------------------------------------


class LifecycleDBConnectivityTest(TestCase):
    def test_raises_immediately_when_db_unreachable(self):
        """
        If the DB connection cannot be established, run_endpoint_lifecycle()
        raises PolicyLifecycleIncompleteError before any writes happen.
        """
        with patch.object(
            connection,
            "ensure_connection",
            side_effect=Exception("Connection refused"),
        ):
            with self.assertRaises(PolicyLifecycleIncompleteError) as ctx:
                run_endpoint_lifecycle(
                    config={
                        "app_key": "auth",
                        "endpoint_key": "user-read",
                        "permission_key": "auth.user.read",
                        "operation_type": OperationType.READ,
                        "display_name": "Read User",
                    }
                )

        self.assertIn("database is unreachable", str(ctx.exception))
        self.assertEqual(PolicyApplication.objects.count(), 0)
        self.assertEqual(PolicyChangeLog.objects.count(), 0)
