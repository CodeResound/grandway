"""Request and response serializers for the document_templates app.

Serializers own validation, sanitization, and input/output shaping. Business
rules that span more than one field, or that need to read another record, live
in ``services.py``.

**Every user-entered text field is Unicode-normalized on write (§39.2)** — not
only the Devanagari-labelled ones. Two spellings of the same Devanagari name
that look identical but differ at the byte level would otherwise be two
different signatories to the search index.
"""

from __future__ import annotations

from typing import Any

from core.nepal.text import normalize_unicode
from documents.constants import DocumentFamily
from documents.validators import validate_template_key
from rest_framework import serializers

from document_templates.constants import LifecycleStatus
from document_templates.models import DocumentTemplate, Signatory


class _NormalizedTextMixin:
    """Normalizes every declared free-text field on write (§39.2)."""

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


class SignatorySerializer(serializers.ModelSerializer):
    """One signatory, list and detail alike.

    A single shape rather than the list/detail pair the other apps declare:
    there is no large column to withhold from a list, so a second serializer
    would exist only to drift from this one.
    """

    is_active = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = Signatory
        fields = (
            "id",
            "name",
            "title",
            "role",
            "signature_image_url",
            "status",
            "is_active",
            "status_note",
            "created_by_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class DocumentTemplateSerializer(serializers.ModelSerializer):
    """One catalogue row, list and detail alike."""

    is_active = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = DocumentTemplate
        fields = (
            "id",
            "key",
            "family",
            "label",
            "description",
            "display_order",
            "status",
            "is_active",
            "status_note",
            "created_by_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class SignatoryCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A new person in the signature library.

    The service normalizes ``name`` on write (§39.2).

    ``status`` is absent — a new signatory starts as ``draft`` and is activated
    through its own action, so "this signatory is usable" is always a recorded
    decision rather than a default.
    """

    text_fields = ("name", "title", "role")

    name = serializers.CharField(max_length=255)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    role = serializers.CharField(max_length=100, required=False, allow_blank=True)
    signature_image_url = serializers.URLField(max_length=500, required=False, allow_blank=True)


class SignatoryUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A correction to an existing signatory.

    ``status`` is absent by construction — there is no field here through which
    a signatory could change standing without the transition being recorded.
    """

    text_fields = ("name", "title", "role")

    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    role = serializers.CharField(max_length=100, required=False, allow_blank=True)
    signature_image_url = serializers.URLField(max_length=500, required=False, allow_blank=True)


class TemplateCreateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """A new slug in the catalogue.

    ``key`` and ``family`` are cross-validated by the service using the rule
    ``documents`` owns — send them together, from one picker.
    """

    text_fields = ("label", "description")

    key = serializers.CharField(max_length=100, validators=[validate_template_key])
    family = serializers.ChoiceField(choices=DocumentFamily.choices)
    label = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    display_order = serializers.IntegerField(min_value=0, required=False)


class TemplateUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """An edit to a catalogue row.

    ``key`` is absent by construction, and a request carrying one is rejected in
    the view rather than dropped — see ``views.TemplateDetailView``.
    """

    text_fields = ("label", "description")

    family = serializers.ChoiceField(choices=DocumentFamily.choices, required=False)
    label = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    display_order = serializers.IntegerField(min_value=0, required=False)


class StatusChangeSerializer(_NormalizedTextMixin, serializers.Serializer):
    """The activate/deactivate payload, shared by both resources.

    The note is optional on every transition. Unlike archiving a document — which
    demands a reason because the record is being taken out of circulation
    forever — deactivating a template or signatory is reversible and loses
    nothing, so requiring an explanation would be ceremony rather than
    accountability.
    """

    text_fields = ("note",)

    status = serializers.ChoiceField(choices=LifecycleStatus.choices)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------


class SignatorySearchSerializer(serializers.Serializer):
    """The signatory list's query string.

    Validated rather than read loosely: silently ignoring ``?status=enabled``
    would return every signatory and read as a result set rather than a mistake.
    Same reasoning as ``documents``, ``institutions``, and ``offers``.
    """

    status = serializers.ChoiceField(choices=LifecycleStatus.choices, required=False)
    role = serializers.CharField(max_length=100, required=False)
    search = serializers.CharField(max_length=255, required=False)


class TemplateSearchSerializer(serializers.Serializer):
    """The template catalogue's query string."""

    family = serializers.ChoiceField(choices=DocumentFamily.choices, required=False)
    status = serializers.ChoiceField(choices=LifecycleStatus.choices, required=False)
    search = serializers.CharField(max_length=255, required=False)
