"""Data models for the leads app.

See ``leads/docs/DATA_CONTRACT.md`` for the authoritative contract.
"""

from __future__ import annotations

from core.constants import ContactNumberLabel, LanguageTestStatus, StudyLevel
from core.models import BaseModel
from core.validators import validate_contact_number
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from leads.constants import LeadStage
from leads.validators import validate_reference_code


class ReferenceEntry(BaseModel):
    """Shared shape for the app's two Admin-configurable reference tables.

    Lead sources and loss reasons are configurable rather than hardcoded
    (``concepts/leads.txt`` — "Lead source" / "Marking a lead as lost"), and
    carry identical fields. Abstract so each keeps its own table; declared once
    so the two never drift apart.

    Entries are deactivated, never deleted — existing leads keep pointing at
    them, and the consultancy's history stays readable.
    """

    code = models.CharField(max_length=50, unique=True, validators=[validate_reference_code])
    name = models.CharField(max_length=150)

    requires_detail = models.BooleanField(
        default=False,
        help_text='Set on catch-all entries such as "Other" so the user must explain their choice.',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class LeadSource(ReferenceEntry):
    """How a lead found the consultancy — walk-in, referral, TikTok, and so on."""

    class Meta(ReferenceEntry.Meta):
        abstract = False
        db_table = "leads_leadsource"
        verbose_name = "Lead Source"
        verbose_name_plural = "Lead Sources"


class LossReason(ReferenceEntry):
    """Why a lead did not proceed — recorded whenever a lead is marked lost."""

    class Meta(ReferenceEntry.Meta):
        abstract = False
        db_table = "leads_lossreason"
        verbose_name = "Loss Reason"
        verbose_name_plural = "Loss Reasons"


class Lead(BaseModel):
    """A person who has shown interest but has not entered the applicant lifecycle.

    Ownership is by creation and never moves: Grandway has no lead pools,
    assignment, transfer, or reassignment (``concepts/leads.txt`` — "Lead
    ownership"). ``created_by`` stays attached even after conversion so the
    applicant's origin remains attributable.

    The ``lost_*`` and ``converted_*`` fields are denormalized *current state*,
    mirroring the ``core.policy_engine`` lifecycle pattern (§35 item 15): they
    make "which leads are lost, and why" a plain field read, while the
    append-only audit log remains the authoritative event history.
    """

    # --- Identity ----------------------------------------------------------
    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # --- Tracking ----------------------------------------------------------
    source = models.ForeignKey(LeadSource, on_delete=models.PROTECT, related_name="leads")
    source_detail = models.CharField(
        max_length=255,
        blank=True,
        help_text='Required when the chosen source requires detail (e.g. "Other").',
    )
    stage = models.CharField(
        max_length=30,
        choices=LeadStage.choices,
        default=LeadStage.NEW,
        db_index=True,
    )
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="leads_created",
        help_text="The Lead Manager who created this lead. Immutable — ownership never moves.",
    )

    # --- Manual follow-up --------------------------------------------------
    last_followed_up_at = models.DateTimeField(null=True, blank=True)
    last_followed_up_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_followups_recorded",
    )

    # --- Lost state (cleared on reopen) ------------------------------------
    lost_reason = models.ForeignKey(
        LossReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leads",
    )
    lost_detail = models.TextField(blank=True)
    lost_at = models.DateTimeField(null=True, blank=True)
    lost_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads_marked_lost",
    )
    stage_before_loss = models.CharField(max_length=30, choices=LeadStage.choices, blank=True)

    # --- Conversion state --------------------------------------------------
    # ``converted_applicant`` is a OneToOne deliberately: it puts "never create a
    # second applicant from one lead" in the database rather than in service
    # logic, which is the strongest available form of the idempotency §15
    # requires for conversion. ``leads`` owns both links, so ``applicants`` and
    # ``applicant_journeys`` carry no dependency on this app and work perfectly
    # well for an applicant created directly. Read the reverse direction via
    # ``applicant.originating_lead``.
    converted_applicant = models.OneToOneField(
        "applicants.Applicant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="originating_lead",
    )
    converted_journey = models.ForeignKey(
        "applicant_journeys.ApplicantJourney",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="originating_leads",
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads_converted",
    )

    class Meta:
        db_table = "leads_lead"
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ["-created_at"]
        indexes = [
            # The default list view: a Lead Manager's own leads, newest first.
            models.Index(fields=["created_by", "-created_at"], name="lead_owner_recent_idx"),
            # Funnel and stage filters, scoped or unscoped.
            models.Index(fields=["stage", "-created_at"], name="lead_stage_recent_idx"),
            # Name search (§39.6). ``search_leads`` runs a leading-wildcard
            # icontains, which a B-tree index cannot serve — hence GIN trigram.
            # One index now rather than three: there is one name to search.
            GinIndex(fields=["full_name"], name="lead_name_trgm_idx", opclasses=["gin_trgm_ops"]),
            # ``search_leads`` also matches the email with a leading wildcard,
            # so the same reasoning as the name fields applies.
            GinIndex(fields=["email"], name="lead_email_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.stage})"

    @property
    def is_lost(self) -> bool:
        return self.stage == LeadStage.LOST

    @property
    def is_converted(self) -> bool:
        return self.stage == LeadStage.CONVERTED

    @property
    def is_terminal(self) -> bool:
        """True when the lead must be reopened before its stage can move again."""
        return self.is_lost or self.is_converted


class LeadContactNumber(BaseModel):
    """One reachable number for a lead.

    A person may give more than one usable number, so this is a collection
    while ``Lead.email`` stays a single field (``concepts/leads.txt`` — "Lead
    information"). Managed nested inside the lead payload, not through its own
    endpoints.
    """

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="contact_numbers")
    number = models.CharField(max_length=32, validators=[validate_contact_number])
    label = models.CharField(
        max_length=20,
        choices=ContactNumberLabel.choices,
        default=ContactNumberLabel.MOBILE,
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "leads_leadcontactnumber"
        verbose_name = "Lead Contact Number"
        verbose_name_plural = "Lead Contact Numbers"
        ordering = ["-is_primary", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["lead", "number"], name="uniq_lead_contact_number"),
        ]
        indexes = [
            # ``search_leads`` joins here to find a lead from a phone number
            # alone. The unique constraint above is on ``(lead, number)`` and
            # cannot serve a lookup that does not know the lead.
            models.Index(fields=["number"], name="lead_contact_number_idx"),
            # The B-tree above serves an equality or prefix lookup. It cannot
            # serve the one the search box actually issues: ``number__icontains``
            # has a leading wildcard, and a B-tree has no way in. Every phone
            # search — the single most common way a lead is found, because a
            # lead is usually a number in a call log before anyone has agreed
            # how to spell the name — was therefore a sequential scan of this
            # table. Both indexes are kept: the B-tree stays cheaper for the
            # exact-match paths, and the GIN is what makes substring search
            # scale (§39.6).
            GinIndex(fields=["number"], name="lead_contact_num_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.label})"


class LeadStudyInterest(BaseModel):
    """What the person is considering, as far as it is known during follow-up.

    Preliminary and possibly incomplete. It is explicitly *not* an applicant
    journey — the authoritative journey is created only at conversion
    (``concepts/leads.txt`` — "Preliminary study interest"). Every field is
    optional for that reason.
    """

    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="study_interest")

    interested_countries = models.JSONField(
        default=list,
        blank=True,
        help_text="List of country names the person is considering.",
    )
    study_level = models.CharField(max_length=30, choices=StudyLevel.choices, blank=True)
    field_of_study = models.CharField(max_length=150, blank=True)
    preferred_intake = models.CharField(
        max_length=50,
        blank=True,
        help_text='Free text at this stage, e.g. "Fall 2026".',
    )
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_currency = models.CharField(max_length=3, blank=True, help_text="ISO 4217 code, e.g. NPR.")
    scholarship_interest = models.BooleanField(default=False)
    highest_qualification = models.CharField(max_length=150, blank=True)
    language_test_status = models.CharField(max_length=20, choices=LanguageTestStatus.choices, blank=True)
    interest_notes = models.TextField(blank=True)

    class Meta:
        db_table = "leads_leadstudyinterest"
        verbose_name = "Lead Study Interest"
        verbose_name_plural = "Lead Study Interests"

    def __str__(self) -> str:
        return f"study_interest<{self.lead_id}>"


class LeadNote(BaseModel):
    """A free-text note explaining where a lead stands.

    Append-only: notes are created and read, never edited or deleted, because a
    Lead Manager "may not delete lead history" (``concepts/leads.txt`` —
    "Permissions"). No update or delete endpoint exists.
    """

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    body = models.TextField()
    author = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="lead_notes_authored",
    )

    class Meta:
        db_table = "leads_leadnote"
        verbose_name = "Lead Note"
        verbose_name_plural = "Lead Notes"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"note<{self.lead_id}:{self.created_at:%Y-%m-%d}>"
