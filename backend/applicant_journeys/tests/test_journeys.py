"""Journey endpoints: access, creation, stage rules, defer, close, reopen, history."""

from __future__ import annotations

from applicants.tests.factories import (
    make_admin,
    make_applicant,
    make_lead_manager,
    make_superadmin,
    token_for,
)
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from applicant_journeys import services
from applicant_journeys.constants import (
    CreationSource,
    ErrorCode,
    JourneyAuditAction,
    JourneyOutcome,
    JourneyStage,
)
from applicant_journeys.models import ApplicantJourney


class JourneyApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.superadmin = make_superadmin()
        self.applicant = make_applicant(self.admin)
        self.list_url = reverse("v1:journeys:journey-list")

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def make_journey(self, **overrides: object) -> ApplicantJourney:
        data = {"target_country": "Australia", "study_level": "masters", **overrides}
        return services.create_journey(actor=self.admin, applicant=self.applicant, data=data)

    def url(self, name: str, journey: ApplicantJourney) -> str:
        return reverse(f"v1:journeys:{name}", args=[journey.id])


class TestJourneyAccess(JourneyApiTestCase):
    def test_requires_authentication(self) -> None:
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_is_forbidden(self) -> None:
        self.auth(self.superadmin)
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_create_a_journey(self) -> None:
        """Unlike applicant creation, adding an objective is ordinary operational work."""
        self.auth(self.manager)
        resp = self.client.post(
            self.list_url,
            {"applicant": str(self.applicant.id), "target_country": "Canada"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_missing_journey_is_404(self) -> None:
        self.auth(self.manager)
        resp = self.client.get(reverse("v1:journeys:journey-detail", args=["00000000-0000-0000-0000-000000000000"]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.JOURNEY_NOT_FOUND)


class TestJourneyCreate(JourneyApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_creates_at_planning_stage(self) -> None:
        resp = self.client.post(
            self.list_url,
            {"applicant": str(self.applicant.id), "target_country": "Australia"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.data["data"]
        self.assertEqual(data["stage"], JourneyStage.PLANNING)
        self.assertEqual(data["creation_source"], CreationSource.MANUAL)
        self.assertEqual(data["applicant"]["id"], str(self.applicant.id))

    def test_only_the_applicant_is_required(self) -> None:
        """A journey often begins as little more than an intention."""
        resp = self.client.post(self.list_url, {"applicant": str(self.applicant.id)}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_unknown_applicant_is_rejected(self) -> None:
        resp = self.client.post(
            self.list_url,
            {"applicant": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.APPLICANT_NOT_FOUND)

    def test_one_applicant_may_hold_many_journeys(self) -> None:
        self.client.post(
            self.list_url, {"applicant": str(self.applicant.id), "target_country": "Australia"}, format="json"
        )
        self.client.post(
            self.list_url, {"applicant": str(self.applicant.id), "target_country": "Canada"}, format="json"
        )
        resp = self.client.get(self.list_url, {"applicant": str(self.applicant.id)})
        self.assertEqual(resp.data["meta"]["count"], 2)

    def test_applicant_cannot_be_reassigned_on_update(self) -> None:
        journey = self.make_journey()
        other = make_applicant(self.admin, name_np="सीता गुरुङ")
        self.client.patch(
            self.url("journey-detail", journey),
            {"applicant": str(other.id)},
            format="json",
        )
        journey.refresh_from_db()
        self.assertEqual(journey.applicant_id, self.applicant.id)


class TestJourneyStage(JourneyApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.journey = self.make_journey()
        self.auth(self.admin)

    def test_moves_between_active_stages(self) -> None:
        resp = self.client.post(
            self.url("journey-stage", self.journey),
            {"stage": JourneyStage.SHORTLISTING},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["stage"], JourneyStage.SHORTLISTING)

    def test_terminal_stages_are_not_selectable(self) -> None:
        for stage in (JourneyStage.COMPLETED, JourneyStage.CLOSED, JourneyStage.DEFERRED):
            resp = self.client.post(self.url("journey-stage", self.journey), {"stage": stage}, format="json")
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("stage", resp.data["error"]["details"])

    def test_stage_frozen_once_closed(self) -> None:
        self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.WITHDRAWN},
            format="json",
        )
        resp = self.client.post(
            self.url("journey-stage", self.journey),
            {"stage": JourneyStage.APPLYING},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.STAGE_NOT_EDITABLE)

    def test_update_cannot_set_stage(self) -> None:
        self.client.patch(
            self.url("journey-detail", self.journey),
            {"stage": JourneyStage.CLOSED},
            format="json",
        )
        self.journey.refresh_from_db()
        self.assertEqual(self.journey.stage, JourneyStage.PLANNING)


class TestJourneyClose(JourneyApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.journey = self.make_journey()
        self.auth(self.admin)

    def test_successful_outcome_completes_the_journey(self) -> None:
        resp = self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.SUCCESSFUL},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["stage"], JourneyStage.COMPLETED)
        self.assertEqual(data["outcome"], JourneyOutcome.SUCCESSFUL)

    def test_any_other_outcome_closes_the_journey(self) -> None:
        resp = self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.REJECTED},
            format="json",
        )
        self.assertEqual(resp.data["data"]["stage"], JourneyStage.CLOSED)

    def test_outcome_is_mandatory(self) -> None:
        resp = self.client.post(self.url("journey-close", self.journey), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("outcome", resp.data["error"]["details"])

    def test_other_outcome_requires_an_explanation(self) -> None:
        resp = self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.OTHER},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.OUTCOME_DETAIL_REQUIRED)

    def test_previous_stage_is_remembered(self) -> None:
        self.client.post(
            self.url("journey-stage", self.journey),
            {"stage": JourneyStage.OFFER_STAGE},
            format="json",
        )
        self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.WITHDRAWN},
            format="json",
        )
        self.journey.refresh_from_db()
        self.assertEqual(self.journey.stage_before_terminal, JourneyStage.OFFER_STAGE)

    def test_cannot_close_twice(self) -> None:
        self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.WITHDRAWN},
            format="json",
        )
        resp = self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.REJECTED},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


