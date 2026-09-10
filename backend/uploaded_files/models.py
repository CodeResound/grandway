"""Data models for the uploaded_files app.

See ``uploaded_files/docs/DATA_CONTRACT.md`` for the authoritative contract.

Three conventions run through this app and are deliberate:

* **The bytes are private.** ``MEDIA_ROOT`` is not web-served and ``MEDIA_URL``
  is unset. The ``file`` column is never serialized — returning a storage path
  would leak the layout of the volume and imply a fetchable URL that does not
  exist. The only way out is ``GET /files/<id>/download/``, which applies the
  same authority check as every other route.
* **Nothing is ever deleted and nothing is ever overwritten.** There is no
  delete endpoint, no delete service, and no path that replaces the bytes of an
  existing row. A replacement is a *new row* pointing back at its predecessor,
  so the chain is a fact in the database rather than an entry in a log.
* **Exactly one owner, enforced by the database.** A serializer check alone
  would leave the admin, the shell, and any future management command free to
  create a file that belongs to two records or to none.

``upload_destination`` lives in this module rather than in a helper because
every migration that touches the ``file`` column references it by import path
forever. Moving it later would need a migration edit; moving it *silently* would
break historical migrations on a fresh database.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.models import BaseModel
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from uploaded_files.constants import (
    OWNER_FIELDS,
    FileCategory,
    OwnerType,
    UploadSource,
    VerificationStatus,
)


def upload_destination(instance: UploadedFile, filename: str) -> str:
    """Return the storage path for one uploaded file.

    ``uploaded_files/<owner_type>/<YYYY>/<MM>/<uuid4>.<ext>``.

    **The client's filename is never used on disk.** It is replaced by a fresh
    UUID, which removes three problems at once: a crafted name cannot traverse a
    path, two applicants named the same scan cannot collide, and an operator
    browsing the volume cannot read an applicant's identity off the filenames.
    The original survives verbatim in ``original_filename`` and is what a client
    sees on download.

    The extension is carried through because it is already validated against the
    file's leading bytes by then, and keeping it makes the volume navigable for
    an operator holding a row's id.
    """
    _, _, extension = (filename or "").rpartition(".")
    extension = extension.strip().lower()
    stamp = timezone.now()
    stored_name = f"{uuid.uuid4()}.{extension}" if extension else str(uuid.uuid4())
    return f"uploaded_files/{instance.owner_type or 'unassigned'}/{stamp:%Y}/{stamp:%m}/{stored_name}"


def _single_owner_condition() -> models.Q:
    """Build the "exactly one owner FK is set" database condition.

    Written as an explicit six-way disjunction rather than an arithmetic
    null-count so it evaluates identically on PostgreSQL and on the SQLite the
    test suite runs against. **Do not "simplify" it to ``num_nonnulls(...) = 1``**
    — that is PostgreSQL-only, and the test suite would stop exercising the rule
    it is here to enforce. Derived from ``OWNER_FIELDS`` rather than typed out,
    so a seventh owner extends the constraint by extending one tuple.

    Note that the *migration* inlines the expanded tree rather than calling this,
    so extending ``OWNER_FIELDS`` also requires a migration that drops and
    re-adds the constraint. ``0002_signatory_owner`` is the worked example.
    """
    condition = models.Q()
    for owner in OWNER_FIELDS:
        clause = {f"{field}__isnull": field != owner for field in OWNER_FIELDS}
        condition |= models.Q(**clause)
    return condition


class UploadedFile(BaseModel):
    """One stored file and everything Grandway knows about it.

    A file is not a document (``concepts/uploaded_files.txt`` — "This is not the
    document renderer"). ``documents`` owns the editable business object,
    ``document_history`` owns the frozen copies, ``document_templates`` owns the
    catalogue; this owns the bytes and their lifecycle, and it is the only place
    in the project where bytes are stored at all.

    **Two apps reference this model, and both do it the same way.**
    ``checklists.ChecklistItem.evidence_file`` cites the file that proves a
    requirement was met, and ``document_templates.Signatory.signature_file``
    names the signature image that renders on a certificate. Both are nullable
    ``PROTECT`` foreign keys resolved through a function-local selector import.

    Everywhere else the relationship is still one-way by design — ``applicants``
    has no photograph field and ``offers`` has no attachment field, so a file
    knows its owner while the owner learns about its files only through this
    app's list endpoint filtered by that record's id. A reverse pointer is what
    an app adds when *which* file is the answer to a question, rather than
    merely *some* file among several.
    """

    # --- Ownership: exactly one of six --------------------------------------
    #
    # ``PROTECT`` on all six, matching every existing cross-app FK in the
    # project: a person with files on record cannot be removed out from under
    # them. There is no cascade here, deliberately, whatever a client may assume
    # about deleting an applicant.
    #
    # ``signatory`` arrived last and is the only owner that is not applicant
    # work — it holds a certificate signer's signature image. Adding it was one
    # column plus one entry in ``OWNER_FIELDS``, exactly as this comment used to
    # predict in the abstract.
    #
    # ``education`` and ``test_scores`` are named in the concept and absent here
    # because those apps do not exist. A seventh column plus one more entry in
    # ``OWNER_FIELDS`` is the whole change when they ship.
    applicant = models.ForeignKey(
        "applicants.Applicant",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
        null=True,
        blank=True,
    )
    journey = models.ForeignKey(
        "applicant_journeys.ApplicantJourney",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
        null=True,
        blank=True,
    )
    offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
        null=True,
        blank=True,
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
        null=True,
        blank=True,
    )
    snapshot = models.ForeignKey(
        "document_history.DocumentSnapshot",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
        null=True,
        blank=True,
    )
    signatory = models.ForeignKey(
        "document_templates.Signatory",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
        null=True,
        blank=True,
    )

    # --- Classification ------------------------------------------------------
    category = models.CharField(max_length=30, choices=FileCategory.choices, db_index=True)
    upload_source = models.CharField(
        max_length=20,
        choices=UploadSource.choices,
        default=UploadSource.STAFF_UPLOAD,
    )
    notes = models.TextField(blank=True)

    # --- The file itself -----------------------------------------------------
    #
    # ``max_length=500`` because the generated path carries an owner type, a
    # year, a month, and a UUID; the default 100 would truncate it.
    file = models.FileField(upload_to=upload_destination, max_length=500)
    original_filename = models.CharField(
        max_length=255,
        help_text="The name the file arrived with. Never used as the name on disk.",
    )
    content_type = models.CharField(
        max_length=100,
        help_text="Derived from the validated extension — never the client's declared Content-Type.",
    )
    size_bytes = models.PositiveBigIntegerField()
    checksum_sha256 = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Streamed SHA-256 hex digest, computed once at upload. Duplicates are recorded, not blocked.",
    )

    # --- Replacement chain ---------------------------------------------------
    #
    # ``OneToOneField`` rather than a plain FK: the uniqueness is what keeps the
    # chain from forking, so "which file is current" always has exactly one
    # answer. ``PROTECT`` because a superseded file is the reason its successor
    # exists.
    version_number = models.PositiveIntegerField(
        default=1,
        help_text="Position in this file's replacement chain, 1-based.",
    )
    replaces = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="replaced_by",
        null=True,
        blank=True,
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files_superseded",
    )

    # --- Verification --------------------------------------------------------
    #
    # A record of a human judgement, not a gate. No endpoint anywhere in
    # Grandway refuses to proceed because a file is unverified — see
    # docs/DATA_CONTRACT.md, Deliberate Deviations.
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files_reviewed",
    )

    # --- Archive state (cleared on restore) ----------------------------------
    #
    # Denormalized current state, mirroring ``documents``, ``leads``,
    # ``applicant_journeys``, ``offers``, and ``clients`` (§35 item 15): current
    # state is a plain field read, while the append-only audit log remains the
    # authoritative event history.
    archive_reason = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files_archived",
    )

    # --- Provenance ----------------------------------------------------------
    uploaded_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="files_uploaded",
    )

    class Meta:
        db_table = "uploaded_files_uploadedfile"
        verbose_name = "Uploaded File"
        verbose_name_plural = "Uploaded Files"
        # Newest first, with ``id`` as a tiebreaker.
        #
        # The tiebreaker is not cosmetic. ``created_at`` is not unique — a
        # replace writes two rows in one transaction — while this list is
        # paginated and offers no client-controllable ordering. A non-unique
        # sort key under page-number pagination lets a row appear on two pages
        # or on none, which on a file ledger reads as a file that silently
        # vanished. ``id`` is a UUID: an arbitrary but *stable* tiebreak, which
        # is all pagination needs.
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=_single_owner_condition(),
                name="uploaded_file_single_owner",
            ),
        ]
        indexes = [
            # The four per-record file panels.
            models.Index(fields=["applicant", "-created_at"], name="file_applicant_recent_idx"),
            models.Index(fields=["journey", "-created_at"], name="file_journey_recent_idx"),
            models.Index(fields=["offer", "-created_at"], name="file_offer_recent_idx"),
            models.Index(fields=["document", "-created_at"], name="file_document_recent_idx"),
            # The review queue: ?verification_status=pending.
            models.Index(fields=["verification_status", "-created_at"], name="file_review_queue_idx"),
            # The category filter on the file list.
            models.Index(fields=["category", "-created_at"], name="file_category_recent_idx"),
            # ?search= over the original filename. pg_trgm already exists —
            # leads migration 0002, declared as a migration dependency.
            #
            # One field, not the three-field set §39.6 describes: a filename has
            # no Devanagari/Roman/romanized triple, because it is a byte-level
            # artefact rather than a canonical identity. The limitation that
            # follows is real and documented — a Devanagari-named file will not
            # be found by a Roman-script query.
            GinIndex(
                fields=["original_filename"],
                name="file_orig_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]
        # The ``snapshot`` and ``signatory`` FKs get only their implicit
        # indexes: a snapshot has at most one generated file and a signatory
        # holds one live signature plus a short chain of superseded and archived
        # predecessors, so in both cases a composite would serve nothing a
        # single-row lookup does not.

    def __str__(self) -> str:
        # Reads only local columns — naming the owner here would look friendlier
        # and would fire one query per row in the admin changelist.
        return f"{self.original_filename} ({self.category} v{self.version_number})"

    # --- Derived ownership ---------------------------------------------------
    #
    # Computed, never stored. A stored ``owner_type`` would be a second source
    # of truth that could disagree with the foreign keys — exactly what the
    # ``uploaded_file_single_owner`` constraint exists to prevent.

    @property
    def owner_type(self) -> str | None:
        """Which of the six business records this file belongs to."""
        for owner in OWNER_FIELDS:
            if getattr(self, f"{owner}_id", None) is not None:
                return owner
        return None

    @property
    def owner_id(self) -> Any | None:
        """The id of the owning record."""
        owner = self.owner_type
        return getattr(self, f"{owner}_id") if owner else None

    # --- Derived lifecycle ---------------------------------------------------

    @property
    def is_current(self) -> bool:
        """True while nothing has replaced this file.

        Independent of ``is_archived``, deliberately: archiving does not make a
        file non-current, and being superseded does not archive it. They answer
        different questions — "is this the latest version" and "is this still in
        active use" — and collapsing them would make the version chain
        unreadable the first time someone archived a v1.
        """
        return self.superseded_at is None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def owner_type_label(self) -> str:
        """Human-readable owner type, for the admin and for logs."""
        owner = self.owner_type
        return OwnerType(owner).label if owner else "—"
