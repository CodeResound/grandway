"""Request validation and response shaping for the institutions app.

Two conventions run through this module:

* **Every user-entered text field is Unicode-normalized on write** (§39.2).
  Devanagari has NFC/NFD variants that look identical but differ at the byte
  level, and the rule applies to all text — not only the Nepali-labelled
  fields.
* **Identifiers are immutable after creation.** Update serializers simply do
  not declare ``code``, ``institution`` on a campus, or ``institution`` on a
  program, so a client that sends them is ignored rather than refused — the
  same shape ``applicant_journeys`` uses for ``applicant``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.constants import StudyLevel
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from institutions.constants import AvailabilityStatus, InstitutionType
from institutions.models import Campus, Country, Field, Institution, Program
from institutions.validators import validate_currency_code, validate_reference_code


class OptionalBooleanField(serializers.BooleanField):
    """A tri-state boolean query parameter: true, false, or *not filtering*.

    DRF's ``BooleanField`` implements HTML checkbox semantics — when the key is
    absent from a form or query string it yields ``False`` rather than being
    skipped. For a filter that is exactly wrong: omitting
    ``?scholarship_available`` would silently filter to programs *without* a
    scholarship, hiding every scholarship program from the default search.

    Absent therefore means ``None``, which the selectors read as "do not
    filter on this at all".
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("default", None)
        super().__init__(**kwargs)


class NormalizedTextMixin:
    """Normalizes every declared ``CharField``/``TextField`` on write.

    Declared once rather than as thirty ``validate_<field>()`` methods: the
    rule is the same for every text field in this app, and writing it out per
    field is exactly how one gets missed.
    """

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        for name, value in attrs.items():
            if isinstance(value, str):
                attrs[name] = normalize_unicode(value)
        return attrs


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


