"""Dashboard sections against a seeded world: do the numbers say what they claim?

`test_views.py` proves the endpoints answer and validate. This proves they
*count correctly*, which for an app that owns no data is the only thing left to
get wrong.

The cases worth the most here are the ones where a plausible implementation
would be quietly wrong: overdue and due-soon double-counting the same item, a
completed checklist's items still appearing as outstanding, a blocked item being
treated as resolved, an already-expired passport being filtered out of the
expiring list, and — the one with real consequences — a Lead Manager seeing
another manager's pipeline in aggregate.
"""

from __future__ import annotations

from typing import Any

from checklists.constants import ItemStatus
from django.urls import reverse
from rest_framework.test import APITestCase

from dashboards.tests.factories import (
    age_lead,
    block_item,
    decide_offer,
    make_admin,
    make_applicant,
    make_catalogue,
    make_issued_offer,
    make_journey,
    make_lead,
    make_lead_manager,
    make_live_checklist,
    make_source,
    set_item_due,
    token_for,
)


def url_for(name: str) -> str:
    return reverse(f"v1:dashboards:{name}")


class SeededDashboardTestCase(APITestCase):
    """One applicant with a journey, a live checklist, and an issued offer."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.catalogue = make_catalogue(self.admin)
        self.country = self.catalogue["country"]

        self.applicant = make_applicant(self.admin)
        self.journey = make_journey(self.admin, self.applicant)
        self.checklist = make_live_checklist(self.admin, self.journey, self.country)
        self.items = list(self.checklist.items.order_by("display_order"))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def section(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.client.get(url_for(name), params or {}).data["data"]


class TestTodaysWork(SeededDashboardTestCase):
    def test_an_overdue_item_appears_once_and_only_in_the_overdue_list(self) -> None:
        """Overdue and due-soon must be disjoint, or the backlog is overstated."""
        set_item_due(self.items[0], days_from_now=-3)
        data = self.section("dashboard-today")

        self.assertEqual(data["overdue_checklist_items"]["total"], 1)
        self.assertEqual(data["due_soon_checklist_items"]["total"], 0)
        self.assertEqual(data["overdue_checklist_items"]["items"][0]["id"], str(self.items[0].id))

    def test_a_due_soon_item_appears_only_in_the_due_soon_list(self) -> None:
        set_item_due(self.items[0], days_from_now=2)
        data = self.section("dashboard-today")

        self.assertEqual(data["overdue_checklist_items"]["total"], 0)
        self.assertEqual(data["due_soon_checklist_items"]["total"], 1)

    def test_an_item_past_the_horizon_is_in_neither_list(self) -> None:
        set_item_due(self.items[0], days_from_now=30)
        data = self.section("dashboard-today", {"due_within_days": 7})

        self.assertEqual(data["overdue_checklist_items"]["total"], 0)
        self.assertEqual(data["due_soon_checklist_items"]["total"], 0)

    def test_widening_the_horizon_pulls_the_item_in(self) -> None:
        set_item_due(self.items[0], days_from_now=30)
        data = self.section("dashboard-today", {"due_within_days": 60})
        self.assertEqual(data["due_soon_checklist_items"]["total"], 1)

    def test_an_item_with_no_due_date_never_appears(self) -> None:
        """Nothing is late about a deadline that was never set."""
        data = self.section("dashboard-today")
        self.assertEqual(data["overdue_checklist_items"]["total"], 0)
        self.assertEqual(data["due_soon_checklist_items"]["total"], 0)

    def test_a_completed_item_drops_off_the_overdue_list(self) -> None:
        from checklists import services as checklist_services

        set_item_due(self.items[0], days_from_now=-3)
        self.assertEqual(self.section("dashboard-today")["overdue_checklist_items"]["total"], 1)

        checklist_services.set_item_status(
            actor=self.admin,
            item=self.items[0],
            status=ItemStatus.COMPLETED,
        )
        self.assertEqual(self.section("dashboard-today")["overdue_checklist_items"]["total"], 0)

    def test_a_blocked_item_stays_overdue(self) -> None:
        """`blocked` is not resolved — a stuck requirement is still not done."""
        set_item_due(self.items[0], days_from_now=-3)
        block_item(self.admin, self.items[0])
        self.assertEqual(self.section("dashboard-today")["overdue_checklist_items"]["total"], 1)

    def test_archiving_the_checklist_removes_its_items_from_the_worklist(self) -> None:
        from checklists import services as checklist_services

        set_item_due(self.items[0], days_from_now=-3)
        checklist_services.archive_checklist(actor=self.admin, checklist=self.checklist, reason="Applicant withdrew.")
        self.assertEqual(self.section("dashboard-today")["overdue_checklist_items"]["total"], 0)

    def test_an_overdue_row_carries_the_ids_needed_to_reach_the_record(self) -> None:
        """A number nobody can click is what this module exists not to build."""
        set_item_due(self.items[0], days_from_now=-3)
        row = self.section("dashboard-today")["overdue_checklist_items"]["items"][0]

        self.assertEqual(row["checklist_id"], str(self.checklist.id))
        self.assertEqual(row["journey_id"], str(self.journey.id))
        self.assertEqual(row["applicant_id"], str(self.applicant.id))
        self.assertEqual(row["applicant_name"], self.applicant.full_name_en)
        self.assertEqual(row["country_name_en"], self.country.name_en)

    def test_an_overdue_offer_appears_in_todays_work(self) -> None:
        make_issued_offer(self.admin, self.journey, deadline_days=-2)
        block = self.section("dashboard-today")["offers_awaiting_response"]
        self.assertEqual(block["total"], 1)
        self.assertTrue(block["items"][0]["is_response_overdue"])

    def test_a_drafted_offer_never_awaits_a_response(self) -> None:
        """Only an issued offer can be overdue — nobody was asked to answer a draft."""
        from datetime import timedelta

        from core.nepal.calendar import nepal_today

        from dashboards.tests.factories import make_manual_offer

        make_manual_offer(self.admin, self.journey, response_deadline=nepal_today() - timedelta(days=5))
        self.assertEqual(self.section("dashboard-today")["offers_awaiting_response"]["total"], 0)


class TestBlockers(SeededDashboardTestCase):
    def test_a_blocked_item_is_surfaced_with_its_note(self) -> None:
        block_item(self.admin, self.items[0], note="Waiting on the embassy.")
        block = self.section("dashboard-blockers")["blocked_checklist_items"]

        self.assertEqual(block["total"], 1)
        self.assertEqual(block["items"][0]["status_note"], "Waiting on the embassy.")

    def test_a_blocked_item_need_not_be_overdue(self) -> None:
        """Blocked and overdue are different problems and are listed separately."""
        block_item(self.admin, self.items[0])
        self.assertEqual(self.section("dashboard-blockers")["blocked_checklist_items"]["total"], 1)
        self.assertEqual(self.section("dashboard-today")["overdue_checklist_items"]["total"], 0)

    def test_blockers_shows_only_past_deadlines_and_todays_work_shows_the_approaching_ones(self) -> None:
        """The two offer lists must not overlap."""
        make_issued_offer(self.admin, self.journey, deadline_days=-2)
        second_journey = make_journey(self.admin, self.applicant)
        make_issued_offer(self.admin, second_journey, deadline_days=3)

        self.assertEqual(self.section("dashboard-blockers")["overdue_offers"]["total"], 1)
        self.assertEqual(self.section("dashboard-today")["offers_awaiting_response"]["total"], 2)

    def test_an_expired_passport_is_included_not_filtered_out(self) -> None:
        """The applicant whose passport already lapsed is the most blocked one."""
        from datetime import timedelta

        from applicants import services as applicant_services
        from core.nepal.calendar import nepal_today

        applicant_services.update_applicant(
            actor=self.admin,
            applicant=self.applicant,
            fields={},
            passport={"passport_number": "PA1234567", "expiry_date": nepal_today() - timedelta(days=30)},
        )
        block = self.section("dashboard-blockers")["expiring_passports"]
        self.assertEqual(block["total"], 1)
        self.assertTrue(block["items"][0]["has_expired"])

    def test_a_passport_beyond_the_horizon_is_excluded(self) -> None:
        from datetime import timedelta

        from applicants import services as applicant_services
        from core.nepal.calendar import nepal_today

        applicant_services.update_applicant(
            actor=self.admin,
            applicant=self.applicant,
            fields={},
            passport={"passport_number": "PA1234567", "expiry_date": nepal_today() + timedelta(days=900)},
        )
        self.assertEqual(self.section("dashboard-blockers")["expiring_passports"]["total"], 0)

    def test_a_journey_whose_country_has_no_template_is_surfaced(self) -> None:
        """The safety net: inheritance is silent when nobody authored the list."""
        from institutions import services as catalogue_services

        canada = catalogue_services.create_country(actor=self.admin, data={"code": "ca", "name_en": "Canada"})
        orphan_applicant = make_applicant(self.admin, name_np="सीता गुरुङ")
        orphan_journey = make_journey(self.admin, orphan_applicant, target_country_ref=canada)

        block = self.section("dashboard-blockers")["journeys_without_a_checklist"]
        returned = [row["id"] for row in block["items"]]
        self.assertIn(str(orphan_journey.id), returned)
        self.assertNotIn(str(self.journey.id), returned)


class TestPipelineAndOutcomes(SeededDashboardTestCase):
    def test_journey_stage_counts_reflect_reality(self) -> None:
        data = self.section("dashboard-pipeline")
        self.assertEqual(data["journeys_by_stage"]["planning"], 1)
        self.assertEqual(data["journeys_by_stage"]["visa_stage"], 0)

    def test_country_filter_narrows_journeys(self) -> None:
        from institutions import services as catalogue_services

        canada = catalogue_services.create_country(actor=self.admin, data={"code": "ca", "name_en": "Canada"})
        make_journey(self.admin, self.applicant, target_country_ref=canada)

        self.assertEqual(self.section("dashboard-pipeline")["journeys_by_stage"]["planning"], 2)
        narrowed = self.section("dashboard-pipeline", {"country": str(canada.id)})
        self.assertEqual(narrowed["journeys_by_stage"]["planning"], 1)

    def test_documents_panel_declares_that_it_ignores_the_country_filter(self) -> None:
        """A document belongs to a person, not a study plan — say so, don't imply otherwise."""
        data = self.section("dashboard-pipeline", {"country": str(self.country.id)})
        self.assertFalse(data["documents_by_status_is_country_filtered"])

    def test_a_decided_offer_appears_in_outcomes(self) -> None:
        offer = make_issued_offer(self.admin, self.journey, deadline_days=10)
        decide_offer(self.admin, offer, outcome="accepted")

        outcomes = self.section("dashboard-outcomes")
        self.assertEqual(outcomes["offer_decisions"]["accepted"], 1)
        self.assertEqual(outcomes["offer_decisions"]["rejected"], 0)

    def test_offer_decisions_hold_only_terminal_statuses(self) -> None:
        """`draft` and `issued` are not decisions and must never appear as keys."""
        decisions = self.section("dashboard-outcomes")["offer_decisions"]
        self.assertNotIn("draft", decisions)
        self.assertNotIn("issued", decisions)
        self.assertEqual(len(decisions), 5)

    def test_an_undecided_offer_is_in_neither_acceptance_bucket(self) -> None:
        make_issued_offer(self.admin, self.journey, deadline_days=10)
        rate = self.section("dashboard-conversion")["rates"]["offer_acceptance"]
        self.assertEqual(rate["denominator"], 0)
        self.assertIsNone(rate["percent"])


