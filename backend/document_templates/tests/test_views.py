"""Endpoint tests for the document_templates app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

The authority assertions check a Lead Manager **and** a Superadmin on every
route. That matters more here than the risk ratings suggest: this app holds no
applicant data, so a reviewer skimming it could reasonably assume the access
rule is looser than its siblings'. It is not — and a regression that quietly
opened a read would be easy to miss for exactly that reason.
"""

from __future__ import annotations

from typing import Any

from documents.constants import DocumentFamily
from rest_framework.test import APITestCase

from document_templates.constants import ErrorCode, LifecycleStatus
from document_templates.tests import factories as f

BASE = "/api/v1/document-templates/"
SIGNATORIES = f"{BASE}signatories/"
TEMPLATES = f"{BASE}templates/"
MISSING_ID = "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819"


class TemplatesAPITestCase(APITestCase):
    """Shared fixtures and envelope assertions."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.superadmin = f.make_superadmin()

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

    def signatory_payload(self, **overrides: Any) -> dict[str, Any]:
        return {"name_np": f.NAME_NP, "name_en": f.NAME_EN, "role": "director", **overrides}

    def template_payload(self, **overrides: Any) -> dict[str, Any]:
        return {
            "key": "bank-vyas-statement",
            "family": DocumentFamily.BANK_STATEMENT,
            "label": "Vyas Statement",
            **overrides,
        }


class AccessTests(TemplatesAPITestCase):
    """Admin only, reads included — on every one of the six routes."""

    def setUp(self) -> None:
        super().setUp()
        self.signatory = f.make_signatory(self.admin)
        self.template = f.make_template(self.admin)

    def routes(self) -> list[tuple[str, str]]:
        return [
            ("get", SIGNATORIES),
            ("post", SIGNATORIES),
            ("get", f"{SIGNATORIES}{self.signatory.id}/"),
            ("patch", f"{SIGNATORIES}{self.signatory.id}/"),
            ("post", f"{SIGNATORIES}{self.signatory.id}/status/"),
            ("get", TEMPLATES),
            ("post", TEMPLATES),
            ("get", f"{TEMPLATES}{self.template.id}/"),
            ("patch", f"{TEMPLATES}{self.template.id}/"),
            ("post", f"{TEMPLATES}{self.template.id}/status/"),
        ]

    def test_unauthenticated_is_rejected_everywhere(self) -> None:
        for method, url in self.routes():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 401)

    def test_lead_manager_is_forbidden_everywhere_including_reads(self) -> None:
        self.auth(self.lead_manager)
        for method, url in self.routes():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_superadmin_is_forbidden_everywhere(self) -> None:
        self.auth(self.superadmin)
        for method, url in self.routes():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 403)

    def test_no_route_accepts_delete(self) -> None:
        """Nothing here is ever removed, at the HTTP layer either."""
        self.auth(self.admin)
        for url in (f"{SIGNATORIES}{self.signatory.id}/", f"{TEMPLATES}{self.template.id}/", TEMPLATES):
            with self.subTest(url=url):
                self.assertEqual(self.client.delete(url).status_code, 405)


class SignatoryEndpointTests(TemplatesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_create_returns_201_with_the_derived_romanization(self) -> None:
        response = self.client.post(SIGNATORIES, self.signatory_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertTrue(data["name_romanized"])
        self.assertEqual(data["status"], LifecycleStatus.DRAFT)
        self.assertFalse(data["is_active"])

    def test_create_rejects_a_missing_devanagari_name(self) -> None:
        response = self.client.post(SIGNATORIES, {"name_en": "Sunita"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name_np", response.json()["error"]["details"])

    def test_create_rejects_a_malformed_signature_url(self) -> None:
        response = self.client.post(
            SIGNATORIES, self.signatory_payload(signature_image_url="not-a-url"), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("signature_image_url", response.json()["error"]["details"])

    def test_the_frontend_picker_call_returns_only_active_signatories(self) -> None:
        """`?status=active` — the one call the frontend makes into this app."""
        f.make_signatory(self.admin, name_np="मुकेश")
        active = f.make_active_signatory(self.admin, name_np="सुनिता")

        response = self.client.get(f"{SIGNATORIES}?status=active")

        data = self.assert_success_envelope(response)["data"]
        self.assertEqual([row["id"] for row in data], [str(active.id)])

    def test_list_rejects_an_unrecognised_status_rather_than_ignoring_it(self) -> None:
        response = self.client.get(f"{SIGNATORIES}?status=enabled")

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json()["error"]["details"])

    def test_pagination_meta_matches_the_project_schema(self) -> None:
        f.make_signatory(self.admin)

        body = self.client.get(SIGNATORIES).json()

        self.assertEqual(set(body["meta"]), {"count", "page", "page_size", "next", "previous"})

    def test_detail_returns_the_signatory(self) -> None:
        signatory = f.make_signatory(self.admin)

        response = self.client.get(f"{SIGNATORIES}{signatory.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assert_success_envelope(response)["data"]["id"], str(signatory.id))

    def test_an_unknown_signatory_is_a_404(self) -> None:
        response = self.client.get(f"{SIGNATORIES}{MISSING_ID}/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.SIGNATORY_NOT_FOUND)

    def test_patch_updates_the_role(self) -> None:
        signatory = f.make_signatory(self.admin)

        response = self.client.patch(f"{SIGNATORIES}{signatory.id}/", {"role": "instructor"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["role"], "instructor")

    def test_patch_refuses_to_set_status_directly(self) -> None:
        signatory = f.make_signatory(self.admin)

        response = self.client.patch(f"{SIGNATORIES}{signatory.id}/", {"status": "active"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.STATUS_IMMUTABLE)

    def test_status_action_activates_a_signatory(self) -> None:
        signatory = f.make_signatory(self.admin)

        response = self.client.post(
            f"{SIGNATORIES}{signatory.id}/status/",
            {"status": "active", "note": "Signature received."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertTrue(data["is_active"])
        self.assertEqual(data["status_note"], "Signature received.")

    def test_status_action_rejects_an_unknown_status(self) -> None:
        """A bad value fails at the serializer, so the code is VALIDATION_ERROR.

        `DOCUMENT_TEMPLATES_STATUS_INVALID_TRANSITION` is unreachable over HTTP
        for exactly this reason — the service guard behind it can only be hit by
        a non-serializer caller.
        """
        signatory = f.make_signatory(self.admin)

        response = self.client.post(f"{SIGNATORIES}{signatory.id}/status/", {"status": "enabled"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("status", response.json()["error"]["details"])

    def test_patch_refuses_to_set_status_note_directly(self) -> None:
        """`status_note` is guarded alongside `status`, on both resources."""
        signatory = f.make_signatory(self.admin)

        response = self.client.patch(f"{SIGNATORIES}{signatory.id}/", {"status_note": "sneaking it in"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.STATUS_IMMUTABLE)

    def test_omitting_status_returns_every_signatory(self) -> None:
        """The management screen wants drafts and retired signers, not the picker."""
        f.make_signatory(self.admin, name_np="मुकेश")
        f.make_active_signatory(self.admin, name_np="सुनिता")

        body = self.client.get(SIGNATORIES).json()

        self.assertEqual(body["meta"]["count"], 2)


class TemplateEndpointTests(TemplatesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_create_returns_201(self) -> None:
        response = self.client.post(TEMPLATES, self.template_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["key"], "bank-vyas-statement")
        self.assertEqual(data["status"], LifecycleStatus.DRAFT)

    def test_create_rejects_a_duplicate_key(self) -> None:
        f.make_template(self.admin)

        response = self.client.post(TEMPLATES, self.template_payload(), format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.KEY_ALREADY_EXISTS)

    def test_create_rejects_a_key_that_disagrees_with_its_family(self) -> None:
        """The rule is imported from `documents`; the error code is this app's."""
        response = self.client.post(TEMPLATES, self.template_payload(family=DocumentFamily.LOR), format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.TEMPLATE_KEY_INVALID)

    def test_create_rejects_a_malformed_slug_at_the_serializer(self) -> None:
        response = self.client.post(TEMPLATES, self.template_payload(key="Bank Vyas"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("key", response.json()["error"]["details"])

    def test_family_filter_narrows_the_catalogue(self) -> None:
        f.make_template(self.admin)
        f.make_template(self.admin, key="lor-kcmit", family=DocumentFamily.LOR, label="KCMIT")

        response = self.client.get(f"{TEMPLATES}?family=lor")

        data = self.assert_success_envelope(response)["data"]
        self.assertEqual([row["key"] for row in data], ["lor-kcmit"])

    def test_create_error_precedence_is_serializer_then_duplicate_then_family(self) -> None:
        """Which of the three 400s wins when a payload trips more than one."""
        f.make_template(self.admin)

        # Malformed slug + duplicate + family mismatch → the serializer wins.
        malformed = self.client.post(
            TEMPLATES, self.template_payload(key="Bank Vyas", family=DocumentFamily.LOR), format="json"
        )
        self.assertEqual(malformed.json()["error"]["code"], "VALIDATION_ERROR")

        # Well-formed but duplicate + family mismatch → uniqueness wins.
        duplicate = self.client.post(TEMPLATES, self.template_payload(family=DocumentFamily.LOR), format="json")
        self.assertEqual(duplicate.json()["error"]["code"], ErrorCode.KEY_ALREADY_EXISTS)

    def test_patch_refuses_to_set_status_note_directly(self) -> None:
        template = f.make_template(self.admin)

        response = self.client.patch(f"{TEMPLATES}{template.id}/", {"status_note": "sneaking it in"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.STATUS_IMMUTABLE)

    def test_patch_refuses_to_rename_the_key(self) -> None:
        template = f.make_template(self.admin)

        response = self.client.patch(f"{TEMPLATES}{template.id}/", {"key": "bank-tribeni-statement"}, format="json")

        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.KEY_IMMUTABLE)
        self.assertIn("key", body["error"]["details"])

    def test_patch_updates_the_label(self) -> None:
        template = f.make_template(self.admin)

        response = self.client.patch(f"{TEMPLATES}{template.id}/", {"label": "Vyas Bank Statement"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["label"], "Vyas Bank Statement")

    def test_an_unknown_template_is_a_404(self) -> None:
        response = self.client.get(f"{TEMPLATES}{MISSING_ID}/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.TEMPLATE_NOT_FOUND)

    def test_status_action_retires_a_template(self) -> None:
        template = f.make_active_template(self.admin)

        response = self.client.post(
            f"{TEMPLATES}{template.id}/status/",
            {"status": "inactive", "note": "Partner closed."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertFalse(data["is_active"])

    def test_a_retired_template_is_still_retrievable(self) -> None:
        """Retirement must not break records that already point at the key."""
        template = f.make_active_template(self.admin)
        self.client.post(f"{TEMPLATES}{template.id}/status/", {"status": "inactive"}, format="json")

        response = self.client.get(f"{TEMPLATES}{template.id}/")

        self.assertEqual(response.status_code, 200)
