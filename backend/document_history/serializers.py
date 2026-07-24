"""Request and response serializers for the document_history app.

Serializers own validation, sanitization, and input/output shaping. Business
rules that span more than one field, or that need to read another record, live
in ``services.py``.

**``render_context`` is passed through untouched.** It is declared as a bare
``JSONField`` with no nested serializer, no field list, and no coercion, for the
same reason ``documents`` declares ``content`` that way: it holds whatever the
frontend needed to reproduce one of 42 templates, and a serializer that named
fields would silently drop the keys a template it has never heard of depends on.

**There is no write serializer for a snapshot body.** ``content`` is read off
the document by the service and can never be supplied by a client — see
``services.create_snapshot``. A client that posts ``content`` here has it
ignored, which is the intended behaviour and is documented in ``docs/API.md``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from document_history.constants import PrintEventType
from document_history.models import DocumentSnapshot, PrintEvent


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """The Bikram Sambat rendering of a datetime, or None when unset."""
    return to_bs(value).to_dict() if value else None


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write (§39.2).

    ``render_context`` is deliberately **not** normalizable through this mixin —
    it is opaque JSON, and walking it to normalize strings would be exactly the
    "backend touches the frozen payload" behaviour this app forbids.
    """

    text_fields: tuple[str, ...] = ()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)  # type: ignore[misc]
        for field in self.text_fields:
            if attrs.get(field):
                attrs[field] = normalize_unicode(attrs[field])
        return attrs


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class SnapshotListSerializer(serializers.ModelSerializer):
    """One row of a document's version chain.

    **Omits ``content`` and ``render_context`` entirely** — the two columns the
    list selector defers. A chain of twenty bank statements would otherwise
    carry twenty frozen transaction arrays to render a list of dates.
    """

    captured_by_username = serializers.CharField(source="captured_by.username", read_only=True)
    created_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = DocumentSnapshot
        fields = (
            "id",
            "document",
            "version_number",
            "family",
            "template_key",
            "label",
            "capture_note",
            "captured_by_username",
            "created_at",
            "created_at_bs",
        )
        read_only_fields = fields

    def get_created_at_bs(self, obj: DocumentSnapshot) -> dict[str, Any] | None:
        return _bs(obj.created_at)


class SnapshotDetailSerializer(SnapshotListSerializer):
    """One frozen snapshot in full — the Snapshot Detail screen.

    Extends the list shape rather than restating it, so the two cannot drift.
    This is the only endpoint that returns the frozen body.
    """

    class Meta(SnapshotListSerializer.Meta):
        fields = (
            *SnapshotListSerializer.Meta.fields,
            "content",
            "render_context",
        )
        read_only_fields = fields


class PrintEventSerializer(serializers.ModelSerializer):
    """One row of the Document History Timeline.

    Carries the snapshot's ``version_number`` and ``label`` inline: a timeline
    row that showed only an opaque snapshot id would force the client into one
    extra request per row to render anything a human could read.
    """

    version_number = serializers.IntegerField(source="snapshot.version_number", read_only=True)
    label = serializers.CharField(source="snapshot.label", read_only=True)
    performed_by_username = serializers.CharField(source="performed_by.username", read_only=True)
    created_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = PrintEvent
        fields = (
            "id",
            "snapshot",
            "document",
            "version_number",
            "label",
            "event_type",
            "note",
            "performed_by_username",
            "created_at",
            "created_at_bs",
        )
        read_only_fields = fields

    def get_created_at_bs(self, obj: PrintEvent) -> dict[str, Any] | None:
        return _bs(obj.created_at)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class SnapshotCaptureSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The capture payload.

    Note what is **absent**: there is no ``content`` field, no ``label``, and no
    ``version_number``. All three are taken from the document or allocated by
    the service, because a client that could set them could produce a snapshot
    that disagrees with the record it claims to freeze.
    """

    text_fields = ("capture_note",)

    render_context = serializers.JSONField(required=False)
    capture_note = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class PrintEventNoteSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The reprint and recover payloads — an optional note, and nothing else.

    Shared by both actions because both take exactly one optional field. What
    distinguishes them is the ``event_type`` the service writes, which is the
    service's decision rather than the client's: a client that could name its
    own event type could file a recovery as a reprint.
    """

    text_fields = ("note",)

    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


class SnapshotSearchSerializer(serializers.Serializer):
    """The version chain's query string.

    Validated rather than read loosely: silently ignoring ``?fiscal_year=2081``
    would return the whole chain and read as a result set rather than a mistake.
    Same reasoning as ``documents``, ``institutions``, and ``offers``.
    """

    fiscal_year = serializers.RegexField(r"^\d{4}/\d{2}$", required=False)


class TimelineSearchSerializer(serializers.Serializer):
    """The Document History Timeline's query string."""

    event_type = serializers.ChoiceField(choices=PrintEventType.choices, required=False)
    fiscal_year = serializers.RegexField(r"^\d{4}/\d{2}$", required=False)
