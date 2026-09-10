"""Business logic for the uploaded_files app.

Services receive already-validated data, own every rule that spans more than one
field, and return model instances — never HTTP responses.

Four rules here are load-bearing:

1. **A file is validated before it is stored, never after.** ``validate_upload``
   runs first; a rejected upload leaves no row and no bytes. There is no
   quarantine state and no cleanup path, because nothing ever gets far enough to
   need one.
2. **The checksum is streamed, never buffered.** A 10 MB file must not sit in
   memory whole just to be hashed.
3. **Replacement writes a new row.** The predecessor keeps its bytes, its
   verdict, and its place in the chain. Nothing overwrites a stored file, ever —
   which is what makes "what did we hold at the time" answerable later.
4. **The storage path never leaves this module.** It is not serialized, not
   logged, and not recorded in an audit event. What is recorded is the file's
   id, its category, and its owner.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from applicant_journeys.selectors import get_journey_by_id
from applicants.selectors import get_applicant_by_id
from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone
from document_history.selectors import get_snapshot_by_id
from document_templates.selectors import get_signatory_by_id
from documents.selectors import get_document_by_id
from offers.selectors import get_offer_by_id

from uploaded_files.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_FILE,
    CHECKSUM_CHUNK_BYTES,
    OWNER_FIELDS,
    OWNER_NAMES,
    REVIEWABLE_STATUSES,
    OwnerType,
    UploadedFilesAuditAction,
    UploadSource,
    VerificationStatus,
)
from uploaded_files.exceptions import (
    AlreadyArchivedError,
    AlreadySupersededError,
    FieldImmutableError,
    FileArchivedError,
    InvalidVerificationStatusError,
    NotArchivedError,
    OwnerNotFoundError,
    OwnerNotResolvedError,
    ReasonRequiredError,
)
from uploaded_files.models import UploadedFile
from uploaded_files.validators import validate_upload

logger = logging.getLogger(__name__)

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}

#: Fields a client may change after upload. Everything else about a file is
#: fixed the moment it is stored.
MUTABLE_FIELDS: frozenset[str] = frozenset({"category", "notes"})


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    uploaded_file: UploadedFile,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one audit event for a file action.

    **What is deliberately absent: the storage path and the file's contents.**
    ``documents`` replaces its body with a marker and ``document_history`` drops
    two whole JSON columns; the equivalent here is narrower but the same idea —
    an event records *which* file moved and *where it belongs*, never where the
    bytes live. A path in the log would let anyone with log access locate an
    applicant's passport on the volume without touching the API.

    ``original_filename`` **is** recorded, in the summary and in the metadata.
    It can carry identity ("sita_passport_scan.pdf"), and that is accepted: the
    log is already scoped to staff, and a file event that cannot say which file
    it was about is not worth writing.
    """
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=AUDIT_ENTITY_FILE,
        entity_id=str(uploaded_file.id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata={
            "category": uploaded_file.category,
            "owner_type": uploaded_file.owner_type or "",
            "owner_id": str(uploaded_file.owner_id or ""),
            **(metadata or {}),
        },
        ip_address=ip_address,
        source="api",
    )


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


#: One lookup per owner type, each the owning app's own selector.
#:
#: §4 permits importing another app's ``selectors.py``, and this is the only
#: cross-app coupling in the module. Six imports is a lot, and the alternative
#: is worse: assigning a raw id to a foreign key would push a nonexistent owner
#: all the way to an ``IntegrityError``, which surfaces to a client as a 500
#: with no indication of which of the six fields was wrong.
#:
#: **Import-cycle note.** ``document_templates`` imports back into this module
#: (``services.set_signatory_signature`` calls ``upload_file``/``replace_file``),
#: making these two the project's first bidirectional app pair. It does not
#: deadlock, and the reason is narrow enough to write down: the edge *out* of
#: here lands in ``document_templates.selectors``, which imports only its own
#: ``constants`` and ``models``, while the edge *back* is function-local. The
#: invariant that keeps it acyclic is therefore:
#:
#:     ``document_templates/selectors.py`` must never import
#:     ``document_templates/services.py``, and this app's ``selectors.py`` must
#:     never import this app's ``services.py``.
#:
#: Break either and Django fails at startup with a "partially initialized
#: module" traceback naming neither app's real problem.
#:
#: Documented in ``docs/DATA_CONTRACT.md`` and in ``docs/INTEGRATION.md`` §2, as
#: §4 requires for a runtime dependency, and in ``document_templates``' §2 for
#: the other direction.
_OWNER_LOOKUPS: dict[str, Any] = {
    OwnerType.APPLICANT: get_applicant_by_id,
    OwnerType.JOURNEY: get_journey_by_id,
    OwnerType.OFFER: get_offer_by_id,
    OwnerType.DOCUMENT: get_document_by_id,
    OwnerType.SNAPSHOT: get_snapshot_by_id,
    OwnerType.SIGNATORY: get_signatory_by_id,
}


