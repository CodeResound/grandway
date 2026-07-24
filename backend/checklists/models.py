"""Data models for the checklists app.

See ``checklists/docs/DATA_CONTRACT.md`` for the authoritative contract.

Four conventions run through this module and every one of them is deliberate:

* **The template is the country's requirements; the checklist is one
  applicant's copy of them.** Two applicants headed for the same country get
  identical item sets and entirely separate progress, because each holds real
  rows of their own rather than a pointer into shared configuration.
* **Instantiation is a snapshot, not a subscription.** Items are copied at the
  moment a checklist is created. An Admin who later adds a requirement to the
  Australia template changes what *future* applicants inherit and nothing about
  anyone already being worked — the same call ``document_history`` makes about
  print snapshots, for the same reason.
* **Progress is derived, never stored.** ``ChecklistStatus`` has no
  "in progress" or "partially complete" value. Those come from counting item
  statuses at read time (``selectors.get_checklists`` annotates them), so a
  stored counter can never disagree with the items it summarizes.
* **One default per country, enforced by the database.** Automatic inheritance
  has to resolve "the checklist for this country" to exactly one template. A
  serializer check alone would leave the admin, the shell, and any future
  management command free to create the ambiguity.
"""

from __future__ import annotations

from core.models import BaseModel
from django.db import models

from checklists.constants import (
    RESOLVED_ITEM_STATUSES,
    ChecklistOrigin,
    ChecklistStatus,
    ItemStatus,
    ItemType,
    TemplateStatus,
)
from checklists.validators import validate_template_key


