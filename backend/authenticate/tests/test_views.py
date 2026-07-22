"""Endpoint tests: envelopes, auth failures, device limits, lockout, rotation."""

from __future__ import annotations

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from authenticate import services
from authenticate.constants import AuthorityType, ErrorCode

STRONG_PW = "Str0ng-Passphrase-17"
NEW_PW = "An0ther-Str0ng-Phrase-42"


def make_user(username: str = "leadmgr", password: str = STRONG_PW, must_change: bool = False) -> object:
    return services.create_account(
        username=username,
        password=password,
        authority_type=AuthorityType.LEAD_MANAGER,
        provisioned_via="admin_created",
        must_change_password=must_change,
        display_name="Lead Manager",
    )


class TestLoginEndpoint(APITestCase):
    def setUp(self) -> None:
        self.url = reverse("v1:auth:login")
        self.user = make_user()

    def _login(self, **overrides: object) -> object:
        payload = {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"}
        payload.update(overrides)
        return self.client.post(self.url, payload, format="json")

    def test_success_envelope(self) -> None:
        resp = self._login()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        self.assertIn("access", resp.data["data"])
        self.assertIn("refresh", resp.data["data"])  # body mode in dev/testing
        self.assertEqual(resp.data["data"]["user"]["username"], "leadmgr")
        self.assertIn("meta", resp.data)

    def test_wrong_password_is_uniform_401(self) -> None:
        resp = self._login(password="incorrect-password")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(resp.data["success"])
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CREDENTIALS_INVALID)

    def test_unknown_user_same_error_as_wrong_password(self) -> None:
        resp = self._login(username="ghost")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CREDENTIALS_INVALID)

    def test_missing_device_id_is_validation_error(self) -> None:
        resp = self.client.post(self.url, {"username": "leadmgr", "password": STRONG_PW}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], "VALIDATION_ERROR")

    def test_fourth_device_conflict(self) -> None:
        for dev in ("a", "b", "c"):
            self.assertEqual(self._login(device_id=f"dev-{dev}").status_code, status.HTTP_200_OK)
        resp = self._login(device_id="dev-d")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.DEVICE_LIMIT_REACHED)

    def test_lockout_does_not_leak(self) -> None:
        # Exhaust the axes failure limit, then a CORRECT password must still fail
        # with the identical generic error (no lockout signal).
        for _ in range(6):
            self._login(password="incorrect-password")
        resp = self._login(password=STRONG_PW)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CREDENTIALS_INVALID)


class TestForcedPasswordChange(APITestCase):
    def setUp(self) -> None:
        self.user = make_user(must_change=True)

    def test_login_reports_must_change(self) -> None:
        resp = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.assertTrue(resp.data["data"]["must_change_password"])

    def test_change_clears_flag_and_revokes_sessions(self) -> None:
        login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        access = login.data["data"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        change = self.client.post(
            reverse("v1:auth:password-change"),
            {"current_password": STRONG_PW, "new_password": NEW_PW},
            format="json",
        )
        self.assertEqual(change.status_code, status.HTTP_200_OK)
        # session was revoked by the password change → old access now rejected
        me = self.client.get(reverse("v1:auth:me"))
        self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_weak_new_password_rejected(self) -> None:
        login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['data']['access']}")
        resp = self.client.post(
            reverse("v1:auth:password-change"),
            {"current_password": STRONG_PW, "new_password": "123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.PASSWORD_WEAK)

    def test_wrong_current_password_rejected(self) -> None:
        login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['data']['access']}")
        resp = self.client.post(
            reverse("v1:auth:password-change"),
            {"current_password": "nope", "new_password": NEW_PW},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.PASSWORD_INCORRECT)


class TestProtectedEndpointsRequireAuth(APITestCase):
    def test_me_requires_auth(self) -> None:
        resp = self.client.get(reverse("v1:auth:me"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(resp.data["success"])

    def test_logout_requires_auth(self) -> None:
        resp = self.client.post(reverse("v1:auth:logout"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class TestSessionLifecycleEndpoints(APITestCase):
    def setUp(self) -> None:
        make_user()
        self.login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.access = self.login.data["data"]["access"]
        self.refresh = self.login.data["data"]["refresh"]

    def _auth(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")

    def test_me_returns_current_user(self) -> None:
        self._auth()
        resp = self.client.get(reverse("v1:auth:me"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["username"], "leadmgr")
        self.assertFalse(resp.data["data"]["must_change_password"])

    def test_refresh_rotates(self) -> None:
        resp = self.client.post(reverse("v1:auth:refresh"), {"refresh": self.refresh}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data["data"])
        self.assertNotEqual(resp.data["data"]["refresh"], self.refresh)

    def test_refresh_reuse_detected(self) -> None:
        self.client.post(reverse("v1:auth:refresh"), {"refresh": self.refresh}, format="json")
        resp = self.client.post(reverse("v1:auth:refresh"), {"refresh": self.refresh}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.REFRESH_REUSED)

    def test_logout_revokes_session(self) -> None:
        self._auth()
        logout = self.client.post(reverse("v1:auth:logout"))
        self.assertEqual(logout.status_code, status.HTTP_200_OK)
        me = self.client.get(reverse("v1:auth:me"))
        self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_refresh_is_invalid(self) -> None:
        resp = self.client.post(reverse("v1:auth:refresh"), {"refresh": ""}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.REFRESH_INVALID)
