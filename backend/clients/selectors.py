"""Read-only query logic for the clients app (no side effects).

The directory is shared across the consultancy, so there is no owner scoping
here — every Admin and Lead Manager sees every client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from audit.selectors import get_events_for_entity
from django.db.models import Q, QuerySet

from clients.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_CLIENT
from clients.models import Client

if TYPE_CHECKING:
    # Annotation only. Importing another app's model at runtime for anything but
    # a ForeignKey is the coupling §4 forbids; the audit selector returns the
    # queryset, this app never touches the model.
    from audit.models import AuditEvent


def get_clients() -> QuerySet[Client]:
    """Every client, alphabetically, with contact numbers prefetched.

    The prefetch is required, not an optimisation: the directory list shows a
    phone number per row, so without it the list is N+1 (§6).
    """
    return Client.objects.select_related("created_by").prefetch_related("contact_numbers")


def get_client_by_id(client_id: str) -> Client | None:
    """One client with its detail relations, or None."""
    return (
        Client.objects.select_related("created_by", "retired_by")
        .prefetch_related("contact_numbers")
        .filter(pk=client_id)
        .first()
    )


def search_clients(queryset: QuerySet[Client], query: str) -> QuerySet[Client]:
    """Narrow clients by organization **or** spokesperson name (§39.6).

    OR semantics with ``icontains``; never ``__exact`` on a Devanagari name.
    The concept's "Find the right partner" flow says staff "look up the company
    or contact person", so both are searched from the one box.

    **Only the three organization-name fields are trigram-indexed.** The
    spokesperson fields are not, deliberately: the directory is a bounded table
    of partner organizations — tens to hundreds of rows — unlike ``leads``,
    which grows without limit. Indexing six columns on a table this size costs
    more in write overhead and disk than it saves. If the directory ever reaches
    a few thousand rows, add the three spokesperson indexes; the query is
    already written to use them.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        Q(name_np__icontains=query)
        | Q(name_en__icontains=query)
        | Q(name_romanized__icontains=query)
        | Q(spokesperson_name_np__icontains=query)
        | Q(spokesperson_name_en__icontains=query)
        | Q(spokesperson_name_romanized__icontains=query)
    )


def filter_clients(queryset: QuerySet[Client], filters: dict[str, Any] | None = None) -> QuerySet[Client]:
    """Apply the documented list filters.

    Recognised keys: ``status``, ``search``, and ``fiscal_year`` (``YYYY/YY``,
    Nepali fiscal year — §39.4).

    Omitting ``status`` returns **both** active and inactive clients. The
    concept requires that a retired partner stay "visible historically but not
    treated as a preferred current contact" — which is a presentation decision,
    so the API does not silently hide them.
    """
    filters = filters or {}

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    search = filters.get("search")
    if search:
        queryset = search_clients(queryset, search)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    return queryset


def get_history_for_client(client: Client) -> QuerySet[AuditEvent]:
    """A client's chronological history, newest first, from the central audit log."""
    return get_events_for_entity(
        entity_type=AUDIT_ENTITY_CLIENT,
        entity_id=str(client.id),
        app_label=AUDIT_APP_LABEL,
    )
