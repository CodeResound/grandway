"""Shared setup helpers for the reminders test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``. That keeps the fixtures honest: an applicant or
client built here went through the same validation and audit path a real one
does, so a test that passes against these fixtures is testing the real system.

The one exception is ``make_overdue_reminder``: the create *serializer*
rejects past due dates, but the service does not — deliberately, because a
reminder becomes overdue by time passing, not by being created that way. The
factory reaches for the service directly with a past date to simulate exactly
that aging.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from applicants import services as applicant_services
from authenticate import services as auth_services
from authenticate.constants import AuthorityType
from clients import services as client_services
from core.nepal.calendar import nepal_today

from reminders import services

STRONG_PW = "Str0ng-Passphrase-17"


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------


def make_user(username: str, authority: str) -> Any:
    return auth_services.create_account(
        username=username,
        password=STRONG_PW,
        authority_type=authority,
        provisioned_via="admin_created",
        must_change_password=False,
        display_name=username.title(),
    )


def make_admin(username: str = "adminuser") -> Any:
    return make_user(username, AuthorityType.ADMIN)


def make_lead_manager(username: str = "leadmgr") -> Any:
    return make_user(username, AuthorityType.LEAD_MANAGER)


def make_superadmin(username: str = "superuser") -> Any:
    return make_user(username, AuthorityType.SUPERADMIN)


def token_for(user: Any) -> str:
    session, _ = auth_services.issue_session(user=user, device_id=f"dev-{user.username}")
    return auth_services.build_access_token(user, session, must_change_password=False)


def auth(client: Any, user: Any) -> None:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")


# ---------------------------------------------------------------------------
# The records a reminder attaches to
# ---------------------------------------------------------------------------


def make_applicant(actor: Any, *, name: str = "Ram Bahadur", **overrides: Any) -> Any:
    return applicant_services.create_applicant(
        actor=actor,
        data={"full_name": name, **overrides},
        contact_numbers=[{"number": "9800000000", "label": "mobile", "is_primary": True}],
    )


def make_client(actor: Any, *, name: str = "Himal Education", **overrides: Any) -> Any:
    return client_services.create_client(actor=actor, data={"name": name, **overrides})


# ---------------------------------------------------------------------------
# Reminders — always through the service, so the audit trail is real
# ---------------------------------------------------------------------------


def make_reminder(
    actor: Any,
    *,
    applicant: Any = None,
    client: Any = None,
    due_in_days: int = 3,
    note: str = "Chase the pending documents.",
) -> Any:
    """An open reminder due ``due_in_days`` from Nepal's today (may be negative)."""
    return services.create_reminder(
        actor=actor,
        applicant=applicant,
        client=client,
        due_date=nepal_today() + timedelta(days=due_in_days),
        note=note,
    )


def due_on(days_from_today: int) -> date:
    return nepal_today() + timedelta(days=days_from_today)