class TestJourneyDefer(JourneyApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.journey = self.make_journey()
        self.auth(self.admin)

    def test_defers_to_a_named_intake(self) -> None:
        resp = self.client.post(
            self.url("journey-defer", self.journey),
            {"to_intake": "Spring 2027", "reason": "Test result delayed."},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["stage"], JourneyStage.DEFERRED)
        self.assertEqual(data["deferred_to_intake"], "Spring 2027")
        self.assertIsNotNone(data["deferred_at_bs"])

    def test_target_intake_is_mandatory(self) -> None:
        resp = self.client.post(self.url("journey-defer", self.journey), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("to_intake", resp.data["error"]["details"])

    def test_deferring_records_no_outcome(self) -> None:
        """Deferment is not an outcome — the journey is paused, not ended."""
        self.client.post(self.url("journey-defer", self.journey), {"to_intake": "Fall 2027"}, format="json")
        self.journey.refresh_from_db()
        self.assertEqual(self.journey.outcome, "")


class TestJourneyReopen(JourneyApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.journey = self.make_journey()
        self.auth(self.admin)

    def test_reopening_a_closed_journey_clears_closure_state(self) -> None:
        self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.REJECTED, "reason": "No offer."},
            format="json",
        )
        resp = self.client.post(self.url("journey-reopen", self.journey), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["stage"], JourneyStage.PLANNING)
        self.assertEqual(data["outcome"], "")
        self.assertIsNone(data["closed_at"])

    def test_reopening_a_deferred_journey_clears_deferment_state(self) -> None:
        self.client.post(self.url("journey-defer", self.journey), {"to_intake": "Fall 2027"}, format="json")
        resp = self.client.post(
            self.url("journey-reopen", self.journey),
            {"stage": JourneyStage.APPLYING},
            format="json",
        )
        data = resp.data["data"]
        self.assertEqual(data["stage"], JourneyStage.APPLYING)
        self.assertEqual(data["deferred_to_intake"], "")
        self.assertIsNone(data["deferred_at"])

    def test_active_journey_cannot_be_reopened(self) -> None:
        resp = self.client.post(self.url("journey-reopen", self.journey), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.JOURNEY_NOT_TERMINAL)

    def test_reopening_preserves_the_closure_in_history(self) -> None:
        """Reopening a completed journey does not undo that it was completed."""
        self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.SUCCESSFUL},
            format="json",
        )
        self.client.post(self.url("journey-reopen", self.journey), {}, format="json")
        actions = [
            entry["action"] for entry in self.client.get(self.url("journey-history", self.journey)).data["data"]
        ]
        self.assertIn(JourneyAuditAction.JOURNEY_CLOSED, actions)
        self.assertIn(JourneyAuditAction.JOURNEY_REOPENED, actions)


class TestJourneyIndependence(JourneyApiTestCase):
    """The journey and applicant lifecycles run independently, by design."""

    def setUp(self) -> None:
        super().setUp()
        self.journey = self.make_journey()
        self.auth(self.admin)

    def test_closing_a_journey_does_not_change_applicant_status(self) -> None:
        before = self.applicant.status
        self.client.post(
            self.url("journey-close", self.journey),
            {"outcome": JourneyOutcome.SUCCESSFUL},
            format="json",
        )
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, before)

    def test_archiving_an_applicant_does_not_close_journeys(self) -> None:
        self.client.post(
            reverse("v1:applicants:applicant-status", args=[self.applicant.id]),
            {"status": "archived"},
            format="json",
        )
        self.journey.refresh_from_db()
        self.assertEqual(self.journey.stage, JourneyStage.PLANNING)


class TestJourneyHistory(JourneyApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.journey = self.make_journey()
        self.auth(self.admin)

    def test_history_records_the_whole_journey_in_order(self) -> None:
        self.client.post(
            self.url("journey-stage", self.journey),
            {"stage": JourneyStage.APPLYING},
            format="json",
        )
        self.client.post(self.url("journey-defer", self.journey), {"to_intake": "Fall 2027"}, format="json")
        self.client.post(self.url("journey-reopen", self.journey), {}, format="json")

        actions = [
            entry["action"] for entry in self.client.get(self.url("journey-history", self.journey)).data["data"]
        ]
        for expected in (
            JourneyAuditAction.JOURNEY_CREATED,
            JourneyAuditAction.JOURNEY_STAGE_CHANGED,
            JourneyAuditAction.JOURNEY_DEFERRED,
            JourneyAuditAction.JOURNEY_REOPENED,
        ):
            self.assertIn(expected, actions)
        self.assertEqual(actions[0], JourneyAuditAction.JOURNEY_REOPENED)

    def test_stage_change_carries_from_and_to(self) -> None:
        self.client.post(
            self.url("journey-stage", self.journey),
            {"stage": JourneyStage.APPLYING},
            format="json",
        )
        history = self.client.get(self.url("journey-history", self.journey)).data["data"]
        entry = next(e for e in history if e["action"] == JourneyAuditAction.JOURNEY_STAGE_CHANGED)
        self.assertEqual(
            entry["changes"]["stage"],
            {"from": JourneyStage.PLANNING, "to": JourneyStage.APPLYING},
        )
