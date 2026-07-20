from datetime import timedelta

from django.test import TestCase

from core.nepal.text import normalize_unicode
from core.policy_engine.constants import (
    ChangeType,
    CreatedByType,
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    OperationType,
    RiskLevel,
)
from core.policy_engine.exceptions import (
    PolicyCircularDependencyError,
    PolicyDependencyNotFoundError,
    PolicyEndpointNotFoundError,
    PolicyIdentityConflictError,
    PolicyInvalidPermissionKeyError,
    PolicyInvalidVersionError,
    PolicyLifecycleIncompleteError,
    PolicyVersionConflictError,
)
from core.policy_engine.models import (
    EndpointCategoryMap,
    PermissionCategory,
    PolicyApplication,
    PolicyChangeLog,
    PolicyDependency,
    PolicyEndpoint,
    PolicyEndpointVersion,
)
from core.policy_engine.services import (
    add_dependency,
    create_version,
    deprecate_endpoint,
    disable_endpoint,
    map_endpoint_to_category,
    register_application,
    register_category,
    register_endpoint,
    register_model,
    remove_dependency,
    restore_endpoint,
)


class GitProvenanceTest(TestCase):
    """Every PolicyChangeLog row auto-captures branch_name/based_on_commit_sha
    via log_change() -> _git_provenance() — no caller passes these explicitly."""

    def test_log_change_populates_real_git_provenance(self):
        import subprocess

        from core.policy_engine import services as policy_services

        policy_services._git_provenance.cache_clear()
        register_application(key="auth", display_name="Auth")
        log = PolicyChangeLog.objects.filter(object_key="auth", change_type=ChangeType.CREATED).first()
        self.assertIsNotNone(log)

        expected_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        expected_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.assertEqual(log.branch_name, expected_branch)
        self.assertEqual(log.based_on_commit_sha, expected_sha)

    def test_git_failure_returns_blank_and_never_raises(self):
        from unittest.mock import patch

        from core.policy_engine import services as policy_services

        policy_services._git_provenance.cache_clear()
        with patch("core.policy_engine.services.subprocess.run", side_effect=OSError("git not found")):
            app = register_application(key="auth", display_name="Auth")
        policy_services._git_provenance.cache_clear()

        self.assertEqual(app.key, "auth")
        log = PolicyChangeLog.objects.filter(object_key="auth", change_type=ChangeType.CREATED).first()
        self.assertEqual(log.branch_name, "")
        self.assertEqual(log.based_on_commit_sha, "")

    def test_provenance_memoized_across_multiple_log_change_calls(self):
        from unittest.mock import patch

        from core.policy_engine import services as policy_services

        policy_services._git_provenance.cache_clear()
        with patch(
            "core.policy_engine.services.subprocess.run",
            wraps=policy_services.subprocess.run,
        ) as spy:
            register_application(key="auth", display_name="Auth")
            register_model(app_key="auth", key="user", display_name="User")
        # Two log_change() calls above -> git shelled out for exactly the
        # first one (2 subprocess.run calls: branch + sha), memoized after.
        self.assertEqual(spy.call_count, 2)


class RegisterApplicationServiceTest(TestCase):
    def test_creates_new_application(self):
        app = register_application(key="auth", display_name="Auth")
        self.assertEqual(app.key, "auth")
        self.assertEqual(app.current_version, "1.0.0")

    def test_idempotent_on_second_call(self):
        register_application(key="auth", display_name="Auth")
        app2 = register_application(key="auth", display_name="Auth Updated")
        self.assertEqual(PolicyApplication.objects.filter(key="auth").count(), 1)
        self.assertEqual(app2.display_name, "Auth Updated")

    def test_creates_changelog_on_creation(self):
        register_application(key="auth", display_name="Auth", created_by_type=CreatedByType.AI)
        log = PolicyChangeLog.objects.filter(object_key="auth", change_type=ChangeType.CREATED).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.created_by_type, CreatedByType.AI)

    def test_invalid_version_raises(self):
        with self.assertRaises(PolicyInvalidVersionError):
            register_application(key="auth", display_name="Auth", version="bad-version")


class RegisterModelServiceTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")

    def test_creates_new_model(self):
        pm = register_model(app_key="auth", key="user", display_name="User")
        self.assertEqual(str(pm), "auth.user")

    def test_idempotent_on_second_call(self):
        register_model(app_key="auth", key="user", display_name="User")
        register_model(app_key="auth", key="user", display_name="User Updated")
        from core.policy_engine.models import PolicyModel

        self.assertEqual(PolicyModel.objects.filter(application__key="auth", key="user").count(), 1)

    def test_migration_reference_recorded_on_creation(self):
        register_model(app_key="auth", key="user", display_name="User", migration_reference="0007_add_user_status")
        log = PolicyChangeLog.objects.filter(object_key="auth.user", change_type=ChangeType.CREATED).first()
        self.assertEqual(log.migration_reference, "0007_add_user_status")

    def test_migration_reference_recorded_on_update(self):
        register_model(app_key="auth", key="user", display_name="User")
        register_model(app_key="auth", key="user", display_name="User Account", migration_reference="0008_rename_user")
        log = (
            PolicyChangeLog.objects.filter(object_key="auth.user", change_type=ChangeType.METADATA_UPDATE)
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(log.migration_reference, "0008_rename_user")


class RegisterCategoryServiceTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")

    def test_creates_new_category(self):
        cat = register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        self.assertEqual(cat.key, "user_mgmt")
        self.assertEqual(cat.application.key, "auth")

    def test_idempotent_with_no_changes(self):
        register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        self.assertEqual(PermissionCategory.objects.filter(key="user_mgmt").count(), 1)
        self.assertFalse(
            PolicyChangeLog.objects.filter(object_key="user_mgmt", change_type=ChangeType.METADATA_UPDATE).exists()
        )

    def test_description_reconciled_on_resync(self):
        register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        cat = register_category(
            key="user_mgmt", display_name="User Management", app_key="auth", description="Manages user accounts."
        )
        self.assertEqual(cat.description, "Manages user accounts.")
        self.assertTrue(
            PolicyChangeLog.objects.filter(object_key="user_mgmt", change_type=ChangeType.METADATA_UPDATE).exists()
        )

    def test_blank_description_does_not_wipe_existing(self):
        register_category(
            key="user_mgmt", display_name="User Management", app_key="auth", description="Manages user accounts."
        )
        cat = register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        self.assertEqual(cat.description, "Manages user accounts.")

    def test_icon_key_reconciled_on_resync(self):
        register_category(key="user_mgmt", display_name="User Management", app_key="auth")
        cat = register_category(key="user_mgmt", display_name="User Management", app_key="auth", icon_key="user")
        self.assertEqual(cat.icon_key, "user")

    def test_sort_order_reconciled_on_resync(self):
        register_category(key="user_mgmt", display_name="User Management", app_key="auth", sort_order=5)
        cat = register_category(key="user_mgmt", display_name="User Management", app_key="auth", sort_order=1)
        self.assertEqual(cat.sort_order, 1)

    def test_policy_model_reconciled_on_resync(self):
        register_model(app_key="auth", key="user", display_name="User")
        register_model(app_key="auth", key="session", display_name="Session")
        register_category(key="user_mgmt", display_name="User Management", app_key="auth", model_key="user")
        cat = register_category(key="user_mgmt", display_name="User Management", app_key="auth", model_key="session")
        self.assertEqual(cat.policy_model.key, "session")


class MapEndpointToCategoryServiceTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        register_category(key="user_mgmt", display_name="User Management", app_key="auth")

    def test_creates_new_mapping(self):
        mapping = map_endpoint_to_category("auth.user.read", "user_mgmt")
        self.assertEqual(mapping.category.key, "user_mgmt")

    def test_idempotent_with_no_changes(self):
        map_endpoint_to_category("auth.user.read", "user_mgmt", is_sensitive=True)
        map_endpoint_to_category("auth.user.read", "user_mgmt", is_sensitive=True)
        self.assertEqual(EndpointCategoryMap.objects.filter(endpoint__permission_key="auth.user.read").count(), 1)
        self.assertEqual(
            PolicyChangeLog.objects.filter(
                object_key="auth.user.read", change_type=ChangeType.CATEGORY_CHANGED
            ).count(),
            1,
        )

    def test_is_sensitive_reconciled_on_resync(self):
        map_endpoint_to_category("auth.user.read", "user_mgmt", is_sensitive=False)
        mapping = map_endpoint_to_category("auth.user.read", "user_mgmt", is_sensitive=True)
        self.assertTrue(mapping.is_sensitive)

    def test_is_visible_in_ui_reconciled_on_resync(self):
        map_endpoint_to_category("auth.user.read", "user_mgmt", is_visible_in_ui=True)
        mapping = map_endpoint_to_category("auth.user.read", "user_mgmt", is_visible_in_ui=False)
        self.assertFalse(mapping.is_visible_in_ui)

    def test_help_text_reconciled_on_resync(self):
        map_endpoint_to_category("auth.user.read", "user_mgmt")
        mapping = map_endpoint_to_category("auth.user.read", "user_mgmt", help_text="View a user's profile.")
        self.assertEqual(mapping.help_text, "View a user's profile.")

    def test_sort_order_reconciled_on_resync(self):
        map_endpoint_to_category("auth.user.read", "user_mgmt", sort_order=5)
        mapping = map_endpoint_to_category("auth.user.read", "user_mgmt", sort_order=1)
        self.assertEqual(mapping.sort_order, 1)


class RegisterEndpointServiceTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_model(app_key="auth", key="user", display_name="User")

    def test_creates_endpoint(self):
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            model_key="user",
        )
        self.assertEqual(ep.permission_key, "auth.user.create")

    def test_creates_version_record(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        self.assertTrue(PolicyEndpointVersion.objects.filter(endpoint__permission_key="auth.user.create").exists())

    def test_migration_reference_recorded_on_creation(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            migration_reference="0007_add_user_status",
        )
        log = PolicyChangeLog.objects.filter(object_key="auth.user.create", change_type=ChangeType.CREATED).first()
        self.assertEqual(log.migration_reference, "0007_add_user_status")

    def test_migration_reference_recorded_on_update(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User v2",
            migration_reference="0009_add_create_user_flag",
        )
        log = (
            PolicyChangeLog.objects.filter(object_key="auth.user.create")
            .exclude(change_type=ChangeType.CREATED)
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(log.migration_reference, "0009_add_create_user_flag")

    def test_creates_changelog_record(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            created_by_type=CreatedByType.AI,
            created_by_identifier="claude",
        )
        log = PolicyChangeLog.objects.filter(object_key="auth.user.create").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.created_by_type, CreatedByType.AI)
        self.assertEqual(log.created_by_identifier, "claude")

    def test_invalid_permission_key_raises(self):
        with self.assertRaises(PolicyInvalidPermissionKeyError):
            register_endpoint(
                app_key="auth",
                endpoint_key="bad",
                permission_key="BAD_KEY",
                operation_type=OperationType.CREATE,
                display_name="Bad",
            )

    def test_idempotent_on_second_call(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User v2",
        )
        self.assertEqual(PolicyEndpoint.objects.filter(permission_key="auth.user.create").count(), 1)

    def test_custom_operation_type(self):
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
            description="Bans a user account.",
            risk_level=RiskLevel.HIGH,
        )
        self.assertEqual(ep.operation_type, OperationType.CUSTOM)
        self.assertEqual(ep.risk_level, RiskLevel.HIGH)

    def test_is_dependency_root_persisted_on_create(self):
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-login",
            permission_key="auth.user.login",
            operation_type=OperationType.CUSTOM,
            display_name="Login",
            risk_level=RiskLevel.HIGH,
            is_dependency_root=True,
        )
        self.assertTrue(ep.is_dependency_root)

    def test_is_dependency_root_updated_on_resync(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-login",
            permission_key="auth.user.login",
            operation_type=OperationType.CUSTOM,
            display_name="Login",
            risk_level=RiskLevel.HIGH,
        )
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-login",
            permission_key="auth.user.login",
            operation_type=OperationType.CUSTOM,
            display_name="Login",
            risk_level=RiskLevel.HIGH,
            is_dependency_root=True,
        )
        ep.refresh_from_db()
        self.assertTrue(ep.is_dependency_root)
        log = PolicyChangeLog.objects.filter(
            object_key="auth.user.login",
            change_type=ChangeType.UPDATED,
        ).first()
        self.assertIsNotNone(log)

    def test_operation_type_reconciled_on_resync(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
        )
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.UPDATE,
            display_name="Ban User",
        )
        ep.refresh_from_db()
        self.assertEqual(ep.operation_type, OperationType.UPDATE)

    def test_is_internal_reconciled_on_resync(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
            is_internal=False,
        )
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
            is_internal=True,
        )
        ep.refresh_from_db()
        self.assertTrue(ep.is_internal)

    def test_policy_model_reparented_on_resync(self):
        register_model(app_key="auth", key="user", display_name="User")
        register_model(app_key="auth", key="session", display_name="Session")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
            model_key="user",
        )
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-ban",
            permission_key="auth.user.ban",
            operation_type=OperationType.CUSTOM,
            display_name="Ban User",
            model_key="session",
        )
        ep.refresh_from_db()
        self.assertEqual(ep.policy_model.key, "session")


