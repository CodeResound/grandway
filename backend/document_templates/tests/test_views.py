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

import pathlib
import shutil
import tempfile
from typing import Any

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
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
        return {"name": f.NAME, "role": "director", **overrides}

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
            # Multipart-only, but posted here as JSON like every other route.
            # Safe: ``check_actor`` runs before ``request.data`` is touched, so
            # the 401/403 returns before any parser is selected.
            ("post", f"{SIGNATORIES}{self.signatory.id}/signature/"),
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
        for url in (
            f"{SIGNATORIES}{self.signatory.id}/",
            f"{SIGNATORIES}{self.signatory.id}/signature/",
            f"{TEMPLATES}{self.template.id}/",
            TEMPLATES,
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.delete(url).status_code, 405)


class SignatoryEndpointTests(TemplatesAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_create_returns_201_as_a_draft(self) -> None:
        response = self.client.post(SIGNATORIES, self.signatory_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["name"], f.NAME)
        self.assertEqual(data["status"], LifecycleStatus.DRAFT)
        self.assertFalse(data["is_active"])

    def test_create_rejects_a_missing_name(self) -> None:
        response = self.client.post(SIGNATORIES, {"role": "director"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["error"]["details"])

    def test_create_rejects_a_malformed_signature_url(self) -> None:
        response = self.client.post(
            SIGNATORIES, self.signatory_payload(signature_image_url="not-a-url"), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("signature_image_url", response.json()["error"]["details"])

    def test_the_frontend_picker_call_returns_only_active_signatories(self) -> None:
        """`?status=active` — the one call the frontend makes into this app."""
        f.make_signatory(self.admin)
        active = f.make_active_signatory(self.admin)

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
        f.make_signatory(self.admin)
        f.make_active_signatory(self.admin)

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


class SignatureUploadTests(TemplatesAPITestCase):
    """``POST /signatories/<id>/signature/`` — the app's first multipart route.

    This is also the suite's first test class needing real bytes on disk, so it
    carries the isolated ``MEDIA_ROOT`` that ``uploaded_files`` established.
    Without it a test run would write signature images into the developer's own
    media volume and leave them there.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._media_root = tempfile.mkdtemp(prefix="document-templates-signature-test-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.signatory = f.make_signatory(self.admin)
        self.url = f"{SIGNATORIES}{self.signatory.id}/signature/"

    def upload(self, **kwargs: Any) -> Any:
        return self.client.post(self.url, {"file": f.png_upload(**kwargs)}, format="multipart")

    # --- Success ---------------------------------------------------------

    def test_upload_returns_201_and_the_signatory_with_its_signature(self) -> None:
        response = self.upload()

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["signature_source"], "uploaded")
        self.assertEqual(data["signature_file"]["content_type"], "image/png")
        self.assertEqual(data["signature_file"]["original_filename"], "signature.png")
        self.assertEqual(data["signature_file"]["version_number"], 1)
        self.assertGreater(data["signature_file"]["size_bytes"], 0)

    def test_the_response_is_the_signatory_not_the_file(self) -> None:
        """The client re-renders the whole row from one response."""
        data = self.assert_success_envelope(self.upload())["data"]

        self.assertEqual(data["id"], str(self.signatory.id))
        self.assertEqual(data["name"], f.NAME)
        self.assertEqual(data["status"], LifecycleStatus.DRAFT)

    def test_the_storage_path_never_appears_in_the_response(self) -> None:
        """The one model field that is never serialized, anywhere in the project."""
        data = self.assert_success_envelope(self.upload())["data"]

        self.assertNotIn("uploaded_files/", str(data))
        self.assertNotIn("file", data["signature_file"])

    def test_the_download_path_is_the_documented_route(self) -> None:
        """``docs/API.md`` publishes this literal shape; a route move must fail here."""
        data = self.assert_success_envelope(self.upload())["data"]
        file_id = data["signature_file"]["id"]

        self.assertEqual(data["signature_file"]["download_path"], f"/api/v1/files/{file_id}/download/")

    def test_the_download_path_actually_serves_the_bytes(self) -> None:
        data = self.assert_success_envelope(self.upload())["data"]

        response = self.client.get(data["signature_file"]["download_path"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertGreater(len(b"".join(response.streaming_content)), 0)

    def test_an_inactive_signatory_may_still_receive_a_signature(self) -> None:
        """Retired signers stay editable — old certificates still resolve them."""
        retired = f.make_signatory(self.admin, name="Retired Signer")
        self.client.post(f"{SIGNATORIES}{retired.id}/status/", {"status": LifecycleStatus.INACTIVE}, format="json")

        response = self.client.post(
            f"{SIGNATORIES}{retired.id}/signature/", {"file": f.png_upload()}, format="multipart"
        )

        self.assertEqual(response.status_code, 201)

    # --- Precedence ------------------------------------------------------

    def test_signature_source_is_url_when_only_the_legacy_field_is_set(self) -> None:
        response = self.client.get(f"{SIGNATORIES}{self.signatory.id}/")

        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["signature_source"], "url")
        self.assertIsNone(data["signature_file"])

    def test_signature_source_is_none_when_neither_is_set(self) -> None:
        bare = f.make_signatory(self.admin, name="No Signature", signature_image_url="")

        data = self.assert_success_envelope(self.client.get(f"{SIGNATORIES}{bare.id}/"))["data"]

        self.assertEqual(data["signature_source"], "none")
        self.assertIsNone(data["signature_file"])

    def test_an_uploaded_file_wins_over_the_legacy_url(self) -> None:
        """The precedence rule, tested rather than only documented."""
        data = self.assert_success_envelope(self.upload())["data"]

        self.assertEqual(data["signature_source"], "uploaded")
        self.assertTrue(data["signature_image_url"], "the legacy URL must still be returned")
        self.assertIsNotNone(data["signature_file"])

    def test_the_legacy_url_still_works_on_create(self) -> None:
        """The non-breaking guarantee: nothing about the old field changed."""
        response = self.client.post(
            SIGNATORIES,
            {"name": "Legacy Only", "signature_image_url": "https://files.example/x.png"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["signature_image_url"], "https://files.example/x.png")
        self.assertEqual(data["signature_source"], "url")

    # --- Replacement and removal ----------------------------------------

    def test_a_second_upload_supersedes_the_first(self) -> None:
        first = self.assert_success_envelope(self.upload())["data"]["signature_file"]

        second = self.assert_success_envelope(self.upload(name="v2.png"))["data"]["signature_file"]

        self.assertEqual(second["version_number"], 2)
        self.assertNotEqual(second["id"], first["id"])
        versions = self.client.get(f"/api/v1/files/{first['id']}/versions/")
        self.assertEqual(len(versions.json()["data"]), 2)

    def test_archiving_the_file_removes_the_signature(self) -> None:
        """There is no remove endpoint; archiving the file is the gesture."""
        file_id = self.assert_success_envelope(self.upload())["data"]["signature_file"]["id"]

        archived = self.client.post(f"/api/v1/files/{file_id}/archive/", {"reason": "signer left"}, format="json")
        self.assertEqual(archived.status_code, 200)

        data = self.assert_success_envelope(self.client.get(f"{SIGNATORIES}{self.signatory.id}/"))["data"]
        self.assertIsNone(data["signature_file"])
        self.assertEqual(data["signature_source"], "url")

    def test_an_upload_after_archiving_starts_a_fresh_chain(self) -> None:
        """Not a 400 — removal must not have to be undone before re-adding."""
        file_id = self.assert_success_envelope(self.upload())["data"]["signature_file"]["id"]
        self.client.post(f"/api/v1/files/{file_id}/archive/", {"reason": "signer left"}, format="json")

        response = self.upload(name="fresh.png")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["signature_file"]["version_number"], 1)

    def test_a_signature_superseded_directly_is_re_pointed_not_followed(self) -> None:
        file_id = self.assert_success_envelope(self.upload())["data"]["signature_file"]["id"]
        self.client.post(
            f"/api/v1/files/{file_id}/replace/", {"file": f.png_upload(name="sideways.png")}, format="multipart"
        )

        response = self.upload(name="through-the-front-door.png")

        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]["signature_file"]
        self.assertEqual(data["version_number"], 1)
        self.assertEqual(data["original_filename"], "through-the-front-door.png")

    def test_restoring_an_archived_signature_makes_it_render_again(self) -> None:
        """Removal is a real undo — the link was never broken, only invalidated.

        Documented in `docs/INTEGRATION.md` §9. Pinned here because a client
        builds a "remove signature" button against it, and an undo whose
        behaviour is undefined is not shippable.
        """
        file_id = self.assert_success_envelope(self.upload())["data"]["signature_file"]["id"]
        self.client.post(f"/api/v1/files/{file_id}/archive/", {"reason": "signer left"}, format="json")
        self.assertEqual(
            self.client.get(f"{SIGNATORIES}{self.signatory.id}/").json()["data"]["signature_source"], "url"
        )

        self.client.post(f"/api/v1/files/{file_id}/restore/", {}, format="json")

        data = self.assert_success_envelope(self.client.get(f"{SIGNATORIES}{self.signatory.id}/"))["data"]
        self.assertEqual(data["signature_source"], "uploaded")
        self.assertEqual(data["signature_file"]["id"], file_id)

    def test_a_rejected_signature_still_renders(self) -> None:
        """`verification_status` is a record of judgement, not a gate.

        Surprising enough to pin: a reviewer rejecting a signature does **not**
        stop it printing on certificates. Only archiving does.
        """
        file_id = self.assert_success_envelope(self.upload())["data"]["signature_file"]["id"]

        rejected = self.client.post(
            f"/api/v1/files/{file_id}/verify/",
            {"status": "rejected", "reason": "wrong image"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 200)

        data = self.client.get(f"{SIGNATORIES}{self.signatory.id}/").json()["data"]
        self.assertEqual(data["signature_source"], "uploaded")

    def test_replacing_through_the_file_module_directly_blanks_the_signature(self) -> None:
        """The documented footgun, pinned so the warning cannot go stale.

        `POST /files/<id>/replace/` succeeds and creates a new row with a new
        id; this module's link does not follow it. Warned about in
        `uploaded_files/docs/INTEGRATION.md` §7 and this module's §9.
        """
        file_id = self.assert_success_envelope(self.upload())["data"]["signature_file"]["id"]

        replaced = self.client.post(
            f"/api/v1/files/{file_id}/replace/",
            {"file": f.png_upload(name="sideways.png")},
            format="multipart",
        )
        self.assertEqual(replaced.status_code, 201)

        data = self.client.get(f"{SIGNATORIES}{self.signatory.id}/").json()["data"]
        self.assertIsNone(data["signature_file"])
        self.assertEqual(data["signature_source"], "url")

    # --- Rejections ------------------------------------------------------

    def test_a_pdf_is_refused_as_a_signature(self) -> None:
        """The ledger would accept it; a signatory record must not."""
        response = self.client.post(self.url, {"file": f.pdf_upload()}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.SIGNATURE_NOT_AN_IMAGE)
        self.assertIn("file", response.json()["error"]["details"])

    def test_a_disallowed_type_is_refused(self) -> None:
        response = self.client.post(self.url, {"file": f.disallowed_upload()}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.SIGNATURE_NOT_AN_IMAGE)

    def test_an_oversize_image_is_refused(self) -> None:
        response = self.client.post(self.url, {"file": f.oversize_upload(name="huge.png")}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.SIGNATURE_FILE_TOO_LARGE)

    def test_an_empty_file_is_refused(self) -> None:
        """As ``VALIDATION_ERROR``, not ``SIGNATURE_FILE_EMPTY`` — see the code's note.

        DRF's own ``FileField`` refuses a zero-byte part before the service is
        reached, so the ledger's ``FileEmptyError`` never fires on this route.
        The refusal is what matters and it is tested here; the code that would
        carry it is documented as unreachable rather than quietly assumed.
        """
        response = self.client.post(self.url, {"file": f.empty_upload(name="empty.png")}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, "VALIDATION_ERROR")
        self.assertIn("file", response.json()["error"]["details"])

    def test_bytes_that_contradict_the_extension_are_refused(self) -> None:
        """A PNG wearing a name this app accepts — caught on leading bytes."""
        response = self.client.post(self.url, {"file": f.png_upload(name="signature.jpg")}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.SIGNATURE_FILE_CONTENT_MISMATCH)

    def test_a_missing_file_part_is_a_validation_error(self) -> None:
        response = self.client.post(self.url, {}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json()["error"]["details"])

    def test_no_uploaded_files_error_code_ever_surfaces(self) -> None:
        """A consumer must never receive another app's code namespace."""
        cases = [
            f.pdf_upload(),
            f.oversize_upload(name="huge.png"),
            f.empty_upload(name="empty.png"),
            f.png_upload(name="x.jpg"),
        ]
        for upload in cases:
            with self.subTest(upload=upload.name):
                response = self.client.post(self.url, {"file": upload}, format="multipart")
                code = response.json()["error"]["code"]
                self.assertFalse(code.startswith("UPLOADED_FILES_"), code)
                # Either this app's namespace or the project-wide validation
                # code. Never another app's.
                self.assertTrue(code.startswith("DOCUMENT_TEMPLATES_") or code == "VALIDATION_ERROR", code)

    def test_a_refused_upload_leaves_nothing_on_disk(self) -> None:
        before = sorted(pathlib.Path(self._media_root).rglob("*.pdf"))

        self.client.post(self.url, {"file": f.pdf_upload()}, format="multipart")

        self.assertEqual(sorted(pathlib.Path(self._media_root).rglob("*.pdf")), before)

    # --- Access and method shape ----------------------------------------

    def test_a_missing_signatory_is_404(self) -> None:
        response = self.client.post(
            f"{SIGNATORIES}{MISSING_ID}/signature/", {"file": f.png_upload()}, format="multipart"
        )

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.SIGNATORY_NOT_FOUND)

    def test_json_to_the_multipart_route_is_refused(self) -> None:
        response = self.client.post(self.url, {"file": "not-a-file"}, format="json")

        self.assertEqual(response.status_code, 415)

    def test_the_route_accepts_no_other_method(self) -> None:
        for method in ("get", "patch", "put", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)

    def test_patch_refuses_signature_file(self) -> None:
        """Loudly, not silently — a 200 would imply the link had been re-pointed."""
        response = self.client.patch(
            f"{SIGNATORIES}{self.signatory.id}/",
            {"signature_file": MISSING_ID},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.SIGNATURE_FILE_IMMUTABLE)
        self.assertIn("signature_file", response.json()["error"]["details"])


class SignatoryListQueryCountTests(TemplatesAPITestCase):
    """The signatory list must not fire one query per signature (§6 N+1).

    Structurally the same guard ``uploaded_files`` uses: the absolute count is
    not asserted — that would break on any unrelated middleware change — only
    that it does not grow with the number of rows.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._media_root = tempfile.mkdtemp(prefix="document-templates-nplus1-test-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def _populate(self, count: int) -> None:
        for index in range(count):
            f.make_signatory_with_signature(self.admin, name=f"Signer {index}")

    def test_the_query_count_does_not_grow_with_the_number_of_signatories(self) -> None:
        self.auth(self.admin)
        self._populate(2)
        with CaptureQueriesContext(connection) as small:
            response = self.client.get(SIGNATORIES, {"page_size": 100})
        self.assertEqual(len(response.json()["data"]), 2)

        self._populate(6)
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(SIGNATORIES, {"page_size": 100})
        self.assertEqual(len(response.json()["data"]), 8)

        self.assertEqual(len(large.captured_queries), len(small.captured_queries))

    def test_every_row_carries_its_signature(self) -> None:
        self.auth(self.admin)
        self._populate(3)

        data = self.client.get(SIGNATORIES, {"page_size": 100}).json()["data"]

        self.assertEqual(len(data), 3)
        for row in data:
            self.assertEqual(row["signature_source"], "uploaded")
            self.assertIsNotNone(row["signature_file"]["download_path"])
