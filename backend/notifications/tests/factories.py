"""Shared setup helpers for the notifications test suite.

Every source record is built through the owning app's own service, never
``Model.objects.create``, so a fixture goes through the same validation, audit,
and **signal** path a real record does. That last one matters more here than in
any other suite: half of this app is signal receivers, and a fixture that
bypassed ``save()`` would let a receiver pass its tests without ever having been
connected.

The actor and source-record helpers are re-exported from
``checklists.tests.factories`` rather than reimplemented — that suite already
builds the applicant → journey → catalogue → template → checklist chain this one
needs, and a second copy would drift on the setup every test here depends on.

**Nothing here creates a ``Notification`` directly.** A fixture that inserted
rows would test the serializer against data no generator could produce. Alerts in
these tests come from ``services.dispatch``, from a signal, or from the sweep —
the three paths that exist in production.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from checklists import services as checklist_services
from checklists.constants import ItemType
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
    set_journey_country,
    token_for,
    upload_for_applicant,
)
from django.utils import timezone
from reminders.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    make_client,
    make_reminder,
)

from notifications import services
from notifications.constants import NotificationType, SourceEntityType


def make_checklist(actor: Any, journey: Any, *, title: str = "Australia — Student Visa", **overrides: Any) -> Any:
    """A blank checklist on a journey, activated so its items count as live.

    Activated because every deadline selector this app reads narrows to live
    checklists, and a suite whose fixtures were all drafts would be testing that
    guard rather than the feature.
    """
    checklist = checklist_services.create_blank_checklist(
        actor=actor,
        journey=journey,
        data={"title": title, **overrides},
    )
    return checklist_services.activate_checklist(actor=actor, checklist=checklist)


def add_item(
    actor: Any,
    checklist: Any,
    *,
    label: str = "Passport bio page scan",
    due_in_days: int | None = None,
    item_type: str = ItemType.DOCUMENT,
    **overrides: Any,
) -> Any:
    """One requirement on one applicant's checklist.

    ``due_in_days`` is relative and may be negative — an overdue item is the most
    common fixture in this suite, and expressing it as "three days ago" keeps the
    test readable and keeps it from breaking when the calendar moves.
    """
    data: dict[str, Any] = {"label": label, "item_type": item_type, **overrides}
    if due_in_days is not None:
        data["due_at"] = timezone.now() + timedelta(days=due_in_days)
    return checklist_services.add_checklist_item(actor=actor, checklist=checklist, data=data)


def complete_item(actor: Any, item: Any) -> Any:
    """Resolve a requirement — the act the sweep's auto-resolve pass reacts to."""
    from checklists.constants import ItemStatus

    return checklist_services.set_item_status(actor=actor, item=item, status=ItemStatus.COMPLETED)


def issued_offer(actor: Any, journey: Any, *, deadline_in_days: int, **overrides: Any) -> Any:
    """An offer that has been issued and is awaiting a response by a given day.

    Goes through ``issue_offer`` rather than setting the status, because only an
    ``issued`` offer is visible to ``get_offers_awaiting_response`` and because
    the transition itself fires a signal this suite asserts on.
    """
    from core.nepal.calendar import nepal_today
    from offers import services as offer_services

    offer = make_manual_offer(
        actor,
        journey,
        response_deadline=nepal_today() + timedelta(days=deadline_in_days),
        **overrides,
    )
    return offer_services.issue_offer(actor=actor, offer=offer)


def give_passport(actor: Any, applicant: Any, *, expires_in_days: int) -> Any:
    """Put a passport on an applicant with a chosen expiry.

    Goes through ``update_applicant`` so the upsert path and its validation run.
    Returns the ``PassportDetail`` row, which is what the alert points at.
    """
    from applicants import services as applicant_services
    from applicants.models import PassportDetail
    from core.nepal.calendar import nepal_today

    applicant_services.update_applicant(
        actor=actor,
        applicant=applicant,
        fields={},
        passport={
            "passport_number": "PA1234567",
            "expiry_date": nepal_today() + timedelta(days=expires_in_days),
        },
    )
    return PassportDetail.objects.get(applicant=applicant)


def raise_alert(
    recipient: Any,
    *,
    notification_type: str = NotificationType.CHECKLIST_ITEM_OVERDUE,
    dedupe_key: str = "test:checklist_item:fixed-key",
    title: str = "Overdue: Passport bio page scan",
    due_at: Any = None,
    generated_by: str = "sweep",
    **overrides: Any,
) -> Any:
    """One alert, raised through the production write path.

    Used by the endpoint tests, which need a notification to exist but do not
    care which generator produced it. Still goes through ``services.dispatch``,
    so the row is shaped exactly as a real one — including its delivery state,
    which a direct ``objects.create`` would leave at ``pending`` and quietly
    break the serializer assertions.
    """
    spec = services.AlertSpec(
        notification_type=notification_type,
        dedupe_key=dedupe_key,
        title=title,
        body=overrides.pop("body", "Required for Ram Bahadur."),
        source_app=overrides.pop("source_app", "checklists"),
        source_entity_type=overrides.pop("source_entity_type", SourceEntityType.CHECKLIST_ITEM),
        source_entity_id=overrides.pop("source_entity_id", None),
        source_api_path=overrides.pop("source_api_path", "/api/v1/checklists/x/items/y/"),
        due_at=due_at,
    )
    created = services.dispatch(spec, [recipient], generated_by=generated_by)
    return created[0] if created else None


def auth(client: Any, user: Any) -> None:
    """Put a real bearer token on the test client for this user."""
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")
