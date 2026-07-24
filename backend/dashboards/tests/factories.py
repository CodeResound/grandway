"""Shared setup helpers for the dashboards test suite.

This module builds records in **seven** other apps, which is unusual for a
fixture file and is unavoidable here: the app under test owns no table, so there
is nothing to set up except the world it summarizes. A dashboard test with no
leads, applicants, journeys, offers, checklists, documents, and files is a test
that every section correctly returns zero.

Every record goes through the owning app's own service rather than
``Model.objects.create``, and the chain helpers are re-exported from
``checklists.tests.factories`` rather than reimplemented — that suite already
assembles applicant → journey → catalogue → checklist → file, which is most of
what is needed here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from checklists import services as checklist_services
from checklists.constants import ChecklistStatus, ItemStatus
from checklists.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    STRONG_PW,
    add_requirement,
    make_admin,
    make_applicant,
    make_catalogue,
    make_country_template,
    make_journey,
    make_lead_manager,
    make_manual_offer,
    make_superadmin,
    make_template,
    make_user,
    pdf_upload,
    set_journey_country,
    token_for,
    upload_for_applicant,
)
from django.utils import timezone
from leads import services as lead_services
from leads.models import LeadSource
from offers import services as offer_services
from offers.constants import OfferStatus

# ---------------------------------------------------------------------------
# Leads — the only owner-scoped rows, and therefore the ones the scoping tests
# turn on.
# ---------------------------------------------------------------------------


def make_source(code: str = "walk_in") -> LeadSource:
    return LeadSource.objects.create(code=code, name_np="वाक-इन", name_en="Walk-in")


def make_lead(owner: Any, source: LeadSource, *, name_np: str = "राम श्रेष्ठ", **overrides: Any) -> Any:
    return lead_services.create_lead(
        actor=owner,
        data={"full_name_np": name_np, "source": source, **overrides},
        contact_numbers=[{"number": "9800000000", "label": "mobile", "is_primary": True}],
    )


def age_lead(lead: Any, *, days: int) -> Any:
    """Backdate a lead's last contact so it counts as stale.

    Writes the column directly rather than through the service, deliberately:
    there is no endpoint for "this happened a fortnight ago", and the staleness
    rule is what the test is about, not how the timestamp got there.
    """
    stamp = timezone.now() - timedelta(days=days)
    type(lead).objects.filter(pk=lead.pk).update(created_at=stamp, last_followed_up_at=None)
    lead.refresh_from_db()
    return lead


# ---------------------------------------------------------------------------
# Checklists — the largest contributor to Today's work and Blockers.
# ---------------------------------------------------------------------------


def make_live_checklist(actor: Any, journey: Any, country: Any) -> Any:
    """An active checklist for this journey, from the country's template.

    Instantiated **explicitly** rather than by setting the journey's country and
    letting inheritance fire. The receiver defers to ``transaction.on_commit``,
    which a ``TestCase`` never reaches, so relying on it here would mean wrapping
    every fixture in ``captureOnCommitCallbacks`` to test something this suite is
    not about. Inheritance has its own tests in ``checklists/tests/test_signals.py``;
    what these tests need is a checklist that exists.

    Activated rather than left in draft because most of the dashboard's item
    queries are scoped to live checklists, and a suite whose fixtures were all
    drafts would still pass while testing very little.
    """
    template = make_country_template(actor, country)
    set_journey_country(actor, journey, country)
    checklist = checklist_services.instantiate_checklist(actor=actor, journey=journey, template=template)
    if checklist.status == ChecklistStatus.DRAFT:
        checklist = checklist_services.activate_checklist(actor=actor, checklist=checklist)
    return checklist


def set_item_due(item: Any, *, days_from_now: int) -> Any:
    """Move an item's due date. Negative days puts it in the past."""
    due = timezone.now() + timedelta(days=days_from_now)
    type(item).objects.filter(pk=item.pk).update(due_at=due)
    item.refresh_from_db()
    return item


def block_item(actor: Any, item: Any, note: str = "Waiting on the embassy.") -> Any:
    """Declare an item stuck — the status Blockers is built around."""
    return checklist_services.set_item_status(
        actor=actor,
        item=item,
        status=ItemStatus.BLOCKED,
        status_note=note,
    )


# ---------------------------------------------------------------------------
# Offers — the response-deadline worklist.
# ---------------------------------------------------------------------------


def make_issued_offer(actor: Any, journey: Any, *, deadline_days: int, **overrides: Any) -> Any:
    """An issued offer whose response deadline is ``deadline_days`` from today.

    Negative puts the deadline in the past, which is the only way to produce an
    overdue offer — ``Offer.is_response_overdue`` compares against today in
    Nepal and there is no way to fake "now".
    """
    from core.nepal.calendar import nepal_today

    offer = make_manual_offer(
        actor,
        journey,
        response_deadline=nepal_today() + timedelta(days=deadline_days),
        **overrides,
    )
    return offer_services.issue_offer(actor=actor, offer=offer)


def decide_offer(actor: Any, offer: Any, outcome: str = OfferStatus.ACCEPTED, **kwargs: Any) -> Any:
    return offer_services.record_decision(actor=actor, offer=offer, outcome=outcome, **kwargs)
