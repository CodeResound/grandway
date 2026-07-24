"""Shared setup helpers for the document_templates test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``, so a fixture goes through the same validation, Nepali
localization, and audit path a real record does.

The actor helpers are re-exported from ``documents.tests.factories`` rather than
reimplemented — the same call ``document_history`` made. Duplicating account
creation across three suites would let them drift on the one thing every test
in all three depends on.
"""

from __future__ import annotations

from typing import Any

from documents.constants import DocumentFamily
from documents.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    STRONG_PW,
    make_admin,
    make_lead_manager,
    make_superadmin,
    make_user,
    token_for,
)

from document_templates import services
from document_templates.constants import LifecycleStatus

#: A signatory name used across the suite.
NAME = "Sunita Shrestha"


def make_signatory(actor: Any, **overrides: Any) -> Any:
    """A signatory, ``draft`` by default — the service's own default."""
    data: dict[str, Any] = {
        "name": NAME,
        "title": "Director",
        "role": "director",
        "signature_image_url": "https://files.example/signatures/sunita.png",
        **overrides,
    }
    return services.create_signatory(actor=actor, data=data)


def make_active_signatory(actor: Any, **overrides: Any) -> Any:
    """A signatory that would appear in the frontend's picker."""
    signatory = make_signatory(actor, **overrides)
    return services.change_signatory_status(
        actor=actor,
        signatory=signatory,
        status=LifecycleStatus.ACTIVE,
    )


def make_template(actor: Any, **overrides: Any) -> Any:
    """A catalogue row, ``draft`` by default."""
    data: dict[str, Any] = {
        "key": "bank-vyas-statement",
        "family": DocumentFamily.BANK_STATEMENT,
        "label": "Vyas Statement",
        **overrides,
    }
    return services.create_template(actor=actor, data=data)


def make_active_template(actor: Any, **overrides: Any) -> Any:
    """A catalogue row the picker would offer."""
    template = make_template(actor, **overrides)
    return services.change_template_status(
        actor=actor,
        template=template,
        status=LifecycleStatus.ACTIVE,
    )
