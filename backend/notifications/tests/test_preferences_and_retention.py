"""Preferences, categories, language-test expiry, and retention (2026-10-29, updates.md §4).

* Preferences are applied in ``dispatch``: a muted alert is never written.
* Categories are derived from the type — the filter, the summary, and the
  per-category read-all all agree on the same mapping.
* The sweep raises ``test_score_expiring`` and purges what is safe to forget,
  never a dismissed or still-active deadline alert.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

from applicants import services as applicant_services
from core.nepal.calendar import nepal_today
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from notifications import services
from notifications.constants import (
    GenerationSource,
    NotificationCategory,
    NotificationStatus,
    NotificationType,
    Resolution,
    SourceEntityType,
)
from notifications.models import Notification
from notifications.tests.factories import auth, make_admin, make_applicant, make_lead_manager, make_superadmin

PREFS_URL = reverse("v1:notifications:notification-preferences")
LIST_URL = reverse("v1:notifications:notification-list")
SUMMARY_URL = reverse("v1:notifications:notification-summary")
READ_ALL_URL = reverse("v1:notifications:notification-read-all")


def spec(notification_type: str = NotificationType.LEAD_CREATED, key: str = "k", **kw: Any) -> services.AlertSpec:
    return services.AlertSpec(
        notification_type=notification_type,
        dedupe_key=key,
        title="t",
        body="b",
        source_app="leads",
        source_entity_type=SourceEntityType.LEAD,
        source_entity_id=None,
        **kw,
    )


class DispatchPreferenceTests(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin("admin1")
        self.manager = make_lead_manager("manager1")

    def test_muted_category_writes_nothing(self) -> None:
        services.update_preferences(self.manager, in_app={NotificationCategory.LEAD: False})
        created = services.dispatch(spec(), [self.admin, self.manager])
        self.assertEqual([n.recipient for n in created], [self.admin])

    def test_assigned_only(self) -> None:
        services.update_preferences(self.manager, assigned_only=True)
        applicant_id = make_applicant(self.admin).id
        theirs = spec(NotificationType.APPLICANT_STATUS_CHANGED, "a", applicant_id=applicant_id, assignee_id=None)
        mine = spec(
            NotificationType.APPLICANT_STATUS_CHANGED, "b", applicant_id=applicant_id, assignee_id=self.manager.id
        )
        no_applicant = spec(NotificationType.LEAD_CREATED, "c")
        self.assertEqual(services.dispatch(theirs, [self.manager]), [])
        self.assertEqual(len(services.dispatch(mine, [self.manager])), 1)
        self.assertEqual(len(services.dispatch(no_applicant, [self.manager])), 1)

    def test_unmuting_restores_delivery(self) -> None:
        services.update_preferences(self.manager, in_app={NotificationCategory.LEAD: False})
        services.update_preferences(self.manager, in_app={NotificationCategory.LEAD: True})
        self.assertEqual(len(services.dispatch(spec(), [self.manager])), 1)


class PreferenceApiTests(APITestCase):
    def setUp(self) -> None:
        self.manager = make_lead_manager("manager1")
        self.other = make_lead_manager("manager2")
        auth(self.client, self.manager)

    def test_defaults(self) -> None:
        data = self.client.get(PREFS_URL).json()["data"]
        self.assertFalse(data["assigned_only"])
        self.assertEqual(set(data["categories"]), set(NotificationCategory.values))
        self.assertTrue(all(v == {"in_app": True} for v in data["categories"].values()))

    def test_patch_changes_only_what_is_sent_and_only_for_the_caller(self) -> None:
        self.client.patch(PREFS_URL, {"categories": {"lead": {"in_app": False}}}, format="json")
        response = self.client.patch(PREFS_URL, {"assigned_only": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertFalse(data["categories"]["lead"]["in_app"])
        self.assertTrue(data["categories"]["notes"]["in_app"])
        self.assertTrue(data["assigned_only"])
        auth(self.client, self.other)
        self.assertTrue(self.client.get(PREFS_URL).json()["data"]["categories"]["lead"]["in_app"])

    def test_unknown_category_is_a_400(self) -> None:
        response = self.client.patch(PREFS_URL, {"categories": {"gossip": {"in_app": False}}}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_superadmin_is_refused(self) -> None:
        auth(self.client, make_superadmin())
        self.assertEqual(self.client.get(PREFS_URL).status_code, 403)


class CategoryFeedTests(APITestCase):
    def setUp(self) -> None:
        self.manager = make_lead_manager("manager1")
        self.applicant_id = make_applicant(make_admin("admin1")).id
        services.dispatch(spec(NotificationType.LEAD_CREATED, "1"), [self.manager])
        services.dispatch(spec(NotificationType.VISIT_NOTE_ADDED, "2", applicant_id=self.applicant_id), [self.manager])
        services.dispatch(spec(NotificationType.PASSPORT_EXPIRING, "3"), [self.manager])
        auth(self.client, self.manager)

    def types(self, **params: str) -> set[str]:
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["notification_type"] for row in response.json()["data"]}

    def test_category_and_applicant_filters(self) -> None:
        self.assertEqual(self.types(category="lead,notes"), {"lead_created", "visit_note_added"})
        self.assertEqual(self.types(applicant_id=str(self.applicant_id)), {"visit_note_added"})
        self.assertEqual(self.client.get(LIST_URL, {"category": "lead,nope"}).status_code, 400)

    def test_rows_carry_category(self) -> None:
        row = next(r for r in self.client.get(LIST_URL).json()["data"] if r["notification_type"] == "visit_note_added")
        self.assertEqual((row["category"], row["applicant_id"]), ("notes", str(self.applicant_id)))

    def test_summary_by_category_and_read_all_by_category(self) -> None:
        summary = self.client.get(SUMMARY_URL).json()["data"]
        self.assertEqual((summary["by_category"]["lead"], summary["by_category"]["expiry"]), (1, 1))
        self.assertEqual(summary["unread"], 3)
        marked = self.client.post(READ_ALL_URL, {"category": "lead"}, format="json").json()["data"]["marked_read"]
        self.assertEqual(marked, 1)
        summary = self.client.get(SUMMARY_URL).json()["data"]
        self.assertEqual((summary["unread"], summary["by_category"]["lead"]), (2, 0))
        self.assertEqual(self.client.post(READ_ALL_URL, {}, format="json").json()["data"]["marked_read"], 2)


def sweep(**options: Any) -> str:
    out = StringIO()
    call_command("sweep_notifications", stdout=out, stderr=StringIO(), **options)
    return out.getvalue()


class LanguageTestExpiryTests(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = make_admin("admin1")
        self.manager = make_lead_manager("manager1")
        self.applicant = make_applicant(self.admin)

    def give_test(self, expires_in_days: int) -> None:
        today = nepal_today()
        applicant_services.update_applicant(
            actor=self.admin,
            applicant=self.applicant,
            fields={},
            language_tests=[
                {
                    "test_type": "ielts",
                    "overall_score": "7.0",
                    "test_date": today - timedelta(days=600),
                    "expiry_date": today + timedelta(days=expires_in_days),
                }
            ],
        )

    def alerts(self) -> Any:
        return Notification.objects.filter(notification_type=NotificationType.TEST_SCORE_EXPIRING)

    def test_raised_for_admins_plus_assignee_and_resolved_on_renewal(self) -> None:
        applicant_services.assign_applicant(actor=self.admin, applicant=self.applicant, assignee=self.manager)
        self.give_test(30)
        sweep(only_type=NotificationType.TEST_SCORE_EXPIRING)
        self.assertEqual(set(self.alerts().values_list("recipient__username", flat=True)), {"admin1", "manager1"})
        self.assertNotIn("7.0", self.alerts().first().title + self.alerts().first().body)

        self.give_test(700)  # a retake: the old condition is gone
        sweep(only_type=NotificationType.TEST_SCORE_EXPIRING)
        self.assertFalse(self.alerts().filter(status=NotificationStatus.ACTIVE).exists())

    def test_outside_the_horizon_raises_nothing(self) -> None:
        self.give_test(200)
        sweep(only_type=NotificationType.TEST_SCORE_EXPIRING)
        self.assertFalse(self.alerts().exists())


class RetentionTests(TestCase):
    def setUp(self) -> None:
        self.user = make_admin("admin1")

    def make(self, key: str, *, generated_by: str, status: str = NotificationStatus.ACTIVE, age: int = 120) -> Any:
        notification = services.dispatch(spec(key=key), [self.user], generated_by=generated_by)[0]
        fields: dict[str, Any] = {"created_at": timezone.now() - timedelta(days=age), "status": status}
        if status != NotificationStatus.ACTIVE:
            fields.update(resolved_at=timezone.now(), resolution=Resolution.SOURCE_CLEARED)
        Notification.objects.filter(pk=notification.pk).update(**fields)
        return notification

    def test_purges_only_what_is_safe_to_forget(self) -> None:
        old_event = self.make("event", generated_by=GenerationSource.SIGNAL)
        old_resolved = self.make("resolved", generated_by=GenerationSource.SWEEP, status=NotificationStatus.RESOLVED)
        old_dismissed = self.make(
            "dismissed", generated_by=GenerationSource.SWEEP, status=NotificationStatus.DISMISSED
        )
        old_active = self.make("active", generated_by=GenerationSource.SWEEP)
        young_event = self.make("young", generated_by=GenerationSource.SIGNAL, age=10)

        self.assertEqual(services.purge_expired(older_than_days=90), 2)
        remaining = set(Notification.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {old_dismissed.pk, old_active.pk, young_event.pk})
        self.assertNotIn(old_event.pk, remaining)
        self.assertNotIn(old_resolved.pk, remaining)

    def test_sweep_purges_unless_dry_run_limited_or_disabled(self) -> None:
        self.make("event", generated_by=GenerationSource.SIGNAL)
        sweep(dry_run=True)
        sweep(limit=1)
        sweep(retention_days=0)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertIn("1 purged", sweep())
        self.assertEqual(Notification.objects.count(), 0)