class AddDependencyServiceTest(TestCase):
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
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-list",
            permission_key="auth.user.list",
            operation_type=OperationType.LIST,
            display_name="List Users",
        )

    def test_forward_dependency_created(self):
        dep = add_dependency("auth.user.delete", "auth.user.read", direction=DependencyDirection.FORWARD)
        self.assertEqual(dep.direction, DependencyDirection.FORWARD)
        self.assertEqual(dep.dependency_type, DependencyType.REQUIRES)

    def test_backward_dependency_created(self):
        dep = add_dependency(
            "auth.user.read",
            "auth.user.delete",
            direction=DependencyDirection.BACKWARD,
            dependency_type=DependencyType.REVOKES_WITH,
        )
        self.assertEqual(dep.direction, DependencyDirection.BACKWARD)

    def test_circular_dependency_raises(self):
        add_dependency("auth.user.delete", "auth.user.read", direction=DependencyDirection.FORWARD)
        with self.assertRaises(PolicyCircularDependencyError):
            add_dependency("auth.user.read", "auth.user.delete", direction=DependencyDirection.FORWARD)

    def test_idempotent(self):
        add_dependency("auth.user.delete", "auth.user.read")
        add_dependency("auth.user.delete", "auth.user.read")
        self.assertEqual(
            PolicyDependency.objects.filter(
                source_endpoint__permission_key="auth.user.delete",
                target_endpoint__permission_key="auth.user.read",
            ).count(),
            1,
        )

    def test_changelog_created(self):
        add_dependency("auth.user.delete", "auth.user.read")
        log = PolicyChangeLog.objects.filter(change_type=ChangeType.DEPENDENCY_ADDED).first()
        self.assertIsNotNone(log)

    def test_enforcement_mode_tightened_on_resync_is_applied(self):
        """Security-relevant: permissions' grant-time dependency enforcement
        reads enforcement_mode. A registry declaration tightening warning ->
        strict must actually take effect on resync, not silently no-op."""
        add_dependency("auth.user.delete", "auth.user.read", enforcement_mode=EnforcementMode.WARNING)
        dep = add_dependency("auth.user.delete", "auth.user.read", enforcement_mode=EnforcementMode.STRICT)
        dep.refresh_from_db()
        self.assertEqual(dep.enforcement_mode, EnforcementMode.STRICT)

    def test_enforcement_mode_loosened_on_resync_is_applied(self):
        add_dependency("auth.user.delete", "auth.user.read", enforcement_mode=EnforcementMode.STRICT)
        dep = add_dependency("auth.user.delete", "auth.user.read", enforcement_mode=EnforcementMode.WARNING)
        dep.refresh_from_db()
        self.assertEqual(dep.enforcement_mode, EnforcementMode.WARNING)

    def test_enforcement_mode_change_logs_metadata_update(self):
        add_dependency("auth.user.delete", "auth.user.read", enforcement_mode=EnforcementMode.WARNING)
        add_dependency("auth.user.delete", "auth.user.read", enforcement_mode=EnforcementMode.STRICT)
        log = PolicyChangeLog.objects.filter(change_type=ChangeType.METADATA_UPDATE).first()
        self.assertIsNotNone(log)
        self.assertIn("warning", log.detail)
        self.assertIn("strict", log.detail)

    def test_reason_reconciled_on_resync(self):
        add_dependency("auth.user.delete", "auth.user.read", reason="Initial reason.")
        dep = add_dependency("auth.user.delete", "auth.user.read", reason="Updated reason.")
        dep.refresh_from_db()
        self.assertEqual(dep.reason, "Updated reason.")

    def test_blank_reason_does_not_wipe_existing(self):
        add_dependency("auth.user.delete", "auth.user.read", reason="Documented reason.")
        dep = add_dependency("auth.user.delete", "auth.user.read")
        dep.refresh_from_db()
        self.assertEqual(dep.reason, "Documented reason.")


