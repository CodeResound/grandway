"""Unit tests for the notifications service layer.

Three things are worth testing here and everything else follows from them: that
``dispatch`` is genuinely idempotent, that routing sends alerts to the right
people, and that the composers produce keys with the discriminators the
idempotency argument depends on.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from notifications import services
from notifications.constants import (
    TYPE_PRIORITY,
    UNGENERATED_TYPES,
    DeliveryState,
    GenerationSource,
    NotificationStatus,
    NotificationType,
    Priority,
    Resolution,
    SourceEntityType,
)
from notifications.exceptions import AlreadyTerminalError
from notifications.models import Notification
from notifications.tests.factories import (
    add_item,
    make_admin,
    make_applicant,
    make_checklist,
    make_journey,
    make_lead_manager,
    raise_alert,
)


def _spec(key: str = "k1", **overrides) -> services.AlertSpec:
    defaults = {
        "notification_type": NotificationType.CHECKLIST_ITEM_OVERDUE,
        "dedupe_key": key,
        "title": "Overdue: Passport bio page scan",
        "body": "Required for Ram Bahadur.",
        "source_app": "checklists",
        "source_entity_type": SourceEntityType.CHECKLIST_ITEM,
        "source_entity_id": None,
    }
    return services.AlertSpec(**{**defaults, **overrides})


class DispatchTests(TestCase):
    """The single write path, and the idempotency the whole app rests on."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()

    def test_creates_one_row_per_recipient(self) -> None:
        created = services.dispatch(_spec(), [self.admin, self.manager])

        self.assertEqual(len(created), 2)
        self.assertEqual(Notification.objects.count(), 2)

    def test_second_dispatch_of_the_same_key_creates_nothing(self) -> None:
        services.dispatch(_spec(), [self.admin])
        created = services.dispatch(_spec(), [self.admin])

        self.assertEqual(created, [])
        self.assertEqual(Notification.objects.count(), 1)

    def test_the_same_key_for_a_different_recipient_is_a_different_row(self) -> None:
        services.dispatch(_spec(), [self.admin])
        created = services.dispatch(_spec(), [self.manager])

        self.assertEqual(len(created), 1)
        self.assertEqual(Notification.objects.count(), 2)

    def test_an_existing_row_is_never_rewritten(self) -> None:
        """The concept file's "do not silently rewrite history", enforced."""
        services.dispatch(_spec(title="Original title"), [self.admin])
        services.dispatch(_spec(title="Rewritten title"), [self.admin])

        self.assertEqual(Notification.objects.get().title, "Original title")

    def test_a_dismissed_alert_still_occupies_its_key(self) -> None:
        """Dismissal sticks: tonight's sweep must not re-raise what a user closed."""
        notification = services.dispatch(_spec(), [self.admin])[0]
        services.dismiss(notification, actor=self.admin)

        created = services.dispatch(_spec(), [self.admin])

        self.assertEqual(created, [])
        self.assertEqual(Notification.objects.get().status, NotificationStatus.DISMISSED)

    def test_priority_is_mapped_from_type_and_stored(self) -> None:
        services.dispatch(_spec(notification_type=NotificationType.OFFER_EXPIRED), [self.admin])

        self.assertEqual(Notification.objects.get().priority, Priority.URGENT)

    def test_in_app_delivery_completes_on_creation(self) -> None:
        services.dispatch(_spec(), [self.admin])
        notification = Notification.objects.get()

        self.assertEqual(notification.delivery_state, DeliveryState.DELIVERED)
        self.assertIsNotNone(notification.delivered_at)

    def test_every_declared_type_has_a_priority(self) -> None:
        """A type with no mapping would silently ship as ``normal``."""
        for value in NotificationType.values:
            self.assertIn(value, TYPE_PRIORITY, f"{value} has no priority mapping")

    def test_the_ungenerated_gap_is_exactly_three_types(self) -> None:
        """A new type nobody generates is a bug, not a feature (`constants.py`)."""
        from notifications.constants import SIGNAL_TYPES, SWEEP_TYPES

        covered = set(SWEEP_TYPES) | set(SIGNAL_TYPES) | set(UNGENERATED_TYPES)
        self.assertEqual(covered, set(NotificationType.values))
        self.assertEqual(len(UNGENERATED_TYPES), 3)


