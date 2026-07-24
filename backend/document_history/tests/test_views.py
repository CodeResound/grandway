"""Endpoint tests for the document_history app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

The authority assertions are checked against a Lead Manager **and** a
Superadmin on every route, for the same reason ``documents`` does it: this is
the second app in the project where a Lead Manager is denied outright, reads
included, and a regression that quietly opened a read would expose frozen bank
statements.
"""

from __future__ import annotations

from typing import Any

from documents import services as document_services
from rest_framework.test import APITestCase

from document_history.constants import ErrorCode, PrintEventType
from document_history.tests import factories as f

BASE = "/api/v1/document-history/"


class HistoryAPITestCase(APITestCase):
    """Shared fixtures and envelope assertions."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.superadmin = f.make_superadmin()
        self.applicant = f.make_applicant(self.admin)
        self.document = f.make_bank_statement(self.admin, self.applicant)

        self.snapshots_url = f"{BASE}documents/{self.document.id}/snapshots/"
        self.timeline_url = f"{BASE}documents/{self.document.id}/timeline/"

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token_for(user)}")

    def snapshot_url(self, snapshot: Any, suffix: str = "") -> str:
        return f"{BASE}snapshots/{snapshot.id}/{suffix}"

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

    def capture_payload(self, **overrides: Any) -> dict[str, Any]:
        return {"render_context": f.render_context(), "capture_note": "Printed for the visa file.", **overrides}


class AccessTests(HistoryAPITestCase):
    """Admin only, reads included — on every one of the six routes."""

    def setUp(self) -> None:
        super().setUp()
        self.snapshot = f.make_snapshot(self.admin, self.document)

    def routes(self) -> list[tuple[str, str]]:
        return [
            ("get", self.snapshots_url),
            ("post", self.snapshots_url),
            ("get", self.timeline_url),
            ("get", self.snapshot_url(self.snapshot)),
            ("post", self.snapshot_url(self.snapshot, "reprint/")),
            ("post", self.snapshot_url(self.snapshot, "recover/")),
        ]

    def test_unauthenticated_is_rejected_everywhere(self) -> None:
        for method, url in self.routes():
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 401)

    def test_lead_manager_is_forbidden_everywhere_including_reads(self) -> None:
        self.auth(self.lead_manager)
        for method, url in self.routes():
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_superadmin_is_forbidden_everywhere(self) -> None:
        self.auth(self.superadmin)
        for method, url in self.routes():
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 403)

    def test_no_route_accepts_put_patch_or_delete(self) -> None:
        """Nothing here is ever edited or deleted, at the HTTP layer either."""
        self.auth(self.admin)
        for method in ("put", "patch", "delete"):
            for url in (self.snapshot_url(self.snapshot), self.snapshots_url, self.timeline_url):
                with self.subTest(method=method, url=url):
                    response = getattr(self.client, method)(url, {}, format="json")
                    self.assertEqual(response.status_code, 405)


class CaptureTests(HistoryAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_capture_returns_201_and_the_full_snapshot(self) -> None:
        response = self.client.post(self.snapshots_url, self.capture_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["version_number"], 1)
        self.assertEqual(data["content"], self.document.content)
        self.assertEqual(data["label"], self.document.label)
        self.assertIn("render_context", data)
        self.assertIsNotNone(data["created_at_bs"])

    def test_capture_works_with_an_empty_body(self) -> None:
        response = self.client.post(self.snapshots_url, {}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["render_context"], {})

    def test_a_client_supplied_content_is_ignored(self) -> None:
        """The body is copied off the document; a request cannot influence it."""
        response = self.client.post(
            self.snapshots_url,
            self.capture_payload(content={"statement_account_holder": "Injected"}),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["content"], self.document.content)

    def test_a_non_object_render_context_is_a_400(self) -> None:
        response = self.client.post(self.snapshots_url, {"render_context": ["a", "b"]}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.RENDER_CONTEXT_INVALID)

    def test_an_unknown_document_is_a_404(self) -> None:
        url = f"{BASE}documents/2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819/snapshots/"

        response = self.client.post(url, self.capture_payload(), format="json")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_FOUND)

    def test_an_overlong_capture_note_is_a_validation_error(self) -> None:
        response = self.client.post(self.snapshots_url, {"capture_note": "x" * 2001}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("capture_note", response.json()["error"]["details"])


class SnapshotListTests(HistoryAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        for _ in range(3):
            f.make_snapshot(self.admin, self.document)

    def test_list_returns_the_chain_newest_first(self) -> None:
        response = self.client.get(self.snapshots_url)

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual([row["version_number"] for row in data], [3, 2, 1])

    def test_list_omits_the_frozen_body_and_render_context(self) -> None:
        row = self.client.get(self.snapshots_url).json()["data"][0]

        self.assertNotIn("content", row)
        self.assertNotIn("render_context", row)

    def test_pagination_meta_matches_the_project_schema(self) -> None:
        body = self.client.get(self.snapshots_url).json()

        self.assertEqual(
            set(body["meta"]),
            {"count", "page", "page_size", "next", "previous"},
        )
        self.assertEqual(body["meta"]["count"], 3)

    def test_an_unknown_document_is_a_404_not_an_empty_list(self) -> None:
        url = f"{BASE}documents/2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819/snapshots/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_FOUND)

    def test_a_malformed_fiscal_year_is_rejected_not_ignored(self) -> None:
        response = self.client.get(f"{self.snapshots_url}?fiscal_year=2081")

        self.assertEqual(response.status_code, 400)
        self.assertIn("fiscal_year", response.json()["error"]["details"])


class SnapshotDetailTests(HistoryAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.snapshot = f.make_snapshot(self.admin, self.document)

    def test_detail_returns_the_frozen_body(self) -> None:
        response = self.client.get(self.snapshot_url(self.snapshot))

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["content"], self.document.content)
        self.assertEqual(data["render_context"], f.render_context())

    def test_an_unknown_snapshot_is_a_404(self) -> None:
        response = self.client.get(f"{BASE}snapshots/2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.SNAPSHOT_NOT_FOUND)


class TimelineTests(HistoryAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.snapshot = f.make_snapshot(self.admin, self.document)

    def test_timeline_returns_the_capture_event(self) -> None:
        response = self.client.get(self.timeline_url)

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_type"], PrintEventType.CAPTURE)

    def test_timeline_rows_carry_the_snapshot_version_and_label_inline(self) -> None:
        row = self.client.get(self.timeline_url).json()["data"][0]

        self.assertEqual(row["version_number"], self.snapshot.version_number)
        self.assertEqual(row["label"], self.snapshot.label)

    def test_event_type_filter_narrows_the_timeline(self) -> None:
        self.client.post(self.snapshot_url(self.snapshot, "reprint/"), {}, format="json")

        response = self.client.get(f"{self.timeline_url}?event_type=reprint")

        data = response.json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_type"], PrintEventType.REPRINT)

    def test_an_unrecognised_event_type_is_rejected_not_ignored(self) -> None:
        response = self.client.get(f"{self.timeline_url}?event_type=printed")

        self.assertEqual(response.status_code, 400)
        self.assertIn("event_type", response.json()["error"]["details"])

    def test_a_document_never_printed_returns_an_empty_list(self) -> None:
        other = f.make_document(self.admin, self.applicant, label="Certificate")

        response = self.client.get(f"{BASE}documents/{other.id}/timeline/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    def test_an_unknown_document_is_a_404(self) -> None:
        response = self.client.get(f"{BASE}documents/2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819/timeline/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_FOUND)


class ReprintTests(HistoryAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.snapshot = f.make_snapshot(self.admin, self.document)

    def test_reprint_returns_201_and_the_event(self) -> None:
        response = self.client.post(
            self.snapshot_url(self.snapshot, "reprint/"),
            {"note": "Second copy for the bank."},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["event_type"], PrintEventType.REPRINT)
        self.assertEqual(data["version_number"], self.snapshot.version_number)

    def test_reprint_does_not_grow_the_version_chain(self) -> None:
        self.client.post(self.snapshot_url(self.snapshot, "reprint/"), {}, format="json")

        chain = self.client.get(self.snapshots_url).json()["data"]
        self.assertEqual(len(chain), 1)

    def test_an_unknown_snapshot_is_a_404(self) -> None:
        response = self.client.post(
            f"{BASE}snapshots/2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819/reprint/", {}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.SNAPSHOT_NOT_FOUND)

    def test_an_overlong_note_is_a_validation_error(self) -> None:
        response = self.client.post(self.snapshot_url(self.snapshot, "reprint/"), {"note": "x" * 2001}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("note", response.json()["error"]["details"])


class RecoverTests(HistoryAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.snapshot = f.make_snapshot(self.admin, self.document)
        document_services.update_document(
            actor=self.admin,
            document=self.document,
            fields={"content": {"statement_account_holder": "Someone Else"}, "label": "Renamed"},
        )

    def test_recover_returns_the_updated_document_not_the_snapshot(self) -> None:
        response = self.client.post(self.snapshot_url(self.snapshot, "recover/"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        # The `documents` detail shape, identified by fields no snapshot has.
        self.assertIn("status", data)
        self.assertIn("is_editable", data)
        self.assertNotIn("version_number", data)
        self.assertEqual(data["content"], self.snapshot.content)
        self.assertEqual(data["label"], "Vyas Statement")

    def test_recover_into_an_archived_document_is_a_409(self) -> None:
        document_services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")

        response = self.client.post(self.snapshot_url(self.snapshot, "recover/"), {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_EDITABLE)

    def test_recover_records_a_recovery_event_on_the_timeline(self) -> None:
        self.client.post(self.snapshot_url(self.snapshot, "recover/"), {"note": "Reverting."}, format="json")

        events = self.client.get(f"{self.timeline_url}?event_type=recovery").json()["data"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["note"], "Reverting.")

    def test_an_unknown_snapshot_is_a_404(self) -> None:
        response = self.client.post(
            f"{BASE}snapshots/2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819/recover/", {}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.SNAPSHOT_NOT_FOUND)
