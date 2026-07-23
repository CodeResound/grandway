"""Shared setup helpers for the institutions test suite.

Users are built straight from ``authenticate`` rather than reusing
``applicants.tests.factories``: this app has no dependency on ``applicants``,
and borrowing its factory would invent one in the test suite that does not
exist in the code.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from authenticate import services as auth_services
from authenticate.constants import AuthorityType

from institutions import services

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
# Catalogue records — always built through the services, so every rule and
# audit event a real create would apply also applies here.
# ---------------------------------------------------------------------------


def make_field(actor: Any, *, code: str = "information_technology", **overrides: Any) -> Any:
    data = {"code": code, "name_en": "Information Technology", **overrides}
    return services.create_field(actor=actor, data=data)


def make_country(actor: Any, *, code: str = "au", **overrides: Any) -> Any:
    data = {"code": code, "name_en": "Australia", **overrides}
    return services.create_country(actor=actor, data=data)


def make_institution(actor: Any, country: Any, **overrides: Any) -> Any:
    data = {"country": country, "name_en": "University of Melbourne", **overrides}
    return services.create_institution(actor=actor, data=data)


def make_campus(actor: Any, institution: Any, *, name_en: str = "Parkville", **overrides: Any) -> Any:
    data = {"name_en": name_en, **overrides}
    return services.create_campus(actor=actor, institution=institution, data=data)


def make_program(actor: Any, institution: Any, field: Any, **overrides: Any) -> Any:
    data = {
        "institution": institution,
        "field": field,
        "title": "Master of Information Technology",
        "qualification_level": "masters",
        **overrides,
    }
    return services.create_program(actor=actor, data=data)


def priced(amount: str = "49824.00", currency: str = "AUD", period: str = "total_program") -> dict[str, Any]:
    """A complete tuition triple — amount, currency, and period together."""
    return {
        "tuition_amount": Decimal(amount),
        "tuition_currency": currency,
        "tuition_fee_period": period,
    }
