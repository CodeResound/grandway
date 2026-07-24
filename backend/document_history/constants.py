"""Enums, size caps, error codes, and audit-action names for the document_history app.

Two ideas govern this module and every enum in it.

**A snapshot is not an event.** ``concepts/document_history.txt`` names them as
two separate core entities, and the distinction is load-bearing: a reprint is
new *activity* against an existing frozen body, not a new body. Modelling them
as one row would force every reprint to duplicate a bank statement's entire
transaction array, and would make "which version was actually issued" ambiguous.

**Nothing here is ever rewritten.** There is no status, no lifecycle, and no
edit or delete action — hence no lifecycle enum. The only enum is
``PrintEventType``, which classifies *why* an event exists.
"""

from django.db import models


class PrintEventType(models.TextChoices):
    """What produced a print event.

    ``concepts/document_history.txt`` — "The timeline should make reprints and
    recoveries easy to distinguish from original first captures." That sentence
    is the whole reason this enum exists: without it the timeline is an
    undifferentiated list of times and actors, and staff cannot answer "was this
    the version we issued, or a later reprint of it".
    """

    CAPTURE = "capture", "Capture"
    REPRINT = "reprint", "Reprint"
    RECOVERY = "recovery", "Recovery"


#: Maximum serialized size of ``render_context``, in bytes.
#:
#: Mirrors ``documents.MAX_CONTENT_BYTES`` at the same 256 KiB, and is declared
#: here rather than imported: a cross-app constant import is an undocumented
#: runtime coupling (§4), and the two caps govern different payloads that may
#: legitimately diverge later. ``content`` needs no second check — it was
#: already capped by ``documents`` on the way in, and this app copies it rather
#: than accepting it from a client.
MAX_RENDER_CONTEXT_BYTES: int = 256 * 1024

#: Fields a recovery pushes back into the working document.
#:
#: Exactly what the snapshot froze and ``documents``' ``update_document`` will
#: accept. Three things are deliberately absent:
#:
#: * ``applicant``, ``family``, ``template_key`` — immutable in ``documents``,
#:   and identical here by construction (a snapshot of a document can only
#:   carry that document's own family).
#: * ``status`` — recovering a body is not a judgement that the result is ready.
#: * ``notes`` — the working annotation staff keep *about* a document, never
#:   part of what was issued. The snapshot does not freeze it, so a recovery
#:   cannot clobber a note written after the print.
RECOVERABLE_FIELDS: tuple[str, ...] = ("label", "content")


class DocumentHistoryAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    SNAPSHOT_CAPTURED = "snapshot_captured"
    SNAPSHOT_REPRINTED = "snapshot_reprinted"
    SNAPSHOT_RECOVERED = "snapshot_recovered"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "document_history"

#: ``audit.AuditEvent.entity_type`` value. The snapshot is the entity a reader
#: cares about; a print event is always reached through the snapshot it names.
AUDIT_ENTITY_SNAPSHOT = "document_snapshot"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the document_history app (§7)."""

    ACTOR_FORBIDDEN = "DOCUMENT_HISTORY_ACTOR_FORBIDDEN"

    DOCUMENT_NOT_FOUND = "DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND"
    SNAPSHOT_NOT_FOUND = "DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND"

    RENDER_CONTEXT_INVALID = "DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID"
    RENDER_CONTEXT_TOO_LARGE = "DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE"

    DOCUMENT_NOT_EDITABLE = "DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE"
    CONTENT_TOO_LARGE = "DOCUMENT_HISTORY_CONTENT_TOO_LARGE"
    SNAPSHOT_IMMUTABLE = "DOCUMENT_HISTORY_SNAPSHOT_IMMUTABLE"
