"""Model-level tests: the two database constraints and the derived properties.

The constraints are tested with ``Model.objects.create`` on purpose — the
point is that the *database* rejects a bad row even when every application
layer above it is bypassed.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from reminders.constants import ReminderStatus
from reminders.models import Reminder
from reminders.tests.factories import due_on, make_admin, make_applicant, make_client, make_reminder


class SingleOwnerConstraintTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)
        self.client_record = make_client(self.admin)

    def test_no_owner_is_rejected_by_the_database(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reminder.objects.create(due_date=due_on(1), note="orphan", created_by=self.admin)

    def test_two_owners_are_rejected_by_the_database(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reminder.objects.create(
                applicant=self.applicant,
                client=self.client_record,
                due_date=due_on(1),
                note="ambiguous",
                created_by=self.admin,
            )

    def test_exactly_one_owner_is_accepted(self) -> None:
        reminder = Reminder.objects.create(
            applicant=self.applicant, due_date=due_on(1), note="ok", created_by=self.admin
        )
        self.assertEqual(reminder.owner_type, "applicant")
        self.assertEqual(reminder.owner_id, self.applicant.id)


class ClosureCoherenceConstraintTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)

    def test_an_active_reminder_may_not_carry_a_closure_stamp(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reminder.objects.create(
                applicant=self.applicant,
                due_date=due_on(1),
                note="bad",
                created_by=self.admin,
                status=ReminderStatus.ACTIVE,
                closed_at=timezone.now(),
            )

    def test_a_terminal_reminder_must_carry_a_closure_stamp(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reminder.objects.create(
                applicant=self.applicant,
                due_date=due_on(1),
                note="bad",
                created_by=self.admin,
                status=ReminderStatus.COMPLETED,
                closed_at=None,
            )


class DerivedPropertyTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.client_record = make_client(self.admin)
        self.reminder = make_reminder(self.admin, client=self.client_record)

    def test_owner_type_walks_the_client_fk(self) -> None:
        self.assertEqual(self.reminder.owner_type, "client")
        self.assertEqual(self.reminder.owner_id, self.client_record.id)

    def test_is_active_tracks_status(self) -> None:
        self.assertTrue(self.reminder.is_active)

    def test_str_is_human_readable(self) -> None:
        text = str(self.reminder)
        self.assertIn("Chase the pending documents.", text)
        self.assertIn("active", text)
