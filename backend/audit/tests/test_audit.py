"""Audit app tests: record_event, immutability, read endpoints + access, integration."""

from __future__ import annotations

from authenticate import services as auth_services
from authenticate.constants import AuthorityType
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from audit import services as audit_services
from audit.exceptions import ImmutabilityError
from audit.models import AuditEvent

STRONG_PW = "Str0ng-Passphrase-17"


def make(username: str, authority: str) -> object:
    return auth_services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="U",
    )


def token_for(user: object) -> str:
    session, _ = auth_services.issue_session(user=user, device_id=f"t-{user.username}")
    return auth_services.build_access_token(user, session, must_change_password=False)


class TestRecordAndImmutability(TestCase):
    def test_record_event_appends(self) -> None:
        event = audit_services.record_event(
            app_label="authenticate", action="login_success", actor_type="admin", actor_label="x"
        )
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(event.app_label, "authenticate")

    def test_bulk_delete_blocked(self) -> None:
        audit_services.record_event(app_label="authenticate", action="login_success")
        with self.assertRaises(ImmutabilityError):
            AuditEvent.objects.all().delete()

    def test_instance_delete_blocked(self) -> None:
        event = audit_services.record_event(app_label="authenticate", action="login_success")
        with self.assertRaises(ImmutabilityError):
            event.delete()


class TestAuditReadEndpoints(APITestCase):
    def setUp(self) -> None:
        self.admin = make("adminx", AuthorityType.ADMIN)
        self.lead = make("leadmgr", AuthorityType.LEAD_MANAGER)
        audit_services.record_event(
            app_label="authenticate", action="login_success", entity_type="authenticate.user", actor_label="a"
        )
        audit_services.record_event(app_label="authenticate", action="account_blocked", actor_label="b")

    def test_requires_auth(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lead_manager_forbidden(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.lead)}")
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_lists_paginated(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["meta"]["count"], 2)

    def test_filter_by_action(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        resp = self.client.get(reverse("v1:audit:event-list"), {"action": "account_blocked"})
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_malformed_filters_are_400_not_500(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        for params in ({"actor_id": "not-a-uuid"}, {"success": "maybe"}, {"fiscal_year": "garbage"}):
            resp = self.client.get(reverse("v1:audit:event-list"), params)
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, params)
            self.assertEqual(resp.data["error"]["code"], "VALIDATION_ERROR")

    def test_detail_and_404(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        event = AuditEvent.objects.first()
        ok = self.client.get(reverse("v1:audit:event-detail", args=[event.id]))
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        missing = self.client.get(reverse("v1:audit:event-detail", args=["00000000-0000-0000-0000-000000000000"]))
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.data["error"]["code"], "AUDIT_EVENT_NOT_FOUND")


class TestAuthenticateEmitsToAudit(APITestCase):
    def test_login_creates_central_audit_event(self) -> None:
        make("leadmgr", AuthorityType.LEAD_MANAGER)
        before = AuditEvent.objects.filter(app_label="authenticate").count()
        resp = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "d1"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        after = AuditEvent.objects.filter(app_label="authenticate", action="login_success").count()
        self.assertGreater(after, before)
