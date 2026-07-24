"""Request validation and response shaping for the notifications app.

Almost every serializer in this project validates something a user typed. None
here does — a client cannot create or edit a notification, so the only input
this app accepts is a filter set on the feed. Two consequences follow, and both
are departures from the shape the other apps have:

* **§39.2 Unicode normalization has no write path to apply to.** Titles and
  bodies are composed by ``services.py`` from fields the owning apps already
  normalized on write.
* **The read serializer is fully read-only, by construction rather than by a
  ``read_only_fields`` list.** Every field is either a model field on a
  serializer with no ``create``/``update``, or a method field.

``due_bucket`` and ``is_read`` are computed rather than stored (see
``models.py``), and ``due_at_bs`` is required by §39.4 — a deadline is the one
kind of date staff read off a Bikram Sambat calendar.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.nepal.calendar import to_bs
from django.utils import timezone
from rest_framework import serializers

from notifications.constants import (
    DEFAULT_DUE_WITHIN_DAYS,
    DueBucket,
    NotificationStatus,
    NotificationType,
    Priority,
)
from notifications.models import Notification

#: Upper bound on the ``due_within_days`` control. A horizon wider than a year
#: makes "due soon" mean nothing, and an unbounded one lets a client turn the
#: bucket filter into a full-table scan on a query that runs on every page load.
MAX_DUE_WITHIN_DAYS: int = 365


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """Render a stored date/datetime as its Bikram Sambat date (§39.4)."""
    return to_bs(value).to_dict() if value else None


class NotificationFilterSerializer(serializers.Serializer):
    """Query parameters for the feed and the summary.

    Nothing is required. An unfiltered feed is the normal first load, and every
    field defaults to "do not narrow on this" — including ``status``, because the
    concept file requires the alert history be preserved after the source issue
    is fixed, and defaulting to ``active`` here would hide it behind a parameter
    nobody knew to pass.

    ``is_read`` is a ``BooleanField`` read from a query string, which DRF treats
    as HTML input: a *missing* key resolves to ``False`` rather than being
    skipped. The view's ``_search_params`` helper intersects the validated data
    with the keys actually supplied, which is what stops a plain ``GET /`` from
    silently meaning "unread only".
    """

    status = serializers.ChoiceField(choices=NotificationStatus.choices, required=False, allow_blank=True)
    is_read = serializers.BooleanField(required=False)
    # Named for the field it filters, not shortened to ``type``. Eleven of the
    # twelve parameters here already match their payload field exactly, and the
    # twelfth being the odd one out is a guaranteed bug in somebody's filter
    # serialization — caught by the §19.5 consumer review, which read the
    # contract cold and flagged it as the one inconsistency in the set.
    notification_type = serializers.ChoiceField(choices=NotificationType.choices, required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False, allow_blank=True)

    source_app = serializers.CharField(required=False, allow_blank=True, max_length=50)
    source_entity_id = serializers.UUIDField(required=False, allow_null=True)

    due_bucket = serializers.ChoiceField(choices=DueBucket.choices, required=False, allow_blank=True)
    due_within_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_DUE_WITHIN_DAYS,
        default=DEFAULT_DUE_WITHIN_DAYS,
    )

    # §39.4 — the same three date controls every list endpoint in this project
    # accepts, resolved by ``core.querying`` so the fiscal-year and explicit-date
    # precedence rule is written down exactly once.
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)
    fiscal_year = serializers.CharField(required=False, allow_blank=True)

    def validate_fiscal_year(self, value: str) -> str:
        """Reject a malformed fiscal year here rather than deep in a selector.

        ``fiscal_year_gregorian_range`` raises on a bad label, and an unvalidated
        one reached the selector and surfaced as a **500** — an unhandled server
        error for what is plainly bad client input. Caught by the §19.5 consumer
        review, which asked what format the parameter takes and found the
        contract silent. ``dashboards`` guards the same parameter the same way,
        for the same reason.
        """
        value = (value or "").strip()
        if not value:
            return ""

        from core.nepal.calendar import fiscal_year_gregorian_range

        try:
            fiscal_year_gregorian_range(value)
        except Exception as exc:  # noqa: BLE001 — any parse failure is the same answer to a client
            raise serializers.ValidationError("Expected a Nepali fiscal year label such as '2082/83'.") from exc
        return value


class NotificationSerializer(serializers.ModelSerializer):
    """One notification as a client sees it.

    Two stored columns are deliberately absent:

    * ``dedupe_key`` — an internal idempotency detail. Exposing it would invite a
      client to construct one and ask why nothing happened.
    * ``dismissed_by`` — it always equals ``recipient`` today, and publishing it
      would invite a "dismissed by X" display that is not true of anyone yet.

    ``recipient`` is absent for a different reason: every row this endpoint can
    return belongs to the caller, so the field would be a constant.
    """

    is_read = serializers.BooleanField(read_only=True)
    due_at_bs = serializers.SerializerMethodField()
    due_bucket = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "priority",
            "title",
            "body",
            "source_app",
            "source_entity_type",
            "source_entity_id",
            "source_api_path",
            "due_at",
            "due_at_bs",
            "due_bucket",
            "is_read",
            "read_at",
            "status",
            "resolution",
            "resolved_at",
            "delivery_channel",
            "delivery_state",
            "generated_by",
            "created_at",
        ]
        read_only_fields = fields

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Resolve "now" once per serializer, not once per row.

        A page of rows straddling a bucket boundary would otherwise place two
        identically-due notifications in different buckets, purely because the
        clock moved between them. The context may supply ``now`` so a test can
        pin it.
        """
        super().__init__(*args, **kwargs)
        self._now: datetime = (self.context or {}).get("now") or timezone.now()
        self._due_within_days: int = (self.context or {}).get("due_within_days") or DEFAULT_DUE_WITHIN_DAYS

    def get_due_at_bs(self, obj: Notification) -> dict[str, Any] | None:
        return _bs(obj.due_at)

    def get_due_bucket(self, obj: Notification) -> str:
        return obj.due_bucket(now=self._now, due_within_days=self._due_within_days)


class FeedSummarySerializer(serializers.Serializer):
    """The bell badge and the feed's grouping headers.

    A plain ``Serializer`` over the dict ``selectors.get_feed_summary`` returns,
    rather than a hand-built response dict in the view: the shape is a documented
    payload contract (`DATA_CONTRACT.md` — FeedSummary), and a view assembling it
    inline would let the contract and the code drift without either one being
    obviously wrong.
    """

    unread = serializers.IntegerField()
    active = serializers.IntegerField()
    by_priority = serializers.DictField(child=serializers.IntegerField())
    by_due_bucket = serializers.DictField(child=serializers.IntegerField())


class BulkReadResultSerializer(serializers.Serializer):
    """What ``POST /read-all/`` changed.

    Returns the count rather than the rows. The action exists for a feed that has
    got away from its reader, which is exactly when returning every affected row
    would be the largest response the app produces and the least useful.
    """

    marked_read = serializers.IntegerField()
