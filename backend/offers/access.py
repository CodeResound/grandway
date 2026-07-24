"""Interim inline access checks for the offers app (§9).

Offers are shared exactly as the journeys they belong to are: any Admin or Lead
Manager may read and write any offer, and Superadmin is denied outright. See
``docs/SECURITY.md`` §1.

There is deliberately **one rule for read and write**, unlike ``institutions``.
An offer is journey-scoped operational work: the Lead Manager who is running
the journey is the person who receives the institution's letter and records the
applicant's answer. Letting them see an offer but not record its decision would
put an Admin in the middle of every routine admission response.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from offers.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_offer_actor(user: object) -> None:
    """Allow Admin and Lead Manager only."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access offer records.")
