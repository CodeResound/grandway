"""Lead CRUD, owner scoping, search, and filters."""

from __future__ import annotations

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from leads.constants import ErrorCode, LeadStage
from leads.models import Lead
from leads.tests.factories import (
    make_admin,
    make_lead,
    make_lead_manager,
    make_source,
    make_superadmin,
    token_for,
)


class LeadApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.other = make_lead_manager("other")
        self.superadmin = make_superadmin()
        self.source = make_source()
        self.list_url = reverse("v1:leads:lead-list")

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def payload(self, **overrides: object) -> dict:
        base = {
            "full_name_np": "राम श्रेष्ठ",
            "full_name_en": "Ram Shrestha",
            "email": "ram@example.com",
            "source": str(self.source.id),
            "contact_numbers": [{"number": "9800000000", "label": "mobile", "is_primary": True}],
        }
        base.update(overrides)
        return base


class TestLeadCreate(LeadApiTestCase):
    def test_requires_authentication(self) -> None:
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_forbidden(self) -> None:
        self.auth(self.superadmin)
        resp = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_creates_lead_owned_by_creator_at_stage_new(self) -> None:
        self.auth(self.owner)
        resp = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["success"])

        data = resp.data["data"]
        self.assertEqual(data["stage"], LeadStage.NEW)
        self.assertEqual(data["created_by"]["username"], "owner")
        self.assertEqual(len(data["contact_numbers"]), 1)
        # Romanized name is derived by the service, never supplied by the client.
        self.assertNotEqual(data["full_name_romanized"], "")

    def test_contact_number_is_required(self) -> None:
        self.auth(self.owner)
        resp = self.client.post(self.list_url, self.payload(contact_numbers=[]), format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contact_numbers", resp.data["error"]["details"])

    def test_source_requiring_detail_rejects_blank_detail(self) -> None:
        other_source = make_source(code="other", requires_detail=True)
        self.auth(self.owner)
        resp = self.client.post(
            self.list_url,
            self.payload(source=str(other_source.id)),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.SOURCE_DETAIL_REQUIRED)

    def test_inactive_source_is_rejected(self) -> None:
        retired = make_source(code="retired", is_active=False)
        self.auth(self.owner)
        resp = self.client.post(self.list_url, self.payload(source=str(retired.id)), format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.SOURCE_INACTIVE)

    def test_study_interest_is_stored_when_supplied(self) -> None:
        self.auth(self.owner)
        resp = self.client.post(
            self.list_url,
            self.payload(
                study_interest={
                    "interested_countries": ["Australia", "Canada"],
                    "study_level": "masters",
                    "scholarship_interest": True,
                }
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        interest = resp.data["data"]["study_interest"]
        self.assertEqual(interest["interested_countries"], ["Australia", "Canada"])
        self.assertEqual(interest["study_level"], "masters")


class TestLeadScoping(LeadApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.own_lead = make_lead(self.owner, self.source, name_np="राम श्रेष्ठ")
        self.other_lead = make_lead(self.other, self.source, name_np="सीता गुरुङ")

    def test_lead_manager_sees_only_own_leads(self) -> None:
        self.auth(self.owner)
        resp = self.client.get(self.list_url)
        ids = [row["id"] for row in resp.data["data"]]
        self.assertEqual(ids, [str(self.own_lead.id)])

    def test_admin_sees_every_lead(self) -> None:
        self.auth(self.admin)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.data["meta"]["count"], 2)

    def test_other_managers_lead_is_404_not_403(self) -> None:
        """Ownership must never leak: "not yours" is indistinguishable from "missing"."""
        self.auth(self.owner)
        resp = self.client.get(reverse("v1:leads:lead-detail", args=[self.other_lead.id]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.LEAD_NOT_FOUND)

    def test_other_managers_lead_cannot_be_edited(self) -> None:
        self.auth(self.owner)
        resp = self.client.patch(
            reverse("v1:leads:lead-detail", args=[self.other_lead.id]),
            {"full_name_en": "Hijacked"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_lead_is_404(self) -> None:
        self.auth(self.owner)
        resp = self.client.get(reverse("v1:leads:lead-detail", args=["00000000-0000-0000-0000-000000000000"]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class TestLeadListFilters(LeadApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ram = make_lead(self.owner, self.source, name_np="राम श्रेष्ठ")
        self.sita = make_lead(self.owner, self.source, name_np="सीता गुरुङ")
        Lead.objects.filter(pk=self.sita.pk).update(stage=LeadStage.COUNSELLING)

    def test_filter_by_stage(self) -> None:
        self.auth(self.owner)
        resp = self.client.get(self.list_url, {"stage": LeadStage.COUNSELLING})
        ids = [row["id"] for row in resp.data["data"]]
        self.assertEqual(ids, [str(self.sita.id)])

    def test_filter_by_source(self) -> None:
        self.auth(self.owner)
        resp = self.client.get(self.list_url, {"source": str(self.source.id)})
        self.assertEqual(resp.data["meta"]["count"], 2)

    def test_search_matches_devanagari_name(self) -> None:
        self.auth(self.owner)
        resp = self.client.get(self.list_url, {"search": "राम"})
        ids = [row["id"] for row in resp.data["data"]]
        self.assertEqual(ids, [str(self.ram.id)])

    def test_search_matches_romanized_name(self) -> None:
        self.auth(self.owner)
        romanized = Lead.objects.get(pk=self.ram.pk).full_name_romanized
        resp = self.client.get(self.list_url, {"search": romanized[:3]})
        self.assertIn(str(self.ram.id), [row["id"] for row in resp.data["data"]])

    def test_list_uses_standard_pagination_meta(self) -> None:
        self.auth(self.owner)
        meta = self.client.get(self.list_url).data["meta"]
        for key in ("count", "page", "page_size", "next", "previous"):
            self.assertIn(key, meta)


class TestLeadUpdate(LeadApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lead = make_lead(self.owner, self.source)
        self.url = reverse("v1:leads:lead-detail", args=[self.lead.id])

    def test_owner_updates_identity(self) -> None:
        self.auth(self.owner)
        resp = self.client.patch(self.url, {"full_name_en": "Ram B. Shrestha"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["full_name_en"], "Ram B. Shrestha")

    def test_admin_may_correct_any_lead(self) -> None:
        self.auth(self.admin)
        resp = self.client.patch(self.url, {"address": "Lalitpur"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_contact_numbers_replace_wholesale(self) -> None:
        self.auth(self.owner)
        resp = self.client.patch(
            self.url,
            {
                "contact_numbers": [
                    {"number": "9811111111", "label": "mobile", "is_primary": True},
                    {"number": "9822222222", "label": "whatsapp"},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        numbers = {entry["number"] for entry in resp.data["data"]["contact_numbers"]}
        self.assertEqual(numbers, {"9811111111", "9822222222"})

    def test_update_cannot_set_stage(self) -> None:
        """Stage moves only through its own deliberate actions, never a field patch."""
        self.auth(self.owner)
        self.client.patch(self.url, {"stage": LeadStage.CONVERTED}, format="json")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage, LeadStage.NEW)
