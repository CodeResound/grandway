"""Request validation and response shaping for the dashboards app.

Two things live here. The **filter serializer** is the more important of them:
every section takes the same filter set, and validating it in one place is what
keeps "narrow the same underlying data" (``concepts/dashboards.txt`` — "Useful
filters") true rather than aspirational. If each view parsed its own params, the
sections would drift apart and a user changing one control would silently get
inconsistent answers across the page.

The **row serializers** shape the worklist entries. Each one carries the ids a
client needs to reach the underlying record, because a dashboard number nobody
can navigate from is the thing this app exists not to build
(``concepts/dashboards.txt`` — "Drill-down behavior").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from applicant_journeys.constants import JourneyStage
from checklists.constants import ChecklistStatus
from core.nepal.calendar import to_bs
from core.validators import validate_fiscal_year_label
from documents.constants import DocumentStatus
from offers.constants import OfferStatus
from rest_framework import serializers

from dashboards.constants import (
    DEFAULT_DUE_WITHIN_DAYS,
    DEFAULT_PASSPORT_HORIZON_DAYS,
    MAX_DUE_WITHIN_DAYS,
)


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """Render a stored date/datetime as its Bikram Sambat date (§39.4)."""
    return to_bs(value).to_dict() if value else None


class DashboardFilterSerializer(serializers.Serializer):
    """The one filter set, shared by every section.

    Nothing here is required. A dashboard with no filters applied is the normal
    first load, and every field defaults to "do not narrow on this".

    `date_to` is **inclusive** — the user picking "up to the 24th" means the
    whole of the 24th. The conversion to a half-open SQL bound happens once, in
    `core.querying.resolve_window`, so no selector has to remember it.
    """

    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)
    fiscal_year = serializers.CharField(required=False, allow_blank=True)

    country = serializers.UUIDField(required=False, allow_null=True)
    institution = serializers.UUIDField(required=False, allow_null=True)
    owner = serializers.UUIDField(required=False, allow_null=True)

    journey_stage = serializers.ChoiceField(choices=JourneyStage.choices, required=False, allow_blank=True)
    offer_status = serializers.ChoiceField(choices=OfferStatus.choices, required=False, allow_blank=True)
    document_status = serializers.ChoiceField(choices=DocumentStatus.choices, required=False, allow_blank=True)
    checklist_status = serializers.ChoiceField(choices=ChecklistStatus.choices, required=False, allow_blank=True)

    due_within_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_DUE_WITHIN_DAYS,
        default=DEFAULT_DUE_WITHIN_DAYS,
    )
    passport_within_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=365 * 2,
        default=DEFAULT_PASSPORT_HORIZON_DAYS,
    )

    def validate_fiscal_year(self, value: str) -> str:
        """Reject a malformed fiscal year here rather than deep in a selector.

        ``fiscal_year_gregorian_range`` raises on a bad label, and letting that
        surface from seven different selectors would produce seven different
        error shapes for one mistake. The actual rule lives in
        ``core.validators.validate_fiscal_year_label``, shared with every other
        app that accepts ``?fiscal_year=``.
        """
        value = (value or "").strip()
        if not value:
            return ""
        validate_fiscal_year_label(value)
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """A window that runs backwards is a mistake, not an empty result.

        Returning zero rows for `date_from > date_to` would look exactly like a
        quiet period, and the user would read the dashboard as reporting no work
        rather than as refusing their input.
        """
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({"date_to": ["Must fall on or after 'date_from'."]})
        return attrs

    def to_filters(self) -> dict[str, Any]:
        """The validated filters as the keyword arguments the selectors take.

        Blank strings and nulls are dropped rather than passed through, so a
        selector never has to distinguish "not filtering on this" from
        "filtering on empty".
        """
        data = dict(self.validated_data)
        return {key: value for key, value in data.items() if value not in (None, "")}


# ---------------------------------------------------------------------------
# Shared row fragments
# ---------------------------------------------------------------------------


class OwnerRowSerializer(serializers.Serializer):
    """One staff member's row in a workload section.

    `owner_id` is null and `owner_display_name` reads "Unassigned" for the
    bucket of work nobody owns — returned deliberately rather than dropped,
    because unowned work is the most likely to be missed.
    """

    owner_id = serializers.CharField(allow_null=True)
    owner_username = serializers.CharField(allow_blank=True)
    owner_display_name = serializers.CharField(allow_blank=True)


class LeadWorkloadRowSerializer(OwnerRowSerializer):
    open_leads = serializers.IntegerField()


class ChecklistWorkloadRowSerializer(OwnerRowSerializer):
    open_items = serializers.IntegerField()
    overdue_items = serializers.IntegerField()
    blocked_items = serializers.IntegerField()


class OfferWorkloadRowSerializer(OwnerRowSerializer):
    awaiting_response = serializers.IntegerField()


class SourceConversionRowSerializer(serializers.Serializer):
    """One intake channel's volume and what became of it."""

    source_id = serializers.CharField()
    source_code = serializers.CharField()
    source_name = serializers.CharField(allow_blank=True)
    total = serializers.IntegerField()
    converted = serializers.IntegerField()
    lost = serializers.IntegerField()
    in_progress = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Worklist rows
# ---------------------------------------------------------------------------


