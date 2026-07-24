"""Service-level tests for the checklists app.

Grouped by the rule each class defends rather than by function name, because
every one of these rules is a decision someone could reasonably have made
differently — the snapshot guarantee, the single default, what "complete"
actually requires, and whose files may be cited as proof.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from checklists import services
from checklists.constants import ChecklistOrigin, ChecklistStatus, ItemStatus, ItemType, TemplateStatus
from checklists.exceptions import (
    ArchiveReasonRequiredError,
    ChecklistArchivedError,
    ChecklistNotArchivedError,
    DefaultRequiresCountryError,
    DefaultTemplateExistsError,
    EvidenceNotAllowedError,
    InvalidTransitionError,
    RequiredItemsPendingError,
    StatusNoteRequiredError,
    TemplateAlreadyAppliedError,
    TemplateHasNoItemsError,
    TemplateNotActiveError,
)
from checklists.models import Checklist, ChecklistTemplate
from checklists.selectors import get_checklist_by_id
from checklists.tests.factories import (
    add_requirement,
    make_admin,
    make_applicant,
    make_catalogue,
    make_country_template,
    make_journey,
    make_template,
    upload_for,
    upload_for_applicant,
)


class BaseChecklistTest(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.catalogue = make_catalogue(self.admin)
        self.country = self.catalogue["country"]
        self.applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, self.applicant)
        self.template = make_country_template(self.admin, self.country)

    def apply(self, **overrides: object) -> Checklist:
        return services.instantiate_checklist(
            journey=self.journey,
            template=self.template,
            actor=self.admin,
            **overrides,
        )


class TemplateAuthoringTests(BaseChecklistTest):
    def test_a_country_may_have_only_one_active_default(self) -> None:
        with self.assertRaises(DefaultTemplateExistsError) as ctx:
            make_template(self.admin, country=self.country, key="australia-second", label="Australia — Second")
        # The refusal names the template already holding the slot, so an Admin
        # does not have to go looking for it.
        self.assertEqual(ctx.exception.existing.pk, self.template.pk)

    def test_a_non_default_template_for_the_same_country_is_fine(self) -> None:
        other = make_template(
            self.admin,
            country=self.country,
            key="australia-scholarship",
            label="Australia — Scholarship Route",
            is_default=False,
        )
        self.assertFalse(other.is_default)
        self.assertFalse(other.is_inheritable)

    def test_a_default_must_name_a_country(self) -> None:
        with self.assertRaises(DefaultRequiresCountryError):
            make_template(self.admin, country=None, key="general", label="General")

    def test_a_retired_default_frees_the_slot(self) -> None:
        services.update_template(
            actor=self.admin,
            template=self.template,
            fields={"status": TemplateStatus.INACTIVE},
        )
        replacement = make_template(
            self.admin,
            country=self.country,
            key="australia-2026",
            label="Australia — 2026 rules",
        )
        self.assertTrue(replacement.is_inheritable)


class SnapshotTests(BaseChecklistTest):
    """Instantiation is a copy, not a subscription. The module's core promise."""

    def test_instantiation_copies_every_active_requirement_in_order(self) -> None:
        checklist = self.apply()
        self.assertEqual(
            list(checklist.items.order_by("display_order").values_list("label", "item_type", "is_required")),
            [
                ("Passport bio page scan", ItemType.DOCUMENT, True),
                ("Academic transcripts", ItemType.DOCUMENT, True),
                ("Application submitted", ItemType.STAGE, False),
            ],
        )
        self.assertEqual(checklist.title, self.template.label)
        self.assertEqual(checklist.country, self.country)
        self.assertEqual(checklist.status, ChecklistStatus.ACTIVE)

    def test_retired_requirements_are_not_copied(self) -> None:
        retired = add_requirement(self.admin, self.template, label="Old police report")
        services.update_template_item(actor=self.admin, item=retired, fields={"is_active": False})

        checklist = self.apply()
        self.assertNotIn("Old police report", checklist.items.values_list("label", flat=True))

    def test_editing_the_template_afterwards_leaves_live_checklists_untouched(self) -> None:
        checklist = self.apply()
        before = set(checklist.items.values_list("label", flat=True))

        add_requirement(self.admin, self.template, label="Medical certificate")
        services.update_template(actor=self.admin, template=self.template, fields={"label": "Australia — v2"})

        checklist.refresh_from_db()
        self.assertEqual(set(checklist.items.values_list("label", flat=True)), before)
        self.assertEqual(checklist.title, "Australia — Student Visa")

    def test_due_dates_are_derived_from_the_template_offsets(self) -> None:
        template = make_template(
            self.admin,
            country=None,
            key="with-offsets",
            label="With offsets",
            is_default=False,
        )
        add_requirement(self.admin, template, label="Within a week", default_due_offset_days=7)
        add_requirement(self.admin, template, label="No deadline")

        checklist = services.instantiate_checklist(journey=self.journey, template=template, actor=self.admin)
        dated = checklist.items.get(label="Within a week")
        undated = checklist.items.get(label="No deadline")

        self.assertIsNotNone(dated.due_at)
        self.assertGreater(dated.due_at, timezone.now())
        self.assertIsNone(undated.due_at)

    def test_a_draft_template_cannot_be_applied(self) -> None:
        draft = make_template(
            self.admin,
            country=None,
            key="draft-list",
            label="Draft",
            is_default=False,
            status=TemplateStatus.DRAFT,
        )
        add_requirement(self.admin, draft, label="Something")
        with self.assertRaises(TemplateNotActiveError):
            services.instantiate_checklist(journey=self.journey, template=draft, actor=self.admin)

    def test_an_empty_template_cannot_be_applied(self) -> None:
        empty = make_template(self.admin, country=None, key="empty", label="Empty", is_default=False)
        with self.assertRaises(TemplateHasNoItemsError):
            services.instantiate_checklist(journey=self.journey, template=empty, actor=self.admin)

    def test_the_same_template_cannot_be_applied_twice(self) -> None:
        self.apply()
        with self.assertRaises(TemplateAlreadyAppliedError):
            self.apply()


