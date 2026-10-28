"""Regression tests for the "signed out every 15–20 minutes" report (2026-10-28).

Four causes, each pinned here:

* A concurrent refresh (two tabs, or a burst of 401s) presented a token the
  winner had just rotated away; that counted as reuse and revoked the session.
  The reuse grace window now answers it with an access token instead.
* "Log out other devices" cleared the caller's own refresh cookie.
* The refresh throttle was per IP only, so one office's shared IP was one bucket.
* The refresh cookie had no expiry, so closing the browser ended the session.

Also covers what the client was missing to diagnose any of it: ``access_expires_at``,
``error.details.reason`` on ``AUTH_REFRESH_INVALID``, and the ``refresh_rejected``
audit event behind the ``auth_session_report`` command.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from authenticate import services
from authenticate.constants import (
    CLAIM_SESSION_ID,
    REFRESH_GRACE_EVENT_REASON,
    AuthEventType,
    AuthorityType,
    ErrorCode,
    RefreshRejectReason,
    SessionRevocationReason,
)
from authenticate.exceptions import InvalidRefreshTokenError, RefreshTokenReuseError
from authenticate.models import AuthEvent, AuthSession, User
from authenticate.throttling import RefreshThrottle, RefreshTokenThrottle

STRONG_PW = "Str0ng-Passphrase-17"
COOKIE = "grandway_refresh"


def make_user(username: str = "graceuser") -> User:
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=AuthorityType.LEAD_MANAGER,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="Grace User",
    )


def sid_of(access: str) -> str:
    return str(AccessToken(access)[CLAIM_SESSION_ID])


class TestGraceWindowService(TestCase):
    def setUp(self) -> None:
        self.user = make_user()
        self.first, self.raw = services.issue_session(user=self.user, device_id="dev-a")

    def test_concurrent_refresh_inside_window_keeps_session(self) -> None:
        winner = services.refresh_session(raw_token=self.raw)
        loser = services.refresh_session(raw_token=self.raw)

        self.assertIsNone(loser["refresh"])
        self.assertEqual(loser["session"].pk, winner["session"].pk)
        self.assertEqual(sid_of(loser["access"]), str(winner["session"].pk))
        # The family survives and the winner's refresh token still rotates.
        self.assertTrue(AuthSession.objects.get(pk=winner["session"].pk).is_active)
        services.refresh_session(raw_token=winner["refresh"])

    def test_grace_answer_is_audited(self) -> None:
        services.refresh_session(raw_token=self.raw)
        services.refresh_session(raw_token=self.raw)
        self.assertTrue(
            AuthEvent.objects.filter(
                event_type=AuthEventType.SESSION_REFRESHED, reason=REFRESH_GRACE_EVENT_REASON, subject=self.user
            ).exists()
        )

    def test_any_ancestor_inside_window_gets_current_session(self) -> None:
        second = services.refresh_session(raw_token=self.raw)
        third = services.refresh_session(raw_token=second["refresh"])
        late = services.refresh_session(raw_token=self.raw)
        self.assertEqual(late["session"].pk, third["session"].pk)

    def test_replay_after_window_revokes_family(self) -> None:
        winner = services.refresh_session(raw_token=self.raw)
        AuthSession.objects.filter(pk=self.first.pk).update(revoked_at=timezone.now() - timedelta(seconds=31))

        with self.assertRaises(RefreshTokenReuseError):
            services.refresh_session(raw_token=self.raw)
        self.assertFalse(AuthSession.objects.get(pk=winner["session"].pk).is_active)
        self.assertEqual(
            AuthSession.objects.get(pk=winner["session"].pk).revoked_reason, SessionRevocationReason.ROTATED_REUSE
        )

    def test_replay_after_successor_logged_out_is_reuse(self) -> None:
        winner = services.refresh_session(raw_token=self.raw)
        services.logout(winner["session"])
        with self.assertRaises(RefreshTokenReuseError):
            services.refresh_session(raw_token=self.raw)

    def test_grace_never_applies_to_a_logged_out_token(self) -> None:
        services.logout(self.first)
        with self.assertRaises(InvalidRefreshTokenError) as ctx:
            services.refresh_session(raw_token=self.raw)
        self.assertEqual(ctx.exception.reason, SessionRevocationReason.LOGOUT)

    def test_blocked_user_gets_no_grace(self) -> None:
        services.refresh_session(raw_token=self.raw)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(RefreshTokenReuseError):
            services.refresh_session(raw_token=self.raw)


class TestRefreshRejectReasons(TestCase):
    def setUp(self) -> None:
        self.user = make_user()

    def _reason(self, raw: str) -> str:
        with self.assertRaises(InvalidRefreshTokenError) as ctx:
            services.refresh_session(raw_token=raw)
        return ctx.exception.reason

    def test_unknown_token(self) -> None:
        self.assertEqual(self._reason("not-a-real-token"), RefreshRejectReason.NOT_FOUND)

    def test_same_device_relogin(self) -> None:
        _, raw = services.issue_session(user=self.user, device_id="dev-a")
        services.issue_session(user=self.user, device_id="dev-a")
        self.assertEqual(self._reason(raw), SessionRevocationReason.REPLACED_SAME_DEVICE)

    def test_expired_session_is_revoked_and_stays_revoked(self) -> None:
        session, raw = services.issue_session(user=self.user, device_id="dev-a")
        AuthSession.objects.filter(pk=session.pk).update(idle_expires_at=timezone.now() - timedelta(seconds=1))

        self.assertEqual(self._reason(raw), SessionRevocationReason.EXPIRED)
        # The revoke used to be rolled back by the exception raised inside the
        # rotation transaction, leaving the expired session marked active.
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertEqual(session.revoked_reason, SessionRevocationReason.EXPIRED)
        self.assertEqual(self._reason(raw), SessionRevocationReason.EXPIRED)

    def test_inactive_user(self) -> None:
        _, raw = services.issue_session(user=self.user, device_id="dev-a")
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self._reason(raw), SessionRevocationReason.BLOCKED)

    def test_rejection_is_audited_against_the_user(self) -> None:
        session, raw = services.issue_session(user=self.user, device_id="dev-a")
        services.logout(session)
        self._reason(raw)
        event = AuthEvent.objects.get(event_type=AuthEventType.REFRESH_REJECTED)
        self.assertEqual(event.subject, self.user)
        self.assertEqual(event.reason, SessionRevocationReason.LOGOUT)
        self.assertFalse(event.success)
        self.assertEqual(event.device_id, "dev-a")


class TestRefreshEndpointBodyMode(APITestCase):
    def setUp(self) -> None:
        make_user()
        self.login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "graceuser", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.refresh = self.login.data["data"]["refresh"]

    def _refresh(self, raw: str) -> object:
        return self.client.post(reverse("v1:auth:refresh"), {"refresh": raw}, format="json")

    def test_login_returns_access_expires_at(self) -> None:
        data = self.login.data["data"]
        exp = datetime.fromtimestamp(AccessToken(data["access"])["exp"], tz=UTC)
        self.assertEqual(data["access_expires_at"], exp)
        self.assertIn("access_expires_at", self.login.json()["data"])

    def test_refresh_returns_access_expires_at(self) -> None:
        resp = self._refresh(self.refresh)
        data = resp.data["data"]
        self.assertEqual(data["access_expires_at"], datetime.fromtimestamp(AccessToken(data["access"])["exp"], tz=UTC))

    def test_concurrent_refresh_returns_access_without_refresh(self) -> None:
        self.assertEqual(self._refresh(self.refresh).status_code, status.HTTP_200_OK)
        resp = self._refresh(self.refresh)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data["data"])
        self.assertNotIn("refresh", resp.data["data"])

    def test_invalid_refresh_reports_reason(self) -> None:
        resp = self._refresh("not-a-real-token")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.REFRESH_INVALID)
        self.assertEqual(resp.data["error"]["details"], {"reason": RefreshRejectReason.NOT_FOUND})

    def test_missing_refresh_reports_reason(self) -> None:
        resp = self._refresh("")
        self.assertEqual(resp.data["error"]["code"], ErrorCode.REFRESH_INVALID)
        self.assertEqual(resp.data["error"]["details"], {"reason": RefreshRejectReason.MISSING})

    def test_same_device_relogin_reports_reason(self) -> None:
        self.client.post(
            reverse("v1:auth:login"),
            {"username": "graceuser", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        resp = self._refresh(self.refresh)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.REFRESH_INVALID)
        self.assertEqual(resp.data["error"]["details"]["reason"], SessionRevocationReason.REPLACED_SAME_DEVICE)

    def test_expired_access_token_is_authentication_failed(self) -> None:
        """Pins the documented trigger for a client refresh: ``AUTHENTICATION_FAILED``."""
        session = AuthSession.objects.get(is_active=True)
        token = AccessToken.for_user(session.user)
        token[CLAIM_SESSION_ID] = str(session.id)
        token.set_exp(from_time=timezone.now() - timedelta(hours=1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = self.client.get(reverse("v1:auth:me"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], "AUTHENTICATION_FAILED")


@override_settings(AUTH_REFRESH_COOKIE_ENABLED=True)
class TestRefreshCookie(APITestCase):
    def setUp(self) -> None:
        make_user()
        self.login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "graceuser", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.raw = self.login.cookies[COOKIE].value

    def test_login_sets_persistent_cookie(self) -> None:
        morsel = self.login.cookies[COOKIE]
        self.assertNotIn("refresh", self.login.data["data"])
        self.assertTrue(morsel["httponly"])
        self.assertTrue(morsel["secure"])
        self.assertEqual(morsel["samesite"], "Lax")
        self.assertEqual(morsel["path"], "/api/v1/auth/")
        self.assertEqual(morsel["domain"], "")
        self.assertTrue(morsel["expires"])
        lifetime = settings.AUTH_SESSION_ABSOLUTE_LIFETIME.total_seconds()
        self.assertAlmostEqual(int(morsel["max-age"]), lifetime, delta=5)

    @override_settings(AUTH_REFRESH_COOKIE_DOMAIN=".example.com", AUTH_REFRESH_COOKIE_SAMESITE="Strict")
    def test_configured_domain_and_samesite(self) -> None:
        resp = self.client.post(reverse("v1:auth:refresh"))
        morsel = resp.cookies[COOKIE]
        self.assertEqual(morsel["domain"], ".example.com")
        self.assertEqual(morsel["samesite"], "Strict")

    def test_refresh_rotates_cookie(self) -> None:
        resp = self.client.post(reverse("v1:auth:refresh"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotEqual(resp.cookies[COOKIE].value, self.raw)

    def test_concurrent_refresh_sets_no_cookie(self) -> None:
        winner = self.client.post(reverse("v1:auth:refresh"))
        self.client.cookies[COOKIE] = self.raw  # the second tab still holds the old token
        loser = self.client.post(reverse("v1:auth:refresh"))
        self.assertEqual(loser.status_code, status.HTTP_200_OK)
        self.assertNotIn(COOKIE, loser.cookies)
        self.assertEqual(sid_of(loser.data["data"]["access"]), sid_of(winner.data["data"]["access"]))

    @override_settings(AUTH_REFRESH_COOKIE_DOMAIN=".example.com")
    def test_rejected_refresh_clears_cookie_with_matching_attributes(self) -> None:
        self.client.cookies[COOKIE] = "not-a-real-token"
        resp = self.client.post(reverse("v1:auth:refresh"))
        morsel = resp.cookies[COOKIE]
        self.assertEqual(morsel.value, "")
        self.assertEqual(int(morsel["max-age"]), 0)
        self.assertEqual(morsel["domain"], ".example.com")
        self.assertEqual(morsel["path"], "/api/v1/auth/")


@override_settings(AUTH_REFRESH_COOKIE_ENABLED=True)
class TestOwnSessionRevokeCookie(APITestCase):
    def setUp(self) -> None:
        make_user()
        self.other_session, _ = services.issue_session(user=User.objects.get(), device_id="dev-b")
        login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "graceuser", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['data']['access']}")
        self.current_id = sid_of(login.data["data"]["access"])
        self.url = reverse("v1:auth:session-revoke")

    def test_revoke_others_keeps_caller_cookie(self) -> None:
        resp = self.client.post(self.url, {"others_only": True}, format="json")
        self.assertEqual(resp.data["data"]["revoked"], 1)
        self.assertNotIn(COOKIE, resp.cookies)
        self.assertEqual(self.client.post(reverse("v1:auth:refresh")).status_code, status.HTTP_200_OK)

    def test_revoke_one_other_session_keeps_caller_cookie(self) -> None:
        resp = self.client.post(self.url, {"session_id": str(self.other_session.id)}, format="json")
        self.assertNotIn(COOKIE, resp.cookies)

    def test_revoke_current_session_clears_cookie(self) -> None:
        resp = self.client.post(self.url, {"session_id": self.current_id}, format="json")
        self.assertEqual(resp.cookies[COOKIE].value, "")

    def test_revoke_all_clears_cookie(self) -> None:
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.data["data"]["revoked"], 2)
        self.assertEqual(resp.cookies[COOKIE].value, "")


class TestRefreshTokenThrottle(APITestCase):
    """Each refresh credential has its own bucket; a shared IP no longer is one.

    ``THROTTLE_RATES`` is bound when DRF imports, so it is patched on the class
    rather than through ``override_settings``.
    """

    def setUp(self) -> None:
        cache.clear()
        self.user = make_user()
        _, self.raw_a = services.issue_session(user=self.user, device_id="dev-a")
        _, self.raw_b = services.issue_session(user=self.user, device_id="dev-b")

    def tearDown(self) -> None:
        cache.clear()

    def test_per_token_buckets_are_independent(self) -> None:
        url = reverse("v1:auth:refresh")
        rates = {"auth_refresh": None, "auth_refresh_token": "1/minute"}
        with (
            mock.patch.object(RefreshThrottle, "THROTTLE_RATES", rates),
            mock.patch.object(RefreshTokenThrottle, "THROTTLE_RATES", rates),
        ):
            self.assertEqual(self.client.post(url, {"refresh": self.raw_a}, format="json").status_code, 200)
            # Same token again: its own bucket is spent.
            self.assertEqual(
                self.client.post(url, {"refresh": self.raw_a}, format="json").status_code,
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
            # Another session from the same IP is unaffected.
            self.assertEqual(self.client.post(url, {"refresh": self.raw_b}, format="json").status_code, 200)


class TestAuthSessionReportCommand(TestCase):
    def test_reports_refresh_and_revocation_counts(self) -> None:
        user = make_user()
        _, raw = services.issue_session(user=user, device_id="dev-a")
        services.refresh_session(raw_token=raw)
        services.refresh_session(raw_token=raw)  # grace answer
        services.issue_session(user=user, device_id="dev-a")  # replaces the session
        with self.assertRaises(InvalidRefreshTokenError):
            services.refresh_session(raw_token="not-a-real-token")

        out = StringIO()
        call_command("auth_session_report", username="graceuser", stdout=out)
        text = out.getvalue()
        self.assertIn("session_refreshed / - / ok: 1", text)
        self.assertIn(f"session_refreshed / {REFRESH_GRACE_EVENT_REASON} / ok: 1", text)
        self.assertIn("rotated: 1", text)
        self.assertIn("replaced_same_device: 1", text)

    def test_unknown_user_is_an_error(self) -> None:
        with self.assertRaises(CommandError):
            call_command("auth_session_report", username="nobody", stdout=StringIO())

    def test_days_must_be_positive(self) -> None:
        make_user()
        with self.assertRaises(CommandError):
            call_command("auth_session_report", username="graceuser", days=0, stdout=StringIO())
