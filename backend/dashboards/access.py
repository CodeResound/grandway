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
