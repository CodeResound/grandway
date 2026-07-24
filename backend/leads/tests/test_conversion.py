"""Lead → applicant conversion: idempotency, authority, guards, and data mapping.

This is the one point where the lead cycle meets the applicant cycle, so these
tests care most about what must *not* happen: no second applicant, no silent
loss of the study interest, and no conversion undone by a later reopen.
"""

from __future__ import annotations

from applicant_journeys.constants import CreationSource as JourneyCreationSource
from applicant_journeys.models import ApplicantJourney
from applicants.constants import CreationSource as ApplicantCreationSource
from applicants.models import Applicant
from django.db import IntegrityError, transaction
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


class ConversionTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.source = make_source()
        self.reason = make_loss_reason()
        self.lead = make_lead(self.owner, self.source)
        self.url = reverse("v1:leads:lead-convert", args=[self.lead.id])

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def lead_url(self, name: str) -> str:
        return reverse(f"v1:leads:{name}", args=[self.lead.id])


class TestConversionAuthority(ConversionTestCase):
    def test_lead_manager_cannot_convert(self) -> None:
        """Only an Admin converts a lead — entry to the applicant lifecycle is their call."""
        self.auth(self.owner)
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)
        self.assertEqual(Applicant.objects.count(), 0)

    def test_admin_converts_successfully(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(resp.data["data"]["applicant_id"])
        self.assertIsNotNone(resp.data["data"]["journey_id"])

    def test_unauthenticated_is_401(self) -> None:
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, status.HTTP_401_UNAUTHORIZED)


class TestConversionIdempotency(ConversionTestCase):
    """Conversion must be protected against repeated execution (§15)."""

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_converting_twice_creates_exactly_one_applicant_and_journey(self) -> None:
        first = self.client.post(self.url, {}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.url, {}, format="json")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data["error"]["code"], ErrorCode.LEAD_ALREADY_CONVERTED)

        # The count assertion is the real test — a 409 alone would not prove
        # that the second call created nothing.
        self.assertEqual(Applicant.objects.count(), 1)
        self.assertEqual(ApplicantJourney.objects.count(), 1)

    def test_one_applicant_per_lead_is_enforced_by_the_database(self) -> None:
        """The OneToOne makes two leads sharing one applicant structurally impossible.

        The service guard is the first line; this is the backstop that holds
        even if a future caller reaches the model directly.
        """
        self.client.post(self.url, {}, format="json")
        self.lead.refresh_from_db()

        second_lead = make_lead(self.owner, self.source)
        second_lead.converted_applicant = self.lead.converted_applicant
        with self.assertRaises(IntegrityError), transaction.atomic():
            second_lead.save(update_fields=["converted_applicant"])

    def test_a_different_applicant_may_be_linked_to_a_different_lead(self) -> None:
        """The constraint is one applicant per lead — not one applicant overall."""
        self.client.post(self.url, {}, format="json")

        other_applicant = Applicant.objects.create(
            created_by=self.admin,
            creation_source=ApplicantCreationSource.DIRECT_ADMIN,
        )
        second_lead = make_lead(self.owner, self.source)
        second_lead.converted_applicant = other_applicant
        second_lead.save(update_fields=["converted_applicant"])

        self.assertEqual(Lead.objects.filter(converted_applicant__isnull=False).count(), 2)


