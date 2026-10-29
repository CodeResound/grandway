"""Tests for the 2026-10-29 documents changes (frontend ``updates.md`` §6, §7.1).

* ``student-certificate`` content is checked on write — the one template the
  backend looks inside — leniently: nothing required, unknown keys kept.
* ``photo_media_id`` must name a photograph uploaded for the same applicant.
* ``template_version`` is stored per document.
* The workspace list reports archived documents separately.
* Snapshot recovery puts back a printed body even if it fails today's rules.
"""

from __future__ import annotations

import shutil
import tempfile
from typing import Any

from django.test import TestCase, override_settings
from document_history import services as history_services
from rest_framework.test import APITestCase
from uploaded_files import services as file_services
from uploaded_files.constants import FileCategory
from uploaded_files.tests import factories as file_factories

from documents import services
from documents.constants import DocumentStatus, ErrorCode
from documents.exceptions import ContentInvalidError, DocumentNotEditableError
from documents.selectors import get_workspace_summaries
from documents.tests import factories as f
from documents.validators import validate_template_content

DOCS_URL = "/api/v1/documents/"


def full_certificate() -> dict[str, Any]:
    """Every §7.1 key, valid."""
    return {
        "firstname": "Ram",
        "middlename": "",
        "lastname": "Thapa",
        "date_of_birth": "2001-04-14",
        "date_of_admission": "2025-01-05",
        "date_of_completion": "2025-06-30",
        "issue": "2025-07-02",
        "gender": "male",
        "address": "Kathmandu-10, Bagmati",
        "course_name": "Japanese Language",
        "course_level": "N5",
        "course_books": ["Minna no Nihongo I", "Kanji Look and Learn"],
        "course_total_days": 120,
        "course_hours_per_day": "2.5",
        "marking": [
            {"month": "2025-01", "total_days": 20, "class_hr": 50, "present": 46.5, "absent": 3.5},
            {
                "month": "2025-02",
                "total_days": 20,
                "class_hr": "50",
                "present": "50",
                "absent": 0,
                "attendance_percentage": 100,
            },
        ],
        "grades": {"grammar": "A", "listening": "B", "conversation": "A", "reading": "", "composition": "C"},
        "photo_media_id": None,
        "branch_name": "Putalisadak",
        "branch_no": "02",
        "study_type": 1,
        "instructor_id": "anything-opaque",
        "director_id": "anything-opaque",
    }


