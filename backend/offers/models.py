"""Data models for the offers app.

See ``offers/docs/DATA_CONTRACT.md`` for the authoritative contract.

Three conventions run through both models here and are deliberate:

* **The reference block is written once and never rewritten.** An offer carries
  a *snapshot* of the institution, campus, program, level, and intake as they
  stood when the institution made its decision, alongside optional foreign keys
  into the live catalogue. ``concepts/offers.txt`` — "The offer should preserve
  what was true when the institution made the decision. Later catalogue edits,
  applicant updates, or intake changes should not rewrite the historical offer
  record."
* **Nothing is ever deleted.** No resource here has a delete endpoint. An offer
  that is no longer live becomes terminal; a condition that no longer applies
  becomes ``not_applicable``.
* **Snapshot names are English-only**, like every name in the system — as in
  §39.1, inherited from ``institutions``. These are foreign proper nouns with
  no authoritative Devanagari identity; requiring one would produce invented
  transliterations. See ``docs/DATA_CONTRACT.md`` — "Deliberate Deviations".
"""

from __future__ import annotations

from core.constants import FeePeriod, StudyLevel
from core.models import BaseModel
from core.nepal.calendar import nepal_today
from core.validators import validate_currency_code
from django.db import models

from offers.constants import (
    RESOLVED_CONDITION_STATUSES,
    TERMINAL_STATUSES,
    ConditionStatus,
    ConditionType,
    OfferSource,
    OfferStatus,
    OfferType,
)


