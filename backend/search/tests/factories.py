"""Shared setup helpers for the search test suite.

Like ``dashboards/tests/factories.py``, this module builds records in other
apps, which is unavoidable: the app under test owns no table, so there is
nothing to set up except the world it searches. A search test with no
applicants, leads, clients, documents, files, institutions, programs, templates,
and signatories is a test that every bucket correctly returns zero.

Every record goes through the owning app's own service rather than
``Model.objects.create``, and the actor/applicant/journey/catalogue helpers are
re-exported from ``checklists.tests.factories`` rather than reimplemented — the
same chain ``dashboards`` reuses, for the same reason.

**One fixture builds one world with one shared token in every name.** The tests
turn on which buckets a single query reaches, so a helper that seeds nine types
with a common token is what most of them need; ``seed_world`` is that helper.
"""

from __future__ import annotations

from typing import Any

from checklists.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    STRONG_PW,
    make_admin,
    make_applicant,
    make_catalogue,
    make_journey,
    make_lead_manager,
    make_superadmin,
    make_user,
    pdf_upload,
    token_for,
    upload_for_applicant,
)
from clients import services as client_services
from document_templates import services as template_services
from documents import services as document_services
from institutions import services as catalogue_services
from leads import services as lead_services
from leads.models import LeadSource

#: The token every seeded record carries somewhere in a searchable field, so one
#: query can be asserted against every bucket at once. Deliberately not a real
#: word: a substring search for something like "test" would also match fixture
#: text this suite did not intend to hit.
TOKEN = "Zaraki"


# ---------------------------------------------------------------------------
# Leads — the only owner-scoped type, and therefore the one the scoping tests
# turn on.
# ---------------------------------------------------------------------------


def make_source(code: str = "walk_in") -> LeadSource:
    """The shared intake channel.

    ``get_or_create`` rather than ``create``: ``code`` is unique, and a suite
    that seeds two leads without caring where they came from would otherwise
    fail on the second one for a reason that has nothing to do with search.
    """
    source, _ = LeadSource.objects.get_or_create(code=code, defaults={"name": "Walk-in"})
    return source


def make_lead(
    owner: Any,
    source: LeadSource | None = None,
    *,
    name: str = "Ram Shrestha",
    number: str = "9800000000",
    **overrides: Any,
) -> Any:
    return lead_services.create_lead(
        actor=owner,
        data={"full_name": name, "source": source or make_source(), **overrides},
        contact_numbers=[{"number": number, "label": "mobile", "is_primary": True}],
    )


# ---------------------------------------------------------------------------
# The remaining searchable types
# ---------------------------------------------------------------------------


def make_client(actor: Any, *, name: str = "Himal Education", **overrides: Any) -> Any:
    return client_services.create_client(actor=actor, data={"name": name, **overrides})


def make_document(actor: Any, applicant: Any = None, **overrides: Any) -> Any:
    data: dict[str, Any] = {
        "family": "student",
        "template_key": "student-certificate",
        "label": "Certificate",
        **overrides,
    }
    return document_services.create_document(actor=actor, applicant=applicant, data=data)


def make_signatory(actor: Any, *, name: str = "Sunita Rai", **overrides: Any) -> Any:
    data: dict[str, Any] = {
        "name": name,
        "title": "Director",
        "role": "director",
        "signature_image_url": "https://files.example/signatures/s.png",
        **overrides,
    }
    return template_services.create_signatory(actor=actor, data=data)


def make_doc_template(actor: Any, *, label: str = "Vyas Statement", **overrides: Any) -> Any:
    data: dict[str, Any] = {
        "key": "bank-vyas-statement",
        "family": "bank_statement",
        "label": label,
        **overrides,
    }
    return template_services.create_template(actor=actor, data=data)


def make_institution(actor: Any, country: Any, *, name: str = "Zaraki University", **overrides: Any) -> Any:
    return catalogue_services.create_institution(
        actor=actor,
        data={"country": country, "name": name, **overrides},
    )


# ---------------------------------------------------------------------------
# The whole world, in one call
# ---------------------------------------------------------------------------


def seed_world(admin: Any, manager: Any) -> dict[str, Any]:
    """One record of every searchable type, each carrying ``TOKEN``.

    The lead is created **by the manager** and the applicant, documents, files
    and catalogue rows by the admin, which is what makes the owner-scoping
    assertions meaningful: an Admin searching ``TOKEN`` should reach all nine
    types, and a second manager should reach eight — everything except another
    manager's lead.

    Returns the records by type key so a test can assert against ids rather than
    against positions in a list.
    """
    catalogue = make_catalogue(admin)
    country = catalogue["country"]

    applicant = make_applicant(admin, name=f"{TOKEN} Thapa")
    lead = make_lead(manager, name=f"{TOKEN} Gurung")
    client = make_client(admin, name=f"{TOKEN} Consultancy")
    document = make_document(admin, applicant, label=f"{TOKEN} Certificate")
    uploaded_file = upload_for_applicant(admin, applicant, upload=pdf_upload(f"{TOKEN}-passport.pdf"))
    institution = make_institution(admin, country, name=f"{TOKEN} University")
    program = catalogue_services.create_program(
        actor=admin,
        data={
            "institution": institution,
            "campus": None,
            "field": catalogue["field"],
            "title": f"Master of {TOKEN} Studies",
            "qualification_level": "masters",
            "intake_pattern": "Feb / Jul",
        },
    )
    doc_template = make_doc_template(admin, label=f"{TOKEN} Statement")
    signatory = make_signatory(admin, name=f"{TOKEN} Rai")

    return {
        "applicant": applicant,
        "lead": lead,
        "client": client,
        "document": document,
        "uploaded_file": uploaded_file,
        "institution": institution,
        "program": program,
        "document_template": doc_template,
        "signatory": signatory,
        "catalogue": catalogue,
    }
