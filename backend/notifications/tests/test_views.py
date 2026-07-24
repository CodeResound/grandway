"""Endpoint tests for the notifications app.

Every endpoint gets the §18 set — success, auth failure, permission failure,
not-found, and envelope consistency — plus the two rules that are specific to
this app and would be invisible in any other suite:

* **The feed is own-recipient only, even for an Admin.** Tested from both
  directions: an Admin cannot list another user's notifications, and cannot
  fetch one by id.
* **Another user's notification returns 404, not 403.** A 403 would confirm the
  id exists on somebody else's feed.

There is no create, update, or delete endpoint to test, which is itself asserted
— a route appearing later without a decision behind it should fail here.
"""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from notifications.constants import DueBucket, NotificationStatus, NotificationType, Priority
from notifications.models import Notification
from notifications.tests.factories import (
    auth,
    make_admin,
    make_lead_manager,
    make_superadmin,
    raise_alert,
)

LIST_URL = reverse("v1:notifications:notification-list")
SUMMARY_URL = reverse("v1:notifications:notification-summary")
READ_ALL_URL = reverse("v1:notifications:notification-read-all")


def detail_url(notification) -> str:
    return reverse("v1:notifications:notification-detail", args=[notification.id])


def action_url(name: str, notification) -> str:
    return reverse(f"v1:notifications:notification-{name}", args=[notification.id])


class EnvelopeAndAuthTests(APITestCase):
    """The standard envelope (§7) and the two ways in are refused."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.notification = raise_alert(self.admin)

    def test_anonymous_is_refused(self) -> None:
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_is_refused_with_the_standard_error_envelope(self) -> None:
        """A platform authority does not participate in consultancy operations."""
        auth(self.client, make_superadmin())

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"]["code"], "NOTIFICATIONS_ACTOR_FORBIDDEN")
        self.assertIn("details", response.data["error"])
        self.assertIn("meta", response.data)

    def test_the_list_uses_the_standard_pagination_meta(self) -> None:
        auth(self.client, self.admin)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            set(response.data["meta"]),
            {"count", "page", "page_size", "next", "previous"},
        )

    def test_a_lead_manager_may_use_the_feed(self) -> None:
        manager = make_lead_manager()
        raise_alert(manager, dedupe_key="mgr-1")
        auth(self.client, manager)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)


class OwnRecipientScopingTests(APITestCase):
    """The rule that makes this app stricter than every other one."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.theirs = raise_alert(self.manager, dedupe_key="theirs")
        raise_alert(self.admin, dedupe_key="mine")

    def test_the_feed_returns_only_the_callers_own_notifications(self) -> None:
        auth(self.client, self.admin)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["title"], "Overdue: Passport bio page scan")

    def test_an_admin_cannot_fetch_another_users_notification(self) -> None:
        auth(self.client, self.admin)

        response = self.client.get(detail_url(self.theirs))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_another_users_notification_is_404_and_never_403(self) -> None:
        """A 403 would confirm the id exists on somebody else's feed."""
        auth(self.client, self.admin)

        response = self.client.get(detail_url(self.theirs))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "NOTIFICATIONS_NOTIFICATION_NOT_FOUND")

    def test_a_nonexistent_id_gives_the_same_answer(self) -> None:
        auth(self.client, self.admin)

        response = self.client.get(
            reverse("v1:notifications:notification-detail", args=["3f8e4c22-0000-4000-8000-000000000000"])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "NOTIFICATIONS_NOTIFICATION_NOT_FOUND")

    def test_acting_on_another_users_notification_is_refused(self) -> None:
        auth(self.client, self.admin)

        for name in ("read", "unread", "dismiss"):
            with self.subTest(action=name):
                response = self.client.post(action_url(name, self.theirs))
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, NotificationStatus.ACTIVE)
        self.assertIsNone(self.theirs.read_at)


