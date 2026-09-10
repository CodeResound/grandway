"""Enums, limits, error codes, and audit-action names for the uploaded_files app.

One idea governs this module: **this app stores bytes and the facts about them,
and decides nothing about what those bytes mean.**

It does not read a PDF, does not extract a passport number, does not thumbnail an
image, and does not refuse an operation elsewhere because a file is unverified.
``verification_status`` is a record of a human judgement, not a gate — no
endpoint in Grandway consults it. That is why there is no "required categories"
map, no per-category verification policy, and no per-owner-type category
restriction: each would be a rule no consumer enforces.

The upload limits live here rather than in settings because they are contract,
not configuration. A client is told 10 MB in ``docs/API.md``; an operator
changing that silently in an environment file would make the published contract
wrong in one environment and right in another.
"""

from django.db import models


class FileCategory(models.TextChoices):
    """What kind of file this is.

    ``concepts/uploaded_files.txt`` names "file category" as stored data but
    leaves the vocabulary open ("Which file categories are required in v1").
    These eleven cover every owner type the concept lists — an applicant's
    identity and photograph, academic records, test results, an offer letter,
    financial and sponsorship evidence, a signature image, and a
    platform-produced PDF. ``SIGNATURE_IMAGE`` was declared here before anything
    could use it; ``OwnerType.SIGNATORY`` is what finally gave it an owner.

    ``OTHER`` is deliberate. An enum with no escape hatch turns every
    unanticipated document into a migration, and the operator who needs to
    attach one is never the person who can run it.
    """

    PASSPORT = "passport", "Passport"
    PHOTOGRAPH = "photograph", "Photograph"
    ACADEMIC_TRANSCRIPT = "academic_transcript", "Academic Transcript"
    ACADEMIC_CERTIFICATE = "academic_certificate", "Academic Certificate"
    TEST_SCORE_REPORT = "test_score_report", "Test Score Report"
    OFFER_LETTER = "offer_letter", "Offer Letter"
    FINANCIAL = "financial", "Financial Document"
    SPONSORSHIP = "sponsorship", "Sponsorship Document"
    SIGNATURE_IMAGE = "signature_image", "Signature Image"
    GENERATED_DOCUMENT = "generated_document", "Generated Document"
    OTHER = "other", "Other"


class UploadSource(models.TextChoices):
    """Where the file came from.

    ``concepts/uploaded_files.txt`` names "upload source" as stored data. Two
    values, because there are two origins that behave differently in review: a
    file a person handed over, and a file this platform produced. A third value
    for "imported from a previous system" would be a guess — no import path
    exists.
    """

    STAFF_UPLOAD = "staff_upload", "Staff Upload"
    SYSTEM_GENERATED = "system_generated", "System Generated"


class VerificationStatus(models.TextChoices):
    """Whether a human has accepted this file.

    ``concepts/uploaded_files.txt`` lifecycle step 3: "Review and mark it
    verified, pending, or rejected."
    """

    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"


class OwnerType(models.TextChoices):
    """The six business records a file may belong to.

    **Derived, never stored.** Each value names one of the six nullable
    foreign keys on the model; the column that is set determines the value.
    Storing it as well would create a second source of truth that could disagree
    with the foreign keys — exactly what the ``uploaded_file_single_owner``
    constraint exists to prevent.

    ``signatory`` is the newest and the only one that is not applicant work: a
    certificate signatory's signature image, which lived as an external URL on
    ``document_templates.Signatory`` until this app could hold it. It is the
    worked example of the claim this docstring used to make in the abstract —
    a sixth value plus its column really was the whole change.

    ``education`` and ``test_scores`` are named in the concept and absent here
    because those apps do not exist. Adding a seventh value plus its column is
    one additive migration when they do.
    """

    APPLICANT = "applicant", "Applicant"
    JOURNEY = "journey", "Applicant Journey"
    OFFER = "offer", "Offer"
    DOCUMENT = "document", "Document"
    SNAPSHOT = "snapshot", "Document Snapshot"
    SIGNATORY = "signatory", "Signatory"


#: The model field name behind each owner type, in the order the serializer and
#: the database constraint both walk them. One tuple, so a seventh owner is
#: added in exactly one place.
OWNER_FIELDS: tuple[str, ...] = (
    OwnerType.APPLICANT,
    OwnerType.JOURNEY,
    OwnerType.OFFER,
    OwnerType.DOCUMENT,
    OwnerType.SNAPSHOT,
    OwnerType.SIGNATORY,
)

#: The owner names spelled out in the two "exactly one owner" error messages,
#: derived rather than typed so a seventh owner never leaves a message naming
#: six. Message text is not contract (``docs/INTEGRATION.md`` §3 says not to
#: assert on it), but a message that lies is still a defect.
OWNER_NAMES: str = ", ".join(OWNER_FIELDS)

