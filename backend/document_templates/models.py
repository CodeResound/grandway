"""Data models for the document_templates app.

See ``document_templates/docs/DATA_CONTRACT.md`` for the authoritative contract.

Three conventions run through this app and are deliberate:

* **This app stores what is *offered*, not what is *rendered*.** The frontend
  owns the template code — the 53 slugs are a hardcoded union there and the
  per-family content shapes are compiled-in types. ``DocumentTemplate`` is a
  picker row: a key, a family, a label, and whether it may still be chosen.
  There is no section list, no field-hint map, and no version chain, because no
  consumer reads any of them and inventing a schema for them would guarantee
  drift from the templates that actually exist.
* **Nothing is ever deleted.** A signatory or template that is no longer current
  is deactivated and kept. Documents reference a template by plain string and
  snapshots freeze signatory ids, so a row removed here would silently orphan
  history that has no foreign key to protect it.
* **Two things are imported from ``documents`` rather than redeclared** — the
  ``DocumentFamily`` enum and the key/family agreement rule. §4 forbids
  duplicating enums and service functions across apps, and here that outranks
  the fact that ``constants.py`` is not on §4's list of importable modules: a
  second copy of the six families, or a second copy of the prefix/suffix check,
  could accept a key ``documents`` would reject. ``document_history`` made the
  opposite call for ``MAX_RENDER_CONTEXT_BYTES``, and the distinction holds — a
  size cap may legitimately diverge between two apps, a shared vocabulary may
  not.
"""

from __future__ import annotations

from core.models import BaseModel
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from documents.constants import DocumentFamily
from documents.validators import validate_template_key

from document_templates.constants import LifecycleStatus


class LifecycleMixin(models.Model):
    """Shared activation state for both models in this app.

    A mixin rather than two copies of three fields, following the
    ``AvailabilityMixin`` precedent in ``institutions``. Both models answer the
    same question — "may this be offered for new work?" — with the same three
    answers, and the ``status_note`` carries the optional why.
    """

    status = models.CharField(
        max_length=20,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.DRAFT,
        db_index=True,
    )
    status_note = models.TextField(
        blank=True,
        help_text="Why this entry is in its current state. Optional — no transition here requires one.",
    )

    class Meta:
        abstract = True

    @property
    def is_active(self) -> bool:
        """True when this entry may be offered for new work.

        The frontend's ``Signature.is_active`` boolean maps to this: a ``draft``
        signatory is not offered, and neither is an ``inactive`` one.
        """
        return self.status == LifecycleStatus.ACTIVE