class FeedShapeTests(APITestCase):
    """What one row looks like, including the derived fields."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.overdue = raise_alert(
            self.admin,
            dedupe_key="overdue",
            due_at=timezone.now() - timedelta(days=2),
        )
        auth(self.client, self.admin)

    def test_a_row_carries_the_source_pointer_and_the_bs_date(self) -> None:
        response = self.client.get(detail_url(self.overdue))
        row = response.data["data"]

        self.assertEqual(row["source_app"], "checklists")
        self.assertEqual(row["source_entity_type"], "checklist_item")
        self.assertEqual(row["source_api_path"], "/api/v1/checklists/x/items/y/")
        self.assertEqual(set(row["due_at_bs"]) & {"year", "month", "day"}, {"year", "month", "day"})

    def test_the_due_bucket_is_derived(self) -> None:
        response = self.client.get(detail_url(self.overdue))

        self.assertEqual(response.data["data"]["due_bucket"], DueBucket.OVERDUE)

    def test_internal_columns_are_withheld(self) -> None:
        """`dedupe_key` and `dismissed_by` are stored but never published."""
        response = self.client.get(detail_url(self.overdue))

        self.assertNotIn("dedupe_key", response.data["data"])
        self.assertNotIn("dismissed_by", response.data["data"])
        self.assertNotIn("recipient", response.data["data"])

    def test_an_alert_with_no_due_date_buckets_as_none(self) -> None:
        lifecycle = raise_alert(
            self.admin,
            dedupe_key="lifecycle",
            notification_type=NotificationType.JOURNEY_STAGE_CHANGED,
        )

        response = self.client.get(detail_url(lifecycle))

        self.assertEqual(response.data["data"]["due_bucket"], DueBucket.NONE)
        self.assertIsNone(response.data["data"]["due_at_bs"])


class FilterTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.overdue = raise_alert(
            self.admin,
            dedupe_key="overdue",
            due_at=timezone.now() - timedelta(days=2),
        )
        self.later = raise_alert(
            self.admin,
            dedupe_key="later",
            notification_type=NotificationType.PASSPORT_EXPIRING,
            due_at=timezone.now() + timedelta(days=90),
        )
        auth(self.client, self.admin)

    def test_an_unfiltered_feed_returns_everything_including_history(self) -> None:
        """Defaulting to active would hide the history behind an unknown param."""
        from notifications import services

        services.dismiss(self.overdue, actor=self.admin)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.data["meta"]["count"], 2)

    def test_is_read_false_does_not_leak_from_an_absent_query_param(self) -> None:
        """DRF resolves a missing BooleanField to False on HTML input."""
        from notifications import services

        services.mark_read(self.overdue)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.data["meta"]["count"], 2)

    def test_filter_by_read_state(self) -> None:
        from notifications import services

        services.mark_read(self.overdue)

        response = self.client.get(LIST_URL, {"is_read": "true"})

        self.assertEqual(response.data["meta"]["count"], 1)

    def test_filter_by_due_bucket(self) -> None:
        response = self.client.get(LIST_URL, {"due_bucket": DueBucket.OVERDUE})

        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["due_bucket"], DueBucket.OVERDUE)

    def test_filter_by_type_and_priority(self) -> None:
        response = self.client.get(LIST_URL, {"notification_type": NotificationType.PASSPORT_EXPIRING})

        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["priority"], Priority.HIGH)

    def test_every_filter_name_matches_its_payload_field(self) -> None:
        """The §19.5 review's finding: one odd parameter out is a client bug.

        Asserted rather than merely documented, because the failure mode is
        silent — a mismatched name filters nothing and returns a full page.
        """
        from notifications.serializers import NotificationFilterSerializer

        row = self.client.get(LIST_URL).data["data"][0]
        params = set(NotificationFilterSerializer().fields)
        not_payload_fields = {"due_within_days", "date_from", "date_to", "fiscal_year"}

        for name in params - not_payload_fields:
            with self.subTest(param=name):
                self.assertIn(name, row, f"filter '{name}' names no field in the payload")

    def test_a_malformed_fiscal_year_is_a_400_not_a_500(self) -> None:
        """It reached the selector and raised until the §19.5 review asked."""
        response = self.client.get(LIST_URL, {"fiscal_year": "nonsense"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("fiscal_year", response.data["error"]["details"])

    def test_a_well_formed_fiscal_year_is_accepted(self) -> None:
        response = self.client.get(LIST_URL, {"fiscal_year": "2082/83"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_source_record(self) -> None:
        import uuid

        source_id = uuid.uuid4()
        raise_alert(self.admin, dedupe_key="sourced", source_entity_id=source_id)

        response = self.client.get(LIST_URL, {"source_entity_id": str(source_id)})

        self.assertEqual(response.data["meta"]["count"], 1)

    def test_an_invalid_filter_value_is_rejected(self) -> None:
        response = self.client.get(LIST_URL, {"status": "not-a-status"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_an_out_of_range_horizon_is_rejected(self) -> None:
        response = self.client.get(LIST_URL, {"due_within_days": 9999})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_summary_validates_filters_it_does_not_honour(self) -> None:
        """`?status=bogus` on /summary/ is a client mistake worth hearing about."""
        response = self.client.get(SUMMARY_URL, {"status": "bogus"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data["error"]["details"])


class SummaryTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        raise_alert(self.admin, dedupe_key="a", due_at=timezone.now() - timedelta(days=1))
        raise_alert(
            self.admin,
            dedupe_key="b",
            notification_type=NotificationType.OFFER_EXPIRED,
            due_at=timezone.now() + timedelta(days=2),
        )
        auth(self.client, self.admin)

    def test_the_summary_counts_by_priority_and_bucket(self) -> None:
        response = self.client.get(SUMMARY_URL)
        data = response.data["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["unread"], 2)
        self.assertEqual(data["active"], 2)
        self.assertEqual(data["by_priority"][Priority.HIGH], 1)
        self.assertEqual(data["by_priority"][Priority.URGENT], 1)
        self.assertEqual(data["by_due_bucket"][DueBucket.OVERDUE], 1)
        self.assertEqual(data["by_due_bucket"][DueBucket.DUE_SOON], 1)

    def test_every_bucket_is_zero_filled(self) -> None:
        """A missing key and a zero are the same fact to a human, not to a client."""
        response = self.client.get(SUMMARY_URL)

        self.assertEqual(set(response.data["data"]["by_priority"]), set(Priority.values))
        self.assertEqual(set(response.data["data"]["by_due_bucket"]), set(DueBucket.values))

    def test_an_unread_but_resolved_alert_still_counts_as_unread(self) -> None:
        """An alert resolved before anybody read it deserves to be noticed once."""
        from notifications import services

        services.resolve_cleared(set(), types=(NotificationType.CHECKLIST_ITEM_OVERDUE,))

        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.data["data"]["unread"], 2)
        self.assertEqual(response.data["data"]["active"], 1)

    def test_the_summary_is_scoped_to_the_caller(self) -> None:
        raise_alert(make_lead_manager(), dedupe_key="theirs")

        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.data["data"]["unread"], 2)


class ReadStateEndpointTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.notification = raise_alert(self.admin)
        auth(self.client, self.admin)

    def test_mark_read_returns_the_updated_row(self) -> None:
        response = self.client.post(action_url("read", self.notification))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["is_read"])
        self.assertIsNotNone(response.data["data"]["read_at"])

    def test_mark_read_is_idempotent(self) -> None:
        self.client.post(action_url("read", self.notification))
        first = Notification.objects.get(pk=self.notification.pk).read_at

        self.client.post(action_url("read", self.notification))

        self.assertEqual(Notification.objects.get(pk=self.notification.pk).read_at, first)

    def test_mark_read_does_not_change_status(self) -> None:
        """Reading is not deciding."""
        self.client.post(action_url("read", self.notification))

        self.notification.refresh_from_db()
        self.assertEqual(self.notification.status, NotificationStatus.ACTIVE)

    def test_mark_unread_reverses_it(self) -> None:
        self.client.post(action_url("read", self.notification))
        response = self.client.post(action_url("unread", self.notification))

        self.assertFalse(response.data["data"]["is_read"])

    def test_read_all_reports_how_many_changed(self) -> None:
        raise_alert(self.admin, dedupe_key="b")

        response = self.client.post(READ_ALL_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["marked_read"], 2)
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 0)

    def test_read_all_leaves_another_users_feed_alone(self) -> None:
        manager = make_lead_manager()
        raise_alert(manager, dedupe_key="theirs")

        self.client.post(READ_ALL_URL)

        self.assertIsNone(Notification.objects.get(recipient=manager).read_at)


class DismissEndpointTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.notification = raise_alert(self.admin)
        auth(self.client, self.admin)

    def test_dismiss_returns_the_terminal_row(self) -> None:
        response = self.client.post(action_url("dismiss", self.notification))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], NotificationStatus.DISMISSED)
        self.assertEqual(response.data["data"]["resolution"], "dismissed_by_user")
        self.assertIsNotNone(response.data["data"]["resolved_at"])

    def test_dismissing_twice_is_a_conflict_not_a_silent_success(self) -> None:
        self.client.post(action_url("dismiss", self.notification))

        response = self.client.post(action_url("dismiss", self.notification))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "NOTIFICATIONS_ALREADY_TERMINAL")
        self.assertEqual(response.data["error"]["details"]["status"], NotificationStatus.DISMISSED)


class NoWriteSurfaceTests(APITestCase):
    """The absence of an authoring surface is a decision, so it is asserted."""

    def setUp(self) -> None:
        self.admin = make_admin()
        self.notification = raise_alert(self.admin)
        auth(self.client, self.admin)

    def test_the_feed_cannot_be_posted_to(self) -> None:
        response = self.client.post(LIST_URL, {"title": "Hand-written"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_a_notification_cannot_be_edited_or_deleted(self) -> None:
        for method in (self.client.patch, self.client.put, self.client.delete):
            with self.subTest(method=method.__name__):
                response = method(detail_url(self.notification))
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
