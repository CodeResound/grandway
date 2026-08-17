"""Read-only query logic for the uploaded_files app (no side effects).

There is **no owner scoping** here. Any Admin or Lead Manager may read any file,
inherited from ``applicants``: once a person enters the applicant lifecycle,
several staff legitimately work on their file. This is the most sensitive data
in the project, so the decision is argued rather than assumed — see ``access.py``
and ``docs/SECURITY.md`` §2.

**Every selector that returns rows joins the five owner tables and the four user
columns.** Nine ``select_related`` targets is unusual, and it is what keeps the
list endpoint at a bounded query count: the serializer reads ``owner_type`` off
whichever foreign key is set, so a list of twenty mixed-owner files would
otherwise fire twenty owner queries plus up to eighty user queries. Covered by
``tests/test_views.py::FileListQueryCountTests``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from core.querying import narrow_to_window
from django.db.models import Count, Q, QuerySet

from uploaded_files.constants import ADMIN_ONLY_OWNER_TYPES, OWNER_FIELDS, VerificationStatus
from uploaded_files.models import UploadedFile

#: The joins every read needs. ``replaces`` is included because the version
#: chain's previous-version id is part of the response shape.
_RELATED: tuple[str, ...] = (
    *OWNER_FIELDS,
    "uploaded_by",
    "reviewed_by",
    "archived_by",
    "superseded_by",
    "replaces",
)


def get_files() -> QuerySet[UploadedFile]:
    """Every file, newest first, with every join a response needs."""
    return UploadedFile.objects.select_related(*_RELATED)


def get_file_by_id(file_id: str) -> UploadedFile | None:
    """One file, or None."""
    return get_files().filter(pk=file_id).first()


def get_visible_files(*, is_admin: bool) -> QuerySet[UploadedFile]:
    """Every file the caller's authority may see.

    **The only scoping in this app, and it is not owner-scoping.** A Lead Manager
    may read any applicant's files; what they may not see is a file belonging to
    a ``document`` or a ``document_snapshot``, because ``documents`` and
    ``document_history`` are Admin-only on every route including reads. Listing
    those files here would make this module a side door around another module's
    access rule.

    Excluded from the queryset rather than refused per row, so a restricted file
    never appears in a page at all — a 403 on one row of a list would leak the
    existence of the very record the other module hides.
    """
    queryset = get_files()
    if is_admin:
        return queryset

    restricted = Q()
    for owner in ADMIN_ONLY_OWNER_TYPES:
        restricted |= Q(**{f"{owner}__isnull": False})
    return queryset.exclude(restricted)


def search_files(queryset: QuerySet[UploadedFile], query: str) -> QuerySet[UploadedFile]:
    """Narrow files by their original filename.

    One field, backed by a GIN trigram index. **This is a real limitation and
    not an oversight:** unlike every other searchable model in the project, a
    file has no separate display name to search across, because a
    filename is a byte-level artefact rather than a canonical identity (§39.1).
    A file named in Devanagari will not be found by a Roman-script query.
    ``notes`` is deliberately not searched — it is an operator's free text and
    may carry applicant details that should not be reachable by guessing.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(original_filename__icontains=query)


def filter_files(
    queryset: QuerySet[UploadedFile],
    filters: dict[str, Any] | None = None,
) -> QuerySet[UploadedFile]:
    """Apply the documented file list filters.

    Recognised keys: the five owner ids (``applicant``, ``journey``, ``offer``,
    ``document``, ``snapshot``), ``category``, ``verification_status``,
    ``upload_source``, ``is_archived``, ``is_current``, ``checksum``, ``search``.

    Omitting ``is_archived`` returns archived files too. That is deliberate:
    which of them a given screen shows is a presentation decision, and a
    selector that hid rows nobody asked it to hide would make "why is this file
    missing" unanswerable from the API. The per-record panels pass
    ``?is_archived=false`` explicitly.
    """
    filters = filters or {}

    for owner in OWNER_FIELDS:
        value = filters.get(owner)
        if value:
            queryset = queryset.filter(**{owner: value})

    for field in ("category", "verification_status", "upload_source"):
        value = filters.get(field)
        if value:
            queryset = queryset.filter(**{field: value})

    checksum = filters.get("checksum")
    if checksum:
        # Stored digests come from hashlib's hexdigest() and are always
        # lowercase, so lowercasing the caller's value keeps the lookup
        # case-insensitive while letting the checksum B-tree serve it —
        # __iexact compiled to UPPER(col) and bypassed the index (audit P7).
        queryset = queryset.filter(checksum_sha256=checksum.lower())

    is_archived = filters.get("is_archived")
    if is_archived is not None:
        queryset = queryset.filter(archived_at__isnull=not is_archived)

    is_current = filters.get("is_current")
    if is_current is not None:
        queryset = queryset.filter(superseded_at__isnull=is_current)

    search = filters.get("search")
    if search:
        queryset = search_files(queryset, search)

    return queryset


