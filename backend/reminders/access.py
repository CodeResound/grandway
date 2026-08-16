"""Interim inline access checks for the reminders app (§9).

Reminders are shared operational work: any Admin or Lead Manager may create,
read, and maintain any reminder, and Superadmin is denied outright. The
concept's asymmetry — only Admins *receive* the due alert — is a notification
routing fact (``notifications.services.recipients_for_admins``), not an access
rule here: the Lead Manager who set a reminder can always see and close it.

There is deliberately one rule for read and write, as in ``offers``: a
reminder is a note on a record the actor already works, and letting them see
it but not complete it would put an Admin in the middle of every routine
follow-up.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from reminders.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_reminder_actor(user: object) -> None:
    """Allow Admin and Lead Manager only."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access reminders.")