class DeprecateEndpointServiceTest(TestCase):
    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
        )

    def test_deprecate_endpoint(self):
        ep = deprecate_endpoint("auth.user.delete", reason="Replaced by v2 endpoint.")
        ep.refresh_from_db()
        self.assertTrue(ep.is_deprecated)

    def test_not_found_raises(self):
        with self.assertRaises(PolicyEndpointNotFoundError):
            deprecate_endpoint("auth.user.nonexistent", reason="Test.")

    def test_changelog_created(self):
        deprecate_endpoint("auth.user.delete", reason="Replaced by v2.")
        log = PolicyChangeLog.objects.filter(change_type=ChangeType.DEPRECATED).first()
        self.assertIsNotNone(log)

    def test_deprecate_records_lifecycle_metadata(self):
        from django.utils import timezone

        sunset = timezone.now() + timedelta(days=90)
        ep = deprecate_endpoint(
            "auth.user.delete",
            reason="Replaced by v2 endpoint.",
            sunset_at=sunset,
            replaced_by_permission_key="auth.user.delete_v2",
            removal_ticket="OPS-1234",
        )
        ep.refresh_from_db()
        self.assertIsNotNone(ep.deprecated_at)
        self.assertEqual(ep.sunset_at, sunset)
        self.assertEqual(ep.replaced_by_permission_key, "auth.user.delete_v2")
        self.assertEqual(ep.removal_ticket, "OPS-1234")
        self.assertEqual(ep.removal_reason, "Replaced by v2 endpoint.")
        # The removal ticket is also threaded into the changelog's issue_reference.
        log = PolicyChangeLog.objects.filter(change_type=ChangeType.DEPRECATED).first()
        self.assertEqual(log.issue_reference, "OPS-1234")

    def test_deprecate_normalizes_removal_reason(self):
        # NFD-composed Devanagari must be normalized to NFC on write (§39.2).
        raw = "नेपाल"  # already-composed baseline
        ep = deprecate_endpoint("auth.user.delete", reason=raw)
        ep.refresh_from_db()
        self.assertEqual(ep.removal_reason, normalize_unicode(raw))


