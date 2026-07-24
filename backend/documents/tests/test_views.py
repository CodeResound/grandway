"""Endpoint tests for the documents app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

The authority assertions matter more here than anywhere else in the project:
this is the first app where a **Lead Manager is denied outright**, reads
included, so every endpoint is checked against both a Lead Manager and a
Superadmin rather than just the latter.
"""

from __future__ import annotations

import copy
from typing import Any

from rest_framework.test import APITestCase

from documents.constants import DocumentStatus, ErrorCode
from documents.tests import factories as f

DOCS_URL = "/api/v1/documents/"


class DocumentAPITestCase(APITestCase):
    """Shared fixtures and envelope assertions."""

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

    def create_payload(self, **overrides: Any) -> dict[str, Any]:
        return {
            "applicant": str(self.applicant.id),
            "family": "student",
            "template_key": "student-certificate",
            "label": "Certificate",
            **overrides,
        }


class AccessTests(DocumentAPITestCase):
    """The defining property of this app: Admin only, reads included."""

    def setUp(self) -> None:
        super().setUp()
        self.document = f.make_document(self.admin, self.applicant)
        self.detail = f"{DOCS_URL}{self.document.id}/"

    def test_every_endpoint_requires_authentication(self) -> None:
        for url in (DOCS_URL, f"{DOCS_URL}workspaces/", self.detail, f"{self.detail}history/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)

    def test_lead_manager_is_denied_every_read(self) -> None:
        """No other app in the project refuses a Lead Manager a read."""
        self.auth(self.lead_manager)
        for url in (DOCS_URL, f"{DOCS_URL}workspaces/", self.detail, f"{self.detail}history/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_is_denied_every_write(self) -> None:
        self.auth(self.lead_manager)
        cases = (
            ("post", DOCS_URL, self.create_payload()),
            ("patch", self.detail, {"label": "x"}),
            ("post", f"{self.detail}status/", {"status": "ready"}),
            ("post", f"{self.detail}archive/", {"reason": "x"}),
            ("post", f"{self.detail}restore/", {}),
        )
        for method, url, payload in cases:
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, payload, format="json")
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_superadmin_is_denied_too(self) -> None:
        self.auth(self.superadmin)
        response = self.client.get(DOCS_URL)

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)