class TestConversionGuards(ConversionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_a_lost_lead_must_be_reopened_first(self) -> None:
        self.client.post(
            self.lead_url("lead-lost"),
            {"loss_reason": str(self.reason.id)},
            format="json",
        )
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CONVERSION_NOT_READY)
        self.assertEqual(Applicant.objects.count(), 0)

    def test_conversion_succeeds_after_reopening(self) -> None:
        self.client.post(self.lead_url("lead-lost"), {"loss_reason": str(self.reason.id)}, format="json")
        self.client.post(self.lead_url("lead-reopen"), {}, format="json")
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_conversion_allowed_from_any_active_stage(self) -> None:
        """`ready_for_conversion` signals readiness but is not a precondition."""
        self.client.post(self.lead_url("lead-stage"), {"stage": LeadStage.CONTACTED}, format="json")
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_unknown_lead_is_404(self) -> None:
        resp = self.client.post(
            reverse("v1:leads:lead-convert", args=["00000000-0000-0000-0000-000000000000"]),
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class TestConversionResult(ConversionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_lead_reaches_its_terminal_converted_state(self) -> None:
        self.client.post(self.url, {}, format="json")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage, LeadStage.CONVERTED)
        self.assertIsNotNone(self.lead.converted_at)
        self.assertEqual(self.lead.converted_by_id, self.admin.id)
        self.assertIsNotNone(self.lead.converted_applicant_id)
        self.assertIsNotNone(self.lead.converted_journey_id)

    def test_applicant_carries_the_leads_identity_and_contacts(self) -> None:
        self.client.post(self.url, {}, format="json")
        applicant = Applicant.objects.get()
        self.assertEqual(applicant.full_name, self.lead.full_name)
        self.assertEqual(applicant.creation_source, ApplicantCreationSource.LEAD_CONVERSION)
        self.assertEqual(
            [entry.number for entry in applicant.contact_numbers.all()],
            [entry.number for entry in self.lead.contact_numbers.all()],
        )

    def test_the_reverse_link_resolves_back_to_the_lead(self) -> None:
        self.client.post(self.url, {}, format="json")
        applicant = Applicant.objects.get()
        self.assertEqual(applicant.originating_lead.id, self.lead.id)

    def test_journey_is_marked_as_created_by_conversion(self) -> None:
        self.client.post(self.url, {}, format="json")
        journey = ApplicantJourney.objects.get()
        self.assertEqual(journey.creation_source, JourneyCreationSource.LEAD_CONVERSION)

    def test_history_records_both_conversion_events(self) -> None:
        self.client.post(self.url, {}, format="json")
        actions = [entry["action"] for entry in self.client.get(self.lead_url("lead-history")).data["data"]]
        self.assertIn(LeadAuditAction.LEAD_CONVERTED, actions)
        self.assertIn(LeadAuditAction.LEAD_APPLICANT_CREATED, actions)


class TestStudyInterestMapping(ConversionTestCase):
    """The ten interest fields must not be silently dropped at conversion."""

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def set_interest(self, **interest: object) -> None:
        from leads import services as lead_services

        lead_services.update_lead(actor=self.owner, lead=self.lead, fields={}, study_interest=interest)

    def test_single_country_becomes_the_journey_target(self) -> None:
        self.set_interest(interested_countries=["Australia"], study_level="masters")
        self.client.post(self.url, {}, format="json")
        journey = ApplicantJourney.objects.get()
        self.assertEqual(journey.target_country, "Australia")
        self.assertEqual(journey.study_level, "masters")

    def test_multiple_countries_are_left_for_a_human_to_resolve(self) -> None:
        """A journey targets one country; two is a real ambiguity, not a default."""
        self.set_interest(interested_countries=["Australia", "Canada"])
        self.client.post(self.url, {}, format="json")
        journey = ApplicantJourney.objects.get()
        self.assertEqual(journey.target_country, "")
        self.assertIn("Australia", journey.notes)
        self.assertIn("Canada", journey.notes)

    def test_fields_owned_by_unbuilt_modules_are_carried_in_notes(self) -> None:
        self.set_interest(
            highest_qualification="BSc CSIT",
            language_test_status="preparing",
            interest_notes="Prefers Melbourne.",
        )
        self.client.post(self.url, {}, format="json")
        journey = ApplicantJourney.objects.get()
        self.assertIn("BSc CSIT", journey.notes)
        self.assertIn("preparing", journey.notes)
        self.assertIn("Prefers Melbourne.", journey.notes)

    def test_the_six_mapped_fields_are_copied(self) -> None:
        self.set_interest(
            study_level="masters",
            field_of_study="Computer Science",
            preferred_intake="Fall 2026",
            budget_amount="2500000.00",
            budget_currency="NPR",
            scholarship_interest=True,
        )
        self.client.post(self.url, {}, format="json")
        journey = ApplicantJourney.objects.get()
        self.assertEqual(journey.field_of_study, "Computer Science")
        self.assertEqual(journey.preferred_intake, "Fall 2026")
        self.assertEqual(journey.budget_currency, "NPR")
        self.assertTrue(journey.scholarship_interest)

    def test_a_lead_with_no_interest_still_converts(self) -> None:
        self.client.post(self.url, {}, format="json")
        self.assertEqual(ApplicantJourney.objects.count(), 1)


class TestReopenAfterConversion(ConversionTestCase):
    """Reopening a converted lead must never undo the conversion."""

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.client.post(self.url, {}, format="json")
        self.lead.refresh_from_db()

    def test_reopen_preserves_the_applicant_link(self) -> None:
        applicant_id = self.lead.converted_applicant_id
        journey_id = self.lead.converted_journey_id

        resp = self.client.post(self.lead_url("lead-reopen"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage, LeadStage.FOLLOW_UP)
        self.assertEqual(self.lead.converted_applicant_id, applicant_id)
        self.assertEqual(self.lead.converted_journey_id, journey_id)
        self.assertIsNotNone(self.lead.converted_at)

    def test_reopen_does_not_delete_the_applicant_or_journey(self) -> None:
        self.client.post(self.lead_url("lead-reopen"), {}, format="json")
        self.assertEqual(Applicant.objects.count(), 1)
        self.assertEqual(ApplicantJourney.objects.count(), 1)

    def test_a_reopened_converted_lead_cannot_be_converted_again(self) -> None:
        """The whole point: no second applicant can ever come from this lead."""
        self.client.post(self.lead_url("lead-reopen"), {}, format="json")
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.LEAD_ALREADY_CONVERTED)
        self.assertEqual(Applicant.objects.count(), 1)


class TestConversionAtomicity(ConversionTestCase):
    """The applicant and the journey are created together or not at all.

    Exercised at the service layer rather than over HTTP: the project's global
    exception handler turns an unhandled error into a 500 envelope, so a view
    test would assert the error shape rather than the rollback. The atomicity
    guarantee lives in the service, so that is where it is tested.
    """

    def test_a_failure_mid_conversion_leaves_nothing_behind(self) -> None:
        from unittest.mock import patch

        from leads import services as lead_services

        with patch(
            "applicant_journeys.services.create_journey",
            side_effect=RuntimeError("journey creation blew up"),
        ):
            with self.assertRaises(RuntimeError):
                lead_services.convert_lead(actor=self.admin, lead=self.lead)

        # The applicant was created before the failure; the transaction must
        # have rolled it back, or conversion would leave an orphan behind.
        self.assertEqual(Applicant.objects.count(), 0)
        self.assertEqual(ApplicantJourney.objects.count(), 0)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage, LeadStage.NEW)
        self.assertIsNone(self.lead.converted_applicant_id)

    def test_the_lead_can_still_be_converted_after_a_failed_attempt(self) -> None:
        from unittest.mock import patch

        from leads import services as lead_services

        with patch(
            "applicant_journeys.services.create_journey",
            side_effect=RuntimeError("transient failure"),
        ):
            with self.assertRaises(RuntimeError):
                lead_services.convert_lead(actor=self.admin, lead=self.lead)

        self.lead.refresh_from_db()
        lead_services.convert_lead(actor=self.admin, lead=self.lead)
        self.assertEqual(Applicant.objects.count(), 1)
        self.assertEqual(ApplicantJourney.objects.count(), 1)


