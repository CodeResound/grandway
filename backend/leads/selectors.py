"""Read-only query logic for the leads app (no side effects, no business rules).

Owner scoping lives here, not in the views: every lead queryset is narrowed to
what the actor may see *in the database*, so a Lead Manager can never read
another Lead Manager's lead by any path (§9, ``docs/SECURITY.md`` §1).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from audit.selectors import get_events_for_entity
from core.constants import NoteCategory
from core.querying import narrow_to_window
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, QuerySet, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from leads.access import is_admin

if TYPE_CHECKING:
    # Annotation only. Importing another app's model at runtime for anything but
    # a ForeignKey is the coupling §4 forbids; the audit selector returns the
    # queryset, this app never touches the model.
    from audit.models import AuditEvent
from leads.constants import AUDIT_APP_LABEL, AUDIT_ENTITY_LEAD, LeadStage
from leads.models import Lead, LeadLanguageCertificate, LeadNote, LeadSource, LossReason

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


def get_leads_for_actor(actor: Any, *, deleted: bool = False) -> QuerySet[Lead]:
    """Every lead the actor may see: all of them for an Admin, own for a Lead Manager.

    Soft-deleted leads are excluded unless ``deleted=True``, which returns
    *only* deleted leads (the Admin's "deleted" view — the view refuses it to a
    Lead Manager). Because search and the dashboard figures read leads through
    this selector, a deleted lead drops out of both with no change there.

    ``select_related``/``prefetch_related`` are applied here so list rendering
    never issues a query per row (§6, N+1 prevention).
    """
    queryset = Lead.objects.select_related("source", "created_by").prefetch_related("contact_numbers")
    queryset = queryset.filter(deleted_at__isnull=not deleted)
    if is_admin(actor):
        return queryset
    return queryset.filter(created_by=actor)


def get_lead_for_actor(actor: Any, lead_id: str) -> Lead | None:
    """One in-scope lead with its detail relations, or None.

    Returning None for both "missing" and "not yours" is deliberate — the view
    turns either into 404, so ownership is never disclosed. A deleted lead is in
    scope for an Admin only (so it can be read and restored); for a Lead
    Manager it is simply not found.
    """
    queryset = Lead.objects.select_related("source", "created_by").prefetch_related(
        "contact_numbers", "language_certificates"
    )
    if not is_admin(actor):
        queryset = queryset.filter(created_by=actor, deleted_at__isnull=True)
    return (
        queryset.select_related(
            "study_interest", "lost_reason", "last_followed_up_by", "lost_by", "converted_by", "deleted_by"
        )
        .filter(pk=lead_id)
        .first()
    )


#: The three language representations of a lead's name (§39.1), searched
#: together. Mirrors ``applicants.selectors._NAME_FIELDS`` — the two apps hold
#: the same person at two stages of their life and are searched the same way.
_NAME_FIELDS = ("full_name",)


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

    Recognised keys: ``stage``, ``source`` (id), ``search``, ``fiscal_year``
    (``YYYY/YY``, Nepali fiscal year — §39.4), ``highest_qualification_level``
    and ``language_test_status`` (on the study interest), and
    ``language_test_type`` (leads holding at least one certificate of that type).
    """
    filters = filters or {}

    level = filters.get("highest_qualification_level")
    if level:
        queryset = queryset.filter(study_interest__highest_qualification_level=level)

    test_status = filters.get("language_test_status")
    if test_status:
        queryset = queryset.filter(study_interest__language_test_status=test_status)

    test_type = filters.get("language_test_type")
    if test_type:
        # ``Exists`` rather than a join + ``distinct()``: a lead with two IELTS
        # results must still appear once, and ``rank_leads`` annotates later.
        queryset = queryset.filter(
            Exists(LeadLanguageCertificate.objects.filter(lead=OuterRef("pk"), test_type=test_type))
        )

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


# ---------------------------------------------------------------------------
# Dashboard summaries
# ---------------------------------------------------------------------------
#
# Aggregates over this app's own rows, living in this app because §4 forbids
# another app querying these tables directly. ``dashboards`` composes what it
# gets back; it never reaches into ``leads_lead`` itself.
#
# Every one of these takes ``actor`` and starts from ``get_leads_for_actor``.
# That is not defensive habit — leads are the only owner-scoped rows in the
# project, so a summary that skipped the scoping would let a Lead Manager read
# the size and shape of another manager's pipeline off a dashboard tile.


