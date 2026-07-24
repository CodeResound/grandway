"""Read-only query logic for the applicants app (no side effects, no business rules).

Unlike ``leads.selectors``, there is no owner scoping here — applicants are
shared across the consultancy (``docs/SECURITY.md`` §1). The authority check
that matters (Superadmin denied) happens in the view via ``access.py``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from audit.selectors import get_events_for_entity
from core.nepal.calendar import nepal_today
from core.querying import narrow_to_window
from django.db.models import Case, Count, IntegerField, Q, QuerySet, When

from applicants.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_APPLICANT, ApplicantStatus
from applicants.models import Applicant, PassportDetail

if TYPE_CHECKING:
    # Annotation only. Importing another app's model at runtime for anything but
    # a ForeignKey is the coupling §4 forbids; the audit selector returns the
    # queryset, this app never touches the model.
    from audit.models import AuditEvent


def get_applicants() -> QuerySet[Applicant]:
    """Every applicant, newest first, with list relations joined.

    ``select_related``/``prefetch_related`` are applied here so list rendering
    never issues a query per row (§6, N+1 prevention).

    ``journeys__target_country_ref`` is prefetched because the list response
    carries each applicant's destinations, read through the reverse accessor.
    Without it a page of twenty applicants would fire twenty extra queries.
    """
    return Applicant.objects.select_related("created_by").prefetch_related(
        "contact_numbers",
        "journeys__target_country_ref",
    )


def get_applicant_by_id(applicant_id: str) -> Applicant | None:
    """One applicant with its full detail graph, or None."""
    return (
        Applicant.objects.select_related("created_by", "passport")
        .prefetch_related(
            "contact_numbers",
            "addresses",
            "family_members",
            "emergency_contacts",
            "journeys__target_country_ref",
        )
        .filter(pk=applicant_id)
        .first()
    )


#: The three language representations of an applicant's name (§39.1). Searched
#: together everywhere, because they are three canonical identities for one
#: person rather than a value and its translations.
_NAME_FIELDS = ("full_name_np", "full_name_en", "full_name_romanized")


def _name_match(query: str) -> Q:
    """OR across the three name representations with ``icontains`` (§39.6)."""
    matches = Q()
    for field in _NAME_FIELDS:
        matches |= Q(**{f"{field}__icontains": query})
    return matches


def search_applicants(queryset: QuerySet[Applicant], query: str) -> QuerySet[Applicant]:
    """Narrow applicants by name, email, contact number, or passport number.

    Names are matched across all three language representations with
    ``icontains``; the GIN trigram indexes carry the performance and ``__exact``
    is never used on a Devanagari name (§39.6).

    The other three fields are how staff actually find a file when they have the
    person in front of them rather than a spelling: a phone number read off a
    call log, an email from an enquiry, a passport number from the document
    itself. ``contact_numbers`` is a reverse foreign key, so a person with three
    numbers would otherwise appear three times — hence ``distinct()``.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        _name_match(query)
        | Q(email__icontains=query)
        | Q(contact_numbers__number__icontains=query)
        | Q(passport__passport_number__icontains=query)
    ).distinct()


