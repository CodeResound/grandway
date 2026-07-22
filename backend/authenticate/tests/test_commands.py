"""Tests for deployment recovery management commands."""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice

from authenticate import services
from authenticate.constants import AuthorityType
from authenticate.models import User
from authenticate.selectors import has_confirmed_mfa

STRONG_PW = "Str0ng-Passphrase-17"


def make(username: str, authority: str) -> User:
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="bootstrap_command",
        must_change_password=False,
        display_name="U",
    )


class TestRecoveryCommands(TestCase):
    def test_reset_superadmin_password_forces_change(self) -> None:
        sup = make("superadmin", AuthorityType.SUPERADMIN)
        call_command("reset_superadmin_password", "--username", "superadmin", "--password", "Br4nd-New-Passphrase")
        sup.refresh_from_db()
        self.assertTrue(sup.check_password("Br4nd-New-Passphrase"))
        self.assertTrue(sup.security_state.must_change_password)

    def test_reset_superadmin_password_refuses_non_superadmin(self) -> None:
        make("adminx", AuthorityType.ADMIN)
        with self.assertRaises(CommandError):
            call_command("reset_superadmin_password", "--username", "adminx")

    def test_reset_superadmin_mfa_removes_device(self) -> None:
        sup = make("superadmin", AuthorityType.SUPERADMIN)
        TOTPDevice.objects.create(user=sup, name="default", confirmed=True)
        call_command("reset_superadmin_mfa", "--username", "superadmin")
        self.assertFalse(has_confirmed_mfa(sup))
