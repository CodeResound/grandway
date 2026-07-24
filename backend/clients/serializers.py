"""Request and response serializers for the clients app.

Serializers own validation, sanitization, and output shaping. Business rules
that span more than one field, or that need to read another record, live in
``services.py``.

Every user-entered text field is normalized with
``core.nepal.text.normalize_unicode`` on write (§39.2) — not only the
Devanagari-labelled ones. Devanagari has NFC/NFD variants that look identical
but differ byte-wise, and un-normalized text breaks search and equality.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.constants import ContactNumberLabel
from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from core.validators import validate_contact_number
from rest_framework import serializers

from clients.constants import ClientStatus
from clients.models import Client, ClientContactNumber


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """The Bikram Sambat rendering of a date, or None when there is no date."""
    return to_bs(value).to_dict() if value else None


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write.

    A mixin rather than a dozen near-identical ``validate_<field>`` methods —
    copying the same two lines per field is how one of them ends up missing it.
    """

    text_fields: tuple[str, ...] = ()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)  # type: ignore[misc]
        for field in self.text_fields:
            if attrs.get(field):
                attrs[field] = normalize_unicode(attrs[field])
        return attrs


# ---------------------------------------------------------------------------
# Contact numbers
# ---------------------------------------------------------------------------


class ContactNumberSerializer(serializers.ModelSerializer):
    """One contact number as returned to a client."""

    class Meta:
        model = ClientContactNumber
        fields = ("id", "number", "label", "is_primary")
        read_only_fields = fields


class ContactNumberInputSerializer(serializers.Serializer):
    """One contact number in a write payload.

    Nested inside the client write, never posted on its own — numbers are
    replaced as a complete set, matching how ``applicants`` handles them.
    """

    number = serializers.CharField(max_length=32, validators=[validate_contact_number])
    label = serializers.ChoiceField(choices=ContactNumberLabel.choices, default=ContactNumberLabel.MOBILE)
    is_primary = serializers.BooleanField(default=False)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class ClientListSerializer(serializers.ModelSerializer):
    """One row of the Client List directory.

    Carries `primary_contact_number` so the directory can show a number per row
    without the client fetching the detail of every entry — the concept's Client
    List names "email or phone" as a column.
    """

    primary_contact_number = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "name_np",
            "name_en",
            "name_romanized",
            "spokesperson_name_np",
            "spokesperson_name_en",
            "email",
            "primary_contact_number",
            "status",
            "is_active",
            "logo_url",
            "updated_at",
        )
        read_only_fields = fields

    def get_primary_contact_number(self, obj: Client) -> str | None:
        """The number flagged primary, else the first one, else None.

        Reads from the prefetched relation rather than querying — ordering is
        ``-is_primary`` then ``created_at``, so the first row is already the
        right one.
        """
        numbers = list(obj.contact_numbers.all())
        return numbers[0].number if numbers else None


class ClientDetailSerializer(serializers.ModelSerializer):
    """The full client record.

    Declared independently of the list shape rather than extending it: the two
    have different purposes here — the list shows a single flattened
    ``primary_contact_number``, the detail shows every number as an object — so
    inheritance would mean overriding as much as it reused.
    """

    contact_numbers = ContactNumberSerializer(many=True, read_only=True)
    retired_at_bs = serializers.SerializerMethodField()
    retired_by_username = serializers.CharField(source="retired_by.username", read_only=True, default=None)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "name_np",
            "name_en",
            "name_romanized",
            "spokesperson_name_np",
            "spokesperson_name_en",
            "spokesperson_name_romanized",
            "spokesperson_designation",
            "email",
            "website",
            "logo_url",
            "address",
            "contact_numbers",
            "status",
            "is_active",
            "status_note",
            "retired_at",
            "retired_at_bs",
            "retired_by_username",
            "notes",
            "created_by_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_retired_at_bs(self, obj: Client) -> dict[str, Any] | None:
        return _bs(obj.retired_at)


# A client's history entries are serialized by ``audit.serializers``'s canonical
# ``AuditEventHistorySerializer`` — the shape is the audit app's to define, and
# six per-app copies of it had already drifted apart (§4). The view imports it
# directly. That shared shape includes ``actor_id``, which this app's copy
# omitted; the field is additive and breaks no consumer (§22).


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class _ClientWritableSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The fields a client may set on create and correct on update.

    A ``Serializer`` subclass rather than a plain mixin: DRF's metaclass only
    inherits declared fields from bases carrying ``_declared_fields``, so fields
    on a plain mixin would be silently dropped.

    ``status`` is absent by construction — it moves only through the retire and
    restore actions, which stamp who did it and why.
    """

    text_fields = (
        "name_np",
        "name_en",
        "name_romanized",
        "spokesperson_name_np",
        "spokesperson_name_en",
        "spokesperson_name_romanized",
        "spokesperson_designation",
        "address",
        "notes",
    )

    name_en = serializers.CharField(max_length=255, required=False, allow_blank=True)
    name_romanized = serializers.CharField(max_length=255, required=False, allow_blank=True)

    spokesperson_name_np = serializers.CharField(max_length=255, required=False, allow_blank=True)
    spokesperson_name_en = serializers.CharField(max_length=255, required=False, allow_blank=True)
    spokesperson_name_romanized = serializers.CharField(max_length=255, required=False, allow_blank=True)
    spokesperson_designation = serializers.CharField(max_length=150, required=False, allow_blank=True)

    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.URLField(max_length=500, required=False, allow_blank=True)
    logo_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    address = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)

    contact_numbers = ContactNumberInputSerializer(many=True, required=False)


class ClientCreateSerializer(_ClientWritableSerializer):
    """A new partner organization being added to the directory.

    ``name_np`` is the one required field. §39.1 applies here as written —
    unlike ``institutions``, whose foreign universities have no authoritative
    Devanagari identity, a referral partner of a Nepal consultancy generally
    does.
    """

    name_np = serializers.CharField(max_length=255)


class ClientUpdateSerializer(_ClientWritableSerializer):
    """A correction to a client's identity, contact details, or notes."""

    name_np = serializers.CharField(max_length=255, required=False)


class RetireSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The retire dialog's payload."""

    text_fields = ("reason",)

    reason = serializers.CharField(max_length=2000)


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


class ClientSearchSerializer(serializers.Serializer):
    """The Client List's query string.

    Validated rather than read loosely: silently ignoring ``?status=retired``
    would return the whole directory and read as a result set rather than a
    mistake. Same reasoning as ``institutions`` and ``offers``.
    """

    status = serializers.ChoiceField(choices=ClientStatus.choices, required=False)
    search = serializers.CharField(max_length=150, required=False)
    fiscal_year = serializers.RegexField(r"^\d{4}/\d{2}$", required=False)
