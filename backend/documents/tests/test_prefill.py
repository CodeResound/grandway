"""Document prefill — GET /api/v1/documents/prefill/<applicant_id>/ (2026-10-29, updates.md §7.2).

Read-only and Admin-only. These pin the shape the Woda and certificate forms
fill from, the name split, the newest-relative rule, and the photo convention.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from applicants import services as applicant_services
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from uploaded_files import services as file_services
from uploaded_files.constants import FileCategory
from uploaded_files.tests import factories as file_factories

from documents.serializers import split_full_name
from documents.tests import factories as f
from documents.tests.test_certificate_and_versions import MediaRootMixin


class NameSplitTests(TestCase):
    def test_split(self) -> None:
        self.assertEqual(split_full_name(""), ("", "", ""))
        self.assertEqual(split_full_name("Ram"), ("Ram", "", ""))
        self.assertEqual(split_full_name("Ram Thapa"), ("Ram", "", "Thapa"))
        self.assertEqual(split_full_name("Ram  Bahadur Kumar   Thapa"), ("Ram", "Bahadur Kumar", "Thapa"))


class PrefillApiTests(MediaRootMixin, APITestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin, name="Ram Bahadur Thapa")
        self.url = reverse("v1:documents:document-prefill", args=[self.applicant.id])

    def get(self, user: Any = None) -> Any:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token_for(user or self.admin)}")
        return self.client.get(self.url)

    def photo(self, **overrides: Any) -> Any:
        return file_factories.upload_for_applicant(
            self.admin,
            self.applicant,
            category=FileCategory.PHOTOGRAPH,
            upload=file_factories.jpeg_upload(),
            **overrides,
        )

    def test_admin_only(self) -> None:
        self.assertEqual(self.get(f.make_lead_manager()).status_code, 403)
        self.assertEqual(self.get(f.make_superadmin()).status_code, 403)

    def test_unknown_applicant(self) -> None:
        self.url = reverse("v1:documents:document-prefill", args=["2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819"])
        response = self.get()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "DOCUMENTS_APPLICANT_NOT_FOUND")

    def test_empty_file_has_the_full_shape(self) -> None:
        data = self.get().json()["data"]
        self.assertEqual(
            set(data),
            {
                "applicant",
                "father",
                "mother",
                "grandfather",
                "grandmother",
                "educations",
                "language_tests",
                "photo_media_id",
            },
        )
        applicant = data["applicant"]
        self.assertEqual(
            (applicant["first_name"], applicant["middle_name"], applicant["last_name"]), ("Ram", "Bahadur", "Thapa")
        )
        self.assertIsNone(applicant["permanent_address"])
        self.assertEqual(applicant["primary_phone"], "9800000000")
        self.assertEqual(applicant["passport_no"], "")
        self.assertIsNone(data["father"])
        self.assertEqual((data["educations"], data["language_tests"]), ([], []))
        self.assertIsNone(data["photo_media_id"])
        self.assertNotIn("name_native", applicant)

    def test_full_file(self) -> None:
        applicant_services.update_applicant(
            actor=self.admin,
            applicant=self.applicant,
            fields={"citizenship_no": "27-01-75-12345", "citizenship_issue_district": "Kathmandu"},
            addresses=[
                {
                    "address_type": "permanent",
                    "province": "Bagmati",
                    "district": "Kathmandu",
                    "municipality": "Kathmandu Metropolitan City",
                    "ward": "10",
                    "street_address": "Baneshwor",
                }
            ],
            family_members=[
                {
                    "relationship": "father",
                    "full_name": "Hari Thapa",
                    "occupation": "Teacher",
                    "citizenship_no": "1-1",
                },
                {"relationship": "grandmother", "full_name": "Gita Thapa"},
            ],
            educations=[{"level": "plus_two", "qualification": "Science", "completion_status": "completed"}],
            language_tests=[{"test_type": "ielts", "overall_score": "7.0", "test_date": timezone.now().date()}],
            passport={"passport_number": "PA1234567"},
        )
        data = self.get().json()["data"]
        applicant = data["applicant"]
        self.assertEqual(applicant["citizenship_no"], "27-01-75-12345")
        self.assertEqual(applicant["passport_no"], "PA1234567")
        self.assertEqual(
            applicant["permanent_address"],
            {
                "province": "Bagmati",
                "district": "Kathmandu",
                "municipality": "Kathmandu Metropolitan City",
                "ward_no": "10",
                "tole": "Baneshwor",
                "formatted": "Baneshwor, Kathmandu Metropolitan City-10, Kathmandu, Bagmati",
            },
        )
        self.assertEqual(data["father"], {"name": "Hari Thapa", "citizenship_no": "1-1", "occupation": "Teacher"})
        self.assertEqual(data["grandmother"]["name"], "Gita Thapa")
        self.assertIsNone(data["mother"])
        self.assertEqual(data["educations"][0]["level"], "plus_two")
        self.assertEqual(data["language_tests"][0]["overall_score"], "7.0")
        self.assertIsNotNone(data["language_tests"][0]["test_date_bs"])

    def test_newest_relative_wins(self) -> None:
        applicant_services.update_applicant(
            actor=self.admin,
            applicant=self.applicant,
            fields={},
            family_members=[{"relationship": "father", "full_name": "First Entry"}],
        )
        first = self.applicant.family_members.get()
        type(first).objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=1))
        type(first).objects.create(applicant=self.applicant, relationship="father", full_name="Second Entry")
        self.assertEqual(self.get().json()["data"]["father"]["name"], "Second Entry")

    def test_photo_is_newest_current_unarchived_photograph(self) -> None:
        old = self.photo()
        newest = self.photo()
        self.assertEqual(self.get().json()["data"]["photo_media_id"], str(newest.id))

        file_services.archive_file(actor=self.admin, uploaded_file=newest, reason="Blurry.")
        self.assertEqual(self.get().json()["data"]["photo_media_id"], str(old.id))

        file_factories.upload_for_applicant(self.admin, self.applicant, category=FileCategory.PASSPORT)
        self.assertEqual(self.get().json()["data"]["photo_media_id"], str(old.id))

    def test_superseded_photo_is_skipped(self) -> None:
        old = self.photo()
        replacement = file_services.replace_file(
            actor=self.admin, uploaded_file=old, upload=file_factories.jpeg_upload("new.jpg")
        )
        self.assertEqual(self.get().json()["data"]["photo_media_id"], str(replacement.id))
