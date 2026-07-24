"""Lead source and loss reason endpoints: access, validation, envelopes."""

from __future__ import annotations

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from leads.constants import ErrorCode
from leads.models import LeadSource
from leads.tests.factories import (
    make_admin,
    make_lead_manager,
    make_source,
    make_superadmin,
    token_for,
)


class TestLeadSourceEndpoints(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.superadmin = make_superadmin()
        self.url = reverse("v1:leads:source-list")

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    # --- auth / access -----------------------------------------------------

    def test_requires_authentication(self) -> None:
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_is_forbidden(self) -> None:
        self.auth(self.superadmin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_list_but_not_create(self) -> None:
        make_source()
        self.auth(self.manager)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

        resp = self.client.post(self.url, {"code": "website", "name": "Website"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    # --- behaviour ---------------------------------------------------------

    def test_admin_creates_source(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(
            self.url,
            {"code": "Referral", "name": "Referral"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["success"])
        # Code is normalized to lowercase ASCII.
        self.assertEqual(resp.data["data"]["code"], "referral")
        self.assertEqual(resp.data["data"]["name"], "Referral")

    def test_duplicate_code_conflicts(self) -> None:
        make_source(code="walk_in")
        self.auth(self.admin)
        resp = self.client.post(self.url, {"code": "walk_in", "name": "Walk-in"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.SOURCE_CODE_TAKEN)

    def test_invalid_code_is_a_field_error(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(self.url, {"name": "Walk-in"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data["success"])
        self.assertIn("code", resp.data["error"]["details"])

    def test_list_hides_inactive_unless_requested(self) -> None:
        make_source(code="active_one")
        make_source(code="retired_one", is_active=False)
        self.auth(self.manager)

        visible = self.client.get(self.url).data["data"]
        self.assertEqual([entry["code"] for entry in visible], ["active_one"])

        everything = self.client.get(self.url, {"include_inactive": "true"}).data["data"]
        self.assertEqual(len(everything), 2)

    def test_admin_deactivates_rather_than_deletes(self) -> None:
        source = make_source()
        self.auth(self.admin)
        resp = self.client.patch(
            reverse("v1:leads:source-detail", args=[source.id]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["data"]["is_active"])
        self.assertTrue(LeadSource.objects.filter(pk=source.id).exists())

    def test_unknown_source_is_404(self) -> None:
        self.auth(self.admin)
        resp = self.client.patch(
            reverse("v1:leads:source-detail", args=["00000000-0000-0000-0000-000000000000"]),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.SOURCE_NOT_FOUND)


class TestLossReasonEndpoints(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.url = reverse("v1:leads:loss-reason-list")

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def test_lead_manager_may_list(self) -> None:
        self.auth(self.manager)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])

    def test_lead_manager_may_not_create(self) -> None:
        self.auth(self.manager)
        resp = self.client.post(self.url, {"code": "other", "name": "Other"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_creates_reason(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(
            self.url,
            {"code": "other", "requires_detail": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["data"]["requires_detail"])