class Signatory(BaseModel, LifecycleMixin):
    """One stored person-and-signature record a certificate may point at.

    **A signatory is not a system user** (``concepts/document_templates.txt`` —
    "A signatory is not a system actor"). There is no account, no login, and no
    link to ``authenticate.User``: the person whose name appears at the bottom
    of a certificate is usually not someone who uses Grandway at all.

    This is the record ``documents``' ``content.instructorId`` and
    ``content.directorId`` have been pointing at since that app shipped, and the
    one ``document_history`` freezes into ``render_context.signatories``. Both
    stored those ids as opaque strings against a table that did not exist. It
    exists now — but note what still has not changed: **neither app validates
    those ids on write.** A document may still name a signatory that never
    existed; the difference is that a client now has a real list to pick from.
    """

    # --- Identity (§39.1 applies in full here) -----------------------------
    #
    # Unlike ``documents.label`` — operational shorthand from a picker, which
    # that app deliberately kept as a single field — a signatory is a named
    # person whose name is printed on a Nepali legal document. That is exactly
    # §39.1's premise: the Devanagari and Roman forms are two equally canonical
    # identities, not translations of each other.
    name_np = models.CharField(max_length=255)
    name_en = models.CharField(max_length=255, blank=True)
    name_romanized = models.CharField(
        max_length=255,
        blank=True,
        help_text="Auto-derived from name_np by the service layer (§39.3). Never hand-entered.",
    )

    # --- Standing ----------------------------------------------------------
    #
    # No ``_romanized`` sibling: §39.6 scopes romanized fields to search, and
    # search here is over names only. Nobody looks up a signatory by job title.
    title_np = models.CharField(max_length=255, blank=True)
    title_en = models.CharField(max_length=255, blank=True)

    # Free text, not an enum. The frontend picks signatories into
    # ``instructorId`` and ``directorId`` slots, and ``document_history``'s
    # worked example carries ``"role": "director"`` — but the signature-slot
    # metadata that would fix the vocabulary is not built, so an enum here would
    # be a guess that starts rejecting real roles the moment a template needs a
    # fourth one.
    role = models.CharField(
        max_length=100,
        blank=True,
        help_text='Free text, e.g. "director", "instructor". Not an enum — see docs/DATA_CONTRACT.md.',
    )

    # --- The signature itself ----------------------------------------------
    #
    # A URL, not an upload. §14 requires a full file contract — allowed types,
    # max size, MIME validation, filename rule, access control — and
    # ``uploaded_files`` does not exist. Fourth deferral of this kind, after the
    # applicant photograph, offer attachments, and ``clients.logo_url``, whose
    # field this mirrors exactly.
    signature_image_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="A link to a signature image hosted elsewhere. Not an upload — see docs/DATA_CONTRACT.md.",
    )

    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="signatories_created",
    )

    class Meta:
        db_table = "document_templates_signatory"
        verbose_name = "Signatory"
        verbose_name_plural = "Signatories"
        # Alphabetical by Devanagari name — this is a reference library read as
        # a picker, not a worklist, so recency means nothing here. Same call
        # ``clients`` made.
        ordering = ["name_np"]
        indexes = [
            # The frontend's only call: the active-signatory picker.
            models.Index(fields=["status", "name_np"], name="signatory_status_name_idx"),
            # ?search= across all three name forms (§39.6). pg_trgm already
            # exists — leads migration 0002.
            GinIndex(fields=["name_np"], name="signatory_name_np_trgm_idx", opclasses=["gin_trgm_ops"]),
            GinIndex(fields=["name_en"], name="signatory_name_en_trgm_idx", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["name_romanized"],
                name="signatory_name_rom_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name_en or self.name_np} ({self.status})"


class DocumentTemplate(BaseModel, LifecycleMixin):
    """One row of the template picker — a slug, a family, and a label.

    **This is a catalogue entry, not a template.** The template itself lives in
    the frontend as code. What this row adds is the ability to retire a bank
    partner, or rename what staff call a form, without a frontend deploy — and
    a canonical list of what exists, which the backend previously had no way to
    answer.

    It is deliberately **advisory**: ``documents`` does not consult it. Creating
    a document with a ``template_key`` absent from this table still succeeds, by
    design — enforcing it would narrow a shipped endpoint's accepted input, and
    that is its own decision with its own approval gate.
    """

    key = models.CharField(
        max_length=100,
        unique=True,
        validators=[validate_template_key],
        help_text="The template slug the frontend renders with, e.g. 'bank-vyas-statement'.",
    )
    # Imported from ``documents``, never redeclared — see the module docstring.
    family = models.CharField(max_length=20, choices=DocumentFamily.choices, db_index=True)
    label = models.CharField(
        max_length=255,
        help_text='What staff call this template in the picker, e.g. "Vyas Statement".',
    )
    description = models.TextField(blank=True)

    # Picker ordering. Without it the eleven bank statements sort alphabetically
    # by label, which is not the order anyone wants to read them in.
    display_order = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="document_templates_created",
    )

    class Meta:
        db_table = "document_templates_documenttemplate"
        verbose_name = "Document Template"
        verbose_name_plural = "Document Templates"
        # Grouped by family, then curated order, then label — the shape of the
        # picker the frontend draws.
        ordering = ["family", "display_order", "label"]
        indexes = [
            # The picker: "every active bank statement template".
            models.Index(fields=["family", "status"], name="template_family_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"
