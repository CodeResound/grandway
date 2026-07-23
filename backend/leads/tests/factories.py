"""Shared setup helpers for the leads test suite."""

from __future__ import annotations

from typing import Any

from authenticate import services as auth_services
from authenticate.constants import AuthorityType

from leads.models import Lead, LeadSource, LossReason

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


def make_source(code: str = "walk_in", *, requires_detail: bool = False, is_active: bool = True) -> LeadSource:
    return LeadSource.objects.create(
        code=code,
        name_np="वाक-इन",
        name_en="Walk-in",
        requires_detail=requires_detail,
        is_active=is_active,
    )


def make_loss_reason(
    code: str = "no_response",
    *,
    requires_detail: bool = False,
    is_active: bool = True,
) -> LossReason:
    return LossReason.objects.create(
        code=code,
        name_np="कुनै जवाफ छैन",
        name_en="No response",
        requires_detail=requires_detail,
        is_active=is_active,
    )


def make_lead(owner: Any, source: LeadSource, *, name_np: str = "राम श्रेष्ठ") -> Lead:
    """Create a lead directly through the service so derived fields are set."""
    from leads import services

    return services.create_lead(
        actor=owner,
        data={"full_name_np": name_np, "source": source},
        contact_numbers=[{"number": "9800000000", "label": "mobile", "is_primary": True}],
    )