class RoutingTests(TestCase):
    """Who receives an alert — a business rule, tested as one."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.other_admin = make_admin("admin2")
        self.manager = make_lead_manager()
        applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, applicant)
        self.checklist = make_checklist(self.admin, self.journey)

    def test_item_assignee_wins_over_the_checklist_assignee(self) -> None:
        self.checklist.assigned_to = self.admin
        self.checklist.save(update_fields=["assigned_to"])
        item = add_item(self.admin, self.checklist, assigned_to=self.manager)

        self.assertEqual(services.recipients_for_checklist_item(item), [self.manager])

    def test_checklist_assignee_is_the_fallback_for_an_unassigned_item(self) -> None:
        self.checklist.assigned_to = self.manager
        self.checklist.save(update_fields=["assigned_to"])
        item = add_item(self.admin, self.checklist)
        item.checklist = self.checklist

        self.assertEqual(services.recipients_for_checklist_item(item), [self.manager])

    def test_unowned_work_fans_out_to_every_active_admin(self) -> None:
        item = add_item(self.admin, self.checklist)

        recipients = services.recipients_for_checklist_item(item)

        self.assertCountEqual(recipients, [self.admin, self.other_admin])
        self.assertNotIn(self.manager, recipients)

    def test_the_actor_is_never_notified_about_their_own_action(self) -> None:
        recipients = services.recipients_for_admins(exclude_actor=self.admin)

        self.assertEqual(recipients, [self.other_admin])

    def test_deactivated_admins_receive_nothing(self) -> None:
        self.other_admin.is_active = False
        self.other_admin.save(update_fields=["is_active"])

        self.assertEqual(services.recipients_for_admins(), [self.admin])

    def test_a_recipient_appearing_twice_receives_one_alert(self) -> None:
        """An uploader who is also an Admin is one person, not two recipients."""
        recipients = services._finalize([self.admin, self.admin, self.other_admin])

        self.assertEqual(recipients, [self.admin, self.other_admin])


class ComposerTests(TestCase):
    """The dedupe keys, and the discriminators the idempotency argument needs."""

    def setUp(self) -> None:
        self.admin = make_admin()
        applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, applicant)
        self.checklist = make_checklist(self.admin, self.journey)

    def test_due_and_overdue_are_different_keys_for_the_same_item(self) -> None:
        """Escalation depends on this: an item crossing its deadline re-alerts once."""
        item = add_item(self.admin, self.checklist, due_in_days=-3)

        due = services.build_checklist_item_alert(item, overdue=False)
        overdue = services.build_checklist_item_alert(item, overdue=True)

        self.assertNotEqual(due.dedupe_key, overdue.dedupe_key)
        self.assertIn(NotificationType.CHECKLIST_ITEM_DUE, due.dedupe_key)
        self.assertIn(NotificationType.CHECKLIST_ITEM_OVERDUE, overdue.dedupe_key)

    def test_the_due_date_is_part_of_the_key(self) -> None:
        """A rescheduled item must be able to raise a fresh alert."""
        item = add_item(self.admin, self.checklist, due_in_days=-3)
        first = services.build_checklist_item_alert(item, overdue=True)

        item.due_at = timezone.now() - timedelta(days=1)
        second = services.build_checklist_item_alert(item, overdue=True)

        self.assertNotEqual(first.dedupe_key, second.dedupe_key)

    def test_the_alert_carries_the_source_record_and_its_api_path(self) -> None:
        item = add_item(self.admin, self.checklist, due_in_days=-1)

        spec = services.build_checklist_item_alert(item, overdue=True)

        self.assertEqual(spec.source_app, "checklists")
        self.assertEqual(spec.source_entity_type, SourceEntityType.CHECKLIST_ITEM)
        self.assertEqual(spec.source_entity_id, item.id)
        self.assertEqual(spec.source_api_path, f"/api/v1/checklists/{self.checklist.id}/items/{item.id}/")

    def test_the_body_names_the_applicant_and_the_checklist(self) -> None:
        item = add_item(self.admin, self.checklist, due_in_days=-2)

        spec = services.build_checklist_item_alert(item, overdue=True)

        self.assertIn("Ram Bahadur", spec.body)
        self.assertIn(self.checklist.title, spec.body)

    def test_the_assignment_key_carries_the_assignee(self) -> None:
        """Reassignment alerts the new owner; a re-save alerts nobody."""
        manager = make_lead_manager()
        item = add_item(self.admin, self.checklist, assigned_to=manager)

        first = services.build_assignment_alert(item, entity_type=SourceEntityType.CHECKLIST_ITEM)
        item.assigned_to = self.admin
        item.assigned_to_id = self.admin.id
        second = services.build_assignment_alert(item, entity_type=SourceEntityType.CHECKLIST_ITEM)

        self.assertNotEqual(first.dedupe_key, second.dedupe_key)

    def test_the_journey_key_carries_the_stage(self) -> None:
        first = services.build_journey_alert(self.journey, closed=False)
        self.journey.stage = "shortlisting"
        second = services.build_journey_alert(self.journey, closed=False)

        self.assertNotEqual(first.dedupe_key, second.dedupe_key)


class ReadStateTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.notification = raise_alert(self.admin)

    def test_mark_read_sets_a_timestamp(self) -> None:
        services.mark_read(self.notification)

        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)
        self.assertTrue(self.notification.is_read)

    def test_marking_read_twice_keeps_the_first_timestamp(self) -> None:
        """The receipt answers "when did they first see this"."""
        services.mark_read(self.notification)
        first = Notification.objects.get(pk=self.notification.pk).read_at

        services.mark_read(self.notification)

        self.assertEqual(Notification.objects.get(pk=self.notification.pk).read_at, first)

    def test_mark_unread_clears_the_timestamp(self) -> None:
        services.mark_read(self.notification)
        services.mark_unread(self.notification)

        self.notification.refresh_from_db()
        self.assertIsNone(self.notification.read_at)

    def test_mark_all_read_clears_the_badge_including_terminal_rows(self) -> None:
        """Clearing the badge must leave nothing unread, or the number returns."""
        second = raise_alert(self.admin, dedupe_key="k2")
        services.dismiss(second, actor=self.admin)

        marked = services.mark_all_read(self.admin)

        self.assertEqual(marked, 2)
        self.assertEqual(Notification.objects.filter(recipient=self.admin, read_at__isnull=True).count(), 0)

    def test_mark_all_read_does_not_touch_another_user_feed(self) -> None:
        other = make_lead_manager()
        raise_alert(other, dedupe_key="k-other")

        services.mark_all_read(self.admin)

        self.assertIsNone(Notification.objects.get(recipient=other).read_at)


class DismissTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.notification = raise_alert(self.admin)

    def test_dismiss_sets_the_full_terminal_state(self) -> None:
        services.dismiss(self.notification, actor=self.admin)

        self.notification.refresh_from_db()
        self.assertEqual(self.notification.status, NotificationStatus.DISMISSED)
        self.assertEqual(self.notification.resolution, Resolution.DISMISSED_BY_USER)
        self.assertIsNotNone(self.notification.resolved_at)
        self.assertEqual(self.notification.dismissed_by, self.admin)

    def test_dismissing_twice_is_refused(self) -> None:
        services.dismiss(self.notification, actor=self.admin)

        with self.assertRaises(AlreadyTerminalError):
            services.dismiss(self.notification, actor=self.admin)

    def test_dismiss_writes_an_audit_event(self) -> None:
        """The one human judgement this app records."""
        from audit.models import AuditEvent

        services.dismiss(self.notification, actor=self.admin)

        event = AuditEvent.objects.filter(app_label="notifications", action="notification_dismissed").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.entity_id, self.notification.id)

    def test_creating_an_alert_writes_no_audit_event(self) -> None:
        """The row is the record. Auditing each one would double the sweep's writes."""
        from audit.models import AuditEvent

        self.assertFalse(AuditEvent.objects.filter(app_label="notifications").exists())


class ResolveClearedTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()

    def test_a_key_no_longer_true_is_resolved(self) -> None:
        raise_alert(self.admin, dedupe_key="gone")

        resolved = services.resolve_cleared(set(), types=(NotificationType.CHECKLIST_ITEM_OVERDUE,))

        self.assertEqual(resolved, 1)
        notification = Notification.objects.get()
        self.assertEqual(notification.status, NotificationStatus.RESOLVED)
        self.assertEqual(notification.resolution, Resolution.SOURCE_CLEARED)
        self.assertIsNotNone(notification.resolved_at)

    def test_a_key_still_true_is_left_alone(self) -> None:
        raise_alert(self.admin, dedupe_key="still-true")

        resolved = services.resolve_cleared({"still-true"}, types=(NotificationType.CHECKLIST_ITEM_OVERDUE,))

        self.assertEqual(resolved, 0)
        self.assertEqual(Notification.objects.get().status, NotificationStatus.ACTIVE)

    def test_types_not_examined_are_never_resolved(self) -> None:
        """A --type run must not close every other type as "no longer true"."""
        raise_alert(self.admin, dedupe_key="offer", notification_type=NotificationType.OFFER_EXPIRED)

        resolved = services.resolve_cleared(set(), types=(NotificationType.CHECKLIST_ITEM_OVERDUE,))

        self.assertEqual(resolved, 0)
        self.assertEqual(Notification.objects.get().status, NotificationStatus.ACTIVE)

    def test_signal_alerts_are_never_auto_resolved(self) -> None:
        """A stage change cannot un-happen."""
        raise_alert(
            self.admin,
            dedupe_key="stage",
            notification_type=NotificationType.JOURNEY_STAGE_CHANGED,
            generated_by=GenerationSource.SIGNAL,
        )

        resolved = services.resolve_cleared(set(), types=(NotificationType.JOURNEY_STAGE_CHANGED,))

        self.assertEqual(resolved, 0)

    def test_a_dismissed_alert_is_not_re_resolved(self) -> None:
        notification = raise_alert(self.admin, dedupe_key="dismissed")
        services.dismiss(notification, actor=self.admin)

        services.resolve_cleared(set(), types=(NotificationType.CHECKLIST_ITEM_OVERDUE,))

        self.assertEqual(Notification.objects.get().resolution, Resolution.DISMISSED_BY_USER)
