"""Phase 3 tests: account management + authority hierarchy + session/event admin."""

from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status
from rest_framework.test import APITestCase

from authenticate import services
from authenticate.constants import AuthorityType, ErrorCode
from authenticate.models import AuthSession, User
from authenticate.selectors import has_confirmed_mfa

STRONG_PW = "Str0ng-Passphrase-17"


def make(username: str, authority: str) -> User:
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="U",
    )


def token_for(user: User) -> str:
    session, _ = services.issue_session(user=user, device_id=f"test-{user.username}")
    return services.build_access_token(user, session, must_change_password=False)


class TestAccountCreate(APITestCase):
    def setUp(self) -> None:
        self.superadmin = make("root", AuthorityType.SUPERADMIN)
        self.admin = make("adminx", AuthorityType.ADMIN)
        self.url = reverse("v1:auth:user-list")

    def _as(self, user: User) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def test_superadmin_creates_admin_with_generated_password(self) -> None:
        self._as(self.superadmin)
        resp = self.client.post(self.url, {"username": "newadmin", "authority_type": "admin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("temporary_password", resp.data["data"])
        created = User.objects.get(username="newadmin")
        self.assertEqual(created.authority_type, AuthorityType.ADMIN)
        self.assertTrue(created.security_state.must_change_password)

    def test_admin_creates_lead_manager(self) -> None:
        self._as(self.admin)
        resp = self.client.post(self.url, {"username": "lm1", "authority_type": "lead_manager"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_admin_cannot_create_admin(self) -> None:
        self._as(self.admin)
        resp = self.client.post(self.url, {"username": "lm2", "authority_type": "admin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.INVALID_AUTHORITY)

    def test_superadmin_cannot_create_lead_manager(self) -> None:
        self._as(self.superadmin)
        resp = self.client.post(self.url, {"username": "lm3", "authority_type": "lead_manager"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_username_taken(self) -> None:
        self._as(self.superadmin)
        make("dupe", AuthorityType.ADMIN)
        resp = self.client.post(self.url, {"username": "dupe", "authority_type": "admin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.USERNAME_TAKEN)

    def test_lead_manager_is_refused_the_account_list(self) -> None:
        """An authority that manages nobody is denied, not handed an empty page.

        This previously asserted `200 []`, which a Lead Manager holds no
        authority to receive: `get_manageable_users` returns `none()` for them,
        so the endpoint answered success for a request it should refuse. Nothing
        leaked — the queryset really was empty — but it was the one route in this
        app whose denial was indistinguishable from a permitted empty result,
        and a client could not tell the two apart.
        """
        lm = make("lm", AuthorityType.LEAD_MANAGER)
        self._as(lm)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_lead_manager_is_refused_before_field_validation(self) -> None:
        """Denial must not describe the endpoint it is refusing.

        Posting garbage as a Lead Manager used to return 400 with the serializer's
        field errors — enumerating the shape of an endpoint the caller may not
        use — because validation ran before the authority check.
        """
        lm = make("lm2", AuthorityType.LEAD_MANAGER)
        self._as(lm)
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TestAccountManagement(APITestCase):
    def setUp(self) -> None:
        self.admin = make("adminx", AuthorityType.ADMIN)
        self.lm = make("leadmgr", AuthorityType.LEAD_MANAGER)
        self.other_admin = make("admin2", AuthorityType.ADMIN)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def _url(self, name: str, user: User) -> str:
        return reverse(f"v1:auth:{name}", args=[user.id])

    def test_read_managed_account(self) -> None:
        resp = self.client.get(self._url("user-detail", self.lm))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["username"], "leadmgr")

    def test_out_of_tier_is_404(self) -> None:
        # admin cannot manage another admin
        resp = self.client.get(self._url("user-detail", self.other_admin))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.USER_NOT_FOUND)

    def test_update_profile(self) -> None:
        resp = self.client.patch(self._url("user-detail", self.lm), {"display_name": "Renamed"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.lm.refresh_from_db()
        self.assertEqual(self.lm.display_name, "Renamed")

    def test_block_revokes_sessions(self) -> None:
        services.issue_session(user=self.lm, device_id="d1")
        resp = self.client.post(self._url("user-block", self.lm), {"reason": "policy"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.lm.refresh_from_db()
        self.assertFalse(self.lm.is_active)
        self.assertEqual(AuthSession.objects.filter(user=self.lm, is_active=True).count(), 0)

    def test_restore(self) -> None:
        services.block_account(actor=self.admin, target=self.lm)
        resp = self.client.post(self._url("user-restore", self.lm))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.lm.refresh_from_db()
        self.assertTrue(self.lm.is_active)

    def test_reset_password_returns_temp_and_revokes(self) -> None:
        services.issue_session(user=self.lm, device_id="d1")
        resp = self.client.post(self._url("user-reset-password", self.lm))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("temporary_password", resp.data["data"])
        self.lm.refresh_from_db()
        self.assertTrue(self.lm.security_state.must_change_password)
        self.assertEqual(AuthSession.objects.filter(user=self.lm, is_active=True).count(), 0)

    def test_reset_mfa(self) -> None:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        TOTPDevice.objects.create(user=self.lm, name="default", confirmed=True)
        resp = self.client.post(self._url("user-reset-mfa", self.lm))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(has_confirmed_mfa(self.lm))

    def test_list_and_revoke_target_sessions(self) -> None:
        services.issue_session(user=self.lm, device_id="d1")
        services.issue_session(user=self.lm, device_id="d2")
        listing = self.client.get(self._url("user-session-list", self.lm))
        self.assertEqual(len(listing.data["data"]), 2)
        revoke = self.client.post(self._url("user-session-revoke", self.lm))
        self.assertEqual(revoke.data["data"]["revoked"], 2)

    def test_events_review(self) -> None:
        services.record_auth_event(
            event_type="login_success", subject=self.lm, subject_username=self.lm.username, success=True
        )
        resp = self.client.get(self._url("user-events", self.lm))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data["data"]), 1)


class TestAccountListQueryCount(APITestCase):
    """The MFA fields must not cost per-row device queries (2026-08-17 audit, P2)."""

    def setUp(self) -> None:
        self.superadmin = make("root-qc", AuthorityType.SUPERADMIN)
        self.url = reverse("v1:auth:user-list")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.superadmin)}")

    def _populate(self, count: int, offset: int = 0) -> None:
        for index in range(count):
            user = make(f"adm-qc-{offset + index}", AuthorityType.ADMIN)
            # Every second account has a confirmed device, so both values of
            # the annotated flag are exercised on the same page.
            if index % 2:
                TOTPDevice.objects.create(user=user, name="default", confirmed=True)

    def test_query_count_does_not_grow_with_the_number_of_accounts(self) -> None:
        self._populate(2)
        with CaptureQueriesContext(connection) as small:
            first = self.client.get(self.url, {"page_size": 100})

        self._populate(6, offset=2)
        with CaptureQueriesContext(connection) as large:
            second = self.client.get(self.url, {"page_size": 100})

        self.assertEqual(len(first.data["data"]), 2)
        self.assertEqual(len(second.data["data"]), 8)
        self.assertTrue(any(row["mfa_enabled"] for row in second.data["data"]))
        self.assertTrue(any(not row["mfa_enabled"] for row in second.data["data"]))
        self.assertEqual(len(large.captured_queries), len(small.captured_queries))


class TestOwnSessions(APITestCase):
    def setUp(self) -> None:
        self.user = make("leadmgr", AuthorityType.LEAD_MANAGER)
        self.session, _ = services.issue_session(user=self.user, device_id="current")
        self.access = services.build_access_token(self.user, self.session, must_change_password=False)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")

    def test_list_own_sessions(self) -> None:
        services.issue_session(user=self.user, device_id="other")
        resp = self.client.get(reverse("v1:auth:session-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["data"]), 2)

    def test_revoke_others_keeps_current(self) -> None:
        services.issue_session(user=self.user, device_id="other")
        resp = self.client.post(reverse("v1:auth:session-revoke"), {"others_only": True}, format="json")
        self.assertEqual(resp.data["data"]["revoked"], 1)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_active)  # current survived

    def test_revoke_foreign_session_404(self) -> None:
        other_user = make("someone", AuthorityType.LEAD_MANAGER)
        foreign, _ = services.issue_session(user=other_user, device_id="x")
        resp = self.client.post(reverse("v1:auth:session-revoke"), {"session_id": str(foreign.id)}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.SESSION_NOT_FOUND)
