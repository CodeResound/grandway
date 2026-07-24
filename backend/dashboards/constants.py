"""Enums and stable constants for the dashboards app.

This app owns no table, so nothing here is a model choice field. What it does
own is the vocabulary of its own API: the error codes it can return and the
defaults that decide what "soon" and "expiring" mean.
"""

from __future__ import annotations

#: Default horizon for "due soon" — checklist items falling due, offers whose
#: response deadline is approaching. A week is the span a person can actually
#: plan around: shorter and the list is empty until it is already urgent,
#: longer and everything is always on it.
DEFAULT_DUE_WITHIN_DAYS: int = 7

#: Upper bound on the caller-supplied ``due_within_days``. A year-long "due
#: soon" window is not a due-soon list, it is the whole table, and serving it
#: from a section meant for immediate action is worse than refusing.
MAX_DUE_WITHIN_DAYS: int = 90

#: Default horizon for an expiring passport. Deliberately far longer than
#: ``DEFAULT_DUE_WITHIN_DAYS``: renewing a Nepali passport is not a same-week
#: errand, and a visa cannot be lodged on one that expires too soon. Six months
#: is the point at which it becomes actionable, not the point at which it
#: becomes a problem.
DEFAULT_PASSPORT_HORIZON_DAYS: int = 180

#: Days without any follow-up after which a live lead counts as stale. A lead
#: has no due date — silence is the only signal there is.
DEFAULT_STALE_LEAD_DAYS: int = 7

#: How many rows a worklist section returns inline before a caller must page
#: through the owning app's list endpoint. The dashboard's job is to get someone
#: to the next action, not to become a second list view (``concepts/dashboards.txt``
#: — "Boundaries").
WORKLIST_PREVIEW_LIMIT: int = 10

#: How many audit events the activity feed returns per page.
ACTIVITY_PAGE_SIZE: int = 20


class ErrorCode:
    """Stable error codes, `APP_RESOURCE_REASON` per §7."""

    ACTOR_FORBIDDEN = "DASHBOARDS_ACTOR_FORBIDDEN"
    FILTER_INVALID = "DASHBOARDS_FILTER_INVALID"
