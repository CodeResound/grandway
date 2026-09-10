"""Business logic for the document_templates app.

Services receive already-validated data, own every rule that spans more than one
field, and return model instances — never HTTP responses.

Three rules here are load-bearing:

1. **The key/family agreement rule is imported, not reimplemented.**
   ``documents.services.assert_template_key_matches_family`` is the single
   definition of "does this slug belong to this family". A second copy here
   could accept a key ``documents`` would reject, which would let an Admin
   publish a catalogue row no document could ever be created from.
2. **The key is immutable.** Documents store it as a plain string with no
   foreign key behind it, so renaming one here would orphan every document that
   used it, silently and with nothing in the database to notice.
3. **Nothing is deleted.** There is no delete service and no delete endpoint.
   A signatory frozen into a snapshot's ``render_context`` must stay resolvable
   forever, and a template a document points at must keep its label readable.
"""

from __future__ import annotations

from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode
from django.db import transaction
from documents.services import assert_template_key_matches_family

from document_templates.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_SIGNATORY,
    AUDIT_ENTITY_TEMPLATE,
    SELECTABLE_STATUSES,
    SIGNATURE_IMAGE_EXTENSIONS,
    DocumentTemplatesAuditAction,
)
from document_templates.exceptions import (
    InvalidStatusTransitionError,
    SignatureNotAnImageError,
    TemplateKeyAlreadyExistsError,
    TemplateKeyImmutableError,
)
from document_templates.models import DocumentTemplate, Signatory
from document_templates.selectors import get_current_signature_file, get_template_by_key

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}

#: Fields fixed at creation on a template. Only one, and it is the identity
#: every document points at by string.
IMMUTABLE_TEMPLATE_FIELDS: frozenset[str] = frozenset({"key"})


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    entity_type: str,
    entity_id: str,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one audit event.

    **Nothing in this app is redacted**, unlike ``documents`` (which replaces
    its body with a marker) and ``document_history`` (which drops two whole
    JSON columns). There is no applicant data here to protect: a signatory is a
    staff member's name and a link to their signature, and a template is a slug
    and a label. Full before/after values are safe to record and are the point
    of the log.
    """
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
        source="api",
    )


def _diff(instance: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply ``fields`` to ``instance`` and return the change map.

    Returning the empty dict when nothing moved is what keeps a no-op PATCH
    from writing a misleading "updated" event into the history.
    """
    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(instance, name)
        if previous == value:
            continue
        changes[name] = {"from": str(previous), "to": str(value)}
        setattr(instance, name, value)
    return changes


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


