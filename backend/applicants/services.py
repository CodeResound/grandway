"""Business logic for the applicants app.

Services receive already-validated data, own every state transition, and return
model instances — never HTTP responses. Multi-table writes run inside
``atomic()``.

``create_applicant`` is this app's public creation path and is called by
``leads`` during conversion (§4: another app imports services, never models).

Every mutation appends one event to the central audit log through
``audit.services.record_event``. That log *is* the applicant's chronological
history; this app owns no history table.
"""

from __future__ import annotations

from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.constants import ContactNumberLabel
from core.nepal.text import normalize_unicode
from django.db import transaction

from applicants.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_APPLICANT,
    ApplicantAuditAction,
    ApplicantStatus,
    CreationSource,
)
from applicants.exceptions import ContactNumberRequiredError, PassportExpiryInvalidError
from applicants.models import (
    Applicant,
    ApplicantAddress,
    ApplicantContactNumber,
    EmergencyContact,
    FamilyMember,
    PassportDetail,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    applicant: Applicant,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one applicants audit event. Never pass secrets or full record dumps."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", ""),
        entity_type=AUDIT_ENTITY_APPLICANT,
        entity_id=str(applicant.id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
    )


def _apply_name_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the applicant's name (§39.2).

    Applied in the service layer as well as the serializer so a direct service
    caller — a management command, a test, a conversion — cannot bypass it.
    """
    if data.get("full_name"):
        data["full_name"] = normalize_unicode(data["full_name"])
    return data


def _replace_contact_numbers(applicant: Applicant, numbers: list[dict[str, Any]]) -> None:
    """Replace an applicant's contact numbers wholesale.

    Replacement rather than per-row patching keeps the write predictable: the
    payload is the complete set the applicant should have afterwards.
    """
    if not numbers:
        raise ContactNumberRequiredError("An applicant needs at least one contact number.")
    applicant.contact_numbers.all().delete()
    ApplicantContactNumber.objects.bulk_create(
        [
            ApplicantContactNumber(
                applicant=applicant,
                number=entry["number"],
                label=entry.get("label") or ContactNumberLabel.MOBILE,
                is_primary=entry.get("is_primary", False),
            )
            for entry in numbers
        ]
    )


def _replace_addresses(applicant: Applicant, addresses: list[dict[str, Any]]) -> None:
    """Replace the applicant's addresses wholesale (at most one per type)."""
    applicant.addresses.all().delete()
    ApplicantAddress.objects.bulk_create([ApplicantAddress(applicant=applicant, **entry) for entry in addresses])


def _replace_family_members(applicant: Applicant, members: list[dict[str, Any]]) -> None:
    applicant.family_members.all().delete()
    FamilyMember.objects.bulk_create(
        [
            FamilyMember(
                applicant=applicant,
                **{**entry, "full_name": normalize_unicode(entry.get("full_name", ""))},
            )
            for entry in members
        ]
    )


def _replace_emergency_contacts(applicant: Applicant, contacts: list[dict[str, Any]]) -> None:
    applicant.emergency_contacts.all().delete()
    EmergencyContact.objects.bulk_create(
        [
            EmergencyContact(
                applicant=applicant,
                **{**entry, "full_name": normalize_unicode(entry.get("full_name", ""))},
            )
            for entry in contacts
        ]
    )


def _upsert_passport(applicant: Applicant, passport: dict[str, Any]) -> None:
    """Create or replace the applicant's current passport."""
    issued = passport.get("issued_date")
    expiry = passport.get("expiry_date")
    if issued and expiry and expiry <= issued:
        raise PassportExpiryInvalidError("Passport expiry must fall after its issue date.")
    PassportDetail.objects.update_or_create(applicant=applicant, defaults=passport)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


