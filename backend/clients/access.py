"""Interim inline access checks for the clients app (§9).

The directory is **read-shared, write-restricted** — the same split as
``institutions``, and for the same reason:

* **Every Admin and Lead Manager may read.** Looking up who to call at a
  partner organization is the whole point of the directory
  (``concepts/clients.txt`` — "Find the right partner" describes a Lead Manager
  doing exactly this). A directory only Admins can see is a phone list in a
  drawer.
* **Only an Admin may write.** Every maintenance flow in the concept begins
  "An Admin creates or updates a client". Client records are shared reference
  data: one careless edit to a spokesperson's number changes who every Lead
  Manager calls, so the edit right is narrower than the read right. Blast
  radius, not sensitivity, is what narrows it.
* **Superadmin is denied outright.** It is a platform authority that manages
  Admin accounts and does not participate in consultancy operations
  (``concepts/authenticate.txt`` — "Authority structure").

See ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from clients.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_client_reader(user: object) -> None:
    """Allow Admin and Lead Manager — the read population."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access client records.")


def require_admin(user: object) -> None:
    """Allow Admin only — every client create, update, retire, and restore."""
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to maintain the client directory.")
