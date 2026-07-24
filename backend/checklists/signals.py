"""Automatic checklist inheritance (§11).

This is the module's headline behaviour: an applicant who settles on a country
does not wait for anyone to hand them a list of requirements. Setting the
journey's destination *is* the request.

**Why a signal, and not a call from ``applicant_journeys``.** The dependency has
to run one way. ``checklists`` knows about journeys; ``applicant_journeys`` must
never learn that checklists exist, or the journeys app acquires a reason to
break every time this one changes. §11's three tests are all met: the side effect
is decoupled from the trigger, it does not need the trigger's transaction, and
there is exactly one place that fires it.

**Why no "did the country change" check.** ``inherit_for_journey`` is idempotent
— it looks for an existing live checklist from the same template and does
nothing when it finds one. Comparing against a previous value would need a
``pre_save`` receiver stashing state on the instance, and would buy nothing that
the idempotency check does not already guarantee.

**Why ``on_commit``.** A checklist is written only once the journey it belongs to
is really in the database. A journey save that rolls back leaves nothing behind,
and a failure in here can never roll back the journey save that triggered it —
the destination being recorded matters more than the list being generated, and
the list can always be generated later by ``apply_country_checklists``.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from checklists.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_CHECKLIST,
    ChecklistAuditAction,
)

logger = logging.getLogger(__name__)


def _signals_disabled() -> bool:
    """True when signal side effects are switched off for this process.

    Set ``DISABLE_SIGNALS = True`` for bulk imports that write thousands of
    journeys and would otherwise produce a checklist per row inside the import's
    own transaction. Rebuild afterwards with::

        python manage.py apply_country_checklists

    (§11 — a signal that cannot be switched off cannot be imported around.)
    """
    return bool(getattr(settings, "DISABLE_SIGNALS", False))


def inherit_country_checklist(journey_id: Any) -> None:
    """Give this journey its destination's checklist, if there is one.

    Re-reads the journey rather than trusting the instance handed to the
    receiver: by the time this runs the transaction has committed, and the row
    is the authority on what was actually saved.

    Swallows every failure on purpose. This runs after commit, outside any
    request the client is still waiting on, and there is nothing useful to raise
    *to* — the journey is saved either way. What a failure must not do is stay
    invisible, so it goes to the log **and** to the audit trail as an
    unsuccessful event.
    """
    from applicant_journeys.models import ApplicantJourney
    from audit.services import record_event

    from checklists.services import inherit_for_journey

    journey = ApplicantJourney.objects.select_related("applicant", "target_country_ref").filter(pk=journey_id).first()
    if journey is None or not journey.target_country_ref_id:
        return

    try:
        checklist = inherit_for_journey(journey)
    except Exception:  # noqa: BLE001 — see the docstring: nothing may propagate from here.
        logger.exception(
            "checklist inheritance failed",
            extra={"journey_id": str(journey_id), "country_id": str(journey.target_country_ref_id)},
        )
        record_event(
            app_label=AUDIT_APP_LABEL,
            action=ChecklistAuditAction.CHECKLIST_INHERIT_FAILED,
            entity_type=AUDIT_ENTITY_CHECKLIST,
            success=False,
            summary="Automatic checklist inheritance failed for this journey.",
            metadata={
                "journey_id": str(journey_id),
                "country_id": str(journey.target_country_ref_id),
            },
        )
        return

    if checklist is not None:
        logger.info(
            "checklist inherited",
            extra={
                "journey_id": str(journey_id),
                "checklist_id": str(checklist.id),
                "template_id": str(checklist.source_template_id),
            },
        )


@receiver(post_save, sender="applicant_journeys.ApplicantJourney", dispatch_uid="checklists_inherit_on_journey_save")
def on_journey_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Queue inheritance for any journey that names a catalogue country.

    ``dispatch_uid`` keeps a double import from connecting the receiver twice,
    which would attempt two checklists for one journey — the second harmlessly
    refused, but the audit log would carry a failure nobody caused.
    """
    if _signals_disabled() or not getattr(instance, "target_country_ref_id", None):
        return
    journey_id = instance.pk
    transaction.on_commit(lambda: inherit_country_checklist(journey_id))