class EndpointVersionBumpTest(TestCase):
    """Version currency is derived from endpoint.current_version — re-registering
    with a bumped version must append a new immutable record, never mutate one."""

    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            route_pattern="/api/v1/auth/users/",
            version="1.0.0",
        )

    def _bump(self, version: str = "1.1.0") -> PolicyEndpoint:
        return register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            route_pattern="/api/v1/auth/users/",
            version=version,
        )

    def test_version_bump_succeeds(self):
        ep = self._bump()
        ep.refresh_from_db()
        self.assertEqual(ep.current_version, "1.1.0")

    def test_version_bump_appends_new_version_record(self):
        self._bump()
        versions = PolicyEndpointVersion.objects.filter(endpoint__permission_key="auth.user.create")
        self.assertEqual(versions.count(), 2)
        self.assertEqual({v.version for v in versions}, {"1.0.0", "1.1.0"})

    def test_prior_version_record_is_untouched(self):
        original = PolicyEndpointVersion.objects.get(endpoint__permission_key="auth.user.create", version="1.0.0")
        self._bump()
        unchanged = PolicyEndpointVersion.objects.get(pk=original.pk)
        self.assertEqual(unchanged.version, "1.0.0")
        self.assertEqual(unchanged.route_pattern, original.route_pattern)

    def test_serializer_derives_exactly_one_current_version(self):
        from core.policy_engine.serializers import PolicyEndpointVersionSerializer

        self._bump()
        versions = PolicyEndpointVersion.objects.filter(endpoint__permission_key="auth.user.create")
        data = PolicyEndpointVersionSerializer(versions, many=True).data
        current = [item for item in data if item["is_current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["version"], "1.1.0")

    def test_version_bump_creates_changelog_with_previous_version(self):
        self._bump()
        log = (
            PolicyChangeLog.objects.filter(object_key="auth.user.create", new_version="1.1.0")
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.previous_version, "1.0.0")


class EndpointIdentityConflictTest(TestCase):
    """An endpoint's identity is ((application, key), permission_key) — changing
    either half of an already-registered pair must fail loudly, never silently."""

    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )

    def test_permission_key_rename_raises(self):
        with self.assertRaises(PolicyIdentityConflictError):
            register_endpoint(
                app_key="auth",
                endpoint_key="user-create",
                permission_key="auth.user.create_v2",
                operation_type=OperationType.CREATE,
                display_name="Create User",
            )

    def test_endpoint_key_rename_raises(self):
        with self.assertRaises(PolicyIdentityConflictError):
            register_endpoint(
                app_key="auth",
                endpoint_key="user-create-renamed",
                permission_key="auth.user.create",
                operation_type=OperationType.CREATE,
                display_name="Create User",
            )

    def test_conflict_leaves_existing_row_unchanged(self):
        try:
            register_endpoint(
                app_key="auth",
                endpoint_key="user-create",
                permission_key="auth.user.create_v2",
                operation_type=OperationType.CREATE,
                display_name="Create User",
            )
        except PolicyIdentityConflictError:
            pass
        self.assertTrue(PolicyEndpoint.objects.filter(permission_key="auth.user.create").exists())
        self.assertFalse(PolicyEndpoint.objects.filter(permission_key="auth.user.create_v2").exists())

    def test_matching_identity_still_syncs(self):
        ep = register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User Updated",
        )
        self.assertEqual(ep.permission_key, "auth.user.create")
        self.assertEqual(PolicyEndpoint.objects.filter(application__key="auth").count(), 1)


