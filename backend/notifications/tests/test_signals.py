"""Tests for the real-time lifecycle receivers.

Every test here saves a record through its owning app's service and then asserts
on what appeared in the feed. Nothing calls a receiver directly: a receiver that
passes its tests while disconnected from ``post_save`` is the exact failure this
suite exists to catch, and only going through a real save proves the wiring.

``TransactionTestCase`` throughout, and that is load-bearing rather than
incidental. Every receiver defers its work to ``transaction.on_commit``, which in
an ordinary ``TestCase`` never fires — the surrounding test transaction is rolled
back rather than committed, so a suite written on ``TestCase`` would assert
against an empty feed and pass by testing nothing.
"""

from __future__ import annotations

from django.test import TransactionTestCase, override_settings

from notifications.constants import GenerationSource, NotificationType, SourceEntityType
from notifications.models import Notification
from notifications.tests.factories import (
    add_item,
    give_passport,
    issued_offer,
    make_admin,
    make_applicant,
    make_checklist,
    make_journey,
    make_lead_manager,
    upload_for_applicant,
)


class AssignmentSignalTests(TransactionTestCase):
    """The alert with a genuinely targeted recipient."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, self.applicant)
        self.checklist = make_checklist(self.admin, self.journey)
        Notification.objects.all().delete()

    def test_assigning_an_item_alerts_the_assignee_alone(self) -> None:
        add_item(self.admin, self.checklist, assigned_to=self.manager)

        alerts = Notification.objects.filter(notification_type=NotificationType.ASSIGNMENT_RECEIVED)

        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts.get().recipient, self.manager)

    def test_an_unassigned_item_alerts_nobody(self) -> None:
        """An assignment with no assignee is not an assignment."""
        add_item(self.admin, self.checklist)

        self.assertFalse(Notification.objects.filter(notification_type=NotificationType.ASSIGNMENT_RECEIVED).exists())

    def test_re_saving_an_unchanged_item_creates_nothing(self) -> None:
        """The dedupe key is the change detector — there is no pre_save anywhere."""
        item = add_item(self.admin, self.checklist, assigned_to=self.manager)

        item.description = "Touched, but the assignee did not move."
        item.save()

        self.assertEqual(
            Notification.objects.filter(notification_type=NotificationType.ASSIGNMENT_RECEIVED).count(), 1
        )

    def test_reassigning_alerts_the_new_owner(self) -> None:
        item = add_item(self.admin, self.checklist, assigned_to=self.manager)

        item.assigned_to = self.admin
        item.save()

        recipients = set(
            Notification.objects.filter(notification_type=NotificationType.ASSIGNMENT_RECEIVED).values_list(
                "recipient_id", flat=True
            )
        )
        self.assertEqual(recipients, {self.manager.id, self.admin.id})

    def test_the_alert_is_marked_signal_generated(self) -> None:
        """Only sweep-generated alerts may be auto-resolved."""
        add_item(self.admin, self.checklist, assigned_to=self.manager)

        alert = Notification.objects.get(notification_type=NotificationType.ASSIGNMENT_RECEIVED)
        self.assertEqual(alert.generated_by, GenerationSource.SIGNAL)


class FileRejectionSignalTests(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.other_admin = make_admin("admin2")
        self.manager = make_lead_manager()
        self.applicant = make_applicant(self.admin)

    def test_rejecting_a_file_alerts_the_uploader_and_the_admins(self) -> None:
        from uploaded_files import services as file_services

        uploaded = upload_for_applicant(self.manager, self.applicant)
        Notification.objects.all().delete()

        file_services.review_file(
            actor=self.admin,
            uploaded_file=uploaded,
            status="rejected",
            reason="The scan is unreadable.",
        )

        alerts = Notification.objects.filter(notification_type=NotificationType.FILE_REJECTED)
        recipients = set(alerts.values_list("recipient_id", flat=True))

        # The uploader and the *other* Admin — never the Admin who rejected it.
        self.assertEqual(recipients, {self.manager.id, self.other_admin.id})

    def test_the_rejection_reason_is_carried_into_the_body(self) -> None:
        from uploaded_files import services as file_services

        uploaded = upload_for_applicant(self.manager, self.applicant)
        file_services.review_file(
            actor=self.admin,
            uploaded_file=uploaded,
            status="rejected",
            reason="The scan is unreadable.",
        )

        alert = Notification.objects.filter(notification_type=NotificationType.FILE_REJECTED).first()
        self.assertIn("unreadable", alert.body)
        self.assertEqual(alert.source_entity_type, SourceEntityType.UPLOADED_FILE)

    def test_verifying_a_file_alerts_nobody(self) -> None:
        from uploaded_files import services as file_services

        uploaded = upload_for_applicant(self.manager, self.applicant)
        file_services.review_file(actor=self.admin, uploaded_file=uploaded, status="verified")

        self.assertFalse(Notification.objects.filter(notification_type=NotificationType.FILE_REJECTED).exists())


class JourneySignalTests(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)

    def test_creating_a_journey_alerts_the_admins(self) -> None:
        make_journey(self.admin, self.applicant)

        alerts = Notification.objects.filter(notification_type=NotificationType.JOURNEY_STAGE_CHANGED)
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts.get().recipient, self.admin)

    def test_re_saving_at_the_same_stage_creates_nothing(self) -> None:
        journey = make_journey(self.admin, self.applicant)

        journey.notes = "Touched."
        journey.save()

        self.assertEqual(
            Notification.objects.filter(notification_type=NotificationType.JOURNEY_STAGE_CHANGED).count(), 1
        )

    def test_moving_to_a_new_stage_raises_a_second_alert(self) -> None:
        from applicant_journeys import services as journey_services
        from applicant_journeys.constants import JourneyStage

        journey = make_journey(self.admin, self.applicant)
        journey_services.change_stage(actor=self.admin, journey=journey, stage=JourneyStage.SHORTLISTING)

        self.assertEqual(
            Notification.objects.filter(notification_type=NotificationType.JOURNEY_STAGE_CHANGED).count(), 2
        )

    def test_closing_a_journey_raises_the_closure_alert(self) -> None:
        from applicant_journeys import services as journey_services

        journey = make_journey(self.admin, self.applicant)
        journey_services.close_journey(
            actor=self.admin,
            journey=journey,
            outcome="successful",
            reason="Visa granted.",
        )

        self.assertTrue(Notification.objects.filter(notification_type=NotificationType.JOURNEY_CLOSED).exists())


class OfferSignalTests(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, self.applicant)

    def test_a_draft_or_issued_offer_raises_no_decision_alert(self) -> None:
        """Drafting is the office's own working state, not news."""
        issued_offer(self.admin, self.journey, deadline_in_days=5)

        self.assertFalse(Notification.objects.filter(notification_type=NotificationType.OFFER_DECIDED).exists())

    def test_a_decision_raises_one_alert(self) -> None:
        from offers import services as offer_services

        offer = issued_offer(self.admin, self.journey, deadline_in_days=5)
        offer_services.record_decision(actor=self.admin, offer=offer, outcome="accepted")

        alerts = Notification.objects.filter(notification_type=NotificationType.OFFER_DECIDED)
        self.assertEqual(alerts.count(), 1)
        self.assertIn("accepted", alerts.get().title.lower())


class DisableSignalsTests(TransactionTestCase):
    """§11 — a signal that cannot be switched off cannot be imported around."""

    @override_settings(DISABLE_SIGNALS=True)
    def test_no_receiver_fires_when_signals_are_disabled(self) -> None:
        admin = make_admin()
        manager = make_lead_manager()
        applicant = make_applicant(admin)
        journey = make_journey(admin, applicant)
        checklist = make_checklist(admin, journey)
        add_item(admin, checklist, assigned_to=manager)
        give_passport(admin, applicant, expires_in_days=10)

        self.assertEqual(Notification.objects.count(), 0)
