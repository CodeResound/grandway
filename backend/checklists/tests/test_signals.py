"""Automatic inheritance — the behaviour the module exists for.

These are the tests that matter most in this app. Everything else here guards a
rule; these prove the promise: an applicant who settles on a country gets that
country's requirement list without anyone asking, and two applicants headed for
the same place are tracked entirely separately.

``captureOnCommitCallbacks`` is what makes them run at all. The receiver defers
to ``transaction.on_commit``, and a ``TestCase`` wraps each test in a
transaction that never commits — so without the context manager these would all
pass by doing nothing, which is the failure mode worth naming out loud.
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from checklists.constants import ChecklistOrigin, ChecklistStatus, ItemStatus
from checklists.models import Checklist
from checklists.tests.factories import (
    make_admin,
    make_applicant,
    make_catalogue,
    make_country_template,
    make_journey,
    make_template,
    set_journey_country,
)


class InheritanceTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.catalogue = make_catalogue(self.admin)
        self.country = self.catalogue["country"]
        self.template = make_country_template(self.admin, self.country)

    def _journey(self, name_np: str, username_suffix: str) -> object:
        applicant = make_applicant(self.admin, name_np=name_np, full_name_en=username_suffix)
        return make_journey(self.admin, applicant)

    def test_choosing_a_country_inherits_that_countrys_checklist(self) -> None:
        journey = self._journey("राम बहादुर", "Ram")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, journey, self.country)

        checklist = Checklist.objects.get(journey=journey)
        self.assertEqual(checklist.source_template, self.template)
        self.assertEqual(checklist.country, self.country)
        self.assertEqual(checklist.title, self.template.label)
        self.assertEqual(checklist.origin, ChecklistOrigin.AUTO)
        self.assertEqual(checklist.status, ChecklistStatus.ACTIVE)
        # Nobody authored it, and the record says so rather than crediting
        # whoever happened to be editing the journey.
        self.assertIsNone(checklist.created_by)
        self.assertEqual(checklist.items.count(), 3)
        self.assertEqual(
            list(checklist.items.order_by("display_order").values_list("label", flat=True)),
            ["Passport bio page scan", "Academic transcripts", "Application submitted"],
        )

    def test_creating_a_journey_with_a_country_inherits_immediately(self) -> None:
        """Inheritance is not update-only — a journey born with a destination gets its list."""
        applicant = make_applicant(self.admin, name_np="सीता देवी", full_name_en="Sita")

        with self.captureOnCommitCallbacks(execute=True):
            journey = make_journey(self.admin, applicant, target_country_ref=self.country)

        self.assertEqual(Checklist.objects.filter(journey=journey).count(), 1)

    def test_resaving_the_journey_does_not_create_a_second_checklist(self) -> None:
        journey = self._journey("हरि प्रसाद", "Hari")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, journey, self.country)
        with self.captureOnCommitCallbacks(execute=True):
            journey.notes = "Called the applicant."
            journey.save(update_fields=["notes", "updated_at"])
        with self.captureOnCommitCallbacks(execute=True):
            journey.save()

        self.assertEqual(Checklist.objects.filter(journey=journey).count(), 1)

    def test_two_applicants_same_country_are_tracked_separately(self) -> None:
        """The requirement, stated literally: same list, independent progress."""
        first = self._journey("राम बहादुर", "Ram")
        second = self._journey("सीता देवी", "Sita")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, first, self.country)
        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, second, self.country)

        first_list = Checklist.objects.get(journey=first)
        second_list = Checklist.objects.get(journey=second)

        self.assertNotEqual(first_list.pk, second_list.pk)
        self.assertEqual(
            list(first_list.items.order_by("display_order").values_list("label", flat=True)),
            list(second_list.items.order_by("display_order").values_list("label", flat=True)),
        )

        from checklists import services

        item = first_list.items.order_by("display_order").first()
        services.set_item_status(actor=self.admin, item=item, status=ItemStatus.COMPLETED)

        self.assertEqual(first_list.items.filter(status=ItemStatus.COMPLETED).count(), 1)
        self.assertEqual(second_list.items.filter(status=ItemStatus.COMPLETED).count(), 0)

    def test_a_country_with_no_template_inherits_nothing_and_raises_nothing(self) -> None:
        from institutions import services as catalogue_services

        nowhere = catalogue_services.create_country(actor=self.admin, data={"code": "nz", "name_en": "New Zealand"})
        journey = self._journey("गीता शर्मा", "Gita")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, journey, nowhere)

        self.assertFalse(Checklist.objects.filter(journey=journey).exists())

    def test_a_draft_template_is_not_inherited(self) -> None:
        """Only an active default is inheritable — a half-written list is not a policy."""
        from institutions import services as catalogue_services

        from checklists.constants import TemplateStatus

        canada = catalogue_services.create_country(actor=self.admin, data={"code": "ca", "name_en": "Canada"})
        make_template(
            self.admin,
            country=canada,
            key="canada-student",
            label="Canada — Student",
            status=TemplateStatus.DRAFT,
        )
        journey = self._journey("बिनोद थापा", "Binod")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, journey, canada)

        self.assertFalse(Checklist.objects.filter(journey=journey).exists())

    def test_journey_without_a_country_inherits_nothing(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            journey = self._journey("कमल राई", "Kamal")

        self.assertFalse(Checklist.objects.filter(journey=journey).exists())

    @override_settings(DISABLE_SIGNALS=True)
    def test_disable_signals_switches_inheritance_off(self) -> None:
        """The escape hatch §11 requires: a bulk import can turn the handler off."""
        journey = self._journey("प्रकाश गुरुङ", "Prakash")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, journey, self.country)

        self.assertFalse(Checklist.objects.filter(journey=journey).exists())

    def test_archiving_frees_the_journey_to_inherit_again(self) -> None:
        """Archiving is the reset — the one way to ask for a fresh copy."""
        from checklists import services

        journey = self._journey("अनिता के.सी.", "Anita")

        with self.captureOnCommitCallbacks(execute=True):
            set_journey_country(self.admin, journey, self.country)

        first = Checklist.objects.get(journey=journey)
        services.archive_checklist(actor=self.admin, checklist=first, reason="Applicant restarted their file.")

        with self.captureOnCommitCallbacks(execute=True):
            journey.save()

        self.assertEqual(Checklist.objects.filter(journey=journey).count(), 2)
        self.assertEqual(Checklist.objects.filter(journey=journey, status=ChecklistStatus.ACTIVE).count(), 1)


class BackfillCommandTests(TestCase):
    """``apply_country_checklists`` — the path for journeys the signal missed."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.catalogue = make_catalogue(self.admin)
        self.country = self.catalogue["country"]

    def _journey_with_country_but_no_template(self) -> object:
        applicant = make_applicant(self.admin, name_np="राम बहादुर", full_name_en="Ram")
        # No template exists yet, so nothing is inherited — the common real case:
        # the destination is recorded before anyone authors its requirements.
        with self.captureOnCommitCallbacks(execute=True):
            return make_journey(self.admin, applicant, target_country_ref=self.country)

    def test_command_applies_the_template_authored_after_the_journey(self) -> None:
        from io import StringIO

        from django.core.management import call_command

        journey = self._journey_with_country_but_no_template()
        self.assertFalse(Checklist.objects.filter(journey=journey).exists())

        make_country_template(self.admin, self.country)
        call_command("apply_country_checklists", stdout=StringIO())

        self.assertEqual(Checklist.objects.filter(journey=journey).count(), 1)

    def test_dry_run_writes_nothing(self) -> None:
        from io import StringIO

        from django.core.management import call_command

        journey = self._journey_with_country_but_no_template()
        make_country_template(self.admin, self.country)

        out = StringIO()
        call_command("apply_country_checklists", "--dry-run", stdout=out)

        self.assertFalse(Checklist.objects.filter(journey=journey).exists())
        self.assertIn("would create 1", out.getvalue())

    def test_command_is_idempotent(self) -> None:
        from io import StringIO

        from django.core.management import call_command

        journey = self._journey_with_country_but_no_template()
        make_country_template(self.admin, self.country)

        call_command("apply_country_checklists", stdout=StringIO())
        call_command("apply_country_checklists", stdout=StringIO())

        self.assertEqual(Checklist.objects.filter(journey=journey).count(), 1)
