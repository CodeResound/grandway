"""Request and response serializers for the offers app.

Serializers own validation, sanitization, and output shaping. Business rules
that span more than one field, or that need to read another record, live in
``services.py``.

Two conventions are inherited from the rest of the project:

* Every user-entered text field is normalized with
  ``core.nepal.text.normalize_unicode`` on write (§39.2). Devanagari has NFC/NFD
  variants that look identical but differ byte-wise, and un-normalized text
  breaks search and equality.
* Every user-facing date carries a ``_bs`` sibling in read output (§39.4).
  System timestamps (``created_at``, ``updated_at``) do not — the rule applies
  to dates staff act on, and ``decided_at`` is one of them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.constants import FeePeriod, StudyLevel
from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from core.validators import validate_fiscal_year_label
from rest_framework import serializers

from offers.constants import (
    ConditionStatus,
    ConditionType,
    DecisionOutcome,
    OfferStatus,
    OfferType,
)
from offers.models import Offer, OfferCondition

#: Snapshot fields a client may supply directly. Accepted on create only — a
#: manually recorded historical offer has no catalogue record to copy from.
SNAPSHOT_INPUT_FIELDS = (
    "institution_name",
    "campus_name",
    "program_title",
    "country_name",
    "qualification_level",
    "intake_label",
)


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """The Bikram Sambat rendering of a date, or None when there is no date."""
    return to_bs(value).to_dict() if value else None


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write.

    Declared as a mixin rather than repeated ``validate_<field>`` methods
    because this app has fourteen text fields across four serializers and
    copying the same two lines fourteen times is how one of them ends up
    missing it.
    """

    text_fields: tuple[str, ...] = ()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)  # type: ignore[misc]
        for field in self.text_fields:
            if attrs.get(field):
                attrs[field] = normalize_unicode(attrs[field])
        return attrs


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


