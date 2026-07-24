"""Audit app tests: record_event, immutability, read endpoints + access, integration."""

from __future__ import annotations

from datetime import timedelta

from authenticate import services as auth_services
from authenticate.constants import AuthorityType
from core.nepal.constants import NEPAL_TZ
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from audit import services as audit_services
from audit.exceptions import ImmutabilityError
from audit.models import AuditEvent
from audit.selectors import get_events_for_entity

STRONG_PW = "Str0ng-Passphrase-17"


def make(username: str, authority: str) -> object:
    return auth_services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name="U",
    )


def token_for(user: object) -> str:
    session, _ = auth_services.issue_session(user=user, device_id=f"t-{user.username}")
    return auth_services.build_access_token(user, session, must_change_password=False)


class TestRecordAndImmutability(TestCase):
    def test_record_event_appends(self) -> None:
        event = audit_services.record_event(
            app_label="authenticate", action="login_success", actor_type="admin", actor_label="x"
        )
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(event.app_label, "authenticate")

    def test_bulk_delete_blocked(self) -> None:
        audit_services.record_event(app_label="authenticate", action="login_success")
        with self.assertRaises(ImmutabilityError):
            AuditEvent.objects.all().delete()

    def test_instance_delete_blocked(self) -> None:
        event = audit_services.record_event(app_label="authenticate", action="login_success")
        with self.assertRaises(ImmutabilityError):
            event.delete()


