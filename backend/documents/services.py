"""Business logic for the documents app.

Services receive already-validated data, own every rule that spans more than one
field, and return model instances — never HTTP responses.

Two rules here are load-bearing and easy to break by accident:

1. **``content`` is stored verbatim.** Nothing in this module computes, injects,
   normalizes, reorders, or strips anything inside the document body. Running
   balances, debit/credit totals, closing balances, the automatic interest and
   tax rows, and amount-in-words are all frontend concerns
   (``concepts/documents.txt`` — "Document input data"). Unknown keys are
   preserved because a template the backend has never heard of may depend on
   them.
2. **``content`` never reaches the audit log.** It is arbitrarily large and
   routinely holds bank balances, account numbers, and transaction histories.
   §17 forbids logging that. The history records that the body changed and who
   changed it, never what it said.
"""

from __future__ import annotations

import json
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from django.utils import timezone

from documents.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_DOCUMENT,
    CONTENT_CHANGE_MARKER,
    FAMILY_SLUG_PREFIX,
    FAMILY_SLUG_SUFFIX,
    MAX_CONTENT_BYTES,
    SELECTABLE_STATUSES,
    DocumentAuditAction,
    DocumentStatus,
)
from documents.exceptions import (
    ArchiveReasonRequiredError,
    ContentInvalidError,
    ContentTooLargeError,
    DocumentAlreadyArchivedError,
    DocumentNotArchivedError,
    DocumentNotEditableError,
    InvalidStatusTransitionError,
    OwnerRequiredError,
    TemplateKeyInvalidError,
)
from documents.models import Document

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}

#: Fields fixed at creation. What a document *is* — whose it is, and which
#: template renders it — cannot change, because changing either would turn one
#: record into a different document while keeping its id and its history.
IMMUTABLE_FIELDS: frozenset[str] = frozenset({"applicant", "family", "template_key"})


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    document: Document,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one document audit event. Never pass the document body."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=AUDIT_ENTITY_DOCUMENT,
        entity_id=str(document.id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
        source="api",
    )


