"""MFA (TOTP) tests: enrollment, login MFA step, disable, superadmin rules."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status
from rest_framework.test import APITestCase

from authenticate import services
from authenticate.constants import AuthorityType, ErrorCode
from authenticate.exceptions import MfaMandatoryError
from authenticate.models import AuthSession, User
from authenticate.selectors import has_confirmed_mfa

STRONG_PW = "Str0ng-Passphrase-17"


def make_user(username: str = "leadmgr", authority: str = AuthorityType.LEAD_MANAGER) -> User:
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="User",
    )


def make_confirmed_device(user: User) -> TOTPDevice:
    return TOTPDevice.objects.create(user=user, name="default", confirmed=True)


def current_code(device: TOTPDevice) -> str:
    value = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift)
    return f"{value:0{device.digits}d}"


class TestMfaEnrollmentService(TestCase):
    def test_enroll_returns_secret_and_url(self) -> None:
        user = make_user()
        result = services.begin_mfa_enrollment(user)
        self.assertIn("secret", result)
        self.assertTrue(result["otpauth_url"].startswith("otpauth://totp/"))
        self.assertFalse(has_confirmed_mfa(user))  # not active until confirmed

    def test_confirm_activates_mfa(self) -> None:
        user = make_user()
        services.begin_mfa_enrollment(user)
        device = services.get_unconfirmed_totp_device(user)
        services.confirm_mfa_enrollment(user, current_code(device))
        self.assertTrue(has_confirmed_mfa(user))

    def test_confirm_invalid_code_rejected(self) -> None:
        from authenticate.exceptions import MfaInvalidError

        user = make_user()
        services.begin_mfa_enrollment(user)
        with self.assertRaises(MfaInvalidError):
            services.confirm_mfa_enrollment(user, "000000")

    def test_superadmin_mfa_mandatory_flag(self) -> None:
        sup = make_user(username="root", authority=AuthorityType.SUPERADMIN)
        self.assertTrue(services.mfa_enrollment_required(sup))
        device = make_confirmed_device(sup)
        self.assertFalse(services.mfa_enrollment_required(sup))
        self.assertTrue(has_confirmed_mfa(sup))
        self.assertIsNotNone(device)

    def test_superadmin_cannot_disable(self) -> None:
        sup = make_user(username="root", authority=AuthorityType.SUPERADMIN)
        device = make_confirmed_device(sup)
        with self.assertRaises(MfaMandatoryError):
            services.disable_mfa(sup, STRONG_PW, current_code(device))

    def test_reset_mfa_removes_device_and_sessions(self) -> None:
        user = make_user()
        make_confirmed_device(user)
        services.issue_session(user=user, device_id="dev-a")
        removed = services.reset_mfa(user, reason="test")
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(has_confirmed_mfa(user))
        self.assertEqual(AuthSession.objects.filter(user=user, is_active=True).count(), 0)


class TestMfaLogin(APITestCase):
    def setUp(self) -> None:
        self.user = make_user()
        self.device = make_confirmed_device(self.user)
        self.url = reverse("v1:auth:login")

    def _login(self, **extra: object) -> object:
        payload = {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"}
        payload.update(extra)
        return self.client.post(self.url, payload, format="json")

    def test_login_without_code_requires_mfa(self) -> None:
        resp = self._login()
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.MFA_REQUIRED)

    def test_login_wrong_code_invalid(self) -> None:
        resp = self._login(otp_code="000000")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.MFA_INVALID)

    def test_login_with_valid_code_succeeds(self) -> None:
        resp = self._login(otp_code=current_code(self.device))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data["data"])


class TestMfaEndpoints(APITestCase):
    def setUp(self) -> None:
        make_user()
        login = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "dev-a"},
            format="json",
        )
        self.access = login.data["data"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.user = User.objects.get(username="leadmgr")

    def test_enroll_then_verify(self) -> None:
        enroll = self.client.post(reverse("v1:auth:mfa-enroll"))
        self.assertEqual(enroll.status_code, status.HTTP_200_OK)
        self.assertIn("secret", enroll.data["data"])
        device = services.get_unconfirmed_totp_device(self.user)
        verify = self.client.post(reverse("v1:auth:mfa-verify"), {"code": current_code(device)}, format="json")
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        self.assertTrue(has_confirmed_mfa(self.user))

    def test_me_exposes_mfa_flags(self) -> None:
        resp = self.client.get(reverse("v1:auth:me"))
        self.assertFalse(resp.data["data"]["mfa_enabled"])
        self.assertFalse(resp.data["data"]["mfa_enrollment_required"])
        make_confirmed_device(self.user)
        resp2 = self.client.get(reverse("v1:auth:me"))
        self.assertTrue(resp2.data["data"]["mfa_enabled"])

    def test_disable_requires_password_and_code(self) -> None:
        device = make_confirmed_device(self.user)
        resp = self.client.post(
            reverse("v1:auth:mfa-disable"),
            {"current_password": STRONG_PW, "code": current_code(device)},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(has_confirmed_mfa(self.user))

    def test_disable_wrong_password_rejected(self) -> None:
        device = make_confirmed_device(self.user)
        resp = self.client.post(
            reverse("v1:auth:mfa-disable"),
            {"current_password": "wrong", "code": current_code(device)},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.PASSWORD_INCORRECT)

    def test_enroll_when_already_enrolled_conflicts(self) -> None:
        make_confirmed_device(self.user)
        resp = self.client.post(reverse("v1:auth:mfa-enroll"))
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.MFA_ALREADY_ENROLLED)