class CompletionTests(BaseChecklistTest):
    """Completion is derived from the items, never asserted."""

    def setUp(self) -> None:
        super().setUp()
        self.checklist = self.apply()

    def _items(self) -> list[object]:
        return list(self.checklist.items.order_by("display_order"))

    def test_completion_is_refused_while_a_required_item_is_pending(self) -> None:
        with self.assertRaises(RequiredItemsPendingError) as ctx:
            services.complete_checklist(actor=self.admin, checklist=self.checklist)
        # The refusal names the offending items — "something is pending" on a
        # long list is not an answer anyone can act on.
        self.assertEqual(
            {item.label for item in ctx.exception.items}, {"Passport bio page scan", "Academic transcripts"}
        )

    def test_a_blocked_required_item_still_blocks_completion(self) -> None:
        for item in self._items():
            if item.is_required:
                services.set_item_status(
                    actor=self.admin,
                    item=item,
                    status=ItemStatus.BLOCKED,
                    status_note="Waiting on the university.",
                )
        with self.assertRaises(RequiredItemsPendingError):
            services.complete_checklist(actor=self.admin, checklist=self.checklist)

    def test_waived_and_not_applicable_required_items_do_not_block(self) -> None:
        required = [item for item in self._items() if item.is_required]
        services.set_item_status(actor=self.admin, item=required[0], status=ItemStatus.COMPLETED)
        services.set_item_status(
            actor=self.admin,
            item=required[1],
            status=ItemStatus.WAIVED,
            status_note="Institution accepted a provisional copy.",
        )

        completed = services.complete_checklist(actor=self.admin, checklist=self.checklist)
        self.assertEqual(completed.status, ChecklistStatus.COMPLETED)
        self.assertEqual(completed.completed_by, self.admin)
        self.assertIsNotNone(completed.completed_at)

    def test_an_optional_item_never_blocks_completion(self) -> None:
        for item in self._items():
            if item.is_required:
                services.set_item_status(actor=self.admin, item=item, status=ItemStatus.COMPLETED)
        optional = self.checklist.items.get(is_required=False)
        self.assertEqual(optional.status, ItemStatus.PENDING)

        services.complete_checklist(actor=self.admin, checklist=self.checklist)
        self.checklist.refresh_from_db()
        self.assertEqual(self.checklist.status, ChecklistStatus.COMPLETED)

    def test_a_completed_checklist_refuses_item_edits_until_reopened(self) -> None:
        for item in self._items():
            if item.is_required:
                services.set_item_status(actor=self.admin, item=item, status=ItemStatus.COMPLETED)
        services.complete_checklist(actor=self.admin, checklist=self.checklist)

        optional = self.checklist.items.get(is_required=False)
        with self.assertRaises(InvalidTransitionError):
            services.set_item_status(actor=self.admin, item=optional, status=ItemStatus.COMPLETED)

        services.reopen_checklist(actor=self.admin, checklist=self.checklist)
        self.checklist.refresh_from_db()
        self.assertEqual(self.checklist.status, ChecklistStatus.ACTIVE)
        # Reopening clears the stamps: a reopened checklist must not read as
        # finished to anything querying ``completed_at``.
        self.assertIsNone(self.checklist.completed_at)
        self.assertIsNone(self.checklist.completed_by)

        services.set_item_status(actor=self.admin, item=optional, status=ItemStatus.COMPLETED)

    def test_progress_counts_come_from_the_annotation(self) -> None:
        required = [item for item in self._items() if item.is_required]
        services.set_item_status(actor=self.admin, item=required[0], status=ItemStatus.COMPLETED)

        annotated = get_checklist_by_id(str(self.checklist.id))
        self.assertEqual(annotated.item_total, 3)
        self.assertEqual(annotated.item_resolved, 1)
        self.assertEqual(annotated.required_total, 2)
        self.assertEqual(annotated.required_resolved, 1)
        self.assertEqual(annotated.document_total, 2)