class TestAuditReadEndpoints(APITestCase):
    def setUp(self) -> None:
        self.admin = make("adminx", AuthorityType.ADMIN)
        self.lead = make("leadmgr", AuthorityType.LEAD_MANAGER)
        audit_services.record_event(
            app_label="authenticate", action="login_success", entity_type="authenticate.user", actor_label="a"
        )
        audit_services.record_event(app_label="authenticate", action="account_blocked", actor_label="b")

    def test_requires_auth(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lead_manager_forbidden(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.lead)}")
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_lists_paginated(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["meta"]["count"], 2)

    def test_filter_by_action(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        resp = self.client.get(reverse("v1:audit:event-list"), {"action": "account_blocked"})
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_malformed_filters_are_400_not_500(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        for params in ({"actor_id": "not-a-uuid"}, {"success": "maybe"}, {"fiscal_year": "garbage"}):
            resp = self.client.get(reverse("v1:audit:event-list"), params)
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, params)
            self.assertEqual(resp.data["error"]["code"], "VALIDATION_ERROR")

    def test_detail_and_404(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        event = AuditEvent.objects.first()
        ok = self.client.get(reverse("v1:audit:event-detail", args=[event.id]))
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        missing = self.client.get(reverse("v1:audit:event-detail", args=["00000000-0000-0000-0000-000000000000"]))
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.data["error"]["code"], "AUDIT_EVENT_NOT_FOUND")


class TestBikramSambatOnRead(APITestCase):
    """`created_at_bs` on both read endpoints (§39.4).

    The six per-app history projections all rendered a BS date; the central log
    did not, so the same row read differently depending on where you read it.
    """

    def setUp(self) -> None:
        self.admin = make("adminbs", AuthorityType.ADMIN)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        self.event = audit_services.record_event(app_label="leads", action="lead_created", actor_label="a")

    def _assert_bs_shape(self, value: object) -> None:
        self.assertIsInstance(value, dict)
        for key in ("year", "month", "day", "month_name", "display"):
            self.assertIn(key, value)
        self.assertIsInstance(value["year"], int)
        self.assertGreater(value["year"], 2000)

    def test_list_carries_bs(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_bs_shape(resp.data["data"][0]["created_at_bs"])

    def test_detail_carries_bs(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-detail", args=[self.event.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_bs_shape(resp.data["data"]["created_at_bs"])


class TestSearchFilter(APITestCase):
    def setUp(self) -> None:
        self.admin = make("adminsearch", AuthorityType.ADMIN)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        audit_services.record_event(app_label="leads", action="lead_created", summary="Created a lead for Sita.")
        audit_services.record_event(app_label="offers", action="offer_issued", summary="Issued an offer to Ram.")
        audit_services.record_event(app_label="leads", action="lead_updated", summary="")

    def _count(self, **params: str) -> int:
        resp = self.client.get(reverse("v1:audit:event-list"), params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return resp.data["meta"]["count"]

    def test_matches_summary_substring_case_insensitively(self) -> None:
        self.assertEqual(self._count(search="sita"), 1)
        self.assertEqual(self._count(search="offer"), 1)

    def test_no_match_returns_empty_not_error(self) -> None:
        self.assertEqual(self._count(search="nobody-said-this"), 0)

    def test_blank_summary_is_unreachable_by_search(self) -> None:
        # Documented in INTEGRATION.md §9: an empty result is not proof of absence.
        self.assertEqual(self._count(search="lead_updated"), 0)

    def test_single_character_term_is_rejected(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-list"), {"search": "s"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("search", resp.data["error"]["details"])


class TestDateRangeFilter(APITestCase):
    def setUp(self) -> None:
        self.admin = make("admindate", AuthorityType.ADMIN)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        self.event = audit_services.record_event(app_label="leads", action="lead_created", summary="x")
        # ``created_at`` is auto_now_add, so the row's day is decided by the
        # clock; derive the window from the row rather than from `today`, which
        # would make this test flaky across the NPT midnight boundary.
        self.day = self.event.created_at.astimezone(NEPAL_TZ).date()

    def _count(self, **params: str) -> int:
        resp = self.client.get(reverse("v1:audit:event-list"), params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return resp.data["meta"]["count"]

    def test_both_bounds_are_inclusive_of_the_event_day(self) -> None:
        day = self.day.isoformat()
        self.assertEqual(self._count(date_from=day, date_to=day), 1)

    def test_window_before_the_event_excludes_it(self) -> None:
        before = (self.day - timedelta(days=2)).isoformat()
        self.assertEqual(self._count(date_from=before, date_to=(self.day - timedelta(days=1)).isoformat()), 0)

    def test_window_after_the_event_excludes_it(self) -> None:
        self.assertEqual(self._count(date_from=(self.day + timedelta(days=1)).isoformat()), 0)

    def test_inverted_range_is_rejected(self) -> None:
        resp = self.client.get(
            reverse("v1:audit:event-list"),
            {"date_from": self.day.isoformat(), "date_to": (self.day - timedelta(days=1)).isoformat()},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["details"]["date_to"], ["Must not be earlier than date_from."])

    def test_malformed_date_is_400_not_500(self) -> None:
        for params in ({"date_from": "yesterday"}, {"date_to": "2026-13-45"}):
            resp = self.client.get(reverse("v1:audit:event-list"), params)
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, params)
            self.assertEqual(resp.data["error"]["code"], "VALIDATION_ERROR")


class TestOrdering(APITestCase):
    def setUp(self) -> None:
        self.admin = make("adminorder", AuthorityType.ADMIN)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        self.first = audit_services.record_event(app_label="leads", action="lead_created", summary="first")
        self.second = audit_services.record_event(app_label="leads", action="lead_updated", summary="second")

    def _summaries(self, **params: str) -> list[str]:
        resp = self.client.get(reverse("v1:audit:event-list"), params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return [row["summary"] for row in resp.data["data"]]

    def test_default_is_newest_first(self) -> None:
        self.assertEqual(self._summaries(), ["second", "first"])

    def test_asc_is_oldest_first(self) -> None:
        # The record-timeline flow: chronological order comes from the server,
        # because reversing a page client-side reverses the wrong page.
        self.assertEqual(self._summaries(order="asc"), ["first", "second"])

    def test_explicit_desc_matches_the_default(self) -> None:
        self.assertEqual(self._summaries(order="desc"), ["second", "first"])

    def test_unknown_order_is_rejected(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-list"), {"order": "sideways"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("order", resp.data["error"]["details"])


class TestFacetsEndpoint(APITestCase):
    def setUp(self) -> None:
        self.admin = make("adminfacet", AuthorityType.ADMIN)
        self.lead = make("leadfacet", AuthorityType.LEAD_MANAGER)
        audit_services.record_event(app_label="leads", action="lead_created", entity_type="lead")
        audit_services.record_event(app_label="offers", action="offer_issued", entity_type="offer")
        audit_services.record_event(app_label="leads", action="lead_created", entity_type="lead")

    def test_requires_auth(self) -> None:
        resp = self.client.get(reverse("v1:audit:event-facets"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lead_manager_forbidden(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.lead)}")
        resp = self.client.get(reverse("v1:audit:event-facets"))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_distinct_observed_values_and_the_full_actor_enum(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        resp = self.client.get(reverse("v1:audit:event-facets"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data["data"]
        self.assertEqual(data["apps"], ["leads", "offers"])
        self.assertEqual(data["actions"], ["lead_created", "offer_issued"])
        self.assertEqual(data["entity_types"], ["lead", "offer"])
        # Closed enum: every value is offered, including ones never observed.
        self.assertEqual(data["actor_types"], ["superadmin", "admin", "lead_manager", "system", "ai"])

    def test_empty_log_returns_empty_lists_not_an_error(self) -> None:
        AuditEvent.objects.all().update(app_label="", action="", entity_type="")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        resp = self.client.get(reverse("v1:audit:event-facets"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["actions"], [])


class TestEntityTimelineSelector(TestCase):
    """``get_events_for_entity`` — the query behind every app's history endpoint."""

    def test_narrows_to_one_entity_and_orders_both_ways(self) -> None:
        target = "11111111-1111-4111-8111-111111111111"
        other = "22222222-2222-4222-8222-222222222222"
        audit_services.record_event(
            app_label="leads", action="lead_created", entity_type="lead", entity_id=target, summary="first"
        )
        audit_services.record_event(
            app_label="leads", action="lead_updated", entity_type="lead", entity_id=target, summary="second"
        )
        audit_services.record_event(
            app_label="leads", action="lead_created", entity_type="lead", entity_id=other, summary="elsewhere"
        )

        newest_first = get_events_for_entity(entity_type="lead", entity_id=target, app_label="leads")
        self.assertEqual([e.summary for e in newest_first], ["second", "first"])

        oldest_first = get_events_for_entity(entity_type="lead", entity_id=target, app_label="leads", order="asc")
        self.assertEqual([e.summary for e in oldest_first], ["first", "second"])


class TestAuthenticateEmitsToAudit(APITestCase):
    def test_login_creates_central_audit_event(self) -> None:
        make("leadmgr", AuthorityType.LEAD_MANAGER)
        before = AuditEvent.objects.filter(app_label="authenticate").count()
        resp = self.client.post(
            reverse("v1:auth:login"),
            {"username": "leadmgr", "password": STRONG_PW, "device_id": "d1"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        after = AuditEvent.objects.filter(app_label="authenticate", action="login_success").count()
        self.assertGreater(after, before)
