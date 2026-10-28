"""Read-only query logic for the documents app (no side effects).

Documents are Admin-only in their entirety, so there is no owner scoping here —
the population that may read is one authority type, and it reads everything.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from audit.selectors import get_events_for_entity
from core.querying import narrow_to_window
from django.db.models import Count, Max, Q, QuerySet

from documents.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_DOCUMENT, DocumentStatus
from documents.models import Document

if TYPE_CHECKING:
    # Annotation only. Importing another app's model at runtime for anything but
    # a ForeignKey is the coupling §4 forbids; the audit selector returns the
    # queryset, this app never touches the model.
    from audit.models import AuditEvent


def get_documents() -> QuerySet[Document]:
    """Every document, most recently touched first, with list relations joined.

    ``content`` is deliberately **not** deferred. It is the bulk of every row
    and the list serializer never renders it, so deferring would be the obvious
    optimisation — but `Document.objects.defer("content")` then triggers a
    second query the moment any caller touches it, which is exactly the
    N+1-by-accident this project avoids elsewhere. The directory is a worklist
    read a page at a time; if `content` size ever makes the list slow, add
    `.defer()` here **and** a matching `.only()` on the detail selector so the
    two cannot disagree.
    """
    return Document.objects.select_related("applicant", "created_by")


def get_document_by_id(document_id: str) -> Document | None:
    """One document with its detail relations, or None."""
    return Document.objects.select_related("applicant", "created_by", "archived_by").filter(pk=document_id).first()


def get_documents_for_applicant(applicant_id: str) -> QuerySet[Document]:
    """One applicant's documents — the Applicant Detail panel."""
    return get_documents().filter(applicant_id=applicant_id)


