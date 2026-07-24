"""Data models for the document_history app.

See ``document_history/docs/DATA_CONTRACT.md`` for the authoritative contract.

Three conventions run through this app and are deliberate:

* **Nothing here is ever rewritten.** ``concepts/document_history.txt`` —
  "Snapshots are append-only and never edited in place", "No editing of
  existing snapshots", "No deletion of historical snapshots". Both models block
  ``delete()``, and ``DocumentSnapshot`` additionally blocks a second ``save()``
  on an existing row. Enforced at the model layer, not only in services, so the
  Django admin and any future management command hit the same wall.
* **A snapshot is not a print event.** The frozen body and the act of producing
  it are two records. A reprint is new activity against an existing body, so it
  writes an event and no snapshot — otherwise every reprint would duplicate a
  bank statement's entire transaction array and "which version was issued"
  would stop having an answer.
* **The backend copies the body; it never accepts one.** ``content`` is read
  off the ``Document`` at capture time. A snapshot that took its body from the
  request could disagree with the record it claims to freeze, which would make
  the whole module untrustworthy for the one job it has.
"""

from __future__ import annotations

from typing import Any

from core.models import BaseModel
from django.db import models

from document_history.constants import PrintEventType
from document_history.exceptions import SnapshotImmutableError


class DocumentSnapshot(BaseModel):
    """One immutable copy of a document, frozen at print or save-to-history time.

    A snapshot is not a document (``concepts/document_history.txt`` —
    "Relationship to other records"). The ``documents`` app owns the current
    editable body; this owns the frozen copies plus the render-time context
    needed to reproduce what the frontend showed at that moment. It must never
    rewrite the working document, and the working document must never silently
    rewrite it.

    ``family``, ``template_key``, and ``label`` are **copied**, not read through
    the FK. Renaming a document later must not retitle what was already issued —
    that is precisely the "later changes must not silently rewrite historical
    print records" hard constraint in ``concepts/project_overview.txt``.
    """

    # --- What was frozen ---------------------------------------------------
    #
    # ``PROTECT`` because a document with print history cannot be removed out
    # from under it. There is no delete path in ``documents`` today, and this
    # makes adding one a deliberate decision rather than a cascade nobody saw.
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    version_number = models.PositiveIntegerField(
        help_text="Position in this document's version chain, 1-based.",
    )

    # --- Frozen identity ---------------------------------------------------
    #
    # Copied at capture time. See the class docstring for why these are not
    # read through the FK.
    family = models.CharField(max_length=20)
    template_key = models.CharField(max_length=100)
    label = models.CharField(max_length=255)

    # --- The frozen body ---------------------------------------------------
    content = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Verbatim copy of the document body at capture time. Read from the document by the "
            "backend, never accepted from the client."
        ),
    )
    render_context = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Client-supplied render-time context: the frontend-computed values, template version, "
            "and signatory metadata as they stood at capture. Stored verbatim, shape unvalidated."
        ),
    )

    # --- Who and why -------------------------------------------------------
    capture_note = models.TextField(blank=True)
    captured_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="document_snapshots_captured",
    )

    class Meta:
        db_table = "document_history_documentsnapshot"
        verbose_name = "Document Snapshot"
        verbose_name_plural = "Document Snapshots"
        # Newest version first — the history timeline's default review mode, and
        # the order the Snapshot Detail screen's "previous version" link walks.
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="document_snapshot_version_unique",
            )
        ]
        indexes = [
            # The version chain read: every snapshot of one document, newest
            # first. Backs both the list endpoint and the next-version lookup
            # in ``services.create_snapshot``.
            models.Index(fields=["document", "-version_number"], name="snapshot_document_version_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} v{self.version_number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Append-only: a stored snapshot may never be saved again.

        Checked with ``_state.adding`` rather than a null-pk test, because
        ``BaseModel`` assigns the UUID in Python before the first insert — a
        ``pk is None`` guard would never fire.
        """
        if not self._state.adding:
            raise SnapshotImmutableError("A stored snapshot cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise SnapshotImmutableError("Snapshots are append-only; delete is not allowed.")


class PrintEvent(BaseModel):
    """One act of producing output from a snapshot — a capture, reprint, or recovery.

    ``concepts/document_history.txt`` names this as a core entity separate from
    the snapshot: "A document may have many print events over time." A capture
    writes a snapshot *and* an event; a reprint and a recovery write only an
    event, against a snapshot that already exists.
    """

    snapshot = models.ForeignKey(
        DocumentSnapshot,
        on_delete=models.PROTECT,
        related_name="print_events",
    )
    # Denormalized from ``snapshot.document``. The per-document timeline is this
    # app's primary read, and carrying the document here makes it one index scan
    # on ``print_event_document_recent_idx`` instead of a join through the
    # snapshot table. A snapshot's document is immutable, so the two can never
    # disagree. Documented in docs/DATA_CONTRACT.md.
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        related_name="print_events",
    )

    event_type = models.CharField(max_length=20, choices=PrintEventType.choices, db_index=True)
    note = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="document_print_events",
    )

    class Meta:
        db_table = "document_history_printevent"
        verbose_name = "Print Event"
        verbose_name_plural = "Print Events"
        # The timeline reads newest first, with ``id`` as a tiebreaker.
        #
        # The tiebreaker is not cosmetic. ``created_at`` is **not unique** — a
        # capture writes its snapshot and its event in one transaction, and two
        # events can share a timestamp — while this list is paginated and offers
        # no client-controllable ordering. A non-unique sort key under
        # page-number pagination lets a row appear on two pages or on none,
        # which on an append-only history reads as an event that silently
        # vanished. ``id`` is a UUID, so it breaks ties arbitrarily but
        # *stably*, which is all pagination needs.
        ordering = ["-created_at", "-id"]
        indexes = [
            # The Document History Timeline screen. Name kept short — Django
            # caps index names at 30 characters (models.E034).
            models.Index(fields=["document", "-created_at"], name="print_event_doc_recent_idx"),
        ]

    def __str__(self) -> str:
        # Reads only local columns. Naming the snapshot's label here would look
        # friendlier and would fire one query per row in the admin changelist.
        return f"{self.event_type} of snapshot {self.snapshot_id}"

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise SnapshotImmutableError("Print events are append-only; delete is not allowed.")
