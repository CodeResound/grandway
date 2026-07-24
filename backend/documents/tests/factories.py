"""Shared setup helpers for the documents test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``, so a fixture goes through the same validation and
audit path a real record does.
"""

from __future__ import annotations

from typing import Any

from applicants import services as applicant_services
from authenticate import services as auth_services
from authenticate.constants import AuthorityType

from documents import services

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


def make_applicant(actor: Any, *, name: str = "Ram Bahadur", **overrides: Any) -> Any:
    return applicant_services.create_applicant(
        actor=actor,
        data={"full_name": name, **overrides},
        contact_numbers=[{"number": "9800000000", "label": "mobile", "is_primary": True}],
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def make_document(actor: Any, applicant: Any = None, **overrides: Any) -> Any:
    """A document, applicant-owned by default.

    Pass ``applicant=None`` together with ``standalone_purpose`` for a
    standalone record.
    """
    data: dict[str, Any] = {
        "family": "student",
        "template_key": "student-certificate",
        "label": "Certificate",
        **overrides,
    }
    return services.create_document(actor=actor, applicant=applicant, data=data)


def make_bank_statement(actor: Any, applicant: Any = None, **overrides: Any) -> Any:
    """A bank statement carrying a realistic transaction array."""
    data: dict[str, Any] = {
        "family": "bank_statement",
        "template_key": "bank-vyas-statement",
        "label": "Vyas Statement",
        "content": bank_statement_content(),
        **overrides,
    }
    return services.create_document(actor=actor, applicant=applicant, data=data)


def bank_statement_content() -> dict[str, Any]:
    """Input fields only — no derived values.

    Mirrors ``BankStatementContent`` from the frontend data contract. The
    running ``balance`` per row, the debit/credit totals, the closing balance,
    and the auto interest/tax rows are all absent by design: the frontend
    computes them at render time and the backend must never add them.
    """
    return {
        "statement_account_holder": "Ram Bahadur",
        "statement_account_no": "0123456789012",
        "statement_account_type": "Savings",
        "statement_opening_balance": 250000,
        "statement_interest": "5.5",
        "statement_tax": "5",
        "transactions": [
            {"date": "2026-04-01", "description": "Deposit", "credit": 500000},
            {"date": "2026-05-12", "description": "Withdrawal", "debit": 120000},
        ],
        "statement_spokesperson": "Sunita Shrestha",
    }
