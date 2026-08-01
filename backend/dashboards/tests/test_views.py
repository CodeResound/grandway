"""Dashboard endpoints: access, filter validation, envelopes, and empty state.

The eight sections share one base view and one filter serializer, so the access
and validation cases are written once and run against all eight by name. That is
deliberate rather than lazy: the risk with eight near-identical endpoints is that
one quietly diverges, and a per-endpoint loop is what would catch it.
"""

from __future__ import annotations

from typing import Any

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from dashboards.constants import ErrorCode
from dashboards.tests.factories import make_admin, make_lead_manager, make_superadmin, token_for

#: Every section, by URL name. Kept as one list so a new endpoint added without
#: an access or envelope test is a visible omission rather than a silent one.
SECTION_NAMES: tuple[str, ...] = (
    "dashboard-summary",
    "dashboard-today",
    "dashboard-pipeline",
    "dashboard-blockers",
    "dashboard-workload",
    "dashboard-conversion",
    "dashboard-outcomes",
    "dashboard-activity",
)


def url_for(name: str) -> str:
    return reverse(f"v1:dashboards:{name}")


class DashboardApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.superadmin = make_superadmin()

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")


class TestDashboardAccess(DashboardApiTestCase):
    def test_every_section_requires_authentication(self) -> None:
        for name in SECTION_NAMES:
            with self.subTest(section=name):
                self.assertEqual(self.client.get(url_for(name)).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_is_forbidden_everywhere(self) -> None:
        """A platform authority does not participate in consultancy operations."""
        self.auth(self.superadmin)
        for name in SECTION_NAMES:
            with self.subTest(section=name):
                resp = self.client.get(url_for(name))
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_admin_may_read_every_section(self) -> None:
        self.auth(self.admin)
        for name in SECTION_NAMES:
            with self.subTest(section=name):
                self.assertEqual(self.client.get(url_for(name)).status_code, status.HTTP_200_OK)

    def test_lead_manager_may_read_every_section_except_activity(self) -> None:
        """Same endpoints for both authorities, with one documented exception.

        For every summarising section the scoping happens in the data — a Lead
        Manager calls the same URL as an Admin and legitimately sees different
        numbers. `dashboard-activity` is the exception because it summarises
        nothing: it returns rows from the central audit log, which is
        `is_staff`-only at `GET /api/v1/audit/events/` and is now equally
        `is_staff`-only here. Before that check existed this loop asserted a 200
        for activity too, which made it a test that the leak stayed open.
        """
        self.auth(self.manager)
        for name in SECTION_NAMES:
            if name == "dashboard-activity":
                continue
            with self.subTest(section=name):
                self.assertEqual(self.client.get(url_for(name)).status_code, status.HTTP_200_OK)

    def test_lead_manager_is_refused_the_activity_feed(self) -> None:
        """The audit log's access rule holds whichever door it is read through."""
        self.auth(self.manager)

        resp = self.client.get(url_for("dashboard-activity"))

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)


