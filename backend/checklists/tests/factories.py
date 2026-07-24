"""Shared setup helpers for the checklists test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``, so a fixture goes through the same validation and
audit path a real record does. The actor, applicant, journey, and catalogue
helpers are re-exported from ``uploaded_files.tests.factories`` rather than
reimplemented — that suite already builds the whole applicant → journey →
catalogue → file chain this one needs, including real file bytes for the
evidence tests, and a second copy would drift on the setup every test here
depends on.
"""

from __future__ import annotations

from typing import Any

from uploaded_files.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    STRONG_PW,
    make_admin,
    make_applicant,
    make_catalogue,
    make_journey,
    make_lead_manager,
    make_manual_offer,
    make_superadmin,
    make_user,
    pdf_upload,
    token_for,
    upload_for,
    upload_for_applicant,
)

from checklists import services
from checklists.constants import ItemType, TemplateStatus


def make_template(
    actor: Any,
    *,
    country: Any = None,
    key: str = "australia-student",
    label: str = "Australia — Student Visa",
    is_default: bool = True,
    status: str = TemplateStatus.ACTIVE,
    **overrides: Any,
) -> Any:
    """One country requirement list, active and inheritable by default.

    Active by default because the interesting behaviour — inheritance — only
    happens for an active template, and a suite whose fixtures were all drafts
    would test the guard rather than the feature.
    """
    return services.create_template(
        actor=actor,
        data={
            "key": key,
            "label": label,
            "country": country,
            "is_default": is_default,
            "status": status,
            **overrides,
        },
    )


def add_requirement(
    actor: Any,
    template: Any,
    *,
    label: str = "Passport bio page scan",
    item_type: str = ItemType.DOCUMENT,
    is_required: bool = True,
    **overrides: Any,
) -> Any:
    """One requirement definition on a template."""
    return services.add_template_item(
        actor=actor,
        template=template,
        data={"label": label, "item_type": item_type, "is_required": is_required, **overrides},
    )


def make_country_template(actor: Any, country: Any, **overrides: Any) -> Any:
    """A country's default list with three real requirements on it.

    Two required documents and one optional stage — enough shape for the
    completion rule to be worth testing, since a list where everything is
    required could not distinguish "all done" from "all required work done".
    """
    template = make_template(actor, country=country, **overrides)
    add_requirement(actor, template, label="Passport bio page scan", display_order=1)
    add_requirement(actor, template, label="Academic transcripts", display_order=2)
    add_requirement(
        actor,
        template,
        label="Application submitted",
        item_type=ItemType.STAGE,
        is_required=False,
        display_order=3,
    )
    return template


def set_journey_country(actor: Any, journey: Any, country: Any) -> Any:
    """Choose the applicant's destination — the act that triggers inheritance.

    Goes through the journey app's own service rather than assigning the field,
    so the ``post_save`` the whole feature hangs off actually fires.
    """
    from applicant_journeys import services as journey_services

    return journey_services.update_journey(
        actor=actor,
        journey=journey,
        fields={"target_country_ref": country},
    )
