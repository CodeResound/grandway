"""Composition logic for the dashboards app — the only module that assembles sections.

**Nothing here queries another app's tables.** Every figure comes from a summary
selector living in the app that owns the rows, and this module's whole job is to
call those and arrange the results. That is not ceremony: a dashboard that wrote
its own `Checklist.objects.filter(...)` would encode another app's definition of
"overdue" in a second place, and the two would drift the first time that app
changed its mind. §4 forbids the coupling; this file is what obeying it looks
like.

Three rules run through every section:

* **Scoping is inherited, never re-implemented.** Lead figures come through
  `leads.selectors`, which narrows to the actor; file figures come through
  `uploaded_files.selectors`, which applies that app's visibility rule. This
  module passes the actor down and trusts the owning app, because the owning app
  is where the rule is tested.
* **Every count is paired with the ids needed to act on it.** A number a user
  cannot click is the thing `concepts/dashboards.txt` explicitly asks this app
  not to build.
* **Worklists are previews, not list views.** Sections return the first
  `WORKLIST_PREVIEW_LIMIT` rows plus a total, and the total is what the client
  shows; the full list lives in the owning app's endpoint. The dashboard exists
  to get someone *to* the list, not to become a second one.
"""

from __future__ import annotations

from typing import Any

from applicant_journeys import selectors as journey_selectors
from applicants import selectors as applicant_selectors
from audit.selectors import get_events
from checklists import selectors as checklist_selectors
from documents import selectors as document_selectors
from leads import selectors as lead_selectors
from offers import selectors as offer_selectors
from uploaded_files import selectors as file_selectors

from dashboards.access import is_admin
from dashboards.constants import (
    DEFAULT_DUE_WITHIN_DAYS,
    DEFAULT_PASSPORT_HORIZON_DAYS,
    DEFAULT_STALE_LEAD_DAYS,
    WORKLIST_PREVIEW_LIMIT,
)

#: The filter keys that describe *when*. Passed to nearly every summary selector.
_WINDOW_KEYS: tuple[str, ...] = ("date_from", "date_to", "fiscal_year")


def _window(filters: dict[str, Any]) -> dict[str, Any]:
    """Just the date controls, as selector keyword arguments."""
    return {key: filters[key] for key in _WINDOW_KEYS if key in filters}


def _country(filters: dict[str, Any]) -> str | None:
    """The destination filter as a plain id, or None."""
    country = filters.get("country")
    return str(country) if country else None


def _preview(queryset: Any, serializer_class: Any, limit: int = WORKLIST_PREVIEW_LIMIT) -> dict[str, Any]:
    """A worklist section: the total, and the first few rows.

    The count runs against the full queryset and the slice against the same one,
    so the total a user sees is always the real backlog rather than the length
    of the preview. `has_more` saves a client from inferring it by comparing
    two numbers.
    """
    total = queryset.count()
    rows = serializer_class(queryset[:limit], many=True).data
    return {"total": total, "has_more": total > len(rows), "items": rows}


def _rate(numerator: int, denominator: int) -> float | None:
    """A conversion rate as a percentage, or None when there is nothing to divide.

    `None` rather than `0.0` on an empty denominator, deliberately: "no leads
    arrived this month" and "leads arrived and none converted" are different
    facts, and a zero would present the first as the second.
    """
    if not denominator:
        return None
    return round(numerator * 100 / denominator, 1)


# ---------------------------------------------------------------------------
# 1. Summary — the alert strip
# ---------------------------------------------------------------------------


