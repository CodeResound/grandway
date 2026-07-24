"""Business logic for the document_history app.

Services receive already-validated data, own every rule that spans more than one
field, and return model instances — never HTTP responses.

Four rules here are load-bearing and easy to break by accident:

1. **The body is copied, never accepted.** ``create_snapshot`` reads
   ``document.content`` off the record itself. Nothing in a request payload can
   influence what a snapshot claims the document said. A snapshot that could
   disagree with its own document is worthless as history.
2. **The chain is serialized on the parent row.** ``version_number`` is
   allocated under ``select_for_update()`` on the ``Document``, so two
   simultaneous prints produce versions 4 and 5 rather than one
   ``IntegrityError``. The unique constraint is the backstop, not the mechanism.
3. **Recovery writes forward, never backward.** It pushes the frozen fields into
   the *working document* through ``documents.services.update_document`` and
   leaves the snapshot untouched — "The historical snapshot is not altered by
   recovery" (``concepts/document_history.txt`` flow 3).
4. **Neither ``content`` nor ``render_context`` ever reaches the audit log.**
   Both are arbitrarily large and routinely hold bank balances, account numbers,
   and transaction histories; ``render_context`` additionally holds the computed
   closing balances. §17 forbids logging that. Events record *that* a snapshot
   was taken and by whom, never what it said.
"""

from __future__ import annotations

import json
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from documents import services as document_services
from documents.models import Document

