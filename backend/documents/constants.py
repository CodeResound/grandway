"""Enums, error codes, and audit-action names for the documents app.

The taxonomy here is deliberately split in two. ``DocumentFamily`` is the stable
*class* of a document and lives in the database as an enum; ``template_key`` is
the concrete template slug (``bank-vyas-statement``) and is a validated string,
not an enum. ``concepts/documents.txt`` — "Document type ... is the stable class
of the document, not the rendered instance" — describes exactly this split, and
its final open question asks for it outright.

The practical consequence: onboarding a new bank partner adds a row, not a
migration. When ``document_templates`` ships it takes ownership of the slug
registry, and that is an additive change rather than a breaking one to a shipped
42-value enum.
"""

from django.db import models


class DocumentFamily(models.TextChoices):
    """The stable class a document belongs to.

    Six values covering the frontend's 42 slugs. Bank documents split into two
    families rather than one because a statement and a certificate have
    different content shapes, different derived values, and different screens —
    treating them as one family would make ``family`` useless for the one thing
    it exists for, which is knowing what shape ``content`` is in.
    """

    STUDENT = "student", "Student"
    WODA = "woda", "WODA"
    LOR = "lor", "Letter of Recommendation"
    MOI = "moi", "Medium of Instruction"
    BANK_STATEMENT = "bank_statement", "Bank Statement"
    BANK_CERTIFICATE = "bank_certificate", "Bank Certificate"


#: The ``template_key`` prefix each family's slugs must carry, checked on write.
#: Bank families additionally require a matching suffix — see
#: ``services.assert_template_key_matches_family``.
FAMILY_SLUG_PREFIX: dict[str, str] = {
    DocumentFamily.STUDENT: "student-",
    DocumentFamily.WODA: "woda-",
    DocumentFamily.LOR: "lor-",
    DocumentFamily.MOI: "moi-",
    DocumentFamily.BANK_STATEMENT: "bank-",
    DocumentFamily.BANK_CERTIFICATE: "bank-",
}

#: Suffix required for the two bank families, which share the ``bank-`` prefix.
FAMILY_SLUG_SUFFIX: dict[str, str] = {
    DocumentFamily.BANK_STATEMENT: "-statement",
    DocumentFamily.BANK_CERTIFICATE: "-certificate",
}


class DocumentStatus(models.TextChoices):
    """Where a document stands in its working lifecycle.

    Three values, not the concept's five. ``active`` is dropped as a synonym for
    ``draft``, and ``printed`` is **still** deliberately absent, now for a
    different reason than when this app shipped. Print snapshots exist —
    ``document_history`` was built — but capturing one deliberately does not
    touch this field. "Has been printed" is derivable from the existence of a
    snapshot, and duplicating it here would create a second, denormalized
    answer that can drift from the first. A client that wants it asks
    ``document_history`` for the version chain.

    The frontend's ``submitted`` is mapped to ``READY``. Nothing in Grandway
    submits a document anywhere — there is no review step and no recipient — so
    the name would describe a workflow that does not exist.
    """

    DRAFT = "draft", "Draft"
    READY = "ready", "Ready"
    ARCHIVED = "archived", "Archived"


#: Statuses a user may move between with the status action. ``ARCHIVED`` is
#: absent: archiving carries a mandatory reason and is its own endpoint.
SELECTABLE_STATUSES: tuple[str, ...] = (
    DocumentStatus.DRAFT,
    DocumentStatus.READY,
)

#: Status a restored document returns to. Never ``ready`` — whoever archived it
#: may have done so precisely because it was not ready.
DEFAULT_RESTORE_STATUS: str = DocumentStatus.DRAFT


#: Maximum serialized size of ``content``, in bytes.
#:
#: A bank statement carries an unbounded transaction array, so this is the only
#: thing standing between one document and an unusable row. 256 KiB is roughly
#: a two-thousand-row statement — far beyond any real document, and small
#: enough that a runaway client is caught early.
MAX_CONTENT_BYTES: int = 256 * 1024


class DocumentAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    DOCUMENT_CREATED = "document_created"
    DOCUMENT_UPDATED = "document_updated"
    DOCUMENT_STATUS_CHANGED = "document_status_changed"
    DOCUMENT_ARCHIVED = "document_archived"
    DOCUMENT_RESTORED = "document_restored"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "documents"

#: ``audit.AuditEvent.entity_type`` value.
AUDIT_ENTITY_DOCUMENT = "document"

#: Placeholder written into an audit ``changes`` map in place of ``content``.
#:
#: The document body is arbitrarily large and routinely holds personal financial
#: data — bank balances, account numbers, transaction histories. §17 forbids
#: logging it. The audit trail records *that* it changed and who changed it,
#: never what it said.
CONTENT_CHANGE_MARKER = "<changed>"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the documents app (§7)."""

    ACTOR_FORBIDDEN = "DOCUMENTS_ACTOR_FORBIDDEN"

    DOCUMENT_NOT_FOUND = "DOCUMENTS_DOCUMENT_NOT_FOUND"
    APPLICANT_NOT_FOUND = "DOCUMENTS_APPLICANT_NOT_FOUND"

    OWNER_REQUIRED = "DOCUMENTS_OWNER_REQUIRED"
    OWNERSHIP_IMMUTABLE = "DOCUMENTS_OWNERSHIP_IMMUTABLE"
    STATUS_IMMUTABLE = "DOCUMENTS_STATUS_IMMUTABLE"
    TEMPLATE_KEY_INVALID = "DOCUMENTS_TEMPLATE_KEY_INVALID"
    CONTENT_INVALID = "DOCUMENTS_CONTENT_INVALID"
    CONTENT_TOO_LARGE = "DOCUMENTS_CONTENT_TOO_LARGE"

    DOCUMENT_NOT_EDITABLE = "DOCUMENTS_DOCUMENT_NOT_EDITABLE"
    STATUS_INVALID_TRANSITION = "DOCUMENTS_STATUS_INVALID_TRANSITION"
    ARCHIVE_REASON_REQUIRED = "DOCUMENTS_ARCHIVE_REASON_REQUIRED"
    DOCUMENT_ALREADY_ARCHIVED = "DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED"
    DOCUMENT_NOT_ARCHIVED = "DOCUMENTS_DOCUMENT_NOT_ARCHIVED"
