"""Business logic for the institutions app.

Services receive already-validated data, own every rule that spans more than
one field, and return model instances — never HTTP responses.

Every mutation appends one event to the central audit log; that log *is* a
catalogue record's history. The concept requires that "if a record changes
later, the previous values should remain visible in history" — that is
delivered by recording a `from`/`to` pair for every changed field, not by
versioning the rows.

There is no delete service. Withdrawal from use is
``availability_status = inactive``, which is an ordinary update.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from django.db import transaction

from institutions.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_CAMPUS,
    AUDIT_ENTITY_COUNTRY,
    AUDIT_ENTITY_FIELD,
    AUDIT_ENTITY_INSTITUTION,
    AUDIT_ENTITY_PROGRAM,
    NOTE_REQUIRED_STATUSES,
    AvailabilityStatus,
    CatalogueAuditAction,
)
from institutions.exceptions import (
    AvailabilityNoteRequiredError,
    CampusInstitutionMismatchError,
    TuitionIncompleteError,
)
from institutions.models import Campus, Country, Field, Institution, Program

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    entity_type: str,
    entity_id: str,
    summary: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one catalogue event to the central audit log."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
        source="api",
    )


def _diff(instance: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply ``fields`` to ``instance`` and return only what actually changed.

    Returning the empty dict when nothing moved is what keeps a no-op PATCH
    from writing a misleading "record updated" event into the history.
    """
    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(instance, name)
        if previous != value:
            changes[name] = {"from": str(previous), "to": str(value)}
            setattr(instance, name, value)
    return changes


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


def assert_availability_explained(status: str, note: str) -> None:
    """A record withdrawn from use must say why.

    Applied on create and on update, against the *resulting* state — patching
    the status alone while an old note sits in the row would otherwise pass.
    """
    if status in NOTE_REQUIRED_STATUSES and not (note or "").strip():
        raise AvailabilityNoteRequiredError(
            "An availability note is required when a record is not active.",
        )


def assert_tuition_complete(
    amount: Decimal | None,
    currency: str,
    fee_period: str,
) -> None:
    """An amount is not a fee until its currency and period are known."""
    if amount is not None and not (currency and fee_period):
        raise TuitionIncompleteError(
            "Recording a tuition amount requires both a currency and a fee period.",
        )


def assert_campus_belongs_to_institution(campus: Campus | None, institution: Institution) -> None:
    """Both FKs resolve individually; only this catches the mismatch."""
    if campus is not None and campus.institution_id != institution.id:
        raise CampusInstitutionMismatchError(
            "The selected campus does not belong to the selected institution.",
        )


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