class DocumentListCreateTests(DocumentAPITestCase):
    def test_admin_may_list(self) -> None:
        f.make_document(self.admin, self.applicant)
        self.auth(self.admin)
        response = self.client.get(DOCS_URL)

        self.assertEqual(response.status_code, 200)
        body = self.assert_success_envelope(response)
        self.assertEqual(len(body["data"]), 1)
        self.assertIn("count", body["meta"])

    def test_the_list_row_omits_the_document_body(self) -> None:
        """A page of bank statements would otherwise carry a megabyte of rows."""
        f.make_bank_statement(self.admin, self.applicant)
        self.auth(self.admin)
        row = self.client.get(DOCS_URL).json()["data"][0]

        self.assertNotIn("content", row)
        self.assertIn("label", row)

    def test_filter_by_family(self) -> None:
        f.make_document(self.admin, self.applicant)
        f.make_bank_statement(self.admin, self.applicant)
        self.auth(self.admin)

        response = self.client.get(DOCS_URL, {"family": "bank_statement"})
        self.assertEqual(len(response.json()["data"]), 1)

    def test_filter_by_applicant(self) -> None:
        f.make_document(self.admin, self.applicant)
        other = f.make_applicant(self.admin, name_np="सीता")
        f.make_document(self.admin, other)
        self.auth(self.admin)

        response = self.client.get(DOCS_URL, {"applicant": str(self.applicant.id)})
        self.assertEqual(len(response.json()["data"]), 1)

    def test_unparseable_filter_is_rejected(self) -> None:
        self.auth(self.admin)
        self.assertEqual(self.client.get(DOCS_URL, {"family": "banks"}).status_code, 400)

    def test_create_applicant_owned(self) -> None:
        self.auth(self.admin)
        response = self.client.post(DOCS_URL, self.create_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["status"], DocumentStatus.DRAFT)
        self.assertFalse(data["is_standalone"])
        self.assertEqual(data["content"], {})

    def test_create_with_a_body(self) -> None:
        content = f.bank_statement_content()
        self.auth(self.admin)
        response = self.client.post(
            DOCS_URL,
            self.create_payload(
                family="bank_statement",
                template_key="bank-vyas-statement",
                label="Vyas Statement",
                content=copy.deepcopy(content),
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["content"], content)

    def test_create_standalone(self) -> None:
        self.auth(self.admin)
        payload = self.create_payload(applicant=None, standalone_purpose="Office letter for the director.")
        response = self.client.post(DOCS_URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["data"]["is_standalone"])

    def test_create_without_any_owner(self) -> None:
        self.auth(self.admin)
        response = self.client.post(DOCS_URL, self.create_payload(applicant=None), format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.OWNER_REQUIRED)

    def test_create_with_unknown_applicant(self) -> None:
        self.auth(self.admin)
        payload = self.create_payload(applicant="00000000-0000-0000-0000-000000000000")
        response = self.client.post(DOCS_URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.APPLICANT_NOT_FOUND)

    def test_create_with_mismatched_family_and_template(self) -> None:
        self.auth(self.admin)
        payload = self.create_payload(family="lor", template_key="bank-vyas-statement")
        response = self.client.post(DOCS_URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.TEMPLATE_KEY_INVALID)

    def test_create_with_a_malformed_template_key(self) -> None:
        self.auth(self.admin)
        response = self.client.post(DOCS_URL, self.create_payload(template_key="Student Certificate"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("template_key", response.json()["error"]["details"])

    def test_create_with_a_non_object_body(self) -> None:
        self.auth(self.admin)
        response = self.client.post(DOCS_URL, self.create_payload(content=[1, 2, 3]), format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.CONTENT_INVALID)

    def test_create_with_an_invalid_family(self) -> None:
        self.auth(self.admin)
        self.assertEqual(
            self.client.post(DOCS_URL, self.create_payload(family="wizardry"), format="json").status_code, 400
        )


class WorkspaceTests(DocumentAPITestCase):
    def test_workspaces_group_by_applicant(self) -> None:
        f.make_document(self.admin, self.applicant)
        f.make_bank_statement(self.admin, self.applicant)
        self.auth(self.admin)

        response = self.client.get(f"{DOCS_URL}workspaces/")
        self.assertEqual(response.status_code, 200)
        rows = self.assert_success_envelope(response)["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["document_count"], 2)
        self.assertTrue(rows[0]["applicant_name"])
        self.assertIsNotNone(rows[0]["last_updated"])

    def test_workspaces_is_not_shadowed_by_the_detail_route(self) -> None:
        """`workspaces/` is a literal segment declared before `<uuid:...>/`."""
        self.auth(self.admin)
        self.assertEqual(self.client.get(f"{DOCS_URL}workspaces/").status_code, 200)


class DocumentDetailTests(DocumentAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.document = f.make_bank_statement(self.admin, self.applicant)
        self.url = f"{DOCS_URL}{self.document.id}/"

    def test_retrieve_returns_the_body(self) -> None:
        self.auth(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["content"], f.bank_statement_content())

    def test_retrieve_unknown_document(self) -> None:
        self.auth(self.admin)
        response = self.client.get(f"{DOCS_URL}00000000-0000-0000-0000-000000000000/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_FOUND)

    def test_patch_saves_the_body_verbatim(self) -> None:
        content = f.bank_statement_content()
        content["transactions"].append({"date": "2026-06-01", "description": "Deposit", "credit": 75000})
        self.auth(self.admin)

        response = self.client.patch(self.url, {"content": copy.deepcopy(content)}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["content"], content)

    def test_patch_cannot_reassign_the_owner(self) -> None:
        other = f.make_applicant(self.admin, name_np="सीता")
        self.auth(self.admin)
        response = self.client.patch(self.url, {"applicant": str(other.id)}, format="json")

        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.OWNERSHIP_IMMUTABLE)
        self.assertIn("applicant", body["error"]["details"])

    def test_patch_cannot_change_the_template(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.url, {"template_key": "bank-karnali-statement"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.OWNERSHIP_IMMUTABLE)

    def test_patch_cannot_set_status(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.url, {"status": "archived"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.STATUS_IMMUTABLE)

    def test_patch_of_an_ordinary_field_still_works(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.url, {"label": "Vyas Statement 2083"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["label"], "Vyas Statement 2083")

    def test_patch_with_an_oversized_body(self) -> None:
        self.auth(self.admin)
        oversized = {"rows": ["x" * 2000 for _ in range(200)]}
        response = self.client.patch(self.url, {"content": oversized}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.CONTENT_TOO_LARGE)


class LifecycleEndpointTests(DocumentAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.document = f.make_document(self.admin, self.applicant)
        self.url = f"{DOCS_URL}{self.document.id}/"

    def test_mark_ready(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}status/", {"status": "ready"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], DocumentStatus.READY)

    def test_status_action_refuses_archived(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}status/", {"status": "archived"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json()["error"]["details"])

    def test_archive(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}archive/", {"reason": "Superseded."}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], DocumentStatus.ARCHIVED)
        self.assertFalse(data["is_editable"])
        self.assertIsNotNone(data["archived_at_bs"])
        self.assertEqual(data["archived_by_username"], self.admin.username)

    def test_archive_without_a_reason(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}archive/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["error"]["details"])

    def test_archiving_twice_conflicts(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}archive/", {"reason": "Superseded."}, format="json")
        response = self.client.post(f"{self.url}archive/", {"reason": "Again."}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_ALREADY_ARCHIVED)

    def test_an_archived_document_rejects_edits(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}archive/", {"reason": "Superseded."}, format="json")
        response = self.client.patch(self.url, {"label": "New"}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_EDITABLE)

    def test_restore(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}archive/", {"reason": "Superseded."}, format="json")
        response = self.client.post(f"{self.url}restore/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], DocumentStatus.DRAFT)
        self.assertTrue(data["is_editable"])
        self.assertIsNone(data["archived_at"])

    def test_restoring_an_active_document_conflicts(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}restore/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.DOCUMENT_NOT_ARCHIVED)

    def test_an_archived_document_is_still_listed(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}archive/", {"reason": "Superseded."}, format="json")

        self.assertEqual(len(self.client.get(DOCS_URL).json()["data"]), 1)
        self.assertEqual(len(self.client.get(DOCS_URL, {"status": "archived"}).json()["data"]), 1)
        self.assertEqual(len(self.client.get(DOCS_URL, {"status": "draft"}).json()["data"]), 0)

    def test_history_returns_the_full_trail(self) -> None:
        self.auth(self.admin)
        self.client.patch(self.url, {"label": "Renamed"}, format="json")
        self.client.post(f"{self.url}archive/", {"reason": "Superseded."}, format="json")

        response = self.client.get(f"{self.url}history/")
        self.assertEqual(response.status_code, 200)
        actions = [e["action"] for e in response.json()["data"]]
        self.assertIn("document_created", actions)
        self.assertIn("document_updated", actions)
        self.assertIn("document_archived", actions)

    def test_history_entries_carry_the_shared_audit_shape(self) -> None:
        """Regression: this endpoint used to omit `actor_id` (contract 1.1.0).

        The six history endpoints now render one shape owned by `audit`; three
        of them, this one included, had been dropping the acting user's id. The
        shared shape adds no field that could carry a document body — the
        redaction lives in the emitter, not the serializer.
        """
        self.auth(self.admin)
        entry = self.client.get(f"{self.url}history/").json()["data"][0]
        self.assertEqual(
            set(entry),
            {
                "id",
                "action",
                "actor_type",
                "actor_id",
                "actor_label",
                "summary",
                "reason",
                "changes",
                "metadata",
                "created_at",
                "created_at_bs",
            },
        )
        self.assertEqual(entry["actor_id"], str(self.admin.id))

    def test_history_never_carries_the_document_body(self) -> None:
        statement = f.make_bank_statement(self.admin, self.applicant)
        url = f"{DOCS_URL}{statement.id}/"
        content = f.bank_statement_content()
        content["statement_account_no"] = "5555444433332"
        self.auth(self.admin)
        self.client.patch(url, {"content": content}, format="json")

        events = self.client.get(f"{url}history/").json()["data"]
        self.assertNotIn("5555444433332", str(events))
