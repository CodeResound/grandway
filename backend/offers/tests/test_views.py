"""Endpoint tests for the offers app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).
"""

from __future__ import annotations

from typing import Any

from rest_framework.test import APITestCase

from offers.constants import ErrorCode, OfferStatus
from offers.tests import factories as f

OFFERS_URL = "/api/v1/offers/"


class OfferAPITestCase(APITestCase):
    """Shared fixtures and envelope assertions."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.superadmin = f.make_superadmin()
        self.applicant = f.make_applicant(self.admin)
        self.journey = f.make_journey(self.admin, self.applicant)
        self.catalogue = f.make_catalogue(self.admin)

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token_for(user)}")

    def assert_success_envelope(self, response: Any) -> dict[str, Any]:
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("data", body)
        self.assertIn("meta", body)
        return body

    def assert_error_envelope(self, response: Any, code: str) -> dict[str, Any]:
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("details", body["error"])
        self.assertIn("meta", body)
        return body

    def create_offer_payload(self, **overrides: Any) -> dict[str, Any]:
        return {
            "journey": str(self.journey.id),
            "program": str(self.catalogue["program"].id),
            "offer_type": "conditional",
            **overrides,
        }


class OfferListCreateTests(OfferAPITestCase):
    def test_list_requires_authentication(self) -> None:
        response = self.client.get(OFFERS_URL)
        self.assertEqual(response.status_code, 401)

    def test_superadmin_is_denied(self) -> None:
        self.auth(self.superadmin)
        response = self.client.get(OFFERS_URL)

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_list(self) -> None:
        """Offers are shared, exactly as the journeys they belong to are."""
        f.make_offer(self.admin, self.journey, program=self.catalogue["program"])
        self.auth(self.lead_manager)
        response = self.client.get(OFFERS_URL)

        self.assertEqual(response.status_code, 200)
        body = self.assert_success_envelope(response)
        self.assertEqual(len(body["data"]), 1)
        self.assertIn("count", body["meta"])

    def test_list_row_carries_the_applicant(self) -> None:
        f.make_offer(self.admin, self.journey, program=self.catalogue["program"])
        self.auth(self.admin)
        row = self.client.get(OFFERS_URL).json()["data"][0]

        self.assertEqual(row["applicant_id"], str(self.applicant.id))
        self.assertTrue(row["applicant_name"])

    def test_filter_by_journey(self) -> None:
        f.make_offer(self.admin, self.journey, program=self.catalogue["program"])
        other_journey = f.make_journey(self.admin, f.make_applicant(self.admin))
        f.make_manual_offer(self.admin, other_journey)
        self.auth(self.admin)

        response = self.client.get(OFFERS_URL, {"journey": str(self.journey.id)})
        self.assertEqual(len(response.json()["data"]), 1)

    def test_unparseable_filter_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.get(OFFERS_URL, {"deadline_before": "soon"})
        self.assertEqual(response.status_code, 400)

    def test_out_of_range_fiscal_year_is_400(self) -> None:
        # Format-valid but unconvertible: the old RegexField let this through
        # to the selector, where it raised as a 500.
        self.auth(self.admin)
        response = self.client.get(OFFERS_URL, {"fiscal_year": "9999/99"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("fiscal_year", response.json()["error"]["details"])

    def test_lead_manager_may_record_an_offer(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(OFFERS_URL, self.create_offer_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = self.assert_success_envelope(response)
        self.assertEqual(body["data"]["program_title"], "Master of Information Technology")
        self.assertEqual(body["data"]["reference_source"], "catalogue")
        self.assertEqual(body["data"]["status"], OfferStatus.DRAFT)

    def test_create_with_conditions(self) -> None:
        self.auth(self.admin)
        payload = self.create_offer_payload(conditions=[f.condition(), f.condition("academic_result")])
        response = self.client.post(OFFERS_URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["data"]["conditions"]), 2)

    def test_create_with_unknown_journey(self) -> None:
        self.auth(self.admin)
        payload = self.create_offer_payload(journey="00000000-0000-0000-0000-000000000000")
        response = self.client.post(OFFERS_URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.JOURNEY_NOT_FOUND)

    def test_create_with_unknown_program(self) -> None:
        self.auth(self.admin)
        payload = self.create_offer_payload(program="00000000-0000-0000-0000-000000000000")
        response = self.client.post(OFFERS_URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.CATALOGUE_REFERENCE_INVALID)

    def test_create_with_no_reference_at_all(self) -> None:
        self.auth(self.admin)
        response = self.client.post(OFFERS_URL, {"journey": str(self.journey.id)}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.PROGRAM_REFERENCE_REQUIRED)

    def test_create_manual_historical_offer(self) -> None:
        self.auth(self.admin)
        payload = {
            "journey": str(self.journey.id),
            "institution_name": "Ancient Polytechnic",
            "program_title": "Diploma in Hospitality",
            "intake_label": "Sep 2019",
        }
        response = self.client.post(OFFERS_URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["reference_source"], "manual")

    def test_amount_without_currency_is_rejected(self) -> None:
        self.auth(self.admin)
        payload = self.create_offer_payload(deposit_amount="5000.00")
        response = self.client.post(OFFERS_URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.AMOUNT_INCOMPLETE)

    def test_invalid_offer_type_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(OFFERS_URL, self.create_offer_payload(offer_type="maybe"), format="json")
        self.assertEqual(response.status_code, 400)


class OfferDetailTests(OfferAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])
        self.url = f"{OFFERS_URL}{self.offer.id}/"

    def test_retrieve(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["id"], str(self.offer.id))
        self.assertIn("conditions", data)

    def test_retrieve_unknown_offer(self) -> None:
        self.auth(self.admin)
        response = self.client.get(f"{OFFERS_URL}00000000-0000-0000-0000-000000000000/")

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.OFFER_NOT_FOUND)

    def test_dates_carry_a_bikram_sambat_sibling(self) -> None:
        self.auth(self.admin)
        self.client.patch(self.url, {"response_deadline": "2026-09-30"}, format="json")
        data = self.client.get(self.url).json()["data"]

        self.assertIsNotNone(data["response_deadline_bs"])
        self.assertIn("display", data["response_deadline_bs"])

    def test_patch_corrects_decision_details(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.patch(self.url, {"offer_reference": "OFR-2026-77"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["offer_reference"], "OFR-2026-77")

    def test_patch_cannot_rewrite_the_snapshot(self) -> None:
        """Rejected loudly, not dropped silently — history is not editable."""
        self.auth(self.admin)
        response = self.client.patch(self.url, {"program_title": "Something Else"}, format="json")

        self.assertEqual(response.status_code, 400)
        body = self.assert_error_envelope(response, ErrorCode.REFERENCE_IMMUTABLE)
        self.assertIn("program_title", body["error"]["details"])
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.program_title, "Master of Information Technology")

    def test_patch_cannot_move_the_offer_to_another_journey(self) -> None:
        other_journey = f.make_journey(self.admin, f.make_applicant(self.admin))
        self.auth(self.admin)
        response = self.client.patch(self.url, {"journey": str(other_journey.id)}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.REFERENCE_IMMUTABLE)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.journey_id, self.journey.id)

    def test_patch_cannot_set_status_directly(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.url, {"status": "accepted"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.REFERENCE_IMMUTABLE)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, OfferStatus.DRAFT)

    def test_patch_of_an_ordinary_field_still_works(self) -> None:
        """The guard must not catch a legitimate correction alongside it."""
        self.auth(self.admin)
        response = self.client.patch(self.url, {"notes": "Deposit invoice received."}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["notes"], "Deposit invoice received.")


class OfferLifecycleEndpointTests(OfferAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])
        self.url = f"{OFFERS_URL}{self.offer.id}/"

    def test_issue(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(f"{self.url}issue/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], OfferStatus.ISSUED)

    def test_issuing_a_non_draft_conflicts(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}issue/", {}, format="json")
        response = self.client.post(f"{self.url}issue/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.OFFER_NOT_ISSUABLE)

    def test_accept(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(f"{self.url}decision/", {"outcome": "accepted"}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], OfferStatus.ACCEPTED)
        self.assertIsNotNone(data["decided_at"])
        self.assertTrue(data["is_terminal"])

    def test_reject_without_a_reason(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}decision/", {"outcome": "rejected"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.DECISION_REASON_REQUIRED)

    def test_defer_without_an_intake(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}decision/", {"outcome": "deferred"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.DEFER_INTAKE_REQUIRED)

    def test_deciding_twice_conflicts(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}decision/", {"outcome": "accepted"}, format="json")
        response = self.client.post(
            f"{self.url}decision/", {"outcome": "rejected", "reason": "changed"}, format="json"
        )

        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.OFFER_NOT_DECIDABLE)

    def test_a_second_accepted_offer_conflicts(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}decision/", {"outcome": "accepted"}, format="json")
        second = f.make_manual_offer(self.admin, self.journey)

        response = self.client.post(f"{OFFERS_URL}{second.id}/decision/", {"outcome": "accepted"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.ACCEPTED_OFFER_EXISTS)

    def test_invalid_outcome_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.url}decision/", {"outcome": "issued"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_history_returns_the_full_trail(self) -> None:
        self.auth(self.admin)
        self.client.post(f"{self.url}issue/", {}, format="json")
        self.client.post(f"{self.url}decision/", {"outcome": "accepted"}, format="json")

        response = self.client.get(f"{self.url}history/")
        self.assertEqual(response.status_code, 200)
        actions = [e["action"] for e in response.json()["data"]]
        self.assertIn("offer_created", actions)
        self.assertIn("offer_issued", actions)
        self.assertIn("offer_decision_recorded", actions)

    def test_history_entries_carry_the_shared_audit_shape(self) -> None:
        """Regression: this endpoint used to omit `actor_id` (contract 1.1.0).

        The six history endpoints now render one shape owned by `audit`; three
        of them, this one included, had been dropping the acting user's id, so
        the same audit row looked different depending on which record you
        reached it from.
        """
        self.auth(self.admin)
        entry = self.client.get(f"{self.url}history/").json()["data"][0]
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
        self.assertEqual(entry["actor_id"], str(self.admin.id))

    def test_superadmin_is_denied_every_action(self) -> None:
        self.auth(self.superadmin)
        for path, method in (("issue/", "post"), ("decision/", "post"), ("history/", "get")):
            with self.subTest(path=path):
                call = getattr(self.client, method)
                response = call(f"{self.url}{path}", {} if method == "post" else None, format="json")
                self.assertEqual(response.status_code, 403)


class ConditionEndpointTests(OfferAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.offer = f.make_offer(
            self.admin,
            self.journey,
            program=self.catalogue["program"],
            conditions=[f.condition()],
        )
        self.condition = self.offer.conditions.first()
        self.conditions_url = f"{OFFERS_URL}{self.offer.id}/conditions/"
        self.condition_url = f"{OFFERS_URL}conditions/{self.condition.id}/"

    def test_list(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.get(self.conditions_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.assert_success_envelope(response)["data"]), 1)

    def test_create(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(self.conditions_url, f.condition("deposit_payment"), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["condition_type"], "deposit_payment")

    def test_create_with_invalid_type(self) -> None:
        self.auth(self.admin)
        response = self.client.post(self.conditions_url, f.condition("vibes"), format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_on_unknown_offer(self) -> None:
        self.auth(self.admin)
        response = self.client.post(
            f"{OFFERS_URL}00000000-0000-0000-0000-000000000000/conditions/", f.condition(), format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.OFFER_NOT_FOUND)

    def test_patch_corrects_the_wording(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(self.condition_url, {"description": "IELTS 7.0 overall."}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["description"], "IELTS 7.0 overall.")

    def test_patch_cannot_set_status(self) -> None:
        self.auth(self.admin)
        self.client.patch(self.condition_url, {"status": "satisfied"}, format="json")

        self.condition.refresh_from_db()
        self.assertEqual(self.condition.status, "pending")

    def test_patch_unknown_condition(self) -> None:
        self.auth(self.admin)
        response = self.client.patch(
            f"{OFFERS_URL}conditions/00000000-0000-0000-0000-000000000000/", {}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.CONDITION_NOT_FOUND)

    def test_satisfy(self) -> None:
        self.auth(self.lead_manager)
        response = self.client.post(f"{self.condition_url}status/", {"status": "satisfied"}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "satisfied")
        self.assertTrue(data["is_resolved"])
        self.assertEqual(data["resolved_by_username"], self.lead_manager.username)

    def test_waive_without_a_note(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.condition_url}status/", {"status": "waived"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.CONDITION_NOTE_REQUIRED)

    def test_waive_with_a_note(self) -> None:
        self.auth(self.admin)
        response = self.client.post(
            f"{self.condition_url}status/",
            {"status": "waived", "note": "Institution confirmed by email that this is not required."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "waived")

    def test_invalid_status_is_rejected(self) -> None:
        self.auth(self.admin)
        response = self.client.post(f"{self.condition_url}status/", {"status": "maybe"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_condition_endpoints_require_authentication(self) -> None:
        for url in (self.conditions_url, self.condition_url, f"{self.condition_url}status/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)

    def test_superadmin_is_denied(self) -> None:
        self.auth(self.superadmin)
        response = self.client.get(self.conditions_url)

        self.assertEqual(response.status_code, 403)
        self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)