@transaction.atomic
def create_field(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> Field:
    """Add a study-area classification."""
    field = Field.objects.create(**data)
    _record(
        action=CatalogueAuditAction.FIELD_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_FIELD,
        entity_id=str(field.id),
        summary=f"Study field '{field.name}' created.",
        metadata={"code": field.code},
        ip_address=ip_address,
    )
    return field


@transaction.atomic
def update_field(
    *,
    actor: Any,
    field: Field,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Field:
    """Correct a study field. ``code`` is immutable and never reaches here."""
    changes = _diff(field, fields)
    if changes:
        field.save(update_fields=[*changes.keys(), "updated_at"])
        _record(
            action=CatalogueAuditAction.FIELD_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_FIELD,
            entity_id=str(field.id),
            summary=f"Study field '{field.name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return field


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------


@transaction.atomic
def create_country(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> Country:
    """Add a destination country."""
    assert_availability_explained(
        data.get("availability_status", AvailabilityStatus.ACTIVE),
        data.get("availability_note", ""),
    )
    country = Country.objects.create(**data)
    _record(
        action=CatalogueAuditAction.COUNTRY_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_COUNTRY,
        entity_id=str(country.id),
        summary=f"Country '{country.name}' created.",
        metadata={"code": country.code},
        ip_address=ip_address,
    )
    return country


@transaction.atomic
def update_country(
    *,
    actor: Any,
    country: Country,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Country:
    """Correct a country, including its availability. ``code`` is immutable."""
    assert_availability_explained(
        fields.get("availability_status", country.availability_status),
        fields.get("availability_note", country.availability_note),
    )
    changes = _diff(country, fields)
    if changes:
        country.save(update_fields=[*changes.keys(), "updated_at"])
        _record(
            action=CatalogueAuditAction.COUNTRY_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_COUNTRY,
            entity_id=str(country.id),
            summary=f"Country '{country.name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return country


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------


@transaction.atomic
def create_institution(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> Institution:
    """Add a provider under a country."""
    assert_availability_explained(
        data.get("availability_status", AvailabilityStatus.ACTIVE),
        data.get("availability_note", ""),
    )
    institution = Institution.objects.create(**data)
    _record(
        action=CatalogueAuditAction.INSTITUTION_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_INSTITUTION,
        entity_id=str(institution.id),
        summary=f"Institution '{institution.name}' created.",
        metadata={"country_id": str(institution.country_id)},
        ip_address=ip_address,
    )
    return institution


@transaction.atomic
def update_institution(
    *,
    actor: Any,
    institution: Institution,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Institution:
    """Correct a provider, including its country and availability."""
    assert_availability_explained(
        fields.get("availability_status", institution.availability_status),
        fields.get("availability_note", institution.availability_note),
    )
    changes = _diff(institution, fields)
    if changes:
        institution.save(update_fields=[*changes.keys(), "updated_at"])
        _record(
            action=CatalogueAuditAction.INSTITUTION_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_INSTITUTION,
            entity_id=str(institution.id),
            summary=f"Institution '{institution.name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return institution


# ---------------------------------------------------------------------------
# Campus
# ---------------------------------------------------------------------------


@transaction.atomic
def create_campus(
    *,
    actor: Any,
    institution: Institution,
    data: dict[str, Any],
    ip_address: str | None = None,
) -> Campus:
    """Add a site to a provider. The institution is set here and never changes."""
    assert_availability_explained(
        data.get("availability_status", AvailabilityStatus.ACTIVE),
        data.get("availability_note", ""),
    )
    campus = Campus.objects.create(institution=institution, **data)
    _record(
        action=CatalogueAuditAction.CAMPUS_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_CAMPUS,
        entity_id=str(campus.id),
        summary=f"Campus '{campus.name}' created for {institution.name}.",
        metadata={"institution_id": str(institution.id)},
        ip_address=ip_address,
    )
    return campus


@transaction.atomic
def update_campus(
    *,
    actor: Any,
    campus: Campus,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Campus:
    """Correct a site. ``institution`` is immutable and never reaches here."""
    assert_availability_explained(
        fields.get("availability_status", campus.availability_status),
        fields.get("availability_note", campus.availability_note),
    )
    changes = _diff(campus, fields)
    if changes:
        campus.save(update_fields=[*changes.keys(), "updated_at"])
        _record(
            action=CatalogueAuditAction.CAMPUS_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_CAMPUS,
            entity_id=str(campus.id),
            summary=f"Campus '{campus.name}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return campus


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------


@transaction.atomic
def create_program(*, actor: Any, data: dict[str, Any], ip_address: str | None = None) -> Program:
    """Add a study offering.

    Only institution, title, level, and field are required. The concept
    explicitly allows saving an incomplete record and marking it inactive
    until it is ready for operational use.
    """
    assert_availability_explained(
        data.get("availability_status", AvailabilityStatus.ACTIVE),
        data.get("availability_note", ""),
    )
    assert_campus_belongs_to_institution(data.get("campus"), data["institution"])
    assert_tuition_complete(
        data.get("tuition_amount"),
        data.get("tuition_currency", ""),
        data.get("tuition_fee_period", ""),
    )

    program = Program.objects.create(**data)
    _record(
        action=CatalogueAuditAction.PROGRAM_CREATED,
        actor=actor,
        entity_type=AUDIT_ENTITY_PROGRAM,
        entity_id=str(program.id),
        summary=f"Program '{program.title}' created at {program.institution.name}.",
        metadata={
            "institution_id": str(program.institution_id),
            "qualification_level": program.qualification_level,
        },
        ip_address=ip_address,
    )
    return program


@transaction.atomic
def update_program(
    *,
    actor: Any,
    program: Program,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> Program:
    """Correct a study offering. ``institution`` is immutable.

    Every cross-field rule is checked against the **resulting** state, not the
    incoming patch — a PATCH that clears ``tuition_currency`` while leaving an
    existing amount in place is just as broken as one that sets an amount with
    no currency, and only a resulting-state check catches both.
    """
    assert_availability_explained(
        fields.get("availability_status", program.availability_status),
        fields.get("availability_note", program.availability_note),
    )
    assert_campus_belongs_to_institution(
        fields["campus"] if "campus" in fields else program.campus,
        program.institution,
    )
    assert_tuition_complete(
        fields.get("tuition_amount", program.tuition_amount),
        fields.get("tuition_currency", program.tuition_currency),
        fields.get("tuition_fee_period", program.tuition_fee_period),
    )

    changes = _diff(program, fields)
    if changes:
        program.save(update_fields=[*changes.keys(), "updated_at"])
        _record(
            action=CatalogueAuditAction.PROGRAM_UPDATED,
            actor=actor,
            entity_type=AUDIT_ENTITY_PROGRAM,
            entity_id=str(program.id),
            summary=f"Program '{program.title}' updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return program
