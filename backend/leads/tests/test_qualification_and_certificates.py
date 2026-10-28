"""Structured qualification and language certificates on leads (2026-10-29, updates.md §1).

What these guard: the score/type and year/calendar pairings (judged against the
merged record on a partial PATCH), certificate replacement and its cap, the
three new list filters, and conversion turning both into real applicant records.
"""

from __future__ import annotations

from typing import Any

from applicant_journeys.models import ApplicantJourney
from applicants.models import ApplicantEducation, ApplicantLanguageTest
from django.urls import reverse
from rest_framework.test import APITestCase

from leads import services
from leads.constants import ErrorCode
from leads.models import LeadLanguageCertificate
from leads.tests.factories import make_admin, make_lead, make_lead_manager, make_source, token_for

IELTS = {"test_type": "ielts", "overall_score": "7.0", "test_date": "2025-03-01", "expiry_date": "2027-03-01"}
INTEREST = {
    "highest_qualification": "BBS",
    "highest_qualification_level": "bachelor",
    "academic_score": "3.45",
    "academic_score_type": "gpa",
    "pass_year": 2080,
    "pass_year_calendar": "bs",
    "language_test_status": "taken",
}


class QualificationApiTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.source = make_source()
        self.lead = make_lead(self.owner, self.source)
        self.url = reverse("v1:leads:lead-detail", args=[self.lead.id])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.owner)}")

    def patch(self, payload: dict[str, Any]) -> Any:
        return self.client.patch(self.url, payload, format="json")

    def assert_fields(self, response: Any, code: str, expected: set[str]) -> None:
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertEqual(set(body["error"]["details"]["fields"]), expected)

    def test_study_interest_fields_round_trip(self) -> None:
        response = self.patch({"study_interest": INTEREST})
        self.assertEqual(response.status_code, 200, response.content)
        interest = response.json()["data"]["study_interest"]
        self.assertEqual(interest["highest_qualification"], "BBS")
        self.assertEqual(interest["highest_qualification_level"], "bachelor")
        self.assertEqual((interest["academic_score"], interest["pass_year"]), ("3.45", 2080))

    def test_pairings_and_ranges(self) -> None:
        cases = [
            ({"academic_score": "3.0"}, {"study_interest.academic_score_type"}),
            ({"academic_score_type": "percentage"}, {"study_interest.academic_score"}),
            ({"academic_score": "4.5", "academic_score_type": "gpa"}, {"study_interest.academic_score"}),
            ({"academic_score": "101", "academic_score_type": "percentage"}, {"study_interest.academic_score"}),
            ({"pass_year": 2080}, {"study_interest.pass_year_calendar"}),
            ({"pass_year": 1940, "pass_year_calendar": "ad"}, {"study_interest.pass_year"}),
        ]
        for interest, expected in cases:
            with self.subTest(interest=interest):
                self.assert_fields(
                    self.patch({"study_interest": interest}), ErrorCode.STUDY_INTEREST_INVALID, expected
                )

    def test_partial_patch_is_judged_against_the_stored_record(self) -> None:
        self.patch({"study_interest": INTEREST})
        self.assertEqual(self.patch({"study_interest": {"academic_score": "3.9"}}).status_code, 200)
        # Switching the type without a fitting score is still checked against the range.
        response = self.patch({"study_interest": {"academic_score_type": "gpa", "academic_score": "75"}})
        self.assert_fields(response, ErrorCode.STUDY_INTEREST_INVALID, {"study_interest.academic_score"})

    def test_existing_free_text_qualification_still_accepted_alone(self) -> None:
        response = self.patch({"study_interest": {"highest_qualification": "Science, +2"}})
        self.assertEqual(response.status_code, 200)

    def test_certificates_replace_omit_clear(self) -> None:
        pte = {"test_type": "pte", "overall_score": "65"}
        response = self.patch({"language_certificates": [IELTS, pte]})
        self.assertEqual(response.status_code, 200, response.content)
        certs = response.json()["data"]["language_certificates"]
        self.assertEqual({c["test_type"] for c in certs}, {"ielts", "pte"})
        self.assertIsNotNone(next(c for c in certs if c["test_type"] == "ielts")["test_date_bs"])

        self.patch({"full_name": "Renamed"})  # omitted: untouched
        self.assertEqual(LeadLanguageCertificate.objects.filter(lead=self.lead).count(), 2)
        self.patch({"language_certificates": [pte]})
        self.assertEqual(LeadLanguageCertificate.objects.filter(lead=self.lead).count(), 1)
        self.patch({"language_certificates": []})
        self.assertFalse(LeadLanguageCertificate.objects.filter(lead=self.lead).exists())

    def test_certificate_rules(self) -> None:
        response = self.patch({"language_certificates": [{**IELTS, "overall_score": "6.3"}]})
        self.assert_fields(response, ErrorCode.CERTIFICATE_INVALID, {"language_certificates[0].overall_score"})
        response = self.patch({"language_certificates": [IELTS] * 11})
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CERTIFICATE_LIMIT)
        self.assertFalse(LeadLanguageCertificate.objects.exists())

    def test_create_with_certificates(self) -> None:
        response = self.client.post(
            reverse("v1:leads:lead-list"),
            {
                "full_name": "Sita Thapa",
                "source": str(self.source.id),
                "contact_numbers": [{"number": "9811111111", "label": "mobile", "is_primary": True}],
                "study_interest": INTEREST,
                "language_certificates": [IELTS],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(len(response.json()["data"]["language_certificates"]), 1)


class QualificationFilterTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        source = make_source()
        self.bachelor = make_lead(self.admin, source, name="Bachelor Lead")
        self.see = make_lead(self.admin, source, name="See Lead")
        services.update_lead(
            actor=self.admin,
            lead=self.bachelor,
            fields={},
            study_interest={"highest_qualification_level": "bachelor", "language_test_status": "taken"},
            language_certificates=[
                {"test_type": "ielts", "overall_score": 7},
                {"test_type": "ielts", "overall_score": 6.5},
            ],
        )
        services.update_lead(
            actor=self.admin,
            lead=self.see,
            fields={},
            study_interest={"highest_qualification_level": "see", "language_test_status": "preparing"},
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def names(self, **params: str) -> list[str]:
        rows = self.client.get(reverse("v1:leads:lead-list"), params).json()["data"]
        return sorted(row["full_name"] for row in rows)

    def test_filters(self) -> None:
        self.assertEqual(self.names(highest_qualification_level="bachelor"), ["Bachelor Lead"])
        self.assertEqual(self.names(language_test_status="preparing"), ["See Lead"])
        # Two IELTS certificates, one row.
        self.assertEqual(self.names(language_test_type="ielts"), ["Bachelor Lead"])
        self.assertEqual(self.names(language_test_type="pte"), [])
        self.assertEqual(self.names(language_test_type="ielts", search="Bachelor"), ["Bachelor Lead"])

    def test_bad_filter_value_is_refused(self) -> None:
        response = self.client.get(reverse("v1:leads:lead-list"), {"language_test_type": "sat"})
        self.assertEqual(response.status_code, 400)


class ConversionCopiesQualificationTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.lead = make_lead(self.admin, make_source())

    def convert(self) -> Any:
        services.convert_lead(actor=self.admin, lead=self.lead)
        self.lead.refresh_from_db()
        return self.lead.converted_applicant

    def test_education_and_tests_become_applicant_records(self) -> None:
        services.update_lead(
            actor=self.admin,
            lead=self.lead,
            fields={},
            study_interest={k: v for k, v in INTEREST.items()},
            language_certificates=[
                {"test_type": "ielts", "overall_score": "7.0", "certificate_number": "25NP1"},
                {"test_type": "duolingo", "overall_score": "120"},
            ],
        )
        applicant = self.convert()

        education = ApplicantEducation.objects.get(applicant=applicant)
        self.assertEqual(
            (education.level, education.qualification, education.grading_system, education.completion_status),
            ("bachelor", "BBS", "GPA (4.0)", "completed"),
        )
        self.assertEqual((education.completion_year, education.year_calendar), (2080, "bs"))
        self.assertEqual(education.source_lead_id, self.lead.id)

        tests = ApplicantLanguageTest.objects.filter(applicant=applicant)
        self.assertEqual({t.test_type for t in tests}, {"ielts", "duolingo"})
        self.assertTrue(all(t.source_lead_id == self.lead.id for t in tests))

        notes = ApplicantJourney.objects.get(pk=self.lead.converted_journey_id).notes
        self.assertNotIn("Highest qualification", notes)
        self.assertIn("Language test status: taken", notes)

    def test_level_less_lead_keeps_text_in_journey_notes(self) -> None:
        services.update_lead(
            actor=self.admin, lead=self.lead, fields={}, study_interest={"highest_qualification": "BSc CSIT"}
        )
        applicant = self.convert()
        self.assertFalse(ApplicantEducation.objects.filter(applicant=applicant).exists())
        self.assertIn("BSc CSIT", ApplicantJourney.objects.get(pk=self.lead.converted_journey_id).notes)

    def test_nothing_to_copy(self) -> None:
        applicant = self.convert()
        self.assertFalse(ApplicantEducation.objects.filter(applicant=applicant).exists())
        self.assertFalse(ApplicantLanguageTest.objects.filter(applicant=applicant).exists())
