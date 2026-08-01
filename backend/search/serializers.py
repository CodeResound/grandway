"""Request validation and response shaping for the search app.

The **query serializer** is the substantive part of this file. A search box is
the one endpoint in the project that a user drives keystroke by keystroke, so
its validation decides how much of the database a stray keypress can scan. Three
rules do that work, and each refuses in a way a client can act on:

* a query shorter than ``MIN_QUERY_LENGTH`` is refused rather than run,
* ``limit_per_type`` is capped, so search cannot be walked as an export,
* ``types`` must name known types, so a typo is a 400 rather than a silently
  narrower search that looks like "no results".

The **response serializers** exist to pin the contract rather than to transform
anything: the selectors already emit plain dictionaries in the response's shape.
Declaring them means `docs/INTEGRATION.md` describes a shape that is enforced in
code, and a field renamed in a selector fails a test instead of quietly changing
the API.
"""

from __future__ import annotations

from typing import Any

from core.nepal.text import normalize_unicode
from rest_framework import serializers

from search.constants import (
    DEFAULT_LIMIT_PER_TYPE,
    MAX_LIMIT_PER_TYPE,
    MAX_QUERY_LENGTH,
    MIN_QUERY_LENGTH,
    SEARCHABLE_TYPE_KEYS,
)


class SearchQuerySerializer(serializers.Serializer):
    """The one query parameter set for ``GET /api/v1/search/``.

    ``q`` is required — unlike a list endpoint, an unqueried global search has
    no meaningful answer. Returning "everything" across nine types would be nine
    unfiltered table scans to answer a question nobody asked.
    """

    q = serializers.CharField(max_length=MAX_QUERY_LENGTH, allow_blank=False, trim_whitespace=True)

    types = serializers.CharField(required=False, allow_blank=True)

    limit_per_type = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_LIMIT_PER_TYPE,
        default=DEFAULT_LIMIT_PER_TYPE,
    )

    def validate_q(self, value: str) -> str:
        """Normalize, then enforce the minimum length on what is left.

        ``normalize_unicode`` runs first because §39.2 requires it on every
        user-entered text field, and because two byte-different spellings of the
        same accented name must not search differently.

        The length check runs **after** stripping, so three spaces is not a
        two-character query. One character matches a large fraction of every
        table through ``icontains``: it would return nine expensive scans and
        nothing usable, and a 400 that says so is more honest than a slow 200.
        """
        value = normalize_unicode((value or "").strip())
        if len(value) < MIN_QUERY_LENGTH:
            raise serializers.ValidationError(
                f"Must be at least {MIN_QUERY_LENGTH} characters.",
            )
        return value

    def validate_types(self, value: str) -> list[str]:
        """Parse and check the comma-separated type filter.

        An unknown key is rejected rather than ignored. Skipping it would return
        a narrower result set that looks exactly like "nothing matched", and the
        client author would debug their query instead of their typo. The error
        names the valid keys so the fix needs no documentation lookup.
        """
        raw = (value or "").strip()
        if not raw:
            return []

        keys = [part.strip() for part in raw.split(",") if part.strip()]
        unknown = [key for key in keys if key not in SEARCHABLE_TYPE_KEYS]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown record type(s): {', '.join(sorted(unknown))}. "
                f"Valid types: {', '.join(SEARCHABLE_TYPE_KEYS)}."
            )
        # De-duplicated, but order is not preserved: the selector re-orders to
        # the catalogue's own section order regardless.
        return list(dict.fromkeys(keys))

    def to_params(self) -> dict[str, Any]:
        """The validated input as the keyword arguments ``search_everything`` takes."""
        data = self.validated_data
        return {
            "query": data["q"],
            "types": data.get("types") or None,
            "limit_per_type": data.get("limit_per_type", DEFAULT_LIMIT_PER_TYPE),
        }


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class SearchHitSerializer(serializers.Serializer):
    """One found record, reduced to what a result row needs.

    ``detail_path`` is an **API** path, not a frontend route: this app cannot
    know a client's routing table, and inventing one would bake a guess into the
    contract. ``entity_type`` is what a client routes on.
    """

    entity_type = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    subtitle = serializers.CharField(allow_blank=True)
    matched_on = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    detail_path = serializers.CharField()
    detail_permission_key = serializers.CharField()


class SearchBucketSerializer(serializers.Serializer):
    """One type's section: its true total, its first few rows, and where the rest are."""

    entity_type = serializers.CharField()
    label = serializers.CharField()
    group = serializers.CharField()
    total = serializers.IntegerField()
    has_more = serializers.BooleanField()
    hits = SearchHitSerializer(many=True)
    list_url = serializers.CharField()
    list_permission_key = serializers.CharField()


class SearchResultSerializer(serializers.Serializer):
    """The whole results panel for one query."""

    query = serializers.CharField()
    types = serializers.ListField(child=serializers.CharField())
    total_hits = serializers.IntegerField()
    results = SearchBucketSerializer(many=True)


class SearchableTypeSerializer(serializers.Serializer):
    """One catalogue row for ``GET /api/v1/search/types/``."""

    key = serializers.CharField()
    label = serializers.CharField()
    group = serializers.CharField()
    app_label = serializers.CharField()
    matched_fields = serializers.ListField(child=serializers.CharField())
    detail_path = serializers.CharField()
    detail_permission_key = serializers.CharField()
    list_path = serializers.CharField()
    list_search_param = serializers.CharField()
    list_permission_key = serializers.CharField()
