"""Read-only query logic for the offers app (no side effects).

Offers are shared across the consultancy exactly as journeys are, so there is
no owner scoping here.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from core.nepal.calendar import nepal_today
from core.querying import narrow_to_window
from django.db.models import Count, QuerySet

from offers.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_OFFER,
    TERMINAL_STATUSES,
    OfferStatus,
)
from offers.models import Offer, OfferCondition

#: Relations every offer read needs. ``journey__applicant`` is here because the
#: Offer List's first column is the applicant's name (``concepts/offers.txt`` —
#: "Offer List"), and reaching it through the journey is two joins that would
#: otherwise fire once per row.
_OFFER_RELATIONS = ("journey", "journey__applicant", "institution", "campus", "program", "created_by")


def get_offers() -> QuerySet[Offer]:
    """Every offer, newest first, with list relations joined (§6, N+1 prevention).

    ``conditions`` is prefetched because the list shows whether an offer still
    has open conditions; without it, ``has_open_conditions`` would fire one
    query per row.
    """
    return Offer.objects.select_related(*_OFFER_RELATIONS).prefetch_related("conditions")


def get_offer_by_id(offer_id: str) -> Offer | None:
    """One offer with its detail relations, or None."""
    return (
        Offer.objects.select_related(*_OFFER_RELATIONS, "decided_by")
        .prefetch_related("conditions", "conditions__resolved_by")
        .filter(pk=offer_id)
        .first()
    )


def get_offers_for_journey(journey_id: str) -> QuerySet[Offer]:
    """One journey's offers, newest first — the Journey Detail offers panel."""
    return get_offers().filter(journey_id=journey_id)


def get_accepted_offer_for_journey(journey_id: str, exclude_offer_id: str | None = None) -> Offer | None:
    """The journey's accepted offer, if it already has one.

    Backs the single rule this app enforces on multiplicity: a journey may hold
    any number of competing offers, but only one of them can be the one taken.
    """
    from offers.constants import OfferStatus

    queryset = Offer.objects.filter(journey_id=journey_id, status=OfferStatus.ACCEPTED)
    if exclude_offer_id:
        queryset = queryset.exclude(pk=exclude_offer_id)
    return queryset.first()


def filter_offers(queryset: QuerySet[Offer], filters: dict[str, Any] | None = None) -> QuerySet[Offer]:
    """Apply the documented list filters.

    Recognised keys: ``journey``, ``applicant``, ``status``, ``offer_type``,
    ``institution``, ``program``, ``intake``, ``deadline_before``, and
    ``fiscal_year`` (``YYYY/YY``, Nepali fiscal year — §39.4).

    ``institution`` and ``program`` match the catalogue foreign key, not the
    snapshot text: they are fed by catalogue pickers. A manually recorded offer
    has no catalogue link and is therefore correctly absent from such a filter —
    use ``?q``-style text search on the list only once it exists (see
    ``docs/INTEGRATION.md`` §9 `Gaps`).
    """
    filters = filters or {}

    journey = filters.get("journey")
    if journey:
        queryset = queryset.filter(journey_id=journey)

    applicant = filters.get("applicant")
    if applicant:
        queryset = queryset.filter(journey__applicant_id=applicant)

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    offer_type = filters.get("offer_type")
    if offer_type:
        queryset = queryset.filter(offer_type=offer_type)

    institution = filters.get("institution")
    if institution:
        queryset = queryset.filter(institution_id=institution)

    program = filters.get("program")
    if program:
        queryset = queryset.filter(program_id=program)

    intake = filters.get("intake")
    if intake:
        queryset = queryset.filter(intake_label__icontains=intake)

    deadline_before = filters.get("deadline_before")
    if deadline_before:
        queryset = queryset.filter(response_deadline__isnull=False, response_deadline__lte=deadline_before)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    return queryset


# ---------------------------------------------------------------------------
# Dashboard summaries
# ---------------------------------------------------------------------------
#
# Aggregates over this app's own rows, living here because §4 forbids another
# app querying these tables directly. ``dashboards`` composes what it gets back.
#
# Offers are shared across the consultancy, so none of these take an ``actor``.


def _narrow_offers(
    queryset: QuerySet[Offer],
    *,
    field: str,
    date_from: date | None,
    date_to: date | None,
    fiscal_year: str | None,
    country_id: str | None,
    institution_id: str | None,
) -> QuerySet[Offer]:
    """The filters every offer summary shares.

    ``country_id`` resolves through the journey's catalogue destination, not
    through the offer's own ``country_name`` snapshot. The snapshot is free text
    preserved for the historical record and would not match a catalogue id.
    """
    queryset = narrow_to_window(
        queryset,
        field=field,
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    if country_id:
        queryset = queryset.filter(journey__target_country_ref_id=country_id)
    if institution_id:
        queryset = queryset.filter(institution_id=institution_id)
    return queryset


def get_offer_status_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
    institution_id: str | None = None,
) -> dict[str, int]:
    """How many offers hold each status, windowed on when they were recorded.

    Every status is present with a zero rather than omitted.
    """
    queryset = _narrow_offers(
        Offer.objects.all(),
        field="created_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
        institution_id=institution_id,
    )
    counted = dict(queryset.values_list("status").annotate(total=Count("id")))
    return {status: counted.get(status, 0) for status in OfferStatus.values}


