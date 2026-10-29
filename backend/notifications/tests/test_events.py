"""Alerts raised from domain events — leads, applicants, documents (2026-10-29).

Every test acts through the owning app's service and asserts on the feed, so the
wiring from ``core.events.emit`` to ``dispatch`` is exercised end to end.
``TransactionTestCase`` because ``emit`` waits for the commit (see
``test_signals.py`` for why a ``TestCase`` here would pass by testing nothing).

Routing under test (decisions of 2026-10-29):

* new event alerts about an applicant go to the assignee (plus Admins for
  status changes), or to every Admin and Lead Manager when nobody is assigned;
* the older journey alerts keep Admin routing and only gain the assignee;
* nobody is told about their own action.
"""

from __future__ import annotations

from typing import Any

from applicant_journeys import services as journey_services
from applicant_journeys.constants import JourneyStage
from applicants import services as applicant_services
from applicants.constants import ApplicantStatus
from core.constants import NoteCategory
from django.test import TransactionTestCase
from documents import services as document_services
from documents.constants import DocumentStatus
from documents.tests.factories import make_document
from leads import services as lead_services
from leads.tests.factories import make_lead, make_source

from notifications.constants import NotificationType
from notifications.models import Notification
from notifications.tests.factories import make_admin, make_applicant, make_journey, make_lead_manager


def recipients(notification_type: str) -> set[str]:
    return set(
        Notification.objects.filter(notification_type=notification_type).values_list("recipient__username", flat=True)
    )


class _Team(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = make_admin("admin1")
        self.admin2 = make_admin("admin2")
        self.manager = make_lead_manager("manager1")
        self.manager2 = make_lead_manager("manager2")


class LeadEventTests(_Team):
    def setUp(self) -> None:
        super().setUp()
        self.lead = make_lead(self.manager, make_source())

    def test_created_goes_to_the_admins(self) -> None:
        self.assertEqual(recipients(NotificationType.LEAD_CREATED), {"admin1", "admin2"})

    def test_converted_goes_to_the_owner_and_other_admins(self) -> None:
        lead_services.convert_lead(actor=self.admin, lead=self.lead)
        self.assertEqual(recipients(NotificationType.LEAD_CONVERTED), {"manager1", "admin2"})
        alert = Notification.objects.filter(notification_type=NotificationType.LEAD_CONVERTED).first()
        self.lead.refresh_from_db()
        self.assertEqual(alert.applicant_id, self.lead.converted_applicant_id)
        self.assertEqual(alert.payload["applicant_id"], str(self.lead.converted_applicant_id))
        self.assertEqual(alert.source_api_path, f"/api/v1/leads/{self.lead.id}/")

    def test_deleted_and_restored_by_the_owner_tell_only_the_admins(self) -> None:
        lead_services.delete_lead(actor=self.manager, lead=self.lead, reason="Duplicate enquiry.")
        lead_services.restore_lead(actor=self.manager, lead=self.lead)
        self.assertEqual(recipients(NotificationType.LEAD_DELETED), {"admin1", "admin2"})
        self.assertEqual(recipients(NotificationType.LEAD_RESTORED), {"admin1", "admin2"})
        self.assertNotIn(
            "Duplicate",
            Notification.objects.get(notification_type=NotificationType.LEAD_DELETED, recipient=self.admin).body,
        )

    def test_deleting_twice_raises_two_alerts(self) -> None:
        lead_services.delete_lead(actor=self.admin, lead=self.lead, reason="x")
        lead_services.restore_lead(actor=self.admin, lead=self.lead)
        lead_services.delete_lead(actor=self.admin, lead=self.lead, reason="y")
        self.assertEqual(
            Notification.objects.filter(
                notification_type=NotificationType.LEAD_DELETED, recipient=self.manager
            ).count(),
            2,
        )

    def test_visit_note_tells_the_owner_and_general_notes_nobody(self) -> None:
        lead_services.add_note(
            actor=self.admin, lead=self.lead, body="Came in with parents.", category=NoteCategory.VISIT
        )
        lead_services.add_note(actor=self.admin, lead=self.lead, body="Called back.", category=NoteCategory.GENERAL)
        self.assertEqual(recipients(NotificationType.VISIT_NOTE_ADDED), {"manager1"})
        alert = Notification.objects.get(notification_type=NotificationType.VISIT_NOTE_ADDED)
        self.assertNotIn("parents", alert.title + alert.body)
        # A note has no GET of its own; the link is the notes feed.
        self.assertEqual(alert.source_api_path, f"/api/v1/leads/{self.lead.id}/notes/")
        self.assertIn("note_id", alert.payload)

    def test_owner_writing_their_own_visit_note_is_not_told(self) -> None:
        lead_services.add_note(actor=self.manager, lead=self.lead, body="Visit.", category=NoteCategory.VISIT)
        self.assertEqual(recipients(NotificationType.VISIT_NOTE_ADDED), set())


class ApplicantEventTests(_Team):
    def setUp(self) -> None:
        super().setUp()
        self.applicant = make_applicant(self.admin)

    def change(self, status: str, actor: Any = None) -> None:
        applicant_services.change_status(actor=actor or self.admin, applicant=self.applicant, status=status)

    def test_unassigned_status_change_goes_to_the_whole_team_except_the_actor(self) -> None:
        self.change(ApplicantStatus.DORMANT)
        self.assertEqual(recipients(NotificationType.APPLICANT_STATUS_CHANGED), {"admin2", "manager1", "manager2"})
        alert = Notification.objects.filter(notification_type=NotificationType.APPLICANT_STATUS_CHANGED).first()
        self.assertEqual((alert.payload["from"], alert.payload["to"]), ("active", "dormant"))
        self.assertEqual(alert.applicant_id, self.applicant.id)

    def test_assigned_status_change_goes_to_the_assignee_and_admins(self) -> None:
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager)
        self.change(ApplicantStatus.DORMANT)
        self.assertEqual(recipients(NotificationType.APPLICANT_STATUS_CHANGED), {"admin2", "manager1"})

    def test_restore(self) -> None:
        self.change(ApplicantStatus.ARCHIVED)
        applicant_services.restore_applicant(actor=self.admin, applicant=self.applicant)
        self.assertEqual(recipients(NotificationType.APPLICANT_RESTORED), {"admin2", "manager1", "manager2"})

    def test_visit_note_goes_to_the_assignee_only_or_everyone(self) -> None:
        applicant_services.add_note(
            actor=self.manager, applicant=self.applicant, body="Visit.", category=NoteCategory.VISIT
        )
        self.assertEqual(recipients(NotificationType.VISIT_NOTE_ADDED), {"admin1", "admin2", "manager2"})
        Notification.objects.all().delete()

        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager2)
        Notification.objects.all().delete()
        applicant_services.add_note(
            actor=self.manager, applicant=self.applicant, body="Visit again.", category=NoteCategory.VISIT
        )
        self.assertEqual(recipients(NotificationType.VISIT_NOTE_ADDED), {"manager2"})

    def test_deactivated_assignee_falls_back_to_the_whole_team(self) -> None:
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager2)
        self.manager2.is_active = False
        self.manager2.save(update_fields=["is_active"])
        applicant_services.add_note(
            actor=self.manager, applicant=self.applicant, body="Visit.", category=NoteCategory.VISIT
        )
        self.assertEqual(recipients(NotificationType.VISIT_NOTE_ADDED), {"admin1", "admin2"})

    def test_assignment_tells_the_new_and_previous_assignee(self) -> None:
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager)
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager2)
        self.assertEqual(recipients(NotificationType.APPLICANT_ASSIGNED), {"manager1", "manager2"})
        self.assertEqual(recipients(NotificationType.APPLICANT_UNASSIGNED), {"manager1"})

    def test_losing_an_applicant_is_told_even_with_assigned_only(self) -> None:
        from notifications.services import update_preferences

        update_preferences(self.manager, assigned_only=True)
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager)
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager2)
        self.assertEqual(recipients(NotificationType.APPLICANT_UNASSIGNED), {"manager1"})

    def test_taking_it_yourself_tells_nobody(self) -> None:
        applicant_services.assign_applicant(actor=self.manager, applicant=self.applicant, assignee=self.manager)
        self.assertEqual(recipients(NotificationType.APPLICANT_ASSIGNED), set())

    def test_converted_applicant_carries_its_lead(self) -> None:
        lead = make_lead(self.manager, make_source())
        lead_services.convert_lead(actor=self.admin, lead=lead)
        lead.refresh_from_db()
        applicant_services.change_status(
            actor=self.admin, applicant=lead.converted_applicant, status=ApplicantStatus.DORMANT
        )
        alert = Notification.objects.filter(
            notification_type=NotificationType.APPLICANT_STATUS_CHANGED, applicant_id=lead.converted_applicant_id
        ).first()
        self.assertEqual(alert.payload["originating_lead_id"], str(lead.id))
        # The converted applicant is assigned to the lead's owner, so only they and the Admins hear.
        self.assertEqual(
            set(
                Notification.objects.filter(
                    notification_type=NotificationType.APPLICANT_STATUS_CHANGED,
                    applicant_id=lead.converted_applicant_id,
                ).values_list("recipient__username", flat=True)
            ),
            {"admin2", "manager1"},
        )


