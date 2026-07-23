"""Interim inline access checks for the leads app (§9).

CLAUDE.md §9's interim snippet (``is_authenticated`` + ``is_staff``) cannot
express what this app needs: leads are *owner-scoped* rows, and the split that
matters is Admin vs Lead Manager, not staff vs non-staff. These helpers are the
minimal, documented stand-in until the ``permissions`` app is wired into the
request path — see ``docs/SECURITY.md`` §1 and ``docs/API.md`` §1.

Two rules, applied everywhere:

* **Superadmin is denied.** It is a platform authority that manages Admin
  accounts and "should not manage leads, applicants, documents, journeys…
  unless it separately holds an ordinary Admin account"
  (``concepts/authenticate.txt`` — "Authority structure").
* **Lead Managers see only what they created.** Enforced by narrowing the
  queryset in ``selectors``, never by filtering in Python after the fact.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from leads.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_lead_actor(user: object) -> None:
    """Allow Admin and Lead Manager only.

    Raises ``ActorNotPermittedError`` for every other authority (superadmin
    today), which views translate to 403 ``LEADS_ACTOR_FORBIDDEN``.
    """
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access lead records.")


def require_admin(user: object) -> None:
    """Allow Admin only — used for reference configuration and conversion."""
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required for this action.")
