"""Read-only query logic for the applicant_journeys app (no side effects).

Journeys are shared across the consultancy, so there is no owner scoping here.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from audit.selectors import get_events
from django.db.models import QuerySet

from applicant_journeys.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_JOURNEY
from applicant_journeys.models import ApplicantJourney


def get_journeys() -> QuerySet[ApplicantJourney]:
    """Every journey, newest first, with the applicant joined (§6, N+1 prevention)."""
    return ApplicantJourney.objects.select_related("applicant", "created_by")


def get_journey_by_id(journey_id: str) -> ApplicantJourney | None:
    """One journey with its detail relations, or None."""
    return (
        ApplicantJourney.objects.select_related("applicant", "created_by", "closed_by", "deferred_by")
        .filter(pk=journey_id)
        .first()
    )


def get_journeys_for_applicant(applicant_id: str) -> QuerySet[ApplicantJourney]:
    """One applicant's journeys, newest first."""
    return get_journeys().filter(applicant_id=applicant_id)


def filter_journeys(
    queryset: QuerySet[ApplicantJourney],
    filters: dict[str, Any] | None = None,
) -> QuerySet[ApplicantJourney]:
    """Apply the documented list filters.

    Recognised keys: ``applicant``, ``stage``, ``target_country``, and
    ``fiscal_year`` (``YYYY/YY``, Nepali fiscal year — §39.4).
    """
    filters = filters or {}

    applicant = filters.get("applicant")
    if applicant:
        queryset = queryset.filter(applicant_id=applicant)

    stage = filters.get("stage")
    if stage:
        queryset = queryset.filter(stage=stage)

    target_country = filters.get("target_country")
    if target_country:
        queryset = queryset.filter(target_country__icontains=target_country)

    fiscal_year = filters.get("fiscal_year")
    if fiscal_year:
        from core.nepal.calendar import fiscal_year_gregorian_range

        start, end = fiscal_year_gregorian_range(fiscal_year)
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)

    return queryset


def get_history_for_journey(journey: ApplicantJourney) -> QuerySet[AuditEvent]:
    """A journey's chronological history, newest first, from the central audit log."""
    return get_events(
        {
            "app": AUDIT_APP_LABEL,
            "entity_type": AUDIT_ENTITY_JOURNEY,
            "entity_id": str(journey.id),
        }
    )
