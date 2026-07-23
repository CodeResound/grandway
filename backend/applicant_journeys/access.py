"""Interim inline access checks for the applicant_journeys app (§9).

Journeys are shared exactly as applicants are: any Admin or Lead Manager may
read and write any journey, and Superadmin is denied outright. See
``docs/SECURITY.md`` §1 and ``concepts/applicant_journeys.txt`` — "Permissions".

Unlike ``applicants``, creation is **not** Admin-restricted: a Lead Manager
routinely adds a second or third objective for an existing client, which is
ordinary operational work rather than an entry decision.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from applicant_journeys.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_journey_actor(user: object) -> None:
    """Allow Admin and Lead Manager only."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access journey records.")
