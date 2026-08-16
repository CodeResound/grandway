"""The Reminder model — a one-off future follow-up against one record.

``concepts/reminders.txt``: three essential parts — a source record, a future
due date, and a note explaining why the reminder exists. The due date is
date-only; the reminder is due at the start of that day, Nepal time. The row
never carries the alert itself: ``notifications`` raises the due alert from
this table on its nightly sweep and owns it from there.
"""

from __future__ import annotations

from core.models import BaseModel
from django.db import models

from reminders.constants import OWNER_FIELDS, ReminderStatus


def _single_owner_condition() -> models.Q:
    """Build the "exactly one owner FK is set" database condition.

    Written as an explicit disjunction rather than an arithmetic null-count so
    it evaluates identically on PostgreSQL and on the SQLite the test suite
    runs against. Derived from ``OWNER_FIELDS`` rather than typed out, so a
    third owner extends the constraint by extending one tuple. Same shape as
    ``uploaded_files``.
    """
    condition = models.Q()
    for owner in OWNER_FIELDS:
        clause = {f"{field}__isnull": field != owner for field in OWNER_FIELDS}
        condition |= models.Q(**clause)
    return condition


class Reminder(BaseModel):
    """One future follow-up note tied to exactly one applicant or client.

    The owner is immutable after creation: a reminder set against the wrong
    record is dismissed and recreated, which keeps the audit trail and the
    notification source stable. Reschedule history is not stored here — the
    audit log carries every ``due_date`` change, and the notification layer's
    dedupe discriminator carries the current date.
    """

    # --- Ownership: exactly one of two --------------------------------------
    #
    # ``PROTECT`` on both, matching every cross-app FK in the project: a
    # record with follow-ups on it cannot be removed out from under them.
    applicant = models.ForeignKey(
        "applicants.Applicant",
        on_delete=models.PROTECT,
        related_name="reminders",
        null=True,
        blank=True,
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="reminders",
        null=True,
        blank=True,
    )

    # --- The reminder itself -------------------------------------------------
    #
    # Date-only, deliberately: "this avoids the complexity of time zones,
    # exact hours, and user scheduling differences" (concept). The rendering
    # to a datetime (Kathmandu midnight) happens only in the notifications
    # composer.
    due_date = models.DateField()
    note = models.TextField()

    # --- Lifecycle -----------------------------------------------------------
    #
    # One ``closed_at``/``closed_by`` pair for both terminal states; ``status``
    # says which one happened. Separate per-action timestamps would need a
    # four-way coherence constraint for no query a status filter doesn't
    # already answer.
    status = models.CharField(
        max_length=15,
        choices=ReminderStatus.choices,
        default=ReminderStatus.ACTIVE,
        db_index=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        related_name="reminders_closed",
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="reminders_created",
    )

    class Meta:
        db_table = "reminders_reminder"
        # ``-id`` breaks ties so pagination is stable when two reminders share
        # a creation timestamp.
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=_single_owner_condition(),
                name="reminder_single_owner",
            ),
            # ``active`` has no closure stamp; a terminal status always has
            # one. ``closed_by`` stays outside the constraint — it is
            # ``SET_NULL``, the same reason ``notifications`` keeps
            # ``dismissed_by`` outside its coherence constraint.
            models.CheckConstraint(
                condition=(
                    models.Q(status=ReminderStatus.ACTIVE, closed_at__isnull=True)
                    | models.Q(
                        status__in=[s for s in ReminderStatus.values if s != ReminderStatus.ACTIVE],
                        closed_at__isnull=False,
                    )
                ),
                name="reminder_closure_matches_status",
            ),
        ]
        indexes = [
            # The applicant detail screen's reminders panel.
            models.Index(fields=["applicant", "-created_at"], name="reminder_applicant_idx"),
            # The client detail screen's reminders panel.
            models.Index(fields=["client", "-created_at"], name="reminder_client_idx"),
            # The nightly sweep (status=active, due_date<=today) and the
            # list's status + due-window filters.
            models.Index(fields=["status", "due_date"], name="reminder_sweep_idx"),
        ]

    def __str__(self) -> str:
        note = self.note if len(self.note) <= 50 else f"{self.note[:47]}..."
        return f"Reminder({note!r}, due {self.due_date}, {self.status})"

    @property
    def owner_type(self) -> str | None:
        """Which kind of record this reminder is set against, from the FKs."""
        for field in OWNER_FIELDS:
            if getattr(self, f"{field}_id") is not None:
                return field
        return None

    @property
    def owner_id(self) -> object | None:
        """The id of whichever owner is set."""
        for field in OWNER_FIELDS:
            value = getattr(self, f"{field}_id")
            if value is not None:
                return value
        return None

    @property
    def is_active(self) -> bool:
        """The reminder is still open."""
        return self.status == ReminderStatus.ACTIVE
