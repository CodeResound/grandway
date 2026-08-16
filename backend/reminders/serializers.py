"""Request and response serializers for the reminders app.

Serializers own validation, sanitization, and output shaping. Business rules
that span more than one record live in ``services.py``.

Every user-entered text field is normalized with
``core.nepal.text.normalize_unicode`` on write (§39.2), and every user-facing
date carries its Bikram Sambat sibling on read (§39.4).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.nepal.calendar import nepal_today, to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from reminders.constants import OWNER_FIELDS, ReminderStatus
from reminders.models import Reminder


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """The Bikram Sambat rendering of a date, or None when there is no date."""
    return to_bs(value).to_dict() if value else None


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write.

    A mixin rather than near-identical ``validate_<field>`` methods — copying
    the same two lines per field is how one of them ends up missing it.
    """

    text_fields: tuple[str, ...] = ()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)  # type: ignore[misc]
        for field in self.text_fields:
            if attrs.get(field):
                attrs[field] = normalize_unicode(attrs[field])
        return attrs


class _OwnerMixin:
    """Requires exactly one owner reference on create.

    Checked here for a usable field-level error and again by the
    ``reminder_single_owner`` database constraint — a serializer must not be
    the only thing standing between the table and an orphan reminder no record
    panel would ever show.
    """

    def _validate_single_owner(self, attrs: dict[str, Any]) -> dict[str, Any]:
        supplied = [field for field in OWNER_FIELDS if attrs.get(field) is not None]
        if len(supplied) != 1:
            raise serializers.ValidationError(
                {"owner": [f"Supply exactly one of: {', '.join(OWNER_FIELDS)}. Received {len(supplied)}."]}
            )
        return attrs


def _validate_due_date_floor(value: date) -> date:
    """The due date may be today or later — Nepal's today, not UTC's (§39.5).

    A today-dated reminder is legitimate ("chase this before end of day") and
    fires on the next nightly sweep; only past dates are rejected.
    """
    if value < nepal_today():
        raise serializers.ValidationError("The due date may not be in the past.")
    return value


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class ReminderSerializer(serializers.ModelSerializer):
    """One reminder as shown on a record's reminders panel or its detail view."""

    owner_type = serializers.CharField(read_only=True)
    due_date_bs = serializers.SerializerMethodField()
    closed_at_bs = serializers.SerializerMethodField()
    created_at_bs = serializers.SerializerMethodField()
    closed_by_username = serializers.CharField(source="closed_by.username", read_only=True, default=None)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Reminder
        fields = (
            "id",
            "owner_type",
            "applicant",
            "client",
            "due_date",
            "due_date_bs",
            "note",
            "status",
            "is_active",
            "closed_at",
            "closed_at_bs",
            "closed_by_username",
            "created_by_username",
            "created_at",
            "created_at_bs",
            "updated_at",
        )
        read_only_fields = fields

    def get_due_date_bs(self, obj: Reminder) -> dict[str, Any] | None:
        return _bs(obj.due_date)

    def get_closed_at_bs(self, obj: Reminder) -> dict[str, Any] | None:
        return _bs(obj.closed_at)

    def get_created_at_bs(self, obj: Reminder) -> dict[str, Any] | None:
        return _bs(obj.created_at)


# A reminder's history entries are serialized by ``audit.serializers``'s
# canonical ``AuditEventHistorySerializer`` — the shape is the audit app's to
# define (§4). The view imports it directly.


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class ReminderCreateSerializer(_NormalizedTextMixin, _OwnerMixin, serializers.Serializer):
    """``POST /reminders/`` — a new follow-up against one record.

    A plain ``Serializer`` rather than a ``ModelSerializer``: the lifecycle
    columns (status, closure stamps, creator) are set by the service and must
    not be accepted from a client.
    """

    text_fields = ("note",)

    applicant = serializers.UUIDField(required=False, allow_null=True)
    client = serializers.UUIDField(required=False, allow_null=True)
    due_date = serializers.DateField(validators=[_validate_due_date_floor])
    note = serializers.CharField(max_length=5000)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        return self._validate_single_owner(attrs)


class ReminderUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``PATCH /reminders/<id>/`` — reschedule and/or correct the note.

    The owner fields are absent by construction: a reminder about the wrong
    record is dismissed and recreated, never re-pointed.
    """

    text_fields = ("note",)

    due_date = serializers.DateField(required=False, validators=[_validate_due_date_floor])
    note = serializers.CharField(max_length=5000, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if not attrs:
            raise serializers.ValidationError("Supply due_date, note, or both.")
        return attrs


class ReminderActionSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The complete/dismiss dialog's payload.

    The optional reason is recorded on the audit event only — history is where
    "why was this dropped" gets answered, not a mostly-empty column.
    """

    text_fields = ("reason",)

    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


class ReminderFilterSerializer(serializers.Serializer):
    """The reminder list's query string.

    Validated rather than read loosely: silently ignoring ``?status=open``
    would return every reminder and read as a result set rather than a
    mistake. Same reasoning as ``clients`` and ``offers``.
    """

    applicant = serializers.UUIDField(required=False)
    client = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=ReminderStatus.choices, required=False)
    due_before = serializers.DateField(required=False)
    due_after = serializers.DateField(required=False)
    fiscal_year = serializers.RegexField(r"^\d{4}/\d{2}$", required=False)
