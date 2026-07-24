"""Request validation and response shaping for the applicant_journeys app."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from audit.models import AuditEvent
from core.constants import StudyLevel
from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from applicant_journeys.constants import ACTIVE_STAGES, JourneyOutcome, JourneyStage
from applicant_journeys.models import ApplicantJourney

#: Stages a client may choose from a dropdown. The terminal and deferred stages
#: are excluded — each has its own deliberate action.
SELECTABLE_STAGE_CHOICES = [(value, JourneyStage(value).label) for value in ACTIVE_STAGES]


def _bs(value: datetime | None) -> dict[str, Any] | None:
    """Render a stored UTC datetime as its Bikram Sambat date (§39.4)."""
    return to_bs(value).to_dict() if value else None


class UserBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


class ApplicantBriefSerializer(serializers.Serializer):
    """Just enough of the applicant to label the journey in a list.

    The journey never duplicates the person's identity — it references it.
    """

    id = serializers.UUIDField(read_only=True)
    full_name_np = serializers.CharField(read_only=True)
    full_name_en = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class CountryBriefSerializer(serializers.Serializer):
    """Just enough of the catalogue country to label the destination.

    Declared here rather than imported from ``institutions``: §4 permits
    importing another app's selectors and services, not its serializers, and a
    response shape silently inherited across a boundary is exactly the coupling
    that makes a later divergence invisible.
    """

    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)
    name_np = serializers.CharField(read_only=True)


class JourneyListSerializer(serializers.ModelSerializer):
    """The journey as it appears in a list."""

    applicant = ApplicantBriefSerializer(read_only=True)
    created_by = UserBriefSerializer(read_only=True)
    target_country_ref = CountryBriefSerializer(read_only=True)

    class Meta:
        model = ApplicantJourney
        fields = [
            "id",
            "applicant",
            "target_country",
            "target_country_ref",
            "target_institution_name",
            "target_program_name",
            "study_level",
            "field_of_study",
            "preferred_intake",
            "budget_amount",
            "budget_currency",
            "scholarship_interest",
            "stage",
            "creation_source",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class JourneyDetailSerializer(JourneyListSerializer):
    """The journey as it appears on its own page: adds notes and lifecycle state."""

    closed_by = UserBriefSerializer(read_only=True)
    deferred_by = UserBriefSerializer(read_only=True)
    closed_at_bs = serializers.SerializerMethodField()
    deferred_at_bs = serializers.SerializerMethodField()

    class Meta(JourneyListSerializer.Meta):
        fields = [
            *JourneyListSerializer.Meta.fields,
            "notes",
            "outcome",
            "closure_reason",
            "closed_at",
            "closed_at_bs",
            "closed_by",
            "deferred_at",
            "deferred_at_bs",
            "deferred_to_intake",
            "deferment_reason",
            "deferred_by",
            "stage_before_terminal",
        ]
        read_only_fields = fields

    def get_closed_at_bs(self, obj: ApplicantJourney) -> dict[str, Any] | None:
        return _bs(obj.closed_at)

    def get_deferred_at_bs(self, obj: ApplicantJourney) -> dict[str, Any] | None:
        return _bs(obj.deferred_at)


class JourneyCreateSerializer(serializers.Serializer):
    """Create input. ``stage`` is not accepted — a new journey starts at planning."""

    applicant = serializers.UUIDField()
    target_country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Written as a bare id and read back as an object, the same asymmetry
    # ``applicant`` already has. ``allow_null`` because clearing the destination
    # is a legitimate correction; the view resolves the id to a catalogue row.
    target_country_ref = serializers.UUIDField(required=False, allow_null=True)
    target_institution_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    target_program_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
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
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_target_country(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_field_of_study(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_target_institution_name(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_notes(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_budget_currency(self, value: str) -> str:
        return value.strip().upper()


class JourneyUpdateSerializer(JourneyCreateSerializer):
    """Update input — every field optional; the applicant is immutable."""

    applicant = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # A journey always belongs to exactly one applicant and is never
        # transferred (``concepts/applicant_journeys.txt``).
        self.fields.pop("applicant", None)


class StageChangeSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=SELECTABLE_STAGE_CHOICES)


class DeferSerializer(serializers.Serializer):
    to_intake = serializers.CharField(max_length=50)
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_reason(self, value: str) -> str:
        return normalize_unicode(value)


class CloseSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=JourneyOutcome.choices)
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_reason(self, value: str) -> str:
        return normalize_unicode(value)


class ReopenSerializer(serializers.Serializer):
    """Reopen to an active stage; defaults to ``planning`` when omitted."""

    stage = serializers.ChoiceField(choices=SELECTABLE_STAGE_CHOICES, required=False)


class JourneyHistorySerializer(serializers.ModelSerializer):
    """One entry of a journey's history, projected from the audit log."""

    created_at_bs = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "action",
            "actor_type",
            "actor_id",
            "actor_label",
            "summary",
            "reason",
            "changes",
            "metadata",
            "created_at",
            "created_at_bs",
        ]
        read_only_fields = fields

    def get_created_at_bs(self, obj: AuditEvent) -> dict[str, Any] | None:
        return _bs(obj.created_at)
