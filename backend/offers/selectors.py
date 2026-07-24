"""Read-only query logic for the offers app (no side effects).

Offers are shared across the consultancy exactly as journeys are, so there is
no owner scoping here.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from django.db.models import QuerySet

from offers.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_OFFER
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