def apply_name_localization(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the signatory's name (§39.2).

    Mirrors ``applicants.services``. The romanized form is a search aid, never
    displayed and never required in a write serializer — but a caller that
    supplies one explicitly keeps it, because a transliteration an operator
    corrected by hand ("Griha" over the generated "grha") should not be
    overwritten on the next save.
    """
    if data.get("name"):
        data["name"] = normalize_unicode(data["name"])
    return data


def assert_status_selectable(status: str) -> None:
    """The status action may only set a value in the enum."""
    if status not in SELECTABLE_STATUSES:
        raise InvalidStatusTransitionError(f"'{status}' is not a valid status.")


def assert_key_available(key: str) -> None:
    """A template key is the catalogue's identity and may claim only one row."""
    if get_template_by_key(key) is not None:
        raise TemplateKeyAlreadyExistsError(f"A template with key '{key}' already exists.")


# ---------------------------------------------------------------------------
# Signatories
# ---------------------------------------------------------------------------


@transaction.atomic
def create_signatory(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> Signatory:
    """Add a person to the signature library.

    Created as ``draft`` by default: a signatory with no signature image yet is
    not one a certificate should be able to name, and requiring an explicit
    activation makes that a decision rather than an oversight.
    """
    data = apply_name_localization(dict(data))
    signatory = Signatory.objects.create(created_by=actor, **data)

    _record(
        action=DocumentTemplatesAuditAction.SIGNATORY_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_SIGNATORY,
        entity_id=str(signatory.id),
        summary=f"Signatory '{signatory.name}' created.",
        metadata={"status": signatory.status, "role": signatory.role},
        ip_address=ip_address,
    )
    return signatory


@transaction.atomic
def update_signatory(
    *,
    actor: Any,
    signatory: Signatory,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Signatory:
    """Correct a signatory's name, title, role, or signature image.

    ``status`` is out of reach here — it moves through its own action, which
    records the transition explicitly rather than burying it in a field diff.
    """
    fields = apply_name_localization(dict(fields))
    changes = _diff(signatory, fields)
    if changes:
        signatory.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=DocumentTemplatesAuditAction.SIGNATORY_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_SIGNATORY,
            entity_id=str(signatory.id),
            summary=f"Signatory '{signatory.name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return signatory


@transaction.atomic
def change_signatory_status(
    *,
    actor: Any,
    signatory: Signatory,
    status: str,
    note: str = "",
    ip_address: str | None = None,
) -> Signatory:
    """Move a signatory between draft, active, and inactive.

    Deactivating does **not** remove the signatory from documents or snapshots
    that already name them — those keep resolving, which is the whole reason
    this is a status rather than a delete. It removes them from the picker only.
    """
    assert_status_selectable(status)

    previous = signatory.status
    if previous == status and not note:
        return signatory

    signatory.status = status
    signatory.status_note = normalize_unicode(note) if note else ""
    signatory.save(update_fields=["status", "status_note", "updated_at"])

    _record(
        action=DocumentTemplatesAuditAction.SIGNATORY_STATUS_CHANGED,
        actor=actor,
        entity_type=AUDIT_ENTITY_SIGNATORY,
        entity_id=str(signatory.id),
        summary=f"Signatory '{signatory.name}' moved from {previous} to {status}.",
        reason=note,
        changes={"status": {"from": previous, "to": status}},
        ip_address=ip_address,
    )
    return signatory


def assert_signature_extension(upload: Any) -> None:
    """Refuse anything that is not an image, before the ledger ever sees it.

    The ledger accepts PDF, DOCX, and XLSX as well. None of them is a signature,
    and a 10 MB spreadsheet stored under a director's name would satisfy every
    check downstream of this one.

    Reads the filename only. The ledger's ``assert_content_matches_extension``
    then checks the leading bytes against that same extension, so a PDF renamed
    ``signature.png`` is refused there — this narrows *which* extensions are
    meaningful, and the ledger proves the bytes match the claim.
    """
    _, _, extension = (getattr(upload, "name", "") or "").rpartition(".")
    if extension.strip().lower() not in SIGNATURE_IMAGE_EXTENSIONS:
        raise SignatureNotAnImageError(
            f"A signature image must be one of: {', '.join(sorted(SIGNATURE_IMAGE_EXTENSIONS))}."
        )


@transaction.atomic
def set_signatory_signature(
    *,
    actor: Any,
    signatory: Signatory,
    upload: Any,
    notes: str = "",
    ip_address: str | None = None,
) -> Signatory:
    """Store or replace this signatory's signature image, and link it atomically.

    One call, two writes, one transaction: the bytes enter the file ledger owned
    by this signatory, and ``signature_file`` is re-pointed at the result. A
    caller must never have to do those two separately, because a file stored
    without the link renders nowhere and reads as a silent success.

    **Which ledger service runs is decided before dispatch, not by catching its
    errors.** ``get_current_signature_file`` returns the linked file only when it
    is neither archived nor superseded:

    * nothing usable → ``upload_file`` starts a fresh chain at v1;
    * a usable predecessor → ``replace_file`` supersedes it and the chain grows,
      so "what did this director's signature look like when we issued that
      certificate" stays answerable.

    An **archived** predecessor therefore starts a fresh chain rather than
    failing. Archiving is the removal gesture; if removal required an unarchive
    dance before a new signature could be added, replacing a departed signer's
    signature would take three calls including restoring the thing you just
    removed. An **already superseded** one does the same, rather than walking to
    the head of a chain this endpoint never linked.

    The consequence is that ``AlreadySupersededError`` and ``FileArchivedError``
    are unreachable from here **by construction** — deliberately, because neither
    is a sentence an operator replacing a signature should ever read.
    ``OwnerNotResolvedError`` and ``OwnerNotFoundError`` cannot be raised either:
    the owner is an instance the caller already resolved.

    ``category`` and ``upload_source`` are fixed here and never accepted from a
    client.

    Two audit events are written per call, and that is correct rather than
    duplication: the ledger records *bytes entered the ledger*, and this records
    *this signatory's signature changed*. Someone reading a signatory's history
    must not have to join to the file ledger to see that it happened.
    """
    # Function-local, and this is load-bearing rather than stylistic.
    # ``uploaded_files.services`` imports ``document_templates.selectors`` at
    # module level for its owner lookup, making these the project's first
    # bidirectional app pair. Deferring this direction to call time keeps the
    # module graph acyclic under any import order instead of merely happening to
    # terminate under the current one. Same shape as
    # ``checklists.services._resolve_evidence``.
    from uploaded_files.constants import FileCategory, UploadSource
    from uploaded_files.services import replace_file, upload_file

    assert_signature_extension(upload)
    notes = normalize_unicode(notes) if notes else ""

    predecessor = get_current_signature_file(signatory)
    if predecessor is not None:
        stored = replace_file(
            actor=actor,
            uploaded_file=predecessor,
            upload=upload,
            notes=notes,
            ip_address=ip_address,
        )
    else:
        stored = upload_file(
            actor=actor,
            upload=upload,
            data={
                "signatory": signatory.id,
                "category": FileCategory.SIGNATURE_IMAGE,
                "upload_source": UploadSource.STAFF_UPLOAD,
                "notes": notes,
            },
            ip_address=ip_address,
        )

    previous_id = signatory.signature_file_id
    signatory.signature_file = stored
    signatory.save(update_fields=["signature_file", "updated_at"])

    _record(
        action=DocumentTemplatesAuditAction.SIGNATORY_SIGNATURE_UPLOADED,
        actor=actor,
        entity_type=AUDIT_ENTITY_SIGNATORY,
        entity_id=str(signatory.id),
        summary=f"Signature image for '{signatory.name}' set to '{stored.original_filename}'.",
        changes={"signature_file": {"from": str(previous_id or ""), "to": str(stored.id)}},
        metadata={
            "file_id": str(stored.id),
            "version_number": stored.version_number,
            "original_filename": stored.original_filename,
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
        },
        ip_address=ip_address,
    )
    return signatory


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@transaction.atomic
def create_template(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> DocumentTemplate:
    """Register a slug in the catalogue.

    Two checks, and the second is borrowed: the key must be unique, and it must
    agree with its family by the **same** rule ``documents`` applies when a
    document is created against it. Publishing a catalogue row that no document
    could be created from would be worse than useless.
    """
    data = dict(data)
    assert_key_available(data["key"])
    assert_template_key_matches_family(data["family"], data["key"])

    template = DocumentTemplate.objects.create(created_by=actor, **data)

    _record(
        action=DocumentTemplatesAuditAction.TEMPLATE_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_TEMPLATE,
        entity_id=str(template.id),
        summary=f"Template '{template.key}' registered.",
        metadata={"key": template.key, "family": template.family, "status": template.status},
        ip_address=ip_address,
    )
    return template


@transaction.atomic
def update_template(
    *,
    actor: Any,
    template: DocumentTemplate,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> DocumentTemplate:
    """Edit a catalogue row's label, description, family, or picker position.

    ``key`` is refused outright rather than dropped: documents point at it as a
    plain string, so a client that renamed one and got 200 back would believe
    every document using it had followed along.
    """
    fields = dict(fields)
    if IMMUTABLE_TEMPLATE_FIELDS & set(fields):
        raise TemplateKeyImmutableError("A template's key cannot be changed after creation.")

    if "family" in fields:
        assert_template_key_matches_family(fields["family"], template.key)

    changes = _diff(template, fields)
    if changes:
        template.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=DocumentTemplatesAuditAction.TEMPLATE_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_TEMPLATE,
            entity_id=str(template.id),
            summary=f"Template '{template.key}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return template


@transaction.atomic
def change_template_status(
    *,
    actor: Any,
    template: DocumentTemplate,
    status: str,
    note: str = "",
    ip_address: str | None = None,
) -> DocumentTemplate:
    """Offer a template for new work, or retire it from the picker.

    ``concepts/document_templates.txt`` flow 4: "Retirement must not break old
    document records that already point at the template key." It cannot —
    ``documents`` never consults this table, so retiring a row changes exactly
    one thing: whether a client's picker still offers it.
    """
    assert_status_selectable(status)

    previous = template.status
    if previous == status and not note:
        return template

    template.status = status
    template.status_note = normalize_unicode(note) if note else ""
    template.save(update_fields=["status", "status_note", "updated_at"])

    _record(
        action=DocumentTemplatesAuditAction.TEMPLATE_STATUS_CHANGED,
        actor=actor,
        entity_type=AUDIT_ENTITY_TEMPLATE,
        entity_id=str(template.id),
        summary=f"Template '{template.key}' moved from {previous} to {status}.",
        reason=note,
        changes={"status": {"from": previous, "to": status}},
        ip_address=ip_address,
    )
    return template
