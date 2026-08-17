"""The Django admin must not be a side door around the service layer (§13).

The admin form runs a model's own field validation and nothing else — not the
`_MANAGED_TIER` authority hierarchy, not `normalize_unicode` (§39.2), and not a
single `record_auth_event`. Every field left editable there is therefore a field
whose business rules can be bypassed silently by an `is_superuser` account.

A 2026-08-01 authorization probe exercised two of them: promoting a Lead Manager
straight to Superadmin, and reactivating a blocked account while
`UserSecurityState.blocked_at` stayed set. Both wrote zero audit rows. These
tests pin the fields shut.

Who may reach `/admin/` at all is decided by the OTP gate (`core.apps`, tested
in `core/tests/test_admin_otp.py`): since 2026-08-17 a session with no verified
TOTP device is bounced at the door. These tests therefore log in *verified* —
what they assert is that even an admitted admin gains no authority the API
would refuse.
"""

from __future__ import annotations

from django.test import Client, TestCase
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from authenticate import services
from authenticate.constants import AuthorityType
from authenticate.models import AuthEvent, User, UserSecurityState

STRONG_PW = "Str0ng-Passphrase-17"


def make(username: str, authority: str):
    return services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name=username,
    )


def login_verified(client: Client, user: User) -> None:
    """Log in with a session that has passed the admin's TOTP gate."""
    client.force_login(user)
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()


class AdminPrivilegeEscalationTests(TestCase):
    def setUp(self):
        self.superadmin = make("adm_super", AuthorityType.SUPERADMIN)
        self.victim = make("adm_victim", AuthorityType.LEAD_MANAGER)
        self.client_ = Client()
        login_verified(self.client_, self.superadmin)

    def _post_user_change(self, **overrides):
        data = {
            "username": self.victim.username,
            "authority_type": AuthorityType.LEAD_MANAGER,
            "display_name": "Victim",
            "full_name": "",
            "email": "",
            "phone": "",
            "_save": "Save",
        }
        data.update(overrides)
        return self.client_.post(f"/admin/authenticate/user/{self.victim.pk}/change/", data=data)

    def test_authority_type_cannot_be_raised_through_the_admin(self):
        self._post_user_change(authority_type=AuthorityType.SUPERADMIN)

        self.victim.refresh_from_db()
        self.assertEqual(self.victim.authority_type, AuthorityType.LEAD_MANAGER)

    def test_superuser_and_staff_flags_cannot_be_granted_through_the_admin(self):
        self._post_user_change(is_superuser="on", is_staff="on")

        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_superuser)
        self.assertFalse(self.victim.is_staff)

    def test_a_blocked_account_cannot_be_reactivated_through_the_admin(self):
        """The divergence case: is_active and blocked_at must not disagree."""
        services.block_account(actor=self.superadmin, target=self.victim, reason="probe")
        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_active)

        self._post_user_change(is_active="on")

        self.victim.refresh_from_db()
        state = UserSecurityState.objects.get(user=self.victim)
        self.assertFalse(self.victim.is_active, "admin reactivated a blocked account")
        self.assertIsNotNone(state.blocked_at)

    def test_username_is_immutable_through_the_admin(self):
        self._post_user_change(username="renamed_via_admin")

        self.victim.refresh_from_db()
        self.assertEqual(self.victim.username, "adm_victim")

    def test_accounts_cannot_be_created_through_the_admin(self):
        """Creation must go through the endpoint that also makes the security state."""
        resp = self.client_.get("/admin/authenticate/user/add/")

        self.assertEqual(resp.status_code, 403)


class AdminSecurityStateTests(TestCase):
    def setUp(self):
        self.superadmin = make("adm_super2", AuthorityType.SUPERADMIN)
        self.victim = make("adm_victim2", AuthorityType.LEAD_MANAGER)
        self.client_ = Client()
        login_verified(self.client_, self.superadmin)

    def test_forced_password_change_cannot_be_cleared_through_the_admin(self):
        state = UserSecurityState.objects.get(user=self.victim)
        state.must_change_password = True
        state.save(update_fields=["must_change_password"])

        self.client_.post(
            f"/admin/authenticate/usersecuritystate/{state.pk}/change/",
            data={"_save": "Save"},
        )

        state.refresh_from_db()
        self.assertTrue(state.must_change_password)

    def test_security_state_cannot_be_created_through_the_admin(self):
        resp = self.client_.get("/admin/authenticate/usersecuritystate/add/")

        self.assertEqual(resp.status_code, 403)


class AdminAuditTrailTests(TestCase):
    """Append-only really is append-only, even for a superuser."""

    def setUp(self):
        self.superadmin = make("adm_super3", AuthorityType.SUPERADMIN)
        self.client_ = Client()
        login_verified(self.client_, self.superadmin)

    def test_auth_events_cannot_be_deleted_through_the_admin(self):
        event = services.record_auth_event(
            event_type="login_success",
            subject_username="victim",
            success=True,
        )

        resp = self.client_.post(
            f"/admin/authenticate/authevent/{event.pk}/delete/",
            data={"post": "yes"},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(AuthEvent.objects.filter(pk=event.pk).exists())
