"""Shared setup helpers for the applicants test suite."""

from __future__ import annotations

from typing import Any

from authenticate import services as auth_services
from authenticate.constants import AuthorityType

from applicants import services
from applicants.models import Applicant

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


def make_applicant(creator: Any, *, name: str = "Ram Shrestha", **overrides: Any) -> Applicant:
    """Create an applicant through the service so derived fields are set."""
    data = {"full_name": name, **overrides}
    return services.create_applicant(
        actor=creator,
        data=data,
        contact_numbers=[{"number": "9800000000", "label": "mobile", "is_primary": True}],
    )
