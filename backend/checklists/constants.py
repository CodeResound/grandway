"""Enums, error codes, and audit-action names for the checklists app.

Three of the vocabularies here look like ones other apps already declare, and
each is declared locally on purpose (§4 forbids importing another app's models,
and an enum quietly shared across a boundary is what makes a later divergence
invisible):

* ``TemplateStatus`` has the same three values as
  ``document_templates.LifecycleStatus`` — the same call ``institutions``
  made when ``AvailabilityStatus`` came out shaped like ``leads.ReferenceEntry``.
* ``NOTE_REQUIRED_STATUSES`` mirrors ``institutions.constants``: some states
  oblige the author to explain themselves.
* ``ItemStatus`` is the concept file's five values, verbatim.
"""

from django.db import models

__all__ = [
    "AUDIT_APP_LABEL",
    "AUDIT_ENTITY_CHECKLIST",
    "AUDIT_ENTITY_ITEM",
    "AUDIT_ENTITY_TEMPLATE",
    "EDITABLE_CHECKLIST_STATUSES",
    "NOTE_REQUIRED_STATUSES",
    "RESOLVED_ITEM_STATUSES",
    "UNRESOLVED_ITEM_STATUSES",
    "ChecklistAuditAction",
    "ChecklistOrigin",
    "ChecklistStatus",
    "ErrorCode",
    "ItemStatus",
    "ItemType",
    "TemplateStatus",
]


class TemplateStatus(models.TextChoices):
    """Whether a template may be offered for new work.

    Nothing here is ever deleted: a checklist points at the template it came
    from forever, so a template that is no longer used becomes ``inactive``
    rather than a tombstone.
    """

    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class ItemType(models.TextChoices):
    """What kind of thing an item tracks.

    The consultancy tracks two different things on one list and they are not
    interchangeable: *documents* are collected from the applicant, *stages* are
    reached by the office. Typing them lets one screen answer "what is still
    missing from this applicant" and "where are they in the process" separately,
    without parsing labels.
    """

    DOCUMENT = "document", "Document"
    STAGE = "stage", "Stage"
    TASK = "task", "Task"


class ItemStatus(models.TextChoices):
    """Where one requirement stands.

    Taken verbatim from ``concepts/checklists.txt`` — "Item model". Note what is
    absent: there is no ``in_progress``. A checklist's overall progress is
    derived by counting these, so a per-item halfway state would make the count
    ambiguous without telling anyone anything they could act on.
    """

    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    WAIVED = "waived", "Waived"
    BLOCKED = "blocked", "Blocked"
    NOT_APPLICABLE = "not_applicable", "Not Applicable"


class ChecklistStatus(models.TextChoices):
    """Where one applicant's checklist stands as a whole.

    The concept file's lifecycle names six steps; only four are stored. "In
    progress" and "partially complete" are **derived from item counts**, never
    written — a stored progress state is a second source of truth that goes
    stale the moment someone ticks an item.
    """

    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ARCHIVED = "archived", "Archived"


class ChecklistOrigin(models.TextChoices):
    """How this checklist came to exist.

    Stored rather than inferred, because the whole promise of the module is that
    choosing a country produces a checklist without anyone asking. "Did the
    automation actually fire for this applicant" must be a field read, not a
    reconstruction from timestamps.
    """

    AUTO = "auto", "Inherited automatically"
    MANUAL = "manual", "Created by staff"


#: Item statuses that no longer block completion. ``blocked`` is deliberately
#: absent — it is the one state that means "stuck", and a checklist that
#: completed over a blocked requirement would be lying.
RESOLVED_ITEM_STATUSES: tuple[str, ...] = (
    ItemStatus.COMPLETED,
    ItemStatus.WAIVED,
    ItemStatus.NOT_APPLICABLE,
)

#: The complement of ``RESOLVED_ITEM_STATUSES`` — items that still stand in the
#: way. Derived from the enum rather than typed out a second time, so adding an
#: item status forces a decision about which side it falls on instead of silently
#: defaulting to "resolved".
#:
#: Needed as a *positive* list because a queryset cannot express "checklists
#: holding an unresolved item" by excluding resolved ones: ``.exclude()`` across
#: a multi-valued relation drops the whole checklist if *any* of its items match,
#: so one completed requirement would hide every outstanding one beside it.
UNRESOLVED_ITEM_STATUSES: tuple[str, ...] = tuple(
    status for status in ItemStatus.values if status not in RESOLVED_ITEM_STATUSES
)

#: Item statuses that oblige the author to explain themselves in ``status_note``.
#: Waiving a requirement and declaring one blocked are both judgements someone
#: will be asked about later.
NOTE_REQUIRED_STATUSES: tuple[str, ...] = (
    ItemStatus.WAIVED,
    ItemStatus.BLOCKED,
)

