"""Enums, priority mapping, error codes, and audit-action names for the notifications app.

See ``notifications/docs/DATA_CONTRACT.md`` for the authoritative contract.

Two vocabularies here look like ones other apps already declare and are declared
locally on purpose (§4 forbids importing another app's models, and an enum quietly
shared across a boundary is what makes a later divergence invisible):

* ``Priority`` reads like ``core.policy_engine``'s risk levels. They answer
  different questions — one rates how dangerous an endpoint is, the other how
  urgently a person should look at a row — and tying them together would mean a
  risk re-rating silently changed what staff see first in their inbox.
* ``GenerationSource`` mirrors ``checklists.ChecklistOrigin``'s auto/manual split
  in spirit. The values differ (``sweep``/``signal``) because the distinction
  that matters here is not "who asked for it" but "does this alert have an
  ongoing condition the sweep can re-check" — only ``sweep`` rows do.
"""

from django.db import models

__all__ = [
    "AUDIT_APP_LABEL",
    "AUDIT_ENTITY_NOTIFICATION",
    "DEFAULT_DUE_WITHIN_DAYS",
    "DEFAULT_PASSPORT_HORIZON_DAYS",
    "SIGNAL_TYPES",
    "SWEEP_TYPES",
    "TERMINAL_STATUSES",
    "TYPE_PRIORITY",
    "UNGENERATED_TYPES",
    "DeliveryChannel",
    "DeliveryState",
    "DueBucket",
    "ErrorCode",
    "GenerationSource",
    "NotificationAuditAction",
    "NotificationStatus",
    "NotificationType",
    "Priority",
    "Resolution",
    "SourceEntityType",
]


class NotificationType(models.TextChoices):
    """What kind of thing happened.

    The concept file's nine types (``concepts/notifications.txt`` — "Notification
    types"), expanded where one concept type covers two operationally different
    states. "Checklist due and overdue alerts" is two values rather than one
    because they carry different priorities and, more importantly, different
    dedupe keys — which is what lets an item escalate from one to the other
    without either re-nagging or going quiet.

    ``MISSING_INFORMATION``, ``APPOINTMENT_REMINDER``, and ``TEST_SCORE_EXPIRING``
    are declared with **no generator**. The first has no source — no app in this
    project defines what "required information" is — and the other two belong to
    ``appointments`` and ``test_scores``, which do not exist. They are here so the
    frontend receives the whole vocabulary in one contract and so writing the
    generator later is not a schema change.
    """

    # --- Deadline-driven (raised by the sweep) --------------------------------
    CHECKLIST_ITEM_DUE = "checklist_item_due", "Checklist Item Due"
    CHECKLIST_ITEM_OVERDUE = "checklist_item_overdue", "Checklist Item Overdue"
    MISSING_DOCUMENTS = "missing_documents", "Missing Documents"
    OFFER_RESPONSE_DUE = "offer_response_due", "Offer Response Due"
    OFFER_EXPIRED = "offer_expired", "Offer Response Overdue"
    PASSPORT_EXPIRING = "passport_expiring", "Passport Expiring"

    # --- Event-driven (raised by a signal receiver) ---------------------------
    ASSIGNMENT_RECEIVED = "assignment_received", "Assignment Received"
    FILE_REJECTED = "file_rejected", "File Rejected"
    JOURNEY_STAGE_CHANGED = "journey_stage_changed", "Journey Stage Changed"
    JOURNEY_CLOSED = "journey_closed", "Journey Closed"
    OFFER_DECIDED = "offer_decided", "Offer Decided"

    # --- Declared, not yet generated ------------------------------------------
    MISSING_INFORMATION = "missing_information", "Missing Information"
    APPOINTMENT_REMINDER = "appointment_reminder", "Appointment Reminder"
    TEST_SCORE_EXPIRING = "test_score_expiring", "Test Score Expiring"


class Priority(models.TextChoices):
    """How urgently the recipient should look at this.

    Four levels, not three: ``urgent`` exists solely so a deadline that has
    *already passed on an irreversible commitment* — an offer nobody answered —
    can outrank the large, steady population of merely-high items. Collapsing it
    into ``high`` would put the one alert that cannot be fixed by working faster
    in the same bucket as forty that can.
    """

    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class NotificationStatus(models.TextChoices):
    """Where this alert stands.

    Deliberately **orthogonal to read state**. An alert someone has read is still
    ``active`` work; the concept file lists "unread and read state" and "resolved
    or dismissed state" as two separate things, and folding them into one column
    would make "I have seen this" indistinguishable from "this is handled".

    The concept's third terminal state, ``expired``, is folded into ``RESOLVED``.
    It and ``resolved`` would be written by the same code path for the same
    reason — the source condition stopped being true — so a separate value would
    only ever be a second name for one fact. ``Resolution`` carries the
    distinction where it matters.
    """

    ACTIVE = "active", "Active"
    DISMISSED = "dismissed", "Dismissed"
    RESOLVED = "resolved", "Resolved"


