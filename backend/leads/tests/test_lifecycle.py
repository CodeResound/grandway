"""Stage transitions, follow-up, loss, reopening, notes, and history."""

from __future__ import annotations

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from leads.constants import ErrorCode, LeadAuditAction, LeadStage
from leads.models import Lead
from leads.tests.factories import (
    make_admin,
    make_lead,
    make_lead_manager,
    make_loss_reason,
    make_source,
    token_for,
)


class LifecycleTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.source = make_source()
        self.reason = make_loss_reason()
        self.lead = make_lead(self.owner, self.source)
        self.auth(self.owner)

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def url(self, name: str) -> str:
        return reverse(f"v1:leads:{name}", args=[self.lead.id])


class TestStageChange(LifecycleTestCase):
    def test_moves_between_active_stages(self) -> None:
        resp = self.client.post(self.url("lead-stage"), {"stage": LeadStage.CONTACTED}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["stage"], LeadStage.CONTACTED)

    def test_lost_cannot_be_selected_from_the_dropdown(self) -> None:
        """Closing a lead demands a reason, so ``lost`` is not a selectable stage."""
        resp = self.client.post(self.url("lead-stage"), {"stage": LeadStage.LOST}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("stage", resp.data["error"]["details"])

    def test_converted_cannot_be_selected_from_the_dropdown(self) -> None:
        """Conversion is a deliberate Admin action, not a stage pick."""
        resp = self.client.post(self.url("lead-stage"), {"stage": LeadStage.CONVERTED}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stage_frozen_once_lost(self) -> None:
        self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        resp = self.client.post(self.url("lead-stage"), {"stage": LeadStage.CONTACTED}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.STAGE_NOT_EDITABLE)


class TestFollowUp(LifecycleTestCase):
    def test_records_who_and_when(self) -> None:
        resp = self.client.post(self.url("lead-follow-up"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertIsNotNone(data["last_followed_up_at"])
        self.assertEqual(data["last_followed_up_by"]["username"], "owner")

    def test_exposes_bikram_sambat_companion(self) -> None:
        """User-facing dates carry a BS projection alongside the Gregorian value (§39.4)."""
        resp = self.client.post(self.url("lead-follow-up"), {}, format="json")
        bs = resp.data["data"]["last_followed_up_at_bs"]
        self.assertIsNotNone(bs)
        for key in ("year", "month", "day", "month_name_en", "month_name_np", "display_en", "display_np"):
            self.assertIn(key, bs)

    def test_optional_note_and_stage_change_apply_together(self) -> None:
        resp = self.client.post(
            self.url("lead-follow-up"),
            {"note": "Called, will decide next week.", "stage": LeadStage.COUNSELLING},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["stage"], LeadStage.COUNSELLING)

        notes = self.client.get(self.url("lead-note-list")).data["data"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["body"], "Called, will decide next week.")

    def test_blocked_on_a_lost_lead(self) -> None:
        self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        resp = self.client.post(self.url("lead-follow-up"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


class TestMarkLost(LifecycleTestCase):
    def test_records_reason_actor_and_previous_stage(self) -> None:
        self.client.post(self.url("lead-stage"), {"stage": LeadStage.COUNSELLING}, format="json")
        resp = self.client.post(
            self.url("lead-lost"),
            {"loss_reason": str(self.reason.id), "detail": "Chose to wait a year."},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["stage"], LeadStage.LOST)
        self.assertEqual(data["stage_before_loss"], LeadStage.COUNSELLING)
        self.assertEqual(data["lost_by"]["username"], "owner")
        self.assertEqual(data["lost_reason"]["code"], self.reason.code)
        self.assertIsNotNone(data["lost_at_bs"])

    def test_reason_is_mandatory(self) -> None:
        resp = self.client.post(self.url("lead-lost"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("loss_reason", resp.data["error"]["details"])

    def test_catch_all_reason_requires_an_explanation(self) -> None:
        other = make_loss_reason(code="other", requires_detail=True)
        resp = self.client.post(self.url("lead-lost"), {"loss_reason": str(other.id)}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.LOSS_DETAIL_REQUIRED)

    def test_cannot_be_lost_twice(self) -> None:
        self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        resp = self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_lead_and_history_survive_being_lost(self) -> None:
        self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())
        history = self.client.get(self.url("lead-history")).data["data"]
        self.assertIn(LeadAuditAction.LEAD_MARKED_LOST, [entry["action"] for entry in history])


class TestReopen(LifecycleTestCase):
    def test_defaults_to_follow_up_and_clears_loss_state(self) -> None:
        self.client.post(
            self.url("lead-lost"),
            {"loss_reason": str(self.reason.id), "detail": "No answer."},
            format="json",
        )
        resp = self.client.post(self.url("lead-reopen"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data["data"]
        self.assertEqual(data["stage"], LeadStage.FOLLOW_UP)
        self.assertIsNone(data["lost_reason"])
        self.assertIsNone(data["lost_at"])
        self.assertEqual(data["lost_detail"], "")

    def test_accepts_another_active_stage(self) -> None:
        self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        resp = self.client.post(self.url("lead-reopen"), {"stage": LeadStage.CONTACTED}, format="json")
        self.assertEqual(resp.data["data"]["stage"], LeadStage.CONTACTED)

    def test_active_lead_cannot_be_reopened(self) -> None:
        resp = self.client.post(self.url("lead-reopen"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.LEAD_NOT_LOST)

    def test_reopening_preserves_the_conversion_link(self) -> None:
        """Reopening a converted lead must not undo the conversion (no second applicant)."""
        from django.utils import timezone

        Lead.objects.filter(pk=self.lead.pk).update(
            stage=LeadStage.CONVERTED,
            converted_at=timezone.now(),
            converted_by=self.admin,
        )
        resp = self.client.post(self.url("lead-reopen"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage, LeadStage.FOLLOW_UP)
        self.assertIsNotNone(self.lead.converted_at)
        self.assertEqual(self.lead.converted_by_id, self.admin.id)


class TestNotesAndHistory(LifecycleTestCase):
    def test_note_records_author(self) -> None:
        resp = self.client.post(
            self.url("lead-note-list"),
            {"body": "Wants Australia, needs IELTS."},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["data"]["author"]["username"], "owner")

    def test_notes_have_no_edit_or_delete_route(self) -> None:
        self.client.post(self.url("lead-note-list"), {"body": "First"}, format="json")
        resp = self.client.delete(self.url("lead-note-list"))
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_history_records_the_whole_journey_in_order(self) -> None:
        self.client.post(self.url("lead-stage"), {"stage": LeadStage.CONTACTED}, format="json")
        self.client.post(self.url("lead-follow-up"), {"note": "Called."}, format="json")
        self.client.post(self.url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        self.client.post(self.url("lead-reopen"), {}, format="json")

        actions = [entry["action"] for entry in self.client.get(self.url("lead-history")).data["data"]]
        for expected in (
            LeadAuditAction.LEAD_CREATED,
            LeadAuditAction.LEAD_STAGE_CHANGED,
            LeadAuditAction.LEAD_FOLLOWUP_RECORDED,
            LeadAuditAction.LEAD_NOTE_ADDED,
            LeadAuditAction.LEAD_MARKED_LOST,
            LeadAuditAction.LEAD_REOPENED,
        ):
            self.assertIn(expected, actions)
        # Newest first.
        self.assertEqual(actions[0], LeadAuditAction.LEAD_REOPENED)

    def test_history_shape_is_unchanged_by_the_shared_serializer(self) -> None:
        """This endpoint's shape did not change when `audit` took ownership of it.

        Three of the six history endpoints gained `actor_id` in that move; this
        one already had every field, so its consumers see nothing new. Asserted
        as an exact set so a future widening of the shared shape cannot leak
        into this contract unnoticed.
        """
        entry = self.client.get(self.url("lead-history")).data["data"][0]
        self.assertEqual(
            set(entry),
            {
                "id",
                "action",
                "actor_type",
                "actor_id",
                "actor_label",
                "summary",
                "reason",
                "changes",
                "metadata",
                "created_at",
                "created_at_bs",
            },
        )

    def test_stage_change_history_carries_from_and_to(self) -> None:
        self.client.post(self.url("lead-stage"), {"stage": LeadStage.CONTACTED}, format="json")
        history = self.client.get(self.url("lead-history")).data["data"]
        entry = next(e for e in history if e["action"] == LeadAuditAction.LEAD_STAGE_CHANGED)
        self.assertEqual(entry["changes"]["stage"], {"from": LeadStage.NEW, "to": LeadStage.CONTACTED})

    def test_history_of_another_managers_lead_is_404(self) -> None:
        stranger = make_lead_manager("stranger")
        theirs = make_lead(stranger, self.source)
        resp = self.client.get(reverse("v1:leads:lead-history", args=[theirs.id]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