def resolve_owner(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve the single owner reference in ``data`` to ``{field: instance}``.

    The serializer checks the *count* too, for a field-level error message. This
    exists because a service must not depend on having been called through a
    serializer: ``concepts/uploaded_files.txt`` makes single ownership a
    lifecycle rule, and the database constraint makes it a schema rule, so the
    business layer states it as well rather than assuming two other layers
    caught it.

    Returns instances rather than ids so the caller can assign them directly and
    so a nonexistent owner is caught here — as a 400 naming the field — instead
    of at the database as an integrity error.
    """
    supplied = {field: data[field] for field in OWNER_FIELDS if data.get(field) is not None}
    if len(supplied) != 1:
        raise OwnerNotResolvedError(f"Exactly one of {OWNER_NAMES} must be supplied.")

    field, value = next(iter(supplied.items()))
    instance = _OWNER_LOOKUPS[field](str(value))
    if instance is None:
        raise OwnerNotFoundError(field, f"No {field} with that id.")
    return {field: instance}


def compute_checksum(upload: Any) -> str:
    """Return the SHA-256 hex digest of an uploaded file, read in chunks.

    Rewinds afterwards so the caller can still save it. Never loads the whole
    file into memory — Django's ``chunks()`` is the same iterator the storage
    backend uses to write it.
    """
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks(CHECKSUM_CHUNK_BYTES):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def assert_writable(uploaded_file: UploadedFile) -> None:
    """Refuse any write against an archived file.

    An archived file must be restored first, so "archived, then changed" is
    always two visible events rather than a silent amendment. Same rule
    ``documents`` applies to its own archived records.
    """
    if uploaded_file.is_archived:
        raise FileArchivedError("This file is archived. Restore it before making changes.")


def assert_fields_mutable(fields: dict[str, Any]) -> None:
    """Refuse an update targeting anything fixed at upload time."""
    fixed = sorted(set(fields) - MUTABLE_FIELDS)
    if fixed:
        raise FieldImmutableError(f"These fields cannot be changed after upload: {', '.join(fixed)}.")


def _normalize_text(fields: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """Unicode-normalize the named free-text fields in place (§39.2)."""
    for name in names:
        if fields.get(name):
            fields[name] = normalize_unicode(fields[name])
    return fields


# ---------------------------------------------------------------------------
# Upload and replace
# ---------------------------------------------------------------------------


@transaction.atomic
def upload_file(
    *,
    actor: Any,
    upload: Any,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> UploadedFile:
    """Store one file against exactly one business record.

    Order matters and is fixed: resolve the owner, validate the bytes, hash
    them, then write. Validation before storage means a rejected upload leaves
    nothing behind — no row, no orphan on the volume, and nothing for a cleanup
    job to find later.

    A new file is always ``pending``. There is no path that uploads something
    pre-verified, including for ``system_generated`` files: a PDF this platform
    produced is still a document a human should look at before it is trusted.
    """
    data = _normalize_text(dict(data), ("notes",))
    owner = resolve_owner(data)

    original_filename, content_type = validate_upload(upload)
    checksum = compute_checksum(upload)

    uploaded_file = UploadedFile(
        **owner,
        category=data["category"],
        upload_source=data.get("upload_source", UploadSource.STAFF_UPLOAD),
        notes=data.get("notes", ""),
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=upload.size,
        checksum_sha256=checksum,
        uploaded_by=actor,
    )
    # Assigned after construction so ``upload_destination`` can read the owner
    # type off the instance when it builds the path.
    uploaded_file.file = upload
    uploaded_file.save()

    _record(
        action=UploadedFilesAuditAction.FILE_UPLOADED,
        actor=actor,
        uploaded_file=uploaded_file,
        summary=f"File '{uploaded_file.original_filename}' uploaded.",
        metadata={
            "size_bytes": uploaded_file.size_bytes,
            "content_type": uploaded_file.content_type,
            "checksum_sha256": uploaded_file.checksum_sha256,
        },
        ip_address=ip_address,
    )
    return uploaded_file


@transaction.atomic
def replace_file(
    *,
    actor: Any,
    uploaded_file: UploadedFile,
    upload: Any,
    notes: str = "",
    ip_address: str | None = None,
) -> UploadedFile:
    """Supersede a file with a newer one, keeping both.

    ``concepts/uploaded_files.txt`` lifecycle step 4: "Replace it with a newer
    file when needed", and step 5: "without losing the history chain."

    The successor **inherits the owner and category** and starts ``pending``
    regardless of what the predecessor's verdict was. That last part is the
    point of replacement: a re-scanned passport is a different artefact, and
    carrying a verified verdict across would mean a file nobody looked at was
    marked as reviewed.

    The predecessor keeps its bytes, its verdict, its notes, and its place in the
    chain. Nothing about it is rewritten except the two columns that record it
    was superseded.
    """
    assert_writable(uploaded_file)
    if not uploaded_file.is_current:
        raise AlreadySupersededError("This file has already been replaced. Replace the current version instead.")

    original_filename, content_type = validate_upload(upload)
    checksum = compute_checksum(upload)

    owner = {uploaded_file.owner_type: getattr(uploaded_file, uploaded_file.owner_type)}
    successor = UploadedFile(
        **owner,
        category=uploaded_file.category,
        upload_source=uploaded_file.upload_source,
        notes=normalize_unicode(notes) if notes else "",
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=upload.size,
        checksum_sha256=checksum,
        version_number=uploaded_file.version_number + 1,
        replaces=uploaded_file,
        uploaded_by=actor,
    )
    successor.file = upload
    successor.save()

    uploaded_file.superseded_at = timezone.now()
    uploaded_file.superseded_by = actor
    uploaded_file.save(update_fields=["superseded_at", "superseded_by", "updated_at"])

    _record(
        action=UploadedFilesAuditAction.FILE_REPLACED,
        actor=actor,
        uploaded_file=successor,
        summary=(
            f"File '{uploaded_file.original_filename}' replaced by "
            f"'{successor.original_filename}' (v{successor.version_number})."
        ),
        changes={"version_number": {"from": uploaded_file.version_number, "to": successor.version_number}},
        metadata={
            "replaces_id": str(uploaded_file.id),
            "checksum_sha256": successor.checksum_sha256,
        },
        ip_address=ip_address,
    )
    return successor


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


@transaction.atomic
def update_file(
    *,
    actor: Any,
    uploaded_file: UploadedFile,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> UploadedFile:
    """Correct a file's category or notes. Nothing else is editable.

    A no-op update writes no audit event — returning the empty change map is
    what keeps a PATCH that changed nothing from appearing in the history as an
    edit.
    """
    assert_writable(uploaded_file)
    fields = _normalize_text(dict(fields), ("notes",))
    assert_fields_mutable(fields)

    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(uploaded_file, name)
        if previous == value:
            continue
        changes[name] = {"from": str(previous), "to": str(value)}
        setattr(uploaded_file, name, value)

    if changes:
        uploaded_file.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=UploadedFilesAuditAction.FILE_UPDATED,
            actor=actor,
            uploaded_file=uploaded_file,
            summary=f"File '{uploaded_file.original_filename}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return uploaded_file


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@transaction.atomic
def review_file(
    *,
    actor: Any,
    uploaded_file: UploadedFile,
    status: str,
    reason: str = "",
    ip_address: str | None = None,
) -> UploadedFile:
    """Record a human verdict on a file: verified or rejected.

    ``concepts/uploaded_files.txt`` lifecycle step 3. Admin only — the uploader
    must not be the reviewer, or the field records who uploaded it rather than
    anyone's judgement (see ``access.py``).

    **Rejecting requires a reason; verifying does not.** A rejection is the
    verdict someone will have to answer for later — "why was this refused" must
    be answerable from the record rather than from someone remembering.
    Re-verifying a previously rejected file clears the old reason, so a stale
    refusal never sits under a current acceptance.

    A verdict may be revised. There is no lock, deliberately: a reviewer who
    rejects the wrong file must be able to correct it, and the audit log carries
    the sequence.
    """
    assert_writable(uploaded_file)
    if status not in REVIEWABLE_STATUSES:
        raise InvalidVerificationStatusError(f"'{status}' is not a verdict this action can set.")
    if status == VerificationStatus.REJECTED and not (reason or "").strip():
        raise ReasonRequiredError("Rejecting a file requires a reason.")

    previous = uploaded_file.verification_status
    uploaded_file.verification_status = status
    uploaded_file.rejection_reason = normalize_unicode(reason) if status == VerificationStatus.REJECTED else ""
    uploaded_file.reviewed_at = timezone.now()
    uploaded_file.reviewed_by = actor
    uploaded_file.save(
        update_fields=["verification_status", "rejection_reason", "reviewed_at", "reviewed_by", "updated_at"]
    )

    _record(
        action=UploadedFilesAuditAction.FILE_REVIEWED,
        actor=actor,
        uploaded_file=uploaded_file,
        summary=f"File '{uploaded_file.original_filename}' moved from {previous} to {status}.",
        reason=reason,
        changes={"verification_status": {"from": previous, "to": status}},
        ip_address=ip_address,
    )
    return uploaded_file


# ---------------------------------------------------------------------------
# Archive and restore
# ---------------------------------------------------------------------------


@transaction.atomic
def archive_file(
    *,
    actor: Any,
    uploaded_file: UploadedFile,
    reason: str,
    ip_address: str | None = None,
) -> UploadedFile:
    """Retire a file from active work without deleting anything.

    The reason is mandatory, matching ``documents``: archived files are kept
    forever, so "why is this one archived" has to be answerable from the record.

    **Archiving does not touch the version chain.** An archived v1 is still v1
    and still the predecessor of v2; ``is_archived`` and ``is_current`` answer
    different questions and are kept independent on purpose. The bytes stay on
    disk and the file stays downloadable — this is a lifecycle state, not a
    tombstone.
    """
    if uploaded_file.is_archived:
        raise AlreadyArchivedError("This file is already archived.")
    if not (reason or "").strip():
        raise ReasonRequiredError("Archiving a file requires a reason.")

    uploaded_file.archive_reason = normalize_unicode(reason)
    uploaded_file.archived_at = timezone.now()
    uploaded_file.archived_by = actor
    uploaded_file.save(update_fields=["archive_reason", "archived_at", "archived_by", "updated_at"])

    _record(
        action=UploadedFilesAuditAction.FILE_ARCHIVED,
        actor=actor,
        uploaded_file=uploaded_file,
        summary=f"File '{uploaded_file.original_filename}' archived.",
        reason=reason,
        changes={"archived": {"from": "false", "to": "true"}},
        ip_address=ip_address,
    )
    return uploaded_file


@transaction.atomic
def restore_file(
    *,
    actor: Any,
    uploaded_file: UploadedFile,
    note: str = "",
    ip_address: str | None = None,
) -> UploadedFile:
    """Return an archived file to active work.

    All three archive columns are cleared, so the record carries no trace of
    having been archived — the audit log carries that, which is the division
    every other app in this project uses: denormalized fields are *current
    state*, the append-only log is *history*.
    """
    if not uploaded_file.is_archived:
        raise NotArchivedError("This file is not archived.")

    uploaded_file.archive_reason = ""
    uploaded_file.archived_at = None
    uploaded_file.archived_by = None
    uploaded_file.save(update_fields=["archive_reason", "archived_at", "archived_by", "updated_at"])

    _record(
        action=UploadedFilesAuditAction.FILE_RESTORED,
        actor=actor,
        uploaded_file=uploaded_file,
        summary=f"File '{uploaded_file.original_filename}' restored.",
        reason=note,
        changes={"archived": {"from": "true", "to": "false"}},
        ip_address=ip_address,
    )
    return uploaded_file


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def record_download(*, actor: Any, uploaded_file: UploadedFile, ip_address: str | None = None) -> None:
    """Append an audit event for a file download.

    **The only read in this project that writes an audit event.** Every other
    list and retrieve endpoint is silent, and this one is not, because this is
    where a passport scan actually leaves the system.
    ``concepts/project_overview.txt``: "Broad access, exports, file replacement,
    and sensitive actions must be reviewable." A download is an export of one
    file.

    Deliberately **not** ``@transaction.atomic`` and deliberately not inside the
    response: the event is written before the file is streamed, so a client that
    aborts mid-transfer still leaves the record that it asked.
    """
    _record(
        action=UploadedFilesAuditAction.FILE_DOWNLOADED,
        actor=actor,
        uploaded_file=uploaded_file,
        summary=f"File '{uploaded_file.original_filename}' downloaded.",
        metadata={"size_bytes": uploaded_file.size_bytes},
        ip_address=ip_address,
    )
