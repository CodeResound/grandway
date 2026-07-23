"""Data models for the applicant_journeys app.

See ``applicant_journeys/docs/DATA_CONTRACT.md`` for the authoritative contract.
"""

from __future__ import annotations

from core.constants import StudyLevel
from core.models import BaseModel
from django.db import models

from applicant_journeys.constants import CreationSource, JourneyOutcome, JourneyStage


class ApplicantJourney(BaseModel):
    """One overseas-study objective pursued by one applicant.

    A person is not the same thing as a plan. Someone may try for a master's in
    Australia, have it fall through, and try again for a diploma in Canada two
    years later — two journeys, one applicant, each with its own destination,
    progress, and ending (``concepts/applicant_journeys.txt`` — "Purpose").

    The journey never stores the person's name or contact details; it references
    the applicant. A journey's stage never changes the applicant's status, and
    archiving an applicant never closes their journeys — the two lifecycles run
    independently, by design.

    The ``deferred_*`` and ``closed_*`` fields are denormalized *current state*,
    mirroring the pattern used by ``leads`` and ``core.policy_engine`` (§35 item
    15): current state is a plain field read, while the append-only audit log
    remains the authoritative event history.
    """

    applicant = models.ForeignKey(
        "applicants.Applicant",
        on_delete=models.PROTECT,
        related_name="journeys",
    )

    # --- The objective -----------------------------------------------------
    target_country = models.CharField(max_length=100, blank=True)
    # Free text until the institutions module exists — a nullable FK still needs
    # a target table, and there is nothing to point at yet. Migrating these into
    # real references is future work (see docs/DATA_CONTRACT.md).
    target_institution_name = models.CharField(max_length=255, blank=True)
    target_program_name = models.CharField(max_length=255, blank=True)
    study_level = models.CharField(max_length=30, choices=StudyLevel.choices, blank=True)
    field_of_study = models.CharField(max_length=150, blank=True)
    preferred_intake = models.CharField(
        max_length=50,
        blank=True,
        help_text='Free text until intakes are catalogued, e.g. "Fall 2026".',
    )
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_currency = models.CharField(max_length=3, blank=True, help_text="ISO 4217 code, e.g. NPR.")
    scholarship_interest = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    # --- Progress ----------------------------------------------------------
    stage = models.CharField(
        max_length=30,
        choices=JourneyStage.choices,
        default=JourneyStage.PLANNING,
        db_index=True,
    )
    creation_source = models.CharField(max_length=20, choices=CreationSource.choices)
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="journeys_created",
    )

    # --- Deferment state (cleared on reopen) -------------------------------
    deferred_at = models.DateTimeField(null=True, blank=True)
    deferred_to_intake = models.CharField(max_length=50, blank=True)
    deferment_reason = models.TextField(blank=True)
    deferred_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journeys_deferred",
    )

    # --- Closure state (cleared on reopen) ---------------------------------
    outcome = models.CharField(max_length=20, choices=JourneyOutcome.choices, blank=True)
    closure_reason = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journeys_closed",
    )
    stage_before_terminal = models.CharField(max_length=30, choices=JourneyStage.choices, blank=True)

    class Meta:
        db_table = "applicant_journeys_applicantjourney"
        verbose_name = "Applicant Journey"
        verbose_name_plural = "Applicant Journeys"
        ordering = ["-created_at"]
        indexes = [
            # The per-person view: one applicant's journeys, newest first.
            models.Index(fields=["applicant", "-created_at"], name="journey_applicant_recent_idx"),
            # The operational worklist: "everything at Offer Stage".
            models.Index(fields=["stage", "-created_at"], name="journey_stage_recent_idx"),
        ]

    def __str__(self) -> str:
        destination = self.target_country or "unspecified destination"
        return f"{destination} ({self.stage})"

    @property
    def is_completed(self) -> bool:
        return self.stage == JourneyStage.COMPLETED

    @property
    def is_closed(self) -> bool:
        return self.stage == JourneyStage.CLOSED

    @property
    def is_deferred(self) -> bool:
        return self.stage == JourneyStage.DEFERRED

    @property
    def is_terminal(self) -> bool:
        """True when the journey must be reopened before its stage can move again."""
        return self.is_completed or self.is_closed or self.is_deferred
