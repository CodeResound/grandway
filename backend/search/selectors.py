"""Composition logic for the search app — the only module that assembles results.

**Nothing here queries another app's tables.** Every bucket is produced by the
search selector of the app that owns the rows, and this module's whole job is to
call those, slice them, and shape the result. Read the import list: there is no
model in it, and there must never be one. A convenient
``Applicant.objects.filter(...)`` here would be shorter than composing nine
selectors and would re-implement another app's matching *and* its access rule in
a second place, where neither is tested. ``search/access.py`` records the
precedent — ``dashboards`` shipped exactly that defect in its activity feed.

Three rules run through every type:

* **Scoping is inherited, never re-implemented.** Leads come through
  ``get_leads_for_actor`` and files through ``get_visible_files``; this module
  passes the actor down and trusts the owning app, because the owning app is
  where the rule is tested.
* **Matching is inherited too.** Which fields a query touches, whether a name is
  ranked, and how ties break are decisions the owning app already made and
  documented. Restating any of them here would fork them.
* **Buckets are previews, not list views.** Each returns its true total and the
  first few rows; the full set lives behind ``list_url``, in the owning app's
  own list endpoint. The box exists to get someone *to* the record, not to
  become a tenth list view (``concepts/search.txt`` — "Full results").
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from applicants import selectors as applicant_selectors
from clients import selectors as client_selectors
from document_templates import selectors as template_selectors
from documents import selectors as document_selectors
from institutions import selectors as institution_selectors
from leads import selectors as lead_selectors
from uploaded_files import selectors as file_selectors

from search.access import is_admin
from search.constants import (
    DEFAULT_LIMIT_PER_TYPE,
    SEARCHABLE_TYPES,
    SEARCHABLE_TYPES_BY_KEY,
    SearchableType,
    SearchableTypeKey,
)

# ---------------------------------------------------------------------------
# Per-type querysets
#
# One resolver per searchable type. Each takes the actor and the query and
# returns the owning app's queryset, already searched and already ordered by
# whatever that app considers the right order. Nothing is sliced yet — the
# bucket needs the full queryset to report a true total.
# ---------------------------------------------------------------------------


def _applicants(actor: Any, query: str) -> Any:
    """Applicants matching by name, email, contact number, or passport number.

    ``rank_applicants`` is applied for the same reason the applicant list applies
    it: without it, the person whose name *is* the query is outranked by anyone
    whose name merely contains it and happens to be newer. In a five-row preview
    that is the difference between finding someone and not.

    The prefetch set is **narrowed** rather than inherited. ``get_applicants``
    prefetches ``journeys__target_country_ref`` because the applicant *list*
    renders each person's destinations; a search hit renders no such thing, so
    inheriting it would fire two extra queries per search to build data that is
    then discarded. ``contact_numbers`` is kept because ``matched_on`` reads it.
    ``select_related("passport")`` is added for the same reason.

    Narrowing the loading strategy cannot change which rows come back — joins
    and prefetches are not filters — which is what makes this safe to do to
    another app's queryset.
    """
    queryset = (
        applicant_selectors.get_applicants()
        .prefetch_related(None)
        .prefetch_related("contact_numbers")
        .select_related("passport")
    )
    queryset = applicant_selectors.search_applicants(queryset, query)
    return applicant_selectors.rank_applicants(queryset, query)


def _leads(actor: Any, query: str) -> Any:
    """Leads matching by name, email, or contact number — **narrowed to the actor**.

    ``get_leads_for_actor`` is the scoping, and it is the reason this resolver
    takes an actor at all. An Admin searches every lead; a Lead Manager searches
    only their own, and is not told the others exist.

    ``created_by`` is dropped from the join set — the lead list shows an owner
    column, a search hit does not. ``source`` is kept; the subtitle names it.
    """
    queryset = lead_selectors.get_leads_for_actor(actor).select_related(None).select_related("source")
    queryset = lead_selectors.search_leads(queryset, query)
    return lead_selectors.rank_leads(queryset, query)


def _clients(actor: Any, query: str) -> Any:
    """Partner organizations matching by company name or spokesperson name.

    Every field the hit renders is local to the row, so both the ``created_by``
    join and the ``contact_numbers`` prefetch are dropped. The prefetch is the
    one worth noting: it is a whole extra round trip, spent to fetch phone
    numbers a search result never displays.
    """
    queryset = client_selectors.get_clients().select_related(None).prefetch_related(None)
    return client_selectors.search_clients(queryset, query)


def _documents(actor: Any, query: str) -> Any:
    """Document records matching by label.

    Document *content* is not searched — the owning selector refuses to, because
    it is opaque JSON holding personal financial data, and making it reachable by
    guessing needs its own decision (``documents.selectors.search_documents``).

    ``created_by`` is dropped from the join set: the document list shows who
    created each row, a search hit does not.
    """
    queryset = document_selectors.get_documents().select_related(None).select_related("applicant")
    return document_selectors.search_documents(queryset, query)


def _uploaded_files(actor: Any, query: str) -> Any:
    """Files matching by original filename — **narrowed by the caller's authority**.

    ``get_visible_files`` is the scoping: a Lead Manager never sees a file that
    belongs to a document or a print snapshot, because those apps are Admin-only
    on every route including reads. Excluded from the queryset rather than
    refused per row, so a restricted file never appears at all.

    The join set is dropped entirely — and this is the largest single saving in
    the app. ``get_files`` joins **nine** relations because a file response
    carries its owner, uploader, reviewer, archiver, and version chain; a search
    hit reads three local columns and none of those relations. Clearing them
    turns a nine-way join into a single-table scan.

    ``select_related(None)`` is applied *before* the visibility filter rather
    than after, so the exclusion still builds its ``owner__isnull`` conditions
    normally — those are filters on foreign-key columns, which need no join.
    """
    queryset = file_selectors.get_visible_files(is_admin=is_admin(actor)).select_related(None)
    return file_selectors.search_files(queryset, query)


def _institutions(actor: Any, query: str) -> Any:
    """Institutions matching by name or common name.

    The catalogue exposes its search as a ``q`` filter key rather than a
    ``search_*`` function; that asymmetry is the owning app's and is absorbed
    here rather than pushed onto a client.

    Availability is deliberately **not** narrowed. The catalogue's own list
    defaults to usable records only, which is right for shortlisting and wrong
    for finding: someone searching a paused institution by name is usually
    checking precisely whether it is paused. The hit carries
    ``availability_status`` so the answer is on the row.
    """
    queryset = institution_selectors.get_institutions()
    return institution_selectors.filter_institutions(queryset, {"q": query})


def _programs(actor: Any, query: str) -> Any:
    """Programs matching by title, or by their institution's name.

    Matching on the institution is the owning selector's behaviour, not an
    addition here — a person typing an institution name expects its programs
    among the results. Availability is unnarrowed, as for institutions.

    ``get_programs`` joins four relations for the catalogue list row; a search
    hit shows the institution and two local columns, so ``campus``, ``field``,
    and ``institution__country`` are dropped. ``institution`` is kept — the
    query filters on ``institution__name`` regardless, and the hit displays it.
    """
    queryset = institution_selectors.get_programs().select_related(None).select_related("institution")
    return institution_selectors.filter_programs(queryset, {"q": query})


def _document_templates(actor: Any, query: str) -> Any:
    """Templates matching by label or key.

    ``created_by`` dropped — the hit shows the label and the key, both local.
    """
    queryset = template_selectors.get_templates().select_related(None)
    return template_selectors.search_templates(queryset, query)


def _signatories(actor: Any, query: str) -> Any:
    """Signatories matching by name.

    ``created_by`` dropped, as for templates.
    """
    queryset = template_selectors.get_signatories().select_related(None)
    return template_selectors.search_signatories(queryset, query)


#: Resolver per type key. Every key in ``SEARCHABLE_TYPES`` must appear here;
#: ``search/tests/test_selectors.py`` asserts the two stay in step, so adding a
#: catalogue row without a resolver fails a test rather than a request.
RESOLVERS: dict[str, Callable[[Any, str], Any]] = {
    SearchableTypeKey.APPLICANT: _applicants,
    SearchableTypeKey.LEAD: _leads,
    SearchableTypeKey.CLIENT: _clients,
    SearchableTypeKey.DOCUMENT: _documents,
    SearchableTypeKey.UPLOADED_FILE: _uploaded_files,
    SearchableTypeKey.INSTITUTION: _institutions,
    SearchableTypeKey.PROGRAM: _programs,
    SearchableTypeKey.DOCUMENT_TEMPLATE: _document_templates,
    SearchableTypeKey.SIGNATORY: _signatories,
}


# ---------------------------------------------------------------------------
# Hit shaping
#
# A hit is what a result row needs and nothing more: what it is, what to call
# it, one line to tell two similar rows apart, why it matched, and where to open
# it. Deliberately not a preview of the record — no status history, no personal
# detail beyond the identifying line (``concepts/search.txt`` — "Core entities").
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    """A field as displayable text, with ``None`` flattened to empty."""
    return "" if value is None else str(value)


def _joined(parts: Iterable[Any]) -> str:
    """Non-empty parts joined into one subtitle line."""
    return " · ".join(part for part in (_text(item).strip() for item in parts) if part)


def _matched_on(query: str, candidates: Sequence[tuple[str, Any]]) -> list[str]:
    """Which of the row's searchable fields actually contain the query.

    Recomputed in Python over the handful of rows in a preview rather than
    annotated in SQL: the alternative is a ``Case``/``When`` per candidate field
    on nine querysets, to produce a label. This runs over at most
    ``MAX_LIMIT_PER_TYPE`` rows per type and touches only fields already loaded.

    It exists because a result found by phone number otherwise looks like an
    inexplicable name match. Empty is a legitimate answer — a program matched
    through its institution's name has no matching field of its own — and the
    client shows nothing rather than guessing.
    """
    needle = query.strip().casefold()
    if not needle:
        return []
    return [name for name, value in candidates if needle in _text(value).casefold()]


def _contact_numbers(obj: Any) -> list[str]:
    """A person's phone numbers, read through the prefetch the owning app set up."""
    return [number.number for number in obj.contact_numbers.all()]


