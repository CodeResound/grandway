"""Enums, error codes, and audit-action names for the document_templates app.

One idea governs this module: **this app stores what is offered, not what is
rendered.** The frontend owns the template code — the 53 slugs are a hardcoded
TypeScript union there, and the per-family content shapes are compiled-in types.
The catalogue here says which of those slugs an Admin may still pick and what to
call them; it does not and cannot describe how any of them draws itself.

That is why there is no version enum, no section vocabulary, and no field-hint
taxonomy. Each would be a guess at a schema no consumer reads.

``DocumentFamily`` is deliberately **not** redeclared here — see ``models.py``.
"""

from django.db import models


class LifecycleStatus(models.TextChoices):
    """Activation state, shared by both models in this app.

    ``concepts/document_templates.txt`` — "Whether a template or signatory is
    draft, active, or inactive. Active entries may be used by the document
    workspace; inactive ones remain visible for history and old snapshots but
    should not be offered for new work."

    The three values carry the whole lifecycle because nothing here is ever
    deleted: an entry a document or snapshot already points at must stay
    resolvable forever, so ``inactive`` is the terminal state rather than a
    tombstone.

    One enum for both models rather than two identical ones — §4 forbids
    duplicating enums, and a signatory and a template answer the same question
    ("may this be offered for new work?") with the same three answers.
    """

    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


#: Statuses reachable through the status action — all three.
#:
#: Unlike ``documents``, where ``archived`` is walled off behind its own
#: endpoint because it demands a reason, no transition here carries a mandatory
#: reason: deactivating a template is reversible, loses nothing, and breaks
#: no existing record. The optional ``status_note`` covers the "why".
SELECTABLE_STATUSES: tuple[str, ...] = (
    LifecycleStatus.DRAFT,
    LifecycleStatus.ACTIVE,
    LifecycleStatus.INACTIVE,
)


class DocumentTemplatesAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    SIGNATORY_CREATED = "signatory_created"
    SIGNATORY_UPDATED = "signatory_updated"
    SIGNATORY_STATUS_CHANGED = "signatory_status_changed"

    TEMPLATE_CREATED = "template_created"
    TEMPLATE_UPDATED = "template_updated"
    TEMPLATE_STATUS_CHANGED = "template_status_changed"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "document_templates"

#: ``audit.AuditEvent.entity_type`` values.
AUDIT_ENTITY_SIGNATORY = "signatory"
AUDIT_ENTITY_TEMPLATE = "document_template"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the document_templates app (§7)."""

    ACTOR_FORBIDDEN = "DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN"

    SIGNATORY_NOT_FOUND = "DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND"
    TEMPLATE_NOT_FOUND = "DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND"

    KEY_ALREADY_EXISTS = "DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS"
    KEY_IMMUTABLE = "DOCUMENT_TEMPLATES_KEY_IMMUTABLE"
    TEMPLATE_KEY_INVALID = "DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID"

    #: A ``PATCH`` carried ``status`` or ``status_note``. Named for immutability
    #: rather than for a transition, and matching ``documents``' equivalent,
    #: because **no transition in this app is ever invalid** — ``LifecycleStatus``
    #: allows every state from every state. An earlier draft called this
    #: ``STATUS_INVALID_TRANSITION``, which described a rule that does not exist.
    STATUS_IMMUTABLE = "DOCUMENT_TEMPLATES_STATUS_IMMUTABLE"

    #: The status action received a value outside the enum.
    #:
    #: **Unreachable over HTTP.** Both status serializers declare ``status`` as a
    #: ``ChoiceField``, so a bad value fails there with the project-wide
    #: ``VALIDATION_ERROR`` and never reaches ``services.assert_status_selectable``.
    #: Registered so the envelope is defined if a non-serializer caller is ever
    #: added; do not write client handling for it.
    STATUS_INVALID_TRANSITION = "DOCUMENT_TEMPLATES_STATUS_INVALID_TRANSITION"