class FieldSerializer(serializers.ModelSerializer):
    """A study field as returned to clients."""

    class Meta:
        model = Field
        fields = [
            "id",
            "code",
            "name_en",
            "name_np",
            "is_active",
            "display_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class FieldCreateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    #: Declared explicitly to drop DRF's automatic ``UniqueValidator``. A taken
    #: code is reported as 409 by the view, matching the campus-duplicate case
    #: — a consumer should not have to handle "already exists" two ways.
    code = serializers.CharField(max_length=50, validators=[validate_reference_code])

    class Meta:
        model = Field
        fields = ["code", "name_en", "name_np", "is_active", "display_order"]


class FieldUpdateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    """``code`` is absent deliberately — it is a stable identifier."""

    class Meta:
        model = Field
        fields = ["name_en", "name_np", "is_active", "display_order"]
        extra_kwargs = {"name_en": {"required": False}}


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------


class CountrySerializer(serializers.ModelSerializer):
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Country
        fields = [
            "id",
            "code",
            "name_en",
            "name_np",
            "availability_status",
            "availability_note",
            "is_usable",
            "notes",
            "display_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CountryCreateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    #: See ``FieldCreateSerializer.code`` — duplicates are a 409, not a 400.
    code = serializers.CharField(max_length=10, validators=[validate_reference_code])

    class Meta:
        model = Country
        fields = [
            "code",
            "name_en",
            "name_np",
            "availability_status",
            "availability_note",
            "notes",
            "display_order",
        ]


class CountryUpdateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    """``code`` is absent deliberately — it is a stable identifier."""

    class Meta:
        model = Country
        fields = [
            "name_en",
            "name_np",
            "availability_status",
            "availability_note",
            "notes",
            "display_order",
        ]
        extra_kwargs = {"name_en": {"required": False}}


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------


class CountryBriefSerializer(serializers.Serializer):
    """Just enough of the country to label an institution in a list."""

    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)
    availability_status = serializers.CharField(read_only=True)


class InstitutionSerializer(serializers.ModelSerializer):
    country = CountryBriefSerializer(read_only=True)
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Institution
        fields = [
            "id",
            "country",
            "name_en",
            "name_np",
            "common_name",
            "institution_type",
            "availability_status",
            "availability_note",
            "is_usable",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class InstitutionCreateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    country = serializers.PrimaryKeyRelatedField(queryset=Country.objects.all())

    class Meta:
        model = Institution
        fields = [
            "country",
            "name_en",
            "name_np",
            "common_name",
            "institution_type",
            "availability_status",
            "availability_note",
            "notes",
        ]


class InstitutionUpdateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    """``country`` stays writable — an institution filed under the wrong country
    is a correctable mistake, and the change is audited."""

    country = serializers.PrimaryKeyRelatedField(queryset=Country.objects.all(), required=False)

    class Meta:
        model = Institution
        fields = [
            "country",
            "name_en",
            "name_np",
            "common_name",
            "institution_type",
            "availability_status",
            "availability_note",
            "notes",
        ]
        extra_kwargs = {"name_en": {"required": False}}


# ---------------------------------------------------------------------------
# Campus
# ---------------------------------------------------------------------------


class InstitutionBriefSerializer(serializers.Serializer):
    """Just enough of the institution to label a campus or program."""

    id = serializers.UUIDField(read_only=True)
    name_en = serializers.CharField(read_only=True)
    common_name = serializers.CharField(read_only=True)
    availability_status = serializers.CharField(read_only=True)


class CampusSerializer(serializers.ModelSerializer):
    institution = InstitutionBriefSerializer(read_only=True)
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Campus
        fields = [
            "id",
            "institution",
            "name_en",
            "city",
            "availability_status",
            "availability_note",
            "is_usable",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CampusCreateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    """``institution`` comes from the URL, not the body — a campus is created
    under a provider and never moves between providers."""

    class Meta:
        model = Campus
        fields = ["name_en", "city", "availability_status", "availability_note", "notes"]


class CampusUpdateSerializer(NormalizedTextMixin, serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = ["name_en", "city", "availability_status", "availability_note", "notes"]
        extra_kwargs = {"name_en": {"required": False}}


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------


class FieldBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)


class CampusBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name_en = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    availability_status = serializers.CharField(read_only=True)


class ProgramListSerializer(serializers.ModelSerializer):
    """The program as it appears in a search result row.

    Carries the tuition and availability a counsellor compares on, but not the
    entry expectations — those are long free text and belong on the detail
    page.
    """

    institution = InstitutionBriefSerializer(read_only=True)
    campus = CampusBriefSerializer(read_only=True)
    field = FieldBriefSerializer(read_only=True)
    country = CountryBriefSerializer(source="institution.country", read_only=True)
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Program
        fields = [
            "id",
            "title",
            "institution",
            "campus",
            "country",
            "qualification_level",
            "field",
            "duration_months",
            "intake_pattern",
            "tuition_amount",
            "tuition_currency",
            "tuition_fee_period",
            "tuition_is_indicative",
            "scholarship_available",
            "availability_status",
            "availability_note",
            "is_usable",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProgramDetailSerializer(ProgramListSerializer):
    """Adds the entry expectations, tuition caveats, and notes."""

    class Meta(ProgramListSerializer.Meta):
        fields = [
            *ProgramListSerializer.Meta.fields,
            "tuition_notes",
            "academic_requirement",
            "english_requirement",
            "backlog_tolerance",
            "document_expectation",
            "selection_notes",
            "scholarship_notes",
            "notes",
        ]
        read_only_fields = fields


#: Clears the model's uppercase-only currency regex so the API can accept
#: "aud" and normalize it. The model keeps the strict validator, so a direct
#: ORM write still cannot store a lowercase code.
CURRENCY_FIELD_KWARGS: dict[str, Any] = {"validators": []}


class ProgramWriteMixin(NormalizedTextMixin):
    """Field-level rules shared by create and update.

    The cross-field rules — campus/institution agreement and tuition
    completeness — are **not** here. They live in ``services.py`` because they
    need the resulting state of a PATCH, which a serializer that sees only the
    incoming fields cannot compute.
    """

    def validate_tuition_currency(self, value: str) -> str:
        """Accept any case, store upper.

        Each concrete serializer must clear this field's inherited validators
        via ``extra_kwargs`` (see ``CURRENCY_FIELD_KWARGS``) — the model's
        uppercase-only regex otherwise runs *before* this method and rejects
        "aud" before it can be upper-cased. A field declared on this mixin
        would not help: DRF's metaclass collects declared fields only from
        serializer bases, so one declared on a plain mixin is silently dropped.
        """
        if not value:
            return value
        value = value.upper()
        validate_currency_code(value)
        return value

    def validate_tuition_amount(self, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise serializers.ValidationError("Tuition amount must be zero or greater.")
        return value


class ProgramCreateSerializer(ProgramWriteMixin, serializers.ModelSerializer):
    institution = serializers.PrimaryKeyRelatedField(queryset=Institution.objects.all())
    campus = serializers.PrimaryKeyRelatedField(queryset=Campus.objects.all(), required=False, allow_null=True)
    field = serializers.PrimaryKeyRelatedField(queryset=Field.objects.all())

    class Meta:
        model = Program
        fields = [
            "institution",
            "campus",
            "title",
            "qualification_level",
            "field",
            "duration_months",
            "intake_pattern",
            "tuition_amount",
            "tuition_currency",
            "tuition_fee_period",
            "tuition_is_indicative",
            "tuition_notes",
            "academic_requirement",
            "english_requirement",
            "backlog_tolerance",
            "document_expectation",
            "selection_notes",
            "scholarship_available",
            "scholarship_notes",
            "availability_status",
            "availability_note",
            "notes",
        ]
        extra_kwargs = {
            "qualification_level": {"required": True},
            "tuition_currency": CURRENCY_FIELD_KWARGS,
        }


class ProgramUpdateSerializer(ProgramWriteMixin, serializers.ModelSerializer):
    """``institution`` is absent deliberately — a program that changes provider
    is a different program. ``campus`` stays writable, but the service still
    checks it belongs to the program's institution."""

    campus = serializers.PrimaryKeyRelatedField(queryset=Campus.objects.all(), required=False, allow_null=True)
    field = serializers.PrimaryKeyRelatedField(queryset=Field.objects.all(), required=False)

    class Meta:
        model = Program
        fields = [
            "campus",
            "title",
            "qualification_level",
            "field",
            "duration_months",
            "intake_pattern",
            "tuition_amount",
            "tuition_currency",
            "tuition_fee_period",
            "tuition_is_indicative",
            "tuition_notes",
            "academic_requirement",
            "english_requirement",
            "backlog_tolerance",
            "document_expectation",
            "selection_notes",
            "scholarship_available",
            "scholarship_notes",
            "availability_status",
            "availability_note",
            "notes",
        ]
        extra_kwargs = {
            "title": {"required": False},
            "qualification_level": {"required": False},
            "tuition_currency": CURRENCY_FIELD_KWARGS,
        }


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


class ProgramSearchSerializer(serializers.Serializer):
    """Validates the shortlisting search's query string.

    ``usable_only`` defaults to **true**: the concept requires that inactive
    items are hidden from active selection workflows, and a search that
    silently offers a withdrawn program is worse than one that returns
    nothing.
    """

    country = serializers.UUIDField(required=False)
    institution = serializers.UUIDField(required=False)
    campus = serializers.UUIDField(required=False)
    qualification_level = serializers.ChoiceField(choices=StudyLevel.choices, required=False)
    field = serializers.UUIDField(required=False)
    availability_status = serializers.ChoiceField(choices=AvailabilityStatus.choices, required=False)
    #: Defaults to true rather than being tri-state — "hide what we cannot
    #: offer" is the intended behaviour of an omitted parameter, not "do not
    #: filter".
    usable_only = serializers.BooleanField(required=False, default=True)
    scholarship_available = OptionalBooleanField()
    tuition_max = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0"))
    q = serializers.CharField(required=False, allow_blank=False, max_length=150)

    def validate_q(self, value: str) -> str:
        return normalize_unicode(value)


class InstitutionSearchSerializer(serializers.Serializer):
    country = serializers.UUIDField(required=False)
    institution_type = serializers.ChoiceField(choices=InstitutionType.choices, required=False)
    availability_status = serializers.ChoiceField(choices=AvailabilityStatus.choices, required=False)
    usable_only = serializers.BooleanField(required=False, default=False)
    q = serializers.CharField(required=False, allow_blank=False, max_length=150)

    def validate_q(self, value: str) -> str:
        return normalize_unicode(value)


class CountrySearchSerializer(serializers.Serializer):
    availability_status = serializers.ChoiceField(choices=AvailabilityStatus.choices, required=False)
    usable_only = serializers.BooleanField(required=False, default=False)
    q = serializers.CharField(required=False, allow_blank=False, max_length=150)

    def validate_q(self, value: str) -> str:
        return normalize_unicode(value)


class CampusSearchSerializer(serializers.Serializer):
    availability_status = serializers.ChoiceField(choices=AvailabilityStatus.choices, required=False)
    usable_only = serializers.BooleanField(required=False, default=False)
    q = serializers.CharField(required=False, allow_blank=False, max_length=150)

    def validate_q(self, value: str) -> str:
        return normalize_unicode(value)


class FieldSearchSerializer(serializers.Serializer):
    is_active = OptionalBooleanField()
    q = serializers.CharField(required=False, allow_blank=False, max_length=150)

    def validate_q(self, value: str) -> str:
        return normalize_unicode(value)
