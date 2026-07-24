"""Interim inline access checks for the notifications app (§9).

Two rules, and the second is the one that matters.

**1. Admin and Lead Manager may use the feed.** Both are named in
``concepts/project_overview.txt`` as recipients — an Admin manages
"notifications" among everything else, and a Lead Manager "responds to
notifications". Superadmin is denied outright, matching ``applicants``,
``applicant_journeys``, ``offers``, ``uploaded_files``, and ``checklists``: it is
a platform authority that manages Admin accounts and does not participate in
consultancy operations (``concepts/authenticate.txt``).

**2. The feed is own-recipient only — including for an Admin.** This is stricter
than every other app in the project and it is the deliberate exception, not an
oversight:

* Everywhere else, the record is a fact about the business. An applicant's file
  is legitimately readable by several staff, which is exactly why ``applicants``
  is not owner-scoped and why ``checklists`` inherited that decision.
* A notification is not a fact about the business — the source record is. A
  notification is a fact about *one person's queue*: what they have been told,
  what they have read, what they have decided to make go away. Reading somebody
  else's is closer to reading their unread mail than to reading a shared file,
  and it discloses nothing about the business that the source app's own
  endpoints do not already disclose to an Admin directly.
* So the scoping costs an Admin nothing operationally: everything a notification
  points at is readable through ``checklists``, ``offers``, ``applicants``, and
  ``uploaded_files`` with the authority they already hold. What it removes is the
  ability to audit somebody's inbox over the API without leaving a trace.

Cross-user inspection is not impossible, it is *attributable*: it happens in
Django admin, where it is a deliberate act by a named superuser.

**Rule 2 is not enforced by a function in this file, and that is the point.** It
lives in ``selectors.get_feed`` and ``selectors.get_own_notification``, both of
which take the actor and narrow by ``recipient`` before anything else. A boolean
``may_read(user, notification)`` would have to be *called* to work, and the one
call site that forgets is a silent cross-user disclosure; a selector that cannot
return another user's row has no such failure mode.

The consequence a reader should know about: fetching somebody else's
notification by id returns **404, not 403**. That is deliberate. A 403 would
confirm the id exists on another person's feed, and a notification title names
an applicant and the document they are missing.

Declared locally rather than imported: §4 permits importing another app's
``selectors.py`` and ``services.py``, and ``access.py`` is not on that list. An
access rule silently inherited across a boundary is the coupling that makes a
later divergence invisible.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from notifications.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_notification_actor(user: object) -> None:
    """Allow Admin and Lead Manager — every endpoint in this app.

    The only authority check this app makes. Everything else is recipient
    scoping, which happens in the selectors.
    """
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access notifications.")