class Resolution(models.TextChoices):
    """Why this alert stopped being active.

    Stored rather than inferred from which timestamp is set, because "the work
    got done" and "somebody made this go away" are the two facts an operations
    lead actually wants to tell apart when reviewing a quiet inbox.
    """

    SOURCE_CLEARED = "source_cleared", "Source condition cleared"
    DISMISSED_BY_USER = "dismissed_by_user", "Dismissed by user"


class DeliveryChannel(models.TextChoices):
    """Where this alert was delivered.

    One value in v1. The column exists anyway because the concept file is
    explicit that future channels "should all point back to the same
    notification record" — the alert stays the source of truth for delivery
    status, so adding email is an additive migration on this table rather than a
    second table that has to be kept in agreement with it.
    """

    IN_APP = "in_app", "In-App"


class DeliveryState(models.TextChoices):
    """Whether the alert reached its channel.

    ``in_app`` is ``delivered`` the moment the row exists — there is nothing
    between writing it and the recipient's feed being able to return it. The
    other two values are unreachable in v1 and are declared for the same reason
    ``DeliveryChannel`` has only one member.
    """

    PENDING = "pending", "Pending"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"


class GenerationSource(models.TextChoices):
    """What produced this alert.

    Load-bearing, not descriptive: the sweep's resolve pass only ever touches
    ``SWEEP`` rows. A signal alert records that something *happened* and has no
    ongoing condition left to re-check, so auto-resolving one would mean deciding
    a stage change had un-happened.
    """

    SWEEP = "sweep", "Deadline sweep"
    SIGNAL = "signal", "Source event"


class DueBucket(models.TextChoices):
    """The concept file's "due now / due soon / later" grouping.

    **Derived at read time, never stored.** A stored bucket would be wrong by the
    next morning, and a nightly job whose only purpose was to move rows between
    buckets would be a second source of truth for a fact ``due_at`` already
    holds. Used as a query-parameter vocabulary and as a serializer field.
    """

    OVERDUE = "overdue", "Overdue"
    DUE_SOON = "due_soon", "Due Soon"
    LATER = "later", "Later"
    NONE = "none", "No due date"


class SourceEntityType:
    """``Notification.source_entity_type`` values.

    Plain strings shared with ``audit.AuditEvent.entity_type`` by convention, so
    that "everything that happened to this record" and "every alert raised about
    it" can be asked with the same pair of values. Not a ``TextChoices``: the
    column deliberately has no ``choices=``, because this app must be able to
    point at a record in an app that does not exist yet without a migration.
    """

    CHECKLIST = "checklist"
    CHECKLIST_ITEM = "checklist_item"
    OFFER = "offer"
    PASSPORT_DETAIL = "passport_detail"
    UPLOADED_FILE = "uploaded_file"
    APPLICANT_JOURNEY = "applicant_journey"


#: Priority for each type, applied once at creation by ``services.create_notification``.
#:
#: Stored on the row rather than looked up at read time. Re-rating a type later
#: is a legitimate thing to want to do; silently rewriting what every past alert
#: claimed about its own urgency is not.
#:
#: The argument for each rating, since a table of adjectives is otherwise
#: unfalsifiable:
#:
#: * ``OFFER_EXPIRED`` is the only ``urgent``. Every other overdue thing here can
#:   still be fixed by doing the work today; an unanswered offer deadline may
#:   have already cost the applicant the place.
#: * ``PASSPORT_EXPIRING`` is ``high`` despite a six-month horizon, because it is
#:   the one blocker that cannot be resolved inside the office at any speed.
#: * ``JOURNEY_STAGE_CHANGED`` is ``low``: it is the routine heartbeat of the
#:   system, useful as context and never as an instruction.
TYPE_PRIORITY: dict[str, str] = {
    NotificationType.CHECKLIST_ITEM_DUE: Priority.NORMAL,
    NotificationType.CHECKLIST_ITEM_OVERDUE: Priority.HIGH,
    NotificationType.MISSING_DOCUMENTS: Priority.NORMAL,
    NotificationType.MISSING_INFORMATION: Priority.NORMAL,
    NotificationType.OFFER_RESPONSE_DUE: Priority.HIGH,
    NotificationType.OFFER_EXPIRED: Priority.URGENT,
    NotificationType.PASSPORT_EXPIRING: Priority.HIGH,
    NotificationType.TEST_SCORE_EXPIRING: Priority.HIGH,
    NotificationType.APPOINTMENT_REMINDER: Priority.NORMAL,
    NotificationType.ASSIGNMENT_RECEIVED: Priority.NORMAL,
    NotificationType.FILE_REJECTED: Priority.HIGH,
    NotificationType.JOURNEY_STAGE_CHANGED: Priority.LOW,
    NotificationType.JOURNEY_CLOSED: Priority.NORMAL,
    NotificationType.OFFER_DECIDED: Priority.NORMAL,
}

