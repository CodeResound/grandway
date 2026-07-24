"""Data models for the documents app.

See ``documents/docs/DATA_CONTRACT.md`` for the authoritative contract.

Three conventions run through this app and are deliberate:

* **The backend is not the rendering engine.** ``content`` is stored verbatim
  and read back verbatim. Running balances, debit/credit totals, closing
  balances, the automatic interest and tax rows, and amount-in-words are all
  computed by the frontend at render time (``concepts/documents.txt`` —
  "Document input data"). Nothing here calculates, injects, or strips them.
* **Nothing is ever deleted.** There is no delete endpoint and no delete
  service. A document that is no longer current is archived with a reason and
  kept — "No document deletion that erases history. Retire, archive, or restore
  instead."
* **Admin only, reads included.** The strictest access model in the project.
  See ``access.py`` and ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from core.models import BaseModel
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from documents.constants import DocumentFamily, DocumentStatus
from documents.validators import validate_template_key


class Document(BaseModel):
    """One editable document record — the working copy staff prepare.

    A document is not an uploaded file, a template, or a print snapshot
    (``concepts/documents.txt`` — "Relationship to other records"). It is the
    *editable business object*: identity, ownership, status, template
    association, and the entered source data. The immutable copy captured at
    print time belongs to ``document_history``, which now exists and holds
    ``PROTECT`` foreign keys to this model; the signatory library and the
    template catalogue to ``document_templates``, which now exists and imports
    this app's family enum and key-validation rule; supporting files to
    ``uploaded_files``, which does not exist.

    Note what ``document_templates`` existing does **not** change here:
    ``template_key`` is still not checked against that catalogue, and
    ``content.instructorId`` / ``content.directorId`` are still unvalidated
    strings. This app consults neither table.

    The ``archived_*`` fields are denormalized *current state*, mirroring the
    pattern in ``leads``, ``applicant_journeys``, ``offers``, and ``clients``
    (§35 item 15): current state is a plain field read, while the append-only
    audit log remains the authoritative event history.
    """

    # --- Ownership ---------------------------------------------------------
    #
    # Nullable because the concept requires standalone documents — internal
    # forms and letters with no applicant behind them. ``PROTECT`` because an
    # applicant who has documents on file cannot be removed out from under
    # them; there is no cascade here, deliberately, whatever a client may
    # assume about deleting a person.
    applicant = models.ForeignKey(
        "applicants.Applicant",
        on_delete=models.PROTECT,
        related_name="documents",
        null=True,
        blank=True,
    )
    standalone_purpose = models.TextField(
        blank=True,
        help_text=(
            "Why a document with no applicant exists, and who commissioned it. "
            "Required exactly when applicant is empty."
        ),
    )

    # --- Type --------------------------------------------------------------
    #
    # The stable class lives in the database as an enum; the concrete template
    # slug is a validated string. That call paid off: ``document_templates``
    # now holds the slug catalogue as rows, and onboarding a bank partner
    # needed no migration here at all. ``family`` stayed the enum, and that app
    # imports it rather than declaring a second copy. See ``constants.py``.
    family = models.CharField(max_length=20, choices=DocumentFamily.choices, db_index=True)
    template_key = models.CharField(
        max_length=100,
        db_index=True,
        validators=[validate_template_key],
        help_text="The template slug the frontend renders with, e.g. 'bank-vyas-statement'.",
    )
    label = models.CharField(
        max_length=255,
        help_text='What staff call this document, e.g. "Vyas Statement".',
    )

    # --- The document body -------------------------------------------------
    content = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "The entered source data, stored verbatim. The backend never computes, injects, "
            "or strips derived presentation values — see docs/DATA_CONTRACT.md."
        ),
    )

    # --- Lifecycle ---------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="documents_created",
    )

    # --- Archive state (cleared on restore) --------------------------------
    archive_reason = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents_archived",
    )

    class Meta:
        db_table = "documents_document"
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        # A workspace worklist reads most-recently-touched first, and the
        # frontend's "last updated" column depends on this ordering.
        ordering = ["-updated_at"]
        indexes = [
            # The Applicant Detail documents panel.
            models.Index(fields=["applicant", "-updated_at"], name="document_applicant_recent_idx"),
            # The Document List worklist filtered by status.
            models.Index(fields=["status", "-updated_at"], name="document_status_recent_idx"),
            # "Every bank statement we hold".
            models.Index(fields=["family", "-updated_at"], name="document_family_recent_idx"),
            # The ?search= lookup over labels. pg_trgm already exists —
            # leads migration 0002.
            GinIndex(fields=["label"], name="document_label_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.template_key})"

    @property
    def is_standalone(self) -> bool:
        """True when this document belongs to no applicant."""
        return self.applicant_id is None

    @property
    def is_archived(self) -> bool:
        return self.status == DocumentStatus.ARCHIVED

    @property
    def is_editable(self) -> bool:
        """True while the document may still be changed.

        An archived document is a historical record; it must be restored first,
        so that "archived, then edited" is always two visible events rather
        than a silent amendment.
        """
        return not self.is_archived
