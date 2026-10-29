"""Data models for the leads app.

See ``leads/docs/DATA_CONTRACT.md`` for the authoritative contract.
"""

from __future__ import annotations

from core.constants import (
    AcademicScoreType,
    CalendarSystem,
    ContactNumberLabel,
    HighestQualification,
    LanguageTestStatus,
    LanguageTestType,
    NoteCategory,
    StudyLevel,
)
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

    # --- Soft delete (cleared on restore) ----------------------------------
    # A deleted lead is hidden from every list, search, and dashboard figure,
    # visible only to an Admin by id or ``?deleted=true``, and frozen until
    # restored. The row, its notes, and its history are kept — "lead history
    # should not be silently removed" (``concepts/leads.txt``). Admin-only.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads_deleted",
    )
    delete_reason = models.CharField(max_length=500, blank=True)

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

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


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
    # Free text: the programme or stream, e.g. "BBS", "Science". Its level is
    # the enum below; the two together become the applicant's first education
    # record at conversion.
    highest_qualification = models.CharField(max_length=150, blank=True)
    highest_qualification_level = models.CharField(max_length=20, choices=HighestQualification.choices, blank=True)
    # GPA or percentage, always with its type; and the pass year, always with
    # its calendar (a BS year spans two AD years). Pairing and ranges are
    # checked in ``services._assert_study_interest_valid``.
    academic_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    academic_score_type = models.CharField(max_length=20, choices=AcademicScoreType.choices, blank=True)
    pass_year = models.PositiveSmallIntegerField(null=True, blank=True)
    pass_year_calendar = models.CharField(max_length=2, choices=CalendarSystem.choices, blank=True)
    language_test_status = models.CharField(max_length=20, choices=LanguageTestStatus.choices, blank=True)
    interest_notes = models.TextField(blank=True)

    class Meta:
        db_table = "leads_leadstudyinterest"
        verbose_name = "Lead Study Interest"
        verbose_name_plural = "Lead Study Interests"

    def __str__(self) -> str:
        return f"study_interest<{self.lead_id}>"


class LeadNote(BaseModel):
    """A note on where a lead stands — general, or a record of an office visit.

    ``noted_at`` is set by the user, so a note can be backdated (a visit
    written up the next morning); ``created_at`` is when it was saved.

    Editable and deletable by its author or an Admin, but **never erased**:
    every edit and delete appends an audit event, and a delete is soft — the
    row keeps its body and is only hidden from the notes list. That is how
    "a Lead Manager may not delete lead history" (``concepts/leads.txt``)
    survives notes becoming correctable (2026-10-29). Once the lead is
    converted its notes are read-only here; they are copied to the applicant,
    where work continues.
    """

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    category = models.CharField(max_length=20, choices=NoteCategory.choices, default=NoteCategory.GENERAL)
    body = models.TextField()
    noted_at = models.DateTimeField(db_index=True)
    author = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="lead_notes_authored",
    )
    updated_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_notes_updated",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_notes_deleted",
    )

    class Meta:
        db_table = "leads_leadnote"
        verbose_name = "Lead Note"
        verbose_name_plural = "Lead Notes"
        ordering = ["-noted_at", "-created_at"]
        indexes = [
            # The notes panel: one lead's notes, most recent event first.
            models.Index(fields=["lead", "-noted_at"], name="leadnote_lead_noted_idx"),
        ]

    def __str__(self) -> str:
        return f"note<{self.lead_id}:{self.created_at:%Y-%m-%d}>"


class LeadLanguageCertificate(BaseModel):
    """A language-test result the enquirer reports — IELTS, PTE, TOEFL, Duolingo.

    Replaced wholesale with the lead's ``language_certificates`` list, like its
    contact numbers, and capped at ten. Validated by the same rule as an
    applicant's language tests (``core.validators.language_test_errors``),
    because conversion copies each certificate onto the applicant 1:1.
    """

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="language_certificates")
    test_type = models.CharField(max_length=20, choices=LanguageTestType.choices)
    overall_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    listening_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    reading_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    writing_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    speaking_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    test_date = models.DateField(null=True, blank=True)
    certificate_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "leads_leadlanguagecertificate"
        verbose_name = "Lead Language Certificate"
        verbose_name_plural = "Lead Language Certificates"
        ordering = ["-test_date", "created_at"]
        indexes = [
            # The ?language_test_type= list filter: "leads holding an IELTS result".
            models.Index(fields=["test_type", "lead"], name="leadcert_type_lead_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_test_type_display()} {self.overall_score or ''}".strip()