from document_history.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_SNAPSHOT,
    MAX_RENDER_CONTEXT_BYTES,
    RECOVERABLE_FIELDS,
    DocumentHistoryAuditAction,
    PrintEventType,
)
from document_history.exceptions import (
    RenderContextInvalidError,
    RenderContextTooLargeError,
)
from document_history.models import DocumentSnapshot, PrintEvent
from document_history.selectors import get_latest_version_number

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    snapshot: DocumentSnapshot,
    summary: str = "",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one document-history audit event.

    Never pass ``content`` or ``render_context`` in ``metadata``. The audit log
    is readable by every Admin and Superadmin through the ``audit`` app, and
    both fields carry personal financial data (§17).
    """
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=AUDIT_ENTITY_SNAPSHOT,
        entity_id=str(snapshot.id),
        reason=reason,
        summary=summary,
        metadata=metadata or {},
        ip_address=ip_address,
        source="api",
    )


def _event_metadata(snapshot: DocumentSnapshot, event_type: str) -> dict[str, Any]:
    """The audit-safe description of a snapshot. Identity and position only."""
    return {
        "document_id": str(snapshot.document_id),
        "version_number": snapshot.version_number,
        "template_key": snapshot.template_key,
        "event_type": event_type,
    }


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


def assert_render_context_storable(render_context: Any) -> None:
    """The render context must be a JSON object within the size cap.

    These are the only two things the backend checks about it. It does **not**
    validate the shape: the render context is whatever the frontend needed to
    reproduce one of 42 templates, its keys differ per template family, and the
    authoritative per-template contract lives with the renderer. Enforcing a
    guessed shape here would reject valid prints — the same call ``documents``
    made about ``content``.
    """
    if not isinstance(render_context, dict):
        raise RenderContextInvalidError("Render context must be a JSON object.")

    size = len(json.dumps(render_context, separators=(",", ":")).encode("utf-8"))
    if size > MAX_RENDER_CONTEXT_BYTES:
        raise RenderContextTooLargeError(
            f"Render context is {size} bytes; the maximum is {MAX_RENDER_CONTEXT_BYTES}.",
        )


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


@transaction.atomic
def create_snapshot(
    *,
    actor: Any,
    document: Document,
    render_context: dict[str, Any] | None = None,
    capture_note: str = "",
    ip_address: str | None = None,
) -> DocumentSnapshot:
    """Freeze the document as it stands right now, and record the capture.

    Writes two rows: the snapshot and its ``capture`` print event. They are one
    transaction because a snapshot nobody can see in the timeline, or a timeline
    entry pointing at nothing, are both worse than neither.

    **An archived document may be captured.** A freeze is a read — it changes
    nothing about the working record — and staff have a legitimate need to print
    a superseded document. Recovery is the operation that respects the archive
    lock, because that one writes.
    """
    render_context = render_context or {}
    assert_render_context_storable(render_context)

    # Serialize the chain on the parent row. Re-reading the document under the
    # lock also guarantees the body copied below is the committed one, not a
    # value another request has since replaced.
    locked = Document.objects.select_for_update().get(pk=document.pk)
    version_number = get_latest_version_number(str(locked.pk)) + 1

    snapshot = DocumentSnapshot.objects.create(
        document=locked,
        version_number=version_number,
        family=locked.family,
        template_key=locked.template_key,
        label=locked.label,
        # Copied from the record, never from the request. See the module
        # docstring, rule 1.
        content=locked.content,
        render_context=render_context,
        capture_note=normalize_unicode(capture_note) if capture_note else "",
        captured_by=actor,
    )
    _create_print_event(
        actor=actor,
        snapshot=snapshot,
        event_type=PrintEventType.CAPTURE,
        note=snapshot.capture_note,
    )
    _record(
        action=DocumentHistoryAuditAction.SNAPSHOT_CAPTURED,
        actor=actor,
        snapshot=snapshot,
        summary=f"Snapshot v{version_number} captured for '{snapshot.label}'.",
        reason=snapshot.capture_note,
        metadata=_event_metadata(snapshot, PrintEventType.CAPTURE),
        ip_address=ip_address,
    )
    return snapshot


def _create_print_event(
    *,
    actor: Any,
    snapshot: DocumentSnapshot,
    event_type: str,
    note: str = "",
) -> PrintEvent:
    """Append one print event against an existing snapshot.

    Private because every event in this app belongs to a named action — there is
    no "record an arbitrary event" use case, and exposing one would let a caller
    write a ``capture`` event with no snapshot behind it.
    """
    return PrintEvent.objects.create(
        snapshot=snapshot,
        document_id=snapshot.document_id,
        event_type=event_type,
        note=note,
        performed_by=actor,
    )


# ---------------------------------------------------------------------------
# Reprint
# ---------------------------------------------------------------------------


@transaction.atomic
def reprint_snapshot(
    *,
    actor: Any,
    snapshot: DocumentSnapshot,
    note: str = "",
    ip_address: str | None = None,
) -> PrintEvent:
    """Record that a past snapshot was printed again.

    Writes an event and **no new snapshot**: "A reprint is new activity, not a
    new body rewrite" (``concepts/document_history.txt`` flow 4). The frontend
    regenerates the output from the snapshot's own saved context, so nothing
    about the frozen body needs to be duplicated to reproduce it.
    """
    note = normalize_unicode(note) if note else ""
    event = _create_print_event(
        actor=actor,
        snapshot=snapshot,
        event_type=PrintEventType.REPRINT,
        note=note,
    )
    _record(
        action=DocumentHistoryAuditAction.SNAPSHOT_REPRINTED,
        actor=actor,
        snapshot=snapshot,
        summary=f"Snapshot v{snapshot.version_number} of '{snapshot.label}' reprinted.",
        reason=note,
        metadata=_event_metadata(snapshot, PrintEventType.REPRINT),
        ip_address=ip_address,
    )
    return event


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


@transaction.atomic
def recover_snapshot(
    *,
    actor: Any,
    snapshot: DocumentSnapshot,
    note: str = "",
    ip_address: str | None = None,
) -> Document:
    """Restore a frozen body into the working document, leaving history intact.

    The one cross-app write in this module (§4, §28 item 12). It calls
    ``documents.services.update_document`` rather than touching ``Document``
    directly, so the working record's own rules still apply in full — the
    archive lock, the size cap, and the redacted ``document_updated`` audit
    event all come from the app that owns them.

    Three consequences worth knowing:

    * Recovering into an **archived** document raises ``DocumentNotEditableError``
      from ``documents``. That is correct: the concept says recovery "should
      create a new working state", and an archived document has no working
      state until it is restored.
    * A **no-op** recovery — the body already matches — writes no
      ``document_updated`` event, because ``update_document`` suppresses
      unchanged saves. It still writes ``snapshot_recovered`` here: the action
      happened, and a timeline that hid it would be lying about what staff did.
    * The snapshot is **not** touched, and the recovery does **not** create a new
      snapshot. The next print does that, and it will carry the recovered body
      as a new version — which is exactly the audit trail the concept asks for.
    """
    note = normalize_unicode(note) if note else ""

    # Re-read the document under a row lock rather than using
    # ``snapshot.document``. That attribute is whatever instance was cached when
    # the snapshot was loaded, and it may be arbitrarily stale — a recovery
    # driven from it would diff the frozen body against an out-of-date copy,
    # decide nothing changed, and silently skip both the write and the archive
    # check. The lock additionally serializes a recovery against a concurrent
    # capture of the same document.
    document = Document.objects.select_for_update().get(pk=snapshot.document_id)

    document = document_services.update_document(
        actor=actor,
        document=document,
        fields={field: getattr(snapshot, field) for field in RECOVERABLE_FIELDS},
        ip_address=ip_address,
    )
    _create_print_event(
        actor=actor,
        snapshot=snapshot,
        event_type=PrintEventType.RECOVERY,
        note=note,
    )
    _record(
        action=DocumentHistoryAuditAction.SNAPSHOT_RECOVERED,
        actor=actor,
        snapshot=snapshot,
        summary=f"Snapshot v{snapshot.version_number} recovered into '{snapshot.label}'.",
        reason=note,
        metadata=_event_metadata(snapshot, PrintEventType.RECOVERY),
        ip_address=ip_address,
    )
    return document
