"""Read-only query logic for the document_history app (no side effects).

Document history is Admin-only in its entirety, so there is no owner scoping
here — the population that may read is one authority type, and it reads
everything.

Unlike ``documents.selectors.get_documents``, the snapshot list selector
**does** defer the two large JSON columns. The reasoning that kept
``documents`` from deferring ``content`` was that a caller touching it would
trigger a second query; here the split is enforced by two separate selectors
feeding two separate serializers, and the list serializer has no field that
could reach either column. A version chain of twenty bank statements would
otherwise carry twenty frozen transaction arrays to render a list of dates.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Max, QuerySet

from document_history.models import DocumentSnapshot, PrintEvent


def get_snapshots_for_document(document_id: str) -> QuerySet[DocumentSnapshot]:
    """One document's version chain, newest version first, bodies deferred.

    ``defer`` rather than ``only`` so that adding a scalar column later does not
    silently drop out of the list response.
    """
    return (
        DocumentSnapshot.objects.filter(document_id=document_id)
        .select_related("captured_by")
        .defer("content", "render_context")
    )


def get_snapshot_by_id(snapshot_id: str) -> DocumentSnapshot | None:
    """One snapshot with its full frozen payload and detail relations, or None."""
    return DocumentSnapshot.objects.select_related("captured_by", "document").filter(pk=snapshot_id).first()


def get_latest_version_number(document_id: str) -> int:
    """The highest version number in a document's chain, or 0 when it has none.

    Called under the parent document's row lock in
    ``services.create_snapshot`` — on its own it is a plain read and carries no
    concurrency guarantee.
    """
    latest = DocumentSnapshot.objects.filter(document_id=document_id).aggregate(Max("version_number"))
    return latest["version_number__max"] or 0


def get_print_events_for_document(document_id: str) -> QuerySet[PrintEvent]:
    """One document's print timeline, newest first.

    Filtered on the denormalized ``document`` column rather than joining
    through ``snapshot__document_id`` — see the field comment in ``models.py``.
    ``select_related`` on the snapshot because every timeline row shows the
    version number it refers to.
    """
    return PrintEvent.objects.filter(document_id=document_id).select_related("snapshot", "performed_by")


def filter_print_events(queryset: QuerySet[PrintEvent], filters: dict[str, Any] | None = None) -> QuerySet[PrintEvent]:
    """Apply the documented timeline filters.

    Recognised keys: ``event_type`` and ``fiscal_year`` (``YYYY/YY``, Nepali
    fiscal year — §39.4).
    """
    filters = filters or {}

    event_type = filters.get("event_type")
    if event_type:
        queryset = queryset.filter(event_type=event_type)

    queryset = filter_by_fiscal_year(queryset, filters.get("fiscal_year"))
    return queryset


def filter_snapshots(
    queryset: QuerySet[DocumentSnapshot],
    filters: dict[str, Any] | None = None,
) -> QuerySet[DocumentSnapshot]:
    """Apply the documented version-chain filters.

    Recognised key: ``fiscal_year`` (``YYYY/YY``, Nepali fiscal year — §39.4).
    A version chain is short by nature, so there is nothing else worth
    narrowing it by.
    """
    filters = filters or {}
    return filter_by_fiscal_year(queryset, filters.get("fiscal_year"))


def filter_by_fiscal_year(queryset: QuerySet[Any], fiscal_year: str | None) -> QuerySet[Any]:
    """Narrow a queryset to one Nepali fiscal year by ``created_at`` (§39.4)."""
    if not fiscal_year:
        return queryset

    from core.nepal.calendar import fiscal_year_gregorian_range

    start, end = fiscal_year_gregorian_range(fiscal_year)
    return queryset.filter(created_at__gte=start, created_at__lt=end)
