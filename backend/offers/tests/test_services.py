"""Service-level tests for the offers app.

These cover the rules that make this app worth having as a separate record:
the snapshot outliving the catalogue, the single-accepted-offer invariant, the
finality of a decision, and the guarantee that recording an offer never touches
the journey it belongs to.
"""

from __future__ import annotations

from decimal import Decimal

from audit.models import AuditEvent
from django.test import TestCase

from offers import services
from offers.constants import (
    AUDIT_APP_LABEL,
    ConditionStatus,
    OfferAuditAction,
    OfferSource,
    OfferStatus,
)
from offers.exceptions import (
    AcceptedOfferExistsError,
    AmountIncompleteError,
    CatalogueReferenceInvalidError,
    ConditionNoteRequiredError,
    DecisionReasonRequiredError,
    DeferIntakeRequiredError,
    OfferNotDecidableError,
    OfferNotIssuableError,
    ProgramReferenceRequiredError,
)
from offers.tests import factories as f


class OfferCreationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()
        cls.applicant = f.make_applicant(cls.admin)
        cls.journey = f.make_journey(cls.admin, cls.applicant)
        cls.catalogue = f.make_catalogue(cls.admin)

    def test_catalogue_offer_copies_the_snapshot(self) -> None:
        offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])

        self.assertEqual(offer.institution_name_en, "University of Melbourne")
        self.assertEqual(offer.program_title, "Master of Information Technology")
        self.assertEqual(offer.campus_name, "Parkville")
        self.assertEqual(offer.country_name, "Australia")
        self.assertEqual(offer.qualification_level, "masters")
        self.assertEqual(offer.reference_source, OfferSource.CATALOGUE)

    def test_program_implies_its_institution_and_campus(self) -> None:
        """One id is enough — the Program Search path sends only the program."""
        offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])

        self.assertEqual(offer.institution_id, self.catalogue["institution"].id)
        self.assertEqual(offer.campus_id, self.catalogue["campus"].id)

    def test_snapshot_survives_a_later_catalogue_edit(self) -> None:
        """The central promise of this app: history is not rewritten."""
        offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])

        from institutions import services as catalogue_services

        catalogue_services.update_program(
            actor=self.admin,
            program=self.catalogue["program"],
            fields={"title": "Master of Computing (renamed)"},
        )
        catalogue_services.update_institution(
            actor=self.admin,
            institution=self.catalogue["institution"],
            fields={
                "name_en": "Melbourne Uni (renamed)",
                "availability_status": "inactive",
                "availability_note": "No longer working with this provider.",
            },
        )

        offer.refresh_from_db()
        self.assertEqual(offer.program_title, "Master of Information Technology")
        self.assertEqual(offer.institution_name_en, "University of Melbourne")
        # The live link is still intact — the offer points at the record it came
        # from, it simply no longer takes its wording from it.
        self.assertEqual(offer.program_id, self.catalogue["program"].id)

    def test_manual_offer_needs_no_catalogue_record(self) -> None:
        offer = f.make_manual_offer(self.admin, self.journey)

        self.assertEqual(offer.reference_source, OfferSource.MANUAL)
        self.assertIsNone(offer.program_id)
        self.assertEqual(offer.program_title, "Diploma in Hospitality")

    def test_offer_with_no_reference_at_all_is_rejected(self) -> None:
        with self.assertRaises(ProgramReferenceRequiredError):
            services.create_offer(actor=self.admin, journey=self.journey, data={})

    def test_caller_supplied_snapshot_overrides_the_catalogue(self) -> None:
        offer = f.make_offer(
            self.admin,
            self.journey,
            program=self.catalogue["program"],
            intake_label="Feb 2027",
        )

        self.assertEqual(offer.intake_label, "Feb 2027")

    def test_campus_from_another_institution_is_rejected(self) -> None:
        other_institution = self.catalogue["institution"].__class__.objects.create(
            country=self.catalogue["country"], name_en="Other University"
        )
        with self.assertRaises(CatalogueReferenceInvalidError):
            services.create_offer(
                actor=self.admin,
                journey=self.journey,
                data={},
                institution=other_institution,
                campus=self.catalogue["campus"],
            )

    def test_amount_without_currency_is_rejected(self) -> None:
        with self.assertRaises(AmountIncompleteError):
            f.make_offer(
                self.admin,
                self.journey,
                program=self.catalogue["program"],
                deposit_amount=Decimal("5000.00"),
            )

    def test_conditions_are_created_with_the_offer(self) -> None:
        offer = f.make_offer(
            self.admin,
            self.journey,
            program=self.catalogue["program"],
            conditions=[f.condition(), f.condition("academic_result")],
        )

        self.assertEqual(offer.conditions.count(), 2)
        self.assertTrue(offer.has_open_conditions)

    def test_creation_appends_one_audit_event(self) -> None:
        offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])

        events = AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, entity_id=str(offer.id))
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().action, OfferAuditAction.OFFER_CREATED)

    def test_recording_an_offer_does_not_move_the_journey(self) -> None:
        """Journey stage, offer status, and applicant status are separate lifecycles."""
        stage_before = self.journey.stage
        f.make_offer(self.admin, self.journey, program=self.catalogue["program"])

        self.journey.refresh_from_db()
        self.assertEqual(self.journey.stage, stage_before)


class OfferLifecycleTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.journey = f.make_journey(self.admin, self.applicant)
        self.catalogue = f.make_catalogue(self.admin)
        self.offer = f.make_offer(self.admin, self.journey, program=self.catalogue["program"])

    def test_issue_moves_draft_to_issued(self) -> None:
        issued = services.issue_offer(actor=self.admin, offer=self.offer)
        self.assertEqual(issued.status, OfferStatus.ISSUED)

    def test_issuing_twice_is_rejected(self) -> None:
        services.issue_offer(actor=self.admin, offer=self.offer)
        with self.assertRaises(OfferNotIssuableError):
            services.issue_offer(actor=self.admin, offer=self.offer)

    def test_accept_stamps_the_decision(self) -> None:
        decided = services.record_decision(actor=self.admin, offer=self.offer, outcome="accepted")

        self.assertEqual(decided.status, OfferStatus.ACCEPTED)
        self.assertIsNotNone(decided.decided_at)
        self.assertEqual(decided.decided_by, self.admin)
        self.assertTrue(decided.is_terminal)

    def test_a_decided_offer_cannot_be_decided_again(self) -> None:
        services.record_decision(actor=self.admin, offer=self.offer, outcome="accepted")
        with self.assertRaises(OfferNotDecidableError):
            services.record_decision(actor=self.admin, offer=self.offer, outcome="rejected", reason="changed mind")

    def test_reject_requires_a_reason(self) -> None:
        with self.assertRaises(DecisionReasonRequiredError):
            services.record_decision(actor=self.admin, offer=self.offer, outcome="rejected")

    def test_defer_requires_the_target_intake(self) -> None:
        with self.assertRaises(DeferIntakeRequiredError):
            services.record_decision(actor=self.admin, offer=self.offer, outcome="deferred")

    def test_defer_records_the_target_intake(self) -> None:
        decided = services.record_decision(
            actor=self.admin, offer=self.offer, outcome="deferred", to_intake="Jul 2027"
        )
        self.assertEqual(decided.deferred_to_intake, "Jul 2027")

    def test_a_journey_may_hold_several_offers(self) -> None:
        second = f.make_manual_offer(self.admin, self.journey)
        self.assertEqual(self.journey.offers.count(), 2)
        self.assertNotEqual(second.id, self.offer.id)

    def test_only_one_offer_per_journey_may_be_accepted(self) -> None:
        services.record_decision(actor=self.admin, offer=self.offer, outcome="accepted")
        second = f.make_manual_offer(self.admin, self.journey)

        with self.assertRaises(AcceptedOfferExistsError):
            services.record_decision(actor=self.admin, offer=second, outcome="accepted")

    def test_a_second_offer_may_still_be_rejected(self) -> None:
        """The invariant is about acceptance only — competing offers still resolve."""
        services.record_decision(actor=self.admin, offer=self.offer, outcome="accepted")
        second = f.make_manual_offer(self.admin, self.journey)

        decided = services.record_decision(
            actor=self.admin, offer=second, outcome="rejected", reason="Accepted the Melbourne offer instead."
        )
        self.assertEqual(decided.status, OfferStatus.REJECTED)

    def test_update_records_a_change_map(self) -> None:
        services.update_offer(actor=self.admin, offer=self.offer, fields={"offer_reference": "OFR-123"})

        event = AuditEvent.objects.filter(action=OfferAuditAction.OFFER_UPDATED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.changes["offer_reference"]["to"], "OFR-123")

    def test_a_no_op_update_writes_no_event(self) -> None:
        services.update_offer(actor=self.admin, offer=self.offer, fields={"offer_reference": ""})
        self.assertFalse(AuditEvent.objects.filter(action=OfferAuditAction.OFFER_UPDATED).exists())


class ConditionTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.journey = f.make_journey(self.admin, self.applicant)
        self.catalogue = f.make_catalogue(self.admin)
        self.offer = f.make_offer(
            self.admin,
            self.journey,
            program=self.catalogue["program"],
            conditions=[f.condition()],
        )
        self.condition = self.offer.conditions.first()

    def test_satisfying_a_condition_stamps_the_resolver(self) -> None:
        resolved = services.change_condition_status(
            actor=self.admin, condition=self.condition, status=ConditionStatus.SATISFIED
        )

        self.assertEqual(resolved.status, ConditionStatus.SATISFIED)
        self.assertIsNotNone(resolved.resolved_at)
        self.assertEqual(resolved.resolved_by, self.admin)
        self.assertTrue(resolved.is_resolved)

    def test_waiving_requires_a_note(self) -> None:
        with self.assertRaises(ConditionNoteRequiredError):
            services.change_condition_status(actor=self.admin, condition=self.condition, status=ConditionStatus.WAIVED)

    def test_marking_not_applicable_requires_a_note(self) -> None:
        with self.assertRaises(ConditionNoteRequiredError):
            services.change_condition_status(
                actor=self.admin, condition=self.condition, status=ConditionStatus.NOT_APPLICABLE
            )

    def test_reopening_clears_the_resolution_stamp(self) -> None:
        services.change_condition_status(actor=self.admin, condition=self.condition, status=ConditionStatus.SATISFIED)
        reopened = services.change_condition_status(
            actor=self.admin, condition=self.condition, status=ConditionStatus.PENDING
        )

        self.assertIsNone(reopened.resolved_at)
        self.assertIsNone(reopened.resolved_by)

    def test_resolving_every_condition_closes_the_offer_out(self) -> None:
        services.change_condition_status(actor=self.admin, condition=self.condition, status=ConditionStatus.SATISFIED)

        self.offer.refresh_from_db()
        self.assertFalse(self.offer.has_open_conditions)

    def test_condition_events_land_in_the_offer_history(self) -> None:
        """One continuous trail — a condition has no history screen of its own."""
        services.change_condition_status(actor=self.admin, condition=self.condition, status=ConditionStatus.SATISFIED)

        events = AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, entity_id=str(self.offer.id))
        actions = set(events.values_list("action", flat=True))
        self.assertIn(OfferAuditAction.CONDITION_STATUS_CHANGED, actions)

    def test_a_condition_may_be_added_after_the_decision(self) -> None:
        services.record_decision(actor=self.admin, offer=self.offer, outcome="accepted")
        added = services.create_condition(actor=self.admin, offer=self.offer, data=f.condition("deposit_payment"))

        self.assertEqual(added.offer_id, self.offer.id)