class ItemStatusTests(BaseChecklistTest):
    def setUp(self) -> None:
        super().setUp()
        self.checklist = self.apply()
        self.item = self.checklist.items.order_by("display_order").first()

    def test_waiving_without_a_note_is_refused(self) -> None:
        with self.assertRaises(StatusNoteRequiredError):
            services.set_item_status(actor=self.admin, item=self.item, status=ItemStatus.WAIVED)

    def test_blocking_without_a_note_is_refused(self) -> None:
        with self.assertRaises(StatusNoteRequiredError):
            services.set_item_status(actor=self.admin, item=self.item, status=ItemStatus.BLOCKED)

    def test_completion_stamps_follow_the_status_rather_than_accumulating(self) -> None:
        services.set_item_status(actor=self.admin, item=self.item, status=ItemStatus.COMPLETED)
        self.item.refresh_from_db()
        self.assertIsNotNone(self.item.completed_at)
        self.assertEqual(self.item.completed_by, self.admin)

        services.set_item_status(actor=self.admin, item=self.item, status=ItemStatus.PENDING)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.completed_at)
        self.assertIsNone(self.item.completed_by)


class EvidenceTests(BaseChecklistTest):
    """Whose files may be cited as proof — the check that keeps this app honest."""

    def setUp(self) -> None:
        super().setUp()
        self.checklist = self.apply()
        self.item = self.checklist.items.order_by("display_order").first()

    def test_a_file_on_this_applicant_may_be_cited(self) -> None:
        evidence = upload_for_applicant(self.admin, self.applicant)
        updated = services.set_item_status(
            actor=self.admin,
            item=self.item,
            status=ItemStatus.COMPLETED,
            evidence_file_id=evidence.id,
        )
        self.assertEqual(updated.evidence_file_id, evidence.id)

    def test_a_file_on_this_journey_may_be_cited(self) -> None:
        evidence = upload_for(self.admin, "journey", self.journey)
        updated = services.set_item_status(
            actor=self.admin,
            item=self.item,
            status=ItemStatus.COMPLETED,
            evidence_file_id=evidence.id,
        )
        self.assertEqual(updated.evidence_file_id, evidence.id)

    def test_another_applicants_file_is_refused(self) -> None:
        stranger = make_applicant(self.admin, full_name="Someone Else")
        theirs = upload_for_applicant(self.admin, stranger)

        with self.assertRaises(EvidenceNotAllowedError):
            services.set_item_status(
                actor=self.admin,
                item=self.item,
                status=ItemStatus.COMPLETED,
                evidence_file_id=theirs.id,
            )
        self.item.refresh_from_db()
        self.assertIsNone(self.item.evidence_file_id)
        self.assertEqual(self.item.status, ItemStatus.PENDING)

    def test_an_unknown_file_id_is_refused(self) -> None:
        import uuid

        with self.assertRaises(EvidenceNotAllowedError):
            services.set_item_status(
                actor=self.admin,
                item=self.item,
                status=ItemStatus.COMPLETED,
                evidence_file_id=uuid.uuid4(),
            )

    def test_evidence_can_be_cleared_explicitly(self) -> None:
        evidence = upload_for_applicant(self.admin, self.applicant)
        services.set_item_status(
            actor=self.admin,
            item=self.item,
            status=ItemStatus.COMPLETED,
            evidence_file_id=evidence.id,
        )
        services.set_item_status(
            actor=self.admin,
            item=self.item,
            status=ItemStatus.PENDING,
            clear_evidence=True,
        )
        self.item.refresh_from_db()
        self.assertIsNone(self.item.evidence_file_id)


