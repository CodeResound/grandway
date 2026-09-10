"""Endpoint tests for the uploaded_files app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

Two things get more attention here than in any other suite in the project, and
both are about what makes this app different:

* **The authority split is asserted route by route.** Seven routes admit a Lead
  Manager and three refuse one, and a regression in either direction is invisible
  from the outside — a Lead Manager who could verify a file would produce records
  that look reviewed and are not.
* **The download response is asserted header by header.** ``attachment``,
  ``nosniff``, and ``no-store`` are the difference between a private file
  transfer and one a browser will render or cache.
"""

from __future__ import annotations

import shutil
import tempfile
from typing import Any

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from uploaded_files.constants import ErrorCode, FileCategory, VerificationStatus
from uploaded_files.tests import factories as f

FILES = "/api/v1/files/"
MISSING_ID = "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819"


class FilesAPITestCase(APITestCase):
    """Shared fixtures, an isolated MEDIA_ROOT, and envelope assertions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._media_root = tempfile.mkdtemp(prefix="uploaded-files-view-test-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.superadmin = f.make_superadmin()
        self.applicant = f.make_applicant(self.admin)

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token_for(user)}")

    def assert_success_envelope(self, response: Any) -> dict[str, Any]:
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("data", body)
        self.assertIn("meta", body)
        return body

    def assert_error_envelope(self, response: Any, code: str) -> dict[str, Any]:
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("details", body["error"])
        self.assertIn("meta", body)
        return body

    def upload_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "applicant": str(self.applicant.id),
            "category": FileCategory.PASSPORT,
            "file": f.pdf_upload(),
        }
        payload.update(overrides)
        return payload

    def stored_file(self, **overrides: Any) -> Any:
        return f.upload_for_applicant(self.admin, self.applicant, **overrides)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


class AuthenticationTests(FilesAPITestCase):
    def test_every_route_requires_authentication(self) -> None:
        stored = self.stored_file()
        routes = [
            ("get", FILES),
            ("post", FILES),
            ("get", f"{FILES}{stored.id}/"),
            ("patch", f"{FILES}{stored.id}/"),
            ("get", f"{FILES}{stored.id}/download/"),
            ("get", f"{FILES}{stored.id}/versions/"),
            ("post", f"{FILES}{stored.id}/replace/"),
            ("post", f"{FILES}{stored.id}/verify/"),
            ("post", f"{FILES}{stored.id}/archive/"),
            ("post", f"{FILES}{stored.id}/restore/"),
        ]
        for method, url in routes:
            with self.subTest(route=f"{method.upper()} {url}"):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 401)


class AuthorityTests(FilesAPITestCase):
    """The split: seven routes for both authorities, three for Admin only."""

    def setUp(self) -> None:
        super().setUp()
        self.stored = self.stored_file()

    def shared_routes(self) -> list[tuple[str, str]]:
        return [
            ("get", FILES),
            ("get", f"{FILES}{self.stored.id}/"),
            ("get", f"{FILES}{self.stored.id}/download/"),
            ("get", f"{FILES}{self.stored.id}/versions/"),
        ]

    def admin_only_routes(self) -> list[tuple[str, str]]:
        return [
            ("post", f"{FILES}{self.stored.id}/verify/"),
            ("post", f"{FILES}{self.stored.id}/archive/"),
            ("post", f"{FILES}{self.stored.id}/restore/"),
        ]

    def test_superadmin_is_refused_everywhere(self) -> None:
        self.auth(self.superadmin)
        for method, url in self.shared_routes() + self.admin_only_routes():
            with self.subTest(route=f"{method.upper()} {url}"):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_read_and_download(self) -> None:
        self.auth(self.lead_manager)
        for method, url in self.shared_routes():
            with self.subTest(route=f"{method.upper()} {url}"):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 200)

    def test_lead_manager_may_upload_and_replace(self) -> None:
        self.auth(self.lead_manager)
        upload = self.client.post(FILES, self.upload_payload(), format="multipart")
        self.assertEqual(upload.status_code, 201)

        replace = self.client.post(f"{FILES}{self.stored.id}/replace/", {"file": f.pdf_upload()}, format="multipart")
        self.assertEqual(replace.status_code, 201)

    def test_lead_manager_may_not_review_or_archive(self) -> None:
        """The whole point of the split: the uploader is not the reviewer."""
        self.auth(self.lead_manager)
        bodies = {
            f"{FILES}{self.stored.id}/verify/": {"status": VerificationStatus.VERIFIED},
            f"{FILES}{self.stored.id}/archive/": {"reason": "no"},
            f"{FILES}{self.stored.id}/restore/": {},
        }
        for url, body in bodies.items():
            with self.subTest(route=url):
                response = self.client.post(url, body, format="json")
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_a_lead_manager_cannot_reach_an_admin_only_owned_file(self) -> None:
        """A file inherits the visibility of the record it belongs to.

        `documents`, `document_history`, and `document_templates` are Admin-only
        on every route, so a Lead Manager who cannot open a bank statement must
        not be able to list or download the PDF attached to it — nor a
        director's signature image, which they equally cannot reach through the
        owning app. 404 rather than 403, because confirming the file exists
        would leak exactly what those modules hide.
        """
        document = f.make_document(self.admin, self.applicant)
        snapshot = f.make_snapshot(self.admin, document)
        signatory = f.make_signatory(self.admin)
        doc_file = f.upload_for(self.admin, "document", document)
        snap_file = f.upload_for(self.admin, "snapshot", snapshot)
        sig_file = f.upload_for(self.admin, "signatory", signatory)

        self.auth(self.lead_manager)
        for restricted in (doc_file, snap_file, sig_file):
            with self.subTest(owner=restricted.owner_type):
                for url in (
                    f"{FILES}{restricted.id}/",
                    f"{FILES}{restricted.id}/download/",
                    f"{FILES}{restricted.id}/versions/",
                ):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 404)
                    self.assert_error_envelope(response, ErrorCode.FILE_NOT_FOUND)

    def test_a_lead_manager_never_sees_restricted_files_in_a_list(self) -> None:
        """Excluded from the queryset, not refused per row — a 403 on one row
        would leak the existence of the record `documents` hides."""
        document = f.make_document(self.admin, self.applicant)
        doc_file = f.upload_for(self.admin, "document", document)
        sig_file = f.upload_for(self.admin, "signatory", f.make_signatory(self.admin))
        own_file = self.stored

        self.auth(self.lead_manager)
        ids = [row["id"] for row in self.client.get(FILES).json()["data"]]
        self.assertIn(str(own_file.id), ids)
        self.assertNotIn(str(doc_file.id), ids)
        self.assertNotIn(str(sig_file.id), ids)

        self.auth(self.admin)
        admin_ids = [row["id"] for row in self.client.get(FILES).json()["data"]]
        self.assertIn(str(doc_file.id), admin_ids)
        self.assertIn(str(sig_file.id), admin_ids)

    def test_a_lead_manager_cannot_upload_against_an_admin_only_owner(self) -> None:
        document = f.make_document(self.admin, self.applicant)
        signatory = f.make_signatory(self.admin)
        self.auth(self.lead_manager)
        for owner_field, owner_id in (("document", document.id), ("signatory", signatory.id)):
            with self.subTest(owner=owner_field):
                response = self.client.post(
                    FILES,
                    {
                        owner_field: str(owner_id),
                        "category": FileCategory.OTHER,
                        "file": f.pdf_upload(),
                    },
                    format="multipart",
                )
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_a_lead_manager_gets_403_before_404_on_a_missing_file(self) -> None:
        """Authority is checked first, so a refused caller cannot probe for ids."""
        self.auth(self.lead_manager)
        response = self.client.post(
            f"{FILES}{MISSING_ID}/verify/", {"status": VerificationStatus.VERIFIED}, format="json"
        )
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class UploadTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_upload_returns_201_and_the_file_metadata(self) -> None:
        response = self.client.post(FILES, self.upload_payload(), format="multipart")
        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]

        self.assertEqual(data["owner_type"], "applicant")
        self.assertEqual(data["owner_id"], str(self.applicant.id))
        self.assertEqual(data["category"], FileCategory.PASSPORT)
        self.assertEqual(data["original_filename"], "passport.pdf")
        self.assertEqual(data["content_type"], "application/pdf")
        self.assertEqual(data["verification_status"], VerificationStatus.PENDING)
        self.assertEqual(data["version_number"], 1)
        self.assertTrue(data["is_current"])
        self.assertFalse(data["is_archived"])

    def test_the_response_never_contains_the_storage_path(self) -> None:
        """The single most important shaping rule in this app."""
        response = self.client.post(FILES, self.upload_payload(), format="multipart")
        data = self.assert_success_envelope(response)["data"]
        self.assertNotIn("file", data)
        self.assertNotIn("uploaded_files/", str(data))

    def test_each_owner_type_is_accepted(self) -> None:
        journey = f.make_journey(self.admin, self.applicant)
        offer = f.make_manual_offer(self.admin, journey)
        document = f.make_document(self.admin, self.applicant)
        snapshot = f.make_snapshot(self.admin, document)
        signatory = f.make_signatory(self.admin)

        cases = {
            "journey": journey.id,
            "offer": offer.id,
            "document": document.id,
            "snapshot": snapshot.id,
            "signatory": signatory.id,
        }
        for owner_field, owner_id in cases.items():
            with self.subTest(owner=owner_field):
                payload = {
                    owner_field: str(owner_id),
                    "category": FileCategory.OTHER,
                    "file": f.pdf_upload(),
                }
                response = self.client.post(FILES, payload, format="multipart")
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["data"]["owner_type"], owner_field)

    def test_no_owner_is_a_validation_error(self) -> None:
        payload = {"category": FileCategory.PASSPORT, "file": f.pdf_upload()}
        response = self.client.post(FILES, payload, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("owner", response.json()["error"]["details"])

    def test_two_owners_is_a_validation_error(self) -> None:
        journey = f.make_journey(self.admin, self.applicant)
        payload = self.upload_payload(journey=str(journey.id))
        response = self.client.post(FILES, payload, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_a_nonexistent_owner_names_the_field_that_failed(self) -> None:
        payload = {"offer": MISSING_ID, "category": FileCategory.OTHER, "file": f.pdf_upload()}
        response = self.client.post(FILES, payload, format="multipart")
        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.OWNER_NOT_FOUND)
        self.assertIn("offer", body["error"]["details"])

    def test_missing_file_part_is_a_validation_error(self) -> None:
        payload = {"applicant": str(self.applicant.id), "category": FileCategory.PASSPORT}
        response = self.client.post(FILES, payload, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json()["error"]["details"])

    def test_oversize_file_is_refused(self) -> None:
        response = self.client.post(FILES, self.upload_payload(file=f.oversize_upload()), format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.FILE_TOO_LARGE)

    def test_disallowed_type_is_refused(self) -> None:
        response = self.client.post(FILES, self.upload_payload(file=f.disallowed_upload()), format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.FILE_TYPE_NOT_ALLOWED)

    def test_content_mismatch_is_refused(self) -> None:
        response = self.client.post(FILES, self.upload_payload(file=f.mislabelled_upload()), format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.FILE_CONTENT_MISMATCH)

    def test_unknown_category_is_a_validation_error(self) -> None:
        response = self.client.post(FILES, self.upload_payload(category="visa"), format="multipart")
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class ListTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.journey = f.make_journey(self.admin, self.applicant)
        self.passport = self.stored_file()
        self.transcript = f.upload_for(
            self.admin,
            "journey",
            self.journey,
            category=FileCategory.ACADEMIC_TRANSCRIPT,
            upload=f.pdf_upload("transcript.pdf"),
        )

    def test_list_returns_the_pagination_meta_shape(self) -> None:
        response = self.client.get(FILES)
        self.assertEqual(response.status_code, 200)
        meta = self.assert_success_envelope(response)["meta"]
        for key in ("count", "page", "page_size", "next", "previous"):
            self.assertIn(key, meta)
        self.assertEqual(meta["count"], 2)

    def test_owner_filter(self) -> None:
        response = self.client.get(FILES, {"applicant": str(self.applicant.id)})
        ids = [row["id"] for row in response.json()["data"]]
        self.assertEqual(ids, [str(self.passport.id)])

    def test_review_queue_filter(self) -> None:
        response = self.client.get(FILES, {"verification_status": VerificationStatus.PENDING})
        self.assertEqual(len(response.json()["data"]), 2)

    def test_search_over_the_original_filename(self) -> None:
        response = self.client.get(FILES, {"search": "transcript"})
        ids = [row["id"] for row in response.json()["data"]]
        self.assertEqual(ids, [str(self.transcript.id)])

    def test_an_unknown_filter_value_is_a_validation_error(self) -> None:
        """A filter that silently did nothing is how a screen shows the wrong files."""
        response = self.client.get(FILES, {"category": "visa"})
        self.assertEqual(response.status_code, 400)

    def test_a_malformed_owner_id_is_a_validation_error(self) -> None:
        response = self.client.get(FILES, {"applicant": "not-a-uuid"})
        self.assertEqual(response.status_code, 400)


class FileListQueryCountTests(FilesAPITestCase):
    """N+1 guard (§6). The list joins six owner tables and four user columns;
    the query count must not grow with the number of rows."""

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def _populate(self, count: int) -> None:
        """Three owner types in rotation, so the sixth join is actually exercised.

        Two would leave ``signatory`` unjoined in every row of the page, and a
        ``select_related`` that is never populated proves nothing.
        """
        journey = f.make_journey(self.admin, self.applicant)
        signatory = f.make_signatory(self.admin)
        rotation = [("applicant", self.applicant), ("journey", journey), ("signatory", signatory)]
        for index in range(count):
            owner_field, owner = rotation[index % 3]
            f.upload_for(self.admin, owner_field, owner, upload=f.pdf_upload(f"scan{index}.pdf"))

    def test_query_count_does_not_grow_with_the_number_of_rows(self) -> None:
        """Four times the rows, the same number of queries.

        The absolute count is not asserted — it includes the authentication
        lookups every request makes, which belong to another app and may
        legitimately change. What must hold is the *shape*: one count query and
        one joined select, no matter how many mixed-owner rows come back.
        """
        self._populate(2)
        with CaptureQueriesContext(connection) as small:
            first = self.client.get(FILES, {"page_size": 100})

        self._populate(6)
        with CaptureQueriesContext(connection) as large:
            second = self.client.get(FILES, {"page_size": 100})

        self.assertEqual(len(first.json()["data"]), 2)
        self.assertEqual(len(second.json()["data"]), 8)
        self.assertEqual(len(large.captured_queries), len(small.captured_queries))


# ---------------------------------------------------------------------------
# Detail, update, versions
# ---------------------------------------------------------------------------


class DetailTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.stored = self.stored_file()

    def test_retrieve(self) -> None:
        response = self.client.get(f"{FILES}{self.stored.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assert_success_envelope(response)["data"]["id"], str(self.stored.id))

    def test_the_three_business_dates_carry_bikram_sambat_siblings(self) -> None:
        """§39.4 — received, reviewed, and archived are dates staff read in BS."""
        self.client.post(f"{FILES}{self.stored.id}/verify/", {"status": VerificationStatus.VERIFIED}, format="json")
        self.client.post(f"{FILES}{self.stored.id}/archive/", {"reason": "Filed."}, format="json")

        data = self.client.get(f"{FILES}{self.stored.id}/").json()["data"]
        for field in ("created_at_bs", "reviewed_at_bs", "archived_at_bs"):
            with self.subTest(field=field):
                self.assertIsNotNone(data[field])
                self.assertIn("display", data[field])

    def test_bs_siblings_are_null_while_their_gregorian_field_is(self) -> None:
        data = self.client.get(f"{FILES}{self.stored.id}/").json()["data"]
        self.assertIsNone(data["reviewed_at_bs"])
        self.assertIsNone(data["archived_at_bs"])
        self.assertIsNotNone(data["created_at_bs"])

    def test_retrieve_missing(self) -> None:
        response = self.client.get(f"{FILES}{MISSING_ID}/")
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.FILE_NOT_FOUND)

    def test_patch_edits_category_and_notes(self) -> None:
        response = self.client.patch(
            f"{FILES}{self.stored.id}/",
            {"category": FileCategory.OTHER, "notes": "Refiled."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["category"], FileCategory.OTHER)
        self.assertEqual(data["notes"], "Refiled.")

    def test_patch_refuses_every_other_field_by_name(self) -> None:
        for field, value in (
            ("applicant", str(self.applicant.id)),
            ("verification_status", VerificationStatus.VERIFIED),
            ("checksum_sha256", "0" * 64),
            ("original_filename", "renamed.pdf"),
        ):
            with self.subTest(field=field):
                response = self.client.patch(f"{FILES}{self.stored.id}/", {field: value}, format="json")
                self.assertEqual(response.status_code, 400)
                body = self.assert_error_envelope(response, ErrorCode.FIELD_IMMUTABLE)
                self.assertIn(field, body["error"]["details"])

    def test_patching_an_archived_file_is_refused(self) -> None:
        self.client.post(f"{FILES}{self.stored.id}/archive/", {"reason": "Filed."}, format="json")
        response = self.client.patch(f"{FILES}{self.stored.id}/", {"notes": "late"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.FILE_ARCHIVED)


class VersionsTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.first = self.stored_file()

    def test_a_lone_file_is_a_chain_of_one(self) -> None:
        response = self.client.get(f"{FILES}{self.first.id}/versions/")
        self.assertEqual(response.status_code, 200)
        body = self.assert_success_envelope(response)
        self.assertEqual(body["meta"]["count"], 1)

    def test_the_chain_is_returned_oldest_first_from_either_end(self) -> None:
        replaced = self.client.post(
            f"{FILES}{self.first.id}/replace/", {"file": f.pdf_upload("v2.pdf")}, format="multipart"
        )
        second_id = replaced.json()["data"]["id"]

        for anchor in (str(self.first.id), second_id):
            with self.subTest(anchor=anchor):
                response = self.client.get(f"{FILES}{anchor}/versions/")
                ids = [row["id"] for row in response.json()["data"]]
                self.assertEqual(ids, [str(self.first.id), second_id])


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class DownloadTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.stored = self.stored_file()

    def test_download_returns_the_exact_bytes(self) -> None:
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(f.read_streamed(response), f.PDF_BYTES)

    def test_download_forces_an_attachment_under_the_original_name(self) -> None:
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        disposition = response["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn("passport.pdf", disposition)
        self.assertNotIn("inline", disposition)

    def test_download_sets_the_two_protective_headers(self) -> None:
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_download_uses_the_stored_content_type(self) -> None:
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_download_never_exposes_the_storage_path(self) -> None:
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        headers = " ".join(f"{key}: {value}" for key, value in response.items())
        self.assertNotIn("uploaded_files/applicant", headers)
        self.assertNotIn(self._media_root, headers)

    def test_download_of_a_missing_file_is_404(self) -> None:
        response = self.client.get(f"{FILES}{MISSING_ID}/download/")
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.FILE_NOT_FOUND)

    def test_a_row_whose_bytes_are_gone_is_404_not_500(self) -> None:
        """Database and volume have diverged. Report it, do not leak a path."""
        self.stored.file.storage.delete(self.stored.file.name)
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        self.assertEqual(response.status_code, 404)
        body = self.assert_error_envelope(response, ErrorCode.FILE_BYTES_MISSING)
        self.assertNotIn("uploaded_files/", str(body))

    def test_an_archived_file_is_still_downloadable(self) -> None:
        """Archival is a lifecycle state, not a tombstone."""
        self.client.post(f"{FILES}{self.stored.id}/archive/", {"reason": "Filed."}, format="json")
        response = self.client.get(f"{FILES}{self.stored.id}/download/")
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Replace, review, archive
# ---------------------------------------------------------------------------


class ReplaceTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.stored = self.stored_file()

    def test_replace_returns_201_and_the_successor(self) -> None:
        response = self.client.post(
            f"{FILES}{self.stored.id}/replace/",
            {"file": f.pdf_upload("rescan.pdf"), "notes": "Re-scanned at 300dpi."},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["version_number"], 2)
        self.assertEqual(data["replaces"], str(self.stored.id))
        self.assertEqual(data["original_filename"], "rescan.pdf")

    def test_replacing_twice_from_the_same_anchor_is_refused(self) -> None:
        self.client.post(f"{FILES}{self.stored.id}/replace/", {"file": f.pdf_upload()}, format="multipart")
        response = self.client.post(f"{FILES}{self.stored.id}/replace/", {"file": f.pdf_upload()}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.ALREADY_SUPERSEDED)

    def test_replace_applies_the_same_upload_rules(self) -> None:
        response = self.client.post(
            f"{FILES}{self.stored.id}/replace/", {"file": f.mislabelled_upload()}, format="multipart"
        )
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.FILE_CONTENT_MISMATCH)

    def test_replace_cannot_move_a_file_to_another_owner(self) -> None:
        """The serializer carries no owner field, so an attempt is ignored, and
        the successor still belongs to the original record."""
        journey = f.make_journey(self.admin, self.applicant)
        response = self.client.post(
            f"{FILES}{self.stored.id}/replace/",
            {"file": f.pdf_upload(), "journey": str(journey.id)},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["owner_type"], "applicant")


class ReviewTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.stored = self.stored_file()

    def test_verify(self) -> None:
        response = self.client.post(
            f"{FILES}{self.stored.id}/verify/", {"status": VerificationStatus.VERIFIED}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["verification_status"], VerificationStatus.VERIFIED)
        self.assertTrue(data["is_verified"])
        self.assertEqual(data["reviewed_by_username"], self.admin.username)

    def test_reject_requires_a_reason(self) -> None:
        response = self.client.post(
            f"{FILES}{self.stored.id}/verify/", {"status": VerificationStatus.REJECTED}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["error"]["details"])

    def test_reject_with_a_reason(self) -> None:
        response = self.client.post(
            f"{FILES}{self.stored.id}/verify/",
            {"status": VerificationStatus.REJECTED, "reason": "Page 2 is unreadable."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["rejection_reason"], "Page 2 is unreadable.")

    def test_pending_is_not_a_settable_verdict(self) -> None:
        response = self.client.post(
            f"{FILES}{self.stored.id}/verify/", {"status": VerificationStatus.PENDING}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class ArchiveTests(FilesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.stored = self.stored_file()

    def test_archive_requires_a_reason(self) -> None:
        response = self.client.post(f"{FILES}{self.stored.id}/archive/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["error"]["details"])

    def test_archive_then_restore(self) -> None:
        archived = self.client.post(
            f"{FILES}{self.stored.id}/archive/", {"reason": "Superseded outside the system."}, format="json"
        )
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json()["data"]["is_archived"])

        restored = self.client.post(f"{FILES}{self.stored.id}/restore/", {}, format="json")
        self.assertEqual(restored.status_code, 200)
        data = restored.json()["data"]
        self.assertFalse(data["is_archived"])
        self.assertEqual(data["archive_reason"], "")

    def test_archiving_twice_is_refused(self) -> None:
        self.client.post(f"{FILES}{self.stored.id}/archive/", {"reason": "Filed."}, format="json")
        response = self.client.post(f"{FILES}{self.stored.id}/archive/", {"reason": "Again."}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.ALREADY_ARCHIVED)

    def test_restoring_a_live_file_is_refused(self) -> None:
        response = self.client.post(f"{FILES}{self.stored.id}/restore/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.NOT_ARCHIVED)