def get_summary(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """The top-line counts, each one a link to somewhere.

    Every entry here is duplicated in a fuller section below. That is the point:
    this is the strip a user reads first, and it exists to say *how much* and
    *where to go*, never to be the only place a number appears.
    """
    admin = is_admin(actor)
    window = _window(filters)
    country_id = _country(filters)
    due_within_days = filters.get("due_within_days", DEFAULT_DUE_WITHIN_DAYS)

    overdue_items = checklist_selectors.get_overdue_checklist_items(country_id=country_id)
    due_soon_items = checklist_selectors.get_due_soon_checklist_items(
        due_within_days=due_within_days, country_id=country_id
    )
    blocked_items = checklist_selectors.get_blocked_checklist_items(country_id=country_id)
    offers_awaiting = offer_selectors.get_offers_awaiting_response(
        due_within_days=due_within_days, country_id=country_id
    )
    files_pending = file_selectors.get_files_awaiting_verification(is_admin=admin, country_id=country_id)
    rejected_files = file_selectors.get_rejected_files(is_admin=admin, country_id=country_id)
    stale_leads = lead_selectors.get_stale_leads(actor=actor, stale_after_days=DEFAULT_STALE_LEAD_DAYS, **window)
    unserved_journeys = checklist_selectors.get_journeys_missing_checklist()
    if country_id:
        unserved_journeys = unserved_journeys.filter(target_country_ref_id=country_id)

    lead_counts = lead_selectors.get_lead_funnel_counts(actor=actor, **window)
    applicant_counts = applicant_selectors.get_applicant_status_counts(country_id=country_id, **window)
    journey_counts = journey_selectors.get_journey_stage_counts(country_id=country_id, **window)

    return {
        "alerts": {
            "overdue_checklist_items": overdue_items.count(),
            "due_soon_checklist_items": due_soon_items.count(),
            "blocked_checklist_items": blocked_items.count(),
            "offers_awaiting_response": offers_awaiting.count(),
            "files_awaiting_verification": files_pending.count(),
            "rejected_files": rejected_files.count(),
            "stale_leads": stale_leads.count(),
            "journeys_without_a_checklist": unserved_journeys.count(),
        },
        "volumes": {
            "leads_total": sum(lead_counts.values()),
            "applicants_active": applicant_counts.get("active", 0),
            "journeys_total": sum(journey_counts.values()),
        },
        "due_within_days": due_within_days,
    }


# ---------------------------------------------------------------------------
# 2. Today's work
# ---------------------------------------------------------------------------


def get_today(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """What needs attention now — the most useful section in the app.

    Overdue and due-soon are returned as **separate** lists rather than one
    sorted stream. They call for different actions: an overdue item is a
    failure to chase, a due-soon item is a plan to make, and merging them
    would bury the first few rows of the first list under the volume of the
    second.
    """
    from dashboards.serializers import (
        ChecklistItemRowSerializer,
        DocumentRowSerializer,
        FileRowSerializer,
        LeadRowSerializer,
        OfferRowSerializer,
    )

    admin = is_admin(actor)
    window = _window(filters)
    country_id = _country(filters)
    owner_id = str(filters["owner"]) if filters.get("owner") else None
    due_within_days = filters.get("due_within_days", DEFAULT_DUE_WITHIN_DAYS)

    return {
        "due_within_days": due_within_days,
        "overdue_checklist_items": _preview(
            checklist_selectors.get_overdue_checklist_items(country_id=country_id, assignee_id=owner_id),
            ChecklistItemRowSerializer,
        ),
        "due_soon_checklist_items": _preview(
            checklist_selectors.get_due_soon_checklist_items(
                due_within_days=due_within_days, country_id=country_id, assignee_id=owner_id
            ),
            ChecklistItemRowSerializer,
        ),
        "offers_awaiting_response": _preview(
            offer_selectors.get_offers_awaiting_response(
                due_within_days=due_within_days,
                country_id=country_id,
                institution_id=str(filters["institution"]) if filters.get("institution") else None,
            ),
            OfferRowSerializer,
        ),
        "files_awaiting_verification": _preview(
            file_selectors.get_files_awaiting_verification(is_admin=admin, country_id=country_id),
            FileRowSerializer,
        ),
        "documents_in_progress": _preview(
            document_selectors.get_documents_in_progress(**window),
            DocumentRowSerializer,
        ),
        "stale_leads": _preview(
            lead_selectors.get_stale_leads(actor=actor, stale_after_days=DEFAULT_STALE_LEAD_DAYS, **window),
            LeadRowSerializer,
        ),
    }


# ---------------------------------------------------------------------------
# 3. Pipeline health
# ---------------------------------------------------------------------------


def get_pipeline(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Stage and status counts across the whole business.

    Every bucket is zero-filled by the owning selector, so an empty stage
    appears as empty rather than vanishing — a funnel that hides its dead ends
    is a funnel that cannot show you one.
    """
    admin = is_admin(actor)
    window = _window(filters)
    country_id = _country(filters)

    return {
        "leads_by_stage": lead_selectors.get_lead_funnel_counts(actor=actor, **window),
        "applicants_by_status": applicant_selectors.get_applicant_status_counts(country_id=country_id, **window),
        "journeys_by_stage": journey_selectors.get_journey_stage_counts(country_id=country_id, **window),
        "offers_by_status": offer_selectors.get_offer_status_counts(
            country_id=country_id,
            institution_id=str(filters["institution"]) if filters.get("institution") else None,
            **window,
        ),
        "checklists_by_status": checklist_selectors.get_checklist_status_counts(country_id=country_id, **window),
        # No country filter: a document belongs to a person, not to a study
        # plan, so it has no destination to narrow by. Stated rather than
        # silently ignored — see ``documents.selectors.get_document_status_counts``.
        "documents_by_status": document_selectors.get_document_status_counts(**window),
        "documents_by_status_is_country_filtered": False,
        "files_by_verification": file_selectors.get_file_verification_counts(
            is_admin=admin, country_id=country_id, **window
        ),
    }


# ---------------------------------------------------------------------------
# 4. Blockers and risk
# ---------------------------------------------------------------------------


def get_blockers(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Risk surfaced before it becomes a missed outcome.

    Grouped by cause rather than merged into one ranked list. "Blocked on
    something outside our control", "nobody authored this country's
    requirements", and "this passport expires before the visa can be lodged"
    are three different problems needing three different people to act, and a
    single list sorted by urgency would obscure which is which.
    """
    from dashboards.serializers import (
        ChecklistItemRowSerializer,
        FileRowSerializer,
        JourneyRowSerializer,
        OfferRowSerializer,
        PassportRowSerializer,
    )

    admin = is_admin(actor)
    country_id = _country(filters)
    owner_id = str(filters["owner"]) if filters.get("owner") else None
    passport_within_days = filters.get("passport_within_days", DEFAULT_PASSPORT_HORIZON_DAYS)

    unserved_journeys = checklist_selectors.get_journeys_missing_checklist()
    if country_id:
        unserved_journeys = unserved_journeys.filter(target_country_ref_id=country_id)

    return {
        "blocked_checklist_items": _preview(
            checklist_selectors.get_blocked_checklist_items(country_id=country_id, assignee_id=owner_id),
            ChecklistItemRowSerializer,
        ),
        # The safety net behind automatic checklist inheritance: a country whose
        # requirements nobody has authored produces no checklist and no error,
        # and this is the only place that silence becomes visible.
        "journeys_without_a_checklist": _preview(unserved_journeys, JourneyRowSerializer),
        "expiring_passports": _preview(
            applicant_selectors.get_expiring_passports(within_days=passport_within_days, country_id=country_id),
            PassportRowSerializer,
        ),
        "overdue_offers": _preview(
            # Zero-day horizon: only deadlines already past, not the approaching
            # ones. The approaching ones belong in Today's work, where they can
            # still be acted on in time.
            offer_selectors.get_offers_awaiting_response(due_within_days=0, country_id=country_id),
            OfferRowSerializer,
        ),
        "rejected_files": _preview(
            file_selectors.get_rejected_files(is_admin=admin, country_id=country_id),
            FileRowSerializer,
        ),
        "passport_within_days": passport_within_days,
    }


# ---------------------------------------------------------------------------
# 5. Workload by owner
# ---------------------------------------------------------------------------


def get_workload(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """How work is distributed across the team.

    **A Lead Manager sees one row in `leads` — their own.** That is the owner
    scoping working, not a degraded view: this section answers "how is work
    distributed", and a Lead Manager's honest answer is "here is mine". Only an
    Admin sees a distribution to rebalance, and `is_scoped_to_caller` says which
    of the two the response is so a client can label it truthfully.

    The three sources are returned separately rather than joined into one row
    per person, because they measure different things: an open lead is a
    prospect being worked, an overdue checklist item is a task already late, and
    an offer awaiting response is someone else's decision to chase. Summing them
    would produce a number with no meaning.
    """
    window = _window(filters)
    country_id = _country(filters)

    return {
        "is_scoped_to_caller": not is_admin(actor),
        "leads": lead_selectors.get_lead_workload_by_owner(actor=actor, **window),
        "checklist_items": checklist_selectors.get_checklist_workload_by_assignee(country_id=country_id),
        "offers": offer_selectors.get_offer_workload_by_owner(country_id=country_id, **window),
    }


# ---------------------------------------------------------------------------
# 6. Source and conversion
# ---------------------------------------------------------------------------


def get_conversion(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Whether intake is producing outcomes.

    The four rates are **not** a single funnel and must not be multiplied
    together. Each is windowed on its own stage's dates, so a lead that arrived
    in Ashadh and converted in Shrawan counts toward Ashadh's intake and
    Shrawan's conversions. Reading them as one cohort walking through four
    gates would be wrong, and a client presenting them as a funnel chart would
    be reporting something the data does not say.

    Every rate is `null` rather than `0` when its denominator is empty — "nobody
    arrived" and "people arrived and none converted" are different facts.
    """
    window = _window(filters)
    country_id = _country(filters)

    lead_counts = lead_selectors.get_lead_funnel_counts(actor=actor, **window)
    leads_total = sum(lead_counts.values())
    leads_converted = lead_counts.get("converted", 0)

    applicant_counts = applicant_selectors.get_applicant_status_counts(country_id=country_id, **window)
    applicants_total = sum(applicant_counts.values())
    applicants_with_journey = journey_selectors.count_applicants_with_a_journey(country_id=country_id, **window)

    journeys_total = journey_selectors.count_journeys(country_id=country_id, **window)
    journeys_with_offer = offer_selectors.count_journeys_with_an_offer(country_id=country_id, **window)

    decisions = offer_selectors.get_decision_counts(country_id=country_id, **window)
    decided_total = sum(decisions.values())
    accepted = decisions.get("accepted", 0)

    return {
        "by_source": lead_selectors.get_lead_source_conversion(actor=actor, **window),
        "rates": {
            "lead_to_applicant": {
                "numerator": leads_converted,
                "denominator": leads_total,
                "percent": _rate(leads_converted, leads_total),
            },
            "applicant_to_journey": {
                "numerator": applicants_with_journey,
                "denominator": applicants_total,
                "percent": _rate(applicants_with_journey, applicants_total),
            },
            "journey_to_offer": {
                "numerator": journeys_with_offer,
                "denominator": journeys_total,
                "percent": _rate(journeys_with_offer, journeys_total),
            },
            "offer_acceptance": {
                "numerator": accepted,
                "denominator": decided_total,
                "percent": _rate(accepted, decided_total),
            },
        },
    }


# ---------------------------------------------------------------------------
# 7. Final outcomes
# ---------------------------------------------------------------------------


def get_outcomes(*, actor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """How work ended, over the window.

    Windowed on **when each thing ended**, not when it started — a journey
    opened last year and closed this month belongs in this month's outcomes.
    That is why this section and `get_pipeline` can legitimately disagree about
    the same journey.
    """
    window = _window(filters)
    country_id = _country(filters)

    journey_stages = journey_selectors.get_journey_stage_counts(country_id=country_id, **window)
    applicant_statuses = applicant_selectors.get_applicant_status_counts(country_id=country_id, **window)
    checklist_statuses = checklist_selectors.get_checklist_status_counts(country_id=country_id, **window)

    return {
        "journey_outcomes": journey_selectors.get_journey_outcome_counts(country_id=country_id, **window),
        "offer_decisions": offer_selectors.get_decision_counts(country_id=country_id, **window),
        "journeys_completed": journey_stages.get("completed", 0),
        "journeys_closed": journey_stages.get("closed", 0),
        "applicants_archived": applicant_statuses.get("archived", 0),
        "applicants_dormant": applicant_statuses.get("dormant", 0),
        "checklists_completed": checklist_statuses.get("completed", 0),
        "checklists_archived": checklist_statuses.get("archived", 0),
    }


# ---------------------------------------------------------------------------
# 8. Recent activity
# ---------------------------------------------------------------------------


def get_activity(*, actor: Any, filters: dict[str, Any]) -> Any:
    """The recent-activity feed, as a queryset for the view to paginate.

    Read from the central `audit` log rather than any table this app owns — the
    change feed *is* the audit trail. Returned unpaginated so the view applies
    the shared paginator; every other section returns an assembled dict, and
    this one is the single exception because it is genuinely a list.

    **Not narrowed by actor.** The audit log is not owner-scoped anywhere in the
    project, and inventing scoping here would make this endpoint disagree with
    `GET /api/v1/audit/events/`, which any of these users may already call.
    """
    return get_events({"fiscal_year": filters.get("fiscal_year")})
