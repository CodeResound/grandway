"""Read-only query logic for the applicants app (no side effects, no business rules).

Unlike ``leads.selectors``, there is no owner scoping here — applicants are
shared across the consultancy (``docs/SECURITY.md`` §1). The authority check
that matters (Superadmin denied) happens in the view via ``access.py``.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from django.db.models import Q, QuerySet

from applicants.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_APPLICANT
from applicants.models import Applicant


def get_applicants() -> QuerySet[Applicant]:
    """Every applicant, newest first, with list relations joined.

    ``select_related``/``prefetch_related`` are applied here so list rendering
    never issues a query per row (§6, N+1 prevention).
    """
    return Applicant.objects.select_related("created_by").prefetch_related("contact_numbers")


def get_applicant_by_id(applicant_id: str) -> Applicant | None:
    """One applicant with its full detail graph, or None."""
    return (
        Applicant.objects.select_related("created_by", "passport")
        .prefetch_related("contact_numbers", "addresses", "family_members", "emergency_contacts")
        .filter(pk=applicant_id)
        .first()
    )


def search_applicants(queryset: QuerySet[Applicant], query: str) -> QuerySet[Applicant]:
    """Narrow applicants by name across all three language representations (§39.6).

    OR semantics over ``full_name_np`` / ``full_name_en`` / ``full_name_romanized``
    using ``icontains``; the GIN trigram indexes carry the performance. Never
    ``__exact`` on a Devanagari name.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        Q(full_name_np__icontains=query) | Q(full_name_en__icontains=query) | Q(full_name_romanized__icontains=query)
    )


def filter_applicants(queryset: QuerySet[Applicant], filters: dict[str, Any] | None = None) -> QuerySet[Applicant]:
    """Apply the documented list filters.

    Recognised keys: ``status``, ``creation_source``, ``search``, and
    ``fiscal_year`` (``YYYY/YY``, Nepali fiscal year — §39.4).
    """
    filters = filters or {}

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    creation_source = filters.get("creation_source")
    if creation_source:
        queryset = queryset.filter(creation_source=creation_source)

    search = filters.get("search")
    if search:
        queryset = search_applicants(queryset, search)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    return queryset


def get_history_for_applicant(applicant: Applicant) -> QuerySet[AuditEvent]:
    """An applicant's chronological history, newest first.

    Reads the central audit log rather than any table this app owns (§4).
    """
    return get_events(
        {
            "app": AUDIT_APP_LABEL,
            "entity_type": AUDIT_ENTITY_APPLICANT,
            "entity_id": str(applicant.id),
        }
    )
