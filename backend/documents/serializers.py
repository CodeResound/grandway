"""Request and response serializers for the documents app.

Serializers own validation, sanitization, and input/output shaping. Business
rules that span more than one field, or that need to read another record, live
in ``services.py``.

**``content`` is passed through untouched.** It is declared as a bare
``JSONField`` with no nested serializer, no field list, and no coercion, because
the 53 template shapes are open (`Record<string, unknown> &`) and every one of
them may carry keys this backend has never heard of. A serializer that named
fields would silently drop them. Shape validation belongs to the frontend that
renders the template; the backend checks that the body is an object and fits
(``services.assert_content_storable``), plus — for ``student-certificate``
alone — the keys that template's frontend asked to have checked
(``validators.validate_template_content``). Both run in the service layer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from documents.constants import TEMPLATE_VERSION_PATTERN, DocumentFamily, DocumentStatus
from documents.models import Document
from documents.validators import validate_template_key

#: Statuses a client may ask for through the status action. ``archived`` is
#: excluded here as well as in the service, so the request is refused at the
#: serializer with a field-level error rather than reaching the domain layer.
SELECTABLE_STATUS_CHOICES = [
    (DocumentStatus.DRAFT.value, DocumentStatus.DRAFT.label),
    (DocumentStatus.READY.value, DocumentStatus.READY.label),
]


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """The Bikram Sambat rendering of a datetime, or None when unset."""
    return to_bs(value).to_dict() if value else None


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write (§39.2).

    ``content`` is deliberately **not** normalizable through this mixin — it is
    opaque JSON, and walking it to normalize strings would be exactly the
    "backend touches the document body" behaviour this app forbids.
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


class DocumentListSerializer(serializers.ModelSerializer):
    """One row of the Document List worklist.

    **Omits ``content`` entirely.** A worklist shows labels and status, and a
    page of twenty bank statements would otherwise carry a megabyte of
    transaction rows nothing renders.
    """

    applicant_name = serializers.SerializerMethodField()
    is_standalone = serializers.BooleanField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)

    class Meta:
        model = Document
        fields = (
            "id",
            "applicant",
            "applicant_name",
            "is_standalone",
            "family",
            "template_key",
            "label",
            "status",
            "is_archived",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_applicant_name(self, obj: Document) -> str | None:
        return str(obj.applicant) if obj.applicant_id else None


class DocumentDetailSerializer(DocumentListSerializer):
    """The full document record, including its body.

    Extends the list shape rather than restating it, so the two cannot drift.
    """

    is_editable = serializers.BooleanField(read_only=True)
    archived_at_bs = serializers.SerializerMethodField()
    archived_by_username = serializers.CharField(source="archived_by.username", read_only=True, default=None)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta(DocumentListSerializer.Meta):
        fields = (
            *DocumentListSerializer.Meta.fields,
            "content",
            "template_version",
            "standalone_purpose",
            "notes",
            "is_editable",
            "archive_reason",
            "archived_at",
            "archived_at_bs",
            "archived_by_username",
            "created_by_username",
        )
        read_only_fields = fields

    def get_archived_at_bs(self, obj: Document) -> dict[str, Any] | None:
        return _bs(obj.archived_at)


class WorkspaceSummarySerializer(serializers.Serializer):
    """One row of the Documents landing table — an applicant and their documents.

    Built from an aggregate queryset of dicts, not model instances, so the
    source keys are the ``values()`` names rather than model attributes.
    """

    applicant_id = serializers.UUIDField(read_only=True)
    applicant_name = serializers.SerializerMethodField()
    document_count = serializers.IntegerField(read_only=True)
    archived_count = serializers.IntegerField(read_only=True)
    last_updated = serializers.DateTimeField(read_only=True)

    def get_applicant_name(self, obj: dict[str, Any]) -> str:
        return obj.get("applicant__full_name") or ""


# A document's history entries are serialized by ``audit.serializers``'s
# canonical ``AuditEventHistorySerializer`` — the shape is the audit app's to
# define, and six per-app copies of it had already drifted apart (§4). The view
# imports it directly. That shared shape includes ``actor_id``, which this app's
# copy omitted; the field is additive and breaks no consumer (§22). It still
# carries no document body — the events record *that* the body changed.


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class DocumentCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A new document being opened in the workspace.

    ``applicant`` and ``standalone_purpose`` are both optional here because
    exactly one of them is required, which is a cross-field rule the service
    owns (``services.assert_owner_declared``) — a serializer-level `required`
    on either would reject the other legitimate case.
    """

    text_fields = ("label", "standalone_purpose", "notes")

    applicant = serializers.UUIDField(required=False, allow_null=True)
    standalone_purpose = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    family = serializers.ChoiceField(choices=DocumentFamily.choices)
    template_key = serializers.CharField(max_length=100, validators=[validate_template_key])
    label = serializers.CharField(max_length=255)

    content = serializers.JSONField(required=False)
    template_version = serializers.RegexField(TEMPLATE_VERSION_PATTERN, required=False)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)


class DocumentUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A save from the document workspace.

    ``applicant``, ``family``, ``template_key``, and ``status`` are absent by
    construction — there is no field here through which a document could become
    a different document, or change standing without a recorded reason.
    """

    text_fields = ("label", "standalone_purpose", "notes")

    label = serializers.CharField(max_length=255, required=False)
    content = serializers.JSONField(required=False)
    template_version = serializers.RegexField(TEMPLATE_VERSION_PATTERN, required=False)
    standalone_purpose = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)


class StatusChangeSerializer(serializers.Serializer):
    """Move a document between its working statuses."""

    status = serializers.ChoiceField(choices=SELECTABLE_STATUS_CHOICES)


class ArchiveSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The archive dialog's payload."""

    text_fields = ("reason",)

    reason = serializers.CharField(max_length=2000)


class RestoreSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The restore action's optional payload — why the document is back."""

    text_fields = ("reason",)

    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


class DocumentSearchSerializer(serializers.Serializer):
    """The Document List's query string.

    Validated rather than read loosely: silently ignoring ``?family=banks``
    would return every document and read as a result set rather than a mistake.
    Same reasoning as ``institutions``, ``offers``, and ``clients``.
    """

    applicant = serializers.UUIDField(required=False)
    standalone = serializers.BooleanField(required=False, allow_null=True, default=None)
    status = serializers.ChoiceField(choices=DocumentStatus.choices, required=False)
    #: Archived documents are hidden unless this is true or ``status=archived``.
    include_archived = serializers.BooleanField(required=False, default=False)
    family = serializers.ChoiceField(choices=DocumentFamily.choices, required=False)
    template_key = serializers.CharField(max_length=100, required=False)
    search = serializers.CharField(max_length=255, required=False)
    fiscal_year = serializers.RegexField(r"^\d{4}/\d{2}$", required=False)


# ---------------------------------------------------------------------------
# Document prefill — GET /documents/prefill/<applicant_id>/
#
# Shaped here with plain serializers rather than applicants' own: §4 lets this
# app read applicants through its selectors, not import its serializers or
# models. The shape is the contract the Woda and certificate forms fill from.
# ---------------------------------------------------------------------------

#: Relationships the prefill names, newest member wins when several exist.
PREFILL_RELATIVES = ("father", "mother", "grandfather", "grandmother")


def split_full_name(full_name: str) -> tuple[str, str, str]:
    """(first, middle, last) from a single English name (§39.1 stores only one).

    First word, last word, and whatever lies between. A heuristic — compound
    surnames split wrongly — which is why the form fields stay editable.
    """
    words = (full_name or "").split()
    if not words:
        return "", "", ""
    if len(words) == 1:
        return words[0], "", ""
    return words[0], " ".join(words[1:-1]), words[-1]


def _address(addresses: list[Any], address_type: str) -> dict[str, Any] | None:
    entry = next((a for a in addresses if a.address_type == address_type), None)
    if entry is None:
        return None
    place = f"{entry.municipality}-{entry.ward}" if entry.municipality and entry.ward else entry.municipality
    formatted = ", ".join(part for part in (entry.street_address, place, entry.district, entry.province) if part)
    return {
        "province": entry.province,
        "district": entry.district,
        "municipality": entry.municipality,
        "ward_no": entry.ward,
        "tole": entry.street_address,
        "formatted": formatted,
    }


