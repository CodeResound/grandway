"""Tests for ``sweep_notifications`` — the deadline half of generation.

Three properties matter more than the rest and each has its own test:

* **Idempotency.** Two runs produce one row. If this breaks, a nightly cron job
  fills every inbox in the office within a week.
* **Auto-resolution.** Finishing the work in the source app closes the alert
  without anybody touching the feed.
* **Never mass-resolve.** A generator that fails, or a ``--type`` run that only
  looked at one condition, must not close every other live alert as "no longer
  true". That is the single most damaging thing this command could do.

``TransactionTestCase`` because the fixtures go through services whose own
signals defer to ``on_commit``; an ordinary ``TestCase`` would leave that work
unrun and the assertions would be measuring a different system.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TransactionTestCase

from notifications.constants import (
    GenerationSource,
    NotificationStatus,
    NotificationType,
    Resolution,
)
from notifications.models import Notification
from notifications.tests.factories import (
    add_item,
    complete_item,
    give_passport,
    issued_offer,
    make_admin,
    make_applicant,
    make_checklist,
    make_journey,
    make_lead_manager,
)


def sweep(**options) -> str:
    out = StringIO()
    call_command("sweep_notifications", stdout=out, stderr=StringIO(), **options)
    return out.getvalue()


class OverdueChecklistItemTests(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, applicant)
        self.checklist = make_checklist(self.admin, self.journey)
        self.item = add_item(self.admin, self.checklist, due_in_days=-3, assigned_to=self.manager)
        Notification.objects.all().delete()

    def test_an_overdue_item_raises_one_alert_for_its_assignee(self) -> None:
        sweep()

        alerts = Notification.objects.filter(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts.get().recipient, self.manager)
        self.assertEqual(alerts.get().generated_by, GenerationSource.SWEEP)

    def test_running_twice_creates_nothing_the_second_time(self) -> None:
        """The idempotency proof. Without it, a nightly cron fills every inbox."""
        sweep()
        before = Notification.objects.count()

        sweep()

        self.assertEqual(Notification.objects.count(), before)

    def test_completing_the_item_resolves_its_alert(self) -> None:
        sweep()
        complete_item(self.admin, self.item)

        sweep()

        alert = Notification.objects.get(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        self.assertEqual(alert.status, NotificationStatus.RESOLVED)
        self.assertEqual(alert.resolution, Resolution.SOURCE_CLEARED)
        self.assertIsNotNone(alert.resolved_at)

    def test_a_resolved_alert_is_retained_not_deleted(self) -> None:
        """`concepts/notifications.txt` — preserve the history after the fix.

        Scoped to the overdue type rather than counting the assignee's whole
        feed: completing the item re-saves it, which fires the assignment
        receiver, and ``setUp`` freed that alert's dedupe key when it cleared the
        table. In production the key would still be occupied and nothing new
        would appear — the extra row here is an artefact of the fixture, not of
        the resolve pass.
        """
        sweep()
        complete_item(self.admin, self.item)
        sweep()

        overdue = Notification.objects.filter(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        self.assertEqual(overdue.count(), 1)
        self.assertEqual(overdue.get().status, NotificationStatus.RESOLVED)

    def test_a_dismissed_alert_is_not_re_raised(self) -> None:
        """Dismissal sticks — the row keeps its key forever."""
        from notifications import services

        sweep()
        alert = Notification.objects.get(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        services.dismiss(alert, actor=self.manager)

        sweep()

        self.assertEqual(Notification.objects.filter(recipient=self.manager).count(), 1)
        self.assertEqual(Notification.objects.get(recipient=self.manager).status, NotificationStatus.DISMISSED)

    def test_escalation_raises_a_second_alert_rather_than_mutating_the_first(self) -> None:
        """Due-soon → overdue is a new key, a new priority, and a new row."""
        soon = add_item(self.admin, self.checklist, label="Bank statement", due_in_days=2)
        sweep()
        self.assertEqual(Notification.objects.filter(notification_type=NotificationType.CHECKLIST_ITEM_DUE).count(), 1)

        # The deadline passes.
        from datetime import timedelta

        from django.utils import timezone

        soon.due_at = timezone.now() - timedelta(days=1)
        soon.save(update_fields=["due_at"])
        sweep()

        keys = set(Notification.objects.filter(source_entity_id=soon.id).values_list("notification_type", flat=True))
        self.assertEqual(keys, {NotificationType.CHECKLIST_ITEM_DUE, NotificationType.CHECKLIST_ITEM_OVERDUE})

    def test_dry_run_writes_nothing(self) -> None:
        output = sweep(dry_run=True)

        self.assertEqual(Notification.objects.count(), 0)
        self.assertIn("dry run", output)


class UnownedWorkTests(TransactionTestCase):
    """Deadlines on records nobody owns fan out to every active Admin."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.other_admin = make_admin("admin2")
        self.applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, self.applicant)

    def test_an_expiring_passport_alerts_every_admin(self) -> None:
        give_passport(self.admin, self.applicant, expires_in_days=30)
        Notification.objects.all().delete()

        sweep()

        alerts = Notification.objects.filter(notification_type=NotificationType.PASSPORT_EXPIRING)
        self.assertEqual(set(alerts.values_list("recipient_id", flat=True)), {self.admin.id, self.other_admin.id})

    def test_an_already_expired_passport_is_included(self) -> None:
        """The most blocked applicant on the list is the one whose passport lapsed."""
        give_passport(self.admin, self.applicant, expires_in_days=-10)
        Notification.objects.all().delete()

        sweep()

        alert = Notification.objects.filter(notification_type=NotificationType.PASSPORT_EXPIRING).first()
        self.assertIsNotNone(alert)
        self.assertIn("expired", alert.title.lower())

    def test_an_approaching_offer_deadline_raises_the_due_alert(self) -> None:
        issued_offer(self.admin, self.journey, deadline_in_days=3)
        Notification.objects.all().delete()

        sweep()

        self.assertTrue(Notification.objects.filter(notification_type=NotificationType.OFFER_RESPONSE_DUE).exists())
        self.assertFalse(Notification.objects.filter(notification_type=NotificationType.OFFER_EXPIRED).exists())

    def test_a_passed_offer_deadline_raises_the_urgent_alert(self) -> None:
        issued_offer(self.admin, self.journey, deadline_in_days=-2)
        Notification.objects.all().delete()

        sweep()

        alert = Notification.objects.filter(notification_type=NotificationType.OFFER_EXPIRED).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.priority, "urgent")


