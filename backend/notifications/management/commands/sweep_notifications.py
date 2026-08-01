"""Raise deadline alerts, and resolve the ones whose work is done.

The other half of this app's generation is real-time (``notifications/signals.py``).
This is the half that cannot be: nothing *happens* when a deadline arrives, so
something has to go and look. Intended to run nightly from cron.

**Why a management command and not Celery.** §1 puts a task on Celery when it
needs retries, exceeds ~500ms in a request, or must run outside the request
cycle. Only the third applies, and cron already satisfies it. A broker, a worker,
and a result backend would be three pieces of infrastructure (§28 item 15) bought
to run one idempotent query set once a day. §37's local-first default points the
same way. If this ever needs per-alert retries or sub-hourly cadence, Celery
becomes the right answer and this command becomes its task body.

**Why two passes.** The raise pass produces, as a by-product, the complete set of
conditions that are true right now. The resolve pass is then a set subtraction —
anything active whose key is not in that set has been dealt with in the source
app — rather than a second round of per-row queries asking each source record
whether it is still overdue.

**Idempotency is structural, not conventional.** Every write goes through
``get_or_create`` on ``(recipient, dedupe_key)``, which runs against a unique
constraint. Two runs in the same minute create nothing the second time; two
concurrent runs race into the database rather than into each other. Safe on a
live system, and safe to re-run after a failure.

**A failing generator never mass-resolves.** If the offer generator raises, its
types are withheld from the resolve pass — otherwise a transient database error
would read as "no offer deadlines exist any more" and close every live offer
alert in the system. That is the single most damaging thing this command could
do, and it is the reason the failure handling here is more careful than the
amount of code suggests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from applicants.selectors import get_expiring_passports
from checklists.selectors import (
    get_checklists_with_pending_documents,
    get_due_soon_checklist_items,
    get_overdue_checklist_items,
)
from django.core.management.base import BaseCommand, CommandError
from offers.selectors import get_offers_awaiting_response

from notifications import services
from notifications.constants import (
    DEFAULT_DUE_WITHIN_DAYS,
    DEFAULT_PASSPORT_HORIZON_DAYS,
    SWEEP_TYPES,
    GenerationSource,
    NotificationType,
)


class Command(BaseCommand):
    help = (
        "Raise deadline notifications from the owning apps' selectors, and resolve alerts whose "
        "source condition has cleared. Idempotent — safe to re-run and safe on a live database."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--type",
            dest="only_type",
            choices=list(SWEEP_TYPES),
            help="Run only this generator. The resolve pass is narrowed to match, so no other type is touched.",
        )
        parser.add_argument(
            "--due-within-days",
            type=int,
            default=DEFAULT_DUE_WITHIN_DAYS,
            help=f"Horizon for 'due soon' checklist items and offer deadlines (default {DEFAULT_DUE_WITHIN_DAYS}).",
        )
        parser.add_argument(
            "--passport-horizon-days",
            type=int,
            default=DEFAULT_PASSPORT_HORIZON_DAYS,
            help=(
                "How far ahead to look for expiring passports "
                f"(default {DEFAULT_PASSPORT_HORIZON_DAYS} — renewing a Nepali passport is not a same-week errand)."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            help=(
                "Stop each generator after this many source rows. For a cautious first pass on a large "
                "database. Implies --no-resolve: a truncated run has only a partial view of what is "
                "still true, and resolving against it would close live alerts."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be raised and resolved, and write nothing.",
        )
        parser.add_argument(
            "--no-resolve",
            action="store_true",
            help="Raise only. Leaves alerts active whose source condition has already cleared.",
        )

    #: ``(due_within_days, overdue, approaching)`` for this run — see ``_split_offers``.
    _offer_split: tuple[int, list[Any], list[Any]] | None = None

    def handle(self, *args: Any, **options: Any) -> None:
        self._offer_split = None
        only_type: str | None = options.get("only_type")
        due_within_days: int = options["due_within_days"]
        passport_horizon: int = options["passport_horizon_days"]
        limit: int | None = options.get("limit")
        dry_run: bool = options["dry_run"]
        no_resolve: bool = options["no_resolve"]

        if due_within_days < 1 or passport_horizon < 1:
            raise CommandError("Horizons must be at least one day.")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1.")

        generators = self._generators(due_within_days=due_within_days, passport_horizon=passport_horizon)
        if only_type:
            generators = {only_type: generators[only_type]}

        raised: dict[str, int] = {}
        live_keys: set[str] = set()
        # Types whose generator completed. Only these may be resolved — a type
        # whose generator raised has no reliable "currently true" key set, and
        # resolving against an incomplete one would close live alerts.
        examined: list[str] = []

        # One Admin lookup for the whole run rather than one per source row.
        # Every ownerless alert — offers and passports, today — falls back to
        # the Admin fan-out, so without this the query count grows with the
        # size of the backlog instead of with the number of generators.
        with services.cached_admin_recipients():
            for notification_type, generate in generators.items():
                try:
                    created, keys = generate(limit=limit, dry_run=dry_run)
                except Exception as exc:  # noqa: BLE001 — one broken generator must not stop the others.
                    services.record_generation_failure(notification_type, exc)
                    self.stderr.write(self.style.ERROR(f"  ! {notification_type}: {type(exc).__name__} — skipped"))
                    continue

                raised[notification_type] = created
                live_keys |= keys
                examined.append(notification_type)
                self.stdout.write(f"  {notification_type}: {created} raised ({len(keys)} conditions true)")

        # A limited run must never resolve. ``--limit`` truncates each generator's
        # source rows and its key set with them, so ``live_keys`` is a *partial*
        # picture of what is true — and the resolve pass treats every key it does
        # not contain as a condition that has cleared. Left to run, `--limit 5`
        # over 50 live alerts resolves 45 of them as SOURCE_CLEARED. The flag is
        # documented as "a cautious first pass on a large database", which is
        # precisely the situation with the most alerts to destroy, so this is
        # enforced here rather than left to the operator to remember.
        if limit is not None and not no_resolve:
            no_resolve = True
            self.stderr.write(
                self.style.WARNING("--limit given: skipping the resolve pass (a truncated run cannot resolve safely).")
            )

        resolved = 0
        if not no_resolve and examined and not dry_run:
            resolved = services.resolve_cleared(live_keys, types=tuple(examined))
        elif not no_resolve and examined and dry_run:
            from notifications.selectors import get_sweep_candidates_to_resolve

            resolved = get_sweep_candidates_to_resolve(types=tuple(examined)).exclude(dedupe_key__in=live_keys).count()

        total = sum(raised.values())
        prefix = "[dry run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}Sweep complete: {total} raised, {resolved} resolved."))
        if len(examined) < len(generators):
            # Never let a partial run report as a clean one — a silent gap here
            # is indistinguishable from a quiet night.
            self.stderr.write(
                self.style.WARNING(f"{len(generators) - len(examined)} generator(s) failed and were skipped.")
            )

    # -----------------------------------------------------------------------
    # Generators — each returns (rows created, keys that are true right now)
    # -----------------------------------------------------------------------

    def _generators(
        self,
        *,
        due_within_days: int,
        passport_horizon: int,
    ) -> dict[str, Callable[..., tuple[int, set[str]]]]:
        """One callable per sweep type, keyed by the type it raises.

        Keyed by type rather than held in a list, so ``--type`` selects one
        without a lookup table that could disagree with ``SWEEP_TYPES``.
        """
        return {
            NotificationType.CHECKLIST_ITEM_OVERDUE: lambda **kw: self._run(
                get_overdue_checklist_items(),
                lambda item: services.build_checklist_item_alert(item, overdue=True),
                services.recipients_for_checklist_item,
                **kw,
            ),
            NotificationType.CHECKLIST_ITEM_DUE: lambda **kw: self._run(
                get_due_soon_checklist_items(due_within_days=due_within_days),
                lambda item: services.build_checklist_item_alert(item, overdue=False),
                services.recipients_for_checklist_item,
                **kw,
            ),
            NotificationType.MISSING_DOCUMENTS: lambda **kw: self._run(
                get_checklists_with_pending_documents(),
                services.build_missing_documents_alert,
                services.recipients_for_checklist,
                **kw,
            ),
            NotificationType.OFFER_EXPIRED: lambda **kw: self._run(
                self._overdue_offers(due_within_days),
                lambda offer: services.build_offer_deadline_alert(offer, expired=True),
                lambda _offer: services.recipients_for_admins(),
                **kw,
            ),
            NotificationType.OFFER_RESPONSE_DUE: lambda **kw: self._run(
                self._approaching_offers(due_within_days),
                lambda offer: services.build_offer_deadline_alert(offer, expired=False),
                lambda _offer: services.recipients_for_admins(),
                **kw,
            ),
            NotificationType.PASSPORT_EXPIRING: lambda **kw: self._run(
                get_expiring_passports(within_days=passport_horizon),
                services.build_passport_alert,
                lambda _passport: services.recipients_for_admins(),
                **kw,
            ),
        }

    def _run(
        self,
        rows: Iterable[Any],
        build: Callable[[Any], services.AlertSpec],
        route: Callable[[Any], list[Any]],
        *,
        limit: int | None,
        dry_run: bool,
    ) -> tuple[int, set[str]]:
        """Raise one generator's alerts. Returns rows created and the keys now true.

        The key set is collected **whether or not** anything was created, because
        it is the input to the resolve pass rather than a report of this run's
        writes: a condition that is still true and already has an alert must keep
        that alert alive.

        ``--limit`` truncates the source rows, and the key set with them — which
        is why a limited run must not be trusted to resolve. ``handle`` enforces
        that by turning ``--no-resolve`` on whenever ``--limit`` is given, so a
        limited run is a raise-only tool by construction rather than by
        convention.
        """
        created = 0
        keys: set[str] = set()

        for index, row in enumerate(rows):
            if limit is not None and index >= limit:
                break
            spec = build(row)
            keys.add(spec.dedupe_key)
            if dry_run:
                continue
            created += len(services.dispatch(spec, route(row), generated_by=GenerationSource.SWEEP))

        return created, keys

    # -----------------------------------------------------------------------
    # Offers: one selector, two alerts
    # -----------------------------------------------------------------------
    #
    # ``offers.get_offers_awaiting_response`` deliberately returns already-passed
    # and merely-approaching deadlines together — splitting them into two queries
    # would put the most urgent rows in the section a user reads second. This app
    # does need them apart, because they are different alerts at different
    # priorities, so the split happens here, in Python, against the same
    # ``nepal_today()`` boundary the selector itself uses (§39.5). Re-querying
    # with a narrower filter would have re-implemented that app's definition of
    # "overdue" in a second place.
    #
    # **The selector runs once per command, not once per alert type.** Both offer
    # generators need the same rows, and asking for them twice fetched every
    # awaiting-response offer and all of its joined relations a second time to
    # produce the complement of a list already in memory.

    def _split_offers(self, due_within_days: int) -> tuple[list[Any], list[Any]]:
        """``(overdue, approaching)`` offers, from a single pass over the selector.

        Memoized on the horizon it was computed for. One command run has one
        ``--due-within-days``, so the memo can only ever be hit with the same
        value; keying on it anyway means a future caller that varies the horizon
        gets a correct answer rather than a stale one.
        """
        cached = self._offer_split
        if cached is not None and cached[0] == due_within_days:
            return cached[1], cached[2]

        today = self._today()
        overdue: list[Any] = []
        approaching: list[Any] = []
        for offer in get_offers_awaiting_response(due_within_days=due_within_days):
            if not offer.response_deadline:
                continue
            if offer.response_deadline < today:
                overdue.append(offer)
            else:
                approaching.append(offer)

        self._offer_split = (due_within_days, overdue, approaching)
        return overdue, approaching

    def _overdue_offers(self, due_within_days: int) -> list[Any]:
        return self._split_offers(due_within_days)[0]

    def _approaching_offers(self, due_within_days: int) -> list[Any]:
        return self._split_offers(due_within_days)[1]

    @staticmethod
    def _today() -> Any:
        from core.nepal.calendar import nepal_today

        return nepal_today()
