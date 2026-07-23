"""Read-only query logic for the institutions app (no side effects).

The catalogue is shared across the consultancy, so there is no owner scoping
here. Every list selector joins its display relations up front — a program row
shows its institution, campus, field, and country, which is four extra queries
per row without ``select_related`` (§6, N+1 prevention).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from institutions.constants import USABLE_STATUSES
from institutions.models import Campus, Country, Field, Institution, Program

# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


def get_fields() -> QuerySet[Field]:
    """Every study field, in display order."""
    return Field.objects.all()


def get_field_by_id(field_id: str) -> Field | None:
    """One study field, or None."""
    return Field.objects.filter(pk=field_id).first()


def filter_fields(queryset: QuerySet[Field], filters: dict[str, Any] | None = None) -> QuerySet[Field]:
    """Recognised keys: ``is_active`` (bool), ``q`` (name substring)."""
    filters = filters or {}

    is_active = filters.get("is_active")
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)

    query = filters.get("q")
    if query:
        queryset = queryset.filter(Q(name_en__icontains=query) | Q(name_np__icontains=query))

    return queryset


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------


def get_countries() -> QuerySet[Country]:
    """Every country, in display order."""
    return Country.objects.all()


def get_country_by_id(country_id: str) -> Country | None:
    """One country, or None."""
    return Country.objects.filter(pk=country_id).first()


def filter_countries(queryset: QuerySet[Country], filters: dict[str, Any] | None = None) -> QuerySet[Country]:
    """Recognised keys: ``availability_status``, ``usable_only`` (bool), ``q``."""
    filters = filters or {}

    status = filters.get("availability_status")
    if status:
        queryset = queryset.filter(availability_status=status)
    elif filters.get("usable_only"):
        queryset = queryset.filter(availability_status__in=USABLE_STATUSES)

    query = filters.get("q")
    if query:
        queryset = queryset.filter(Q(name_en__icontains=query) | Q(name_np__icontains=query))

    return queryset


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------


def get_institutions() -> QuerySet[Institution]:
    """Every institution with its country joined."""
    return Institution.objects.select_related("country")


def get_institution_by_id(institution_id: str) -> Institution | None:
    """One institution with its country, or None."""
    return Institution.objects.select_related("country").filter(pk=institution_id).first()


def filter_institutions(
    queryset: QuerySet[Institution],
    filters: dict[str, Any] | None = None,
) -> QuerySet[Institution]:
    """Recognised keys: ``country``, ``institution_type``, ``availability_status``,
    ``usable_only`` (bool), ``q`` (trigram-backed name search)."""
    filters = filters or {}

    country = filters.get("country")
    if country:
        queryset = queryset.filter(country_id=country)

    institution_type = filters.get("institution_type")
    if institution_type:
        queryset = queryset.filter(institution_type=institution_type)

    status = filters.get("availability_status")
    if status:
        queryset = queryset.filter(availability_status=status)
    elif filters.get("usable_only"):
        queryset = queryset.filter(availability_status__in=USABLE_STATUSES)

    query = filters.get("q")
    if query:
        # ``icontains`` over the trigram GIN indexes (§39.6) — never ``exact``.
        queryset = queryset.filter(
            Q(name_en__icontains=query) | Q(name_np__icontains=query) | Q(common_name__icontains=query)
        )

    return queryset


# ---------------------------------------------------------------------------
# Campus
# ---------------------------------------------------------------------------


def get_campuses() -> QuerySet[Campus]:
    """Every campus with its institution joined."""
    return Campus.objects.select_related("institution")


def get_campus_by_id(campus_id: str) -> Campus | None:
    """One campus with its institution and country, or None."""
    return Campus.objects.select_related("institution", "institution__country").filter(pk=campus_id).first()


def get_campuses_for_institution(institution_id: str) -> QuerySet[Campus]:
    """One institution's campuses."""
    return get_campuses().filter(institution_id=institution_id)


def filter_campuses(queryset: QuerySet[Campus], filters: dict[str, Any] | None = None) -> QuerySet[Campus]:
    """Recognised keys: ``availability_status``, ``usable_only`` (bool), ``q``."""
    filters = filters or {}

    status = filters.get("availability_status")
    if status:
        queryset = queryset.filter(availability_status=status)
    elif filters.get("usable_only"):
        queryset = queryset.filter(availability_status__in=USABLE_STATUSES)

    query = filters.get("q")
    if query:
        queryset = queryset.filter(Q(name_en__icontains=query) | Q(city__icontains=query))

    return queryset


# ---------------------------------------------------------------------------
# Program — the shortlisting search
# ---------------------------------------------------------------------------


def get_programs() -> QuerySet[Program]:
    """Every program with every relation a list row displays.

    Four joins, because a program row shows its institution, that
    institution's country, its campus, and its field. Without them the list
    costs four queries per row.
    """
    return Program.objects.select_related("institution", "institution__country", "campus", "field")


def get_program_by_id(program_id: str) -> Program | None:
    """One program with its display relations, or None."""
    return get_programs().filter(pk=program_id).first()


def filter_programs(queryset: QuerySet[Program], filters: dict[str, Any] | None = None) -> QuerySet[Program]:
    """Apply the documented shortlisting filters.

    Recognised keys: ``country``, ``institution``, ``campus``,
    ``qualification_level``, ``field``, ``availability_status``,
    ``usable_only`` (bool), ``scholarship_available`` (bool), ``tuition_max``,
    ``q``.

    ``usable_only`` filters on the **whole chain** — a program at a paused
    institution is not offerable however active its own record is. That is why
    availability does not cascade at write time: the read path composes it.
    """
    filters = filters or {}

    country = filters.get("country")
    if country:
        queryset = queryset.filter(institution__country_id=country)

    institution = filters.get("institution")
    if institution:
        queryset = queryset.filter(institution_id=institution)

    campus = filters.get("campus")
    if campus:
        queryset = queryset.filter(campus_id=campus)

    qualification_level = filters.get("qualification_level")
    if qualification_level:
        queryset = queryset.filter(qualification_level=qualification_level)

    field = filters.get("field")
    if field:
        queryset = queryset.filter(field_id=field)

    status = filters.get("availability_status")
    if status:
        queryset = queryset.filter(availability_status=status)
    elif filters.get("usable_only"):
        queryset = queryset.filter(
            availability_status__in=USABLE_STATUSES,
            institution__availability_status__in=USABLE_STATUSES,
            institution__country__availability_status__in=USABLE_STATUSES,
        )
        # A null campus is fine; a non-usable one is not.
        queryset = queryset.filter(Q(campus__isnull=True) | Q(campus__availability_status__in=USABLE_STATUSES))

    scholarship_available = filters.get("scholarship_available")
    if scholarship_available is not None:
        queryset = queryset.filter(scholarship_available=scholarship_available)

    tuition_max = filters.get("tuition_max")
    if tuition_max is not None:
        # Programs with no recorded tuition are excluded rather than assumed
        # free — an unknown fee is not a cheap one.
        queryset = queryset.filter(tuition_amount__isnull=False, tuition_amount__lte=tuition_max)

    query = filters.get("q")
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(institution__name_en__icontains=query)
            | Q(institution__common_name__icontains=query)
        )

    return queryset


def get_programs_for_institution(institution_id: str) -> QuerySet[Program]:
    """One institution's programs."""
    return get_programs().filter(institution_id=institution_id)