def rank_applicants(queryset: QuerySet[Applicant], query: str) -> QuerySet[Applicant]:
    """Order a searched queryset by how well each row matches the query.

    Without this, ``?search=`` returns matches in creation order, so a person
    whose name merely *contains* the query outranks the person whose name *is*
    the query purely by being newer. That is the single most visible defect in a
    name search.

    The score is deliberately lexical and computed with ``Case``/``When`` rather
    than ``TrigramSimilarity``: the test suite runs on SQLite, where
    ``SIMILARITY`` does not exist, so a pg_trgm ranking would leave the ordering
    rule — the part most likely to regress — covered by no test at all. This
    emits identical SQL on both backends.

    * ``3`` — a name field equals the query outright
    * ``2`` — a name field starts with it
    * ``1`` — a name field contains it
    * ``0`` — matched only on email, contact number, or passport number

    ``-id`` is the final tiebreaker for the same reason ``checklists.Checklist``
    carries one: ``created_at`` is not unique, and a non-unique sort key under
    page-number pagination lets a row appear on two pages or on none.
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


def filter_applicants(queryset: QuerySet[Applicant], filters: dict[str, Any] | None = None) -> QuerySet[Applicant]:
    """Apply the documented list filters.

    Recognised keys: ``status``, ``creation_source``, ``search``, ``country``,
    ``country_code``, ``journey_stage``, and ``fiscal_year`` (``YYYY/YY``,
    Nepali fiscal year — §39.4).

    ``country``, ``country_code``, and ``journey_stage`` reach through the
    reverse ``journeys`` accessor. An applicant has no destination of its own —
    the destination belongs to the study plan, and a person may pursue several
    over the years (``applicant_journeys.ApplicantJourney``). "Every applicant
    headed for Australia" therefore means "every applicant with *a* journey
    targeting Australia", which is why each of these needs ``distinct()``: an
    applicant with two Australian journeys is still one applicant.

    Reading the reverse accessor needs no import of ``applicant_journeys`` —
    that app owns the ForeignKey — but it is still a cross-app coupling and is
    documented as one in ``docs/DATA_CONTRACT.md``.
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

    # The catalogue id, for a client that holds one from a country picker.
    country = filters.get("country")
    if country:
        queryset = queryset.filter(journeys__target_country_ref_id=country).distinct()

    # The stable ASCII code, for a client that has "AU" and not a UUID.
    country_code = filters.get("country_code")
    if country_code:
        queryset = queryset.filter(journeys__target_country_ref__code__iexact=country_code).distinct()

    journey_stage = filters.get("journey_stage")
    if journey_stage:
        queryset = queryset.filter(journeys__stage=journey_stage).distinct()

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
# No ``actor`` parameter anywhere below, unlike ``leads``: applicants are shared
# across the consultancy, so there is no scope to apply and pretending otherwise
# would invent a restriction the app does not have.


def get_applicant_status_counts(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> dict[str, int]:
    """How many applicants hold each standing.

    Every status is present with a zero rather than omitted — an absent
    ``archived`` key reads as "no archiving happens here" rather than "none yet".

    ``country_id`` reaches through the reverse ``journeys`` accessor, so it means
    "has a journey to this country", exactly as the list filter does.
    """
    queryset = narrow_to_window(
        Applicant.objects.all(),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    if country_id:
        queryset = queryset.filter(journeys__target_country_ref_id=country_id).distinct()

    counted = dict(queryset.values_list("status").annotate(total=Count("id", distinct=True)))
    return {status: counted.get(status, 0) for status in ApplicantStatus.values}


def get_expiring_passports(
    *,
    within_days: int = 180,
    country_id: str | None = None,
) -> QuerySet[PassportDetail]:
    """Passports already expired or expiring within ``within_days``, soonest first.

    A visa application cannot be lodged on a passport that expires too soon, so
    this is a blocker discovered months ahead or not at all. The default horizon
    is deliberately long — six months, not a week — because renewing a Nepali
    passport is not a same-week errand.

    Already-expired passports are **included**, not filtered out: the applicant
    whose passport lapsed last month is the most blocked person on the list, and
    a query that only looked forward would drop exactly them.

    Archived applicants are excluded — their passport expiring is not work
    anybody needs to do. The comparison is made against today in Nepal (§39.5).
    """
    horizon = nepal_today() + timedelta(days=within_days)
    queryset = (
        PassportDetail.objects.select_related("applicant")
        .filter(expiry_date__isnull=False, expiry_date__lte=horizon)
        .exclude(applicant__status=ApplicantStatus.ARCHIVED)
    )
    if country_id:
        queryset = queryset.filter(applicant__journeys__target_country_ref_id=country_id).distinct()
    return queryset.order_by("expiry_date", "id")


def get_history_for_applicant(applicant: Applicant) -> QuerySet[AuditEvent]:
    """An applicant's chronological history, newest first.

    Reads the central audit log rather than any table this app owns (§4).
    """
    return get_events_for_entity(
        entity_type=AUDIT_ENTITY_APPLICANT,
        entity_id=str(applicant.id),
        app_label=AUDIT_APP_LABEL,
    )