class ChecklistItemRowSerializer(serializers.Serializer):
    """One outstanding requirement, with everything needed to reach it."""

    id = serializers.UUIDField()
    label = serializers.CharField()
    status = serializers.CharField()
    item_type = serializers.CharField()
    is_required = serializers.BooleanField()
    due_at = serializers.DateTimeField(allow_null=True)
    due_at_bs = serializers.SerializerMethodField()
    status_note = serializers.CharField(allow_blank=True)

    checklist_id = serializers.UUIDField()
    checklist_title = serializers.CharField(source="checklist.title")
    journey_id = serializers.UUIDField(source="checklist.journey_id")
    applicant_id = serializers.UUIDField(source="checklist.journey.applicant_id")
    applicant_name = serializers.SerializerMethodField()
    country_name = serializers.SerializerMethodField()

    assigned_to = serializers.SerializerMethodField()

    def get_due_at_bs(self, obj: Any) -> dict[str, Any] | None:
        return _bs(obj.due_at)

    def get_applicant_name(self, obj: Any) -> str:
        applicant = obj.checklist.journey.applicant
        return applicant.full_name

    def get_country_name(self, obj: Any) -> str:
        country = obj.checklist.country
        return country.name if country else ""

    def get_assigned_to(self, obj: Any) -> dict[str, Any] | None:
        user = obj.assigned_to
        if user is None:
            return None
        return {"id": str(user.id), "username": user.username, "display_name": user.display_name}


class OfferRowSerializer(serializers.Serializer):
    """One offer awaiting a response."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    institution_name = serializers.CharField()
    program_title = serializers.CharField()
    intake_label = serializers.CharField(allow_blank=True)
    response_deadline = serializers.DateField(allow_null=True)
    response_deadline_bs = serializers.SerializerMethodField()
    is_response_overdue = serializers.BooleanField()

    journey_id = serializers.UUIDField()
    applicant_id = serializers.UUIDField(source="journey.applicant_id")
    applicant_name = serializers.SerializerMethodField()

    def get_response_deadline_bs(self, obj: Any) -> dict[str, Any] | None:
        return _bs(obj.response_deadline)

    def get_applicant_name(self, obj: Any) -> str:
        applicant = obj.journey.applicant
        return applicant.full_name


class FileRowSerializer(serializers.Serializer):
    """One file awaiting review, or one a reviewer rejected."""

    id = serializers.UUIDField()
    original_filename = serializers.CharField()
    category = serializers.CharField()
    verification_status = serializers.CharField()
    rejection_reason = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    reviewed_at = serializers.DateTimeField(allow_null=True)

    applicant_id = serializers.SerializerMethodField()
    journey_id = serializers.SerializerMethodField()

    def get_applicant_id(self, obj: Any) -> str | None:
        return str(obj.applicant_id) if obj.applicant_id else None

    def get_journey_id(self, obj: Any) -> str | None:
        return str(obj.journey_id) if obj.journey_id else None


class DocumentRowSerializer(serializers.Serializer):
    """One draft document nobody has returned to."""

    id = serializers.UUIDField()
    label = serializers.CharField()
    family = serializers.CharField()
    status = serializers.CharField()
    updated_at = serializers.DateTimeField()

    applicant_id = serializers.SerializerMethodField()
    applicant_name = serializers.SerializerMethodField()

    def get_applicant_id(self, obj: Any) -> str | None:
        return str(obj.applicant_id) if obj.applicant_id else None

    def get_applicant_name(self, obj: Any) -> str:
        applicant = obj.applicant
        if applicant is None:
            return ""
        return applicant.full_name


class PassportRowSerializer(serializers.Serializer):
    """One passport that has expired or is close to it."""

    applicant_id = serializers.UUIDField()
    applicant_name = serializers.SerializerMethodField()
    passport_number = serializers.CharField()
    expiry_date = serializers.DateField()
    expiry_date_bs = serializers.SerializerMethodField()
    has_expired = serializers.SerializerMethodField()

    def get_applicant_name(self, obj: Any) -> str:
        return obj.applicant.full_name

    def get_expiry_date_bs(self, obj: Any) -> dict[str, Any] | None:
        return _bs(obj.expiry_date)

    def get_has_expired(self, obj: Any) -> bool:
        """Computed against today in Nepal (§39.5), never in UTC."""
        from core.nepal.calendar import nepal_today

        return obj.expiry_date < nepal_today()


class LeadRowSerializer(serializers.Serializer):
    """One live lead nobody has followed up."""

    id = serializers.UUIDField()
    full_name = serializers.CharField(allow_blank=True)
    stage = serializers.CharField()
    last_followed_up_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    owner_display_name = serializers.CharField(source="created_by.display_name")


class JourneyRowSerializer(serializers.Serializer):
    """One journey with a destination but no checklist behind it."""

    id = serializers.UUIDField()
    stage = serializers.CharField()
    applicant_id = serializers.UUIDField()
    applicant_name = serializers.SerializerMethodField()
    country_id = serializers.SerializerMethodField()
    country_name = serializers.SerializerMethodField()

    def get_applicant_name(self, obj: Any) -> str:
        return obj.applicant.full_name

    def get_country_id(self, obj: Any) -> str | None:
        return str(obj.target_country_ref_id) if obj.target_country_ref_id else None

    def get_country_name(self, obj: Any) -> str:
        country = obj.target_country_ref
        return country.name if country else obj.target_country


class ActivityRowSerializer(serializers.Serializer):
    """One entry in the recent-activity feed, projected from the audit log."""

    id = serializers.UUIDField()
    app_label = serializers.CharField()
    action = serializers.CharField()
    entity_type = serializers.CharField(allow_blank=True)
    entity_id = serializers.UUIDField(allow_null=True)
    actor_type = serializers.CharField()
    actor_label = serializers.CharField(allow_blank=True)
    summary = serializers.CharField(allow_blank=True)
    success = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    created_at_bs = serializers.SerializerMethodField()

    def get_created_at_bs(self, obj: Any) -> dict[str, Any] | None:
        return _bs(obj.created_at)
