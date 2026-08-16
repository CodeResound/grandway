"""Service-level tests: transitions, the audit trail, and normalization.

Every mutation must leave exactly the right audit event behind — the audit log
*is* a reminder's history, so a wrong action name here is a corrupted history,
not a cosmetic defect.
"""

from __future__ import annotations

import unicodedata

from audit.models import AuditEvent
from django.test import TestCase

from reminders import services
from reminders.constants import ReminderAuditAction, ReminderStatus
from reminders.exceptions import (
    OwnerNotFoundError,
    OwnerNotResolvedError,
    ReminderAlreadyClosedError,
)
from reminders.tests.factories import due_on, make_admin, make_applicant, make_client, make_reminder


def events_for(reminder) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(entity_type="reminder", entity_id=reminder.id).order_by("created_at"))


class CreateReminderTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)

    def test_creation_writes_one_audit_event_with_the_owner_in_metadata(self) -> None:
        reminder = make_reminder(self.admin, applicant=self.applicant)

        events = events_for(reminder)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, ReminderAuditAction.REMINDER_CREATED)
        self.assertEqual(events[0].metadata["owner_type"], "applicant")
        self.assertEqual(events[0].metadata["owner_id"], str(self.applicant.id))

    def test_the_note_is_nfc_normalized_at_the_service_layer(self) -> None:
        decomposed = unicodedata.normalize("NFD", "Éva's café follow-up")
        reminder = services.create_reminder(
            actor=self.admin, applicant=self.applicant, due_date=due_on(1), note=decomposed
        )
        self.assertEqual(reminder.note, unicodedata.normalize("NFC", decomposed))


class ResolveOwnerTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)

    def test_zero_owners_raises(self) -> None:
        with self.assertRaises(OwnerNotResolvedError):
            services.resolve_owner({})

    def test_two_owners_raises(self) -> None:
        with self.assertRaises(OwnerNotResolvedError):
            services.resolve_owner({"applicant": self.applicant.id, "client": self.applicant.id})

    def test_a_nonexistent_owner_names_its_field(self) -> None:
        with self.assertRaises(OwnerNotFoundError) as caught:
            services.resolve_owner({"client": self.applicant.id})
        self.assertEqual(caught.exception.owner_field, "client")

    def test_a_real_owner_resolves_to_its_instance(self) -> None:
        resolved = services.resolve_owner({"applicant": self.applicant.id})
        self.assertEqual(resolved, {"applicant": self.applicant})


class UpdateReminderTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)
        self.reminder = make_reminder(self.admin, applicant=self.applicant)

    def test_moving_the_date_is_audited_as_rescheduled_with_the_diff(self) -> None:
        old = self.reminder.due_date
        new = due_on(10)

        services.update_reminder(actor=self.admin, reminder=self.reminder, due_date=new)

        event = events_for(self.reminder)[-1]
        self.assertEqual(event.action, ReminderAuditAction.REMINDER_RESCHEDULED)
        self.assertEqual(event.changes["due_date"], {"from": str(old), "to": str(new)})

    def test_a_note_only_edit_is_audited_as_updated_not_rescheduled(self) -> None:
        services.update_reminder(actor=self.admin, reminder=self.reminder, note="Revised wording.")

        event = events_for(self.reminder)[-1]
        self.assertEqual(event.action, ReminderAuditAction.REMINDER_UPDATED)
        self.assertNotIn("due_date", event.changes)

    def test_a_no_op_update_writes_no_audit_event(self) -> None:
        before = len(events_for(self.reminder))
        services.update_reminder(
            actor=self.admin, reminder=self.reminder, due_date=self.reminder.due_date, note=self.reminder.note
        )
        self.assertEqual(len(events_for(self.reminder)), before)

    def test_a_closed_reminder_cannot_be_updated(self) -> None:
        services.complete_reminder(actor=self.admin, reminder=self.reminder)
        with self.assertRaises(ReminderAlreadyClosedError):
            services.update_reminder(actor=self.admin, reminder=self.reminder, due_date=due_on(5))


class ClosureTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.client_record = make_client(self.admin)
        self.reminder = make_reminder(self.admin, client=self.client_record)

    def test_completing_stamps_the_lifecycle_and_audits(self) -> None:
        services.complete_reminder(actor=self.admin, reminder=self.reminder, reason="Payment received.")

        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, ReminderStatus.COMPLETED)
        self.assertIsNotNone(self.reminder.closed_at)
        self.assertEqual(self.reminder.closed_by, self.admin)

        event = events_for(self.reminder)[-1]
        self.assertEqual(event.action, ReminderAuditAction.REMINDER_COMPLETED)
        self.assertEqual(event.reason, "Payment received.")

    def test_dismissing_is_the_other_terminal_state(self) -> None:
        services.dismiss_reminder(actor=self.admin, reminder=self.reminder)

        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, ReminderStatus.DISMISSED)
        self.assertEqual(events_for(self.reminder)[-1].action, ReminderAuditAction.REMINDER_DISMISSED)

    def test_terminal_states_are_final(self) -> None:
        services.dismiss_reminder(actor=self.admin, reminder=self.reminder)
        with self.assertRaises(ReminderAlreadyClosedError):
            services.complete_reminder(actor=self.admin, reminder=self.reminder)
