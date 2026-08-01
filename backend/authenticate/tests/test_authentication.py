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


class TestAuthenticationQueryCost(APITestCase):
    """Authenticating a request is the hottest query path in the project.

    Every authenticated call to every endpoint in every app runs
    ``SessionBoundJWTAuthentication.get_user`` first, so a stray query here is
    multiplied by the whole request volume of the system rather than by one
    endpoint's.

    Two queries, and both are load-bearing: SimpleJWT's own user lookup (which
    validates the subject claim and ``is_active``), and the session lookup that
    makes revocation take effect immediately. The security state comes back
    joined onto the second — reading it off the *first* user instance instead
    would silently add a third.
    """

    def setUp(self) -> None:
        self.user = make_user()
        self.session, _ = services.issue_session(user=self.user, device_id="dev-a")
        self.access = services.build_access_token(self.user, self.session, must_change_password=False)

    def test_get_user_costs_two_queries(self) -> None:
        from rest_framework_simplejwt.tokens import AccessToken

        from authenticate.authentication import SessionBoundJWTAuthentication

        validated = AccessToken(self.access)
        auth = SessionBoundJWTAuthentication()

        with self.assertNumQueries(2):
            user = auth.get_user(validated)

        self.assertEqual(user.id, self.user.id)

    def test_forced_password_change_flag_is_read_without_an_extra_query(self) -> None:
        """The flag is what pulls the security state in — assert it still works."""
        from rest_framework_simplejwt.tokens import AccessToken

        from authenticate.authentication import SessionBoundJWTAuthentication

        state = self.user.security_state
        state.must_change_password = True
        state.save(update_fields=["must_change_password"])

        validated = AccessToken(self.access)
        with self.assertNumQueries(2):
            user = SessionBoundJWTAuthentication().get_user(validated)

        self.assertTrue(user.must_change_password)
