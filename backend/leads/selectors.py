"""Read-only query logic for the leads app (no side effects, no business rules).

Owner scoping lives here, not in the views: every lead queryset is narrowed to
what the actor may see *in the database*, so a Lead Manager can never read
another Lead Manager's lead by any path (§9, ``docs/SECURITY.md`` §1).
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from django.db.models import Case, IntegerField, Q, QuerySet, When

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


#: The three language representations of a lead's name (§39.1), searched
#: together. Mirrors ``applicants.selectors._NAME_FIELDS`` — the two apps hold
#: the same person at two stages of their life and are searched the same way.
_NAME_FIELDS = ("full_name_np", "full_name_en", "full_name_romanized")


def _name_match(query: str) -> Q:
    """OR across the three name representations with ``icontains`` (§39.6)."""
    matches = Q()
    for field in _NAME_FIELDS:
        matches |= Q(**{f"{field}__icontains": query})
    return matches


def search_leads(queryset: QuerySet[Lead], query: str) -> QuerySet[Lead]:
    """Narrow leads by name, email, or contact number.

    Names are matched across all three language representations with
    ``icontains``; the GIN trigram indexes carry the performance and ``__exact``
    is never used on a Devanagari name (§39.6). Phone and email matter more here
    than anywhere else in the project — a lead is very often a number in a call
    log before anyone has agreed how to spell the name.

    ``contact_numbers`` is a reverse foreign key, so a person with three numbers
    would otherwise appear three times — hence ``distinct()``.

    There is no destination filter: a lead's countries of interest live in
    ``LeadStudyInterest.interested_countries``, a ``JSONField`` whose ``contains``
    lookup is PostgreSQL-only and would fail the SQLite test suite. Recorded in
    ``docs/INTEGRATION.md`` §9 `Gaps`.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        _name_match(query) | Q(email__icontains=query) | Q(contact_numbers__number__icontains=query)
    ).distinct()


def rank_leads(queryset: QuerySet[Lead], query: str) -> QuerySet[Lead]:
    """Order a searched queryset by how well each row matches the query.

    Identical scoring to ``applicants.selectors.rank_applicants`` — see its
    docstring for why the score is a portable ``Case``/``When`` rather than
    ``TrigramSimilarity``:

    * ``3`` — a name field equals the query outright
    * ``2`` — a name field starts with it
    * ``1`` — a name field contains it
    * ``0`` — matched only on email or contact number
    """
    query = (query or "").strip()
    if not query:
        return queryset

    exact = Q()
    prefix = Q()
    for field in _NAME_FIELDS:
        exact |= Q(**{f"{field}__iexact": query})
        prefix |= Q(**{f"{field}__istartswith": query})

    return queryset.annotate(
        relevance=Case(
            When(exact, then=3),
            When(prefix, then=2),
            When(_name_match(query), then=1),
            default=0,
            output_field=IntegerField(),
        )
    ).order_by("-relevance", "-created_at", "-id")


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
