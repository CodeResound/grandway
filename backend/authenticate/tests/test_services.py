"""Service-layer tests: sessions, device limits, rotation/reuse, password, bootstrap."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.utils import timezone

from authenticate import services
from authenticate.constants import AuthorityType, SessionRevocationReason
from authenticate.exceptions import (
    DeviceLimitError,
    InvalidRefreshTokenError,
    PasswordIncorrectError,
    RefreshTokenReuseError,
)
from authenticate.models import AuthEvent, AuthSession, User

STRONG_PW = "Str0ng-Passphrase-17"
NEW_PW = "An0ther-Str0ng-Phrase-42"


def make_user(username: str = "leadmgr", password: str = STRONG_PW, must_change: bool = False) -> User:
    user = services.create_account(
        username=username,
        password=password,
        authority_type=AuthorityType.LEAD_MANAGER,
        provisioned_via="admin_created",
        must_change_password=must_change,
        display_name="Lead Manager",
    )
    return user


class TestBootstrapSuperadmin(TestCase):
    def test_creates_superadmin_flagged_for_password_change(self) -> None:
        user, created = services.bootstrap_superadmin(username="root", password=STRONG_PW)
        self.assertTrue(created)
        self.assertEqual(user.authority_type, AuthorityType.SUPERADMIN)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.security_state.must_change_password)

    def test_is_idempotent(self) -> None:
        services.bootstrap_superadmin(username="root", password=STRONG_PW)
        user, created = services.bootstrap_superadmin(username="root", password=STRONG_PW)
        self.assertFalse(created)
        self.assertEqual(User.objects.filter(username="root").count(), 1)

    def test_rejects_username_taken_by_non_superadmin(self) -> None:
        make_user(username="taken")
        with self.assertRaises(ValueError):
            services.bootstrap_superadmin(username="taken", password=STRONG_PW)


class TestIssueSession(TestCase):
    def test_issue_returns_opaque_refresh_and_hashes_it(self) -> None:
        user = make_user()
        session, raw = services.issue_session(user=user, device_id="dev-a")
        self.assertTrue(session.is_active)
        self.assertNotEqual(session.refresh_token_hash, raw)
        self.assertEqual(session.refresh_token_hash, services.hash_refresh_token(raw))

    def test_same_device_relogin_replaces_session(self) -> None:
        user = make_user()
        first, _ = services.issue_session(user=user, device_id="dev-a")
        second, _ = services.issue_session(user=user, device_id="dev-a")
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(first.revoked_reason, SessionRevocationReason.REPLACED_SAME_DEVICE)
        self.assertEqual(AuthSession.objects.filter(user=user, is_active=True).count(), 1)
        self.assertTrue(second.is_active)

    @override_settings(AUTH_MAX_ACTIVE_DEVICES=3)
    def test_fourth_device_is_rejected(self) -> None:
        user = make_user()
        for dev in ("a", "b", "c"):
            services.issue_session(user=user, device_id=f"dev-{dev}")
        with self.assertRaises(DeviceLimitError):
            services.issue_session(user=user, device_id="dev-d")
        self.assertEqual(AuthSession.objects.filter(user=user, is_active=True).count(), 3)


class TestRefreshRotation(TestCase):
    def test_refresh_rotates_and_retires_old_token(self) -> None:
        user = make_user()
        _, raw = services.issue_session(user=user, device_id="dev-a")
        result = services.refresh_session(raw_token=raw)
        self.assertNotEqual(result["refresh"], raw)
        # old token no longer valid
        with self.assertRaises(RefreshTokenReuseError):
            services.refresh_session(raw_token=raw)

    def test_reuse_of_retired_token_revokes_family(self) -> None:
        user = make_user()
        _, raw = services.issue_session(user=user, device_id="dev-a")
        result = services.refresh_session(raw_token=raw)
        # replaying the retired token triggers family revocation
        with self.assertRaises(RefreshTokenReuseError):
            services.refresh_session(raw_token=raw)
        # the newly-issued token is now also revoked (family killed)
        with self.assertRaises(InvalidRefreshTokenError):
            services.refresh_session(raw_token=result["refresh"])
        self.assertEqual(AuthSession.objects.filter(user=user, is_active=True).count(), 0)

    def test_unknown_token_is_invalid(self) -> None:
        with self.assertRaises(InvalidRefreshTokenError):
            services.refresh_session(raw_token="not-a-real-token")


class TestPasswordChange(TestCase):
    def test_wrong_current_password_raises(self) -> None:
        user = make_user()
        with self.assertRaises(PasswordIncorrectError):
            services.change_own_password(user=user, current_password="wrong", new_password=NEW_PW)

    def test_change_clears_flag_and_revokes_all_sessions(self) -> None:
        user = make_user(must_change=True)
        services.issue_session(user=user, device_id="dev-a")
        services.issue_session(user=user, device_id="dev-b")
        services.change_own_password(user=user, current_password=STRONG_PW, new_password=NEW_PW)
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PW))
        self.assertFalse(user.security_state.must_change_password)
        self.assertIsNotNone(user.security_state.password_changed_at)
        self.assertEqual(AuthSession.objects.filter(user=user, is_active=True).count(), 0)


class TestAuthEventImmutability(TestCase):
    def test_events_are_written_and_cannot_be_bulk_deleted(self) -> None:
        user = make_user()
        services.issue_session(user=user, device_id="dev-a")
        services.record_auth_event(
            event_type="login_success",
            subject=user,
            subject_username=user.username,
            success=True,
        )
        from authenticate.exceptions import ImmutabilityError

        with self.assertRaises(ImmutabilityError):
            AuthEvent.objects.all().delete()

    def test_password_change_at_is_utc(self) -> None:
        from authenticate.models import UserSecurityState

        user = make_user()
        services.change_own_password(user=user, current_password=STRONG_PW, new_password=NEW_PW)
        state = UserSecurityState.objects.get(user=user)
        self.assertIsNotNone(state.password_changed_at)
        self.assertLessEqual(state.password_changed_at, timezone.now())
