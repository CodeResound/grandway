"""Read-only query logic for the applicant_journeys app (no side effects).

Journeys are shared across the consultancy, so there is no owner scoping here.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from audit.selectors import get_events_for_entity
from core.querying import narrow_to_window
from django.db.models import Count, QuerySet

if TYPE_CHECKING:
    # Annotation only. Importing another app's model at runtime for anything but
    # a ForeignKey is the coupling §4 forbids; the audit selector returns the
    # queryset, this app never touches the model.
    from audit.models import AuditEvent

from applicant_journeys.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_JOURNEY,
    JourneyOutcome,
    JourneyStage,
)
from applicant_journeys.models import ApplicantJourney


def get_journeys() -> QuerySet[ApplicantJourney]:
    """Every journey, newest first, with the applicant joined (§6, N+1 prevention)."""
    return ApplicantJourney.objects.select_related("applicant", "created_by", "target_country_ref")


def get_journey_by_id(journey_id: str) -> ApplicantJourney | None:
    """One journey with its detail relations, or None."""
    return (
        ApplicantJourney.objects.select_related(
            "applicant",
            "created_by",
            "closed_by",
            "deferred_by",
            "target_country_ref",
        )
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

    Recognised keys: ``applicant``, ``stage``, ``target_country``,
    ``target_country_ref``, and ``fiscal_year`` (``YYYY/YY``, Nepali fiscal
    year — §39.4).
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

    # The exact filter, separate from the free-text one above: a client that
    # holds a catalogue id should never have to guess how the name was typed.
    target_country_ref = filters.get("target_country_ref")
    if target_country_ref:
        queryset = queryset.filter(target_country_ref_id=target_country_ref)

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
# app querying this table directly. ``dashboards`` composes what it gets back.
#
# Journeys are shared across the consultancy, so none of these take an ``actor``.


def _narrow(
    queryset: QuerySet[ApplicantJourney],
    *,
    field: str,
    date_from: date | None,
    date_to: date | None,
    fiscal_year: str | None,
    country_id: str | None,
) -> QuerySet[ApplicantJourney]:
    """The filters every journey summary shares."""
    queryset = narrow_to_window(
        queryset,
        field=field,
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    if country_id:
        queryset = queryset.filter(target_country_ref_id=country_id)
    return queryset


def get_journey_stage_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> dict[str, int]:
    """How many journeys sit at each stage.

    Every stage is present with a zero rather than omitted, so a pipeline view
    shows the empty stages as empty rather than as though they did not exist.

    Counted by **creation** date, which makes this "of the journeys started in
    this window, where has each got to". A journey that has been running for
    two years is absent from a one-month window even though it is live today —
    the alternative, ignoring the window entirely, would make the date controls
    silently inert on this section.
    """
    queryset = _narrow(
        ApplicantJourney.objects.all(),
        field="created_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
    )
    counted = dict(queryset.values_list("stage").annotate(total=Count("id")))
    return {stage: counted.get(stage, 0) for stage in JourneyStage.values}


def get_journey_outcome_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> dict[str, int]:
    """How many journeys ended each way, windowed on **when they closed**.

    Deliberately not windowed on creation: "how many journeys ended
    successfully in Shrawan" is a question about the ending, and a journey
    started last year and finished this month belongs in this month's outcomes.
    That is why this reads ``closed_at`` while
    ``get_journey_stage_counts`` reads ``created_at``.

    Only closed journeys carry an outcome, so a live journey contributes to
    nothing here. Every outcome is present with a zero.
    """
    queryset = _narrow(
        ApplicantJourney.objects.exclude(outcome=""),
        field="closed_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
    )
    counted = dict(queryset.values_list("outcome").annotate(total=Count("id")))
    return {outcome: counted.get(outcome, 0) for outcome in JourneyOutcome.values}


def count_journeys(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
    with_country_only: bool = False,
) -> int:
    """How many journeys exist in the window.

    ``with_country_only`` restricts to journeys naming a catalogue country —
    the denominator for "how much of the pipeline is machine-readable", and the
    population that inherits a checklist at all.
    """
    queryset = _narrow(
        ApplicantJourney.objects.all(),
        field="created_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
    )
    if with_country_only:
        queryset = queryset.filter(target_country_ref__isnull=False)
    return queryset.count()


def count_applicants_with_a_journey(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> int:
    """How many distinct applicants hold at least one journey in the window.

    The numerator for applicant-to-journey conversion. Distinct on the
    applicant, because a person pursuing three objectives converted once.
    """
    queryset = _narrow(
        ApplicantJourney.objects.all(),
        field="created_at",
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
        country_id=country_id,
    )
    return queryset.values("applicant_id").distinct().count()


def get_history_for_journey(journey: ApplicantJourney) -> QuerySet[AuditEvent]:
    """A journey's chronological history, newest first, from the central audit log."""
    return get_events_for_entity(
        entity_type=AUDIT_ENTITY_JOURNEY,
        entity_id=str(journey.id),
        app_label=AUDIT_APP_LABEL,
    )
