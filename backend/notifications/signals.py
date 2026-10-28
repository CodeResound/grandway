"""Real-time lifecycle alerts (§11).

Five ``post_save`` receivers, one per source model, and one ``core.events``
receiver for the domain events leads, applicants, and documents raise
(2026-10-29). Together they are the half of this app that cannot wait for the
nightly sweep: work landing on somebody's desk, a file coming back rejected, a
journey reaching a new stage, a lead converted, a visit recorded.

**Why domain events for the newer alerts.** ``post_save`` cannot say who saved a
row, and "never tell someone about their own action" needs exactly that. The
source apps announce the event with the actor through ``core.events.emit`` — a
signal they own no listener of, so the dependency still runs one way.

**Why signals, and not calls from the source apps.** The dependency has to run
one way. ``notifications`` knows that checklists, files, journeys, and offers
exist; none of them may ever learn that this app does, or every one of them
acquires a reason to break when it changes — and, worse, a failure to *alert*
becomes a failure to *save the thing being alerted about*. §11's three tests are
all met for each receiver: the side effect is decoupled from the trigger, it does
not need the trigger's transaction, and exactly one place fires it.

**Why no change detection.** Not one receiver here compares an old field value to
a new one, and no ``pre_save`` receiver stashes state on an instance. The dedupe
key carries the value that changed — a journey's stage, an item's assignee — so
a save that changed nothing produces a key that already exists and writes
nothing. The database is the change detector, and it is one that cannot be
defeated by an update path that bypassed the ORM's ``save()``.

**Why ``on_commit``.** An alert is written only once the thing it describes is
really in the database. A save that rolls back leaves no alert behind, and a
failure in here can never roll back the save that triggered it.

**Why every failure is swallowed.** These run after commit, outside any request
the client is still waiting on, and there is nothing useful to raise *to* — the
checklist is saved either way. What a failure must not do is stay invisible, so
it goes to the log **and** to the audit trail as an unsuccessful event. Same
contract ``checklists/signals.py`` established for country inheritance, for the
same reason.
"""

from __future__ import annotations

import logging
from typing import Any

from applicant_journeys.constants import TERMINAL_STAGES
from core.constants import NoteCategory
from core.events import domain_event
from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from offers.constants import TERMINAL_STATUSES as OFFER_TERMINAL_STATUSES
from uploaded_files.constants import VerificationStatus

from notifications import services
from notifications.constants import GenerationSource, NotificationType, SourceEntityType

logger = logging.getLogger(__name__)


def _signals_disabled() -> bool:
    """True when signal side effects are switched off for this process.

    Set ``DISABLE_SIGNALS = True`` for bulk imports that would otherwise produce
    an alert per imported row inside the import's own transaction. Rebuild the
    deadline alerts afterwards with::

        python manage.py sweep_notifications

    Note what that does **not** rebuild: lifecycle alerts for events that
    happened during the import. That is deliberate and not a gap — nobody needs
    to be told about a stage change that happened during a backfill three days
    ago (§11 — a signal that cannot be switched off cannot be imported around).
    """
    return bool(getattr(settings, "DISABLE_SIGNALS", False))


def _safely(what: str, work: Any) -> None:
    """Run one alert generator, absorbing and recording any failure.

    Every receiver's body goes through here so that no path from a source app's
    ``save()`` can raise. ``record_generation_failure`` logs and audits; nothing
    propagates.
    """
    try:
        work()
    except Exception as exc:  # noqa: BLE001 — see the module docstring: nothing may propagate from here.
        services.record_generation_failure(what, exc)


# ---------------------------------------------------------------------------
# Assignment — the alert with a genuinely targeted recipient
# ---------------------------------------------------------------------------


