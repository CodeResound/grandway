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

from datetime import date, timedelta
from typing import Any

from core.querying import narrow_to_window
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
# Dashboard summaries
# ---------------------------------------------------------------------------
#
# Aggregates over this app's own rows, living here because §4 forbids another
# app querying these tables directly. ``dashboards`` composes what it gets back.
#
# The overdue rule below is the one already used by ``filter_checklists``'s
# ``overdue`` branch and is not re-derived: a completed, waived, or archived
# item is never overdue however long its due date has passed, because overdue
# means *the work is late*, not *the date passed*.

#: Checklist statuses whose items still represent outstanding work. A completed
#: or archived checklist's items are finished, whatever their own status says.
_LIVE_CHECKLIST_STATUSES: tuple[str, ...] = (ChecklistStatus.DRAFT, ChecklistStatus.ACTIVE)


def _live_items() -> QuerySet[ChecklistItem]:
    """Items on a live checklist that are not yet resolved, with owners joined."""
    return (
        ChecklistItem.objects.select_related(
            "checklist",
            "checklist__journey",
            "checklist__journey__applicant",
            "checklist__country",
            "assigned_to",
        )
        .filter(checklist__status__in=_LIVE_CHECKLIST_STATUSES)
        .exclude(status__in=RESOLVED_ITEM_STATUSES)
    )


def get_checklist_status_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> dict[str, int]:
    """How many checklists hold each status. Every status present, zero-filled."""
    queryset = narrow_to_window(
        Checklist.objects.all(),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    if country_id:
        queryset = queryset.filter(country_id=country_id)

    counted = dict(queryset.values_list("status").annotate(total=Count("id")))
    return {status: counted.get(status, 0) for status in ChecklistStatus.values}


def get_overdue_checklist_items(
    *,
    country_id: str | None = None,
    assignee_id: str | None = None,
) -> QuerySet[ChecklistItem]:
    """Unresolved items on live checklists whose due date has passed, oldest first.

    The single most useful worklist in the system: every row is a specific
    requirement, on a specific person's file, that someone should already have
    dealt with.

    ``blocked`` items are **included** — a requirement stuck on something
    outside the office's control is still not done, and is exactly the kind of
    thing that quietly stops a file from moving. ``ChecklistItem.is_resolved``
    makes the same call for the same reason.
    """
    queryset = _live_items().filter(due_at__isnull=False, due_at__lt=timezone.now())
    if country_id:
        queryset = queryset.filter(checklist__country_id=country_id)
    if assignee_id:
        queryset = queryset.filter(assigned_to_id=assignee_id)
    return queryset.order_by("due_at", "id")


def get_due_soon_checklist_items(
    *,
    due_within_days: int = 7,
    country_id: str | None = None,
    assignee_id: str | None = None,
) -> QuerySet[ChecklistItem]:
    """Unresolved items falling due within ``due_within_days``, soonest first.

    Strictly forward-looking: already-overdue items are **excluded** so they
    appear once, in ``get_overdue_checklist_items``, rather than in both lists.
    A dashboard that double-counted them would overstate the backlog.
    """
    now = timezone.now()
    horizon = now + timedelta(days=due_within_days)
    queryset = _live_items().filter(due_at__gte=now, due_at__lte=horizon)
    if country_id:
        queryset = queryset.filter(checklist__country_id=country_id)
    if assignee_id:
        queryset = queryset.filter(assigned_to_id=assignee_id)
    return queryset.order_by("due_at", "id")


def get_blocked_checklist_items(
    *,
    country_id: str | None = None,
    assignee_id: str | None = None,
) -> QuerySet[ChecklistItem]:
    """Items someone has explicitly declared stuck, newest first.

    Distinct from overdue: a blocked item may not be late at all. It is the one
    status meaning "we cannot proceed on this", and it is a claim a human made
    deliberately — ``status_note`` carries why, and is mandatory for this status.
    """
    queryset = (
        ChecklistItem.objects.select_related(
            "checklist",
            "checklist__journey",
            "checklist__journey__applicant",
            "checklist__country",
            "assigned_to",
        )
        .filter(checklist__status__in=_LIVE_CHECKLIST_STATUSES, status=ItemStatus.BLOCKED)
        .order_by("-updated_at", "-id")
    )
    if country_id:
        queryset = queryset.filter(checklist__country_id=country_id)
    if assignee_id:
        queryset = queryset.filter(assigned_to_id=assignee_id)
    return queryset


def get_checklist_workload_by_assignee(
    *,
    country_id: str | None = None,
) -> list[dict[str, Any]]:
    """Open, overdue, and blocked item counts per assignee, heaviest first.

    Unassigned items are returned under a null owner rather than dropped. Work
    nobody owns is the most likely to be missed, and a workload view that hid it
    would hide the worst case it exists to surface.
    """
    queryset = _live_items()
    if country_id:
        queryset = queryset.filter(checklist__country_id=country_id)

    now = timezone.now()
    rows = (
        queryset.values("assigned_to_id", "assigned_to__username", "assigned_to__display_name")
        .annotate(
            open_items=Count("id"),
            overdue_items=Count("id", filter=Q(due_at__isnull=False, due_at__lt=now)),
            blocked_items=Count("id", filter=Q(status=ItemStatus.BLOCKED)),
        )
        .order_by("-overdue_items", "-open_items")
    )
    return [
        {
            "owner_id": str(row["assigned_to_id"]) if row["assigned_to_id"] else None,
            "owner_username": row["assigned_to__username"] or "",
            "owner_display_name": row["assigned_to__display_name"] or "Unassigned",
            "open_items": row["open_items"],
            "overdue_items": row["overdue_items"],
            "blocked_items": row["blocked_items"],
        }
        for row in rows
    ]


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