def _passport_number(applicant: Any) -> str:
    """An applicant's passport number, or empty when they have no passport record.

    A reverse one-to-one raises rather than returning ``None`` when absent, and
    most applicants have no passport on file, so the miss is the common path.
    """
    passport = getattr(applicant, "passport", None)
    return _text(getattr(passport, "passport_number", ""))


def _hit_applicant(obj: Any, query: str) -> dict[str, Any]:
    return {
        "title": obj.full_name,
        "subtitle": _joined([obj.email, obj.status]),
        "matched_on": _matched_on(
            query,
            [
                ("full_name", obj.full_name),
                ("email", obj.email),
                *[("contact_number", number) for number in _contact_numbers(obj)],
                ("passport_number", _passport_number(obj)),
            ],
        ),
    }


def _hit_lead(obj: Any, query: str) -> dict[str, Any]:
    return {
        "title": obj.full_name,
        "subtitle": _joined([obj.email, obj.stage, getattr(obj.source, "name", "")]),
        "matched_on": _matched_on(
            query,
            [
                ("full_name", obj.full_name),
                ("email", obj.email),
                *[("contact_number", number) for number in _contact_numbers(obj)],
            ],
        ),
    }


def _hit_client(obj: Any, query: str) -> dict[str, Any]:
    return {
        "title": obj.name,
        "subtitle": _joined([obj.spokesperson_name, obj.status]),
        "matched_on": _matched_on(
            query,
            [("name", obj.name), ("spokesperson_name", obj.spokesperson_name)],
        ),
    }


