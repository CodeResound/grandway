"""Management command: auth_session_report.

Read-only diagnostics for "I keep getting logged out". For one account over a
recent window it prints how many refreshes succeeded, were answered from the
reuse grace window, or were rejected (and why), and how many sessions were
revoked per reason. The mix points at the cause: ``rotated_reuse`` revocations
mean concurrent refreshes outside the grace window; ``refresh_rejected`` with
``replaced_same_device`` means another login on the same device; ``expired``
means the idle or absolute lifetime ran out.

Writes nothing.

Usage:
    python manage.py auth_session_report --username sita
    python manage.py auth_session_report --username sita --days 7
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from authenticate.managers import UserManager
from authenticate.selectors import (
    get_auth_event_counts_for_user,
    get_session_revocation_counts_for_user,
    get_user_by_username,
)


class Command(BaseCommand):
    help = "Count one account's refresh, rejection, and session-revocation events over recent days (read-only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--username", required=True, help="Account to report on.")
        parser.add_argument(
            "--days",
            type=int,
            default=1,
            help="Look-back window in days (default 1).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = UserManager.normalize_username(options["username"])
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be at least 1.")

        user = get_user_by_username(username)
        if user is None:
            raise CommandError(f"No user with username {username!r}.")

        since = timezone.now() - timedelta(days=days)
        self.stdout.write(f"Auth activity for {username!r} since {since.isoformat()} ({days} day(s))")

        self.stdout.write("\nAuth events (event_type / reason / outcome: count)")
        events = get_auth_event_counts_for_user(user, since)
        if not events:
            self.stdout.write("  none")
        for row in events:
            outcome = "ok" if row["success"] else "fail"
            self.stdout.write(f"  {row['event_type']} / {row['reason'] or '-'} / {outcome}: {row['count']}")

        self.stdout.write("\nSessions revoked (revoked_reason: count)")
        revocations = get_session_revocation_counts_for_user(user, since)
        if not revocations:
            self.stdout.write("  none")
        for row in revocations:
            self.stdout.write(f"  {row['revoked_reason'] or '-'}: {row['count']}")
