"""Shared setup helpers for the offers test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``. That keeps the fixtures honest: a journey built here
went through the same validation and audit path a real one does, so a test that
passes against these fixtures is testing the real system.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from applicant_journeys import services as journey_services
from applicants import services as applicant_services
from authenticate import services as auth_services
from authenticate.constants import AuthorityType
from institutions import services as catalogue_services

from offers import services

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


# ---------------------------------------------------------------------------
# The chain an offer hangs from: applicant → journey
# ---------------------------------------------------------------------------


def make_applicant(actor: Any, *, name: str = "Ram Bahadur", **overrides: Any) -> Any:
    return applicant_services.create_applicant(
        actor=actor,
        data={"full_name": name, **overrides},
        contact_numbers=[{"number": "9800000000", "label": "mobile", "is_primary": True}],
    )


def make_journey(actor: Any, applicant: Any, **overrides: Any) -> Any:
    return journey_services.create_journey(
        actor=actor,
        applicant=applicant,
        data={"target_country": "Australia", **overrides},
    )


# ---------------------------------------------------------------------------
# The catalogue an offer snapshots from
# ---------------------------------------------------------------------------


def make_catalogue(actor: Any) -> dict[str, Any]:
    """A complete country → institution → campus → program chain."""
    country = catalogue_services.create_country(actor=actor, data={"code": "au", "name": "Australia"})
    field = catalogue_services.create_field(
        actor=actor, data={"code": "information_technology", "name": "Information Technology"}
    )
    institution = catalogue_services.create_institution(
        actor=actor, data={"country": country, "name": "University of Melbourne"}
    )
    campus = catalogue_services.create_campus(actor=actor, institution=institution, data={"name": "Parkville"})
    program = catalogue_services.create_program(
        actor=actor,
        data={
            "institution": institution,
            "campus": campus,
            "field": field,
            "title": "Master of Information Technology",
            "qualification_level": "masters",
            "intake_pattern": "Feb / Jul",
        },
    )
    return {
        "country": country,
        "field": field,
        "institution": institution,
        "campus": campus,
        "program": program,
    }


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


def make_offer(actor: Any, journey: Any, *, program: Any = None, **overrides: Any) -> Any:
    """An offer built from a catalogue program unless ``program`` is None."""
    data: dict[str, Any] = {"offer_type": "conditional", **overrides}
    conditions = data.pop("conditions", None)
    return services.create_offer(
        actor=actor,
        journey=journey,
        data=data,
        program=program,
        conditions=conditions,
    )


def make_manual_offer(actor: Any, journey: Any, **overrides: Any) -> Any:
    """An offer with no catalogue record behind it — a historical entry."""
    data: dict[str, Any] = {
        "institution_name": "Ancient Polytechnic",
        "program_title": "Diploma in Hospitality",
        "intake_label": "Sep 2019",
        **overrides,
    }
    return services.create_offer(actor=actor, journey=journey, data=data)


def priced(amount: str = "49824.00", currency: str = "AUD", period: str = "total_program") -> dict[str, Any]:
    """A complete tuition triple — amount, currency, and period together."""
    return {
        "tuition_amount": Decimal(amount),
        "tuition_currency": currency,
        "tuition_fee_period": period,
    }


def condition(condition_type: str = "english_test", **overrides: Any) -> dict[str, Any]:
    """One condition payload, as the create endpoint accepts it."""
    return {
        "condition_type": condition_type,
        "description": "IELTS overall 6.5 with no band below 6.0.",
        **overrides,
    }