class MediaRootMixin:
    """Uploads write real bytes; keep them in a throwaway MEDIA_ROOT."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._media_root = tempfile.mkdtemp(prefix="documents-test-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()  # type: ignore[misc]

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()  # type: ignore[misc]
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


class CertificateContentRuleTests(TestCase):
    """The validator itself, rule by rule."""

    def errors_for(self, content: dict[str, Any], applicant_id: Any = None) -> dict[str, str]:
        try:
            validate_template_content(template_key="student-certificate", content=content, applicant_id=applicant_id)
        except ContentInvalidError as exc:
            return exc.fields
        return {}

    def test_a_full_valid_certificate_passes(self) -> None:
        self.assertEqual(self.errors_for(full_certificate()), {})

    def test_nothing_is_required(self) -> None:
        self.assertEqual(self.errors_for({}), {})

    def test_legacy_camel_case_keys_pass_untouched(self) -> None:
        legacy = {"studyType": "whatever", "studentName": 42, "program": None, "nationality": "NP", "coursehour": "x"}
        self.assertEqual(self.errors_for(legacy), {})

    def test_null_skips_a_key(self) -> None:
        self.assertEqual(self.errors_for(dict.fromkeys(full_certificate())), {})

    def test_each_rule_reports_its_own_path(self) -> None:
        cases: list[tuple[dict[str, Any], str]] = [
            ({"firstname": "x" * 151}, "firstname"),
            ({"lastname": 7}, "lastname"),
            ({"address": "x" * 301}, "address"),
            ({"course_level": "x" * 51}, "course_level"),
            ({"branch_no": "x" * 51}, "branch_no"),
            ({"gender": "m"}, "gender"),
            ({"date_of_birth": "14/04/2001"}, "date_of_birth"),
            ({"issue": "2025-02-30"}, "issue"),
            ({"date_of_admission": "2025-06-01", "date_of_completion": "2025-05-01"}, "date_of_completion"),
            ({"course_books": "one book"}, "course_books"),
            ({"course_books": ["b"] * 21}, "course_books"),
            ({"course_books": ["ok", "x" * 151]}, "course_books[1]"),
            ({"course_total_days": 1001}, "course_total_days"),
            ({"course_total_days": True}, "course_total_days"),
            ({"course_total_days": "12"}, "course_total_days"),
            ({"course_hours_per_day": 25}, "course_hours_per_day"),
            ({"course_hours_per_day": "two"}, "course_hours_per_day"),
            ({"marking": {}}, "marking"),
            ({"marking": [{}] * 13}, "marking"),
            ({"marking": ["row"]}, "marking[0]"),
            ({"marking": [{"month": "2025-13"}]}, "marking[0].month"),
            ({"marking": [{"month": "2025-01"}, {"month": "2025-01"}]}, "marking[1].month"),
            ({"marking": [{"total_days": -1}]}, "marking[0].total_days"),
            ({"marking": [{"class_hr": -2}]}, "marking[0].class_hr"),
            ({"marking": [{"class_hr": 10, "present": 8, "absent": 3}]}, "marking[0].present"),
            ({"marking": [{"attendance_percentage": 101}]}, "marking[0].attendance_percentage"),
            ({"grades": ["A"]}, "grades"),
            ({"grades": {"grammar": "E"}}, "grades.grammar"),
            ({"study_type": 2}, "study_type"),
            ({"study_type": True}, "study_type"),
            ({"photo_media_id": "not-a-uuid"}, "photo_media_id"),
        ]
        for content, path in cases:
            with self.subTest(path=path, content=content):
                self.assertIn(path, self.errors_for(content))

    def test_float_hours_that_add_up_exactly_pass(self) -> None:
        marking = [{"class_hr": 0.3, "present": 0.1, "absent": 0.2}]
        self.assertEqual(self.errors_for({"marking": marking}), {})

    def test_every_failure_is_reported_at_once(self) -> None:
        errors = self.errors_for({"gender": "x", "study_type": 5, "grades": {"reading": "Z"}})
        self.assertEqual(set(errors), {"gender", "study_type", "grades.reading"})

    def test_other_templates_stay_opaque(self) -> None:
        validate_template_content(
            template_key="woda-address", content={"gender": "not checked", "marking": "anything"}, applicant_id=None
        )


class CertificateServiceTests(MediaRootMixin, TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.other = f.make_applicant(self.admin, name="Sita Kumari")

    def photo(self, applicant: Any, **overrides: Any) -> Any:
        return file_factories.upload_for_applicant(
            self.admin,
            applicant,
            category=overrides.pop("category", FileCategory.PHOTOGRAPH),
            upload=file_factories.jpeg_upload(),
            **overrides,
        )

    def photo_error(self, photo_id: str, applicant: Any = None, **extra: Any) -> str:
        with self.assertRaises(ContentInvalidError) as ctx:
            f.make_document(self.admin, applicant, content={"photo_media_id": photo_id}, **extra)
        return ctx.exception.fields["photo_media_id"]

    def test_create_rejects_invalid_content(self) -> None:
        with self.assertRaises(ContentInvalidError) as ctx:
            f.make_document(self.admin, self.applicant, content={"gender": "x"})
        self.assertIn("gender", ctx.exception.fields)

    def test_update_rejects_invalid_content(self) -> None:
        document = f.make_document(self.admin, self.applicant, content=full_certificate())
        with self.assertRaises(ContentInvalidError):
            services.update_document(actor=self.admin, document=document, fields={"content": {"study_type": 9}})

    def test_the_applicants_own_photograph_is_accepted(self) -> None:
        photo = self.photo(self.applicant)
        document = f.make_document(self.admin, self.applicant, content={"photo_media_id": str(photo.id)})
        self.assertEqual(document.content["photo_media_id"], str(photo.id))

    def test_another_applicants_photograph_is_rejected(self) -> None:
        self.assertIn("No file", self.photo_error(str(self.photo(self.other).id), self.applicant))

    def test_a_non_photograph_is_rejected(self) -> None:
        passport = self.photo(self.applicant, category=FileCategory.PASSPORT)
        self.assertIn("photograph", self.photo_error(str(passport.id), self.applicant))

    def test_an_archived_photograph_is_rejected(self) -> None:
        photo = self.photo(self.applicant)
        file_services.archive_file(actor=self.admin, uploaded_file=photo, reason="Blurry.")
        self.assertIn("archived", self.photo_error(str(photo.id), self.applicant))

    def test_an_unknown_file_id_is_rejected(self) -> None:
        self.assertIn("No file", self.photo_error("2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819", self.applicant))

    def test_a_standalone_document_cannot_carry_a_photo(self) -> None:
        error = self.photo_error(str(self.photo(self.applicant).id), None, standalone_purpose="Office sample.")
        self.assertIn("belongs to an applicant", error)

    def test_snapshot_recovery_bypasses_todays_rules(self) -> None:
        """Recovery puts back what was printed, even a photo archived since."""
        photo = self.photo(self.applicant)
        document = f.make_document(self.admin, self.applicant, content={"photo_media_id": str(photo.id)})
        snapshot = history_services.create_snapshot(actor=self.admin, document=document)
        services.update_document(actor=self.admin, document=document, fields={"content": {}})
        file_services.archive_file(actor=self.admin, uploaded_file=photo, reason="Retaken.")

        recovered = history_services.recover_snapshot(actor=self.admin, snapshot=snapshot)

        self.assertEqual(recovered.content["photo_media_id"], str(photo.id))


class TemplateVersionServiceTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)

    def test_defaults_to_layout_one(self) -> None:
        self.assertEqual(f.make_document(self.admin, self.applicant).template_version, "1")

    def test_set_on_create_and_changed_on_update(self) -> None:
        document = f.make_document(
            self.admin, self.applicant, family="woda", template_key="woda-address", template_version="2"
        )
        self.assertEqual(document.template_version, "2")
        services.update_document(actor=self.admin, document=document, fields={"template_version": "3"})
        document.refresh_from_db()
        self.assertEqual(document.template_version, "3")

    def test_frozen_once_archived(self) -> None:
        document = f.make_document(self.admin, self.applicant)
        services.archive_document(actor=self.admin, document=document, reason="Removed.")
        with self.assertRaises(DocumentNotEditableError):
            services.update_document(actor=self.admin, document=document, fields={"template_version": "2"})


class WorkspaceArchivedCountTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)

    def test_archived_documents_are_counted_separately(self) -> None:
        f.make_document(self.admin, self.applicant)
        removed = f.make_bank_statement(self.admin, self.applicant)
        services.archive_document(actor=self.admin, document=removed, reason="Removed.")

        row = list(get_workspace_summaries())[0]
        self.assertEqual((row["document_count"], row["archived_count"]), (1, 1))

    def test_an_applicant_with_only_archived_documents_keeps_a_row(self) -> None:
        document = f.make_document(self.admin, self.applicant)
        services.archive_document(actor=self.admin, document=document, reason="Removed.")

        rows = list(get_workspace_summaries())
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["document_count"], rows[0]["archived_count"]), (0, 1))


class DocumentEndpointChangeTests(APITestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token_for(self.admin)}")

    def create(self, **overrides: Any) -> Any:
        payload = {
            "applicant": str(self.applicant.id),
            "family": "student",
            "template_key": "student-certificate",
            "label": "Certificate",
            **overrides,
        }
        return self.client.post(DOCS_URL, payload, format="json")

    def test_invalid_certificate_returns_field_paths_in_the_error_envelope(self) -> None:
        response = self.create(content={"marking": [{"class_hr": 10, "present": 8, "absent": 3}], "gender": "x"})

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], ErrorCode.CONTENT_INVALID)
        self.assertEqual(set(body["error"]["details"]["fields"]), {"marking[0].present", "gender"})
        self.assertTrue(body["error"]["details"]["content"])
        self.assertIn("meta", body)

    def test_a_valid_certificate_is_stored_verbatim(self) -> None:
        content = full_certificate()
        response = self.create(content=content)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["content"], content)

    def test_template_version_round_trip(self) -> None:
        response = self.create(template_version="2")
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["template_version"], "2")

        url = f"{DOCS_URL}{data['id']}/"
        patched = self.client.patch(url, {"template_version": 3}, format="json")  # a JSON number is accepted
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["data"]["template_version"], "3")
        self.assertEqual(self.client.get(url).json()["data"]["template_version"], "3")

    def test_template_version_defaults_to_one(self) -> None:
        self.assertEqual(self.create().json()["data"]["template_version"], "1")

    def test_malformed_template_version_is_rejected(self) -> None:
        response = self.create(template_version="two point oh")
        self.assertEqual(response.status_code, 400)
        self.assertIn("template_version", response.json()["error"]["details"])

    def test_status_before_archive_cannot_be_patched(self) -> None:
        url = f"{DOCS_URL}{self.create().json()['data']['id']}/"
        response = self.client.patch(url, {"status_before_archive": "ready"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.STATUS_IMMUTABLE)

    def test_workspaces_report_archived_count(self) -> None:
        document_id = self.create().json()["data"]["id"]
        self.client.post(f"{DOCS_URL}{document_id}/archive/", {"reason": "Removed."}, format="json")

        rows = self.client.get(f"{DOCS_URL}workspaces/").json()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["document_count"], rows[0]["archived_count"]), (0, 1))

    def test_include_archived_rejects_a_non_boolean(self) -> None:
        response = self.client.get(DOCS_URL, {"include_archived": "maybe"})
        self.assertEqual(response.status_code, 400)

    def test_status_filter_still_selects_live_statuses(self) -> None:
        self.create()
        self.assertEqual(len(self.client.get(DOCS_URL, {"status": DocumentStatus.DRAFT}).json()["data"]), 1)