def _hit_document(obj: Any, query: str) -> dict[str, Any]:
    applicant = obj.applicant
    return {
        "title": obj.label,
        "subtitle": _joined([applicant.full_name if applicant else "Standalone", obj.status]),
        "matched_on": _matched_on(query, [("label", obj.label)]),
    }


def _hit_uploaded_file(obj: Any, query: str) -> dict[str, Any]:
    return {
        "title": obj.original_filename,
        "subtitle": _joined([obj.category, obj.verification_status]),
        "matched_on": _matched_on(query, [("original_filename", obj.original_filename)]),
    }


def _hit_institution(obj: Any, query: str) -> dict[str, Any]:
    country = obj.country
    return {
        "title": obj.name,
        "subtitle": _joined([country.name if country else "", obj.availability_status]),
        "matched_on": _matched_on(
            query,
            [("name", obj.name), ("common_name", obj.common_name)],
        ),
    }


def _hit_program(obj: Any, query: str) -> dict[str, Any]:
    institution = obj.institution
    return {
        "title": obj.title,
        "subtitle": _joined(
            [
                institution.name if institution else "",
                obj.qualification_level,
                obj.availability_status,
            ]
        ),
        "matched_on": _matched_on(query, [("title", obj.title)]),
    }


def _hit_document_template(obj: Any, query: str) -> dict[str, Any]:
    return {
        "title": obj.label,
        "subtitle": _joined([obj.key]),
        "matched_on": _matched_on(query, [("label", obj.label), ("key", obj.key)]),
    }


def _hit_signatory(obj: Any, query: str) -> dict[str, Any]:
    return {
        "title": obj.name,
        "subtitle": _joined([obj.title]),
        "matched_on": _matched_on(query, [("name", obj.name)]),
    }


#: Hit builder per type key, paired with ``RESOLVERS`` and checked by the same test.
HIT_BUILDERS: dict[str, Callable[[Any, str], dict[str, Any]]] = {
    SearchableTypeKey.APPLICANT: _hit_applicant,
    SearchableTypeKey.LEAD: _hit_lead,
    SearchableTypeKey.CLIENT: _hit_client,
    SearchableTypeKey.DOCUMENT: _hit_document,
    SearchableTypeKey.UPLOADED_FILE: _hit_uploaded_file,
    SearchableTypeKey.INSTITUTION: _hit_institution,
    SearchableTypeKey.PROGRAM: _hit_program,
    SearchableTypeKey.DOCUMENT_TEMPLATE: _hit_document_template,
    SearchableTypeKey.SIGNATORY: _hit_signatory,
}


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------


