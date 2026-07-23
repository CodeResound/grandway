"""Service-level rules: availability, tuition completeness, campus placement, audit, PROTECT."""

from __future__ import annotations

from decimal import Decimal

from audit.models import AuditEvent
from django.db.models import ProtectedError
from django.test import TestCase

from institutions import services
from institutions.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_PROGRAM,
    AvailabilityStatus,
    CatalogueAuditAction,
)
from institutions.exceptions import (
    AvailabilityNoteRequiredError,
    CampusInstitutionMismatchError,
    TuitionIncompleteError,
)
from institutions.models import Program
from institutions.tests.factories import (
    make_admin,
    make_campus,
    make_country,
    make_field,
    make_institution,
    make_program,
    priced,
)


class CatalogueServiceTestCase(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.field = make_field(self.admin)
        self.country = make_country(self.admin)
        self.institution = make_institution(self.admin, self.country)


class TestAvailabilityRules(CatalogueServiceTestCase):
    def test_non_active_status_requires_a_note(self) -> None:
        """A record withdrawn from use with no stated reason is the drift the catalogue prevents."""
        with self.assertRaises(AvailabilityNoteRequiredError):
            make_country(
                self.admin,
                code="ca",
                availability_status=AvailabilityStatus.PAUSED,
            )

    def test_seasonal_also_requires_a_note(self) -> None:
        with self.assertRaises(AvailabilityNoteRequiredError):
            make_country(self.admin, code="nz", availability_status=AvailabilityStatus.SEASONAL)

    def test_active_needs_no_note(self) -> None:
        country = make_country(self.admin, code="gb")
        self.assertEqual(country.availability_status, AvailabilityStatus.ACTIVE)
        self.assertTrue(country.is_usable)

    def test_update_checks_the_resulting_state_not_the_patch(self) -> None:
        """Patching only the status, leaving an empty note behind, must still fail."""
        with self.assertRaises(AvailabilityNoteRequiredError):
            services.update_country(
                actor=self.admin,
                country=self.country,
                fields={"availability_status": AvailabilityStatus.INACTIVE},
            )

    def test_status_and_note_together_succeed(self) -> None:
        country = services.update_country(
            actor=self.admin,
            country=self.country,
            fields={
                "availability_status": AvailabilityStatus.INACTIVE,
                "availability_note": "Visa route closed for 2026.",
            },
        )
        self.assertEqual(country.availability_status, AvailabilityStatus.INACTIVE)
        self.assertFalse(country.is_usable)

    def test_seasonal_counts_as_usable(self) -> None:
        """Seasonal is offered, just not year-round — hiding it would remove real options.

        It still needs a note: "seasonal" without saying which season is not an
        explanation.
        """
        country = make_country(
            self.admin,
            code="ie",
            availability_status=AvailabilityStatus.SEASONAL,
            availability_note="September intake only.",
        )
        self.assertTrue(country.is_usable)

    def test_availability_does_not_cascade(self) -> None:
        """Pausing a country leaves its programs' own recorded state untouched."""
        program = make_program(self.admin, self.institution, self.field)
        services.update_country(
            actor=self.admin,
            country=self.country,
            fields={
                "availability_status": AvailabilityStatus.PAUSED,
                "availability_note": "Reviewing partner agreement.",
            },
        )
        program.refresh_from_db()
        self.assertEqual(program.availability_status, AvailabilityStatus.ACTIVE)


class TestTuitionRules(CatalogueServiceTestCase):
    def test_amount_without_currency_is_rejected(self) -> None:
        with self.assertRaises(TuitionIncompleteError):
            make_program(
                self.admin,
                self.institution,
                self.field,
                tuition_amount=Decimal("49824.00"),
                tuition_fee_period="total_program",
            )

    def test_amount_without_fee_period_is_rejected(self) -> None:
        with self.assertRaises(TuitionIncompleteError):
            make_program(
                self.admin,
                self.institution,
                self.field,
                tuition_amount=Decimal("49824.00"),
                tuition_currency="AUD",
            )

    def test_complete_tuition_is_accepted_and_keeps_decimal_precision(self) -> None:
        program = make_program(self.admin, self.institution, self.field, **priced("49824.55"))
        program.refresh_from_db()
        self.assertEqual(program.tuition_amount, Decimal("49824.55"))
        self.assertTrue(program.has_tuition)

    def test_no_tuition_at_all_is_fine(self) -> None:
        """An incomplete catalogue record is explicitly allowed by the concept."""
        program = make_program(self.admin, self.institution, self.field)
        self.assertIsNone(program.tuition_amount)
        self.assertFalse(program.has_tuition)

    def test_clearing_the_currency_on_a_priced_program_is_rejected(self) -> None:
        """The resulting state is what matters, not which field the patch touched."""
        program = make_program(self.admin, self.institution, self.field, **priced())
        with self.assertRaises(TuitionIncompleteError):
            services.update_program(
                actor=self.admin,
                program=program,
                fields={"tuition_currency": ""},
            )


class TestCampusPlacement(CatalogueServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other_institution = make_institution(self.admin, self.country, name_en="Monash University")

    def test_campus_of_another_institution_is_rejected(self) -> None:
        """Both FKs resolve individually — only this check catches the mismatch."""
        foreign_campus = make_campus(self.admin, self.other_institution, name_en="Clayton")
        with self.assertRaises(CampusInstitutionMismatchError):
            make_program(self.admin, self.institution, self.field, campus=foreign_campus)

    def test_campus_of_the_same_institution_is_accepted(self) -> None:
        campus = make_campus(self.admin, self.institution)
        program = make_program(self.admin, self.institution, self.field, campus=campus)
        self.assertEqual(program.campus_id, campus.id)

    def test_no_campus_is_accepted(self) -> None:
        program = make_program(self.admin, self.institution, self.field)
        self.assertIsNone(program.campus)

    def test_moving_a_program_to_a_foreign_campus_is_rejected(self) -> None:
        program = make_program(self.admin, self.institution, self.field)
        foreign_campus = make_campus(self.admin, self.other_institution, name_en="Caulfield")
        with self.assertRaises(CampusInstitutionMismatchError):
            services.update_program(actor=self.admin, program=program, fields={"campus": foreign_campus})


class TestAuditTrail(CatalogueServiceTestCase):
    def test_create_records_one_event(self) -> None:
        program = make_program(self.admin, self.institution, self.field)
        event = AuditEvent.objects.get(
            app_label=AUDIT_APP_LABEL,
            entity_type=AUDIT_ENTITY_PROGRAM,
            entity_id=str(program.id),
        )
        self.assertEqual(event.action, CatalogueAuditAction.PROGRAM_CREATED)
        self.assertEqual(str(event.actor_id), str(self.admin.id))

    def test_update_records_the_previous_and_new_values(self) -> None:
        """The concept requires that earlier values stay visible in history."""
        program = make_program(self.admin, self.institution, self.field)
        services.update_program(actor=self.admin, program=program, fields={"title": "Master of IT (Advanced)"})
        event = AuditEvent.objects.get(
            entity_id=str(program.id),
            action=CatalogueAuditAction.PROGRAM_UPDATED,
        )
        self.assertEqual(event.changes["title"]["from"], "Master of Information Technology")
        self.assertEqual(event.changes["title"]["to"], "Master of IT (Advanced)")

    def test_a_no_op_update_writes_no_event(self) -> None:
        """A PATCH that changes nothing must not fabricate a 'record updated' entry."""
        program = make_program(self.admin, self.institution, self.field)
        services.update_program(
            actor=self.admin,
            program=program,
            fields={"title": "Master of Information Technology"},
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                entity_id=str(program.id),
                action=CatalogueAuditAction.PROGRAM_UPDATED,
            ).exists()
        )


class TestNothingIsDeleted(CatalogueServiceTestCase):
    def test_country_with_institutions_is_protected(self) -> None:
        with self.assertRaises(ProtectedError):
            self.country.delete()

    def test_institution_with_programs_is_protected(self) -> None:
        make_program(self.admin, self.institution, self.field)
        with self.assertRaises(ProtectedError):
            self.institution.delete()

    def test_field_in_use_is_protected(self) -> None:
        make_program(self.admin, self.institution, self.field)
        with self.assertRaises(ProtectedError):
            self.field.delete()

    def test_campus_in_use_is_protected(self) -> None:
        campus = make_campus(self.admin, self.institution)
        make_program(self.admin, self.institution, self.field, campus=campus)
        with self.assertRaises(ProtectedError):
            campus.delete()

    def test_an_inactive_program_still_resolves(self) -> None:
        """A withdrawn program must stay readable for whatever referenced it."""
        program = make_program(self.admin, self.institution, self.field)
        services.update_program(
            actor=self.admin,
            program=program,
            fields={
                "availability_status": AvailabilityStatus.INACTIVE,
                "availability_note": "No longer offered from 2027.",
            },
        )
        self.assertTrue(Program.objects.filter(pk=program.pk).exists())
