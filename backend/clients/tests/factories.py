"""Shared setup helpers for the clients test suite.

Users are built straight from ``authenticate``: this app has no dependency on
``applicants`` or ``leads``, and borrowing one of their factories would invent a
coupling in the test suite that does not exist in the code.
"""

from __future__ import annotations

from typing import Any

from authenticate import services as auth_services
from authenticate.constants import AuthorityType

from clients import services

STRONG_PW = "Str0ng-Passphrase-17"


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


# ---------------------------------------------------------------------------
# Clients — always built through the service, so every rule and audit event a
# real create would apply also applies here.
# ---------------------------------------------------------------------------


def make_client(actor: Any, *, name_np: str = "हिमाल एजुकेशन", **overrides: Any) -> Any:
    contact_numbers = overrides.pop("contact_numbers", None)
    data: dict[str, Any] = {"name_np": name_np, "name_en": "Himal Education", **overrides}
    return services.create_client(actor=actor, data=data, contact_numbers=contact_numbers)


def number(value: str = "9801111111", label: str = "mobile", is_primary: bool = False) -> dict[str, Any]:
    """One contact-number payload, as the create endpoint accepts it."""
    return {"number": value, "label": label, "is_primary": is_primary}
