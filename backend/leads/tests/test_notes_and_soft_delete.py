"""Categorised, backdatable, correctable notes, and lead soft delete (2026-10-29).

Frontend ``updates.md`` §2 and §3.1. What these tests guard:

* notes carry a category and a user-set ``noted_at``; the future is refused;
* only the author or an Admin may change a note, and a deleted note leaves the
  feed but not the database or the audit log;
* a converted lead's notes are read-only here and continue on the applicant;
* a deleted lead is invisible to Lead Managers, frozen for everyone, and drops
  out of the selectors that feed search and dashboards.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from applicants.models import ApplicantNote
from audit.models import AuditEvent
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from leads import services
from leads.constants import ErrorCode, LeadAuditAction
from leads.models import Lead, LeadNote
from leads.selectors import get_lead_funnel_counts, get_leads_for_actor
from leads.tests.factories import (
    make_admin,
    make_lead,
    make_lead_manager,
    make_loss_reason,
    make_source,
    token_for,
)


class LeadsApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.other = make_lead_manager("other")
        self.source = make_source()
        self.lead = make_lead(self.owner, self.source)

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def url(self, name: str, *extra: Any) -> str:
        return reverse(f"v1:leads:{name}", args=[self.lead.id, *extra])

    def notes_url(self) -> str:
        return self.url("lead-note-list")

    def note_url(self, note: LeadNote) -> str:
        return self.url("lead-note-detail", note.id)

    def add_note(self, user: Any, **payload: Any) -> Any:
        self.auth(user)
        return self.client.post(self.notes_url(), {"body": "Called, will visit.", **payload}, format="json")

    def assert_error(self, response: Any, http_status: int, code: str) -> dict[str, Any]:
        self.assertEqual(response.status_code, http_status, response.content)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("details", body["error"])
        return body


class TestNoteWrites(LeadsApiTestCase):
    def test_defaults_general_and_now(self) -> None:
        response = self.add_note(self.owner)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()["data"]
        self.assertEqual(data["category"], "general")
        self.assertFalse(data["is_backdated"])
        self.assertIsNotNone(data["noted_at_bs"])
        self.assertEqual(data["author"]["username"], "owner")

    def test_backdated_visit_note(self) -> None:
        when = timezone.now() - timedelta(days=2)
        response = self.add_note(self.owner, category="visit", noted_at=when.isoformat())
        data = response.json()["data"]
        self.assertEqual(data["category"], "visit")
        self.assertTrue(data["is_backdated"])

    def test_naive_noted_at_is_read_as_nepal_time(self) -> None:
        response = self.add_note(self.owner, noted_at="2026-01-10T10:00")
        self.assertEqual(response.json()["data"]["noted_at"], "2026-01-10T04:15:00Z")

    def test_future_noted_at_is_refused(self) -> None:
        response = self.add_note(self.owner, noted_at=(timezone.now() + timedelta(hours=1)).isoformat())
        self.assert_error(response, status.HTTP_400_BAD_REQUEST, ErrorCode.NOTE_FUTURE_DATE)

    def test_small_clock_skew_is_tolerated(self) -> None:
        response = self.add_note(self.owner, noted_at=(timezone.now() + timedelta(minutes=2)).isoformat())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_blank_body_is_refused(self) -> None:
        response = self.add_note(self.owner, body="   ")
        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")

    def test_service_refuses_blank_body_and_reason(self) -> None:
        from leads.exceptions import DeleteReasonRequiredError, NoteBodyRequiredError

        with self.assertRaises(NoteBodyRequiredError):
            services.add_note(actor=self.owner, lead=self.lead, body=" \n ")
        with self.assertRaises(DeleteReasonRequiredError):
            services.delete_lead(actor=self.admin, lead=self.lead, reason="  ")

    def test_body_over_limit_is_refused(self) -> None:
        response = self.add_note(self.owner, body="x" * 10_001)
        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")

    def test_bad_category_is_refused(self) -> None:
        response = self.add_note(self.owner, category="call")
        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")

    def test_audit_records_metadata_not_body(self) -> None:
        self.add_note(self.owner, body="Secret family situation", category="visit")
        event = AuditEvent.objects.get(action=LeadAuditAction.LEAD_NOTE_ADDED, entity_id=str(self.lead.id))
        self.assertEqual(event.metadata["category"], "visit")
        self.assertNotIn("Secret", str(event.metadata) + str(event.changes) + event.summary)

    def test_follow_up_note_still_written(self) -> None:
        self.auth(self.owner)
        self.client.post(self.url("lead-follow-up"), {"note": "Rang back."}, format="json")
        self.assertEqual(LeadNote.objects.get(lead=self.lead).category, "general")


class TestNoteFeed(LeadsApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        now = timezone.now()
        self.old_visit = services.add_note(
            actor=self.owner, lead=self.lead, body="Visit", category="visit", noted_at=now - timedelta(days=3)
        )
        self.recent = services.add_note(actor=self.owner, lead=self.lead, body="Recent", noted_at=now)
        self.gone = services.add_note(actor=self.owner, lead=self.lead, body="Gone")
        services.delete_note(actor=self.owner, lead=self.lead, note=self.gone)
        self.auth(self.owner)

    def test_newest_noted_at_first_and_deleted_hidden(self) -> None:
        body = self.client.get(self.notes_url()).json()
        self.assertEqual([n["body"] for n in body["data"]], ["Recent", "Visit"])
        self.assertEqual(body["meta"]["counts"], {"general": 1, "visit": 1})
        self.assertEqual(body["meta"]["count"], 2)

    def test_category_filter_keeps_both_counts(self) -> None:
        body = self.client.get(self.notes_url(), {"category": "visit"}).json()
        self.assertEqual([n["body"] for n in body["data"]], ["Visit"])
        self.assertEqual(body["meta"]["counts"], {"general": 1, "visit": 1})

    def test_ordering(self) -> None:
        body = self.client.get(self.notes_url(), {"ordering": "noted_at"}).json()
        self.assertEqual([n["body"] for n in body["data"]], ["Visit", "Recent"])

    def test_bad_ordering_is_refused(self) -> None:
        self.assertEqual(self.client.get(self.notes_url(), {"ordering": "body"}).status_code, 400)

    def test_deleted_note_row_is_kept(self) -> None:
        self.assertTrue(LeadNote.objects.filter(pk=self.gone.pk, deleted_at__isnull=False).exists())


class TestNoteCorrections(LeadsApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.note = services.add_note(actor=self.owner, lead=self.lead, body="Typo here")

    def test_author_edits(self) -> None:
        self.auth(self.owner)
        response = self.client.patch(self.note_url(self.note), {"body": "Fixed", "category": "visit"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual((data["body"], data["category"]), ("Fixed", "visit"))
        self.assertEqual(data["updated_by"]["username"], "owner")
        event = AuditEvent.objects.get(action=LeadAuditAction.LEAD_NOTE_UPDATED)
        self.assertEqual(event.changes["body"], {"from": "<changed>", "to": "<changed>"})
        self.assertEqual(event.changes["category"], {"from": "general", "to": "visit"})

    def test_admin_edits_anyones_note(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.note_url(self.note), {"body": "Moderated"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_author_lead_manager_is_refused(self) -> None:
        # Another manager cannot even see this lead, so make them its author's
        # peer on a lead they own: the owner writes, an Admin-created note is foreign.
        admin_note = services.add_note(actor=self.admin, lead=self.lead, body="Admin's note")
        self.auth(self.owner)
        response = self.client.patch(self.note_url(admin_note), {"body": "Mine now"}, format="json")
        self.assert_error(response, status.HTTP_403_FORBIDDEN, ErrorCode.NOTE_FORBIDDEN)
        response = self.client.delete(self.note_url(admin_note))
        self.assert_error(response, status.HTTP_403_FORBIDDEN, ErrorCode.NOTE_FORBIDDEN)

    def test_other_managers_lead_is_not_found(self) -> None:
        self.auth(self.other)
        response = self.client.patch(self.note_url(self.note), {"body": "x"}, format="json")
        self.assert_error(response, status.HTTP_404_NOT_FOUND, ErrorCode.LEAD_NOT_FOUND)

    def test_edit_to_future_is_refused(self) -> None:
        self.auth(self.owner)
        later = (timezone.now() + timedelta(days=1)).isoformat()
        response = self.client.patch(self.note_url(self.note), {"noted_at": later}, format="json")
        self.assert_error(response, status.HTTP_400_BAD_REQUEST, ErrorCode.NOTE_FUTURE_DATE)

    def test_no_op_edit_writes_no_event(self) -> None:
        self.auth(self.owner)
        self.client.patch(self.note_url(self.note), {"body": "Typo here"}, format="json")
        self.assertFalse(AuditEvent.objects.filter(action=LeadAuditAction.LEAD_NOTE_UPDATED).exists())

    def test_delete_then_not_found(self) -> None:
        self.auth(self.owner)
        response = self.client.delete(self.note_url(self.note))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(AuditEvent.objects.filter(action=LeadAuditAction.LEAD_NOTE_DELETED).exists())
        response = self.client.patch(self.note_url(self.note), {"body": "x"}, format="json")
        self.assert_error(response, status.HTTP_404_NOT_FOUND, ErrorCode.NOTE_NOT_FOUND)


class TestConvertedLeadNotes(LeadsApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.created_at_before = timezone.now() - timedelta(days=5)
        self.note = services.add_note(
            actor=self.owner,
            lead=self.lead,
            body="Interested in Japan",
            category="visit",
            noted_at=timezone.now() - timedelta(days=6),
        )
        LeadNote.objects.filter(pk=self.note.pk).update(created_at=self.created_at_before)
        gone = services.add_note(actor=self.owner, lead=self.lead, body="Removed note")
        services.delete_note(actor=self.owner, lead=self.lead, note=gone)
        services.convert_lead(actor=self.admin, lead=self.lead)
        self.lead.refresh_from_db()

    def test_notes_are_copied_to_the_applicant(self) -> None:
        copies = ApplicantNote.objects.filter(applicant_id=self.lead.converted_applicant_id)
        self.assertEqual(copies.count(), 1)
        copy = copies.get()
        self.assertEqual(
            (copy.body, copy.category, copy.author_id, copy.source_lead_id),
            ("Interested in Japan", "visit", self.owner.id, self.lead.id),
        )
        self.assertEqual(copy.noted_at, self.note.noted_at)
        self.assertEqual(copy.created_at, self.created_at_before)

    def test_lead_notes_stay_readable(self) -> None:
        self.auth(self.owner)
        self.assertEqual(len(self.client.get(self.notes_url()).json()["data"]), 1)

    def test_lead_note_writes_are_refused(self) -> None:
        response = self.add_note(self.owner)
        self.assert_error(response, status.HTTP_409_CONFLICT, ErrorCode.LEAD_ALREADY_CONVERTED)
        response = self.client.patch(self.note_url(self.note), {"body": "x"}, format="json")
        self.assert_error(response, status.HTTP_409_CONFLICT, ErrorCode.LEAD_ALREADY_CONVERTED)

    def test_follow_up_note_on_reopened_converted_lead_is_refused(self) -> None:
        services.reopen_lead(actor=self.admin, lead=self.lead)
        self.auth(self.owner)
        response = self.client.post(self.url("lead-follow-up"), {"note": "x"}, format="json")
        self.assert_error(response, status.HTTP_409_CONFLICT, ErrorCode.LEAD_ALREADY_CONVERTED)


class TestLeadSoftDelete(LeadsApiTestCase):
    def delete(self, user: Any, reason: str = "Duplicate enquiry.") -> Any:
        self.auth(user)
        return self.client.delete(self.url("lead-detail"), {"reason": reason}, format="json")

    def test_admin_deletes_with_reason(self) -> None:
        response = self.delete(self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIsNotNone(data["deleted_at"])
        self.assertIsNotNone(data["deleted_at_bs"])
        self.assertEqual((data["delete_reason"], data["deleted_by"]["username"]), ("Duplicate enquiry.", "adminuser"))
        event = AuditEvent.objects.get(action=LeadAuditAction.LEAD_DELETED)
        self.assertEqual(event.reason, "Duplicate enquiry.")

    def test_reason_is_required(self) -> None:
        self.assert_error(self.delete(self.admin, reason="  "), 400, "VALIDATION_ERROR")
        self.auth(self.admin)
        response = self.client.delete(self.url("lead-detail"), {}, format="json")
        self.assert_error(response, 400, "VALIDATION_ERROR")

    def test_owner_lead_manager_is_forbidden(self) -> None:
        self.assert_error(self.delete(self.owner), 403, ErrorCode.ACTOR_FORBIDDEN)

    def test_other_lead_manager_gets_not_found(self) -> None:
        self.assert_error(self.delete(self.other), 404, ErrorCode.LEAD_NOT_FOUND)

    def test_converted_lead_cannot_be_deleted(self) -> None:
        services.convert_lead(actor=self.admin, lead=self.lead)
        self.assert_error(self.delete(self.admin), 409, ErrorCode.LEAD_ALREADY_CONVERTED)

    def test_deleting_twice_conflicts(self) -> None:
        self.delete(self.admin)
        self.assert_error(self.delete(self.admin), 409, ErrorCode.LEAD_DELETED)

    def test_visibility_after_delete(self) -> None:
        self.delete(self.admin)
        lead_list = reverse("v1:leads:lead-list")

        self.auth(self.owner)
        self.assertEqual(self.client.get(lead_list).json()["data"], [])
        self.assert_error(self.client.get(self.url("lead-detail")), 404, ErrorCode.LEAD_NOT_FOUND)
        self.assert_error(self.client.get(lead_list, {"deleted": "true"}), 403, ErrorCode.ACTOR_FORBIDDEN)

        self.auth(self.admin)
        self.assertEqual(self.client.get(lead_list).json()["data"], [])
        deleted = self.client.get(lead_list, {"deleted": "true"}).json()["data"]
        self.assertEqual([row["id"] for row in deleted], [str(self.lead.id)])
        detail = self.client.get(self.url("lead-detail"))
        self.assertEqual(detail.status_code, 200)
        self.assertIsNotNone(detail.json()["data"]["deleted_at"])
        self.assertEqual(self.client.get(self.url("lead-history")).status_code, 200)

    def test_every_write_is_frozen(self) -> None:
        note = services.add_note(actor=self.admin, lead=self.lead, body="Before delete")
        loss = make_loss_reason()
        self.delete(self.admin)
        self.auth(self.admin)
        writes = [
            ("patch", self.url("lead-detail"), {"full_name": "New"}),
            ("post", self.url("lead-stage"), {"stage": "contacted"}),
            ("post", self.url("lead-follow-up"), {}),
            ("post", self.url("lead-lost"), {"loss_reason": str(loss.id)}),
            ("post", self.url("lead-convert"), {}),
            ("post", self.notes_url(), {"body": "x"}),
            ("patch", self.note_url(note), {"body": "x"}),
            ("delete", self.note_url(note), None),
        ]
        for method, url, payload in writes:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, payload, format="json")
                self.assert_error(response, 409, ErrorCode.LEAD_DELETED)

    def test_reopen_is_frozen(self) -> None:
        services.mark_lost(actor=self.admin, lead=self.lead, loss_reason=make_loss_reason())
        self.delete(self.admin)
        self.auth(self.admin)
        self.assert_error(self.client.post(self.url("lead-reopen"), {}, format="json"), 409, ErrorCode.LEAD_DELETED)

    def test_restore(self) -> None:
        self.delete(self.admin)
        self.auth(self.owner)
        self.assert_error(self.client.post(self.url("lead-restore"), {}, format="json"), 404, ErrorCode.LEAD_NOT_FOUND)
        self.auth(self.admin)
        response = self.client.post(self.url("lead-restore"), {"reason": "Not a duplicate."}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIsNone(data["deleted_at"])
        self.assertEqual(data["delete_reason"], "")
        self.assertEqual(AuditEvent.objects.get(action=LeadAuditAction.LEAD_RESTORED).reason, "Not a duplicate.")
        self.auth(self.owner)
        self.assertEqual(self.client.get(self.url("lead-detail")).status_code, 200)

    def test_owner_cannot_restore_even_if_visible(self) -> None:
        self.auth(self.owner)
        response = self.client.post(self.url("lead-restore"), {}, format="json")
        self.assert_error(response, 403, ErrorCode.ACTOR_FORBIDDEN)

    def test_restoring_a_live_lead_conflicts(self) -> None:
        self.auth(self.admin)
        response = self.client.post(self.url("lead-restore"), {}, format="json")
        self.assert_error(response, 409, ErrorCode.LEAD_NOT_DELETED)

    def test_deleted_lead_leaves_search_and_dashboard_selectors(self) -> None:
        before = sum(get_lead_funnel_counts(actor=self.admin).values())
        services.delete_lead(actor=self.admin, lead=self.lead, reason="Spam.")
        self.assertFalse(get_leads_for_actor(self.admin).filter(pk=self.lead.pk).exists())
        self.assertEqual(sum(get_lead_funnel_counts(actor=self.admin).values()), before - 1)
        self.assertTrue(get_leads_for_actor(self.admin, deleted=True).filter(pk=self.lead.pk).exists())

    def test_admin_cannot_hard_delete(self) -> None:
        from django.contrib import admin as django_admin

        model_admin = django_admin.site._registry[Lead]
        self.assertFalse(model_admin.has_delete_permission(request=None))
