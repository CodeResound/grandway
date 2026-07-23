"""Read-only query logic for the leads app (no side effects, no business rules).

Owner scoping lives here, not in the views: every lead queryset is narrowed to
what the actor may see *in the database*, so a Lead Manager can never read
another Lead Manager's lead by any path (§9, ``docs/SECURITY.md`` §1).
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from django.db.models import Q, QuerySet

from leads.access import is_admin
from leads.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_LEAD
from leads.models import Lead, LeadNote, LeadSource, LossReason

# ---------------------------------------------------------------------------
# Reference configuration
# ---------------------------------------------------------------------------


def get_lead_sources(*, include_inactive: bool = False) -> QuerySet[LeadSource]:
    """Lead sources in display order. Inactive entries are hidden by default."""
    queryset = LeadSource.objects.all()
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return queryset


def get_loss_reasons(*, include_inactive: bool = False) -> QuerySet[LossReason]:
    """Loss reasons in display order. Inactive entries are hidden by default."""
    queryset = LossReason.objects.all()
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return queryset


def get_lead_source_by_id(source_id: str) -> LeadSource | None:
    return LeadSource.objects.filter(pk=source_id).first()


def get_loss_reason_by_id(reason_id: str) -> LossReason | None:
    return LossReason.objects.filter(pk=reason_id).first()


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


def get_leads_for_actor(actor: Any) -> QuerySet[Lead]:
    """Every lead the actor may see: all of them for an Admin, own for a Lead Manager.

    ``select_related``/``prefetch_related`` are applied here so list rendering
    never issues a query per row (§6, N+1 prevention).
    """
    queryset = Lead.objects.select_related("source", "created_by").prefetch_related("contact_numbers")
    if is_admin(actor):
        return queryset
    return queryset.filter(created_by=actor)


def get_lead_for_actor(actor: Any, lead_id: str) -> Lead | None:
    """One in-scope lead with its detail relations, or None.

    Returning None for both "missing" and "not yours" is deliberate — the view
    turns either into 404, so ownership is never disclosed.
    """
    return (
        get_leads_for_actor(actor)
        .select_related("study_interest", "lost_reason", "last_followed_up_by", "lost_by", "converted_by")
        .filter(pk=lead_id)
        .first()
    )


def search_leads(queryset: QuerySet[Lead], query: str) -> QuerySet[Lead]:
    """Narrow leads by name across all three language representations (§39.6).

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


def filter_leads(queryset: QuerySet[Lead], filters: dict[str, Any] | None = None) -> QuerySet[Lead]:
    """Apply the documented list filters.

    Recognised keys: ``stage``, ``source`` (id), ``search``, and ``fiscal_year``
    (``YYYY/YY``, Nepali fiscal year — §39.4).
    """
    filters = filters or {}

    stage = filters.get("stage")
    if stage:
        queryset = queryset.filter(stage=stage)

    source = filters.get("source")
    if source:
        queryset = queryset.filter(source_id=source)

    search = filters.get("search")
    if search:
        queryset = search_leads(queryset, search)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    return queryset


# ---------------------------------------------------------------------------
# Notes and history
# ---------------------------------------------------------------------------


def get_notes_for_lead(lead: Lead) -> QuerySet[LeadNote]:
    """A lead's notes, newest first, with authors joined."""
    return LeadNote.objects.filter(lead=lead).select_related("author")


def get_history_for_lead(lead: Lead) -> QuerySet[AuditEvent]:
    """A lead's chronological history, newest first.

    Reads the central audit log rather than any table this app owns — the
    history *is* the audit trail, filtered to one lead (§4: leads consumes
    ``audit``'s selector rather than duplicating its storage).
    """
    return get_events(
        {
            "app": AUDIT_APP_LABEL,
            "entity_type": AUDIT_ENTITY_LEAD,
            "entity_id": str(lead.id),
        }
    )
