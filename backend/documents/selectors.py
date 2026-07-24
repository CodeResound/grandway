"""Read-only query logic for the documents app (no side effects).

Documents are Admin-only in their entirety, so there is no owner scoping here —
the population that may read is one authority type, and it reads everything.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from django.db.models import Count, Max, QuerySet

from documents.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_DOCUMENT, DocumentStatus
from documents.models import Document


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

    Recognised keys: ``applicant``, ``standalone``, ``status``, ``family``,
    ``template_key``, ``search``, and ``fiscal_year`` (``YYYY/YY``, Nepali
    fiscal year — §39.4).

    Omitting ``status`` returns archived documents too. The concept requires
    that "no historical document should disappear just because it is no longer
    active"; which of them a given screen shows is a presentation decision.
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
    Archived documents are excluded from the count for the same reason the
    landing table exists: it answers "whose files have live work on them".
    """
    return (
        Document.objects.filter(applicant__isnull=False)
        .exclude(status=DocumentStatus.ARCHIVED)
        .values("applicant_id", "applicant__full_name_np", "applicant__full_name_en")
        .annotate(document_count=Count("id"), last_updated=Max("updated_at"))
        .order_by("-last_updated")
    )


def get_history_for_document(document: Document) -> QuerySet[AuditEvent]:
    """A document's chronological history, newest first, from the central audit log.

    The events record *that* the body changed, never what it said — see
    ``services._diff_for_audit``.
    """
    return get_events(
        {
            "app": AUDIT_APP_LABEL,
            "entity_type": AUDIT_ENTITY_DOCUMENT,
            "entity_id": str(document.id),
        }
    )
