"""Request and response serializers for the checklists app.

Serializers own validation, sanitization, and input/output shaping. Business
rules that span more than one field, or that need to read another record, live
in ``services.py``.

Two shaping decisions are deliberate:

* **Progress is returned as counts, not a percentage.** "9 of 12, 2 blocked" is
  something a member of staff can act on; "75%" is not, and a percentage would
  additionally have to decide what a waived item is worth. The counts come from
  the selector's annotations, so a list of twenty checklists stays one query.
* **The country is written as an id and read back as an object**, the same
  asymmetry ``applicant_journeys`` already has for its applicant.

Every user-entered text field is Unicode-normalized on write (§39.2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from checklists.constants import ChecklistOrigin, ChecklistStatus, ItemStatus, ItemType, TemplateStatus
from checklists.models import Checklist, ChecklistItem, ChecklistTemplate, ChecklistTemplateItem
from checklists.validators import validate_template_key


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """Bikram Sambat sibling for one timestamp (§39.4), or None."""
    return to_bs(value).to_dict() if value else None


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write (§39.2)."""

    text_fields: tuple[str, ...] = ()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)  # type: ignore[misc]
        for field in self.text_fields:
            if attrs.get(field):
                attrs[field] = normalize_unicode(attrs[field])
        return attrs


class CountryBriefSerializer(serializers.Serializer):
    """Just enough of the catalogue country to label a template or checklist.

    Declared here rather than imported from ``institutions``: §4 permits
    importing another app's selectors and services, not its serializers.
    """

    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)
    name_np = serializers.CharField(read_only=True)


class ApplicantBriefSerializer(serializers.Serializer):
    """Who the checklist is for. The reason a client never needs a second call."""

    id = serializers.UUIDField(read_only=True)
    full_name_np = serializers.CharField(read_only=True)
    full_name_en = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class UserBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# Templates — output
# ---------------------------------------------------------------------------