def _diff_for_audit(instance: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply ``fields`` to ``instance`` and return an audit-safe change map.

    Identical to the ``_diff`` helper the other apps use, with one exception
    that is the whole reason it is written out here rather than copied: the
    document body is replaced by a marker. ``content`` may hold an applicant's
    bank balance and transaction history, and the audit log is readable by every
    Admin and Superadmin through the ``audit`` app — a change map carrying the
    old and new body would leak it there (§17).

    Returning the empty dict when nothing moved is what keeps a no-op PATCH
    from writing a misleading "document updated" event into the history.
    """
    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(instance, name)
        if previous == value:
            continue
        if name == "content":
            changes[name] = {"from": CONTENT_CHANGE_MARKER, "to": CONTENT_CHANGE_MARKER}
        else:
            changes[name] = {"from": str(previous), "to": str(value)}
        setattr(instance, name, value)
    return changes


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


def assert_owner_declared(applicant: Any, standalone_purpose: str) -> None:
    """A document must say whose it is, one way or the other.

    ``concepts/documents.txt``: a standalone document "must still say who owns
    or commissioned it". A null applicant with an empty purpose is a record
    nobody can account for.
    """
    if applicant is None and not (standalone_purpose or "").strip():
        raise OwnerRequiredError(
            "A document must belong to an applicant, or state its standalone purpose.",
        )


def assert_template_key_matches_family(family: str, template_key: str) -> None:
    """The template slug and the family must describe the same thing.

    Checked as a prefix — and, for the two bank families that share the
    ``bank-`` prefix, a suffix as well. A mismatch means the client sent a
    template and a family chosen from different pickers, which is a UI bug
    rather than user error.
    """
    prefix = FAMILY_SLUG_PREFIX.get(family)
    if prefix and not template_key.startswith(prefix):
        raise TemplateKeyInvalidError(
            f"A '{family}' document's template key must start with '{prefix}'.",
        )

    suffix = FAMILY_SLUG_SUFFIX.get(family)
    if suffix and not template_key.endswith(suffix):
        raise TemplateKeyInvalidError(
            f"A '{family}' document's template key must end with '{suffix}'.",
        )


def assert_content_storable(content: Any) -> None:
    """The body must be a JSON object within the size cap.

    These are the only two things the backend checks about ``content``. It does
    **not** validate the shape against the template: there are 53 of them, every
    one is an open shape required to preserve unknown keys, and the authoritative
    per-template contract lives with the frontend that renders it. Enforcing a
    guessed shape here would reject valid documents.
    """
    if not isinstance(content, dict):
        raise ContentInvalidError("Document content must be a JSON object.")

    size = len(json.dumps(content, separators=(",", ":")).encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise ContentTooLargeError(
            f"Document content is {size} bytes; the maximum is {MAX_CONTENT_BYTES}.",
        )


def assert_editable(document: Document) -> None:
    """An archived document must be restored before it can change again."""
    if not document.is_editable:
        raise DocumentNotEditableError("This document is archived; restore it before editing.")


# ---------------------------------------------------------------------------
# Creation and editing
# ---------------------------------------------------------------------------


@transaction.atomic
def create_document(
    *,
    actor: Any,
    applicant: Any,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> Document:
    """Create the editable working record staff will fill in.

    A document is usable from the moment it exists: `content` defaults to an
    empty object, because the workspace is opened before anything is typed into
    it.
    """
    standalone_purpose = data.get("standalone_purpose", "")
    assert_owner_declared(applicant, standalone_purpose)
    assert_template_key_matches_family(data["family"], data["template_key"])
    assert_content_storable(data.get("content", {}))

    document = Document.objects.create(
        applicant=applicant,
        created_by=actor,
        status=DocumentStatus.DRAFT,
        **data,
    )
    _record(
        action=DocumentAuditAction.DOCUMENT_CREATED,
        actor=actor,
        document=document,
        summary=f"Document '{document.label}' created.",
        metadata={
            "family": document.family,
            "template_key": document.template_key,
            "is_standalone": document.is_standalone,
            "applicant_id": str(applicant.id) if applicant else None,
        },
        ip_address=ip_address,
    )
    return document


@transaction.atomic
def update_document(
    *,
    actor: Any,
    document: Document,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Document:
    """Save the workspace — the label, the body, the notes.

    Ownership, family, template key, and status are all out of reach here.
    The first three are what the document *is*; status moves through its own
    actions, which record who acted and why.
    """
    assert_editable(document)

    if "content" in fields:
        assert_content_storable(fields["content"])
    if "standalone_purpose" in fields:
        assert_owner_declared(document.applicant, fields["standalone_purpose"])

    changes = _diff_for_audit(document, fields)
    if changes:
        document.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=DocumentAuditAction.DOCUMENT_UPDATED,
            actor=actor,
            document=document,
            summary="Document updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return document


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@transaction.atomic
def change_status(
    *,
    actor: Any,
    document: Document,
    status: str,
    ip_address: str | None = None,
) -> Document:
    """Move a document between its working statuses.

    ``archived`` is unreachable here: archiving carries a mandatory reason and
    is its own action, so that a document is never retired without one.
    """
    assert_editable(document)
    if status not in SELECTABLE_STATUSES:
        raise InvalidStatusTransitionError("This status cannot be set directly; use the archive action.")

    previous = document.status
    if previous == status:
        return document

    document.status = status
    document.save(update_fields=["status", "updated_at"])
    _record(
        action=DocumentAuditAction.DOCUMENT_STATUS_CHANGED,
        actor=actor,
        document=document,
        summary=f"Status changed from {previous} to {status}.",
        changes={"status": {"from": previous, "to": status}},
        ip_address=ip_address,
    )
    return document


@transaction.atomic
def archive_document(
    *,
    actor: Any,
    document: Document,
    reason: str,
    ip_address: str | None = None,
) -> Document:
    """Retire a document from active work without deleting anything.

    The reason is mandatory. Archived documents are kept forever, so "why is
    this one archived" has to be answerable from the record rather than from
    someone remembering.
    """
    if document.is_archived:
        raise DocumentAlreadyArchivedError("This document is already archived.")
    if not (reason or "").strip():
        raise ArchiveReasonRequiredError("Archiving a document requires a reason.")

    previous = document.status
    document.status = DocumentStatus.ARCHIVED
    document.archive_reason = normalize_unicode(reason)
    document.archived_at = timezone.now()
    document.archived_by = actor
    document.save(update_fields=["status", "archive_reason", "archived_at", "archived_by", "updated_at"])

    _record(
        action=DocumentAuditAction.DOCUMENT_ARCHIVED,
        actor=actor,
        document=document,
        summary=f"Document '{document.label}' archived.",
        reason=reason,
        changes={"status": {"from": previous, "to": DocumentStatus.ARCHIVED}},
        ip_address=ip_address,
    )
    return document


@transaction.atomic
def restore_document(
    *,
    actor: Any,
    document: Document,
    ip_address: str | None = None,
) -> Document:
    """Return an archived document to active work.

    Always to ``draft``, never to ``ready`` — whoever archived it may have done
    so precisely because it was not ready, and a restore should not re-assert a
    judgement nobody made. Clears the archive state; the archiving itself stays
    in the audit log.
    """
    if not document.is_archived:
        raise DocumentNotArchivedError("Only an archived document can be restored.")

    document.status = DocumentStatus.DRAFT
    document.archive_reason = ""
    document.archived_at = None
    document.archived_by = None
    document.save(update_fields=["status", "archive_reason", "archived_at", "archived_by", "updated_at"])

    _record(
        action=DocumentAuditAction.DOCUMENT_RESTORED,
        actor=actor,
        document=document,
        summary=f"Document '{document.label}' restored to draft.",
        changes={"status": {"from": DocumentStatus.ARCHIVED, "to": DocumentStatus.DRAFT}},
        ip_address=ip_address,
    )
    return document