class Offer(BaseModel):
    """One institution's admission decision, recorded against one journey.

    The journey remains the broader study plan; this is a single concrete
    institutional response within it. A journey may collect several — a second
    offer never replaces a first, because comparing competing responses is the
    whole reason the records are separate (``concepts/offers.txt`` — "Track
    multiple offers").

    Recording an offer does **not** move the journey's stage. Journey stage,
    offer status, and applicant status are separate lifecycles by project rule
    (``concepts/project_overview.txt`` — "Explicit lifecycle states"), so this
    app reads the journey and never writes to it.

    The ``decided_*`` fields are denormalized *current state*, mirroring the
    pattern in ``applicant_journeys`` and ``core.policy_engine`` (§35 item 15):
    current state is a plain field read, while the append-only audit log remains
    the authoritative event history.
    """

    journey = models.ForeignKey(
        "applicant_journeys.ApplicantJourney",
        on_delete=models.PROTECT,
        related_name="offers",
    )

    # --- Catalogue reference ----------------------------------------------
    #
    # Nullable because an offer may be a manual historical record with no
    # catalogue entry behind it, and PROTECT because the catalogue has no
    # delete path at all — a withdrawn catalogue record becomes
    # ``availability_status=inactive`` and the offer still resolves through it.
    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.PROTECT,
        related_name="offers",
        null=True,
        blank=True,
    )
    campus = models.ForeignKey(
        "institutions.Campus",
        on_delete=models.PROTECT,
        related_name="offers",
        null=True,
        blank=True,
    )
    program = models.ForeignKey(
        "institutions.Program",
        on_delete=models.PROTECT,
        related_name="offers",
        null=True,
        blank=True,
    )
    reference_source = models.CharField(
        max_length=20,
        choices=OfferSource.choices,
        help_text="Whether this offer was built from the catalogue or typed in as a historical record.",
    )

    # --- Snapshot (written at creation, never rewritten) --------------------
    #
    # This block, not the foreign keys above, is what the offer *means*. It
    # answers "what was offered" even after the catalogue record is renamed,
    # repriced, or marked inactive — and for a manual offer it is the only
    # answer there is.
    institution_name = models.CharField(max_length=255)
    campus_name = models.CharField(max_length=255, blank=True)
    program_title = models.CharField(max_length=255)
    country_name = models.CharField(max_length=150, blank=True)
    qualification_level = models.CharField(max_length=30, choices=StudyLevel.choices, blank=True)
    intake_label = models.CharField(
        max_length=100,
        blank=True,
        help_text='The intake this offer applies to, free text until intakes are catalogued, e.g. "Feb 2027".',
    )

    # --- The decision itself ------------------------------------------------
    offer_type = models.CharField(max_length=20, choices=OfferType.choices, default=OfferType.CONDITIONAL)
    offer_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="The institution's own offer or letter number, as printed on the document.",
    )
    issue_date = models.DateField(null=True, blank=True)
    response_deadline = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="The date by which the applicant must respond. Drives the overdue flag and deadline reporting.",
    )

    # --- Tuition, as quoted in this offer ----------------------------------
    #
    # Separate from the catalogue's figure on purpose: the catalogue holds what
    # a program generally costs, this holds what this applicant was actually
    # quoted, and the two are allowed to disagree.
    tuition_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tuition_currency = models.CharField(max_length=3, blank=True, validators=[validate_currency_code])
    tuition_fee_period = models.CharField(max_length=20, choices=FeePeriod.choices, blank=True)

    # --- Scholarship --------------------------------------------------------
    scholarship_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    scholarship_currency = models.CharField(max_length=3, blank=True, validators=[validate_currency_code])
    scholarship_notes = models.TextField(blank=True)

    # --- Deposit ------------------------------------------------------------
    #
    # Recorded, never collected. ``concepts/offers.txt`` — "No payments or
    # accounting. Deposit amounts can be recorded, but payment collection is
    # not part of this module."
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    deposit_currency = models.CharField(max_length=3, blank=True, validators=[validate_currency_code])
    deposit_due_date = models.DateField(null=True, blank=True)
    deposit_notes = models.TextField(blank=True)

    # --- Lifecycle ----------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=OfferStatus.choices,
        default=OfferStatus.DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="offers_created",
    )

    # --- Decision state (set once; offers are never reopened) ---------------
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offers_decided",
    )
    deferred_to_intake = models.CharField(
        max_length=100,
        blank=True,
        help_text="Set only when the decision was to defer. The intake the offer was moved to.",
    )

    class Meta:
        db_table = "offers_offer"
        verbose_name = "Offer"
        verbose_name_plural = "Offers"
        ordering = ["-created_at"]
        indexes = [
            # The Journey Detail offers panel: one journey's offers, newest first.
            models.Index(fields=["journey", "-created_at"], name="offer_journey_recent_idx"),
            # The Offer List worklist: "everything still awaiting a response".
            models.Index(fields=["status", "-created_at"], name="offer_status_recent_idx"),
            # Dashboard decision windows: get_decision_counts filters
            # decided_at__isnull=False plus a date range on every pipeline/
            # outcomes/conversion section render (audit P4).
            models.Index(fields=["decided_at"], name="offer_decided_at_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.program_title} — {self.institution_name} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        """True when the offer has been decided and accepts no further decision."""
        return self.status in TERMINAL_STATUSES

    @property
    def is_decided(self) -> bool:
        """True when a decision has actually been recorded against this offer."""
        return self.decided_at is not None

    @property
    def is_response_overdue(self) -> bool:
        """True when an issued offer's response deadline has passed.

        Computed, never stored. Nothing in V1 runs on a schedule, so a stored
        flag would be stale the day after it was written. The date comparison
        is made in Nepal time (§39.5) — a deadline is a calendar day where the
        staff work, not in UTC.
        """
        if self.status != OfferStatus.ISSUED or self.response_deadline is None:
            return False
        return self.response_deadline < nepal_today()

    @property
    def has_open_conditions(self) -> bool:
        """True when any condition still stands in the way of this offer.

        Callers listing many offers should prefetch ``conditions`` — see
        ``selectors.get_offers``.
        """
        return any(c.status not in RESOLVED_CONDITION_STATUSES for c in self.conditions.all())


class OfferCondition(BaseModel):
    """One requirement that must be satisfied for an offer to become usable.

    A dedicated sub-record rather than an entry in a reusable checklist: the
    ``checklists`` domain named in ``concepts/project_overview.txt`` does not
    exist yet, and building a generic checklist here would pre-empt it. See
    ``docs/DATA_CONTRACT.md`` — "Deliberate Deviations".

    Conditions are never deleted. One that turns out not to apply is marked
    ``not_applicable`` with a note, so the offer's history still shows that the
    institution asked for it.
    """

    offer = models.ForeignKey(
        Offer,
        on_delete=models.CASCADE,
        related_name="conditions",
    )
    condition_type = models.CharField(max_length=30, choices=ConditionType.choices)
    description = models.TextField(help_text="The requirement in the institution's own words.")
    due_date = models.DateField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=ConditionStatus.choices,
        default=ConditionStatus.PENDING,
        db_index=True,
    )
    resolution_note = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offer_conditions_resolved",
    )

    class Meta:
        db_table = "offers_offercondition"
        verbose_name = "Offer Condition"
        verbose_name_plural = "Offer Conditions"
        ordering = ["display_order", "created_at"]
        indexes = [
            # The Offer Detail conditions panel, and "what is still pending".
            models.Index(fields=["offer", "status"], name="condition_offer_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_condition_type_display()} ({self.status})"

    @property
    def is_resolved(self) -> bool:
        """True when this condition no longer blocks the offer."""
        return self.status in RESOLVED_CONDITION_STATUSES