class TestConversion(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.source = make_source()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def section(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.client.get(url_for(name), params or {}).data["data"]

    def test_source_row_splits_volume_from_outcome(self) -> None:
        """Volume alone cannot say whether a channel is any good."""
        make_lead(self.admin, self.source, name_np="राम श्रेष्ठ")
        make_lead(self.admin, self.source, name_np="सीता गुरुङ")

        rows = self.section("dashboard-conversion")["by_source"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_code"], "walk_in")
        self.assertEqual(rows[0]["total"], 2)
        self.assertEqual(rows[0]["converted"], 0)
        self.assertEqual(rows[0]["in_progress"], 2)

    def test_a_source_nobody_came_through_is_omitted(self) -> None:
        make_source(code="facebook")
        make_lead(self.admin, self.source)

        rows = self.section("dashboard-conversion")["by_source"]
        self.assertEqual([row["source_code"] for row in rows], ["walk_in"])

    def test_lead_to_applicant_rate_is_computed_from_the_funnel(self) -> None:
        make_lead(self.admin, self.source, name_np="राम श्रेष्ठ")
        make_lead(self.admin, self.source, name_np="सीता गुरुङ")

        rate = self.section("dashboard-conversion")["rates"]["lead_to_applicant"]
        self.assertEqual(rate["denominator"], 2)
        self.assertEqual(rate["numerator"], 0)
        self.assertEqual(rate["percent"], 0.0)

    def test_a_zero_percent_is_distinguishable_from_no_data(self) -> None:
        """0.0 means 'they arrived and none converted'; null means 'none arrived'."""
        empty = self.section("dashboard-conversion")["rates"]["lead_to_applicant"]
        self.assertIsNone(empty["percent"])

        make_lead(self.admin, self.source)
        populated = self.section("dashboard-conversion")["rates"]["lead_to_applicant"]
        self.assertEqual(populated["percent"], 0.0)


class TestOwnerScoping(APITestCase):
    """The consequential case: aggregates must not leak across lead owners.

    A count is not exempt from the rule a list obeys. Telling one Lead Manager
    that the office holds forty leads when they own four discloses the size and
    shape of a colleague's pipeline just as surely as showing them the rows.
    """

    def setUp(self) -> None:
        self.admin = make_admin()
        self.source = make_source()
        self.mine = make_lead_manager("mgr_one")
        self.theirs = make_lead_manager("mgr_two")

        self.my_lead = make_lead(self.mine, self.source, name_np="राम श्रेष्ठ")
        make_lead(self.theirs, self.source, name_np="सीता गुरुङ")
        make_lead(self.theirs, self.source, name_np="हरि थापा")

    def as_user(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def section(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.client.get(url_for(name), params or {}).data["data"]

    def test_admin_sees_every_lead_in_the_funnel(self) -> None:
        self.as_user(self.admin)
        self.assertEqual(self.section("dashboard-pipeline")["leads_by_stage"]["new"], 3)

    def test_lead_manager_sees_only_their_own_in_the_funnel(self) -> None:
        self.as_user(self.mine)
        self.assertEqual(self.section("dashboard-pipeline")["leads_by_stage"]["new"], 1)

    def test_lead_manager_source_mix_covers_only_their_own(self) -> None:
        self.as_user(self.mine)
        rows = self.section("dashboard-conversion")["by_source"]
        self.assertEqual(rows[0]["total"], 1)

    def test_lead_manager_workload_holds_one_row_and_says_so(self) -> None:
        self.as_user(self.mine)
        data = self.section("dashboard-workload")

        self.assertTrue(data["is_scoped_to_caller"])
        self.assertEqual(len(data["leads"]), 1)
        self.assertEqual(data["leads"][0]["owner_id"], str(self.mine.id))

    def test_admin_workload_shows_the_distribution_and_says_so(self) -> None:
        self.as_user(self.admin)
        data = self.section("dashboard-workload")

        self.assertFalse(data["is_scoped_to_caller"])
        owners = {row["owner_id"] for row in data["leads"]}
        self.assertEqual(owners, {str(self.mine.id), str(self.theirs.id)})

    def test_stale_lead_alert_is_scoped(self) -> None:
        age_lead(self.my_lead, days=30)
        for lead in [lead for lead in self.theirs.leads_created.all()]:
            age_lead(lead, days=30)

        self.as_user(self.admin)
        self.assertEqual(self.section("dashboard-summary")["alerts"]["stale_leads"], 3)

        self.as_user(self.mine)
        self.assertEqual(self.section("dashboard-summary")["alerts"]["stale_leads"], 1)

    def test_shared_resources_are_not_narrowed_for_a_lead_manager(self) -> None:
        """Applicants are shared; pretending otherwise would invent a restriction."""
        make_applicant(self.admin)

        self.as_user(self.admin)
        admin_count = self.section("dashboard-pipeline")["applicants_by_status"]["active"]
        self.as_user(self.mine)
        manager_count = self.section("dashboard-pipeline")["applicants_by_status"]["active"]

        self.assertEqual(admin_count, 1)
        self.assertEqual(manager_count, 1)


class TestStaleLeads(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.source = make_source()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def section(self, name: str) -> dict[str, Any]:
        return self.client.get(url_for(name)).data["data"]

    def test_a_never_contacted_lead_goes_stale_from_its_creation_date(self) -> None:
        """Without the fallback, a lead nobody ever called looks perpetually fresh."""
        lead = make_lead(self.admin, self.source)
        age_lead(lead, days=30)
        self.assertEqual(self.section("dashboard-today")["stale_leads"]["total"], 1)

    def test_a_recent_lead_is_not_stale(self) -> None:
        make_lead(self.admin, self.source)
        self.assertEqual(self.section("dashboard-today")["stale_leads"]["total"], 0)

    def test_a_converted_lead_is_never_stale(self) -> None:
        """A finished lead is not neglected."""
        from leads import services as lead_services
        from leads.constants import LeadStage

        lead = make_lead(self.admin, self.source)
        age_lead(lead, days=30)
        lead_services.change_stage(actor=self.admin, lead=lead, stage=LeadStage.CONTACTED)
        lead_services.mark_lost(
            actor=self.admin,
            lead=lead,
            loss_reason=_loss_reason(),
            detail="",
        )
        self.assertEqual(self.section("dashboard-today")["stale_leads"]["total"], 0)


def _loss_reason() -> Any:
    from leads.models import LossReason

    return LossReason.objects.create(code="no_response", name_np="कुनै जवाफ छैन", name_en="No response")


class TestActivityFeed(SeededDashboardTestCase):
    def test_the_feed_reports_real_events_newest_first(self) -> None:
        resp = self.client.get(url_for("dashboard-activity"))
        rows = resp.data["data"]

        self.assertGreater(resp.data["meta"]["count"], 0)
        self.assertGreater(len(rows), 0)
        stamps = [row["created_at"] for row in rows]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_rows_carry_the_entity_ids_needed_to_navigate(self) -> None:
        row = self.client.get(url_for("dashboard-activity")).data["data"][0]
        self.assertIn("app_label", row)
        self.assertIn("entity_type", row)
        self.assertIn("entity_id", row)
        self.assertIn("created_at_bs", row)

    def test_the_feed_is_not_narrowed_by_authority(self) -> None:
        """Consistent with the audit module, which these users may already call."""
        admin_count = self.client.get(url_for("dashboard-activity")).data["meta"]["count"]

        manager = make_lead_manager("mgr_feed")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(manager)}")
        manager_count = self.client.get(url_for("dashboard-activity")).data["meta"]["count"]

        self.assertEqual(admin_count, manager_count)


class TestSummaryAgreesWithItsSections(SeededDashboardTestCase):
    """The strip is a shortcut into the sections, so it must not contradict them.

    Not a consistency *guarantee* — the endpoints are separate requests and the
    contract says so — but within one quiescent test the two must agree, or the
    strip is measuring something different from what it links to.
    """

    def test_overdue_count_matches_todays_work(self) -> None:
        set_item_due(self.items[0], days_from_now=-3)
        set_item_due(self.items[1], days_from_now=-1)

        summary = self.section("dashboard-summary")["alerts"]["overdue_checklist_items"]
        today = self.section("dashboard-today")["overdue_checklist_items"]["total"]
        self.assertEqual(summary, 2)
        self.assertEqual(summary, today)

    def test_blocked_count_matches_blockers(self) -> None:
        block_item(self.admin, self.items[0])

        summary = self.section("dashboard-summary")["alerts"]["blocked_checklist_items"]
        blockers = self.section("dashboard-blockers")["blocked_checklist_items"]["total"]
        self.assertEqual(summary, 1)
        self.assertEqual(summary, blockers)

    def test_the_country_filter_reaches_the_summary_too(self) -> None:
        from institutions import services as catalogue_services

        set_item_due(self.items[0], days_from_now=-3)
        canada = catalogue_services.create_country(actor=self.admin, data={"code": "ca", "name_en": "Canada"})

        self.assertEqual(self.section("dashboard-summary")["alerts"]["overdue_checklist_items"], 1)
        narrowed = self.section("dashboard-summary", {"country": str(canada.id)})
        self.assertEqual(narrowed["alerts"]["overdue_checklist_items"], 0)