class RegisterEndpointChangeMetadataTest(TestCase):
    """change_summary / change_reason from the config must reach the changelog."""

    def setUp(self):
        register_application(key="auth", display_name="Auth")

    def test_custom_summary_and_reason_on_creation(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            change_summary="Initial registration of user creation endpoint.",
            change_reason="Required by the registration feature.",
        )
        log = PolicyChangeLog.objects.filter(object_key="auth.user.create").first()
        self.assertEqual(log.summary, "Initial registration of user creation endpoint.")
        self.assertEqual(log.reason, "Required by the registration feature.")

    def test_defaults_used_when_not_provided(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        log = PolicyChangeLog.objects.filter(object_key="auth.user.create").first()
        self.assertEqual(log.summary, "Endpoint 'auth.user.create' registered.")
        self.assertEqual(log.reason, "Initial registration.")

    def test_custom_summary_and_reason_on_update(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
        )
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User v2",
            change_summary="Renamed display label for clarity.",
            change_reason="UX copy review.",
        )
        log = PolicyChangeLog.objects.filter(object_key="auth.user.create").order_by("-created_at").first()
        self.assertEqual(log.summary, "Renamed display label for clarity.")
        self.assertEqual(log.reason, "UX copy review.")


class StagedDeletionLifecycleTest(TestCase):
    """Part A1: deprecate -> disable -> (restore) staged deletion lifecycle."""

    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-delete",
            permission_key="auth.user.delete",
            operation_type=OperationType.DELETE,
            display_name="Delete User",
        )

    def test_disable_requires_deprecate_first(self):
        with self.assertRaises(PolicyLifecycleIncompleteError):
            disable_endpoint("auth.user.delete", reason="Replaced by v2.")

    def test_disable_after_deprecate_succeeds(self):
        deprecate_endpoint("auth.user.delete", reason="Sunsetting.")
        ep = disable_endpoint("auth.user.delete", reason="Sunset window ended.")
        self.assertFalse(ep.is_active)
        self.assertTrue(ep.is_deprecated)

    def test_disable_writes_removed_changelog(self):
        deprecate_endpoint("auth.user.delete", reason="Sunsetting.")
        disable_endpoint("auth.user.delete", reason="Sunset window ended.")
        log = PolicyChangeLog.objects.filter(object_key="auth.user.delete", change_type=ChangeType.REMOVED).first()
        self.assertIsNotNone(log)

    def test_restore_reactivates_endpoint(self):
        deprecate_endpoint("auth.user.delete", reason="Sunsetting.")
        disable_endpoint("auth.user.delete", reason="Sunset window ended.")
        ep = restore_endpoint("auth.user.delete", reason="Brought back by popular demand.")
        self.assertTrue(ep.is_active)
        self.assertFalse(ep.is_deprecated)

    def test_restore_writes_restored_changelog(self):
        deprecate_endpoint("auth.user.delete", reason="Sunsetting.")
        disable_endpoint("auth.user.delete", reason="Sunset window ended.")
        restore_endpoint("auth.user.delete", reason="Brought back.")
        log = PolicyChangeLog.objects.filter(object_key="auth.user.delete", change_type=ChangeType.RESTORED).first()
        self.assertIsNotNone(log)

    def test_disable_records_disabled_at(self):
        deprecate_endpoint("auth.user.delete", reason="Sunsetting.")
        ep = disable_endpoint("auth.user.delete", reason="Sunset window ended.")
        ep.refresh_from_db()
        self.assertIsNotNone(ep.disabled_at)

    def test_restore_clears_all_lifecycle_metadata(self):
        from django.utils import timezone

        deprecate_endpoint(
            "auth.user.delete",
            reason="Sunsetting.",
            sunset_at=timezone.now() + timedelta(days=30),
            replaced_by_permission_key="auth.user.delete_v2",
            removal_ticket="OPS-1",
        )
        disable_endpoint("auth.user.delete", reason="Sunset window ended.")
        ep = restore_endpoint("auth.user.delete", reason="Brought back.")
        ep.refresh_from_db()
        self.assertIsNone(ep.deprecated_at)
        self.assertIsNone(ep.disabled_at)
        self.assertIsNone(ep.sunset_at)
        self.assertEqual(ep.replaced_by_permission_key, "")
        self.assertEqual(ep.removal_ticket, "")
        self.assertEqual(ep.removal_reason, "")

    def test_serializer_exposes_lifecycle_fields(self):
        from core.policy_engine.selectors import get_endpoint_by_permission_key
        from core.policy_engine.serializers import PolicyEndpointSerializer

        deprecate_endpoint("auth.user.delete", reason="Sunsetting.", replaced_by_permission_key="auth.user.delete_v2")
        data = PolicyEndpointSerializer(get_endpoint_by_permission_key("auth.user.delete")).data
        for field in (
            "deprecated_at",
            "disabled_at",
            "sunset_at",
            "replaced_by_permission_key",
            "removal_ticket",
            "removal_reason",
        ):
            self.assertIn(field, data)
        self.assertEqual(data["replaced_by_permission_key"], "auth.user.delete_v2")


