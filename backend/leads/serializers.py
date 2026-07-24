"""Request validation and response shaping for the leads app.

Serializers own input validation and Unicode normalization (§39.2); they never
hand a raw request dict to a service. Write serializers validate only — the
actual writes happen in ``services``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from core.constants import ContactNumberLabel, LanguageTestStatus, StudyLevel
from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from leads.constants import ACTIVE_STAGES, LeadStage
from leads.models import (
    Lead,
    LeadContactNumber,
    LeadNote,
    LeadSource,
    LeadStudyInterest,
    LossReason,
)

#: Stages a client may choose from a dropdown. ``lost`` and ``converted`` are
#: excluded — each has its own deliberate action.
SELECTABLE_STAGE_CHOICES = [(value, LeadStage(value).label) for value in ACTIVE_STAGES]


def _bs(value: datetime | None) -> dict[str, Any] | None:
    """Render a stored UTC datetime as its Bikram Sambat date (§39.4)."""
    return to_bs(value).to_dict() if value else None


class UserBriefSerializer(serializers.Serializer):
    """The minimum identity needed to attribute an action in the UI."""

    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# Reference configuration
# ---------------------------------------------------------------------------


class ReferenceEntrySerializer(serializers.ModelSerializer):
    """Read shape shared by lead sources and loss reasons."""

    class Meta:
        fields = [
            "id",
            "code",
            "name_np",
            "name_en",
            "name_romanized",
            "requires_detail",
            "is_active",
            "display_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class LeadSourceSerializer(ReferenceEntrySerializer):
    class Meta(ReferenceEntrySerializer.Meta):
        model = LeadSource


class LossReasonSerializer(ReferenceEntrySerializer):
    class Meta(ReferenceEntrySerializer.Meta):
        model = LossReason


class ReferenceEntryWriteSerializer(serializers.Serializer):
    """Create/update input for either reference table.

    ``name_romanized`` is deliberately absent: the service derives it (§39.3).
    """

    code = serializers.CharField(max_length=50)
    name_np = serializers.CharField(max_length=150)
    name_en = serializers.CharField(max_length=150, required=False, allow_blank=True)
    requires_detail = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    display_order = serializers.IntegerField(required=False, min_value=0)

    def validate_code(self, value: str) -> str:
        return value.strip().lower()

    def validate_name_np(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_name_en(self, value: str) -> str:
        return normalize_unicode(value)


class ReferenceEntryUpdateSerializer(ReferenceEntryWriteSerializer):
    """Update input — every field optional, and ``code`` is immutable."""

    code = None
    name_np = serializers.CharField(max_length=150, required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields.pop("code", None)


# ---------------------------------------------------------------------------
# Lead sub-resources
# ---------------------------------------------------------------------------


class LeadContactNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadContactNumber
        fields = ["id", "number", "label", "is_primary"]
        read_only_fields = ["id"]


class LeadContactNumberWriteSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=32)
    label = serializers.ChoiceField(choices=ContactNumberLabel.choices, required=False)
    is_primary = serializers.BooleanField(required=False, default=False)

    def validate_number(self, value: str) -> str:
        return value.strip()


class LeadStudyInterestSerializer(serializers.ModelSerializer):
    """Preliminary interest — every field optional, nothing here is authoritative."""

    class Meta:
        model = LeadStudyInterest
        fields = [
            "interested_countries",
            "study_level",
            "field_of_study",
            "preferred_intake",
            "budget_amount",
            "budget_currency",
            "scholarship_interest",
            "highest_qualification",
            "language_test_status",
            "interest_notes",
        ]


class LeadStudyInterestWriteSerializer(serializers.Serializer):
    interested_countries = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
    )
    study_level = serializers.ChoiceField(choices=StudyLevel.choices, required=False, allow_blank=True)
    field_of_study = serializers.CharField(max_length=150, required=False, allow_blank=True)
    preferred_intake = serializers.CharField(max_length=50, required=False, allow_blank=True)
    budget_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )
    budget_currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    scholarship_interest = serializers.BooleanField(required=False)
    highest_qualification = serializers.CharField(max_length=150, required=False, allow_blank=True)
    language_test_status = serializers.ChoiceField(
        choices=LanguageTestStatus.choices, required=False, allow_blank=True
    )
    interest_notes = serializers.CharField(required=False, allow_blank=True)

    def validate_field_of_study(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_highest_qualification(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_interest_notes(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_budget_currency(self, value: str) -> str:
        return value.strip().upper()


# ---------------------------------------------------------------------------
# Lead read shapes
# ---------------------------------------------------------------------------


class LeadListSerializer(serializers.ModelSerializer):
    """The lead as it appears in a list."""

    source = LeadSourceSerializer(read_only=True)
    created_by = UserBriefSerializer(read_only=True)
    contact_numbers = LeadContactNumberSerializer(many=True, read_only=True)
    last_followed_up_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id",
            "full_name_np",
            "full_name_en",
            "full_name_romanized",
            "email",
            "address",
            "source",
            "source_detail",
            "stage",
            "created_by",
            "contact_numbers",
            "last_followed_up_at",
            "last_followed_up_at_bs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_last_followed_up_at_bs(self, obj: Lead) -> dict[str, Any] | None:
        return _bs(obj.last_followed_up_at)


class LeadDetailSerializer(LeadListSerializer):
    """The lead as it appears on its own page: adds interest and lifecycle state."""

    study_interest = serializers.SerializerMethodField()
    last_followed_up_by = UserBriefSerializer(read_only=True)
    lost_reason = LossReasonSerializer(read_only=True)
    lost_by = UserBriefSerializer(read_only=True)
    converted_by = UserBriefSerializer(read_only=True)
    lost_at_bs = serializers.SerializerMethodField()
    converted_at_bs = serializers.SerializerMethodField()
    # Exposed as bare ids so a client can link through to the applicant and
    # journey without this app embedding either module's response shape.
    converted_applicant_id = serializers.UUIDField(read_only=True, allow_null=True)
    converted_journey_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta(LeadListSerializer.Meta):
        fields = [
            *LeadListSerializer.Meta.fields,
            "study_interest",
            "last_followed_up_by",
            "lost_reason",
            "lost_detail",
            "lost_at",
            "lost_at_bs",
            "lost_by",
            "stage_before_loss",
            "converted_at",
            "converted_at_bs",
            "converted_by",
            "converted_applicant_id",
            "converted_journey_id",
        ]
        read_only_fields = fields

    def get_study_interest(self, obj: Lead) -> dict[str, Any] | None:
        interest = getattr(obj, "study_interest", None)
        return LeadStudyInterestSerializer(interest).data if interest else None

    def get_lost_at_bs(self, obj: Lead) -> dict[str, Any] | None:
        return _bs(obj.lost_at)

    def get_converted_at_bs(self, obj: Lead) -> dict[str, Any] | None:
        return _bs(obj.converted_at)


# ---------------------------------------------------------------------------
# Lead write shapes
# ---------------------------------------------------------------------------


class LeadCreateSerializer(serializers.Serializer):
    """Create input. ``stage`` is not accepted — a new lead always starts at ``new``."""

    full_name_np = serializers.CharField(max_length=255)
    full_name_en = serializers.CharField(max_length=255, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    source = serializers.PrimaryKeyRelatedField(queryset=LeadSource.objects.all())
    source_detail = serializers.CharField(max_length=255, required=False, allow_blank=True)

    contact_numbers = LeadContactNumberWriteSerializer(many=True, allow_empty=False)
    study_interest = LeadStudyInterestWriteSerializer(required=False)

    def validate_full_name_np(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_full_name_en(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_address(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_source_detail(self, value: str) -> str:
        return normalize_unicode(value)


class LeadUpdateSerializer(LeadCreateSerializer):
    """Update input — every field optional; contact numbers replace wholesale."""

    full_name_np = serializers.CharField(max_length=255, required=False)
    source = serializers.PrimaryKeyRelatedField(queryset=LeadSource.objects.all(), required=False)
    contact_numbers = LeadContactNumberWriteSerializer(many=True, allow_empty=False, required=False)


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


class StageChangeSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=SELECTABLE_STAGE_CHOICES)


class FollowUpSerializer(serializers.Serializer):
    """Record a manual follow-up, optionally with a note and a stage change."""

    note = serializers.CharField(required=False, allow_blank=True, default="")
    stage = serializers.ChoiceField(choices=SELECTABLE_STAGE_CHOICES, required=False)
    followed_up_at = serializers.DateTimeField(required=False)

    def validate_note(self, value: str) -> str:
        return normalize_unicode(value)


class MarkLostSerializer(serializers.Serializer):
    loss_reason = serializers.PrimaryKeyRelatedField(queryset=LossReason.objects.all())
    detail = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_detail(self, value: str) -> str:
        return normalize_unicode(value)


class ReopenSerializer(serializers.Serializer):
    """Reopen to an active stage; defaults to ``follow_up`` when omitted."""

    stage = serializers.ChoiceField(choices=SELECTABLE_STAGE_CHOICES, required=False)


# ---------------------------------------------------------------------------
# Notes and history
# ---------------------------------------------------------------------------


class LeadNoteSerializer(serializers.ModelSerializer):
    author = UserBriefSerializer(read_only=True)

    class Meta:
        model = LeadNote
        fields = ["id", "body", "author", "created_at"]
        read_only_fields = fields


class LeadNoteCreateSerializer(serializers.Serializer):
    body = serializers.CharField()

    def validate_body(self, value: str) -> str:
        return normalize_unicode(value)


# A lead's history entries are serialized by ``audit.serializers``'s canonical
# ``AuditEventHistorySerializer`` — the shape is the audit app's to define, and
# six per-app copies of it had already drifted apart (§4). The view imports it
# directly.
