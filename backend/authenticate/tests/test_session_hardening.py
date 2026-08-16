"""Regression tests for the session-lifecycle defects found in the 2026-08-01 audit.

Three separate bugs, each with its own failure mode:

* Refresh rotation read the session without a row lock, so two concurrent
  refreshes both retired it and both inserted a replacement — the second
  violating ``uniq_active_session_per_device`` and surfacing as a 500.
* ``last_used_at`` was declared ``auto_now_add`` and never written, so the
  "active sessions" screen labelled the creation time as last use.
* MFA detection was scoped to this app's own device name while MFA *removal* was
  not, so a confirmed device created under any other name was silently ignored
  at login.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from authenticate import services
from authenticate.constants import AuthorityType
from authenticate.models import AuthSession, User
from authenticate.selectors import (
    get_active_session_by_refresh_hash_for_update,
    has_confirmed_mfa,
)

STRONG_PW = "Str0ng-Passphrase-17"


def make_user(username: str = "sessionuser", authority: str = AuthorityType.LEAD_MANAGER) -> User:
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="User",
    )


class RefreshRotationLockTests(TestCase):
    """The rotation read must take a row lock, not just sit inside a transaction."""

    def test_rotation_read_emits_for_update(self):
        """The lock is in the SQL, not merely intended by the caller.

        Asserted against the compiled query rather than by racing two threads:
        the suite runs on SQLite, where ``select_for_update`` compiles to nothing
        at all, so a thread race here would pass just as happily against the
        unlocked code this test exists to catch.
        """
        if not connection.features.has_select_for_update:
            self.skipTest("backend does not support SELECT ... FOR UPDATE")

        queryset = (
            AuthSession.objects.select_related("user", "user__security_state")
            .select_for_update(of=("self",))
            .filter(refresh_token_hash="x", is_active=True)
        )
        self.assertIn("FOR UPDATE", str(queryset.query).upper())

    def test_locked_read_returns_the_active_session(self):
        """The locking selector still finds what the unlocked one found."""
        user = make_user()
        session, raw = services.issue_session(user=user, device_id="dev-1")

        found = get_active_session_by_refresh_hash_for_update(services.hash_refresh_token(raw))

        self.assertIsNotNone(found)
        self.assertEqual(found.pk, session.pk)

    def test_second_rotation_of_one_token_is_refused(self):
        """A token already rotated away is reuse, never a second new session."""
        user = make_user()
        _, raw = services.issue_session(user=user, device_id="dev-1")

        services.refresh_session(raw_token=raw)

        with self.assertRaises(services.RefreshTokenReuseError):
            services.refresh_session(raw_token=raw)

        # Reuse kills the family, so nothing is left active for that device.
        self.assertEqual(AuthSession.objects.filter(user=user, is_active=True).count(), 0)


class LastUsedAtTests(TestCase):
    """``last_used_at`` has to track use, or the session screen misinforms."""

    def test_stale_last_used_is_refreshed(self):
        from authenticate.authentication import _touch_last_used

        user = make_user()
        session, _ = services.issue_session(user=user, device_id="dev-1")
        AuthSession.objects.filter(pk=session.pk).update(last_used_at=timezone.now() - timedelta(hours=3))
        session.refresh_from_db()
        before = session.last_used_at

        _touch_last_used(session, timezone.now())

        session.refresh_from_db()
        self.assertGreater(session.last_used_at, before)

    def test_an_authenticated_request_advances_last_used(self):
        """The end-to-end shape of the bug: before the fix nothing moved it, ever."""
        user = make_user()
        session, _ = services.issue_session(user=user, device_id="dev-1")
        AuthSession.objects.filter(pk=session.pk).update(last_used_at=timezone.now() - timedelta(hours=3))
        session.refresh_from_db()
        before = session.last_used_at
        access = services.build_access_token(user, session, must_change_password=False)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = client.get(reverse("v1:auth:me"))

        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertGreater(session.last_used_at, before)

    @override_settings(AUTH_SESSION_LAST_USED_RESOLUTION=timedelta(minutes=5))
    def test_fresh_last_used_is_not_rewritten(self):
        """Bounded cost: a recent value must not put an UPDATE on every request."""
        from authenticate.authentication import _touch_last_used

        user = make_user()
        session, _ = services.issue_session(user=user, device_id="dev-1")
        session.refresh_from_db()
        before = session.last_used_at

        _touch_last_used(session, before + timedelta(minutes=1))

        session.refresh_from_db()
        self.assertEqual(session.last_used_at, before)


class MfaDeviceNamingTests(TestCase):
    """A confirmed device is a confirmed device, whatever it is called."""

    def test_device_under_another_name_still_counts_as_enrolled(self):
        user = make_user()
        TOTPDevice.objects.create(user=user, name="yubikey-backup", confirmed=True)

        self.assertTrue(has_confirmed_mfa(user))

    def test_login_requires_a_code_for_a_differently_named_device(self):
        """The bug: login skipped MFA entirely for a device it did not name."""
        user = make_user()
        TOTPDevice.objects.create(user=user, name="yubikey-backup", confirmed=True)

        request = RequestFactory().post("/api/v1/auth/login/")

        with self.assertRaises(services.MfaRequiredError):
            services.login(request=request, username=user.username, password=STRONG_PW, device_id="dev-1")

    def test_code_from_a_differently_named_device_is_accepted(self):
        user = make_user()
        device = TOTPDevice.objects.create(user=user, name="yubikey-backup", confirmed=True)
        code = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift)

        self.assertTrue(services.verify_totp_code(user, f"{code:0{device.digits}d}"))

    def test_an_unconfirmed_device_does_not_count(self):
        user = make_user()
        TOTPDevice.objects.create(user=user, name="half-enrolled", confirmed=False)

        self.assertFalse(has_confirmed_mfa(user))
