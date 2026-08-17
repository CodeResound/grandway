"""The Django admin must not accept password-only sessions (security audit S3).

The API mandates TOTP for superadmins and revokes sessions server-side; the
admin is gated by ``OTPAdminSite`` so the same credentials cannot open a
password-only side door on a plain session cookie.
"""

from authenticate.constants import AuthorityType
from authenticate.models import User
from django.contrib import admin
from django.test import TestCase
from django_otp.admin import OTPAdminSite


class AdminOtpGateTests(TestCase):
    def test_admin_site_is_otp_gated(self) -> None:
        self.assertIsInstance(admin.site, OTPAdminSite)

    def test_password_authenticated_superadmin_is_not_admitted(self) -> None:
        user = User.objects.create_superuser(
            username="root-admin",
            password="a-long-test-password-123",
        )
        self.assertEqual(user.authority_type, AuthorityType.SUPERADMIN)
        # force_login simulates a successful password login: a session exists
        # but no OTP device was verified, so the admin must bounce to its login.
        self.client.force_login(user)
        response = self.client.get("/admin/", follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_password_hash_never_renders_in_user_admin(self) -> None:
        user_admin = admin.site._registry[User]
        self.assertIn("password", user_admin.exclude)
        self.assertNotIn("password", user_admin.readonly_fields)
