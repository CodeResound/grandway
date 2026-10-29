"""Applicant education, language tests, and Woda identity data (2026-10-29, updates.md §1.5, §7.2).

Both collections travel inline on the applicant payload and replace wholesale,
exactly like family members — these tests pin that contract and the per-field
error paths a form needs to mark the right input.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from django.urls import reverse
from rest_framework.test import APITestCase

from applicants.constants import ApplicantAuditAction, ErrorCode
from applicants.models import ApplicantEducation, ApplicantLanguageTest
from applicants.tests.factories import make_admin, make_applicant, make_lead_manager, token_for

EDUCATION = {
    "level": "bachelor",
    "qualification": "BBS",
    "institution": "Shanker Dev Campus",
    "country": "Nepal",
    "completion_status": "completed",
    "score": "3.45",
    "score_type": "gpa",
    "grading_system": "GPA (4.0)",
    "start_year": 2076,
    "completion_year": 2080,
    "year_calendar": "bs",
}
IELTS = {
    "test_type": "ielts",
    "overall_score": "7.0",
    "listening_score": "7.5",
    "reading_score": "6.5",
    "writing_score": "6.5",
    "speaking_score": "7.0",
    "test_date": "2025-03-01",
    "certificate_number": "25NP000123",
    "expiry_date": "2027-03-01",
}


class AcademicRecordsApiTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.applicant = make_applicant(self.admin)
        self.url = reverse("v1:applicants:applicant-detail", args=[self.applicant.id])

    def patch(self, user: Any, payload: dict[str, Any]) -> Any:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")
        return self.client.patch(self.url, payload, format="json")

    def test_lead_manager_writes_both_collections(self) -> None:
        response = self.patch(self.manager, {"educations": [EDUCATION], "language_tests": [IELTS]})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["educations"][0]["level"], "bachelor")
        self.assertEqual(data["educations"][0]["score"], "3.45")
        test = data["language_tests"][0]
        self.assertEqual((test["test_type"], test["overall_score"]), ("ielts", "7.0"))
        self.assertIsNotNone(test["test_date_bs"])
        self.assertIsNotNone(test["expiry_date_bs"])

    def test_replace_omit_and_clear(self) -> None:
        self.patch(
            self.admin,
            {"language_tests": [IELTS, {"test_type": "pte", "overall_score": "65", "speaking_score": "70"}]},
        )
        self.assertEqual(ApplicantLanguageTest.objects.filter(applicant=self.applicant).count(), 2)
        self.patch(self.admin, {"full_name": "Ram Shrestha Updated"})  # key omitted: untouched
        self.assertEqual(ApplicantLanguageTest.objects.filter(applicant=self.applicant).count(), 2)
        self.patch(self.admin, {"language_tests": [IELTS]})
        self.assertEqual(ApplicantLanguageTest.objects.filter(applicant=self.applicant).count(), 1)
        self.patch(self.admin, {"language_tests": []})
        self.assertFalse(ApplicantLanguageTest.objects.filter(applicant=self.applicant).exists())

    def test_audit_records_count_not_scores(self) -> None:
        self.patch(self.admin, {"language_tests": [IELTS]})
        event = AuditEvent.objects.get(action=ApplicantAuditAction.APPLICANT_LANGUAGE_TESTS_CHANGED)
        self.assertEqual(event.metadata, {"count": 1})
        self.assertNotIn("7.0", str(event.metadata) + str(event.changes) + event.summary)

    def assert_fields(self, response: Any, code: str, expected: set[str]) -> None:
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertEqual(set(body["error"]["details"]["fields"]), expected)

    def test_language_test_rules_report_paths(self) -> None:
        bad = {**IELTS, "overall_score": "9.5", "expiry_date": "2024-01-01"}
        response = self.patch(self.admin, {"language_tests": [IELTS, bad]})
        self.assert_fields(
            response,
            ErrorCode.LANGUAGE_TEST_INVALID,
            {"language_tests[1].overall_score", "language_tests[1].expiry_date"},
        )
        self.assertFalse(ApplicantLanguageTest.objects.exists())

    def test_education_rules_report_paths(self) -> None:
        cases = [
            ({**EDUCATION, "score_type": ""}, {"educations[0].score_type"}),
            ({**EDUCATION, "score": "4.5"}, {"educations[0].score"}),
            ({**EDUCATION, "year_calendar": ""}, {"educations[0].year_calendar"}),
            ({**EDUCATION, "start_year": 2081, "completion_year": 2080}, {"educations[0].completion_year"}),
            ({**EDUCATION, "completion_status": "ongoing"}, {"educations[0].completion_year"}),
            ({**EDUCATION, "completion_year": 1990}, {"educations[0].completion_year"}),
        ]
        for entry, expected in cases:
            with self.subTest(entry=entry):
                self.assert_fields(
                    self.patch(self.admin, {"educations": [entry]}), ErrorCode.EDUCATION_INVALID, expected
                )
        self.assertFalse(ApplicantEducation.objects.exists())

    def test_an_ongoing_qualification_without_completion_year(self) -> None:
        entry = {**EDUCATION, "completion_status": "ongoing", "completion_year": None, "score": None, "score_type": ""}
        self.assertEqual(self.patch(self.admin, {"educations": [entry]}).status_code, 200)

    def test_unknown_test_type_is_a_validation_error(self) -> None:
        response = self.patch(self.admin, {"language_tests": [{**IELTS, "test_type": "sat"}]})
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_create_with_collections(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        response = self.client.post(
            reverse("v1:applicants:applicant-list"),
            {
                "full_name": "Sita Thapa",
                "contact_numbers": [{"number": "9811111111", "label": "mobile", "is_primary": True}],
                "educations": [EDUCATION],
                "language_tests": [IELTS],
                "citizenship_no": "27-01-75-12345",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual((len(data["educations"]), len(data["language_tests"])), (1, 1))
        self.assertEqual(data["citizenship_no"], "27-01-75-12345")


class WodaFieldsApiTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        self.url = reverse("v1:applicants:applicant-detail", args=[self.applicant.id])

    def test_identity_numbers_and_grandparents_round_trip(self) -> None:
        response = self.client.patch(
            self.url,
            {
                "citizenship_no": " 27-01-75-12345 ",
                "citizenship_issue_district": "Kathmandu",
                "national_id_no": "123-456-789",
                "family_members": [
                    {"relationship": "grandfather", "full_name": "Hari Shrestha", "citizenship_no": "11-22"},
                    {"relationship": "grandmother", "full_name": "Gita Shrestha"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["citizenship_no"], "27-01-75-12345")
        self.assertEqual(data["citizenship_issue_district"], "Kathmandu")
        self.assertEqual(data["national_id_no"], "123-456-789")
        relations = {m["relationship"]: m for m in data["family_members"]}
        self.assertEqual(relations["grandfather"]["citizenship_no"], "11-22")
        self.assertIn("grandmother", relations)

    def test_identity_numbers_are_not_on_the_list_shape(self) -> None:
        row = self.client.get(reverse("v1:applicants:applicant-list")).json()["data"][0]
        self.assertNotIn("citizenship_no", row)

    def test_identity_numbers_never_reach_the_audit_log(self) -> None:
        self.client.patch(self.url, {"citizenship_no": "27-01-75-12345", "national_id_no": "999"}, format="json")
        event = AuditEvent.objects.get(action=ApplicantAuditAction.APPLICANT_UPDATED)
        self.assertEqual(event.changes["citizenship_no"], {"from": "<changed>", "to": "<changed>"})
        self.assertNotIn("12345", str(event.changes) + str(event.metadata) + event.summary)