class TemplateItemSerializer(serializers.ModelSerializer):
    """One requirement definition, as it appears inside its template."""

    class Meta:
        model = ChecklistTemplateItem
        fields = [
            "id",
            "label",
            "description",
            "item_type",
            "is_required",
            "display_order",
            "default_due_offset_days",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TemplateSerializer(serializers.ModelSerializer):
    """One template, list and detail alike.

    The items come with it rather than behind a second call: a template is only
    ever read in order to see what it requires, and the selector prefetches
    them, so splitting the two would cost a round trip and save nothing.
    """

    country = CountryBriefSerializer(read_only=True)
    created_by = UserBriefSerializer(read_only=True)
    items = serializers.SerializerMethodField()
    is_inheritable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ChecklistTemplate
        fields = [
            "id",
            "key",
            "label",
            "description",
            "country",
            "is_default",
            "is_inheritable",
            "status",
            "status_note",
            "display_order",
            "notes",
            "items",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_items(self, obj: ChecklistTemplate) -> list[dict[str, Any]]:
        """Active definitions first, in the author's order.

        Retired definitions are included too — an Admin editing a template needs
        to see what was retired, and ``is_active`` tells them apart. Sorted in
        Python rather than by a second query, because ``items`` is prefetched.
        """
        items = sorted(obj.items.all(), key=lambda item: (not item.is_active, item.display_order, item.label))
        return TemplateItemSerializer(items, many=True).data


# ---------------------------------------------------------------------------
# Templates — input
# ---------------------------------------------------------------------------


class TemplateCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Create input for a template."""

    text_fields = ("label", "description", "status_note", "notes")

    key = serializers.CharField(max_length=50, validators=[validate_template_key])
    label = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    country = serializers.UUIDField(required=False, allow_null=True)
    is_default = serializers.BooleanField(required=False, default=False)
    status = serializers.ChoiceField(choices=TemplateStatus.choices, required=False)
    status_note = serializers.CharField(required=False, allow_blank=True)
    display_order = serializers.IntegerField(required=False, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_key(self, value: str) -> str:
        key = value.strip().lower()
        if ChecklistTemplate.objects.filter(key=key).exists():
            raise serializers.ValidationError("A template with this key already exists.")
        return key


class TemplateUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Update input — every field optional. ``key`` is immutable.

    The key is what seed data, logs, and any external reference point at; letting
    it move would silently break all three while returning 200.
    """

    text_fields = ("label", "description", "status_note", "notes")

    label = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    country = serializers.UUIDField(required=False, allow_null=True)
    is_default = serializers.BooleanField(required=False)
    status = serializers.ChoiceField(choices=TemplateStatus.choices, required=False)
    status_note = serializers.CharField(required=False, allow_blank=True)
    display_order = serializers.IntegerField(required=False, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)


class TemplateItemCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Create input for one requirement definition."""

    text_fields = ("label", "description")

    label = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    item_type = serializers.ChoiceField(choices=ItemType.choices, required=False)
    is_required = serializers.BooleanField(required=False)
    display_order = serializers.IntegerField(required=False, min_value=0)
    default_due_offset_days = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class TemplateItemUpdateSerializer(TemplateItemCreateSerializer):
    """Update input — every field optional, plus retirement via ``is_active``."""

    label = serializers.CharField(max_length=255, required=False)
    is_active = serializers.BooleanField(required=False)


# ---------------------------------------------------------------------------
# Checklists — output
# ---------------------------------------------------------------------------


class ChecklistItemSerializer(serializers.ModelSerializer):
    """One requirement on one applicant."""

    assigned_to = UserBriefSerializer(read_only=True)
    completed_by = UserBriefSerializer(read_only=True)
    is_resolved = serializers.BooleanField(read_only=True)
    due_at_bs = serializers.SerializerMethodField()
    completed_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistItem
        fields = [
            "id",
            "checklist",
            "source_template_item",
            "label",
            "description",
            "item_type",
            "is_required",
            "display_order",
            "status",
            "status_note",
            "is_resolved",
            "assigned_to",
            "due_at",
            "due_at_bs",
            "evidence_file",
            "evidence_note",
            "completed_at",
            "completed_at_bs",
            "completed_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_due_at_bs(self, obj: ChecklistItem) -> dict[str, Any] | None:
        return _bs(obj.due_at)

    def get_completed_at_bs(self, obj: ChecklistItem) -> dict[str, Any] | None:
        return _bs(obj.completed_at)


class ChecklistProgressSerializer(serializers.Serializer):
    """The counts every screen shows, straight from the selector's annotations.

    Never computed from ``obj.items`` — that would fire one query per row and
    turn a twenty-row page into forty-one queries (§6).
    """

    total = serializers.IntegerField(source="item_total", read_only=True, default=0)
    resolved = serializers.IntegerField(source="item_resolved", read_only=True, default=0)
    required_total = serializers.IntegerField(read_only=True, default=0)
    required_resolved = serializers.IntegerField(read_only=True, default=0)
    blocked = serializers.IntegerField(source="item_blocked", read_only=True, default=0)
    document_total = serializers.IntegerField(read_only=True, default=0)
    document_resolved = serializers.IntegerField(read_only=True, default=0)


class ChecklistListSerializer(serializers.ModelSerializer):
    """The checklist as it appears in a list — progress, but not the items."""

    applicant = ApplicantBriefSerializer(source="journey.applicant", read_only=True)
    country = CountryBriefSerializer(read_only=True)
    assigned_to = UserBriefSerializer(read_only=True)
    progress = serializers.SerializerMethodField()
    due_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = Checklist
        fields = [
            "id",
            "journey",
            "applicant",
            "source_template",
            "country",
            "title",
            "description",
            "origin",
            "status",
            "assigned_to",
            "due_at",
            "due_at_bs",
            "progress",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_progress(self, obj: Checklist) -> dict[str, Any]:
        return ChecklistProgressSerializer(obj).data

    def get_due_at_bs(self, obj: Checklist) -> dict[str, Any] | None:
        return _bs(obj.due_at)


class ChecklistDetailSerializer(ChecklistListSerializer):
    """The checklist on its own page: adds the items and the lifecycle stamps."""

    items = serializers.SerializerMethodField()
    completed_by = UserBriefSerializer(read_only=True)
    archived_by = UserBriefSerializer(read_only=True)
    completed_at_bs = serializers.SerializerMethodField()

    class Meta(ChecklistListSerializer.Meta):
        fields = [
            *ChecklistListSerializer.Meta.fields,
            "notes",
            "items",
            "activated_at",
            "completed_at",
            "completed_at_bs",
            "completed_by",
            "archive_reason",
            "archived_at",
            "archived_by",
            "status_before_archive",
        ]
        read_only_fields = fields

    def get_items(self, obj: Checklist) -> list[dict[str, Any]]:
        items = sorted(obj.items.all(), key=lambda item: (item.display_order, item.created_at))
        return ChecklistItemSerializer(items, many=True).data

    def get_completed_at_bs(self, obj: Checklist) -> dict[str, Any] | None:
        return _bs(obj.completed_at)


class JourneyMissingChecklistSerializer(serializers.Serializer):
    """One journey that names a country but holds no checklist.

    The safety net's response shape. Not a checklist serializer — there is no
    checklist; that is the whole point of the row.
    """

    id = serializers.UUIDField(read_only=True)
    applicant = ApplicantBriefSerializer(read_only=True)
    target_country_ref = CountryBriefSerializer(read_only=True)
    stage = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


# ---------------------------------------------------------------------------
# Checklists — input
# ---------------------------------------------------------------------------


class ChecklistCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Create input.

    Two shapes in one endpoint, and the difference is ``template``:

    * with a template — apply that country's list to this applicant by hand;
      everything else in the body is ignored, because the template supplies it
    * without one — start an empty checklist staff will fill in, which needs a
      ``title`` of its own
    """

    text_fields = ("title", "description", "notes")

    journey = serializers.UUIDField()
    template = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    assigned_to = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if not attrs.get("template") and not attrs.get("title"):
            raise serializers.ValidationError(
                {"title": ["A title is required when no template is applied."]},
            )
        return attrs


class ChecklistUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Update input — every field optional. Status is not among them.

    Status moves only through the lifecycle actions, so a client cannot mark a
    checklist complete with a ``PATCH`` and bypass the required-items check that
    gives the word its meaning.
    """

    text_fields = ("title", "description", "notes")

    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    assigned_to = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ChecklistItemCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Create input for an item added to one applicant's checklist only."""

    text_fields = ("label", "description")

    label = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    item_type = serializers.ChoiceField(choices=ItemType.choices, required=False)
    is_required = serializers.BooleanField(required=False)
    display_order = serializers.IntegerField(required=False, min_value=0)
    assigned_to = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class ChecklistItemUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Update input for an item's descriptive fields. Status is not among them."""

    text_fields = ("label", "description", "evidence_note")

    label = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    item_type = serializers.ChoiceField(choices=ItemType.choices, required=False)
    is_required = serializers.BooleanField(required=False)
    display_order = serializers.IntegerField(required=False, min_value=0)
    assigned_to = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    evidence_note = serializers.CharField(required=False, allow_blank=True)


class ItemStatusSerializer(_NormalizedTextMixin, serializers.Serializer):
    """Status-change input, with its note and evidence.

    ``clear_evidence`` is explicit rather than inferred from a null
    ``evidence_file``: on a partial update the two are indistinguishable, and
    silently detaching the proof behind a completed item is not something a
    client should be able to do by omission.
    """

    text_fields = ("status_note", "evidence_note")

    status = serializers.ChoiceField(choices=ItemStatus.choices)
    status_note = serializers.CharField(required=False, allow_blank=True, default="")
    evidence_file = serializers.UUIDField(required=False, allow_null=True)
    evidence_note = serializers.CharField(required=False, allow_blank=True, default="")
    clear_evidence = serializers.BooleanField(required=False, default=False)


class ArchiveSerializer(_NormalizedTextMixin, serializers.Serializer):
    text_fields = ("reason",)

    reason = serializers.CharField()


class ReopenSerializer(_NormalizedTextMixin, serializers.Serializer):
    text_fields = ("reason",)

    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ChecklistSearchSerializer(serializers.Serializer):
    """Query-parameter validation for the checklist list.

    Validated rather than passed through, so a mistyped status returns a 400
    naming the field instead of an empty page that reads as "this applicant has
    no checklists".
    """

    applicant = serializers.UUIDField(required=False)
    journey = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=ChecklistStatus.choices, required=False)
    origin = serializers.ChoiceField(choices=ChecklistOrigin.choices, required=False)
    assigned_to = serializers.UUIDField(required=False)
    country = serializers.UUIDField(required=False)
    template = serializers.UUIDField(required=False)
    overdue = serializers.BooleanField(required=False)


class TemplateSearchSerializer(serializers.Serializer):
    """Query-parameter validation for the template list."""

    country = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=TemplateStatus.choices, required=False)
    is_default = serializers.BooleanField(required=False)
    search = serializers.CharField(required=False, allow_blank=True)