class PrefillEducationSerializer(serializers.Serializer):
    level = serializers.CharField()
    qualification = serializers.CharField()
    institution = serializers.CharField()
    country = serializers.CharField()
    completion_status = serializers.CharField()
    score = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    score_type = serializers.CharField()
    grading_system = serializers.CharField()
    start_year = serializers.IntegerField(allow_null=True)
    completion_year = serializers.IntegerField(allow_null=True)
    year_calendar = serializers.CharField()


class PrefillLanguageTestSerializer(serializers.Serializer):
    test_type = serializers.CharField()
    overall_score = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    listening_score = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    reading_score = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    writing_score = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    speaking_score = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    test_date = serializers.DateField(allow_null=True)
    test_date_bs = serializers.SerializerMethodField()
    certificate_number = serializers.CharField()
    expiry_date = serializers.DateField(allow_null=True)
    expiry_date_bs = serializers.SerializerMethodField()

    def get_test_date_bs(self, obj: Any) -> dict[str, Any] | None:
        return _bs(obj.test_date)

    def get_expiry_date_bs(self, obj: Any) -> dict[str, Any] | None:
        return _bs(obj.expiry_date)


class DocumentPrefillSerializer(serializers.Serializer):
    """Everything a document form can fill from the applicant's file. Read-only.

    Pass the applicant from ``selectors.get_prefill_applicant`` and
    ``context={"photo_media_id": ...}``.
    """

    applicant = serializers.SerializerMethodField()
    father = serializers.SerializerMethodField()
    mother = serializers.SerializerMethodField()
    grandfather = serializers.SerializerMethodField()
    grandmother = serializers.SerializerMethodField()
    educations = serializers.SerializerMethodField()
    language_tests = serializers.SerializerMethodField()
    photo_media_id = serializers.SerializerMethodField()

    def get_applicant(self, obj: Any) -> dict[str, Any]:
        first, middle, last = split_full_name(obj.full_name)
        addresses = list(obj.addresses.all())
        phone = next(iter(obj.contact_numbers.all()), None)
        passport = getattr(obj, "passport", None)
        return {
            "first_name": first,
            "middle_name": middle,
            "last_name": last,
            "full_name": obj.full_name,
            "gender": obj.gender,
            "date_of_birth": obj.date_of_birth.isoformat() if obj.date_of_birth else None,
            "date_of_birth_bs": _bs(obj.date_of_birth),
            "nationality": obj.nationality,
            "citizenship_no": obj.citizenship_no,
            "citizenship_issue_district": obj.citizenship_issue_district,
            "national_id_no": obj.national_id_no,
            "passport_no": passport.passport_number if passport else "",
            "permanent_address": _address(addresses, "permanent"),
            "current_address": _address(addresses, "current"),
            "primary_email": obj.email,
            "primary_phone": phone.number if phone else "",
        }

    def _relative(self, obj: Any, relationship: str) -> dict[str, Any] | None:
        matches = [m for m in obj.family_members.all() if m.relationship == relationship]
        if not matches:
            return None
        newest = max(matches, key=lambda m: m.created_at)
        return {"name": newest.full_name, "citizenship_no": newest.citizenship_no, "occupation": newest.occupation}

    def get_father(self, obj: Any) -> dict[str, Any] | None:
        return self._relative(obj, "father")

    def get_mother(self, obj: Any) -> dict[str, Any] | None:
        return self._relative(obj, "mother")

    def get_grandfather(self, obj: Any) -> dict[str, Any] | None:
        return self._relative(obj, "grandfather")

    def get_grandmother(self, obj: Any) -> dict[str, Any] | None:
        return self._relative(obj, "grandmother")

    def get_educations(self, obj: Any) -> list[dict[str, Any]]:
        return PrefillEducationSerializer(obj.educations.all(), many=True).data

    def get_language_tests(self, obj: Any) -> list[dict[str, Any]]:
        return PrefillLanguageTestSerializer(obj.language_tests.all(), many=True).data

    def get_photo_media_id(self, obj: Any) -> str | None:
        return self.context.get("photo_media_id")