class ChecklistTemplate(BaseModel):
    """One country's requirement list, authored by an Admin.

    This is the model that makes the module dynamic. Adding a destination's
    document requirements is data entry — a row here and a handful of item rows
    — never a migration and never a deployment. That is the whole point:
    the office that learns Canada now wants a fresh bank statement is not the
    office that can ship code.

    A template with ``country`` set and ``is_default`` true is *the* checklist
    for that destination and is inherited automatically. Extra templates for the
    same country are legitimate and stay available for staff to apply by hand; a
    template with no country is a general list that is only ever applied
    manually.
    """

    key = models.CharField(
        max_length=50,
        unique=True,
        validators=[validate_template_key],
        help_text="Stable ASCII identifier, e.g. 'australia-student-visa'.",
    )

    # A plain ``label`` rather than a display name. A template label is
    # operational shorthand read off a picker by staff — the deviation
    # ``documents.label`` recorded and ``document_templates.label`` followed. The
    # names that genuinely carry two canonical identities in this module are the
    # country's, and those live in the ``institutions`` catalogue where §39.1
    # already applies.
    label = models.CharField(max_length=200, help_text="What staff see, e.g. 'Australia — Student Visa'.")
    description = models.TextField(blank=True)

    country = models.ForeignKey(
        "institutions.Country",
        on_delete=models.PROTECT,
        related_name="checklist_templates",
        null=True,
        blank=True,
        help_text="The destination this list is for. Null means a general list, applied only by hand.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="The list this country's applicants inherit automatically. At most one active default per country.",
    )

    status = models.CharField(
        max_length=20,
        choices=TemplateStatus.choices,
        default=TemplateStatus.DRAFT,
        db_index=True,
    )
    status_note = models.TextField(
        blank=True,
        help_text="Why this template is in its current state. Optional — no transition here requires one.",
    )

    display_order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="checklist_templates_created",
    )

    class Meta:
        db_table = "checklists_checklisttemplate"
        verbose_name = "Checklist Template"
        verbose_name_plural = "Checklist Templates"
        ordering = ["display_order", "label"]
        constraints = [
            # The constraint automatic inheritance rests on. Partial, so a
            # country may hold any number of non-default or retired templates
            # while exactly one active default answers "what does an applicant
            # bound for here inherit".
            models.UniqueConstraint(
                fields=["country"],
                condition=models.Q(is_default=True, status=TemplateStatus.ACTIVE),
                name="checklist_one_active_default_per_country",
            ),
            # A default with no country could never be inherited by anyone —
            # there is no journey whose destination is "unspecified".
            models.CheckConstraint(
                condition=models.Q(is_default=False) | models.Q(country__isnull=False),
                name="checklist_default_requires_country",
            ),
        ]
        indexes = [
            # The picker: active templates for one country.
            models.Index(fields=["country", "status"], name="cl_template_country_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"

    @property
    def is_active(self) -> bool:
        """True when this template may be applied to new work."""
        return self.status == TemplateStatus.ACTIVE

    @property
    def is_inheritable(self) -> bool:
        """True when a journey reaching this country would inherit this template."""
        return self.is_active and self.is_default and self.country_id is not None


class ChecklistTemplateItem(BaseModel):
    """One requirement definition inside a template.

    ``CASCADE`` on the template, unlike every cross-app foreign key in this
    project: a template item has no meaning apart from its template, and
    templates are never deleted — the same call ``offers.OfferCondition`` makes
    about its offer.
    """

    template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.CASCADE,
        related_name="items",
    )

    label = models.CharField(max_length=255, help_text="The requirement, e.g. 'Passport bio page scan'.")
    description = models.TextField(blank=True)
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.DOCUMENT)
    is_required = models.BooleanField(
        default=True,
        help_text="Required items must be resolved before the checklist can be completed.",
    )
    display_order = models.PositiveIntegerField(default=0)

    default_due_offset_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Days after instantiation this item is due. Turned into a real date on each applicant's copy.",
    )

    # Deactivated, never deleted: a live checklist item points back at the
    # definition it came from, and that provenance has to keep resolving.
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "checklists_checklisttemplateitem"
        verbose_name = "Checklist Template Item"
        verbose_name_plural = "Checklist Template Items"
        ordering = ["display_order", "label"]
        indexes = [
            models.Index(fields=["template", "display_order"], name="cl_tmpl_item_order_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.item_type})"


class Checklist(BaseModel):
    """One applicant's copy of a country's requirement list.

    Anchored to the journey rather than to the applicant, because the journey is
    where the destination lives — and since a change of destination closes the
    profile and starts a new registration, that is one checklist per applicant in
    practice. A client shows it as "this applicant's checklist" by filtering
    ``?applicant=<id>``.

    ``source_template`` and ``country`` are both copied at instantiation.
    ``country`` is denormalized on purpose: "every Australia checklist" is a
    question the operations team asks constantly, and answering it through a
    join into mutable configuration would change its answer the day a template
    was re-scoped.
    """

    journey = models.ForeignKey(
        "applicant_journeys.ApplicantJourney",
        on_delete=models.PROTECT,
        related_name="checklists",
    )
    source_template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.PROTECT,
        related_name="checklists",
        null=True,
        blank=True,
        help_text="The template this was inherited from. Null for a checklist staff built by hand.",
    )
    country = models.ForeignKey(
        "institutions.Country",
        on_delete=models.PROTECT,
        related_name="checklists",
        null=True,
        blank=True,
        help_text="Copied from the template at instantiation. Not re-read later.",
    )

    # The label snapshot. Renaming a template does not rename the checklists
    # already carrying its name into an applicant's file.
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    origin = models.CharField(
        max_length=20,
        choices=ChecklistOrigin.choices,
        default=ChecklistOrigin.MANUAL,
        db_index=True,
        help_text="Whether this was inherited automatically or created by staff.",
    )
    status = models.CharField(
        max_length=20,
        choices=ChecklistStatus.choices,
        default=ChecklistStatus.DRAFT,
        db_index=True,
    )

    assigned_to = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklists_assigned",
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    notes = models.TextField(blank=True)

    # --- Denormalized lifecycle state (§35 item 15) --------------------------
    #
    # Current state is a plain field read; the append-only audit log remains the
    # authoritative event history. Matches ``offers``, ``uploaded_files``,
    # ``documents``, and ``applicant_journeys``.
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklists_completed",
    )
    archive_reason = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklists_archived",
    )
    # The status the checklist held when it was archived, so restore puts it
    # back rather than guessing. Without this, archiving a *completed* checklist
    # and restoring it produced an ``active`` checklist still carrying
    # ``completed_at`` — a list showing "completed on the 3rd" above unfinished
    # work. Mirrors ``applicant_journeys.stage_before_terminal``, which exists
    # for exactly the same reason.
    status_before_archive = models.CharField(max_length=20, choices=ChecklistStatus.choices, blank=True)

    # Nullable, unlike every other ``created_by`` in the project: a checklist
    # inherited automatically has no human author. Recording the acting staff
    # member would be a lie about who decided this applicant needed this list.
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="checklists_created",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "checklists_checklist"
        verbose_name = "Checklist"
        verbose_name_plural = "Checklists"
        # Newest first with ``id`` as a tiebreaker: ``created_at`` is not unique
        # — a backfill writes many rows in one transaction — and a non-unique
        # sort key under page-number pagination lets a row appear on two pages
        # or on none.
        ordering = ["-created_at", "-id"]
        indexes = [
            # The Applicant/Journey Detail panel.
            models.Index(fields=["journey", "-created_at"], name="cl_journey_recent_idx"),
            # The operational worklist: "everything still active".
            models.Index(fields=["status", "-created_at"], name="cl_status_recent_idx"),
            # "What is on my desk".
            models.Index(fields=["assigned_to", "status"], name="cl_assignee_status_idx"),
            # "Every Australia checklist", and the overdue sweep.
            models.Index(fields=["country", "status"], name="cl_country_status_idx"),
            models.Index(fields=["due_at"], name="cl_due_idx"),
        ]

    def __str__(self) -> str:
        # Local columns only — naming the applicant here would read better and
        # fire one query per row in the admin changelist.
        return f"{self.title} ({self.status})"

    @property
    def is_editable(self) -> bool:
        """True while items may still be added or moved.

        A completed checklist is reopened first — not locked forever, but not
        silently editable either, because "complete" is a claim someone made
        about a moment in time.
        """
        return self.status in (ChecklistStatus.DRAFT, ChecklistStatus.ACTIVE)

    @property
    def is_archived(self) -> bool:
        return self.status == ChecklistStatus.ARCHIVED

    @property
    def is_completed(self) -> bool:
        return self.status == ChecklistStatus.COMPLETED

    @property
    def is_inherited(self) -> bool:
        return self.origin == ChecklistOrigin.AUTO