def get_lead_funnel_counts(
    *,
    actor: Any,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    source_id: str | None = None,
) -> dict[str, int]:
    """How many leads sit at each stage, within the caller's scope.

    Every stage is present with a zero rather than omitted. A funnel that drops
    its empty stages reads as though those stages do not exist, when the fact
    worth seeing is precisely that nothing has reached them.
    """
    queryset = narrow_to_window(
        get_leads_for_actor(actor),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    if source_id:
        queryset = queryset.filter(source_id=source_id)

    counted = dict(queryset.values_list("stage").annotate(total=Count("id")))
    return {stage: counted.get(stage, 0) for stage in LeadStage.values}


def get_lead_source_conversion(
    *,
    actor: Any,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> list[dict[str, Any]]:
    """Per source: how many arrived, how many converted, how many were lost.

    The question intake reporting actually asks is not "which source sends the
    most people" but "which source sends people who become clients" — a channel
    delivering fifty leads and two conversions is worse than one delivering ten
    and five. Both numbers are returned so the caller can show the rate without
    losing the volume behind it.

    Only sources with at least one lead in the window appear. A source nobody
    came through contributes nothing to a conversion comparison, and listing
    every configured source would bury the ones that matter.
    """
    queryset = narrow_to_window(
        get_leads_for_actor(actor),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    rows = (
        queryset.values("source_id", "source__code", "source__name")
        .annotate(
            total=Count("id"),
            converted=Count("id", filter=Q(stage=LeadStage.CONVERTED)),
            lost=Count("id", filter=Q(stage=LeadStage.LOST)),
        )
        .order_by("-total")
    )
    return [
        {
            "source_id": str(row["source_id"]),
            "source_code": row["source__code"],
            "source_name": row["source__name"],
            "total": row["total"],
            "converted": row["converted"],
            "lost": row["lost"],
            # Neither converted nor lost: still somewhere in the funnel.
            "in_progress": row["total"] - row["converted"] - row["lost"],
        }
        for row in rows
    ]


def get_stale_leads(
    *,
    actor: Any,
    stale_after_days: int = 7,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> QuerySet[Lead]:
    """Live leads nobody has touched in ``stale_after_days``, oldest contact first.

    A lead has no due date — nothing in this app can be "overdue". Silence is
    the only signal there is, so staleness is measured from the last follow-up,
    falling back to creation for a lead never followed up at all. Without that
    fallback a brand-new lead nobody ever called would look perpetually fresh.

    Terminal stages are excluded: a converted or lost lead is not neglected, it
    is finished.
    """
    cutoff = timezone.now() - timedelta(days=stale_after_days)
    queryset = narrow_to_window(
        get_leads_for_actor(actor),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    return (
        queryset.exclude(stage__in=(LeadStage.CONVERTED, LeadStage.LOST))
        .annotate(last_touched=Coalesce("last_followed_up_at", "created_at"))
        .filter(last_touched__lt=cutoff)
        .order_by("last_touched", "id")
    )


def get_lead_workload_by_owner(
    *,
    actor: Any,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> list[dict[str, Any]]:
    """Open leads per owner, heaviest first.

    Owner scoping applies here as everywhere else, so a Lead Manager sees
    exactly one row — their own. That is not a degraded view: the section
    answers "how is work distributed", and a Lead Manager's honest answer is
    "here is mine". Only an Admin sees a distribution to rebalance.
    """
    queryset = narrow_to_window(
        get_leads_for_actor(actor),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    rows = (
        queryset.exclude(stage__in=(LeadStage.CONVERTED, LeadStage.LOST))
        .values("created_by_id", "created_by__username", "created_by__display_name")
        .annotate(open_leads=Count("id"))
        .order_by("-open_leads")
    )
    return [
        {
            "owner_id": str(row["created_by_id"]),
            "owner_username": row["created_by__username"],
            "owner_display_name": row["created_by__display_name"],
            "open_leads": row["open_leads"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Notes and history
# ---------------------------------------------------------------------------


def get_notes_for_lead(
    lead: Lead,
    *,
    category: str | None = None,
    ordering: str | None = None,
) -> QuerySet[LeadNote]:
    """A lead's live notes, most recent ``noted_at`` first, with authors joined.

    Soft-deleted notes are excluded. ``ordering`` is one of
    ``core.constants.NOTE_ORDERINGS``; the serializer validates it first.
    """
    queryset = LeadNote.objects.filter(lead=lead, deleted_at__isnull=True).select_related("author", "updated_by")
    if category:
        queryset = queryset.filter(category=category)
    if ordering:
        queryset = queryset.order_by(ordering, "-created_at")
    return queryset


def get_note_for_lead(lead: Lead, note_id: str) -> LeadNote | None:
    """One live note of this lead, or None (a deleted note is not found)."""
    return (
        LeadNote.objects.filter(lead=lead, pk=note_id, deleted_at__isnull=True)
        .select_related("author", "updated_by")
        .first()
    )


def get_note_category_counts(lead: Lead) -> dict[str, int]:
    """Live note count per category — the notes panel's tab badges."""
    counts = dict(
        LeadNote.objects.filter(lead=lead, deleted_at__isnull=True)
        .values("category")
        .annotate(total=Count("id"))
        .values_list("category", "total")
    )
    return {category: counts.get(category, 0) for category in NoteCategory.values}


def get_lead_note_exports(lead: Lead) -> list[dict[str, Any]]:
    """The lead's live notes as plain dicts, oldest first — copied at conversion.

    Returned as data rather than model instances so ``applicants`` receives
    values, never a ``leads`` model (§4).
    """
    return [
        {
            "category": note.category,
            "body": note.body,
            "noted_at": note.noted_at,
            "author": note.author,
            "created_at": note.created_at,
        }
        for note in LeadNote.objects.filter(lead=lead, deleted_at__isnull=True)
        .select_related("author")
        .order_by("noted_at", "created_at")
    ]


#: The certificate fields copied onto an applicant language test at conversion.
_CERTIFICATE_EXPORT_FIELDS = (
    "test_type",
    "overall_score",
    "listening_score",
    "reading_score",
    "writing_score",
    "speaking_score",
    "test_date",
    "certificate_number",
    "expiry_date",
)


def get_lead_certificate_exports(lead: Lead) -> list[dict[str, Any]]:
    """The lead's language certificates as plain dicts — copied 1:1 at conversion (§4: values, not models)."""
    return list(LeadLanguageCertificate.objects.filter(lead=lead).values(*_CERTIFICATE_EXPORT_FIELDS))


def get_history_for_lead(lead: Lead) -> QuerySet[AuditEvent]:
    """A lead's chronological history, newest first.

    Reads the central audit log rather than any table this app owns — the
    history *is* the audit trail, filtered to one lead (§4: leads consumes
    ``audit``'s selector rather than duplicating its storage or its query).
    """
    return get_events_for_entity(
        entity_type=AUDIT_ENTITY_LEAD,
        entity_id=str(lead.id),
        app_label=AUDIT_APP_LABEL,
    )
