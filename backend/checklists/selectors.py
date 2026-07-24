"""Read-only query logic for the checklists app (no side effects).

Checklists are shared across the consultancy, so there is no owner scoping here
— see ``access.py`` for why.

Two things in this module carry more weight than they look:

* ``get_checklists`` **annotates progress** rather than computing it per row.
  Every list screen shows "7 of 12 done", and a property that counted items
  would fire one query per checklist on every page (§6).
* ``get_journeys_missing_checklist`` is the safety net for automatic
  inheritance. A country whose template nobody authored produces no checklist
  and no error; without this query that silence would be indistinguishable from
  success.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from checklists.constants import (
    RESOLVED_ITEM_STATUSES,
    ChecklistStatus,
    ItemStatus,
    ItemType,
    TemplateStatus,
)
from checklists.models import Checklist, ChecklistItem, ChecklistTemplate, ChecklistTemplateItem

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def get_templates() -> QuerySet[ChecklistTemplate]:
    """Every template with its country joined and its items prefetched (§6)."""
    return ChecklistTemplate.objects.select_related("country", "created_by").prefetch_related("items")


def get_template_by_id(template_id: str) -> ChecklistTemplate | None:
    """One template with its detail relations, or None."""
    return get_templates().filter(pk=template_id).first()


def get_template_by_key(key: str) -> ChecklistTemplate | None:
    """One template by its stable key, or None."""
    return get_templates().filter(key=key).first()


def get_default_template_for_country(country_id: Any) -> ChecklistTemplate | None:
    """The template a journey reaching this country inherits, or None.

    The single query automatic inheritance rests on. Returns at most one row —
    the ``checklist_one_active_default_per_country`` constraint is what makes
    that a guarantee rather than an assumption.
    """
    if not country_id:
        return None
    return (
        ChecklistTemplate.objects.select_related("country")
        .filter(country_id=country_id, is_default=True, status=TemplateStatus.ACTIVE)
        .first()
    )


def filter_templates(
    queryset: QuerySet[ChecklistTemplate],
    filters: dict[str, Any] | None = None,
) -> QuerySet[ChecklistTemplate]:
    """Apply the documented template list filters.

    Recognised keys: ``country``, ``status``, ``is_default``, ``search``.
    """
    filters = filters or {}

    country = filters.get("country")
    if country:
        queryset = queryset.filter(country_id=country)

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    is_default = filters.get("is_default")
    if is_default is not None:
        queryset = queryset.filter(is_default=is_default)

    search = filters.get("search")
    if search:
        queryset = queryset.filter(Q(label__icontains=search) | Q(key__icontains=search))

    return queryset


def get_active_template_items(template: ChecklistTemplate) -> QuerySet[ChecklistTemplateItem]:
    """The item definitions a new checklist would copy, in the author's order."""
    return template.items.filter(is_active=True).order_by("display_order", "label")


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------

#: The progress counters every list and detail response carries. Computed in one
#: aggregate pass so a page of twenty checklists stays one query.
_PROGRESS_ANNOTATIONS: dict[str, Any] = {
    "item_total": Count("items", distinct=True),
    "item_resolved": Count("items", filter=Q(items__status__in=RESOLVED_ITEM_STATUSES), distinct=True),
    "required_total": Count("items", filter=Q(items__is_required=True), distinct=True),
    "required_resolved": Count(
        "items",
        filter=Q(items__is_required=True, items__status__in=RESOLVED_ITEM_STATUSES),
        distinct=True,
    ),
    "item_blocked": Count("items", filter=Q(items__status=ItemStatus.BLOCKED), distinct=True),
    "document_total": Count("items", filter=Q(items__item_type=ItemType.DOCUMENT), distinct=True),
    "document_resolved": Count(
        "items",
        filter=Q(items__item_type=ItemType.DOCUMENT, items__status__in=RESOLVED_ITEM_STATUSES),
        distinct=True,
    ),
}


def get_checklists() -> QuerySet[Checklist]:
    """Every checklist, newest first, with its relations joined and progress annotated."""
    return (
        Checklist.objects.select_related(
            "journey",
            "journey__applicant",
            "country",
            "assigned_to",
            "source_template",
        )
        .annotate(**_PROGRESS_ANNOTATIONS)
        .order_by("-created_at", "-id")
    )