#: Checklist states in which items may still be edited. A completed checklist is
#: reopened first — not locked forever, but not silently editable either.
EDITABLE_CHECKLIST_STATUSES: tuple[str, ...] = (
    ChecklistStatus.DRAFT,
    ChecklistStatus.ACTIVE,
)


class ChecklistAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    TEMPLATE_CREATED = "checklist_template_created"
    TEMPLATE_UPDATED = "checklist_template_updated"
    TEMPLATE_ITEM_CREATED = "checklist_template_item_created"
    TEMPLATE_ITEM_UPDATED = "checklist_template_item_updated"

    CHECKLIST_CREATED = "checklist_created"
    CHECKLIST_INHERITED = "checklist_inherited"
    CHECKLIST_UPDATED = "checklist_updated"
    CHECKLIST_ACTIVATED = "checklist_activated"
    CHECKLIST_COMPLETED = "checklist_completed"
    CHECKLIST_REOPENED = "checklist_reopened"
    CHECKLIST_ARCHIVED = "checklist_archived"
    CHECKLIST_RESTORED = "checklist_restored"
    CHECKLIST_INHERIT_FAILED = "checklist_inherit_failed"

    ITEM_CREATED = "checklist_item_created"
    ITEM_UPDATED = "checklist_item_updated"
    ITEM_STATUS_CHANGED = "checklist_item_status_changed"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "checklists"

#: ``audit.AuditEvent.entity_type`` values.
AUDIT_ENTITY_TEMPLATE = "checklist_template"
AUDIT_ENTITY_CHECKLIST = "checklist"
AUDIT_ENTITY_ITEM = "checklist_item"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the checklists app (§7)."""

    ACTOR_FORBIDDEN = "CHECKLISTS_ACTOR_FORBIDDEN"

    # --- Resolution ------------------------------------------------------
    TEMPLATE_NOT_FOUND = "CHECKLISTS_TEMPLATE_NOT_FOUND"
    TEMPLATE_ITEM_NOT_FOUND = "CHECKLISTS_TEMPLATE_ITEM_NOT_FOUND"
    CHECKLIST_NOT_FOUND = "CHECKLISTS_CHECKLIST_NOT_FOUND"
    ITEM_NOT_FOUND = "CHECKLISTS_ITEM_NOT_FOUND"
    JOURNEY_NOT_FOUND = "CHECKLISTS_JOURNEY_NOT_FOUND"
    COUNTRY_NOT_FOUND = "CHECKLISTS_COUNTRY_NOT_FOUND"

    # --- Template authoring ----------------------------------------------

    #: A second active default for one country. Refused with this rather than an
    #: ``IntegrityError``, so the Admin learns which template already holds the
    #: slot instead of reading a constraint name.
    DEFAULT_TEMPLATE_EXISTS = "CHECKLISTS_DEFAULT_TEMPLATE_EXISTS"

    #: A default template with no country. "The checklist for nowhere in
    #: particular" cannot be inherited by anyone.
    DEFAULT_REQUIRES_COUNTRY = "CHECKLISTS_DEFAULT_REQUIRES_COUNTRY"
    TEMPLATE_KEY_INVALID = "CHECKLISTS_TEMPLATE_KEY_INVALID"

    # --- Instantiation ---------------------------------------------------
    TEMPLATE_ALREADY_APPLIED = "CHECKLISTS_TEMPLATE_ALREADY_APPLIED"
    TEMPLATE_NOT_ACTIVE = "CHECKLISTS_TEMPLATE_NOT_ACTIVE"
    TEMPLATE_HAS_NO_ITEMS = "CHECKLISTS_TEMPLATE_HAS_NO_ITEMS"

    # --- Lifecycle -------------------------------------------------------

    #: Completion is derived from item state, never asserted. This is what a
    #: client gets for trying to close a checklist that still has real work on
    #: it, and the details name every offending item.
    REQUIRED_ITEMS_PENDING = "CHECKLISTS_REQUIRED_ITEMS_PENDING"
    STATUS_NOTE_REQUIRED = "CHECKLISTS_STATUS_NOTE_REQUIRED"
    INVALID_TRANSITION = "CHECKLISTS_INVALID_TRANSITION"
    CHECKLIST_ARCHIVED = "CHECKLISTS_CHECKLIST_ARCHIVED"
    CHECKLIST_NOT_ARCHIVED = "CHECKLISTS_CHECKLIST_NOT_ARCHIVED"
    ARCHIVE_REASON_REQUIRED = "CHECKLISTS_ARCHIVE_REASON_REQUIRED"

    # --- Evidence --------------------------------------------------------

    #: The attached file belongs to somebody else. The one check that keeps this
    #: module from becoming a way to cite another applicant's passport as proof.
    EVIDENCE_NOT_ALLOWED = "CHECKLISTS_EVIDENCE_NOT_ALLOWED"
    EVIDENCE_NOT_FOUND = "CHECKLISTS_EVIDENCE_NOT_FOUND"
