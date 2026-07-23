"""Service-level unit tests: derived fields, normalization, and transition rules.

These exercise the rules directly rather than through HTTP, so a rule stays
enforced even if a future caller reaches the service by another path.
"""

from __future__ import annotations

from audit.models import AuditEvent
from core.nepal.text import normalize_unicode
from django.test import TestCase

from leads import services
from leads.constants import AUDIT_APP_LABEL, LeadStage
from leads.exceptions import (
    ContactNumberRequiredError,
    InvalidStageTransitionError,
    LeadNotLostError,
    LossDetailRequiredError,
    LossReasonRequiredError,
    ReferenceCodeTakenError,
    ReferenceInactiveError,
    SourceDetailRequiredError,
    StageNotEditableError,
)
from leads.models import LeadContactNumber, LeadStudyInterest
from leads.tests.factories import (
    make_admin,
    make_lead,
    make_lead_manager,
    make_loss_reason,
    make_source,
)


class TestLeadCreation(TestCase):
    def setUp(self) -> None:
        self.owner = make_lead_manager("owner")
        self.source = make_source()

    def test_romanized_name_is_derived_from_devanagari(self) -> None:
        lead = make_lead(self.owner, self.source, name_np="राम श्रेष्ठ")
        self.assertNotEqual(lead.full_name_romanized, "")
        self.assertTrue(lead.full_name_romanized.isascii())

    def test_supplied_romanized_name_is_respected(self) -> None:
        lead = services.create_lead(
            actor=self.owner,
            data={
                "full_name_np": "राम श्रेष्ठ",
                "full_name_romanized": "Ram Shrestha",
                "source": self.source,
            },
            contact_numbers=[{"number": "9800000000"}],
        )
        self.assertEqual(lead.full_name_romanized, "Ram Shrestha")

    def test_devanagari_name_is_unicode_normalized(self) -> None:
        raw = "राम"
        lead = make_lead(self.owner, self.source, name_np=raw)
        self.assertEqual(lead.full_name_np, normalize_unicode(raw))

    def test_at_least_one_contact_number_is_required(self) -> None:
        with self.assertRaises(ContactNumberRequiredError):
            services.create_lead(
                actor=self.owner,
                data={"full_name_np": "राम", "source": self.source},
                contact_numbers=[],
            )

    def test_inactive_source_is_rejected(self) -> None:
        retired = make_source(code="retired", is_active=False)
        with self.assertRaises(ReferenceInactiveError):
            services.create_lead(
                actor=self.owner,
                data={"full_name_np": "राम", "source": retired},
                contact_numbers=[{"number": "9800000000"}],
            )

    def test_catch_all_source_requires_detail(self) -> None:
        other = make_source(code="other", requires_detail=True)
        with self.assertRaises(SourceDetailRequiredError):
            services.create_lead(
                actor=self.owner,
                data={"full_name_np": "राम", "source": other},
                contact_numbers=[{"number": "9800000000"}],
            )

    def test_creation_appends_exactly_one_audit_event(self) -> None:
        lead = make_lead(self.owner, self.source)
        events = AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, entity_id=str(lead.id))
        self.assertEqual(events.count(), 1)


class TestLeadUpdate(TestCase):
    def setUp(self) -> None:
        self.owner = make_lead_manager("owner")
        self.source = make_source()
        self.lead = make_lead(self.owner, self.source)

    def test_contact_numbers_replace_rather_than_append(self) -> None:
        services.update_lead(
            actor=self.owner,
            lead=self.lead,
            fields={},
            contact_numbers=[{"number": "9811111111"}, {"number": "9822222222"}],
        )
        numbers = set(LeadContactNumber.objects.filter(lead=self.lead).values_list("number", flat=True))
        self.assertEqual(numbers, {"9811111111", "9822222222"})

    def test_study_interest_upserts(self) -> None:
        services.update_lead(
            actor=self.owner,
            lead=self.lead,
            fields={},
            study_interest={"study_level": "masters"},
        )
        services.update_lead(
            actor=self.owner,
            lead=self.lead,
            fields={},
            study_interest={"study_level": "bachelors"},
        )
        interests = LeadStudyInterest.objects.filter(lead=self.lead)
        self.assertEqual(interests.count(), 1)
        self.assertEqual(interests.first().study_level, "bachelors")