def get_checklist_by_id(checklist_id: str) -> Checklist | None:
    """One checklist with its detail relations and progress, or None."""
    return get_checklists().filter(pk=checklist_id).first()


def get_checklists_for_journey(journey_id: str) -> QuerySet[Checklist]:
    """One journey's checklists, newest first."""
    return get_checklists().filter(journey_id=journey_id)


def get_live_checklist_from_template(journey_id: Any, template_id: Any) -> Checklist | None:
    """An existing, non-archived checklist on this journey from this template.

    The idempotency check behind automatic inheritance: re-saving a journey must
    never produce a second copy of the same list. Archived checklists are
    excluded deliberately — archiving one is how staff ask for a fresh start.
    """
    return (
        Checklist.objects.filter(
            journey_id=journey_id,
            source_template_id=template_id,
        )
        .exclude(status=ChecklistStatus.ARCHIVED)
        .first()
    )


def filter_checklists(
    queryset: QuerySet[Checklist],
    filters: dict[str, Any] | None = None,
) -> QuerySet[Checklist]:
    """Apply the documented checklist list filters.

    Recognised keys: ``applicant``, ``journey``, ``status``, ``assigned_to``,
    ``country``, ``template``, ``origin``, ``overdue``.

    ``applicant`` traverses the journey rather than existing as a column. That
    is the whole reason a client can render "this applicant's checklist" without
    knowing which journey it hangs off.
    """
    filters = filters or {}

    applicant = filters.get("applicant")
    if applicant:
        queryset = queryset.filter(journey__applicant_id=applicant)

    journey = filters.get("journey")
    if journey:
        queryset = queryset.filter(journey_id=journey)

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    assigned_to = filters.get("assigned_to")
    if assigned_to:
        queryset = queryset.filter(assigned_to_id=assigned_to)

    country = filters.get("country")
    if country:
        queryset = queryset.filter(country_id=country)

    template = filters.get("template")
    if template:
        queryset = queryset.filter(source_template_id=template)

    origin = filters.get("origin")
    if origin:
        queryset = queryset.filter(origin=origin)

    if filters.get("overdue"):
        # Overdue means the *work* is late, so a completed or archived checklist
        # is never overdue however long its due date has passed.
        queryset = queryset.filter(
            due_at__lt=timezone.now(),
            status__in=(ChecklistStatus.DRAFT, ChecklistStatus.ACTIVE),
        )

    return queryset


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def get_items_for_checklist(checklist_id: str) -> QuerySet[ChecklistItem]:
    """One checklist's items in the author's order, with evidence joined."""
    return (
        ChecklistItem.objects.select_related("assigned_to", "completed_by", "evidence_file")
        .filter(checklist_id=checklist_id)
        .order_by("display_order", "created_at")
    )


def get_item_by_id(checklist_id: str, item_id: str) -> ChecklistItem | None:
    """One item, scoped to its checklist so a stray id cannot reach another applicant."""
    return get_items_for_checklist(checklist_id).filter(pk=item_id).first()


def get_unresolved_required_items(checklist: Checklist) -> QuerySet[ChecklistItem]:
    """Required items still standing in the way of completion.

    What ``complete_checklist`` refuses on, and what the error names back to the
    client. ``blocked`` counts as unresolved — see ``ChecklistItem.is_resolved``.
    """
    return checklist.items.filter(is_required=True).exclude(status__in=RESOLVED_ITEM_STATUSES)


# ---------------------------------------------------------------------------
# The safety net
# ---------------------------------------------------------------------------


def get_journeys_missing_checklist() -> QuerySet[Any]:
    """Active journeys that name a country but hold no checklist.

    Automatic inheritance is silent when a country has no default template —
    correctly so, since an empty list is worse than none. This query is what
    keeps that silence from reading as success: every journey in it is an
    applicant whose destination nobody has authored requirements for yet.

    Imports the journey model locally, so a module-level import of this app's
    selectors never drags in another app's models at load time.
    """
    from applicant_journeys.models import ApplicantJourney

    return (
        ApplicantJourney.objects.select_related("applicant", "target_country_ref")
        .filter(target_country_ref__isnull=False)
        .exclude(checklists__status__in=(ChecklistStatus.DRAFT, ChecklistStatus.ACTIVE, ChecklistStatus.COMPLETED))
        .order_by("-created_at", "-id")
    )
