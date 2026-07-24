"""Data model for the notifications app.

See ``notifications/docs/DATA_CONTRACT.md`` for the authoritative contract.

One table, and four conventions run through it — every one of them deliberate:

* **The alert points at its source; it never copies it.** ``source_app``,
  ``source_entity_type``, and ``source_entity_id`` are strings and a bare UUID,
  not foreign keys. That is the mechanism keeping this app from becoming a second
  copy of the business graph: a notification can name a record in an app that
  does not exist yet, no migration here is needed when one arrives, and no
  deletion anywhere can break this table. The concept file's boundary rule —
  "should not own applicants, documents, offers, or checklists" — is enforced by
  the absence of those foreign keys, not by anybody remembering it.
* **``(recipient, dedupe_key)`` is unique, unconditionally.** This is the whole
  idempotency guarantee of the app and it lives in the database because the
  nightly sweep, five signal receivers, the admin, and the shell can all write.
  Every generator goes through ``get_or_create`` on that pair; nothing anywhere
  compares a previous field value to a new one.
* **Read state and lifecycle state are separate columns.** An alert somebody has
  read is still active work. Folding ``read_at`` into ``status`` would make "I
  have seen this" indistinguishable from "this is handled", which is the
  distinction the concept file draws when it lists "unread and read state" and
  "resolved or dismissed state" as two separate requirements.
* **Nothing is ever deleted.** ``dismissed`` and ``resolved`` are terminal
  states and the row stays — ``concepts/notifications.txt`` requires it in as
  many words: "preserve the alert history even after the source issue is fixed."
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.models import BaseModel
from django.db import models
from django.utils import timezone

from notifications.constants import (
    DEFAULT_DUE_WITHIN_DAYS,
    TERMINAL_STATUSES,
    DeliveryChannel,
    DeliveryState,
    DueBucket,
    GenerationSource,
    NotificationStatus,
    NotificationType,
    Priority,
    Resolution,
)


class Notification(BaseModel):
    """One alert, for one person, about one source record.

    Created only by ``services.create_notification`` — called by the sweep
    command and by this app's signal receivers. There is no create endpoint and
    no other app imports this module, which is what keeps a failure to alert from
    ever becoming a failure to save the thing being alerted about.

    A condition affecting three Admins is three rows, not one row with three
    readers. That costs storage and buys the thing a shared row cannot give:
    read, dismissal, and resolution are per-person facts, and a second table to
    hold them would put a join on the single most frequently-run query in the
    app (the unread badge).
    """

    recipient = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="notifications",
        db_index=True,
        help_text="Who must act. Users are deactivated, never deleted, so PROTECT never fires in practice.",
    )

    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        db_index=True,
        help_text="Drives priority, grouping, and iconography — never business logic.",
    )

    # Stored, not derived. Re-rating a type later is a legitimate thing to want;
    # silently rewriting what every past alert claimed about its own urgency is
    # not. ``services.create_notification`` maps this from the type and no caller
    # may supply it.
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
    )

    # Plain fields rather than named identities. These are sentences this
    # system composes from a source record, not a second canonical identity of an
    # entity — the same call ``documents.label``, ``document_templates.label``,
    # and ``checklists.label`` recorded. §39.1 exists because an organization
    # genuinely has two legal names; "Passport expires in 21 days" is not a name.
    title = models.CharField(max_length=200, help_text="What happened, in one line.")
    body = models.TextField(blank=True, help_text="Why it needs attention and what to do next.")

    # --- The source record ---------------------------------------------------
    #
    # Strings and a bare UUID, never foreign keys. See the module docstring.
    source_app = models.CharField(max_length=50, help_text="The app that owns the record, e.g. 'checklists'.")
    source_entity_type = models.CharField(
        max_length=50,
        help_text="The record kind, e.g. 'checklist_item'. Shares audit.AuditEvent's vocabulary by convention.",
    )
    source_entity_id = models.UUIDField(null=True, blank=True)
    source_api_path = models.CharField(
        max_length=255,
        blank=True,
        help_text="Canonical API path of the source, so a client is not guessing routes.",
    )

    due_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When this becomes urgent, copied from the source deadline. Null for a lifecycle alert.",
    )

    # --- Read state (orthogonal to status) -----------------------------------
    read_at = models.DateTimeField(null=True, blank=True, help_text="Null means unread.")

    # --- Lifecycle state -----------------------------------------------------
    #
    # Denormalized current state (§35 item 15): a plain field read answers "is
    # this still open", while the append-only ``audit`` log remains the
    # authoritative event history. Matches ``checklists``, ``offers``,
    # ``uploaded_files``, and ``applicant_journeys``.
    status = models.CharField(
        max_length=15,
        choices=NotificationStatus.choices,
        default=NotificationStatus.ACTIVE,
        db_index=True,
    )
    resolution = models.CharField(
        max_length=20,
        choices=Resolution.choices,
        blank=True,
        help_text="Why it stopped being active. Blank while active.",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    dismissed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_dismissed",
        help_text="Set only on a manual dismiss. Always equals recipient today.",
    )

    # --- Delivery ------------------------------------------------------------
    #
    # One channel in v1. The columns exist anyway because the concept file is
    # explicit that future channels "should all point back to the same
    # notification record" — so adding email is an additive migration here rather
    # than a second table that has to be kept in agreement with this one.
    delivery_channel = models.CharField(
        max_length=15,
        choices=DeliveryChannel.choices,
        default=DeliveryChannel.IN_APP,
    )
    delivery_state = models.CharField(
        max_length=15,
        choices=DeliveryState.choices,
        default=DeliveryState.PENDING,
    )
    delivered_at = models.DateTimeField(null=True, blank=True)

    # --- Idempotency ---------------------------------------------------------
    dedupe_key = models.CharField(
        max_length=255,
        help_text="'<type>:<entity_type>:<entity_id>[:<discriminator>]'. Unique per recipient.",
    )
    generated_by = models.CharField(
        max_length=10,
        choices=GenerationSource.choices,
        db_index=True,
        help_text="The sweep's resolve pass only ever touches 'sweep' rows.",
    )

    class Meta:
        db_table = "notifications_notification"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        # Newest first with ``id`` as a tiebreaker: ``created_at`` is not unique
        # — one sweep writes hundreds of rows in one transaction — and a
        # non-unique sort key under page-number pagination lets a row appear on
        # two pages or on none. Same reasoning ``checklists.Checklist`` records.
        ordering = ["-created_at", "-id"]
        constraints = [
            # The whole idempotency guarantee of the app. Unconditional, not
            # partial: a resolved alert must keep occupying its key, or the next
            # sweep would raise the identical alert again the moment the work was
            # finished. Genuinely new instances of a condition get in through a
            # new discriminator (a new due date, a new stage, a new assignee),
            # never by an old row standing aside.
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"],
                name="notification_one_per_recipient_key",
            ),
            # Lifecycle boolean ↔ timestamp coherence, the same rule §35 item 15
            # imposes on the policy engine's own denormalized state. Without it,
            # a row can claim to be resolved while carrying no resolution and no
            # timestamp — which reads, in every list this app returns, as an
            # alert that closed itself for no reason.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=NotificationStatus.ACTIVE,
                        resolution="",
                        resolved_at__isnull=True,
                    )
                    | (
                        models.Q(
                            status__in=TERMINAL_STATUSES,
                            resolved_at__isnull=False,
                        )
                        & ~models.Q(resolution="")
                    )
                ),
                name="notification_resolution_matches_status",
            ),
        ]
        indexes = [
            # The feed. Always scoped to one recipient, almost always to active.
            models.Index(fields=["recipient", "status", "-created_at"], name="notif_feed_idx"),
            # The bell badge — the most frequently-run query in the app.
            models.Index(fields=["recipient", "read_at"], name="notif_unread_idx"),
            # The sweep's resolve pass, and the due-bucket filter.
            models.Index(fields=["status", "due_at"], name="notif_status_due_idx"),
            # "Every alert ever raised about this record" — what makes the
            # retained history usable rather than merely stored.
            models.Index(fields=["source_entity_type", "source_entity_id"], name="notif_source_idx"),
        ]

    def __str__(self) -> str:
        # Local columns only — naming the recipient here would read better and
        # fire one query per row in the admin changelist.
        return f"{self.title} ({self.notification_type}/{self.status})"

    # --- Derived state -------------------------------------------------------
    #
    # Computed, never stored. A stored ``is_read`` alongside ``read_at``, or a
    # stored due bucket, would be a second source of truth that goes stale — the
    # bucket within hours.

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @property
    def is_active(self) -> bool:
        """True while this still represents work somebody has to do."""
        return self.status == NotificationStatus.ACTIVE

    def due_bucket(
        self,
        *,
        now: datetime | None = None,
        due_within_days: int = DEFAULT_DUE_WITHIN_DAYS,
    ) -> str:
        """Which of the concept file's due-now / due-soon / later groups this falls in.

        Takes ``now`` so a serializer rendering a page of rows resolves the
        current time once rather than per row — otherwise a list straddling a
        boundary could place two identically-due rows in different buckets.
        """
        if self.due_at is None:
            return DueBucket.NONE
        moment = now or timezone.now()
        if self.due_at < moment:
            return DueBucket.OVERDUE
        if self.due_at <= moment + timedelta(days=due_within_days):
            return DueBucket.DUE_SOON
        return DueBucket.LATER
