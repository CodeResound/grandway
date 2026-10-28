"""``core.events.emit`` — the post-commit domain-event hook (2026-10-29).

``TransactionTestCase`` because the whole point is ``on_commit``: in a plain
``TestCase`` the outer transaction never commits and nothing would ever fire.
The event name is one no real receiver handles, so only this suite's listener
reacts.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.test import TransactionTestCase, override_settings

from core.events import domain_event, emit


class EmitTests(TransactionTestCase):
    def setUp(self) -> None:
        self.received: list[dict[str, Any]] = []

        def listener(sender: Any, **kwargs: Any) -> None:
            self.received.append(kwargs)

        domain_event.connect(listener, weak=False, dispatch_uid="test_events_listener")
        self.addCleanup(domain_event.disconnect, dispatch_uid="test_events_listener")

    def test_fires_after_commit_with_the_actor_and_data(self) -> None:
        with transaction.atomic():
            emit("test.happened", actor="someone", entity_type="lead", entity_id="abc", stage="new")
            self.assertEqual(self.received, [])  # not before the commit
        self.assertEqual(len(self.received), 1)
        event = self.received[0]
        self.assertEqual((event["event"], event["actor"], event["entity_id"]), ("test.happened", "someone", "abc"))
        self.assertEqual(event["data"], {"stage": "new"})
        self.assertIsNotNone(event["event_id"])

    def test_never_fires_on_rollback(self) -> None:
        try:
            with transaction.atomic():
                emit("test.happened", actor=None, entity_type="lead", entity_id="abc")
                raise RuntimeError("roll back")
        except RuntimeError:
            pass
        self.assertEqual(self.received, [])

    def test_each_emission_has_its_own_event_id(self) -> None:
        emit("test.happened", actor=None, entity_type="lead", entity_id="abc")
        emit("test.happened", actor=None, entity_type="lead", entity_id="abc")
        self.assertNotEqual(self.received[0]["event_id"], self.received[1]["event_id"])

    @override_settings(DISABLE_SIGNALS=True)
    def test_disable_signals_silences_it(self) -> None:
        emit("test.happened", actor=None, entity_type="lead", entity_id="abc")
        self.assertEqual(self.received, [])