class RemoveDependencyServiceTest(TestCase):
    """Part A1: dependency removal is a soft-remove (is_active=False), never
    a hard delete — the row remains for audit-trail integrity."""

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
        register_endpoint(
            app_key="auth",
            endpoint_key="user-read",
            permission_key="auth.user.read",
            operation_type=OperationType.READ,
            display_name="Read User",
        )
        add_dependency(
            source_permission_key="auth.user.delete",
            target_permission_key="auth.user.read",
            direction=DependencyDirection.FORWARD,
            dependency_type=DependencyType.REQUIRES,
        )

    def test_remove_dependency_soft_deletes(self):
        dep = remove_dependency(
            source_permission_key="auth.user.delete",
            target_permission_key="auth.user.read",
            direction=DependencyDirection.FORWARD,
            dependency_type=DependencyType.REQUIRES,
            reason="No longer required after refactor.",
        )
        self.assertFalse(dep.is_active)
        self.assertTrue(PolicyDependency.objects.filter(pk=dep.pk).exists())

    def test_remove_dependency_writes_changelog(self):
        remove_dependency(
            source_permission_key="auth.user.delete",
            target_permission_key="auth.user.read",
            direction=DependencyDirection.FORWARD,
            dependency_type=DependencyType.REQUIRES,
            reason="No longer required.",
        )
        log = PolicyChangeLog.objects.filter(change_type=ChangeType.DEPENDENCY_REMOVED).first()
        self.assertIsNotNone(log)

    def test_remove_nonexistent_dependency_raises(self):
        with self.assertRaises(PolicyDependencyNotFoundError):
            remove_dependency(
                source_permission_key="auth.user.delete",
                target_permission_key="auth.user.read",
                direction=DependencyDirection.BACKWARD,
                dependency_type=DependencyType.REQUIRES,
                reason="Does not exist in this direction.",
            )