#: Owner types whose files are Admin-only, because their **owning records** are.
#:
#: ``documents``, ``document_history``, and ``document_templates`` are Admin-only
#: on every route, reads included. Without this, a Lead Manager who cannot open a
#: bank statement could list and download the PDF attached to it — the file
#: ledger would become a side door around another module's access rule, and
#: neither module would know.
#:
#: ``signatory`` joins for the same structural reason and one of its own. The
#: structural reason: ``document_templates.access.require_template_actor``
#: refuses a Lead Manager on **every** route including ``GET``, so listing or
#: downloading a signatory's file here would hand them an artefact from an app
#: they cannot open at all. Its own reason: a signature image is the most
#: forgeable asset in the system — it is what makes an issued certificate look
#: authoritative — so read access to the bytes is not a smaller ask than read
#: access to the signatory row, it is a larger one.
#:
#: A file inherits the visibility of the record it belongs to. That is the rule;
#: this tuple is its current membership, and it must be revisited in the same
#: change as any decision to give Lead Managers document access.
ADMIN_ONLY_OWNER_TYPES: tuple[str, ...] = (
    OwnerType.DOCUMENT,
    OwnerType.SNAPSHOT,
    OwnerType.SIGNATORY,
)

#: Statuses the verify action may set. ``pending`` is absent deliberately: it is
#: a starting state, not a decision, and there is no un-review action.
REVIEWABLE_STATUSES: tuple[str, ...] = (
    VerificationStatus.VERIFIED,
    VerificationStatus.REJECTED,
)

# ---------------------------------------------------------------------------
# Upload limits (§14) — contract, not configuration. See the module docstring.
# ---------------------------------------------------------------------------

#: Ten megabytes. A 300dpi passport scan is ~1 MB and a twelve-page transcript
#: PDF is well under this; anything larger is more likely a mistake than a
#: document.
MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

#: Chunk size for streamed checksumming. Large enough to be cheap, small enough
#: that a 10 MB file never sits in memory whole.
CHECKSUM_CHUNK_BYTES: int = 64 * 1024

#: Extension → the content type stored on the record. The client's declared
#: ``Content-Type`` is never trusted; this map is the only source of the value.
ALLOWED_EXTENSIONS: dict[str, str] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

#: How many leading bytes ``validators.assert_content_matches_extension`` reads.
#: WEBP needs twelve (``RIFF`` + a four-byte length + ``WEBP``); everything else
#: needs eight or fewer.
SIGNATURE_PREFIX_BYTES: int = 12


class UploadedFilesAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    FILE_UPLOADED = "file_uploaded"
    FILE_UPDATED = "file_updated"
    FILE_REPLACED = "file_replaced"
    FILE_REVIEWED = "file_reviewed"
    FILE_ARCHIVED = "file_archived"
    FILE_RESTORED = "file_restored"
    FILE_DOWNLOADED = "file_downloaded"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "uploaded_files"

#: ``audit.AuditEvent.entity_type`` value.
AUDIT_ENTITY_FILE = "uploaded_file"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the uploaded_files app (§7)."""

    ACTOR_FORBIDDEN = "UPLOADED_FILES_ACTOR_FORBIDDEN"
    FILE_NOT_FOUND = "UPLOADED_FILES_FILE_NOT_FOUND"

    # --- Ownership -------------------------------------------------------
    OWNER_REQUIRED = "UPLOADED_FILES_OWNER_REQUIRED"
    OWNER_NOT_FOUND = "UPLOADED_FILES_OWNER_NOT_FOUND"

    # --- The upload itself (§14) -----------------------------------------
    FILE_MISSING = "UPLOADED_FILES_FILE_MISSING"
    FILE_TOO_LARGE = "UPLOADED_FILES_FILE_TOO_LARGE"

    #: A zero-byte part. Its own code rather than folding into ``FILE_TOO_LARGE``:
    #: a client that maps one code to "your file is too big" would otherwise tell
    #: a user their empty file was oversized.
    FILE_EMPTY = "UPLOADED_FILES_FILE_EMPTY"
    FILE_TYPE_NOT_ALLOWED = "UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED"

    #: The extension and the leading bytes disagree — a ``.pdf`` that is really
    #: a PNG. The one check a client cannot talk its way past.
    FILE_CONTENT_MISMATCH = "UPLOADED_FILES_FILE_CONTENT_MISMATCH"

    #: The row exists but its bytes are gone from disk. A 404 to the client and
    #: an ``ERROR`` in the log — this means the storage volume and the database
    #: have diverged, which no application code can fix.
    FILE_BYTES_MISSING = "UPLOADED_FILES_FILE_BYTES_MISSING"

    # --- Lifecycle -------------------------------------------------------
    ALREADY_SUPERSEDED = "UPLOADED_FILES_ALREADY_SUPERSEDED"
    FILE_ARCHIVED = "UPLOADED_FILES_FILE_ARCHIVED"
    ALREADY_ARCHIVED = "UPLOADED_FILES_ALREADY_ARCHIVED"
    NOT_ARCHIVED = "UPLOADED_FILES_NOT_ARCHIVED"
    VERIFICATION_STATUS_INVALID = "UPLOADED_FILES_VERIFICATION_STATUS_INVALID"
    REJECTION_REASON_REQUIRED = "UPLOADED_FILES_REJECTION_REASON_REQUIRED"
    ARCHIVE_REASON_REQUIRED = "UPLOADED_FILES_ARCHIVE_REASON_REQUIRED"

    #: A ``PATCH`` carried a field that is fixed after upload. Rejected rather
    #: than dropped: a client that re-pointed a file at another applicant and
    #: got 200 back would believe the move happened.
    FIELD_IMMUTABLE = "UPLOADED_FILES_FIELD_IMMUTABLE"
