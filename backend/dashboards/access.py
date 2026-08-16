"""Interim inline access checks for the dashboards app (§9).

This app reads across nearly every other app, which makes its access rule the
one place a mistake would be most costly: a dashboard that ignored another
app's scoping would leak, in aggregate, exactly what that app refuses to show
row by row.

Two rules, and the second is the one that matters:

* **Superadmin is denied**, as in every business app. It is a platform authority
  that manages Admin accounts and does not participate in consultancy operations
  (``concepts/authenticate.txt`` — "Authority structure").
* **Admin and Lead Manager call the same endpoints, and the scoping happens in
  the selectors, not here.** There is no separate "manager dashboard". Every
  lead-derived figure is built on ``leads.selectors.get_leads_for_actor``, so a
  Lead Manager's funnel counts, source mix, and workload row cover only their
  own leads; applicants, journeys, offers, checklists, and documents are shared
  across the consultancy and are not narrowed, because those apps do not narrow
  them either. Files carry their own visibility rule and are read through
  ``uploaded_files.selectors.get_visible_files``.

The consequence worth stating plainly: **an Admin and a Lead Manager calling the
same URL will legitimately see different numbers.** That is the scoping working,
not a bug, and `docs/API.md` §1 says so to a client author who would otherwise
report it as one.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from dashboards.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_dashboard_actor(user: object) -> None:
    """Allow Admin and Lead Manager only — the whole operational population."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not read the dashboard.")


def require_activity_reader(user: object) -> None:
    """Allow only those who may read the central audit log.

    The activity feed is not a summary of rows this app owns — it *is* the
    ``audit`` log, returned row by row. Every other dashboard section is built
    from selectors whose owning app already scoped them, so passing the actor
    down was enough; this one reads a table with its own, stricter rule, and
    reading it through a different door does not soften that rule.

    The rule mirrors ``audit/views.py``'s ``_require_staff`` — ``is_staff``,
    which is true for Admin and Superadmin and false for Lead Manager. It is
    restated here rather than imported because §4 permits importing another
    app's selectors and services, not its access checks; ``uploaded_files``
    made the same call for the same reason. The cost is that a change to the
    audit app's rule must be mirrored here, which is why both sides now say so.

    **This closes a real leak, not a hypothetical one.** A Lead Manager was
    refused by ``GET /api/v1/audit/events/`` with a 403 and served the same rows
    by ``GET /api/v1/dashboard/activity/`` with a 200 — including the actor and
    summary of administrative password resets. ``get_activity``'s own docstring
    justified going unnarrowed on the grounds that the audit endpoint is one
    "which any of these users may already call"; that was assumed rather than
    checked, and it was false for the one tier it mattered for.
    """
    if not getattr(user, "is_staff", False):
        raise ActorNotPermittedError("The activity feed is restricted to administrators.")