def _alert_assignment(model_label: str, entity_type: str, record_id: Any) -> None:
    """Tell an assignee that work has landed on their desk.

    Re-reads the record rather than trusting the instance handed to the receiver:
    by the time this runs the transaction has committed, and the row is the
    authority on what was actually saved.

    The alert goes to the assignee alone — never to the Admin fallback. An
    assignment with no assignee is not an assignment, and this receiver returns
    without writing anything if the field was cleared between the save and the
    commit.
    """
    from django.apps import apps

    model = apps.get_model(model_label)
    select = ("checklist", "checklist__journey", "checklist__journey__applicant", "assigned_to")
    if entity_type == SourceEntityType.CHECKLIST:
        select = ("journey", "journey__applicant", "assigned_to")

    record = model.objects.select_related(*select).filter(pk=record_id).first()
    if record is None or record.assigned_to_id is None:
        return

    spec = services.build_assignment_alert(record, entity_type=entity_type)
    services.dispatch(spec, [record.assigned_to], generated_by=GenerationSource.SIGNAL)


@receiver(post_save, sender="checklists.ChecklistItem", dispatch_uid="notifications_item_assigned")
def on_checklist_item_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Alert the assignee of a checklist item.

    ``dispatch_uid`` keeps a double import from connecting the receiver twice.
    The second call would create nothing — the dedupe key is the same — but the
    audit log would carry work nobody asked for.
    """
    if _signals_disabled() or not getattr(instance, "assigned_to_id", None):
        return
    record_id = instance.pk
    transaction.on_commit(
        lambda: _safely(
            "assignment_received",
            lambda: _alert_assignment("checklists.ChecklistItem", SourceEntityType.CHECKLIST_ITEM, record_id),
        )
    )


@receiver(post_save, sender="checklists.Checklist", dispatch_uid="notifications_checklist_assigned")
def on_checklist_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Alert the assignee of a whole checklist."""
    if _signals_disabled() or not getattr(instance, "assigned_to_id", None):
        return
    record_id = instance.pk
    transaction.on_commit(
        lambda: _safely(
            "assignment_received",
            lambda: _alert_assignment("checklists.Checklist", SourceEntityType.CHECKLIST, record_id),
        )
    )


# ---------------------------------------------------------------------------
# File rejection — the one alert that fans out to two audiences
# ---------------------------------------------------------------------------


def _alert_file_rejected(file_id: Any) -> None:
    """Tell the uploader, and every Admin, that a file came back rejected.

    Re-reads the row and re-checks the status: a file rejected and then verified
    inside the same transaction must not produce a rejection alert for a state it
    no longer holds.

    The reviewer is excluded as the actor, so the Admin who rejected the file
    does not receive an alert saying it was rejected.
    """
    from uploaded_files.models import UploadedFile

    uploaded_file = UploadedFile.objects.select_related("uploaded_by", "reviewed_by").filter(pk=file_id).first()
    if uploaded_file is None or uploaded_file.verification_status != VerificationStatus.REJECTED:
        return

    spec = services.build_file_rejected_alert(uploaded_file)
    recipients = services.recipients_for_file(uploaded_file, exclude_actor=uploaded_file.reviewed_by)
    services.dispatch(spec, recipients, generated_by=GenerationSource.SIGNAL)


