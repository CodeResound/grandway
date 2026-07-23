"""Interim inline access checks for the applicants app (§9).

Unlike ``leads``, applicants are **not** owner-scoped. Any Admin or Lead Manager
may read and edit any applicant: once a person enters the applicant lifecycle
they are the consultancy's client rather than one staff member's prospect, and
several people will legitimately work on their file
(``concepts/applicants.txt`` — "Visibility"). See ``docs/SECURITY.md`` §1.

Two rules remain:

* **Superadmin is denied.** It is a platform authority that manages Admin
  accounts and does not participate in consultancy operations
  (``concepts/authenticate.txt`` — "Authority structure").
* **Only an Admin may create an applicant**, by either path. Lead Managers work
  leads; entry into the applicant lifecycle is an Admin decision.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from applicants.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_applicant_actor(user: object) -> None:
    """Allow Admin and Lead Manager only — the read/write population."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access applicant records.")


def require_admin(user: object) -> None:
    """Allow Admin only — applicant creation and lead conversion."""
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required for this action.")
