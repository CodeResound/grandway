"""Applicant endpoints: access, creation, editing, status, search, history."""

from __future__ import annotations

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from applicants.constants import ApplicantAuditAction, ApplicantStatus, CreationSource, ErrorCode
from applicants.models import Applicant
from applicants.tests.factories import (
    make_admin,
    make_applicant,
    make_lead_manager,
    make_superadmin,
    token_for,
)


class ApplicantApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.superadmin = make_superadmin()
        self.list_url = reverse("v1:applicants:applicant-list")

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def payload(self, **overrides: object) -> dict:
        base = {
            "full_name": "Ram Shrestha",
            "email": "ram@example.com",
            "contact_numbers": [{"number": "9800000000", "label": "mobile", "is_primary": True}],
        }
        base.update(overrides)
        return base


class TestApplicantAccess(ApplicantApiTestCase):
    def test_requires_authentication(self) -> None:
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_is_forbidden(self) -> None:
        self.auth(self.superadmin)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_not_create(self) -> None:
        """Entry into the applicant lifecycle is an Admin decision."""
        self.auth(self.manager)
        resp = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_sees_every_applicant(self) -> None:
        """Applicants are shared, unlike leads — no owner scoping."""
        make_applicant(self.admin)
        make_applicant(self.admin)
        self.auth(self.manager)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.data["meta"]["count"], 2)

    def test_lead_manager_may_edit_any_applicant(self) -> None:
        applicant = make_applicant(self.admin)
        self.auth(self.manager)
        resp = self.client.patch(
            reverse("v1:applicants:applicant-detail", args=[applicant.id]),
            {"nationality": "Nepali"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_missing_applicant_is_404(self) -> None:
        self.auth(self.manager)
        resp = self.client.get(
            reverse("v1:applicants:applicant-detail", args=["00000000-0000-0000-0000-000000000000"])
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.APPLICANT_NOT_FOUND)


class TestApplicantCreate(ApplicantApiTestCase):
    def test_admin_creates_applicant(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.data["data"]
        self.assertEqual(data["status"], ApplicantStatus.ACTIVE)
        self.assertEqual(data["creation_source"], CreationSource.DIRECT_ADMIN)
        self.assertIsNone(data["originating_lead_id"])

    def test_contact_number_is_required(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(self.list_url, self.payload(contact_numbers=[]), format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contact_numbers", resp.data["error"]["details"])

    def test_full_profile_is_stored(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(
            self.list_url,
            self.payload(
                date_of_birth="2002-05-14",
                gender="male",
                addresses=[
                    {"address_type": "permanent", "district": "Lalitpur", "ward": "5"},
                    {"address_type": "current", "district": "Kathmandu"},
                ],
                passport={
                    "passport_number": "pa1234567",
                    "issued_date": "2022-01-01",
                    "expiry_date": "2032-01-01",
                },
                family_members=[{"relationship": "father", "full_name": "Hari Shrestha"}],
                emergency_contacts=[{"contact_number": "9812345678"}],
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.data["data"]
        self.assertEqual(len(data["addresses"]), 2)
        self.assertEqual(len(data["family_members"]), 1)
        self.assertEqual(len(data["emergency_contacts"]), 1)
        # Passport numbers are upper-cased on write.
        self.assertEqual(data["passport"]["passport_number"], "PA1234567")
        # Dates carry a Bikram Sambat companion (§39.4).
        self.assertIsNotNone(data["date_of_birth_bs"])
        self.assertIsNotNone(data["passport"]["expiry_date_bs"])

    def test_passport_expiry_must_follow_issue_date(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(
            self.list_url,
            self.payload(
                passport={
                    "passport_number": "PA1",
                    "issued_date": "2030-01-01",
                    "expiry_date": "2020-01-01",
                }
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.PASSPORT_EXPIRY_INVALID)

    def test_duplicate_address_type_is_rejected(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(
            self.list_url,
            self.payload(
                addresses=[
                    {"address_type": "permanent", "district": "Lalitpur"},
                    {"address_type": "permanent", "district": "Kathmandu"},
                ]
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("addresses", resp.data["error"]["details"])


class TestApplicantUpdate(ApplicantApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.applicant = make_applicant(self.admin)
        self.url = reverse("v1:applicants:applicant-detail", args=[self.applicant.id])
        self.auth(self.admin)

    def test_identity_is_corrected(self) -> None:
        resp = self.client.patch(self.url, {"full_name": "Ram B. Shrestha"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["full_name"], "Ram B. Shrestha")

    def test_contact_numbers_replace_wholesale(self) -> None:
        resp = self.client.patch(
            self.url,
            {"contact_numbers": [{"number": "9811111111"}, {"number": "9822222222"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        numbers = {entry["number"] for entry in resp.data["data"]["contact_numbers"]}
        self.assertEqual(numbers, {"9811111111", "9822222222"})

    def test_update_cannot_set_status(self) -> None:
        """Status moves only through its own action, never a field patch."""
        self.client.patch(self.url, {"status": ApplicantStatus.ARCHIVED}, format="json")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, ApplicantStatus.ACTIVE)

    def test_update_cannot_change_creation_source(self) -> None:
        self.client.patch(self.url, {"creation_source": CreationSource.LEAD_CONVERSION}, format="json")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.creation_source, CreationSource.DIRECT_ADMIN)

    def test_passport_upserts_rather_than_duplicating(self) -> None:
        self.client.patch(self.url, {"passport": {"passport_number": "AA1"}}, format="json")
        resp = self.client.patch(self.url, {"passport": {"passport_number": "BB2"}}, format="json")
        self.assertEqual(resp.data["data"]["passport"]["passport_number"], "BB2")


class TestApplicantStatus(ApplicantApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.applicant = make_applicant(self.admin)
        self.url = reverse("v1:applicants:applicant-status", args=[self.applicant.id])
        self.auth(self.admin)

    def test_status_changes(self) -> None:
        resp = self.client.post(self.url, {"status": ApplicantStatus.DORMANT}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["status"], ApplicantStatus.DORMANT)

    def test_archiving_does_not_delete(self) -> None:
        self.client.post(self.url, {"status": ApplicantStatus.ARCHIVED}, format="json")
        self.assertTrue(Applicant.objects.filter(pk=self.applicant.pk).exists())

    def test_invalid_status_rejected(self) -> None:
        resp = self.client.post(self.url, {"status": "nonsense"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", resp.data["error"]["details"])


class TestApplicantListFilters(ApplicantApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ram = make_applicant(self.admin, name="Ram Shrestha")
        self.sita = make_applicant(self.admin, name="Sita Gurung")
        Applicant.objects.filter(pk=self.sita.pk).update(status=ApplicantStatus.DORMANT)
        self.auth(self.manager)

    def test_filter_by_status(self) -> None:
        resp = self.client.get(self.list_url, {"status": ApplicantStatus.DORMANT})
        self.assertEqual([row["id"] for row in resp.data["data"]], [str(self.sita.id)])

    def test_search_matches_name(self) -> None:
        resp = self.client.get(self.list_url, {"search": "Ram"})
        self.assertEqual([row["id"] for row in resp.data["data"]], [str(self.ram.id)])

    def test_search_is_case_insensitive(self) -> None:
        resp = self.client.get(self.list_url, {"search": "sita"})
        self.assertIn(str(self.sita.id), [row["id"] for row in resp.data["data"]])

    def test_pagination_meta_shape(self) -> None:
        meta = self.client.get(self.list_url).data["meta"]
        for key in ("count", "page", "page_size", "next", "previous"):
            self.assertIn(key, meta)


class TestApplicantHistory(ApplicantApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.applicant = make_applicant(self.admin)
        self.auth(self.admin)

    def test_history_records_creation_and_changes(self) -> None:
        self.client.patch(
            reverse("v1:applicants:applicant-detail", args=[self.applicant.id]),
            {"full_name": "Ram B."},
            format="json",
        )
        self.client.post(
            reverse("v1:applicants:applicant-status", args=[self.applicant.id]),
            {"status": ApplicantStatus.DORMANT},
            format="json",
        )
        history = self.client.get(reverse("v1:applicants:applicant-history", args=[self.applicant.id])).data["data"]
        actions = [entry["action"] for entry in history]
        for expected in (
            ApplicantAuditAction.APPLICANT_CREATED,
            ApplicantAuditAction.APPLICANT_UPDATED,
            ApplicantAuditAction.APPLICANT_STATUS_CHANGED,
        ):
            self.assertIn(expected, actions)
        # Newest first.
        self.assertEqual(actions[0], ApplicantAuditAction.APPLICANT_STATUS_CHANGED)

    def test_status_change_carries_from_and_to(self) -> None:
        self.client.post(
            reverse("v1:applicants:applicant-status", args=[self.applicant.id]),
            {"status": ApplicantStatus.ARCHIVED},
            format="json",
        )
        history = self.client.get(reverse("v1:applicants:applicant-history", args=[self.applicant.id])).data["data"]
        entry = next(e for e in history if e["action"] == ApplicantAuditAction.APPLICANT_STATUS_CHANGED)
        self.assertEqual(
            entry["changes"]["status"],
            {"from": ApplicantStatus.ACTIVE, "to": ApplicantStatus.ARCHIVED},
        )