class MissingDocumentsTests(TransactionTestCase):
    """The gap the due-date-driven selectors structurally cannot see."""

    def setUp(self) -> None:
        self.admin = make_admin()
        applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, applicant)
        self.checklist = make_checklist(self.admin, self.journey)

    def test_document_items_with_no_due_date_raise_one_alert_per_checklist(self) -> None:
        add_item(self.admin, self.checklist, label="Bank statement")
        add_item(self.admin, self.checklist, label="Academic transcripts")
        Notification.objects.all().delete()

        sweep()

        alerts = Notification.objects.filter(notification_type=NotificationType.MISSING_DOCUMENTS)
        self.assertEqual(alerts.count(), 1)
        self.assertIn("2 documents", alerts.get().title)

    def test_a_completed_item_beside_a_pending_one_does_not_hide_the_alert(self) -> None:
        """The `.exclude()` trap: one resolved item must not hide the rest."""
        done = add_item(self.admin, self.checklist, label="Bank statement")
        add_item(self.admin, self.checklist, label="Academic transcripts")
        complete_item(self.admin, done)
        Notification.objects.all().delete()

        sweep()

        alerts = Notification.objects.filter(notification_type=NotificationType.MISSING_DOCUMENTS)
        self.assertEqual(alerts.count(), 1)
        self.assertIn("1 document ", alerts.get().title)

    def test_a_stage_item_with_no_due_date_is_not_a_missing_document(self) -> None:
        from checklists.constants import ItemType

        add_item(self.admin, self.checklist, label="Application submitted", item_type=ItemType.STAGE)
        Notification.objects.all().delete()

        sweep()

        self.assertFalse(Notification.objects.filter(notification_type=NotificationType.MISSING_DOCUMENTS).exists())


class ResolveSafetyTests(TransactionTestCase):
    """The command's most dangerous failure mode, tested directly."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, self.applicant)
        self.checklist = make_checklist(self.admin, self.journey)
        add_item(self.admin, self.checklist, due_in_days=-3)
        give_passport(self.admin, self.applicant, expires_in_days=30)
        Notification.objects.all().delete()
        sweep()

    def test_a_type_scoped_run_does_not_resolve_other_types(self) -> None:
        sweep(only_type=NotificationType.PASSPORT_EXPIRING)

        overdue = Notification.objects.get(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        self.assertEqual(overdue.status, NotificationStatus.ACTIVE)

    def test_a_failing_generator_does_not_resolve_its_own_types(self) -> None:
        """A transient error must not read as "nothing is overdue any more"."""
        target = "notifications.management.commands.sweep_notifications.get_overdue_checklist_items"
        with patch(target, side_effect=RuntimeError("database went away")):
            sweep()

        overdue = Notification.objects.get(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        self.assertEqual(overdue.status, NotificationStatus.ACTIVE)

    def test_a_failing_generator_is_recorded_rather_than_swallowed(self) -> None:
        """No alerts and a broken sweep look identical without this."""
        from audit.models import AuditEvent

        target = "notifications.management.commands.sweep_notifications.get_overdue_checklist_items"
        with patch(target, side_effect=RuntimeError("database went away")):
            sweep()

        self.assertTrue(
            AuditEvent.objects.filter(
                app_label="notifications",
                action="notification_generation_failed",
                success=False,
            ).exists()
        )

    def test_a_failing_generator_does_not_stop_the_others(self) -> None:
        Notification.objects.all().delete()
        target = "notifications.management.commands.sweep_notifications.get_overdue_checklist_items"
        with patch(target, side_effect=RuntimeError("database went away")):
            sweep()

        self.assertTrue(Notification.objects.filter(notification_type=NotificationType.PASSPORT_EXPIRING).exists())

    def test_no_resolve_leaves_cleared_alerts_active(self) -> None:
        item = self.checklist.items.first()
        complete_item(self.admin, item)

        sweep(no_resolve=True)

        overdue = Notification.objects.get(notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE)
        self.assertEqual(overdue.status, NotificationStatus.ACTIVE)
