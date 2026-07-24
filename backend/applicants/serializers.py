"""Request validation and response shaping for the applicants app.

Serializers own input validation and Unicode normalization (§39.2); they never
hand a raw request dict to a service. Write serializers validate only — the
actual writes happen in ``services``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.constants import ContactNumberLabel
from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from applicants.constants import AddressType, ApplicantStatus, CreationSource, FamilyRelationship, Gender
from applicants.models import (
    Applicant,
    ApplicantAddress,
    ApplicantContactNumber,
    EmergencyContact,
    FamilyMember,
    PassportDetail,
)


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """Render a stored date/datetime as its Bikram Sambat date (§39.4)."""
    return to_bs(value).to_dict() if value else None


class UserBriefSerializer(serializers.Serializer):
    """The minimum identity needed to attribute an action in the UI."""

    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# Sub-resource read shapes
# ---------------------------------------------------------------------------


class ApplicantContactNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicantContactNumber
        fields = ["id", "number", "label", "is_primary"]
        read_only_fields = fields


class ApplicantAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicantAddress
        fields = [
            "id",
            "address_type",
            "country",
            "province",
            "district",
            "municipality",
            "ward",
            "street_address",
            "postal_code",
        ]
        read_only_fields = fields


class PassportDetailSerializer(serializers.ModelSerializer):
    issued_date_bs = serializers.SerializerMethodField()
    expiry_date_bs = serializers.SerializerMethodField()

    class Meta:
        model = PassportDetail
        fields = [
            "passport_number",
            "issuing_country",
            "place_of_issue",
            "issued_date",
            "issued_date_bs",
            "expiry_date",
            "expiry_date_bs",
        ]
        read_only_fields = fields

    def get_issued_date_bs(self, obj: PassportDetail) -> dict[str, Any] | None:
        return _bs(obj.issued_date)

    def get_expiry_date_bs(self, obj: PassportDetail) -> dict[str, Any] | None:
        return _bs(obj.expiry_date)


class FamilyMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilyMember
        fields = ["id", "relationship", "full_name", "occupation", "contact_number"]
        read_only_fields = fields


class EmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyContact
        fields = [
            "id",
            "full_name",
            "relationship",
            "contact_number",
            "email",
            "address",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Sub-resource write shapes (nested inside the applicant payload)
# ---------------------------------------------------------------------------


class ContactNumberWriteSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=32)
    label = serializers.ChoiceField(choices=ContactNumberLabel.choices, required=False)
    is_primary = serializers.BooleanField(required=False, default=False)

    def validate_number(self, value: str) -> str:
        return value.strip()


class AddressWriteSerializer(serializers.Serializer):
    address_type = serializers.ChoiceField(choices=AddressType.choices)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    province = serializers.CharField(max_length=100, required=False, allow_blank=True)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    municipality = serializers.CharField(max_length=150, required=False, allow_blank=True)
    ward = serializers.CharField(max_length=10, required=False, allow_blank=True)
    street_address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=20, required=False, allow_blank=True)

    def validate_municipality(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_street_address(self, value: str) -> str:
        return normalize_unicode(value)


class PassportWriteSerializer(serializers.Serializer):
    passport_number = serializers.CharField(max_length=50)
    issuing_country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    place_of_issue = serializers.CharField(max_length=150, required=False, allow_blank=True)
    issued_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)

    def validate_passport_number(self, value: str) -> str:
        return value.strip().upper()


class FamilyMemberWriteSerializer(serializers.Serializer):
    relationship = serializers.ChoiceField(choices=FamilyRelationship.choices)
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    occupation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    contact_number = serializers.CharField(max_length=32, required=False, allow_blank=True)

    def validate_full_name(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_occupation(self, value: str) -> str:
        return normalize_unicode(value)


class EmergencyContactWriteSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    relationship = serializers.CharField(max_length=100, required=False, allow_blank=True)
    contact_number = serializers.CharField(max_length=32)
    email = serializers.EmailField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)

    def validate_full_name(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_address(self, value: str) -> str:
        return normalize_unicode(value)


# ---------------------------------------------------------------------------
# Applicant read shapes
# ---------------------------------------------------------------------------


class ApplicantListSerializer(serializers.ModelSerializer):
    """The applicant as it appears in a list."""

    created_by = UserBriefSerializer(read_only=True)
    contact_numbers = ApplicantContactNumberSerializer(many=True, read_only=True)
    date_of_birth_bs = serializers.SerializerMethodField()
    destinations = serializers.SerializerMethodField()

    class Meta:
        model = Applicant
        fields = [
            "id",
            "full_name",
            "date_of_birth",
            "date_of_birth_bs",
            "gender",
            "nationality",
            "email",
            "status",
            "creation_source",
            "created_by",
            "contact_numbers",
            "destinations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_date_of_birth_bs(self, obj: Applicant) -> dict[str, Any] | None:
        return _bs(obj.date_of_birth)

    def get_destinations(self, obj: Applicant) -> list[dict[str, Any]]:
        """Where this person is trying to go, one entry per journey.

        The applicant record deliberately holds no destination — a person is not
        a study plan, and someone may try for Australia one year and Canada the
        next (``applicants/models.py``). But a list that cannot show where
        anyone is headed forces a second round trip per row just to render a
        country column, so the destinations are projected here.

        Read through the reverse ``journeys`` accessor, which needs no import of
        ``applicant_journeys`` — that app owns the ForeignKey. Same technique as
        ``get_originating_lead_id`` below. ``country_id`` is null for a journey
        recorded before the catalogue existed; ``target_country`` is the free
        text it was typed as, and is the only destination such a journey has.
        """
        entries: list[dict[str, Any]] = []
        for journey in obj.journeys.all():
            country = journey.target_country_ref
            entries.append(
                {
                    "journey_id": str(journey.id),
                    "stage": journey.stage,
                    "country_id": str(country.id) if country else None,
                    "country_code": country.code if country else "",
                    "country_name": country.name if country else "",
                    "target_country": journey.target_country,
                }
            )
        return entries


class ApplicantDetailSerializer(ApplicantListSerializer):
    """The applicant as it appears on their own file page."""

    addresses = ApplicantAddressSerializer(many=True, read_only=True)
    family_members = FamilyMemberSerializer(many=True, read_only=True)
    emergency_contacts = EmergencyContactSerializer(many=True, read_only=True)
    passport = serializers.SerializerMethodField()
    originating_lead_id = serializers.SerializerMethodField()

    class Meta(ApplicantListSerializer.Meta):
        fields = [
            *ApplicantListSerializer.Meta.fields,
            "addresses",
            "passport",
            "family_members",
            "emergency_contacts",
            "originating_lead_id",
        ]
        read_only_fields = fields

    def get_passport(self, obj: Applicant) -> dict[str, Any] | None:
        passport = getattr(obj, "passport", None)
        return PassportDetailSerializer(passport).data if passport else None

    def get_originating_lead_id(self, obj: Applicant) -> str | None:
        """The lead this applicant was converted from, if any.

        Read through the reverse accessor — ``leads.Lead`` owns the ForeignKey,
        so this app has no dependency on ``leads`` (see ``models.Applicant``).
        """
        lead = getattr(obj, "originating_lead", None)
        return str(lead.id) if lead else None


# ---------------------------------------------------------------------------
# Applicant write shapes
# ---------------------------------------------------------------------------


class ApplicantCreateSerializer(serializers.Serializer):
    """Create input. ``status`` is not accepted — a new applicant is always active."""

    full_name = serializers.CharField(max_length=255)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False, allow_blank=True)
    nationality = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    contact_numbers = ContactNumberWriteSerializer(many=True, allow_empty=False)
    addresses = AddressWriteSerializer(many=True, required=False)
    passport = PassportWriteSerializer(required=False)
    family_members = FamilyMemberWriteSerializer(many=True, required=False)
    emergency_contacts = EmergencyContactWriteSerializer(many=True, required=False)

    def validate_full_name(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_nationality(self, value: str) -> str:
        return normalize_unicode(value)

    def validate_addresses(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """At most one address per type — the model enforces it, this reports it cleanly."""
        types = [entry["address_type"] for entry in value]
        if len(types) != len(set(types)):
            raise serializers.ValidationError("An applicant may have only one address of each type.")
        return value


class ApplicantUpdateSerializer(ApplicantCreateSerializer):
    """Update input — every field optional; collections replace wholesale."""

    full_name = serializers.CharField(max_length=255, required=False)
    contact_numbers = ContactNumberWriteSerializer(many=True, allow_empty=False, required=False)


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ApplicantStatus.choices)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

# An applicant's history entries are serialized by ``audit.serializers``'s
# canonical ``AuditEventHistorySerializer`` — the shape is the audit app's to
# define, and six per-app copies of it had already drifted apart (§4). The view
# imports it directly.


#: Re-exported for the list endpoint's documented filter values.
CREATION_SOURCE_CHOICES = CreationSource.choices