class TestEnvelopeConsistency(DashboardApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_success_envelope_shape(self) -> None:
        for name in SECTION_NAMES:
            with self.subTest(section=name):
                resp = self.client.get(url_for(name))
                self.assertTrue(resp.data["success"])
                self.assertIn("data", resp.data)
                self.assertIn("meta", resp.data)

    def test_error_envelope_shape(self) -> None:
        self.auth(self.superadmin)
        resp = self.client.get(url_for("dashboard-summary"))
        self.assertFalse(resp.data["success"])
        self.assertIn("code", resp.data["error"])
        self.assertIn("message", resp.data["error"])
        self.assertIn("details", resp.data["error"])

    def test_seven_sections_return_an_object_and_activity_returns_a_list(self) -> None:
        """The one documented shape difference in the module."""
        for name in SECTION_NAMES[:-1]:
            with self.subTest(section=name):
                self.assertIsInstance(self.client.get(url_for(name)).data["data"], dict)
        self.assertIsInstance(self.client.get(url_for("dashboard-activity")).data["data"], list)

    def test_only_activity_paginates(self) -> None:
        """Everything else is a summary object, so its meta stays empty."""
        for name in SECTION_NAMES[:-1]:
            with self.subTest(section=name):
                self.assertEqual(self.client.get(url_for(name)).data["meta"], {})

        meta = self.client.get(url_for("dashboard-activity")).data["meta"]
        for key in ("count", "page", "page_size", "next", "previous"):
            self.assertIn(key, meta)


class TestEmptySystem(DashboardApiTestCase):
    """A dashboard with nothing on it is the correct answer for an empty system.

    Worth its own class: the failure mode this guards against is a section that
    raises on a null aggregate or a division by zero rather than returning
    nothing, and a fresh installation is exactly when that would first be hit.
    """

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_summary_alerts_are_all_zero(self) -> None:
        data = self.client.get(url_for("dashboard-summary")).data["data"]
        self.assertEqual(set(data["alerts"].values()), {0})

    def test_pipeline_buckets_are_zero_filled_not_absent(self) -> None:
        """An absent stage reads as 'this stage does not exist', not 'none yet'."""
        data = self.client.get(url_for("dashboard-pipeline")).data["data"]
        self.assertEqual(len(data["journeys_by_stage"]), 9)
        self.assertEqual(len(data["offers_by_status"]), 7)
        self.assertEqual(len(data["applicants_by_status"]), 3)
        self.assertEqual(set(data["journeys_by_stage"].values()), {0})

    def test_conversion_rates_are_null_not_zero_on_an_empty_denominator(self) -> None:
        """'Nobody arrived' and 'nobody converted' are different facts."""
        rates = self.client.get(url_for("dashboard-conversion")).data["data"]["rates"]
        for key, rate in rates.items():
            with self.subTest(rate=key):
                self.assertEqual(rate["denominator"], 0)
                self.assertIsNone(rate["percent"])

    def test_worklists_report_zero_totals(self) -> None:
        data = self.client.get(url_for("dashboard-today")).data["data"]
        for key in ("overdue_checklist_items", "offers_awaiting_response", "stale_leads"):
            with self.subTest(worklist=key):
                self.assertEqual(data[key]["total"], 0)
                self.assertEqual(data[key]["items"], [])
                self.assertFalse(data[key]["has_more"])


class TestFilterValidation(DashboardApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_reversed_date_range_is_rejected(self) -> None:
        """Returning zero rows would look exactly like a quiet period."""
        resp = self.client.get(
            url_for("dashboard-pipeline"),
            {"date_from": "2026-07-24", "date_to": "2026-07-01"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_to", resp.data["error"]["details"])

    def test_malformed_fiscal_year_is_rejected(self) -> None:
        resp = self.client.get(url_for("dashboard-pipeline"), {"fiscal_year": "not-a-year"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("fiscal_year", resp.data["error"]["details"])

    def test_out_of_range_due_window_is_rejected(self) -> None:
        """A year-long 'due soon' window is the whole table, not a worklist."""
        resp = self.client.get(url_for("dashboard-today"), {"due_within_days": 400})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("due_within_days", resp.data["error"]["details"])

    def test_zero_due_window_is_rejected(self) -> None:
        resp = self.client.get(url_for("dashboard-today"), {"due_within_days": 0})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_journey_stage_is_rejected(self) -> None:
        resp = self.client.get(url_for("dashboard-pipeline"), {"journey_stage": "nonsense"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_malformed_country_uuid_is_rejected(self) -> None:
        resp = self.client.get(url_for("dashboard-pipeline"), {"country": "not-a-uuid"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_country_returns_empty_not_error(self) -> None:
        """A well-formed id for a country that does not exist is not a client error."""
        resp = self.client.get(
            url_for("dashboard-pipeline"),
            {"country": "00000000-0000-4000-8000-000000000000"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(set(resp.data["data"]["journeys_by_stage"].values()), {0})

    def test_every_section_accepts_the_same_filter_set(self) -> None:
        """One filter bar drives the whole page — no section may reject the shared params."""
        params = {
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
            "country": "00000000-0000-4000-8000-000000000000",
            "institution": "00000000-0000-4000-8000-000000000001",
            "owner": "00000000-0000-4000-8000-000000000002",
            "journey_stage": "offer_stage",
            "offer_status": "issued",
            "document_status": "draft",
            "checklist_status": "active",
            "due_within_days": 14,
            "passport_within_days": 90,
        }
        for name in SECTION_NAMES:
            with self.subTest(section=name):
                self.assertEqual(self.client.get(url_for(name), params).status_code, status.HTTP_200_OK)

    def test_due_within_days_is_echoed_back(self) -> None:
        """A client should not have to assume the default it did not send."""
        data = self.client.get(url_for("dashboard-today"), {"due_within_days": 3}).data["data"]
        self.assertEqual(data["due_within_days"], 3)

    def test_default_due_window_is_seven_days(self) -> None:
        data = self.client.get(url_for("dashboard-today")).data["data"]
        self.assertEqual(data["due_within_days"], 7)


class TestNoWrites(DashboardApiTestCase):
    """This module writes nothing, anywhere, ever — including no audit events."""

    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_write_methods_are_rejected(self) -> None:
        for name in SECTION_NAMES:
            with self.subTest(section=name):
                for method in (self.client.post, self.client.patch, self.client.delete):
                    self.assertEqual(
                        method(url_for(name)).status_code,
                        status.HTTP_405_METHOD_NOT_ALLOWED,
                    )

    def test_reading_the_dashboard_appends_no_audit_event(self) -> None:
        """A read that logged itself would flood the very feed it renders."""
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        for name in SECTION_NAMES:
            self.client.get(url_for(name))
        self.assertEqual(AuditEvent.objects.count(), before)
