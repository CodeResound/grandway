"""Endpoint tests for the clients app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

The authority failure has **two** shapes here, unlike every app except
``institutions``: a Lead Manager refused a write, and a Superadmin refused
everything including reads. Both are asserted.
"""

from __future__ import annotations

from typing import Any

from rest_framework.test import APITestCase

from clients.constants import ClientStatus, ErrorCode
from clients.tests import factories as f

CLIENTS_URL = "/api/v1/clients/"


class ClientAPITestCase(APITestCase):
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


class ClientListCreateTests(ClientAPITestCase):
    def test_list_requires_authentication(self) -> None:
        response = self.client.get(CLIENTS_URL)
        self.assertEqual(response.status_code, 401)

    def test_superadmin_is_denied_reads(self) -> None:
        self.auth(self.superadmin)
        response = self.client.get(CLIENTS_URL)

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_browse_the_directory(self) -> None:
        f.make_client(self.admin)
        self.auth(self.lead_manager)
        response = self.client.get(CLIENTS_URL)

        self.assertEqual(response.status_code, 200)
        body = self.assert_success_envelope(response)
        self.assertEqual(len(body["data"]), 1)
        self.assertIn("count", body["meta"])

    def test_list_row_carries_a_phone_number(self) -> None:
        f.make_client(self.admin, contact_numbers=[f.number("9801111111", is_primary=True)])
        self.auth(self.lead_manager)
        row = self.client.get(CLIENTS_URL).json()["data"][0]

        self.assertEqual(row["primary_contact_number"], "9801111111")

    def test_list_row_has_no_number_when_none_recorded(self) -> None:
        f.make_client(self.admin)
        self.auth(self.admin)
        row = self.client.get(CLIENTS_URL).json()["data"][0]

        self.assertIsNone(row["primary_contact_number"])

    def test_search_filter(self) -> None:
        f.make_client(self.admin, name_np="हिमाल एजुकेशन", name_en="Himal Education")
        f.make_client(self.admin, name_np="सगरमाथा कन्सल्ट", name_en="Sagarmatha Consult")
        self.auth(self.lead_manager)

        response = self.client.get(CLIENTS_URL, {"search": "Sagarmatha"})
        self.assertEqual(len(response.json()["data"]), 1)

    def test_unparseable_filter_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.get(CLIENTS_URL, {"status": "retired"})
        self.assertEqual(response.status_code, 400)

    def test_admin_may_add_a_client(self) -> None:
        self.auth(self.admin)
        response = self.client.post(
            CLIENTS_URL,
            {
                "name_np": "हिमाल एजुकेशन",
                "name_en": "Himal Education",
                "spokesperson_name_np": "सुनिता श्रेष्ठ",
                "spokesperson_designation": "Managing Director",
                "email": "info@himal.example",
                "website": "https://himal.example",
                "contact_numbers": [{"number": "9801111111", "label": "mobile", "is_primary": True}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["status"], ClientStatus.ACTIVE)
        self.assertTrue(data["name_romanized"])
        self.assertTrue(data["spokesperson_name_romanized"])
        self.assertEqual(len(data["contact_numbers"]), 1)

    def test_lead_manager_may_not_add_a_client(self) -> None:
        """The defining split of this app — reads shared, writes Admin-only."""
        self.auth(self.lead_manager)
        response = self.client.post(CLIENTS_URL, {"name_np": "हिमाल"}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_name_np_is_required(self) -> None:
        self.auth(self.admin)
        response = self.client.post(CLIENTS_URL, {"name_en": "Himal Education"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name_np", response.json()["error"]["details"])

    def test_duplicate_number_in_one_payload_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(
            CLIENTS_URL,
            {"name_np": "हिमाल", "contact_numbers": [{"number": "9801111111"}, {"number": "9801111111"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.CONTACT_NUMBER_DUPLICATE)

    def test_malformed_contact_number_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(
            CLIENTS_URL,
            {"name_np": "हिमाल", "contact_numbers": [{"number": "call me maybe"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_malformed_email_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(CLIENTS_URL, {"name_np": "हिमाल", "email": "not-an-email"}, format="json")
        self.assertEqual(response.status_code, 400)


class ClientDetailTests(ClientAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.record = f.make_client(self.admin, contact_numbers=[f.number("9801111111")])
        self.url = f"{CLIENTS_URL}{self.record.id}/"

    def test_lead_manager_may_read_the_detail(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["id"], str(self.record.id))
        self.assertIn("contact_numbers", data)

    def test_retrieve_unknown_client(self) -> None:
        self.auth(self.admin)
        response = self.client.get(f"{CLIENTS_URL}00000000-0000-0000-0000-000000000000/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.CLIENT_NOT_FOUND)

    def test_admin_may_correct_details(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.url, {"spokesperson_designation": "Director"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["spokesperson_designation"], "Director")

    def test_lead_manager_may_not_edit(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.patch(self.url, {"notes": "x"}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_patch_cannot_set_status(self) -> None:
        """Standing has one path — retire and restore. Rejected, not ignored."""
        self.auth(self.admin)
        response = self.client.patch(self.url, {"status": "inactive"}, format="json")

        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.STATUS_IMMUTABLE)
        self.assertIn("status", body["error"]["details"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ClientStatus.ACTIVE)

    def test_patch_cannot_set_the_retirement_stamp(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.url, {"retired_at": "2026-01-01T00:00:00Z"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.STATUS_IMMUTABLE)

    def test_patch_of_an_ordinary_field_still_works(self) -> None:
        """The guard must not catch a legitimate correction alongside it."""
        self.auth(self.admin)
        response = self.client.patch(self.url, {"notes": "Referred 12 students in 2082."}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["notes"], "Referred 12 students in 2082.")

    def test_patch_replaces_contact_numbers(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(
            self.url,
            {"contact_numbers": [{"number": "9802222222", "label": "whatsapp"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        numbers = [n["number"] for n in response.json()["data"]["contact_numbers"]]
        self.assertEqual(numbers, ["9802222222"])


class ClientStandingEndpointTests(ClientAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.record = f.make_client(self.admin)
        self.url = f"{CLIENTS_URL}{self.record.id}/"

    def test_retire(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}retire/", {"reason": "Partnership agreement ended."}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], ClientStatus.INACTIVE)
        self.assertFalse(data["is_active"])
        self.assertIsNotNone(data["retired_at_bs"])
        self.assertEqual(data["retired_by_username"], self.admin.username)

    def test_retire_without_a_reason(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}retire/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["error"]["details"])

    def test_retiring_twice_conflicts(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}retire/", {"reason": "Ended."}, format="json")
        response = self.client.post(f"{self.url}retire/", {"reason": "Ended again."}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.CLIENT_ALREADY_RETIRED)

    def test_lead_manager_may_not_retire(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(f"{self.url}retire/", {"reason": "Ended."}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_restore(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}retire/", {"reason": "Ended."}, format="json")
        response = self.client.post(f"{self.url}restore/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], ClientStatus.ACTIVE)
        self.assertEqual(data["status_note"], "")
        self.assertIsNone(data["retired_at"])

    def test_restoring_an_active_client_conflicts(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}restore/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.CLIENT_NOT_RETIRED)

    def test_a_retired_client_is_still_listed(self) -> None:
        """Retired partners stay visible historically — the concept requires it."""
        self.auth(self.admin)
        self.client.post(f"{self.url}retire/", {"reason": "Ended."}, format="json")

        self.assertEqual(len(self.client.get(CLIENTS_URL).json()["data"]), 1)
        self.assertEqual(len(self.client.get(CLIENTS_URL, {"status": "active"}).json()["data"]), 0)
        self.assertEqual(len(self.client.get(CLIENTS_URL, {"status": "inactive"}).json()["data"]), 1)

    def test_history_returns_the_full_trail(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}retire/", {"reason": "Ended."}, format="json")
        self.client.post(f"{self.url}restore/", {}, format="json")

        response = self.client.get(f"{self.url}history/")
        self.assertEqual(response.status_code, 200)
        actions = [e["action"] for e in response.json()["data"]]
        self.assertIn("client_created", actions)
        self.assertIn("client_retired", actions)
        self.assertIn("client_restored", actions)

    def test_lead_manager_may_read_history(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.get(f"{self.url}history/")
        self.assertEqual(response.status_code, 200)

    def test_superadmin_is_denied_every_action(self) -> None:
        self.auth(self.superadmin)
        for path, method in (("retire/", "post"), ("restore/", "post"), ("history/", "get")):
            with self.subTest(path=path):
                call = getattr(self.client, method)
                response = call(f"{self.url}{path}", {} if method == "post" else None, format="json")
                self.assertEqual(response.status_code, 403)

    def test_standing_endpoints_require_authentication(self) -> None:
        for path in ("retire/", "restore/", "history/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(f"{self.url}{path}").status_code, 401)
