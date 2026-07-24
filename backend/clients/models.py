"""Data models for the clients app.

See ``clients/docs/DATA_CONTRACT.md`` for the authoritative contract.

Two conventions run through this app and are deliberate:

* **Nothing is ever deleted.** There is no delete endpoint and no delete
  service. A partner the consultancy has stopped working with becomes
  ``inactive`` with a note saying why (``concepts/clients.txt`` — "No deletion
  of historical records. Inactive clients should be retained."), so a lead that
  came through them years ago still resolves to a readable organization.
* **``name`` is the one required identity field**, as everywhere else. Same
  shape as ``leads.ReferenceEntry`` and ``applicants.Applicant``.
"""

from __future__ import annotations

from core.constants import ContactNumberLabel
from core.models import BaseModel
from core.validators import validate_contact_number
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from clients.constants import ClientStatus


class Client(BaseModel):
    """A B2B partner organization that refers or sends applicants.

    A client is a *business*, never a person and never a lead
    (``concepts/clients.txt`` — "Relationship to other records"). The people who
    come through a partner stay person records in ``leads`` and ``applicants``;
    this record exists so those workflows have something to reference instead of
    copying an agency's contact details into every person it sent.

    Deliberately compact. The concept calls this "a reference directory for
    relationship management and operational attribution", not a sales CRM, and
    rules out pipelines, deals, commissions, and multi-contact structures.

    The ``retired_*`` fields are denormalized *current state*, mirroring the
    pattern in ``leads``, ``applicant_journeys``, and ``offers`` (§35 item 15):
    current state is a plain field read, while the append-only audit log remains
    the authoritative event history.
    """

    # --- Identity ----------------------------------------------------------
    name = models.CharField(max_length=255)

    # --- Spokesperson (inline, one person) ---------------------------------
    #
    # A named contact list is explicitly out of scope for V1. One person is what
    # staff actually need — "who do I call at this agency" — and every field is
    # optional, because a partner may be an organization you deal with before
    # you know who to ask for.
    spokesperson_name = models.CharField(max_length=255, blank=True)
    spokesperson_designation = models.CharField(
        max_length=150,
        blank=True,
        help_text='Their role at the client organization, e.g. "Managing Director".',
    )

    # --- Contact -----------------------------------------------------------
    email = models.EmailField(blank=True)
    website = models.URLField(max_length=500, blank=True)
    logo_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="A link to a logo hosted elsewhere. Not an upload — see docs/DATA_CONTRACT.md.",
    )
    address = models.TextField(
        blank=True,
        help_text="One free-text field, not the structured shape applicants uses. The concept asks for small.",
    )

    # --- Standing ----------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=ClientStatus.choices,
        default=ClientStatus.ACTIVE,
        db_index=True,
    )
    status_note = models.TextField(
        blank=True,
        help_text="Why the relationship ended or paused. Required when retiring; cleared on restore.",
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clients_retired",
    )

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "authenticate.User",
        on_delete=models.PROTECT,
        related_name="clients_created",
    )

    class Meta:
        db_table = "clients_client"
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        # A directory reads alphabetically, not newest-first — the opposite of
        # every operational list in this project, because nobody looks up a
        # partner by when it was added.
        ordering = ["name"]
        indexes = [
            # The directory filtered to current partners, in name order.
            models.Index(fields=["status", "name"], name="client_status_name_idx"),
            # The ?search= lookup over the organization and spokesperson names
            # (§39.6). The pg_trgm extension already exists — leads migration 0002.
            GinIndex(fields=["name"], name="client_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        """True when this partner should be offered as a current contact."""
        return self.status == ClientStatus.ACTIVE


class ClientContactNumber(BaseModel):
    """One phone number for a client organization.

    A child table rather than a single inline field because an agency
    realistically has a landline and two mobiles, while it has exactly one
    person you ask for — which is why the spokesperson is inline and the numbers
    are not.

    Managed through the client payload as a complete replacement set, never
    through its own endpoints. Same shape and same handling as
    ``applicants.ApplicantContactNumber``.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contact_numbers")
    number = models.CharField(max_length=32, validators=[validate_contact_number])
    label = models.CharField(
        max_length=20,
        choices=ContactNumberLabel.choices,
        default=ContactNumberLabel.MOBILE,
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "clients_clientcontactnumber"
        verbose_name = "Client Contact Number"
        verbose_name_plural = "Client Contact Numbers"
        ordering = ["-is_primary", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["client", "number"], name="uniq_client_contact_number"),
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.label})"