class ChecklistItem(BaseModel):
    """One requirement on one applicant, and the record of what happened to it.

    The fields are copies, not references: ``label``, ``item_type``, and
    ``is_required`` are snapshotted from the template item so that editing the
    template never rewrites an applicant's list. ``source_template_item`` is kept
    for provenance only — nothing reads through it for display.
    """

    checklist = models.ForeignKey(
        Checklist,
        on_delete=models.CASCADE,
        related_name="items",
    )
    source_template_item = models.ForeignKey(
        ChecklistTemplateItem,
        on_delete=models.PROTECT,
        related_name="instances",
        null=True,
        blank=True,
        help_text="Which definition this was copied from. Null for an item staff added by hand.",
    )

    label = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.DOCUMENT)
    is_required = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        default=ItemStatus.PENDING,
        db_index=True,
    )
    status_note = models.TextField(
        blank=True,
        help_text="Why this item was waived or declared blocked. Required for both.",
    )

    assigned_to = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklist_items_assigned",
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # --- Evidence ------------------------------------------------------------
    #
    # The project's first inbound reference to ``uploaded_files``. ``PROTECT``
    # because a file cited as proof that a requirement was met is the reason the
    # item is marked done; the service additionally refuses any file that does
    # not belong to this checklist's journey or its applicant.
    evidence_file = models.ForeignKey(
        "uploaded_files.UploadedFile",
        on_delete=models.PROTECT,
        related_name="checklist_items",
        null=True,
        blank=True,
    )
    evidence_note = models.TextField(blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklist_items_completed",
    )

    class Meta:
        db_table = "checklists_checklistitem"
        verbose_name = "Checklist Item"
        verbose_name_plural = "Checklist Items"
        ordering = ["display_order", "created_at"]
        indexes = [
            # The detail view, in the order the author intended.
            models.Index(fields=["checklist", "display_order"], name="cl_item_order_idx"),
            # The overdue sweep across every applicant.
            models.Index(fields=["status", "due_at"], name="cl_item_status_due_idx"),
            # "What is on my desk", item level.
            models.Index(fields=["assigned_to", "status"], name="cl_item_assignee_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.status})"

    @property
    def is_resolved(self) -> bool:
        """True when this item no longer stands in the way of completion.

        ``blocked`` is not resolved, deliberately. It is the one status meaning
        "stuck on something outside our control", and a checklist that completed
        over a blocked requirement would be reporting work that was never done.
        """
        return self.status in RESOLVED_ITEM_STATUSES