class JourneyRoutingTests(_Team):
    """The older journey alerts keep Admin routing; an assignee is added, Lead Managers are not."""

    def setUp(self) -> None:
        super().setUp()
        self.applicant = make_applicant(self.admin)

    def test_unassigned_journey_alerts_stay_admin_only(self) -> None:
        make_journey(self.admin, self.applicant)
        self.assertEqual(recipients(NotificationType.JOURNEY_STAGE_CHANGED), {"admin1", "admin2"})

    def test_assigned_journey_alerts_add_the_assignee(self) -> None:
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager)
        journey = make_journey(self.admin, self.applicant)
        journey_services.change_stage(actor=self.admin, journey=journey, stage=JourneyStage.SHORTLISTING)
        alerts = Notification.objects.filter(
            notification_type=NotificationType.JOURNEY_STAGE_CHANGED, payload__stage=JourneyStage.SHORTLISTING
        )
        self.assertEqual(set(alerts.values_list("recipient__username", flat=True)), {"admin1", "admin2", "manager1"})


class DocumentEventTests(_Team):
    def test_ready_tells_the_other_admins_only(self) -> None:
        applicant = make_applicant(self.admin)
        applicant_services.assign_applicant(actor=self.admin, applicant=applicant, assignee=self.manager)
        document = make_document(self.admin, applicant)
        document_services.change_status(actor=self.admin, document=document, status=DocumentStatus.READY)
        self.assertEqual(recipients(NotificationType.DOCUMENT_READY), {"admin2"})
        document_services.change_status(actor=self.admin, document=document, status=DocumentStatus.DRAFT)
        self.assertEqual(Notification.objects.filter(notification_type=NotificationType.DOCUMENT_READY).count(), 1)
