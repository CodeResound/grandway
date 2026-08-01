"""Interim inline access checks for the search app (§9).

This app reads across nine record types owned by seven other apps, which makes
its access rule the one place a mistake would be most costly — the same reason
``dashboards/access.py`` opens with that sentence. The failure mode here is
sharper, though: a dashboard leaks in aggregate, whereas a search box leaks the
individual row, by name, to whoever guesses at the name.

Two rules:

* **Superadmin is denied**, as in every business app. It is a platform authority
  that manages Admin accounts and does not participate in consultancy
  operations (``concepts/authenticate.txt`` — "Authority structure").
* **Admin and Lead Manager call the same endpoint, and the narrowing happens in
  the owning apps' selectors, not here.** There is no "manager search". Lead
  results come through ``leads.selectors.get_leads_for_actor`` and files through
  ``uploaded_files.selectors.get_visible_files``, so a Lead Manager searching a
  name gets their own leads and no Admin-only files; every other type is
  unnarrowed because those apps do not narrow their own lists either.

**The rule this app must never break.** A record appears in results only if the
owning app would have shown that row to that caller in its own list. Search is
the most tempting place in the project to write a convenient
``Model.objects.filter(...)`` — it would be shorter and faster than composing
nine selectors — and doing so would silently rebuild each app's access rule in a
second place, where it is not tested. ``dashboards`` shipped exactly that defect
in its activity feed: a Lead Manager refused by the audit endpoint with a 403
was served the same rows by the dashboard with a 200. This app is structured so
that the equivalent mistake is not available: ``search/selectors.py`` imports no
model, only selectors.

Consequence worth stating plainly, because a client author will otherwise report
it as a bug: **an Admin and a Lead Manager searching the same word will
legitimately get different totals.** ``docs/API.md`` §1 says so.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from search.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_search_actor(user: object) -> None:
    """Allow Admin and Lead Manager only — the whole operational population."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not use global search.")
