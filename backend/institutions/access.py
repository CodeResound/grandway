"""Interim inline access checks for the institutions app (§9).

The catalogue is **read-shared, write-restricted** — the inverse split from
``applicants``, where creation is the only Admin gate:

* **Every Admin and Lead Manager may read.** Search is the point of the
  catalogue; a Lead Manager who cannot see it cannot counsel anyone
  (``concepts/institutions.txt`` — "staff can now rely on the catalogue during
  counselling").
* **Only an Admin may write.** Every maintenance flow in the concept begins
  "Admin creates or updates". Catalogue data is shared infrastructure: one
  careless edit silently changes what every Lead Manager sees, so the edit
  right is narrower than the read right.
* **Superadmin is denied outright.** It is a platform authority that manages
  Admin accounts and does not participate in consultancy operations
  (``concepts/authenticate.txt`` — "Authority structure").

See ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from institutions.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_catalogue_reader(user: object) -> None:
    """Allow Admin and Lead Manager — the read population."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access catalogue records.")


def require_admin(user: object) -> None:
    """Allow Admin only — every catalogue create and update."""
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to maintain the catalogue.")