class ArchiveTests(BaseChecklistTest):
    def setUp(self) -> None:
        super().setUp()
        self.checklist = self.apply()

    def test_archiving_requires_a_reason(self) -> None:
        with self.assertRaises(ArchiveReasonRequiredError):
            services.archive_checklist(actor=self.admin, checklist=self.checklist, reason="   ")

    def test_an_archived_checklist_refuses_edits(self) -> None:
        services.archive_checklist(actor=self.admin, checklist=self.checklist, reason="Duplicate.")
        with self.assertRaises(ChecklistArchivedError):
            services.update_checklist(actor=self.admin, checklist=self.checklist, fields={"title": "New"})

    def test_restore_returns_it_to_active_and_clears_the_archive_columns(self) -> None:
        services.archive_checklist(actor=self.admin, checklist=self.checklist, reason="Duplicate.")
        restored = services.restore_checklist(actor=self.admin, checklist=self.checklist)

        self.assertEqual(restored.status, ChecklistStatus.ACTIVE)
        self.assertEqual(restored.archive_reason, "")
        self.assertIsNone(restored.archived_at)
        self.assertIsNone(restored.archived_by)
        self.assertEqual(restored.status_before_archive, "")

    def test_restore_puts_a_completed_checklist_back_as_completed(self) -> None:
        """Regression: restore must not silently reopen a completed checklist.

        The first implementation inferred the restored status from
        ``activated_at``, so archiving a completed checklist and restoring it
        produced an ``active`` one still carrying ``completed_at`` — a screen
        reading "completed on the 3rd" above unfinished work. Found by the §19.5
        consumer-contract review, not by a test.
        """
        for item in self.checklist.items.filter(is_required=True):
            services.set_item_status(actor=self.admin, item=item, status=ItemStatus.COMPLETED)
        services.complete_checklist(actor=self.admin, checklist=self.checklist)
        completed_at = self.checklist.completed_at

        services.archive_checklist(actor=self.admin, checklist=self.checklist, reason="Filed away.")
        restored = services.restore_checklist(actor=self.admin, checklist=self.checklist)

        self.assertEqual(restored.status, ChecklistStatus.COMPLETED)
        self.assertEqual(restored.completed_at, completed_at)
        self.assertEqual(restored.completed_by, self.admin)

    def test_restore_puts_a_draft_checklist_back_as_a_draft(self) -> None:
        draft = services.create_blank_checklist(
            actor=self.admin,
            journey=self.journey,
            data={"title": "Internal review"},
        )
        services.archive_checklist(actor=self.admin, checklist=draft, reason="Not needed.")
        restored = services.restore_checklist(actor=self.admin, checklist=draft)

        self.assertEqual(restored.status, ChecklistStatus.DRAFT)

    def test_restore_on_a_live_checklist_is_refused(self) -> None:
        with self.assertRaises(ChecklistNotArchivedError):
            services.restore_checklist(actor=self.admin, checklist=self.checklist)


class BlankChecklistTests(BaseChecklistTest):
    def test_a_blank_checklist_starts_as_a_draft_and_activates(self) -> None:
        checklist = services.create_blank_checklist(
            actor=self.admin,
            journey=self.journey,
            data={"title": "Internal review"},
        )
        self.assertEqual(checklist.status, ChecklistStatus.DRAFT)
        self.assertEqual(checklist.origin, ChecklistOrigin.MANUAL)
        self.assertIsNone(checklist.source_template)

        activated = services.activate_checklist(actor=self.admin, checklist=checklist)
        self.assertEqual(activated.status, ChecklistStatus.ACTIVE)
        self.assertIsNotNone(activated.activated_at)

    def test_activating_twice_is_refused(self) -> None:
        checklist = services.create_blank_checklist(
            actor=self.admin,
            journey=self.journey,
            data={"title": "Internal review"},
        )
        services.activate_checklist(actor=self.admin, checklist=checklist)
        with self.assertRaises(InvalidTransitionError):
            services.activate_checklist(actor=self.admin, checklist=checklist)

    def test_an_ad_hoc_item_never_reaches_the_template(self) -> None:
        checklist = self.apply()
        services.add_checklist_item(
            actor=self.admin,
            checklist=checklist,
            data={"label": "Extra reference letter"},
        )
        self.assertEqual(checklist.items.count(), 4)
        self.assertEqual(ChecklistTemplate.objects.get(pk=self.template.pk).items.count(), 3)