class ConditionSerializer(serializers.ModelSerializer):
    """One condition as returned to a client."""

    due_date_bs = serializers.SerializerMethodField()
    resolved_at_bs = serializers.SerializerMethodField()
    resolved_by_username = serializers.CharField(source="resolved_by.username", read_only=True, default=None)
    is_resolved = serializers.BooleanField(read_only=True)

    class Meta:
        model = OfferCondition
        fields = (
            "id",
            "condition_type",
            "description",
            "status",
            "is_resolved",
            "due_date",
            "due_date_bs",
            "display_order",
            "resolution_note",
            "resolved_at",
            "resolved_at_bs",
            "resolved_by_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_due_date_bs(self, obj: OfferCondition) -> dict[str, Any] | None:
        return _bs(obj.due_date)

    def get_resolved_at_bs(self, obj: OfferCondition) -> dict[str, Any] | None:
        return _bs(obj.resolved_at)


class ConditionCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A condition being attached to an offer."""

    text_fields = ("description",)

    condition_type = serializers.ChoiceField(choices=ConditionType.choices)
    description = serializers.CharField(max_length=2000)
    due_date = serializers.DateField(required=False, allow_null=True)
    display_order = serializers.IntegerField(required=False, min_value=0)


class ConditionUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A correction to a condition's wording, type, due date, or ordering.

    Status is absent deliberately — it moves through the status action, which
    stamps who resolved it and when.
    """

    text_fields = ("description",)

    condition_type = serializers.ChoiceField(choices=ConditionType.choices, required=False)
    description = serializers.CharField(max_length=2000, required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    display_order = serializers.IntegerField(required=False, min_value=0)


class ConditionStatusSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A condition being resolved, waived, retired, or reopened."""

    text_fields = ("note",)

    status = serializers.ChoiceField(choices=ConditionStatus.choices)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Offers — output
# ---------------------------------------------------------------------------


class OfferListSerializer(serializers.ModelSerializer):
    """One row of the Offer List.

    Carries the applicant's name because the list's first column is the person,
    not the offer — an offer nobody can attribute is useless in a worklist.
    """

    applicant_id = serializers.UUIDField(source="journey.applicant_id", read_only=True)
    applicant_name = serializers.SerializerMethodField()
    journey_stage = serializers.CharField(source="journey.stage", read_only=True)
    issue_date_bs = serializers.SerializerMethodField()
    response_deadline_bs = serializers.SerializerMethodField()
    is_response_overdue = serializers.BooleanField(read_only=True)
    has_open_conditions = serializers.BooleanField(read_only=True)

    class Meta:
        model = Offer
        fields = (
            "id",
            "journey",
            "journey_stage",
            "applicant_id",
            "applicant_name",
            "institution_name",
            "campus_name",
            "program_title",
            "qualification_level",
            "intake_label",
            "offer_type",
            "status",
            "issue_date",
            "issue_date_bs",
            "response_deadline",
            "response_deadline_bs",
            "is_response_overdue",
            "has_open_conditions",
            "created_at",
        )
        read_only_fields = fields

    def get_applicant_name(self, obj: Offer) -> str:
        return str(obj.journey.applicant)

    def get_issue_date_bs(self, obj: Offer) -> dict[str, Any] | None:
        return _bs(obj.issue_date)

    def get_response_deadline_bs(self, obj: Offer) -> dict[str, Any] | None:
        return _bs(obj.response_deadline)


class OfferDetailSerializer(OfferListSerializer):
    """The full offer record, including its conditions and decision.

    Extends the list shape rather than restating it: every list field is a
    detail field too, and keeping them in one place is what stops the two
    drifting apart.
    """

    conditions = ConditionSerializer(many=True, read_only=True)
    deposit_due_date_bs = serializers.SerializerMethodField()
    decided_at_bs = serializers.SerializerMethodField()
    decided_by_username = serializers.CharField(source="decided_by.username", read_only=True, default=None)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta(OfferListSerializer.Meta):
        fields = (
            *OfferListSerializer.Meta.fields,
            "institution",
            "campus",
            "program",
            "reference_source",
            "country_name",
            "offer_reference",
            "tuition_amount",
            "tuition_currency",
            "tuition_fee_period",
            "scholarship_amount",
            "scholarship_currency",
            "scholarship_notes",
            "deposit_amount",
            "deposit_currency",
            "deposit_due_date",
            "deposit_due_date_bs",
            "deposit_notes",
            "notes",
            "is_terminal",
            "decided_at",
            "decided_at_bs",
            "decision_reason",
            "decided_by_username",
            "deferred_to_intake",
            "created_by_username",
            "conditions",
            "updated_at",
        )
        read_only_fields = fields

    def get_deposit_due_date_bs(self, obj: Offer) -> dict[str, Any] | None:
        return _bs(obj.deposit_due_date)

    def get_decided_at_bs(self, obj: Offer) -> dict[str, Any] | None:
        return _bs(obj.decided_at)


# An offer's history entries are serialized by ``audit.serializers``'s canonical
# ``AuditEventHistorySerializer`` — the shape is the audit app's to define, and
# six per-app copies of it had already drifted apart (§4). The view imports it
# directly. That shared shape includes ``actor_id``, which this app's copy
# omitted; the field is additive and breaks no consumer (§22).


# ---------------------------------------------------------------------------
# Offers — input
# ---------------------------------------------------------------------------


class _OfferWritableSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The decision fields a client may set on create and correct on update.

    A ``Serializer`` subclass rather than a plain mixin: DRF's metaclass only
    inherits declared fields from bases that carry ``_declared_fields``, so
    fields on a plain mixin would be silently dropped.
    """

    text_fields = ("offer_reference", "scholarship_notes", "deposit_notes", "notes")

    offer_type = serializers.ChoiceField(choices=OfferType.choices, required=False)
    offer_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    issue_date = serializers.DateField(required=False, allow_null=True)
    response_deadline = serializers.DateField(required=False, allow_null=True)

    tuition_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    tuition_currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    tuition_fee_period = serializers.ChoiceField(
        choices=FeePeriod.choices, required=False, allow_blank=True, default=""
    )

    scholarship_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    scholarship_currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    scholarship_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    deposit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    deposit_currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    deposit_due_date = serializers.DateField(required=False, allow_null=True)
    deposit_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)

    def validate_tuition_currency(self, value: str) -> str:
        return value.upper()

    def validate_scholarship_currency(self, value: str) -> str:
        return value.upper()

    def validate_deposit_currency(self, value: str) -> str:
        return value.upper()


class OfferCreateSerializer(_OfferWritableSerializer, serializers.Serializer):
    """A new offer being recorded against a journey.

    The reference block may arrive two ways, and both are legitimate: a
    ``program`` id resolved from the catalogue, or the snapshot text typed in
    for a historical offer whose catalogue record never existed. Which one was
    used is recorded on the offer as ``reference_source``.
    """

    text_fields = (*_OfferWritableSerializer.text_fields, *SNAPSHOT_INPUT_FIELDS)

    journey = serializers.UUIDField()

    institution = serializers.UUIDField(required=False, allow_null=True)
    campus = serializers.UUIDField(required=False, allow_null=True)
    program = serializers.UUIDField(required=False, allow_null=True)

    institution_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    campus_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    program_title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    country_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    qualification_level = serializers.ChoiceField(
        choices=StudyLevel.choices, required=False, allow_blank=True, default=""
    )
    intake_label = serializers.CharField(max_length=100, required=False, allow_blank=True)

    conditions = ConditionCreateSerializer(many=True, required=False)


class OfferUpdateSerializer(_OfferWritableSerializer, serializers.Serializer):
    """A correction to an offer's decision details.

    The reference block is absent by construction, not by filtering: an offer
    preserves what was true when the institution decided, so there is no field
    here through which that could be rewritten. Status is absent for the same
    reason — it moves through the issue and decision actions.
    """


class DecisionSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The Decision Dialog's payload."""

    text_fields = ("reason", "to_intake")

    outcome = serializers.ChoiceField(choices=DecisionOutcome.choices)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    to_intake = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


class OfferSearchSerializer(serializers.Serializer):
    """The Offer List's query string.

    Validated rather than read loosely: silently ignoring
    ``?deadline_before=soon`` would return every offer and read as a result set
    rather than a mistake. Same reasoning as ``institutions``.
    """

    journey = serializers.UUIDField(required=False)
    applicant = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=OfferStatus.choices, required=False)
    offer_type = serializers.ChoiceField(choices=OfferType.choices, required=False)
    institution = serializers.UUIDField(required=False)
    program = serializers.UUIDField(required=False)
    intake = serializers.CharField(max_length=100, required=False)
    deadline_before = serializers.DateField(required=False)
    # Not a bare RegexField: a format-valid label like 9999/99 still raises in
    # the selector, so the shared validator round-trips the actual conversion.
    fiscal_year = serializers.CharField(required=False, validators=[validate_fiscal_year_label])