class TestStageRules(TestCase):
    def setUp(self) -> None:
        self.owner = make_lead_manager("owner")
        self.source = make_source()
        self.reason = make_loss_reason()
        self.lead = make_lead(self.owner, self.source)

    def test_terminal_stages_are_not_selectable(self) -> None:
        for stage in (LeadStage.LOST, LeadStage.CONVERTED):
            with self.assertRaises(InvalidStageTransitionError):
                services.change_stage(actor=self.owner, lead=self.lead, stage=stage)

    def test_no_op_stage_change_writes_no_event(self) -> None:
        before = AuditEvent.objects.count()
        services.change_stage(actor=self.owner, lead=self.lead, stage=LeadStage.NEW)
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_lost_lead_stage_is_frozen(self) -> None:
        services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=self.reason)
        with self.assertRaises(StageNotEditableError):
            services.change_stage(actor=self.owner, lead=self.lead, stage=LeadStage.CONTACTED)


class TestLossAndReopen(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.source = make_source()
        self.reason = make_loss_reason()
        self.lead = make_lead(self.owner, self.source)

    def test_reason_is_mandatory(self) -> None:
        with self.assertRaises(LossReasonRequiredError):
            services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=None)

    def test_catch_all_reason_requires_detail(self) -> None:
        other = make_loss_reason(code="other", requires_detail=True)
        with self.assertRaises(LossDetailRequiredError):
            services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=other)

    def test_inactive_reason_is_rejected(self) -> None:
        retired = make_loss_reason(code="retired", is_active=False)
        with self.assertRaises(ReferenceInactiveError):
            services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=retired)

    def test_previous_stage_is_remembered(self) -> None:
        services.change_stage(actor=self.owner, lead=self.lead, stage=LeadStage.COUNSELLING)
        services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=self.reason)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage_before_loss, LeadStage.COUNSELLING)

    def test_reopen_requires_a_terminal_lead(self) -> None:
        with self.assertRaises(LeadNotLostError):
            services.reopen_lead(actor=self.owner, lead=self.lead)

    def test_reopen_must_land_on_an_active_stage(self) -> None:
        services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=self.reason)
        with self.assertRaises(InvalidStageTransitionError):
            services.reopen_lead(actor=self.owner, lead=self.lead, stage=LeadStage.CONVERTED)

    def test_reopen_clears_every_loss_field(self) -> None:
        services.mark_lost(actor=self.owner, lead=self.lead, loss_reason=self.reason, detail="No answer.")
        services.reopen_lead(actor=self.owner, lead=self.lead)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.lost_reason)
        self.assertIsNone(self.lead.lost_at)
        self.assertIsNone(self.lead.lost_by)
        self.assertEqual(self.lead.lost_detail, "")
        self.assertEqual(self.lead.stage_before_loss, "")


class TestReferenceServices(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()

    def test_duplicate_source_code_is_rejected(self) -> None:
        services.create_lead_source(actor=self.admin, data={"code": "walk_in", "name_np": "वाक-इन"})
        with self.assertRaises(ReferenceCodeTakenError):
            services.create_lead_source(actor=self.admin, data={"code": "walk_in", "name_np": "वाक-इन"})

    def test_duplicate_loss_reason_code_is_rejected(self) -> None:
        services.create_loss_reason(actor=self.admin, data={"code": "other", "name_np": "अन्य"})
        with self.assertRaises(ReferenceCodeTakenError):
            services.create_loss_reason(actor=self.admin, data={"code": "other", "name_np": "अन्य"})

    def test_update_without_changes_writes_no_event(self) -> None:
        source = services.create_lead_source(actor=self.admin, data={"code": "web", "name_np": "वेब"})
        before = AuditEvent.objects.count()
        services.update_lead_source(actor=self.admin, source=source, fields={"is_active": True})
        self.assertEqual(AuditEvent.objects.count(), before)
