"""Shared setup helpers for the document_history test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``, so a fixture goes through the same validation and
audit path a real record does. Document fixtures are reused from
``documents.tests.factories`` rather than reimplemented — duplicating them here
would let the two drift and would give this suite documents that never went
through ``documents``' own rules.
"""

from __future__ import annotations

from typing import Any

from documents.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    STRONG_PW,
    bank_statement_content,
    make_admin,
    make_applicant,
    make_bank_statement,
    make_document,
    make_lead_manager,
    make_superadmin,
    make_user,
    token_for,
)

from document_history import services


def render_context(**overrides: Any) -> dict[str, Any]:
    """A realistic render context for the bank-statement fixture.

    The ``computed`` block holds exactly the values ``bank_statement_content``
    deliberately omits — the totals, the closing balance, and the amount in
    words. That split is the contract between the two apps, so the fixture
    models it rather than filling ``computed`` with arbitrary keys.
    """
    return {
        "template_version": "2026.03",
        "locale": "en",
        "computed": {
            "statement_debit_total": 120000,
            "statement_credit_total": 500000,
            "statement_closing_balance": 630000,
            "amount_in_words": "Six Hundred Thirty Thousand Only",
        },
        "signatories": [
            {"id": "9f8e7d6c-5b4a-4392-8172-6f5e4d3c2b1a", "role": "director", "name": "Sunita Shrestha"},
        ],
        **overrides,
    }


def make_snapshot(actor: Any, document: Any, **overrides: Any) -> Any:
    """One captured snapshot of a document."""
    return services.create_snapshot(
        actor=actor,
        document=document,
        render_context=overrides.pop("render_context", render_context()),
        capture_note=overrides.pop("capture_note", "Printed for the visa file."),
        **overrides,
    )