#: Types the sweep raises and may therefore auto-resolve.
#:
#: The resolve pass is scoped to exactly these. A type absent from this tuple can
#: never be resolved by a sweep, however the sweep is invoked — which is what
#: stops a ``--type`` run from mass-resolving alerts it did not examine.
SWEEP_TYPES: tuple[str, ...] = (
    NotificationType.CHECKLIST_ITEM_DUE,
    NotificationType.CHECKLIST_ITEM_OVERDUE,
    NotificationType.MISSING_DOCUMENTS,
    NotificationType.OFFER_RESPONSE_DUE,
    NotificationType.OFFER_EXPIRED,
    NotificationType.PASSPORT_EXPIRING,
)

#: Types a signal receiver raises. Never auto-resolved — see ``GenerationSource``.
SIGNAL_TYPES: tuple[str, ...] = (
    NotificationType.ASSIGNMENT_RECEIVED,
    NotificationType.FILE_REJECTED,
    NotificationType.JOURNEY_STAGE_CHANGED,
    NotificationType.JOURNEY_CLOSED,
    NotificationType.OFFER_DECIDED,
)

#: Declared in the vocabulary, produced by nothing. Kept as a named tuple rather
#: than a comment so the test suite can assert the gap is exactly this wide and
#: no wider — a new type that nobody generates is a bug, not a feature.
UNGENERATED_TYPES: tuple[str, ...] = (
    NotificationType.MISSING_INFORMATION,
    NotificationType.APPOINTMENT_REMINDER,
    NotificationType.TEST_SCORE_EXPIRING,
)

#: Statuses in which an alert is no longer active work.
TERMINAL_STATUSES: tuple[str, ...] = (
    NotificationStatus.DISMISSED,
    NotificationStatus.RESOLVED,
)

#: Default horizon for "due soon", matching ``dashboards.DEFAULT_DUE_WITHIN_DAYS``
#: by value and declared separately by §4. The two are the same number today
#: because a week is the natural planning horizon in both places, not because
#: either app is reading the other.
DEFAULT_DUE_WITHIN_DAYS: int = 7

#: Default horizon for passport expiry, matching the six months
#: ``applicants.get_expiring_passports`` already defaults to. Renewing a Nepali
#: passport is not a same-week errand.
DEFAULT_PASSPORT_HORIZON_DAYS: int = 180


class NotificationAuditAction:
    """``audit.AuditEvent.action`` names written by this app.

    Only three, and none of them records a notification being *created*. Writing
    an audit event per alert would double the write volume of the nightly sweep
    to record that the system told someone something — which the notification row
    already is. What is audited here is a human decision (dismissal) and a
    failure that would otherwise be invisible.
    """

    NOTIFICATION_DISMISSED = "notification_dismissed"
    SWEEP_COMPLETED = "notification_sweep_completed"
    GENERATION_FAILED = "notification_generation_failed"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "notifications"

#: ``audit.AuditEvent.entity_type`` value for this app's own model.
AUDIT_ENTITY_NOTIFICATION = "notification"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the notifications app (§7)."""

    #: The caller's authority may not use the notification feed at all —
    #: Superadmin. This is the *only* 403 the app returns.
    ACTOR_FORBIDDEN = "NOTIFICATIONS_ACTOR_FORBIDDEN"

    #: No such notification **on the caller's own feed**. Another user's
    #: notification returns this rather than a 403, deliberately: a 403 would
    #: confirm the id exists on somebody else's feed, and a notification title
    #: names an applicant and the document they are missing.
    NOTIFICATION_NOT_FOUND = "NOTIFICATIONS_NOTIFICATION_NOT_FOUND"

    #: Dismissing something already dismissed or resolved. A 409 rather than a
    #: silent success, so a client that has drifted out of sync learns it.
    ALREADY_TERMINAL = "NOTIFICATIONS_ALREADY_TERMINAL"

    # No filter-validation code is declared here. Every query parameter this app
    # accepts is validated by ``NotificationFilterSerializer``, so a bad value is
    # answered by the global handler with ``VALIDATION_ERROR`` (400) naming the
    # offending field — which is more useful than an app-specific code saying
    # only "a filter was wrong". A code nothing can raise is a promise to
    # consumers that this app cannot keep.
