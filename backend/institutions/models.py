"""Data models for the institutions app.

See ``institutions/docs/DATA_CONTRACT.md`` for the authoritative contract.

Two conventions run through every model here and are deliberate:

* **Nothing is ever deleted.** Every child FK is ``PROTECT`` and no resource has
  a delete endpoint. A record that is no longer offered becomes
  ``inactive`` (``concepts/institutions.txt`` — "No deletion of historical
  catalogue records"), so a journey or offer that referenced it still resolves.
* **Every catalogue record carries one ``name``.** Names are English throughout
  the system; a catalogue of foreign universities is the clearest case for it,
  since these are proper nouns with no second authoritative form.
"""

from __future__ import annotations

from core.constants import StudyLevel
from core.models import BaseModel
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from institutions.constants import (
    USABLE_STATUSES,
    AvailabilityStatus,
    FeePeriod,
    InstitutionType,
)
from institutions.validators import validate_currency_code, validate_reference_code


class AvailabilityMixin(models.Model):
    """Current-offering state, shared by every catalogue record.

    The catalogue's whole reason for existing is to distinguish "we have a
    record of this" from "we can offer this right now". That is one status
    field plus the reason for it — not a separate table, because the question
    asked of it is always about the present.

    Availability never cascades. Pausing a country does not touch its programs;
    search evaluates the whole chain at query time instead. Cascading would
    overwrite each record's own recorded state with no way to restore it.
    """

    availability_status = models.CharField(
        max_length=20,
        choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.ACTIVE,
        db_index=True,
    )
    availability_note = models.TextField(
        blank=True,
        help_text="Why this record is paused, seasonal, or inactive. Required whenever it is not active.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        abstract = True

    @property
    def is_usable(self) -> bool:
        """True when this record may be offered to an applicant today."""
        return self.availability_status in USABLE_STATUSES


class Field(BaseModel):
    """A study-area classification used to group and search programs.

    Admin-managed rather than a fixed enum, because the useful grouping is
    specific to the consultancy's market — unlike ``qualification_level``,
    which reuses ``core.constants.StudyLevel`` so that catalogue and journey
    speak one vocabulary (§3).

    Shaped like ``leads.ReferenceEntry`` but declared independently: §4 forbids
    importing another app's models, and this table carries no ``requires_detail``
    flag.
    """

    code = models.CharField(max_length=50, unique=True, validators=[validate_reference_code])
    name = models.CharField(max_length=150)

    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "institutions_field"
        verbose_name = "Study Field"
        verbose_name_plural = "Study Fields"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Country(BaseModel, AvailabilityMixin):
    """The top-level geographic container, and the first filter in every search."""

    code = models.CharField(max_length=10, unique=True, validators=[validate_reference_code])
    name = models.CharField(max_length=150)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "institutions_country"
        verbose_name = "Country"
        verbose_name_plural = "Countries"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Institution(BaseModel, AvailabilityMixin):
    """A university, college, polytechnic, or similar provider."""

    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="institutions",
    )
    name = models.CharField(max_length=255)
    common_name = models.CharField(
        max_length=150,
        blank=True,
        help_text='What staff actually call it, e.g. "Unimelb".',
    )
    institution_type = models.CharField(
        max_length=20,
        choices=InstitutionType.choices,
        default=InstitutionType.UNIVERSITY,
    )

    class Meta:
        db_table = "institutions_institution"
        verbose_name = "Institution"
        verbose_name_plural = "Institutions"
        ordering = ["name"]
        indexes = [
            # The country-detail screen: providers in one country, usable first.
            models.Index(fields=["country", "availability_status"], name="institution_country_status_idx"),
            # The ?q= search across provider names.
            GinIndex(fields=["name"], name="institution_name_trgm_idx", opclasses=["gin_trgm_ops"]),
            # ``filter_institutions`` matches ``common_name`` in the same OR as
            # ``name``, so leaving it unindexed made the cheaper half of that
            # query decide the cost of the whole thing — and the informal name
            # ("Unimelb") is the one staff actually type (§39.6).
            GinIndex(fields=["common_name"], name="institution_common_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.name


class Campus(BaseModel, AvailabilityMixin):
    """A site of an institution.

    Exists because some institutions price, schedule, or offer programs
    differently by location — not because every institution needs one.
    """

    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        related_name="campuses",
    )
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "institutions_campus"
        verbose_name = "Campus"
        verbose_name_plural = "Campuses"
        ordering = ["name"]
        constraints = [
            # One provider genuinely cannot have two campuses of the same name;
            # here a duplicate is always an error, unlike two same-named
            # institutions in one country, which can both be real.
            models.UniqueConstraint(fields=["institution", "name"], name="campus_institution_name_uniq"),
        ]
        indexes = [
            # The institution-detail screen's campus list.
            models.Index(fields=["institution", "availability_status"], name="campus_institution_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.institution.name} — {self.name}"


class Program(BaseModel, AvailabilityMixin):
    """A specific study offering — the record staff actually shortlist against.

    Tuition, entry expectations, and scholarship availability are inline fields
    rather than related tables in Phase 1. Whether tuition varies by campus,
    intake, or year is still an open question in
    ``concepts/institutions.txt``; answering it by guessing would bake a wrong
    shape into the schema. Promoting these to related tables later is additive.
    """

    # --- Placement ---------------------------------------------------------
    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        related_name="programs",
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.PROTECT,
        related_name="programs",
        null=True,
        blank=True,
        help_text="Optional. Set only when the institution splits programs by campus.",
    )

    # --- Classification ----------------------------------------------------
    title = models.CharField(max_length=255)
    qualification_level = models.CharField(
        max_length=30,
        choices=StudyLevel.choices,
        db_index=True,
        help_text="Same vocabulary as ApplicantJourney.study_level, so the two can be matched directly.",
    )
    field = models.ForeignKey(
        Field,
        on_delete=models.PROTECT,
        related_name="programs",
    )
    duration_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )
    intake_pattern = models.CharField(
        max_length=100,
        blank=True,
        help_text='Free text until intakes are catalogued, e.g. "Feb / Jul".',
    )

    # --- Tuition -----------------------------------------------------------
    tuition_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tuition_currency = models.CharField(max_length=3, blank=True, validators=[validate_currency_code])
    tuition_fee_period = models.CharField(max_length=20, choices=FeePeriod.choices, blank=True)
    tuition_is_indicative = models.BooleanField(
        default=False,
        help_text="True when the figure is an estimate rather than a quoted fee.",
    )
    tuition_notes = models.TextField(
        blank=True,
        help_text="Caveats. The concept asks that both the value and its context be preserved.",
    )

    # --- Entry expectations ------------------------------------------------
    academic_requirement = models.TextField(blank=True)
    english_requirement = models.TextField(blank=True)
    backlog_tolerance = models.TextField(blank=True)
    document_expectation = models.TextField(blank=True)
    selection_notes = models.TextField(blank=True)

    # --- Scholarship -------------------------------------------------------
    scholarship_available = models.BooleanField(default=False)
    scholarship_notes = models.TextField(blank=True)

    class Meta:
        db_table = "institutions_program"
        verbose_name = "Program"
        verbose_name_plural = "Programs"
        ordering = ["title"]
        indexes = [
            # The institution-detail program list.
            models.Index(fields=["institution", "availability_status"], name="program_institution_status_idx"),
            # The shortlisting search's primary filter pair.
            models.Index(fields=["qualification_level", "availability_status"], name="program_level_status_idx"),
            # "All IT programs we can currently offer".
            models.Index(fields=["field", "availability_status"], name="program_field_status_idx"),
            # The ?q= search across program titles.
            GinIndex(fields=["title"], name="program_title_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} — {self.institution.name}"

    @property
    def has_tuition(self) -> bool:
        """True when a usable tuition figure is recorded."""
        return self.tuition_amount is not None