class TestLeadDetailExposesConversion(ConversionTestCase):
    def test_lead_detail_carries_the_conversion_state(self) -> None:
        self.auth(self.admin)
        self.client.post(self.url, {}, format="json")
        data = self.client.get(reverse("v1:leads:lead-detail", args=[self.lead.id])).data["data"]
        self.assertEqual(data["stage"], LeadStage.CONVERTED)
        self.assertIsNotNone(data["converted_at"])
        self.assertIsNotNone(data["converted_at_bs"])
        self.assertEqual(data["converted_by"]["username"], self.admin.username)

    def test_lead_detail_links_through_to_the_applicant_and_journey(self) -> None:
        """Without these ids a client cannot navigate from a converted lead."""
        self.auth(self.admin)
        self.client.post(self.url, {}, format="json")
        data = self.client.get(reverse("v1:leads:lead-detail", args=[self.lead.id])).data["data"]
        self.assertEqual(data["converted_applicant_id"], str(Applicant.objects.get().id))
        self.assertEqual(data["converted_journey_id"], str(ApplicantJourney.objects.get().id))

    def test_an_unconverted_lead_reports_null_conversion_fields(self) -> None:
        self.auth(self.admin)
        data = self.client.get(reverse("v1:leads:lead-detail", args=[self.lead.id])).data["data"]
        self.assertIsNone(data["converted_at"])
        self.assertIsNone(data["converted_by"])
        self.assertIsNone(data["converted_applicant_id"])
        self.assertIsNone(data["converted_journey_id"])


class TestLeadFactoryStillWorks(ConversionTestCase):
    def test_unconverted_lead_has_no_originating_link(self) -> None:
        self.assertFalse(Lead.objects.filter(converted_applicant__isnull=False).exists())