@receiver(post_save, sender="uploaded_files.UploadedFile", dispatch_uid="notifications_file_rejected")
def on_file_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Alert on a file whose review came back rejected."""
    if _signals_disabled() or getattr(instance, "verification_status", None) != VerificationStatus.REJECTED:
        return
    file_id = instance.pk
    transaction.on_commit(lambda: _safely("file_rejected", lambda: _alert_file_rejected(file_id)))


# ---------------------------------------------------------------------------
# Journey lifecycle
# ---------------------------------------------------------------------------


def _alert_journey(journey_id: Any) -> None:
    """Tell the Admins — and the applicant's assignee, if any — that a journey moved, or ended.

    Journeys carry no owner of their own. Since 2026-10-29 an applicant may be
    assigned to someone, and that person is told too; an unassigned applicant's
    journey alerts still go to the Admins only (the product owner kept the
    existing alerts' routing rather than widening it to every Lead Manager).
    """
    from applicant_journeys.models import ApplicantJourney

    journey = (
        ApplicantJourney.objects.select_related("applicant__assigned_to", "target_country_ref")
        .filter(pk=journey_id)
        .first()
    )
    if journey is None:
        return

    spec = services.build_journey_alert(journey, closed=journey.stage in TERMINAL_STAGES)
    services.dispatch(spec, services.recipients_for_applicant(journey.applicant), generated_by=GenerationSource.SIGNAL)


@receiver(post_save, sender="applicant_journeys.ApplicantJourney", dispatch_uid="notifications_journey_stage")
def on_journey_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Alert on a journey's stage.

    Fires on every save, including the one that creates the journey — which is
    correct: a new journey entering ``planning`` is a lifecycle event an Admin
    wants to see. Every subsequent save at the same stage is absorbed by the
    dedupe key.
    """
    if _signals_disabled():
        return
    journey_id = instance.pk
    transaction.on_commit(lambda: _safely("journey_stage_changed", lambda: _alert_journey(journey_id)))


# ---------------------------------------------------------------------------
# Offer decisions
# ---------------------------------------------------------------------------


def _alert_offer_decided(offer_id: Any) -> None:
    """Tell the Admins that an issued offer reached a decision."""
    from offers.models import Offer

    offer = Offer.objects.select_related("journey", "journey__applicant").filter(pk=offer_id).first()
    if offer is None or offer.status not in OFFER_TERMINAL_STATUSES:
        return

    spec = services.build_offer_decided_alert(offer)
    services.dispatch(spec, services.recipients_for_admins(), generated_by=GenerationSource.SIGNAL)


@receiver(post_save, sender="offers.Offer", dispatch_uid="notifications_offer_decided")
def on_offer_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Alert on an offer reaching a terminal status.

    Scoped to terminal statuses rather than every save: ``draft`` and ``issued``
    are working states an offer passes through repeatedly while it is being
    prepared, and alerting on those would report the office's own drafting back
    to it.
    """
    if _signals_disabled() or getattr(instance, "status", None) not in OFFER_TERMINAL_STATUSES:
        return
    offer_id = instance.pk
    transaction.on_commit(lambda: _safely("offer_decided", lambda: _alert_offer_decided(offer_id)))


# ---------------------------------------------------------------------------
# Domain events (2026-10-29) — leads, applicants, documents
# ---------------------------------------------------------------------------
#
# Raised by the source apps' services through ``core.events.emit``, which
# already waits for the commit — so these handlers run directly, not via
# ``on_commit``. Each re-reads what it needs: the event carries ids, never
# instances, and the row is the authority on what was saved.

_LEAD_EVENT_TYPES = {
    "lead.created": NotificationType.LEAD_CREATED,
    "lead.converted": NotificationType.LEAD_CONVERTED,
    "lead.deleted": NotificationType.LEAD_DELETED,
    "lead.restored": NotificationType.LEAD_RESTORED,
}


def _load_lead(lead_id: Any) -> Any:
    from leads.models import Lead

    return Lead.objects.select_related("created_by").filter(pk=lead_id).first()


def _load_applicant(applicant_id: Any) -> Any:
    from applicants.models import Applicant

    return Applicant.objects.select_related("assigned_to", "originating_lead").filter(pk=applicant_id).first()


def _on_lead_event(event: str, event_id: Any, actor: Any, entity_id: Any, data: dict[str, Any]) -> None:
    """Created → the Admins. Converted, deleted, restored → the lead's owner and the Admins."""
    lead = _load_lead(entity_id)
    if lead is None:
        return
    notification_type = _LEAD_EVENT_TYPES[event]
    applicant = _load_applicant(data["applicant_id"]) if data.get("applicant_id") else None
    spec = services.build_lead_alert(
        lead, notification_type=notification_type, event_id=event_id, actor=actor, applicant=applicant
    )
    candidates = services.recipients_for_admins()
    if notification_type != NotificationType.LEAD_CREATED:
        candidates = [lead.created_by, *candidates]
    services.dispatch(
        spec, services.recipients_for_users(candidates, exclude_actor=actor), generated_by=GenerationSource.SIGNAL
    )


def _on_lead_note(event: str, event_id: Any, actor: Any, entity_id: Any, data: dict[str, Any]) -> None:
    """A visit note on a lead → the lead's owner. General notes raise nothing."""
    if data.get("category") != NoteCategory.VISIT:
        return
    lead = _load_lead(entity_id)
    if lead is None:
        return
    spec = services.build_visit_note_alert(
        owner_type=SourceEntityType.LEAD, owner=lead, note_id=data["note_id"], event_id=event_id, actor=actor
    )
    services.dispatch(
        spec,
        services.recipients_for_users([lead.created_by], exclude_actor=actor),
        generated_by=GenerationSource.SIGNAL,
    )


def _on_applicant_status(event: str, event_id: Any, actor: Any, entity_id: Any, data: dict[str, Any]) -> None:
    """Status change or restore → the assignee and the Admins; everyone when unassigned."""
    applicant = _load_applicant(entity_id)
    if applicant is None:
        return
    spec = services.build_applicant_status_alert(
        applicant,
        restored=event == "applicant.restored",
        from_status=data["from_status"],
        to_status=data["to_status"],
        event_id=event_id,
        actor=actor,
    )
    recipients = services.recipients_for_applicant(applicant, exclude_actor=actor, fallback_all=True)
    services.dispatch(spec, recipients, generated_by=GenerationSource.SIGNAL)


def _on_applicant_note(event: str, event_id: Any, actor: Any, entity_id: Any, data: dict[str, Any]) -> None:
    """A visit note → the assignee; everyone when unassigned. General notes raise nothing."""
    if data.get("category") != NoteCategory.VISIT:
        return
    applicant = _load_applicant(entity_id)
    if applicant is None:
        return
    spec = services.build_visit_note_alert(
        owner_type=SourceEntityType.APPLICANT,
        owner=applicant,
        note_id=data["note_id"],
        event_id=event_id,
        actor=actor,
    )
    recipients = services.recipients_for_applicant(
        applicant, exclude_actor=actor, include_admins=False, fallback_all=True
    )
    services.dispatch(spec, recipients, generated_by=GenerationSource.SIGNAL)


def _on_applicant_assigned(event: str, event_id: Any, actor: Any, entity_id: Any, data: dict[str, Any]) -> None:
    """Tell the new assignee they have it, and the previous one they no longer do."""
    from authenticate.selectors import get_active_user_by_id

    applicant = _load_applicant(entity_id)
    if applicant is None:
        return
    for user_id, assigned in ((data.get("assignee_id"), True), (data.get("previous_assignee_id"), False)):
        user = get_active_user_by_id(str(user_id)) if user_id else None
        if user is None:
            continue
        spec = services.build_applicant_assignment_alert(
            applicant, assigned=assigned, recipient=user, event_id=event_id, actor=actor
        )
        services.dispatch(
            spec, services.recipients_for_users([user], exclude_actor=actor), generated_by=GenerationSource.SIGNAL
        )


def _on_document_ready(event: str, event_id: Any, actor: Any, entity_id: Any, data: dict[str, Any]) -> None:
    """A document marked ready → the other Admins. Documents are Admin-only, so never a Lead Manager."""
    from documents.models import Document

    document = Document.objects.select_related("applicant__assigned_to").filter(pk=entity_id).first()
    if document is None:
        return
    spec = services.build_document_ready_alert(document, event_id=event_id, actor=actor)
    services.dispatch(spec, services.recipients_for_admins(exclude_actor=actor), generated_by=GenerationSource.SIGNAL)


_EVENT_HANDLERS = {
    **dict.fromkeys(_LEAD_EVENT_TYPES, _on_lead_event),
    "lead.note_added": _on_lead_note,
    "applicant.status_changed": _on_applicant_status,
    "applicant.restored": _on_applicant_status,
    "applicant.note_added": _on_applicant_note,
    "applicant.assigned": _on_applicant_assigned,
    "document.ready": _on_document_ready,
}


@receiver(domain_event, dispatch_uid="notifications_domain_event")
def on_domain_event(
    sender: Any,
    *,
    event: str,
    event_id: Any,
    actor: Any,
    entity_type: str,
    entity_id: Any,
    data: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Turn one domain event into its alerts. Unknown events are ignored, failures recorded."""
    handler = _EVENT_HANDLERS.get(event)
    if handler is None or _signals_disabled():
        return
    _safely(event, lambda: handler(event, event_id, actor, entity_id, data))
