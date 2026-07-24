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
        other = make_applicant(self.admin)
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


class TestJourneyCountryReference(JourneyApiTestCase):
    """The catalogue reference beside the free text.

    ``target_country`` has always been a typed string. ``target_country_ref``
    points at the real catalogue row, and it is what makes the destination
    machine-readable — downstream, it is the field that decides which document
    checklist an applicant inherits. Both are kept: journeys created before the
    catalogue existed have nothing but the typed name.
    """

    def setUp(self) -> None:
        super().setUp()
        from institutions import services as catalogue_services

        self.country = catalogue_services.create_country(
            actor=self.admin,
            data={"code": "au", "name": "Australia"},
        )
        self.auth(self.admin)

    def test_create_accepts_a_country_id_and_reads_it_back_as_an_object(self) -> None:
        response = self.client.post(
            self.list_url,
            {"applicant": str(self.applicant.id), "target_country_ref": str(self.country.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ref = response.data["data"]["target_country_ref"]
        self.assertEqual(ref["id"], str(self.country.id))
        self.assertEqual(ref["name"], "Australia")

    def test_an_unknown_country_id_is_rejected_by_name(self) -> None:
        response = self.client.post(
            self.list_url,
            {
                "applicant": str(self.applicant.id),
                "target_country_ref": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], ErrorCode.COUNTRY_NOT_FOUND)
        self.assertIn("target_country_ref", response.data["error"]["details"])

    def test_patch_sets_and_clears_the_reference(self) -> None:
        journey = self.make_journey()

        set_response = self.client.patch(
            self.url("journey-detail", journey),
            {"target_country_ref": str(self.country.id)},
            format="json",
        )
        self.assertEqual(set_response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(set_response.data["data"]["target_country_ref"])

        cleared = self.client.patch(
            self.url("journey-detail", journey),
            {"target_country_ref": None},
            format="json",
        )
        self.assertEqual(cleared.status_code, status.HTTP_200_OK)
        self.assertIsNone(cleared.data["data"]["target_country_ref"])

    def test_the_free_text_field_still_works_on_its_own(self) -> None:
        """Backward compatibility: nothing about the old field changed."""
        response = self.client.post(
            self.list_url,
            {"applicant": str(self.applicant.id), "target_country": "Somewhere Uncatalogued"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["target_country"], "Somewhere Uncatalogued")
        self.assertIsNone(response.data["data"]["target_country_ref"])

    def test_the_exact_filter_is_separate_from_the_text_filter(self) -> None:
        matched = self.make_journey(target_country_ref=self.country)
        self.make_journey(target_country="Australia")

        response = self.client.get(self.list_url, {"target_country_ref": str(self.country.id)})
        ids = [row["id"] for row in response.data["data"]]
        self.assertEqual(ids, [str(matched.id)])


class TestCountryBackfill(JourneyApiTestCase):
    """The 0002 data migration's matching rule, exercised directly.

    Deliberately exact, not fuzzy: "UK" does not become "United Kingdom" here.
    A wrong country on a journey is worse than no country at all, because
    downstream it decides which requirements an applicant is measured against.
    """

    def setUp(self) -> None:
        super().setUp()
        from institutions import services as catalogue_services

        self.country = catalogue_services.create_country(
            actor=self.admin,
            data={"code": "au", "name": "Australia"},
        )

    def _run_backfill(self) -> None:
        """Call the migration's own function, not a copy of its logic.

        Imported by path because a module name starting with a digit cannot be
        written as an ``import`` statement. The live app registry stands in for
        the historical one: the two models this touches have the same fields at
        0002 as they do today, so the substitution changes nothing the function
        can observe.
        """
        import importlib

        from django.apps import apps

        module = importlib.import_module("applicant_journeys.migrations.0002_target_country_ref")
        module.backfill_country_ref(apps, None)

    def test_it_matches_case_insensitively_and_leaves_the_rest_alone(self) -> None:
        matched = self.make_journey(target_country="australia")
        by_code = self.make_journey(target_country="AU")
        unmatched = self.make_journey(target_country="Wakanda")
        blank = self.make_journey(target_country="")

        self._run_backfill()

        for journey in (matched, by_code, unmatched, blank):
            journey.refresh_from_db()
        self.assertEqual(matched.target_country_ref_id, self.country.id)
        self.assertEqual(by_code.target_country_ref_id, self.country.id)
        self.assertIsNone(unmatched.target_country_ref_id)
        self.assertIsNone(blank.target_country_ref_id)

    def test_it_never_overwrites_a_reference_that_is_already_set(self) -> None:
        from institutions import services as catalogue_services

        canada = catalogue_services.create_country(actor=self.admin, data={"code": "ca", "name": "Canada"})
        journey = self.make_journey(target_country="Australia", target_country_ref=canada)

        self._run_backfill()

        journey.refresh_from_db()
        self.assertEqual(journey.target_country_ref_id, canada.id)
