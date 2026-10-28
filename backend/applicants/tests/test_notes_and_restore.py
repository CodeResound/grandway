"""Applicant notes and the Admin-only restore (2026-10-29, frontend ``updates.md`` §2, §3.2).

* Admins and Lead Managers read and write notes on any applicant, like the
  rest of the record; the author or an Admin corrects or removes one.
* An archived applicant's notes are readable but frozen.
* Leaving ``archived`` is a restore, Admin-only, back to the prior status —
  ``status/`` can archive but no longer un-archive.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from audit.models import AuditEvent
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from applicants import services
from applicants.constants import ApplicantAuditAction, ApplicantStatus, ErrorCode
from applicants.models import ApplicantNote
from applicants.tests.factories import make_admin, make_applicant, make_lead_manager, token_for


class ApplicantApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.other_manager = make_lead_manager("othermgr")
        self.applicant = make_applicant(self.admin)

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def url(self, name: str, *extra: Any) -> str:
        return reverse(f"v1:applicants:{name}", args=[self.applicant.id, *extra])

    def assert_error(self, response: Any, http_status: int, code: str) -> None:
        self.assertEqual(response.status_code, http_status, response.content)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("details", body["error"])
        self.assertIn("meta", body)


class TestApplicantNotes(ApplicantApiTestCase):
    def post_note(self, user: Any, **payload: Any) -> Any:
        self.auth(user)
        return self.client.post(self.url("applicant-note-list"), {"body": "Visited office.", **payload}, format="json")

    def test_lead_manager_writes_and_reads(self) -> None:
        response = self.post_note(self.manager, category="visit")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()["data"]
        self.assertEqual((data["category"], data["author"]["username"]), ("visit", "leadmgr"))
        self.assertIsNone(data["source_lead_id"])

        body = self.client.get(self.url("applicant-note-list")).json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["meta"]["counts"], {"general": 0, "visit": 1})

    def test_backdated_and_future(self) -> None:
        response = self.post_note(self.manager, noted_at=(timezone.now() - timedelta(days=1)).isoformat())
        self.assertTrue(response.json()["data"]["is_backdated"])
        response = self.post_note(self.manager, noted_at=(timezone.now() + timedelta(hours=2)).isoformat())
        self.assert_error(response, 400, ErrorCode.NOTE_FUTURE_DATE)

    def test_audit_lands_on_the_applicant_history(self) -> None:
        self.post_note(self.manager, body="Private detail")
        event = AuditEvent.objects.get(action=ApplicantAuditAction.APPLICANT_NOTE_ADDED)
        self.assertEqual(str(event.entity_id), str(self.applicant.id))
        self.assertNotIn("Private", str(event.metadata) + event.summary)
        history = self.client.get(self.url("applicant-history")).json()["data"]
        self.assertIn(ApplicantAuditAction.APPLICANT_NOTE_ADDED, [row["action"] for row in history])

    def test_author_or_admin_only(self) -> None:
        note = services.add_note(actor=self.manager, applicant=self.applicant, body="Mine")
        detail = self.url("applicant-note-detail", note.id)

        self.auth(self.other_manager)
        self.assert_error(self.client.patch(detail, {"body": "x"}, format="json"), 403, ErrorCode.NOTE_FORBIDDEN)
        self.assert_error(self.client.delete(detail), 403, ErrorCode.NOTE_FORBIDDEN)

        self.auth(self.manager)
        self.assertEqual(self.client.patch(detail, {"body": "Edited"}, format="json").status_code, 200)

        self.auth(self.admin)
        self.assertEqual(self.client.delete(detail).status_code, 200)
        self.assertTrue(ApplicantNote.objects.filter(pk=note.pk, deleted_at__isnull=False).exists())
        self.assert_error(self.client.delete(detail), 404, ErrorCode.NOTE_NOT_FOUND)

    def test_filters_and_ordering(self) -> None:
        now = timezone.now()
        services.add_note(actor=self.admin, applicant=self.applicant, body="Old", noted_at=now - timedelta(days=9))
        services.add_note(actor=self.admin, applicant=self.applicant, body="Visit", category="visit", noted_at=now)
        self.auth(self.admin)
        rows = self.client.get(self.url("applicant-note-list")).json()["data"]
        self.assertEqual([r["body"] for r in rows], ["Visit", "Old"])
        rows = self.client.get(self.url("applicant-note-list"), {"category": "general"}).json()["data"]
        self.assertEqual([r["body"] for r in rows], ["Old"])
        rows = self.client.get(self.url("applicant-note-list"), {"ordering": "noted_at"}).json()["data"]
        self.assertEqual([r["body"] for r in rows], ["Old", "Visit"])

    def test_archived_applicant_notes_are_read_only(self) -> None:
        note = services.add_note(actor=self.manager, applicant=self.applicant, body="Before archive")
        services.change_status(actor=self.admin, applicant=self.applicant, status=ApplicantStatus.ARCHIVED)
        self.assert_error(self.post_note(self.manager), 409, ErrorCode.APPLICANT_ARCHIVED)
        detail = self.url("applicant-note-detail", note.id)
        self.assert_error(self.client.patch(detail, {"body": "x"}, format="json"), 409, ErrorCode.APPLICANT_ARCHIVED)
        self.assertEqual(len(self.client.get(self.url("applicant-note-list")).json()["data"]), 1)

    def test_missing_applicant(self) -> None:
        self.auth(self.admin)
        url = reverse("v1:applicants:applicant-note-list", args=["2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819"])
        self.assert_error(self.client.get(url), 404, ErrorCode.APPLICANT_NOT_FOUND)

    def test_import_keeps_original_creation_time(self) -> None:
        then = timezone.now() - timedelta(days=30)
        created = services.import_lead_notes(
            actor=self.admin,
            applicant=self.applicant,
            lead_id="3c4d5e6f-7081-4920-b3c4-d5e6f7081920",
            notes=[
                {
                    "category": "general",
                    "body": "From lead",
                    "noted_at": then,
                    "author": self.manager,
                    "created_at": then,
                }
            ],
        )
        note = ApplicantNote.objects.get(pk=created[0].pk)
        self.assertEqual(note.created_at, then)
        self.assertEqual(str(note.source_lead_id), "3c4d5e6f-7081-4920-b3c4-d5e6f7081920")
        event = AuditEvent.objects.get(action=ApplicantAuditAction.APPLICANT_NOTES_IMPORTED)
        self.assertEqual(event.metadata["count"], 1)

    def test_import_of_nothing_writes_nothing(self) -> None:
        services.import_lead_notes(actor=self.admin, applicant=self.applicant, lead_id="x", notes=[])
        self.assertFalse(AuditEvent.objects.filter(action=ApplicantAuditAction.APPLICANT_NOTES_IMPORTED).exists())


class TestApplicantRestore(ApplicantApiTestCase):
    def archive(self, from_status: str = ApplicantStatus.ACTIVE) -> None:
        if from_status != ApplicantStatus.ACTIVE:
            services.change_status(actor=self.admin, applicant=self.applicant, status=from_status)
        services.change_status(actor=self.manager, applicant=self.applicant, status=ApplicantStatus.ARCHIVED)
        self.applicant.refresh_from_db()

    def test_archiving_remembers_the_prior_status(self) -> None:
        self.archive(ApplicantStatus.DORMANT)
        self.assertEqual(self.applicant.status_before_archive, ApplicantStatus.DORMANT)

    def test_admin_restores_to_prior_status(self) -> None:
        self.archive(ApplicantStatus.DORMANT)
        self.auth(self.admin)
        response = self.client.post(self.url("applicant-restore"), {"reason": "Came back."}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], ApplicantStatus.DORMANT)
        event = AuditEvent.objects.get(action=ApplicantAuditAction.APPLICANT_RESTORED)
        self.assertEqual((event.reason, event.changes["status"]["to"]), ("Came back.", ApplicantStatus.DORMANT))

    def test_restore_falls_back_to_active(self) -> None:
        self.archive()
        self.applicant.status_before_archive = ""
        self.applicant.save(update_fields=["status_before_archive"])
        self.auth(self.admin)
        response = self.client.post(self.url("applicant-restore"), {}, format="json")
        self.assertEqual(response.json()["data"]["status"], ApplicantStatus.ACTIVE)

    def test_lead_manager_cannot_restore(self) -> None:
        self.archive()
        self.auth(self.manager)
        self.assert_error(
            self.client.post(self.url("applicant-restore"), {}, format="json"), 403, ErrorCode.ACTOR_FORBIDDEN
        )

    def test_status_endpoint_no_longer_unarchives(self) -> None:
        self.archive()
        for user in (self.manager, self.admin):
            with self.subTest(user=user.username):
                self.auth(user)
                response = self.client.post(self.url("applicant-status"), {"status": "active"}, format="json")
                self.assert_error(response, 409, ErrorCode.APPLICANT_ARCHIVED)

    def test_status_endpoint_still_archives(self) -> None:
        self.auth(self.manager)
        response = self.client.post(self.url("applicant-status"), {"status": "archived"}, format="json")
        self.assertEqual(response.json()["data"]["status"], ApplicantStatus.ARCHIVED)

    def test_restoring_an_active_applicant_conflicts(self) -> None:
        self.auth(self.admin)
        response = self.client.post(self.url("applicant-restore"), {}, format="json")
        self.assert_error(response, 409, ErrorCode.APPLICANT_NOT_ARCHIVED)
