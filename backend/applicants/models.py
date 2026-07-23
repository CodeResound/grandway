"""Data models for the applicants app.

See ``applicants/docs/DATA_CONTRACT.md`` for the authoritative contract.
"""

from __future__ import annotations

from core.constants import ContactNumberLabel
from core.models import BaseModel
from core.validators import validate_contact_number
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from applicants.constants import AddressType, ApplicantStatus, CreationSource, FamilyRelationship, Gender


class Applicant(BaseModel):
    """The permanent, authoritative record of a person the consultancy works with.

    An applicant is the *person*, not a study plan. Everything that varies per
    study objective lives on an applicant journey; everything academic lives in
    the education and test-score modules. This record answers "who is this
    person" and nothing else (``concepts/applicants.txt`` — "Purpose").

    Deliberately **not** owner-scoped: unlike a lead, an applicant is shared
    across the consultancy (see ``access.py`` and ``docs/SECURITY.md`` §1).

    There is no link to the originating lead here. ``leads.Lead`` owns that
    ForeignKey, so this app has no dependency on ``leads`` and works perfectly
    well for an applicant created directly. Read it back via the reverse
    accessor ``applicant.originating_lead``.
    """

    # --- Identity (§39.1 bilingual identity) -------------------------------
    full_name_np = models.CharField(max_length=255)
    full_name_en = models.CharField(max_length=255, blank=True)
    full_name_romanized = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)

    # --- Standing ----------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=ApplicantStatus.choices,
        default=ApplicantStatus.ACTIVE,
        db_index=True,
    )
    creation_source = models.CharField(max_length=20, choices=CreationSource.choices)
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="applicants_created",
        help_text="The Admin who created this applicant, by conversion or directly.",
    )

    class Meta:
        db_table = "applicants_applicant"
        verbose_name = "Applicant"
        verbose_name_plural = "Applicants"
        ordering = ["-created_at"]
        indexes = [
            # The default list view: everyone's applicants, newest first.
            models.Index(fields=["status", "-created_at"], name="applicant_status_recent_idx"),
            # Name search (§39.6). ``search_applicants`` runs a leading-wildcard
            # icontains across all three representations, which a B-tree index
            # cannot serve — hence GIN trigram, one per field.
            GinIndex(fields=["full_name_np"], name="appl_name_np_trgm_idx", opclasses=["gin_trgm_ops"]),
            GinIndex(fields=["full_name_en"], name="appl_name_en_trgm_idx", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["full_name_romanized"],
                name="appl_name_rom_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name_en or self.full_name_np} ({self.status})"

    @property
    def is_archived(self) -> bool:
        return self.status == ApplicantStatus.ARCHIVED

    @property
    def came_from_lead(self) -> bool:
        return self.creation_source == CreationSource.LEAD_CONVERSION


class ApplicantContactNumber(BaseModel):
    """One reachable number for an applicant.

    Same shape and reasoning as ``leads.LeadContactNumber``: a person may give
    several usable numbers but one working email address. Managed nested inside
    the applicant payload, not through its own endpoints.
    """

    applicant = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name="contact_numbers")
    number = models.CharField(max_length=32, validators=[validate_contact_number])
    label = models.CharField(
        max_length=20,
        choices=ContactNumberLabel.choices,
        default=ContactNumberLabel.MOBILE,
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "applicants_applicantcontactnumber"
        verbose_name = "Applicant Contact Number"
        verbose_name_plural = "Applicant Contact Numbers"
        ordering = ["-is_primary", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["applicant", "number"], name="uniq_applicant_contact_number"),
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.label})"


class ApplicantAddress(BaseModel):
    """A permanent or current address.

    Structured for the Nepal context — province, district, municipality, ward —
    but every component is optional, because a file is often started before the
    full address is known. ``street_address`` carries anything the structure
    does not capture.
    """

    applicant = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name="addresses")
    address_type = models.CharField(max_length=20, choices=AddressType.choices)
    country = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    municipality = models.CharField(max_length=150, blank=True)
    ward = models.CharField(max_length=10, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "applicants_applicantaddress"
        verbose_name = "Applicant Address"
        verbose_name_plural = "Applicant Addresses"
        ordering = ["address_type"]
        constraints = [
            models.UniqueConstraint(fields=["applicant", "address_type"], name="uniq_applicant_address_type"),
        ]

    def __str__(self) -> str:
        return f"{self.address_type} address<{self.applicant_id}>"


class PassportDetail(BaseModel):
    """The applicant's current passport.

    One record per applicant: a renewal overwrites it, with the change captured
    in the audit history. Whether old passport numbers need preserving is an
    open question in ``concepts/applicants.txt``.

    ``expiry_date`` is stored rather than derived because an expiring passport
    can block a visa application, and the project anticipates notifications
    driven off this date.
    """

    applicant = models.OneToOneField(Applicant, on_delete=models.CASCADE, related_name="passport")
    passport_number = models.CharField(max_length=50)
    issuing_country = models.CharField(max_length=100, blank=True)
    place_of_issue = models.CharField(max_length=150, blank=True)
    issued_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "applicants_passportdetail"
        verbose_name = "Passport Detail"
        verbose_name_plural = "Passport Details"

    def __str__(self) -> str:
        return f"passport<{self.passport_number}>"


class FamilyMember(BaseModel):
    """One family member of the applicant.

    Kept distinct from ``EmergencyContact``: a person's emergency contact may be
    a friend, landlord, or colleague rather than a relative.
    """

    applicant = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name="family_members")
    relationship = models.CharField(max_length=20, choices=FamilyRelationship.choices)
    full_name_np = models.CharField(max_length=255)
    full_name_en = models.CharField(max_length=255, blank=True)
    occupation = models.CharField(max_length=150, blank=True)
    contact_number = models.CharField(
        max_length=32,
        blank=True,
        validators=[validate_contact_number],
    )

    class Meta:
        db_table = "applicants_familymember"
        verbose_name = "Family Member"
        verbose_name_plural = "Family Members"
        ordering = ["relationship", "created_at"]

    def __str__(self) -> str:
        return f"{self.full_name_en or self.full_name_np} ({self.relationship})"


class EmergencyContact(BaseModel):
    """Who to reach if something goes wrong. Not necessarily a relative."""

    applicant = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name="emergency_contacts")
    full_name_np = models.CharField(max_length=255)
    full_name_en = models.CharField(max_length=255, blank=True)
    relationship = models.CharField(max_length=100, blank=True)
    contact_number = models.CharField(max_length=32, validators=[validate_contact_number])
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    class Meta:
        db_table = "applicants_emergencycontact"
        verbose_name = "Emergency Contact"
        verbose_name_plural = "Emergency Contacts"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.full_name_en or self.full_name_np} ({self.contact_number})"
