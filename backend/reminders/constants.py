"""Enums, audit vocabulary, and error codes for the reminders app.

A reminder is a one-off future follow-up against exactly one applicant or
client (``concepts/reminders.txt``). The vocabulary here mirrors the
``uploaded_files`` owner pattern and the project-wide audit conventions.
"""

from __future__ import annotations

from django.db import models


class OwnerType(models.TextChoices):
    """Which kind of record a reminder is set against.

    Never stored as a column — ``Reminder.owner_type`` is derived from the two
    foreign keys on the model; the column that is set determines the value.
    Storing it as well would create a second source of truth that could
    disagree with the foreign keys — exactly what the
    ``reminder_single_owner`` constraint exists to prevent.

    The concept scopes reminders to applicants and clients only. A third owner
    is one more value here, one more column, and one more entry in
    ``OWNER_FIELDS`` — but it needs a concept change first.
    """

    APPLICANT = "applicant", "Applicant"
    CLIENT = "client", "Client"


#: The model field name behind each owner type, in the order the serializer and
#: the database constraint both walk them. One tuple, so a new owner is added
#: in exactly one place.
OWNER_FIELDS: tuple[str, ...] = (
    OwnerType.APPLICANT,
    OwnerType.CLIENT,
)


class ReminderStatus(models.TextChoices):
    """A reminder's lifecycle.

    ``completed`` and ``dismissed`` are both terminal — there is no reopen.
    The concept is explicit: a follow-up that outlives its reminder gets a new
    reminder with a new date and note, which keeps every reminder's history a
    single closed story.
    """

    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    DISMISSED = "dismissed", "Dismissed"


#: The statuses a reminder can never leave.
TERMINAL_STATUSES: tuple[str, ...] = (
    ReminderStatus.COMPLETED,
    ReminderStatus.DISMISSED,
)


class ReminderAuditAction:
    """Audit log action names (``audit.AuditEvent.action``).

    ``RESCHEDULED`` and ``UPDATED`` are distinct: moving the due date changes
    when the consultancy is prompted — the event the concept most wants
    traceable — while a note correction changes only the wording.
    """

    REMINDER_CREATED = "reminder_created"
    REMINDER_RESCHEDULED = "reminder_rescheduled"
    REMINDER_UPDATED = "reminder_updated"
    REMINDER_COMPLETED = "reminder_completed"
    REMINDER_DISMISSED = "reminder_dismissed"


AUDIT_APP_LABEL = "reminders"
AUDIT_ENTITY_REMINDER = "reminder"


class ErrorCode:
    """Stable error codes (§7, ``APP_RESOURCE_REASON``). Documented in ``docs/API.md``.

    Field-level validation failures (missing owner, two owners, past date,
    blank note) go through the global ``VALIDATION_ERROR`` handler with the
    field errors in ``error.details``, matching the rest of the project.
    """

    ACTOR_FORBIDDEN = "REMINDERS_ACTOR_FORBIDDEN"
    REMINDER_NOT_FOUND = "REMINDERS_REMINDER_NOT_FOUND"
    REMINDER_ALREADY_CLOSED = "REMINDERS_REMINDER_ALREADY_CLOSED"
    OWNER_REQUIRED = "REMINDERS_OWNER_REQUIRED"
    OWNER_NOT_FOUND = "REMINDERS_OWNER_NOT_FOUND"
    FIELD_IMMUTABLE = "REMINDERS_FIELD_IMMUTABLE"