def _list_url(entry: SearchableType, query: str) -> str:
    """The "see all" link: the owning app's list, filtered by the same query.

    Built from the catalogue's own ``list_search_param`` because seven apps read
    ``search`` and the catalogue reads ``q``. Getting this wrong returns the
    whole unfiltered list, which reads as a search bug rather than a bad link.

    The query is URL-encoded here — a name with a space or an ampersand is
    ordinary, and an unencoded one would truncate the filter silently.
    """
    from urllib.parse import urlencode

    return f"{entry.list_path}?{urlencode({entry.list_search_param: query})}"


def build_bucket(entry: SearchableType, actor: Any, query: str, limit: int) -> dict[str, Any]:
    """One type's section of the results panel.

    ``total`` is counted against the full queryset and the rows are sliced from
    that same queryset, so the number a user reads is the real backlog rather
    than the length of the preview. ``has_more`` saves a client inferring it by
    comparing two numbers — the shape ``dashboards._preview`` established.
    """
    queryset = RESOLVERS[entry.key](actor, query)
    total = queryset.count()
    build_hit = HIT_BUILDERS[entry.key]

    hits: list[dict[str, Any]] = []
    for obj in queryset[:limit]:
        hit = build_hit(obj, query)
        hits.append(
            {
                "entity_type": entry.key,
                "id": str(obj.id),
                "detail_path": entry.detail_path.format(id=obj.id),
                "detail_permission_key": entry.detail_permission_key,
                **hit,
            }
        )

    return {
        "entity_type": entry.key,
        "label": entry.label,
        "group": entry.group,
        "total": total,
        "has_more": total > len(hits),
        "hits": hits,
        "list_url": _list_url(entry, query),
        "list_permission_key": entry.list_permission_key,
    }


def search_everything(
    *,
    actor: Any,
    query: str,
    types: Sequence[str] | None = None,
    limit_per_type: int = DEFAULT_LIMIT_PER_TYPE,
) -> dict[str, Any]:
    """The whole results panel for one query.

    Buckets come back in catalogue order — people, then work, then reference —
    because that order is a product decision about what someone at the counter
    is most likely to want, and leaving it to each client would let two clients
    disagree.

    **Every requested bucket is returned, including empty ones.** The client
    decides what to render; the API does not pre-judge that an empty applicant
    bucket is uninteresting, because "no applicant by that name" is often the
    answer someone needed. ``total_hits`` lets a client say "nothing found" once
    without summing nine numbers itself.

    ``types`` narrows which buckets are built at all, which is the one control a
    caller has over the cost of the request: nine types is nine queries plus
    nine counts, and a client that only renders people should ask for three.
    """
    selected = _resolve_types(types)
    buckets = [build_bucket(entry, actor, query, limit_per_type) for entry in selected]
    return {
        "query": query,
        "types": [entry.key for entry in selected],
        "total_hits": sum(bucket["total"] for bucket in buckets),
        "results": buckets,
    }


def _resolve_types(types: Sequence[str] | None) -> list[SearchableType]:
    """The catalogue rows to search, in catalogue order.

    Order comes from the catalogue rather than from the caller's ``?types=``
    string: the section order is the app's, and honouring the order a client
    happened to type its filter chips in would make two clients render the same
    results differently. Unknown keys are rejected by the serializer before this
    is reached.
    """
    if not types:
        return list(SEARCHABLE_TYPES)
    requested = set(types)
    return [entry for entry in SEARCHABLE_TYPES if entry.key in requested]


def get_searchable_types() -> list[dict[str, Any]]:
    """The catalogue, for ``GET /api/v1/search/types/``.

    Served from the server so a client's filter chips and result-routing table
    come from one place. A tenth type then reaches every client without a
    frontend release (``concepts/search.txt`` — "Type filter chips").
    """
    return [
        {
            "key": entry.key,
            "label": entry.label,
            "group": entry.group,
            "app_label": entry.app_label,
            "matched_fields": list(entry.matched_fields),
            "detail_path": entry.detail_path,
            "detail_permission_key": entry.detail_permission_key,
            "list_path": entry.list_path,
            "list_search_param": entry.list_search_param,
            "list_permission_key": entry.list_permission_key,
        }
        for entry in SEARCHABLE_TYPES
    ]


def is_known_type(key: str) -> bool:
    """Whether a ``?types=`` value names a searchable type."""
    return key in SEARCHABLE_TYPES_BY_KEY
