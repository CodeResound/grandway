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
from django.urls import reverse
from documents.constants import DocumentFamily
from documents.validators import validate_template_key
from rest_framework import serializers

from document_templates.constants import LifecycleStatus
from document_templates.models import DocumentTemplate, Signatory
from document_templates.selectors import get_current_signature_file


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


class _SignatureFileSerializer(serializers.Serializer):
    """The six file facts a client needs to render a signature.

    Declared locally rather than reusing ``uploaded_files.UploadedFileSerializer``
    — §4 permits importing another app's ``selectors.py``/``services.py``, not
    its ``serializers.py``, and re-exporting that app's 29-field shape from a
    signatory payload would make every future change to it a breaking change
    here.
    """

    id = serializers.UUIDField(read_only=True)
    download_path = serializers.SerializerMethodField()
    original_filename = serializers.CharField(read_only=True)
    content_type = serializers.CharField(read_only=True)
    size_bytes = serializers.IntegerField(read_only=True)
    version_number = serializers.IntegerField(read_only=True)
    uploaded_at = serializers.DateTimeField(source="created_at", read_only=True)

    def get_download_path(self, obj: Any) -> str:
        """The relative path the bytes are fetched from.

        **This is a ``fetch`` target, not an ``<img src>``.** The route requires
        the bearer token and answers with ``Content-Disposition: attachment``, so
        pointing an ``<img>`` at it yields a 401 and a broken image. Fetch it
        with credentials, then ``URL.createObjectURL`` the blob.

        Relative on purpose — a path cannot be mistaken for a public asset URL.
        Built with ``reverse()`` rather than an f-string so a route change breaks
        at server start instead of silently emitting a dead path.
        """
        return reverse("v1:uploaded_files:file-download", kwargs={"file_id": obj.id})


class SignatorySerializer(serializers.ModelSerializer):
    """One signatory, list and detail alike.

    A single shape rather than the list/detail pair the other apps declare:
    there is no large column to withhold from a list, so a second serializer
    would exist only to drift from this one.

    ``signature_file`` is declared as a ``SerializerMethodField``, which
    **shadows the model foreign key** — the response carries the nested file
    object rather than a bare UUID. That is the intent, and it is non-obvious
    enough to say out loud.
    """

    is_active = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    signature_file = serializers.SerializerMethodField()
    signature_source = serializers.SerializerMethodField()

    class Meta:
        model = Signatory
        fields = (
            "id",
            "name",
            "title",
            "role",
            "signature_image_url",
            "signature_file",
            "signature_source",
            "status",
            "is_active",
            "status_note",
            "created_by_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_signature_file(self, obj: Signatory) -> dict[str, Any] | None:
        """The uploaded signature, or ``null`` when none currently renders.

        ``null`` covers three different situations — never uploaded, uploaded
        then archived, uploaded then superseded directly through the ledger —
        and a client cannot tell them apart from this field alone. It does not
        need to: ``signature_source`` is what it renders from.
        """
        current = get_current_signature_file(obj)
        return _SignatureFileSerializer(current).data if current is not None else None

    def get_signature_source(self, obj: Signatory) -> str:
        """Which signature a client should render: ``uploaded``, ``url``, or ``none``.

        **This field exists so the precedence rule is not prose.** Without it
        every consumer re-implements "an uploaded file wins, else the legacy
        URL, else nothing" — including the archived-and-superseded half of the
        rule, which it cannot see, because a client has no way to know that the
        file behind a signatory was archived. One server-computed enum, and the
        client renders exactly one branch.
        """
        if get_current_signature_file(obj) is not None:
            return "uploaded"
        return "url" if obj.signature_image_url else "none"


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


class SignatureUploadSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``POST /signatories/<id>/signature/`` — the image, and an optional note.

    Two fields, and the absences matter more than the presences. No
    ``category``, no ``upload_source``, no owner: all three are fixed by the
    service. Accepting any of them would let a client store something other than
    a signature under a signatory's name, or attach a signature to someone else.

    The extension check lives in ``services.set_signatory_signature`` rather than
    a ``validate_file`` method here, so a direct service caller cannot bypass it
    — the same discipline ``uploaded_files`` applies to ownership, which it
    checks in the serializer, the service, and the database.

    **Exactly one file part.** ``DATA_UPLOAD_MAX_NUMBER_FILES`` is 1, and a
    second part raises during multipart parsing, before any handler runs, which
    surfaces as a 500 rather than a 400. Documented in ``docs/API.md``.
    """

    text_fields = ("notes",)

    file = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


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
