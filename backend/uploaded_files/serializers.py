"""Request and response serializers for the uploaded_files app.

Serializers own validation, sanitization, and input/output shaping. Business
rules that span more than one field, or that need to read another record, live
in ``services.py``.

Two shaping decisions are deliberate:

* **``file`` is never in a response.** Returning a storage path would leak the
  layout of ``MEDIA_ROOT`` and imply a fetchable URL that does not exist. What a
  client gets is the metadata plus an id it can hand to the download endpoint.
* **The upload serializer validates the *envelope*, not the bytes.** Owner
  presence, category, and source are checked here; size, extension, and leading
  bytes are checked in ``validators.py`` and raised as domain errors, so the
  file rules live in one place and are testable without a request.

Every user-entered text field is Unicode-normalized on write (§39.2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.nepal.calendar import to_bs
from core.nepal.text import normalize_unicode
from rest_framework import serializers

from uploaded_files.constants import (
    OWNER_FIELDS,
    FileCategory,
    UploadSource,
    VerificationStatus,
)
from uploaded_files.models import UploadedFile


def _bs(value: datetime | date | None) -> dict[str, Any] | None:
    """Bikram Sambat sibling for one timestamp (§39.4), or None."""
    return to_bs(value).to_dict() if value else None


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


class UploadedFileSerializer(serializers.ModelSerializer):
    """One file, list and detail alike.

    A single shape rather than a list/detail pair: there is no large column to
    withhold from a list — the bytes are not in the row — so a second serializer
    would exist only to drift from this one.
    """

    owner_type = serializers.CharField(read_only=True)
    owner_id = serializers.CharField(read_only=True, allow_null=True)
    is_current = serializers.BooleanField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)
    reviewed_by_username = serializers.CharField(source="reviewed_by.username", read_only=True, default=None)
    archived_by_username = serializers.CharField(source="archived_by.username", read_only=True, default=None)
    # The third lifecycle actor. Present because "who replaced this?" is a
    # question a version chain must be able to answer — omitting it stored the
    # fact and never returned it.
    superseded_by_username = serializers.CharField(source="superseded_by.username", read_only=True, default=None)

    # §39.4 — three of this resource's timestamps are business dates staff read
    # against the Nepali calendar: when the document was received, when it was
    # reviewed, and when it was taken out of use. ``updated_at`` and
    # ``superseded_at`` get no sibling: the first is bookkeeping, and the second
    # is only ever read alongside the successor's ``created_at``, which has one.
    # Same division ``documents`` drew when it gave ``archived_at`` a sibling
    # and ``updated_at`` none.
    created_at_bs = serializers.SerializerMethodField()
    reviewed_at_bs = serializers.SerializerMethodField()
    archived_at_bs = serializers.SerializerMethodField()

    def get_created_at_bs(self, obj: UploadedFile) -> dict[str, Any] | None:
        return _bs(obj.created_at)

    def get_reviewed_at_bs(self, obj: UploadedFile) -> dict[str, Any] | None:
        return _bs(obj.reviewed_at)

    def get_archived_at_bs(self, obj: UploadedFile) -> dict[str, Any] | None:
        return _bs(obj.archived_at)

    class Meta:
        model = UploadedFile
        fields = (
            "id",
            "owner_type",
            "owner_id",
            "category",
            "upload_source",
            "original_filename",
            "content_type",
            "size_bytes",
            "checksum_sha256",
            "version_number",
            "replaces",
            "is_current",
            "superseded_at",
            "superseded_by_username",
            "verification_status",
            "is_verified",
            "rejection_reason",
            "reviewed_at",
            "reviewed_at_bs",
            "reviewed_by_username",
            "is_archived",
            "archive_reason",
            "archived_at",
            "archived_at_bs",
            "archived_by_username",
            "notes",
            "uploaded_by_username",
            "created_at",
            "created_at_bs",
            "updated_at",
        )
        read_only_fields = fields
        # ``file`` is absent from ``fields`` deliberately — see the module
        # docstring. This is the one model field in the project that is never
        # serialized under any circumstances.


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class _OwnerMixin:
    """Requires exactly one owner reference on a write.

    Checked here for a usable field-level error, again in
    ``services.resolve_owner`` because a service must not assume it was called
    through a serializer, and a third time by the
    ``uploaded_file_single_owner`` database constraint. Three layers for one
    rule is unusual; it is warranted because a file with no owner is invisible
    to every screen and a file with two has no answer to "whose archive rule
    applies".
    """

    def _validate_single_owner(self, attrs: dict[str, Any]) -> dict[str, Any]:
        supplied = [field for field in OWNER_FIELDS if attrs.get(field) is not None]
        if len(supplied) != 1:
            raise serializers.ValidationError(
                {
                    "owner": [
                        "Supply exactly one of: applicant, journey, offer, document, snapshot. "
                        f"Received {len(supplied)}."
                    ]
                }
            )
        return attrs


class FileUploadSerializer(_NormalizedTextMixin, _OwnerMixin, serializers.Serializer):
    """``POST /files/`` — a multipart upload against one business record.

    A plain ``Serializer`` rather than a ``ModelSerializer``: the incoming shape
    and the model diverge sharply here, because eight of the model's columns
    (filename, content type, size, checksum, version, and the three lifecycle
    groups) are derived by the service and must not be accepted from a client.
    A ``ModelSerializer`` would list them only to mark them read-only, which
    reads as though a client could plausibly send them.
    """

    text_fields = ("notes",)

    applicant = serializers.UUIDField(required=False, allow_null=True)
    journey = serializers.UUIDField(required=False, allow_null=True)
    offer = serializers.UUIDField(required=False, allow_null=True)
    document = serializers.UUIDField(required=False, allow_null=True)
    snapshot = serializers.UUIDField(required=False, allow_null=True)

    category = serializers.ChoiceField(choices=FileCategory.choices)
    upload_source = serializers.ChoiceField(
        choices=UploadSource.choices,
        required=False,
        default=UploadSource.STAFF_UPLOAD,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    file = serializers.FileField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        return self._validate_single_owner(attrs)


class FileReplaceSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``POST /files/<id>/replace/`` — the successor's bytes and an optional note.

    Carries no owner and no category: both are inherited from the file being
    replaced. Accepting either would let a replacement quietly move a file to
    another applicant, which is exactly the change ``FIELD_IMMUTABLE`` exists to
    prevent on the ordinary update path.
    """

    text_fields = ("notes",)

    file = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class FileUpdateSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``PATCH /files/<id>/`` — the only two fields a file has that can change."""

    text_fields = ("notes",)

    category = serializers.ChoiceField(choices=FileCategory.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class FileReviewSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``POST /files/<id>/verify/`` — a verdict and, when refusing, its reason.

    ``pending`` is absent from the choices: it is a starting state, not a
    verdict, and there is no un-review action. The object-level check here gives
    a field-level error on ``reason``; ``services.review_file`` repeats it as a
    domain rule.
    """

    status = serializers.ChoiceField(
        choices=[
            (VerificationStatus.VERIFIED, VerificationStatus.VERIFIED.label),
            (VerificationStatus.REJECTED, VerificationStatus.REJECTED.label),
        ]
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    text_fields = ("reason",)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if attrs["status"] == VerificationStatus.REJECTED and not attrs.get("reason", "").strip():
            raise serializers.ValidationError({"reason": ["A reason is required when rejecting a file."]})
        return attrs


class FileArchiveSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``POST /files/<id>/archive/`` — the mandatory why."""

    text_fields = ("reason",)

    reason = serializers.CharField()


class FileRestoreSerializer(_NormalizedTextMixin, serializers.Serializer):
    """``POST /files/<id>/restore/`` — an optional note.

    No reason is required, unlike archiving: restoring returns a file to the
    state it was already in, and demanding an explanation for undoing something
    discourages correcting a mistake.
    """

    text_fields = ("note",)

    note = serializers.CharField(required=False, allow_blank=True, default="")


class FileSearchSerializer(serializers.Serializer):
    """Query parameters for ``GET /files/``.

    Declared as a serializer so an unparseable ``?applicant=`` or an unknown
    ``?category=`` fails with the project-wide ``VALIDATION_ERROR`` envelope
    rather than being silently ignored — a filter that quietly does nothing is
    how a screen ends up showing another applicant's files.
    """

    applicant = serializers.UUIDField(required=False)
    journey = serializers.UUIDField(required=False)
    offer = serializers.UUIDField(required=False)
    document = serializers.UUIDField(required=False)
    snapshot = serializers.UUIDField(required=False)

    category = serializers.ChoiceField(choices=FileCategory.choices, required=False)
    verification_status = serializers.ChoiceField(choices=VerificationStatus.choices, required=False)
    upload_source = serializers.ChoiceField(choices=UploadSource.choices, required=False)
    is_archived = serializers.BooleanField(required=False, allow_null=True, default=None)
    is_current = serializers.BooleanField(required=False, allow_null=True, default=None)
    checksum = serializers.CharField(required=False, max_length=64)
    search = serializers.CharField(required=False, allow_blank=True)
