"""Queryset helpers shared by more than one app (§2, "shared utilities used by 2+ apps").

Only one thing lives here, and it earns its place by being needed identically in
seven apps: narrowing a queryset to a time window. Every app's dashboard summary
selectors accept the same three ways of expressing "when" — an explicit
``date_from``/``date_to`` pair and a Nepali fiscal year — and duplicating the
resolution of those across seven ``selectors.py`` files is exactly the
duplication §3 forbids.

Two details here are easy to get wrong and quiet when wrong, which is why they
live in one place rather than seven:

* **``date_to`` is inclusive to the caller and exclusive in SQL.** A user
  picking "up to the 24th" means the whole of the 24th. Comparing ``< 24th``
  drops that day's rows, and a dashboard would report the loss as a real decline
  in volume rather than an off-by-one.
* **A calendar day is a Nepal day (§39.5).** Staff pick dates in Kathmandu,
  timestamps are stored in UTC, and the offset is +05:45. Treating the boundary
  as UTC midnight shifts every window by 5¾ hours, so a record created at 09:00
  NPT lands in the previous day's bucket.

This is deliberately **not** a query builder, a filter framework, or a base
selector. It resolves a date window and applies it. Anything app-specific stays
in the app that owns the rows.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import QuerySet

from core.nepal.calendar import fiscal_year_gregorian_range
from core.nepal.constants import NEPAL_TZ


def resolve_window(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> tuple[date | None, date | None]:
    """Resolve the three ways of expressing "when" into one half-open window.

    ``fiscal_year`` (``YYYY/YY``, §39.4) is the coarse control and an explicit
    ``date_from``/``date_to`` is the fine one, so an explicit bound **wins**
    where both are given. A client that sets a fiscal year and then drags a date
    handle inside it expects the handle to be obeyed, not silently widened back
    to the whole year.

    Returns ``(start, end)`` where ``start`` is inclusive and ``end`` is
    **exclusive** — matching what ``fiscal_year_gregorian_range`` already
    returns. A caller-supplied ``date_to`` is inclusive, so it is advanced by one
    day here; that conversion happens once, in this function, and nowhere else.
    Either bound may be ``None``, meaning unbounded on that side.
    """
    start: date | None = None
    end: date | None = None

    if fiscal_year:
        start, end = fiscal_year_gregorian_range(fiscal_year)

    if date_from:
        start = date_from
    if date_to:
        end = date_to + timedelta(days=1)

    return start, end


def narrow_to_window(
    queryset: QuerySet[Any],
    *,
    field: str = "created_at",
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: str | None = None,
) -> QuerySet[Any]:
    """Filter ``queryset`` to the window described by the three date controls.

    ``field`` names the column to compare. ``created_at`` answers "records made
    in this period"; a caller reporting on outcomes passes ``decided_at`` or
    ``closed_at`` instead, because "offers accepted in Shrawan" is a question
    about when the decision happened, not when the offer was recorded.

    Datetime columns are compared against Kathmandu-midnight boundaries; date
    columns against plain dates, since a stored date carries no time to shift.
    """
    start, end = resolve_window(date_from=date_from, date_to=date_to, fiscal_year=fiscal_year)
    if start is None and end is None:
        return queryset

    is_datetime = _is_datetime_field(queryset.model, field)
    if start is not None:
        queryset = queryset.filter(**{f"{field}__gte": _bound(start, is_datetime)})
    if end is not None:
        queryset = queryset.filter(**{f"{field}__lt": _bound(end, is_datetime)})
    return queryset


def _bound(value: date, is_datetime: bool) -> date | datetime:
    """The comparison value for one edge of the window."""
    return _nepal_midnight(value) if is_datetime else value


def _nepal_midnight(value: date) -> datetime:
    """The instant ``value`` begins in Kathmandu, as an aware datetime (§39.5)."""
    return datetime.combine(value, time.min, tzinfo=NEPAL_TZ)


def _is_datetime_field(model: Any, field: str) -> bool:
    """True when ``field`` on ``model`` stores a datetime rather than a date."""
    try:
        return model._meta.get_field(field).get_internal_type() == "DateTimeField"
    except Exception:
        # An annotation, or a traversed path rather than a local column.
        # Treating it as a datetime is the safe default: the bounds stay aware,
        # and an aware bound compares correctly against either column type.
        return True
