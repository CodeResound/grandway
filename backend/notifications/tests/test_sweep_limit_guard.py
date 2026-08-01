"""Regression test: ``--limit`` must never reach the resolve pass.

``--limit`` truncates each generator's source rows, and the key set of
"conditions that are true right now" is built from those same rows — so a
limited run's key set is partial by construction. The resolve pass treats every
active alert whose key is absent from that set as a condition that has cleared,
in one ``UPDATE``. Before the guard, ``--limit 5`` over 50 live alerts resolved
45 of them as SOURCE_CLEARED.

What makes it worth a test rather than a note: ``--limit`` is documented as "a
cautious first pass on a large database", which is exactly the database with the
most live alerts to destroy. The flag that reads as safe was the destructive one.
"""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TransactionTestCase

from notifications.constants import (
    GenerationSource,
    NotificationStatus,
    NotificationType,
)
from notifications.models import Notification
from notifications.tests.factories import make_admin


class SweepLimitGuardTests(TransactionTestCase):
    def _make_live_alerts(self, recipient, count: int) -> None:
        Notification.objects.bulk_create(
            Notification(
                recipient=recipient,
                notification_type=NotificationType.CHECKLIST_ITEM_OVERDUE,
                generated_by=GenerationSource.SWEEP,
                status=NotificationStatus.ACTIVE,
                dedupe_key=f"checklist_item_overdue:{index}",
                title=f"Item {index} overdue",
                body="",
            )
            for index in range(count)
        )

    def test_limit_does_not_resolve_live_alerts(self):
        admin = make_admin()
        self._make_live_alerts(admin, 50)

        out, err = StringIO(), StringIO()
        call_command("sweep_notifications", "--limit", "5", stdout=out, stderr=err)

        # None of the 50 may be touched: this run never looked at their sources.
        self.assertEqual(
            Notification.objects.filter(status=NotificationStatus.ACTIVE).count(),
            50,
        )
        self.assertIn("skipping the resolve pass", err.getvalue())

    def test_an_unlimited_run_still_resolves(self):
        """The guard must not disarm the resolve pass in general."""
        admin = make_admin()
        self._make_live_alerts(admin, 3)

        call_command("sweep_notifications", stdout=StringIO(), stderr=StringIO())

        # No checklist items exist, so every one of these keys is genuinely stale.
        self.assertEqual(
            Notification.objects.filter(status=NotificationStatus.ACTIVE).count(),
            0,
        )