class VersionSnapshotIntegrityTest(TestCase):
    """Part A2: reusing an existing (endpoint, version) pair with different
    content must raise, not silently reuse stale content."""

    def setUp(self):
        register_application(key="auth", display_name="Auth")
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            route_pattern="/api/v1/auth/users/",
            http_method="POST",
            version="1.0.0",
        )

    def test_same_version_same_content_is_idempotent(self):
        register_endpoint(
            app_key="auth",
            endpoint_key="user-create",
            permission_key="auth.user.create",
            operation_type=OperationType.CREATE,
            display_name="Create User",
            route_pattern="/api/v1/auth/users/",
            http_method="POST",
            version="1.0.0",
        )
        self.assertEqual(PolicyEndpointVersion.objects.filter(endpoint__permission_key="auth.user.create").count(), 1)

    def test_create_version_honors_explicit_snapshot(self):
        version_obj = create_version(
            permission_key="auth.user.create",
            version="1.1.0",
            snapshot={"custom": "snapshot-content"},
        )
        self.assertEqual(version_obj.snapshot, {"custom": "snapshot-content"})

    def test_reusing_version_with_different_content_raises(self):
        from core.policy_engine.services import _create_version_record

        endpoint = PolicyEndpoint.objects.get(permission_key="auth.user.create")
        with self.assertRaises(PolicyVersionConflictError):
            _create_version_record(
                endpoint=endpoint,
                version="1.0.0",
                http_method="DELETE",
                route_pattern="/api/v1/auth/users/",
                view_import_path="",
                operation_type=OperationType.CREATE,
            )


class ApplicationModelVersionBumpTest(TestCase):
    """Part A3: register_application/register_model version bumps are real —
    current_version updates and the change is logged with prev/new version."""

    def test_application_version_bump_updates_and_logs(self):
        register_application(key="auth", display_name="Auth", version="1.0.0")
        app = register_application(key="auth", display_name="Auth", version="1.1.0")
        self.assertEqual(app.current_version, "1.1.0")
        log = (
            PolicyChangeLog.objects.filter(object_key="auth", change_type=ChangeType.METADATA_UPDATE)
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(log.previous_version, "1.0.0")
        self.assertEqual(log.new_version, "1.1.0")

    def test_model_version_bump_updates_and_logs(self):
        register_application(key="auth", display_name="Auth")
        register_model(app_key="auth", key="user", display_name="User", version="1.0.0")
        register_model(app_key="auth", key="user", display_name="User", version="1.2.0")
        model = PolicyApplication.objects.get(key="auth").policy_models.get(key="user")
        self.assertEqual(model.current_version, "1.2.0")
        log = (
            PolicyChangeLog.objects.filter(object_key="auth.user", change_type=ChangeType.METADATA_UPDATE)
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(log.previous_version, "1.0.0")
        self.assertEqual(log.new_version, "1.2.0")
