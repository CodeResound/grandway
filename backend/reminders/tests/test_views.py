"""Endpoint tests for the reminders app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

The access rule has one shape: Admin and Lead Manager may do everything,
Superadmin may do nothing — asserted once for reads and once for writes.
"""

from __future__ import annotations

import uuid
from typing import Any

from rest_framework.test import APITestCase

from reminders.constants import ErrorCode, ReminderStatus
from reminders.tests import factories as f

REMINDERS_URL = "/api/v1/reminders/"


def detail_url(reminder_id: Any) -> str:
    return f"{REMINDERS_URL}{reminder_id}/"


class ReminderAPITestCase(APITestCase):
    """Shared fixtures and envelope assertions."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.superadmin = f.make_superadmin()
        self.applicant = f.make_applicant(self.admin)
        self.client_record = f.make_client(self.admin)

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
        payload = {
            "applicant": str(self.applicant.id),
            "due_date": str(f.due_on(3)),
            "note": "Chase IELTS certificate.",
        }
        payload.update(overrides)
        return payload


class ReminderListCreateTests(ReminderAPITestCase):
    def test_list_requires_authentication(self) -> None:
        self.assertEqual(self.client.get(REMINDERS_URL).status_code, 401)

    def test_superadmin_is_denied_reads(self) -> None:
        self.auth(self.superadmin)
        response = self.client.get(REMINDERS_URL)
        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_create(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(REMINDERS_URL, self.create_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = self.assert_success_envelope(response)
        self.assertEqual(body["data"]["owner_type"], "applicant")
        self.assertEqual(body["data"]["status"], ReminderStatus.ACTIVE)
        self.assertIsNotNone(body["data"]["due_date_bs"])

    def test_client_owned_reminder_is_accepted(self) -> None:
        self.auth(self.admin)
        payload = self.create_payload()
        payload.pop("applicant")
        payload["client"] = str(self.client_record.id)

        response = self.client.post(REMINDERS_URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["owner_type"], "client")

    def test_two_owners_are_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(
            REMINDERS_URL,
            self.create_payload(client=str(self.client_record.id)),
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_zero_owners_are_rejected(self) -> None:
        self.auth(self.admin)
        payload = self.create_payload()
        payload.pop("applicant")

        self.assertEqual(self.client.post(REMINDERS_URL, payload, format="json").status_code, 400)

    def test_a_nonexistent_owner_is_a_400_naming_the_field(self) -> None:
        self.auth(self.admin)
        response = self.client.post(REMINDERS_URL, self.create_payload(applicant=str(uuid.uuid4())), format="json")

        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.OWNER_NOT_FOUND)
        self.assertIn("applicant", body["error"]["details"])

    def test_a_past_due_date_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(REMINDERS_URL, self.create_payload(due_date=str(f.due_on(-1))), format="json")
        self.assertEqual(response.status_code, 400)

    def test_todays_date_is_accepted(self) -> None:
        self.auth(self.admin)
        response = self.client.post(REMINDERS_URL, self.create_payload(due_date=str(f.due_on(0))), format="json")
        self.assertEqual(response.status_code, 201)

    def test_a_blank_note_is_rejected(self) -> None:
        self.auth(self.admin)
        self.assertEqual(
            self.client.post(REMINDERS_URL, self.create_payload(note=""), format="json").status_code,
            400,
        )

    def test_list_filters_by_owner_and_status(self) -> None:
        open_reminder = f.make_reminder(self.admin, applicant=self.applicant)
        f.make_reminder(self.admin, client=self.client_record, note="Client follow-up.")

        self.auth(self.admin)
        response = self.client.get(REMINDERS_URL, {"applicant": str(self.applicant.id), "status": "active"})

        body = self.assert_success_envelope(response)
        self.assertEqual([row["id"] for row in body["data"]], [str(open_reminder.id)])
        self.assertEqual(body["meta"]["count"], 1)

    def test_an_invalid_filter_is_rejected_not_ignored(self) -> None:
        self.auth(self.admin)
        self.assertEqual(self.client.get(REMINDERS_URL, {"status": "open"}).status_code, 400)

    def test_due_window_filters_apply_to_due_date(self) -> None:
        f.make_reminder(self.admin, applicant=self.applicant, due_in_days=2)
        f.make_reminder(self.admin, applicant=self.applicant, due_in_days=30, note="Far away.")

        self.auth(self.admin)
        response = self.client.get(REMINDERS_URL, {"due_before": str(f.due_on(7))})

        self.assertEqual(response.json()["meta"]["count"], 1)


class ReminderDetailTests(ReminderAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.reminder = f.make_reminder(self.admin, applicant=self.applicant)

    def test_retrieve_returns_the_full_shape(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.get(detail_url(self.reminder.id))

        body = self.assert_success_envelope(response)
        for field in ("owner_type", "due_date", "due_date_bs", "note", "status", "created_by_username"):
            self.assertIn(field, body["data"])

    def test_an_unknown_id_is_404(self) -> None:
        self.auth(self.admin)
        response = self.client.get(detail_url(uuid.uuid4()))
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.REMINDER_NOT_FOUND)

    def test_reschedule_moves_the_date(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(detail_url(self.reminder.id), {"due_date": str(f.due_on(14))}, format="json")

        body = self.assert_success_envelope(response)
        self.assertEqual(body["data"]["due_date"], str(f.due_on(14)))

    def test_an_empty_patch_is_rejected(self) -> None:
        self.auth(self.admin)
        self.assertEqual(self.client.patch(detail_url(self.reminder.id), {}, format="json").status_code, 400)

    def test_owner_fields_on_patch_are_rejected_loudly(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(
            detail_url(self.reminder.id), {"client": str(self.client_record.id)}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.FIELD_IMMUTABLE)
        self.assertIn("client", body["error"]["details"])

    def test_patching_a_closed_reminder_is_a_conflict(self) -> None:
        self.auth(self.admin)
        self.client.post(detail_url(self.reminder.id) + "dismiss/", {}, format="json")

        response = self.client.patch(detail_url(self.reminder.id), {"note": "Late edit."}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.REMINDER_ALREADY_CLOSED)


class ReminderClosureTests(ReminderAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.reminder = f.make_reminder(self.admin, client=self.client_record)

    def test_complete_stamps_the_lifecycle(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(
            detail_url(self.reminder.id) + "complete/", {"reason": "Payment received."}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = self.assert_success_envelope(response)
        self.assertEqual(body["data"]["status"], ReminderStatus.COMPLETED)
        self.assertIsNotNone(body["data"]["closed_at"])
        self.assertEqual(body["data"]["closed_by_username"], self.lead_manager.username)

    def test_dismiss_is_the_other_terminal_action(self) -> None:
        self.auth(self.admin)
        response = self.client.post(detail_url(self.reminder.id) + "dismiss/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], ReminderStatus.DISMISSED)

    def test_closing_twice_is_a_conflict(self) -> None:
        self.auth(self.admin)
        self.client.post(detail_url(self.reminder.id) + "complete/", {}, format="json")

        response = self.client.post(detail_url(self.reminder.id) + "dismiss/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.REMINDER_ALREADY_CLOSED)

    def test_superadmin_is_denied_writes(self) -> None:
        self.auth(self.superadmin)
        response = self.client.post(detail_url(self.reminder.id) + "complete/", {}, format="json")
        self.assertEqual(response.status_code, 403)


class ReminderHistoryTests(ReminderAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.reminder = f.make_reminder(self.admin, applicant=self.applicant)

    def test_history_lists_the_audit_trail_newest_first(self) -> None:
        self.auth(self.admin)
        self.client.patch(detail_url(self.reminder.id), {"due_date": str(f.due_on(21))}, format="json")

        response = self.client.get(detail_url(self.reminder.id) + "history/")

        body = self.assert_success_envelope(response)
        actions = [event["action"] for event in body["data"]]
        self.assertEqual(actions, ["reminder_rescheduled", "reminder_created"])

    def test_history_of_an_unknown_reminder_is_404(self) -> None:
        self.auth(self.admin)
        self.assertEqual(self.client.get(detail_url(uuid.uuid4()) + "history/").status_code, 404)
