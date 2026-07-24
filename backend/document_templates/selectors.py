"""Read-only query logic for the document_templates app (no side effects).

This app is Admin-only in its entirety, so there is no owner scoping here — the
population that may read is one authority type, and it reads everything.

Both tables are small and bounded: one row per signatory, one per template slug
(53 today). Every selector returns the whole set narrowed by explicit filters,
and none defers a column, because there is no large column to defer.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from document_templates.constants import LifecycleStatus
from document_templates.models import DocumentTemplate, Signatory


def get_signatories() -> QuerySet[Signatory]:
    """Every signatory, alphabetical, with the creator joined."""
    return Signatory.objects.select_related("created_by")


def get_signatory_by_id(signatory_id: str) -> Signatory | None:
    """One signatory, or None."""
    return Signatory.objects.select_related("created_by").filter(pk=signatory_id).first()


def get_active_signatories() -> QuerySet[Signatory]:
    """The picker: signatories that may be chosen for new work.

    This is the query behind the frontend's only call into this app. A ``draft``
    signatory is excluded along with an ``inactive`` one — being unfinished and
    being retired are different reasons for the same answer.
    """
    return get_signatories().filter(status=LifecycleStatus.ACTIVE)


def search_signatories(queryset: QuerySet[Signatory], query: str) -> QuerySet[Signatory]:
    """Narrow signatories by any of their three name forms (§39.6).

    ``icontains`` over ``name``,
    carried by its own GIN trigram index, so a Roman-script query finds a
    Devanagari-primary record. ``title`` is **not** searched: it has no
    romanized sibling, so a title search would work in one script and silently
    fail in the other.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(Q(name__icontains=query))


def filter_signatories(queryset: QuerySet[Signatory], filters: dict[str, Any] | None = None) -> QuerySet[Signatory]:
    """Apply the documented signatory list filters.

    Recognised keys: ``status``, ``role``, ``search``. Omitting ``status``
    returns draft and inactive signatories too — which of them a given screen
    shows is a presentation decision, and the picker asks for
    ``?status=active`` explicitly.
    """
    filters = filters or {}

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    role = filters.get("role")
    if role:
        queryset = queryset.filter(role__iexact=role)

    search = filters.get("search")
    if search:
        queryset = search_signatories(queryset, search)

    return queryset


def get_templates() -> QuerySet[DocumentTemplate]:
    """Every template catalogue row, grouped by family in picker order."""
    return DocumentTemplate.objects.select_related("created_by")


def get_template_by_id(template_id: str) -> DocumentTemplate | None:
    """One template by primary key, or None."""
    return DocumentTemplate.objects.select_related("created_by").filter(pk=template_id).first()


def get_template_by_key(key: str) -> DocumentTemplate | None:
    """One template by its slug, or None.

    The lookup a caller reaches for when it holds a ``documents.template_key``
    and wants the label to render. Backed by the unique constraint on ``key``.
    """
    return DocumentTemplate.objects.filter(key=key).first()


def search_templates(queryset: QuerySet[DocumentTemplate], query: str) -> QuerySet[DocumentTemplate]:
    """Narrow templates by label or key.

    Plain ``icontains`` with no trigram index behind it: the catalogue is 53
    rows and will not meaningfully grow, so an index would cost writes to serve
    a scan that is already trivial. Both fields are ASCII by construction — a
    key is a validated slug (§39.7) and a label is picker shorthand — so there
    is no script-mismatch problem to solve here.
    """
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(Q(label__icontains=query) | Q(key__icontains=query))


def filter_templates(
    queryset: QuerySet[DocumentTemplate],
    filters: dict[str, Any] | None = None,
) -> QuerySet[DocumentTemplate]:
    """Apply the documented template list filters.

    Recognised keys: ``family``, ``status``, ``search``.
    """
    filters = filters or {}

    family = filters.get("family")
    if family:
        queryset = queryset.filter(family=family)

    status = filters.get("status")
    if status:
        queryset = queryset.filter(status=status)

    search = filters.get("search")
    if search:
        queryset = search_templates(queryset, search)

    return queryset
