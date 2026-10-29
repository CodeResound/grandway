"""Domain events — one post-commit signal that apps raise and other apps may listen to (§11).

A service that has just done something other apps may care about — a lead was
converted, an applicant restored, a document marked ready — calls ``emit``. It
does not know who is listening, and it must not: ``notifications`` is the one
receiver today, and the dependency has to run from it to the producers, never
the other way, or every producer acquires a reason to break when notifications
changes.

**Why ``on_commit``.** Listeners hear about a change only once it is really in
the database. A transaction that rolls back emits nothing, and a listener that
fails can never roll back the write that triggered it.

**Why the actor travels with the event.** ``post_save`` cannot say *who* saved a
row, and "never notify someone of their own action" needs exactly that.

**Why an ``event_id``.** Each emission gets a fresh UUID, so a listener can tell
two occurrences of the same event apart — a lead deleted, restored, and deleted
again is three facts, not one.

Lives in ``core`` because it is shared infrastructure used by three apps and owns
no business rule (§2).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import transaction
from django.dispatch import Signal

#: Sent with ``sender=<event name>`` and keyword arguments ``event``, ``event_id``,
#: ``actor``, ``entity_type``, ``entity_id``, and ``data`` (a plain dict).
domain_event = Signal()


def emit(event: str, *, actor: Any, entity_type: str, entity_id: Any, **data: Any) -> None:
    """Announce ``event`` to every listener once the current transaction commits.

    ``event`` is ``<entity>.<what happened>`` (``lead.converted``). ``data`` must
    hold plain values — ids, enum strings — never a model instance: listeners run
    after commit and re-read what they need.

    A no-op under ``settings.DISABLE_SIGNALS``, the same switch the bulk-import
    path uses for every other signal in the project.
    """
    if getattr(settings, "DISABLE_SIGNALS", False):
        return
    event_id = uuid.uuid4()
    transaction.on_commit(
        lambda: domain_event.send(
            sender=event,
            event=event,
            event_id=event_id,
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data,
        )
    )