def search_documents(queryset: QuerySet[Document], query: str) -> QuerySet[Document]:
    """Narrow documents by label (§39.6).

    ``icontains`` over ``label`` only, carried by its GIN trigram index.
    ``content`` is **not** searched: it is an opaque JSON body whose shape
    varies across 53 templates, and full-text search over personal financial
    data is a feature that needs its own decision, not an accident of a search
    box.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(label__icontains=query)


def filter_documents(queryset: QuerySet[Document], filters: dict[str, Any] | None = None) -> QuerySet[Document]:
    """Apply the documented list filters.

    Recognised keys: ``applicant``, ``standalone``, ``status``,
    ``include_archived``, ``family``, ``template_key``, ``search``, and
    ``fiscal_year`` (``YYYY/YY``, Nepali fiscal year — §39.4).

    Archived documents are **hidden unless asked for**: ``status=archived``
    lists only them, ``include_archived=true`` lists them alongside the rest.
    Staff archive a document to remove it, and a removed document that kept
    coming back in the applicant's list read as "remove does not work". Nothing
    disappears — the concept's "no historical document should disappear" is
    kept by both of those parameters and by the ``archived_count`` the
    workspace list reports.
    """
    filters = filters or {}

    applicant = filters.get("applicant")
    if applicant:
        queryset = queryset.filter(applicant_id=applicant)

    standalone = filters.get("standalone")
    if standalone is not None:
        queryset = queryset.filter(applicant__isnull=bool(standalone))

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)
    elif not filters.get("include_archived"):
        queryset = queryset.exclude(status=DocumentStatus.ARCHIVED)

    family = filters.get("family")
    if family:
        queryset = queryset.filter(family=family)

    template_key = filters.get("template_key")
    if template_key:
        queryset = queryset.filter(template_key=template_key)

    search = filters.get("search")
    if search:
        queryset = search_documents(queryset, search)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    return queryset


def get_workspace_summaries() -> QuerySet[dict[str, Any]]:
    """Documents grouped by applicant — the Documents landing table.

    One aggregate query, not a fetch-and-group in Python: the frontend's
    workspace list shows a row per applicant with a document count and the most
    recent edit, and computing that client-side would mean pulling every
    document in the system.

    Standalone documents are **excluded** — they have no applicant to group
    under, and folding them into a null bucket would produce a row the UI
    cannot link anywhere. List them through ``?standalone=true`` instead.
    ``document_count`` counts live (non-archived) documents and
    ``archived_count`` the removed ones, so the table still answers "whose
    files have live work on them" while an applicant whose documents are all
    archived keeps a row (``document_count`` 0) — otherwise their removed
    documents could not be reached from this screen to be restored.
    ``last_updated`` spans both.
    """
    archived = Q(status=DocumentStatus.ARCHIVED)
    return (
        Document.objects.filter(applicant__isnull=False)
        .values("applicant_id", "applicant__full_name")
        .annotate(
            document_count=Count("id", filter=~archived),
            archived_count=Count("id", filter=archived),
            last_updated=Max("updated_at"),
        )
        .order_by("-last_updated")
    )


# ---------------------------------------------------------------------------
# Dashboard summaries
# ---------------------------------------------------------------------------
#
# Aggregates over this app's own rows, living here because §4 forbids another
# app querying this table directly. ``dashboards`` composes what it gets back.


def get_document_status_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> dict[str, int]:
    """How many documents hold each status. Every status present, zero-filled.

    There is **no country filter here, and there cannot be one.** A document
    belongs to an applicant, not to a journey, so it has no destination to
    filter by — a person's documents are theirs regardless of where they end up
    applying. A caller narrowing the rest of a dashboard by country must present
    this section as unnarrowed rather than silently implying otherwise.
    """
    queryset = narrow_to_window(
        Document.objects.all(),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    counted = dict(queryset.values_list("status").annotate(total=Count("id")))
    return {status: counted.get(status, 0) for status in DocumentStatus.values}


def get_documents_in_progress(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> QuerySet[Document]:
    """Draft documents, least recently touched first — the stalled-work list.

    A document has no due date and no assignee, so "overdue" is not expressible
    here. The closest honest signal is a draft nobody has returned to, which is
    why the ordering is *oldest edit first* rather than newest.
    """
    queryset = narrow_to_window(
        Document.objects.filter(status=DocumentStatus.DRAFT),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    return queryset.select_related("applicant", "created_by").order_by("updated_at", "id")


def get_history_for_document(document: Document) -> QuerySet[AuditEvent]:
    """A document's chronological history, newest first, from the central audit log.

    The events record *that* the body changed, never what it said — see
    ``services._diff_for_audit``.
    """
    return get_events_for_entity(
        entity_type=AUDIT_ENTITY_DOCUMENT,
        entity_id=str(document.id),
        app_label=AUDIT_APP_LABEL,
    )


# ---------------------------------------------------------------------------
# Document prefill — read-only, composed from the owning apps' selectors
# ---------------------------------------------------------------------------


def get_prefill_applicant(applicant_id: str) -> Any:
    """The applicant with everything prefill renders, or None.

    ``applicants.selectors.get_applicant_by_id`` already joins the passport and
    prefetches contacts, addresses, family, educations, and language tests, so
    the prefill costs a fixed handful of queries (§6, N+1).
    """
    from applicants.selectors import get_applicant_by_id

    return get_applicant_by_id(applicant_id)


def get_prefill_photo_id(applicant_id: str) -> str | None:
    """The applicant's newest current, non-archived photograph, or None.

    A **convention**, not a stored choice: nothing designates a primary
    photograph (``applicants/docs/INTEGRATION.md`` §9). A replaced (superseded)
    or archived photo is never picked. Read through ``uploaded_files``'
    selectors, imported here rather than at module level because that app
    already depends on this one.
    """
    from uploaded_files.constants import FileCategory
    from uploaded_files.selectors import filter_files, get_files

    photo = filter_files(
        get_files(),
        {"applicant": applicant_id, "category": FileCategory.PHOTOGRAPH, "is_archived": False, "is_current": True},
    ).first()
    return str(photo.id) if photo else None