def get_decision_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
    institution_id: str | None = None,
) -> dict[str, int]:
    """How many offers were **decided** each way in the window.

    Windowed on ``decided_at``, not ``created_at``: "offers accepted in
    Shrawan" is a question about when the applicant answered, and an offer
    issued in Ashadh and accepted in Shrawan belongs to Shrawan. Undecided
    offers have a null ``decided_at`` and are absent from every bucket.
    """
    queryset = _narrow_offers(
        Offer.objects.filter(decided_at__isnull=False),
        field="decided_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
        institution_id=institution_id,
    )
    counted = dict(queryset.values_list("status").annotate(total=Count("id")))
    return {status: counted.get(status, 0) for status in TERMINAL_STATUSES}


def get_offers_awaiting_response(
    *,
    due_within_days: int = 7,
    country_id: str | None = None,
    institution_id: str | None = None,
) -> QuerySet[Offer]:
    """Issued offers whose response deadline has passed or falls soon, soonest first.

    Mirrors ``Offer.is_response_overdue`` (``models.py``) rather than
    re-deriving what "overdue" means: only an ``issued`` offer can be overdue,
    and the comparison is against today in **Nepal** (§39.5) — a deadline is a
    calendar day where the staff work, not in UTC.

    Already-passed deadlines are included alongside the merely-approaching ones.
    Splitting them into two queries would put the most urgent rows in the
    section a user reads second; the caller distinguishes them by comparing
    ``response_deadline`` to today.

    Offers with **no** deadline are excluded. Nothing is late about a deadline
    that was never set, and including them would make this list unactionable.
    """
    horizon = nepal_today() + timedelta(days=due_within_days)
    queryset = (
        Offer.objects.select_related("journey", "journey__applicant", "institution", "created_by")
        .filter(
            status=OfferStatus.ISSUED,
            response_deadline__isnull=False,
            response_deadline__lte=horizon,
        )
        .order_by("response_deadline", "id")
    )
    if country_id:
        queryset = queryset.filter(journey__target_country_ref_id=country_id)
    if institution_id:
        queryset = queryset.filter(institution_id=institution_id)
    return queryset


def get_offer_workload_by_owner(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> list[dict[str, Any]]:
    """Offers still awaiting a response, per the staff member who recorded them.

    ``created_by`` is the only ownership this app records — there is no assignee
    on an offer — so "whose offer is this" means "who entered it". A caller
    presenting this as workload should say "recorded by", not "assigned to".
    """
    queryset = _narrow_offers(
        Offer.objects.filter(status=OfferStatus.ISSUED),
        field="created_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
        institution_id=None,
    )
    rows = (
        queryset.values("created_by_id", "created_by__username", "created_by__display_name")
        .annotate(awaiting_response=Count("id"))
        .order_by("-awaiting_response")
    )
    return [
        {
            "owner_id": str(row["created_by_id"]),
            "owner_username": row["created_by__username"],
            "owner_display_name": row["created_by__display_name"],
            "awaiting_response": row["awaiting_response"],
        }
        for row in rows
    ]


def count_journeys_with_an_offer(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> int:
    """How many distinct journeys hold at least one offer in the window.

    The numerator for journey-to-offer conversion. Distinct on the journey,
    because a study plan that collected four competing offers converted once.
    """
    queryset = _narrow_offers(
        Offer.objects.all(),
        field="created_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
        institution_id=None,
    )
    return queryset.values("journey_id").distinct().count()


def get_conditions_for_offer(offer_id: str) -> QuerySet[OfferCondition]:
    """One offer's conditions in display order."""
    return OfferCondition.objects.select_related("resolved_by").filter(offer_id=offer_id)


def get_condition_by_id(condition_id: str) -> OfferCondition | None:
    """One condition with its offer joined, or None.

    The offer comes along because every condition action is authorised and
    audited against the parent offer, never the condition alone.
    """
    return OfferCondition.objects.select_related("offer", "resolved_by").filter(pk=condition_id).first()


def get_history_for_offer(offer: Offer) -> QuerySet[AuditEvent]:
    """An offer's chronological history, newest first, from the central audit log.

    Includes condition events: they are recorded against the offer's entity id
    so that the offer's history is one continuous trail rather than several.
    """
    return get_events(
        {
            "app": AUDIT_APP_LABEL,
            "entity_type": AUDIT_ENTITY_OFFER,
            "entity_id": str(offer.id),
        }
    )
