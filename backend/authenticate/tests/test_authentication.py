"""SessionBoundJWTAuthentication: server-side revocation on every request."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authenticate import services
from authenticate.constants import AuthorityType, SessionRevocationReason
from authenticate.models import User

STRONG_PW = "Str0ng-Passphrase-17"


def make_user(username: str = "leadmgr", authority: str = AuthorityType.LEAD_MANAGER) -> User:
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="Lead Manager",
    )


class TestSessionBoundAuth(APITestCase):
    def setUp(self) -> None:
        self.user = make_user()
        self.session, _ = services.issue_session(user=self.user, device_id="dev-a")
        self.access = services.build_access_token(self.user, self.session, must_change_password=False)
        self.me_url = reverse("v1:auth:me")

    def _auth(self, token: str | None = None) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token or self.access}")

    def test_valid_session_accepted(self) -> None:
        self._auth()
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_200_OK)

    def test_revoked_session_rejected(self) -> None:
        services.revoke_session(self.session, SessionRevocationReason.LOGOUT)
        self._auth()
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_blocked_user_rejected(self) -> None:
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self._auth()
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_session_rejected(self) -> None:
        self.session.idle_expires_at = timezone.now() - timedelta(seconds=1)
        self.session.save(update_fields=["idle_expires_at"])
        self._auth()
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_without_session_claim_rejected(self) -> None:
        from rest_framework_simplejwt.tokens import AccessToken

        bare = AccessToken.for_user(self.user)  # no sid claim
        self._auth(str(bare))
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_password_change_invalidates_prior_session(self) -> None:
        # A session whose issue time predates password_changed_at is rejected.
        state = self.user.security_state
        state.password_changed_at = timezone.now() + timedelta(minutes=1)
        state.save(update_fields=["password_changed_at"])
        self._auth()
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_401_UNAUTHORIZED)