def get_version_chain(uploaded_file: UploadedFile) -> list[UploadedFile]:
    """Return the whole replacement chain containing ``uploaded_file``, oldest first.

    Walks backwards to the original through ``replaces``, then forwards to the
    current version through the ``replaced_by`` reverse of the same
    ``OneToOne``. Returned as a list rather than a queryset because a chain is
    walked one row at a time by construction — it has no set-based form, and
    presenting it as a queryset would invite a caller to filter or paginate
    something that is meaningless in pieces.

    Bounded by the ``OneToOne`` on ``replaces``, which makes forking impossible,
    so the walk cannot branch. The ``seen`` guard is a cycle backstop: a chain
    can only loop if a row is corrupted into replacing one of its own ancestors,
    which the database should prevent — but an infinite loop inside a request is
    a far worse failure than a short answer.
    """
    seen: set[Any] = set()

    oldest = uploaded_file
    while oldest.replaces_id is not None and oldest.replaces_id not in seen:
        seen.add(oldest.pk)
        previous = get_file_by_id(str(oldest.replaces_id))
        if previous is None:
            break
        oldest = previous

    chain: list[UploadedFile] = [oldest]
    seen = {oldest.pk}
    while True:
        successor = get_files().filter(replaces_id=chain[-1].pk).first()
        if successor is None or successor.pk in seen:
            break
        seen.add(successor.pk)
        chain.append(successor)

    return chain


# ---------------------------------------------------------------------------
# Dashboard summaries
# ---------------------------------------------------------------------------
#
# Aggregates over this app's own rows, living here because §4 forbids another
# app querying this table directly. ``dashboards`` composes what it gets back.
#
# **Every one of these takes ``is_admin`` and starts from ``get_visible_files``.**
# A count is not exempt from the rule the list obeys: telling a Lead Manager
# that eleven files await verification, three of which they may not see, is the
# same side door around the document stack's Admin-only rule that
# ``get_visible_files`` exists to close — it just leaks a number instead of a row.


def _live_files(*, is_admin: bool) -> QuerySet[UploadedFile]:
    """Visible, non-archived, current-version files.

    Superseded versions are excluded: a replaced file's verification status is
    history, and counting it would make every replacement look like fresh work.
    """
    return get_visible_files(is_admin=is_admin).filter(archived_at__isnull=True, superseded_at__isnull=True)


def get_file_verification_counts(
    *,
    is_admin: bool,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
    country_id: str | None = None,
) -> dict[str, int]:
    """How many live files hold each verification status. Zero-filled.

    ``country_id`` matches only files owned by a **journey**, since that is the
    only owner type carrying a destination. An applicant-owned passport scan is
    correctly absent from a country-narrowed count — it belongs to the person,
    not to any one study plan.
    """
    queryset = narrow_to_window(
        _live_files(is_admin=is_admin),
        date_from=date_from,
        date_to=date_to,
        fiscal_year=fiscal_year,
    )
    if country_id:
        queryset = queryset.filter(journey__target_country_ref_id=country_id)

    counted = dict(queryset.values_list("verification_status").annotate(total=Count("id")))
    return {status: counted.get(status, 0) for status in VerificationStatus.values}


def get_files_awaiting_verification(
    *,
    is_admin: bool,
    country_id: str | None = None,
) -> QuerySet[UploadedFile]:
    """Live files nobody has reviewed yet, oldest upload first.

    Oldest first, unlike every other list in this app: this is a queue, and the
    file that has waited longest is the one to look at. A newest-first review
    queue starves its own backlog.

    Verification is a record of human judgement, not a gate — nothing in
    Grandway refuses to proceed on an unverified file (``models.py``). A caller
    must present this as work outstanding, never as a blocked state.
    """
    queryset = _live_files(is_admin=is_admin).filter(verification_status=VerificationStatus.PENDING)
    if country_id:
        queryset = queryset.filter(journey__target_country_ref_id=country_id)
    return queryset.order_by("created_at", "id")


def get_rejected_files(
    *,
    is_admin: bool,
    country_id: str | None = None,
) -> QuerySet[UploadedFile]:
    """Live files a reviewer rejected and nobody has replaced, most recent first.

    Only files that are still *current* appear: uploading a replacement
    supersedes the rejected version, which drops out of this list on its own.
    Anything left here is a rejection nobody has acted on, and
    ``rejection_reason`` says what is wrong with it.
    """
    queryset = _live_files(is_admin=is_admin).filter(verification_status=VerificationStatus.REJECTED)
    if country_id:
        queryset = queryset.filter(journey__target_country_ref_id=country_id)
    return queryset.order_by("-reviewed_at", "-id")


def get_files_for_owner(owner_type: str, owner_id: str) -> QuerySet[UploadedFile]:
    """Every file attached to one business record.

    The query a future ``applicants``/``offers``/``documents`` panel would call
    if those apps ever read files server-side. Nothing calls it today — it is
    here because the alternative is each of those apps writing its own
    ``UploadedFile.objects.filter(...)``, which §6 forbids outright.
    """
    if owner_type not in OWNER_FIELDS:
        return UploadedFile.objects.none()
    return get_files().filter(Q(**{owner_type: owner_id}))