@transaction.atomic
def create_applicant(
    *,
    actor: Any,
    data: dict[str, Any],
    contact_numbers: list[dict[str, Any]],
    addresses: list[dict[str, Any]] | None = None,
    family_members: list[dict[str, Any]] | None = None,
    emergency_contacts: list[dict[str, Any]] | None = None,
    passport: dict[str, Any] | None = None,
    creation_source: str = CreationSource.DIRECT_ADMIN,
    ip_address: str | None = None,
) -> Applicant:
    """Create the permanent record of a person.

    This is the app's single creation path, used both by the direct-creation
    endpoint and by ``leads`` during conversion. ``creation_source`` records
    which, so the applicant always remembers how it came to exist.
    """
    data = _apply_name_fields(dict(data))
    applicant = Applicant.objects.create(
        **data,
        created_by=actor,
        creation_source=creation_source,
        status=ApplicantStatus.ACTIVE,
    )

    _replace_contact_numbers(applicant, contact_numbers)
    if addresses:
        _replace_addresses(applicant, addresses)
    if family_members:
        _replace_family_members(applicant, family_members)
    if emergency_contacts:
        _replace_emergency_contacts(applicant, emergency_contacts)
    if passport:
        _upsert_passport(applicant, passport)

    _record(
        action=ApplicantAuditAction.APPLICANT_CREATED,
        actor=actor,
        applicant=applicant,
        summary=f"Applicant '{applicant.full_name}' created.",
        metadata={"creation_source": creation_source},
        ip_address=ip_address,
    )
    return applicant


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@transaction.atomic
def update_applicant(
    *,
    actor: Any,
    applicant: Applicant,
    fields: dict[str, Any],
    contact_numbers: list[dict[str, Any]] | None = None,
    addresses: list[dict[str, Any]] | None = None,
    family_members: list[dict[str, Any]] | None = None,
    emergency_contacts: list[dict[str, Any]] | None = None,
    passport: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> Applicant:
    """Correct an applicant's identity, contact, address, passport, or people.

    ``status`` is deliberately not editable here — it moves only through
    ``change_status``. ``creation_source`` and ``created_by`` are immutable.
    """
    fields = _apply_name_fields(dict(fields))

    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(applicant, field)
        if previous != value:
            changes[field] = {"from": str(previous), "to": str(value)}
            setattr(applicant, field, value)

    if changes:
        applicant.save(update_fields=[*fields.keys(), "updated_at"])
        _record(
            action=ApplicantAuditAction.APPLICANT_UPDATED,
            actor=actor,
            applicant=applicant,
            summary=f"Applicant '{applicant.full_name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )

    if contact_numbers is not None:
        _replace_contact_numbers(applicant, contact_numbers)
        _record(
            action=ApplicantAuditAction.APPLICANT_CONTACT_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Contact numbers updated.",
            metadata={"count": len(contact_numbers)},
            ip_address=ip_address,
        )

    if addresses is not None:
        _replace_addresses(applicant, addresses)
        _record(
            action=ApplicantAuditAction.APPLICANT_ADDRESS_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Addresses updated.",
            metadata={"count": len(addresses)},
            ip_address=ip_address,
        )

    if family_members is not None:
        _replace_family_members(applicant, family_members)
        _record(
            action=ApplicantAuditAction.APPLICANT_FAMILY_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Family members updated.",
            metadata={"count": len(family_members)},
            ip_address=ip_address,
        )

    if emergency_contacts is not None:
        _replace_emergency_contacts(applicant, emergency_contacts)
        _record(
            action=ApplicantAuditAction.APPLICANT_EMERGENCY_CONTACT_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Emergency contacts updated.",
            metadata={"count": len(emergency_contacts)},
            ip_address=ip_address,
        )

    if passport is not None:
        _upsert_passport(applicant, passport)
        _record(
            action=ApplicantAuditAction.APPLICANT_PASSPORT_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Passport information updated.",
            ip_address=ip_address,
        )

    return applicant


def change_status(
    *,
    actor: Any,
    applicant: Applicant,
    status: str,
    ip_address: str | None = None,
) -> Applicant:
    """Set the applicant's standing with the consultancy.

    Always manual. Status is never changed as a side effect of a journey
    opening, closing, or reaching an outcome — the two lifecycles are
    independent (``concepts/applicants.txt`` — "Applicant status").
    """
    previous = applicant.status
    if previous == status:
        return applicant

    applicant.status = status
    applicant.save(update_fields=["status", "updated_at"])
    _record(
        action=ApplicantAuditAction.APPLICANT_STATUS_CHANGED,
        actor=actor,
        applicant=applicant,
        summary=f"Status changed from {previous} to {status}.",
        changes={"status": {"from": previous, "to": status}},
        ip_address=ip_address,
    )
    return applicant
