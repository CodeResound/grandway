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
from authenticate.constants import AuthorityType
from core.constants import ContactNumberLabel, NoteCategory
from core.events import emit
from core.nepal.text import normalize_unicode
from core.validators import (
    academic_score_error,
    language_test_errors,
    note_is_backdated,
    noted_at_is_in_future,
    year_error,
)
from django.db import transaction
from django.utils import timezone

from applicants.access import is_admin, is_lead_manager
from applicants.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_APPLICANT,
    DEFAULT_RESTORE_STATUS,
    ApplicantAuditAction,
    ApplicantStatus,
    CreationSource,
    EducationStatus,
)
from applicants.exceptions import (
    ApplicantArchivedError,
    ApplicantNotArchivedError,
    AssigneeInvalidError,
    AssignmentNotPermittedError,
    ContactNumberRequiredError,
    EducationInvalidError,
    LanguageTestInvalidError,
    NoteBodyRequiredError,
    NoteFutureDateError,
    NoteNotPermittedError,
    PassportExpiryInvalidError,
)
from applicants.models import (
    Applicant,
    ApplicantAddress,
    ApplicantContactNumber,
    ApplicantEducation,
    ApplicantLanguageTest,
    ApplicantNote,
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


#: Identity numbers whose values never reach the audit log — only that they changed.
_REDACTED_IDENTITY_FIELDS = frozenset({"citizenship_no", "national_id_no"})
_REDACTED_MARKER = "<changed>"

#: Free-text fields on the two academic sub-records, normalized on write (§39.2).
_EDUCATION_TEXT = ("qualification", "institution", "country", "grading_system")
_LANGUAGE_TEST_TEXT = ("certificate_number",)


def _normalized(entry: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {**entry, **{f: normalize_unicode(entry[f]).strip() for f in fields if entry.get(f)}}


def _assert_educations_valid(entries: list[dict[str, Any]]) -> None:
    """Cross-field rules for education entries; every failure reported at once.

    A score and its type come together; years need a calendar and a sane range;
    an ongoing qualification has no completion year yet.
    """
    errors: dict[str, str] = {}
    for index, entry in enumerate(entries):
        path = f"educations[{index}]"
        score, score_type = entry.get("score"), entry.get("score_type") or ""
        if (score is None) != (not score_type):
            errors[f"{path}.score_type" if score is not None else f"{path}.score"] = (
                "score and score_type must be given together."
            )
        elif score is not None:
            message = academic_score_error(score_type, score)
            if message:
                errors[f"{path}.score"] = message
        calendar = entry.get("year_calendar") or ""
        start, completion = entry.get("start_year"), entry.get("completion_year")
        if (start is not None or completion is not None) and not calendar:
            errors[f"{path}.year_calendar"] = "Required when a year is given."
        for field, year in (("start_year", start), ("completion_year", completion)):
            message = year_error(year, calendar)
            if message:
                errors[f"{path}.{field}"] = message
        if start is not None and completion is not None and start > completion:
            errors[f"{path}.completion_year"] = "Must not be before start_year."
        if entry.get("completion_status") == EducationStatus.ONGOING and completion is not None:
            errors[f"{path}.completion_year"] = "An ongoing qualification has no completion year."
    if errors:
        raise EducationInvalidError(errors)


def _assert_language_tests_valid(entries: list[dict[str, Any]]) -> None:
    errors: dict[str, str] = {}
    for index, entry in enumerate(entries):
        errors.update(language_test_errors(entry, f"language_tests[{index}]"))
    if errors:
        raise LanguageTestInvalidError(errors)


def _replace_educations(applicant: Applicant, entries: list[dict[str, Any]], source_lead_id: Any = None) -> None:
    """Replace the applicant's education records wholesale. Validate first."""
    applicant.educations.all().delete()
    ApplicantEducation.objects.bulk_create(
        [
            ApplicantEducation(applicant=applicant, source_lead_id=source_lead_id, **_normalized(e, _EDUCATION_TEXT))
            for e in entries
        ]
    )


def _replace_language_tests(applicant: Applicant, entries: list[dict[str, Any]]) -> None:
    """Replace the applicant's language tests wholesale. Validate first."""
    applicant.language_tests.all().delete()
    ApplicantLanguageTest.objects.bulk_create(
        [ApplicantLanguageTest(applicant=applicant, **_normalized(e, _LANGUAGE_TEST_TEXT)) for e in entries]
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
    educations: list[dict[str, Any]] | None = None,
    language_tests: list[dict[str, Any]] | None = None,
    creation_source: str = CreationSource.DIRECT_ADMIN,
    assigned_to: Any = None,
    ip_address: str | None = None,
) -> Applicant:
    """Create the permanent record of a person.

    This is the app's single creation path, used both by the direct-creation
    endpoint and by ``leads`` during conversion. ``creation_source`` records
    which, so the applicant always remembers how it came to exist.

    ``assigned_to`` is set by conversion (the lead's owner) and is quietly
    dropped when that person is no longer an eligible assignee — conversion must
    not fail because the lead's owner left.
    """
    data = _apply_name_fields(dict(data))
    _assert_educations_valid(educations or [])
    _assert_language_tests_valid(language_tests or [])
    applicant = Applicant.objects.create(
        **data,
        created_by=actor,
        creation_source=creation_source,
        status=ApplicantStatus.ACTIVE,
        assigned_to=assigned_to if _is_eligible_assignee(assigned_to) else None,
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
    if educations:
        _replace_educations(applicant, educations)
    if language_tests:
        _replace_language_tests(applicant, language_tests)

    _record(
        action=ApplicantAuditAction.APPLICANT_CREATED,
        actor=actor,
        applicant=applicant,
        summary=f"Applicant '{applicant.full_name}' created.",
        metadata={
            "creation_source": creation_source,
            "assigned_to": str(applicant.assigned_to_id) if applicant.assigned_to_id else None,
        },
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
    educations: list[dict[str, Any]] | None = None,
    language_tests: list[dict[str, Any]] | None = None,
    ip_address: str | None = None,
) -> Applicant:
    """Correct an applicant's identity, contact, address, passport, people, or academics.

    ``status`` is deliberately not editable here — it moves only through
    ``change_status``. ``creation_source`` and ``created_by`` are immutable.
    """
    fields = _apply_name_fields(dict(fields))
    # Validate the collections before writing anything, so a bad score never
    # leaves a half-applied PATCH behind (the transaction would roll back, but
    # failing first keeps the error cheap and the intent obvious).
    _assert_educations_valid(educations or [])
    _assert_language_tests_valid(language_tests or [])

    changes: dict[str, Any] = {}
    for field, value in fields.items():
        previous = getattr(applicant, field)
        if previous != value:
            if field in _REDACTED_IDENTITY_FIELDS:
                # Identity numbers are as sensitive as the passport number, which
                # never enters the audit log either (§17): record that it moved.
                changes[field] = {"from": _REDACTED_MARKER, "to": _REDACTED_MARKER}
            else:
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

    if educations is not None:
        _replace_educations(applicant, educations)
        _record(
            action=ApplicantAuditAction.APPLICANT_EDUCATION_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Education updated.",
            metadata={"count": len(educations)},
            ip_address=ip_address,
        )

    if language_tests is not None:
        _replace_language_tests(applicant, language_tests)
        _record(
            action=ApplicantAuditAction.APPLICANT_LANGUAGE_TESTS_CHANGED,
            actor=actor,
            applicant=applicant,
            summary="Language tests updated.",
            metadata={"count": len(language_tests)},
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

    Archiving goes through here and remembers the status it left. Leaving
    ``archived`` does **not**: that is ``restore_applicant``, an Admin power
    (``concepts/applicants.txt`` — "Archive and restore"), so it raises
    ``ApplicantArchivedError``.
    """
    previous = applicant.status
    if previous == status:
        return applicant
    if applicant.is_archived:
        raise ApplicantArchivedError("This applicant is archived; an Admin must restore them.")

    applicant.status = status
    update_fields = ["status", "updated_at"]
    if status == ApplicantStatus.ARCHIVED:
        applicant.status_before_archive = previous
        update_fields.append("status_before_archive")
    applicant.save(update_fields=update_fields)
    _record(
        action=ApplicantAuditAction.APPLICANT_STATUS_CHANGED,
        actor=actor,
        applicant=applicant,
        summary=f"Status changed from {previous} to {status}.",
        changes={"status": {"from": previous, "to": status}},
        ip_address=ip_address,
    )
    emit(
        "applicant.status_changed",
        actor=actor,
        entity_type="applicant",
        entity_id=applicant.id,
        from_status=previous,
        to_status=status,
    )
    return applicant


def restore_applicant(
    *,
    actor: Any,
    applicant: Applicant,
    reason: str = "",
    ip_address: str | None = None,
) -> Applicant:
    """Bring an archived applicant back to the status they held before. Admin only (view).

    Falls back to ``DEFAULT_RESTORE_STATUS`` for applicants archived before the
    prior status was recorded. Archiving destroyed nothing, so restoring
    recreates nothing — it is a status change with its own audit event.
    """
    if not applicant.is_archived:
        raise ApplicantNotArchivedError("Only an archived applicant can be restored.")

    target = applicant.status_before_archive or DEFAULT_RESTORE_STATUS
    applicant.status = target
    applicant.status_before_archive = ""
    applicant.save(update_fields=["status", "status_before_archive", "updated_at"])
    _record(
        action=ApplicantAuditAction.APPLICANT_RESTORED,
        actor=actor,
        applicant=applicant,
        summary=f"Applicant restored to {target}.",
        reason=normalize_unicode(reason).strip() if reason else "",
        changes={"status": {"from": ApplicantStatus.ARCHIVED, "to": target}},
        ip_address=ip_address,
    )
    emit(
        "applicant.restored",
        actor=actor,
        entity_type="applicant",
        entity_id=applicant.id,
        from_status=ApplicantStatus.ARCHIVED,
        to_status=target,
    )
    return applicant


# ---------------------------------------------------------------------------
# Assignment — who is notified, never who may see
# ---------------------------------------------------------------------------


def _is_eligible_assignee(user: Any) -> bool:
    """An active Admin or Lead Manager. Superadmins do not work files."""
    return (
        user is not None
        and getattr(user, "is_active", False)
        and getattr(user, "authority_type", None) in (AuthorityType.ADMIN, AuthorityType.LEAD_MANAGER)
    )


def assign_applicant(
    *,
    actor: Any,
    applicant: Applicant,
    assignee: Any,
    ip_address: str | None = None,
) -> Applicant:
    """Set or clear the staff member notified about this applicant.

    Routing only — every Admin and Lead Manager keeps full access either way.
    An Admin may assign any eligible person or clear the field. A Lead Manager
    may take an *unassigned* applicant for themselves, or release one they hold;
    nothing else, so one Lead Manager cannot move another's caseload.

    A no-op writes nothing. Archived applicants are frozen here as for notes.
    """
    # Checked in a fixed order — the assignee itself, then the file, then who is
    # asking — so a request with several problems always gets the same answer.
    if assignee is not None and not _is_eligible_assignee(assignee):
        raise AssigneeInvalidError("The assignee must be an active Admin or Lead Manager.")
    if applicant.is_archived:
        raise ApplicantArchivedError("This applicant is archived; an Admin must restore them first.")

    previous_id = applicant.assigned_to_id
    new_id = getattr(assignee, "id", None)
    if is_lead_manager(actor):
        taking = new_id == actor.id and previous_id is None
        releasing = new_id is None and previous_id == actor.id
        if not (taking or releasing or new_id == previous_id):
            raise AssignmentNotPermittedError(
                "A Lead Manager may only take an unassigned applicant or release their own."
            )
    if new_id == previous_id:
        return applicant

    applicant.assigned_to = assignee
    applicant.save(update_fields=["assigned_to", "updated_at"])
    action = ApplicantAuditAction.APPLICANT_ASSIGNED if new_id else ApplicantAuditAction.APPLICANT_UNASSIGNED
    _record(
        action=action,
        actor=actor,
        applicant=applicant,
        summary=f"Assigned to {assignee.username}." if assignee else "Assignment cleared.",
        changes={
            "assigned_to": {
                "from": str(previous_id) if previous_id else None,
                "to": str(new_id) if new_id else None,
            }
        },
        ip_address=ip_address,
    )
    emit(
        "applicant.assigned",
        actor=actor,
        entity_type="applicant",
        entity_id=applicant.id,
        assignee_id=new_id,
        previous_assignee_id=previous_id,
    )
    return applicant


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

#: Audit marker standing in for a note body: the body never reaches the log.
_NOTE_BODY_MARKER = "<changed>"


def _assert_notes_writable(applicant: Applicant) -> None:
    """Notes wait while an applicant is archived; reading them is always fine."""
    if applicant.is_archived:
        raise ApplicantArchivedError("This applicant is archived; restore them before writing notes.")


def _clean_note_body(body: str) -> str:
    cleaned = normalize_unicode(body or "").strip()
    if not cleaned:
        raise NoteBodyRequiredError("A note needs some text.")
    return cleaned


def _check_noted_at(noted_at: Any) -> None:
    if noted_at is not None and noted_at_is_in_future(noted_at):
        raise NoteFutureDateError("A note cannot be dated in the future.")


def _assert_may_change_note(actor: Any, note: ApplicantNote) -> None:
    """Only the author or an Admin may correct or remove a note."""
    if not (is_admin(actor) or note.author_id == getattr(actor, "id", None)):
        raise NoteNotPermittedError("Only the note's author or an Admin may change it.")


def _note_metadata(note: ApplicantNote) -> dict[str, Any]:
    """What the audit log records about a note — never its body (§17)."""
    return {
        "note_id": str(note.id),
        "category": note.category,
        "noted_at": note.noted_at.isoformat(),
        "is_backdated": note_is_backdated(created_at=note.created_at, noted_at=note.noted_at),
    }


def add_note(
    *,
    actor: Any,
    applicant: Applicant,
    body: str,
    category: str = NoteCategory.GENERAL,
    noted_at: Any = None,
    ip_address: str | None = None,
) -> ApplicantNote:
    """Write a note. ``noted_at`` is when it happened (backdatable), defaulting to now."""
    _assert_notes_writable(applicant)
    cleaned = _clean_note_body(body)
    _check_noted_at(noted_at)

    note = ApplicantNote.objects.create(
        applicant=applicant,
        category=category,
        body=cleaned,
        noted_at=noted_at or timezone.now(),
        author=actor,
    )
    _record(
        action=ApplicantAuditAction.APPLICANT_NOTE_ADDED,
        actor=actor,
        applicant=applicant,
        summary=f"{NoteCategory(category).label} note added.",
        metadata=_note_metadata(note),
        ip_address=ip_address,
    )
    emit(
        "applicant.note_added",
        actor=actor,
        entity_type="applicant",
        entity_id=applicant.id,
        note_id=note.id,
        category=note.category,
    )
    return note


def update_note(
    *,
    actor: Any,
    applicant: Applicant,
    note: ApplicantNote,
    fields: dict[str, Any],
    ip_address: str | None = None,
) -> ApplicantNote:
    """Correct a note's category, body, or ``noted_at``. Author or Admin only."""
    _assert_notes_writable(applicant)
    _assert_may_change_note(actor, note)

    if "body" in fields:
        fields = {**fields, "body": _clean_note_body(fields["body"])}
    _check_noted_at(fields.get("noted_at"))

    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(note, name)
        if previous == value:
            continue
        if name == "body":
            changes[name] = {"from": _NOTE_BODY_MARKER, "to": _NOTE_BODY_MARKER}
        elif name == "noted_at":
            changes[name] = {"from": previous.isoformat(), "to": value.isoformat()}
        else:
            changes[name] = {"from": str(previous), "to": str(value)}
        setattr(note, name, value)

    if not changes:
        return note
    note.updated_by = actor
    note.save(update_fields=[*changes.keys(), "updated_by", "updated_at"])
    _record(
        action=ApplicantAuditAction.APPLICANT_NOTE_UPDATED,
        actor=actor,
        applicant=applicant,
        summary="Note edited.",
        changes=changes,
        metadata=_note_metadata(note),
        ip_address=ip_address,
    )
    return note


def delete_note(
    *,
    actor: Any,
    applicant: Applicant,
    note: ApplicantNote,
    ip_address: str | None = None,
) -> ApplicantNote:
    """Hide a note from the notes list. Author or Admin only; the row is kept."""
    _assert_notes_writable(applicant)
    _assert_may_change_note(actor, note)

    note.deleted_at = timezone.now()
    note.deleted_by = actor
    note.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
    _record(
        action=ApplicantAuditAction.APPLICANT_NOTE_DELETED,
        actor=actor,
        applicant=applicant,
        summary="Note deleted.",
        metadata=_note_metadata(note),
        ip_address=ip_address,
    )
    return note


@transaction.atomic
def import_lead_notes(
    *,
    actor: Any,
    applicant: Applicant,
    lead_id: Any,
    notes: list[dict[str, Any]],
    ip_address: str | None = None,
) -> list[ApplicantNote]:
    """Carry a converted lead's notes onto its new applicant. Called by ``leads``.

    Each entry is ``{category, body, noted_at, author, created_at}`` — plain
    values, never a ``leads`` model (§4). The copies keep their author,
    category, and ``noted_at``, and get their original ``created_at`` back
    after insert (``auto_now_add`` would otherwise stamp the conversion time,
    making every carried note look backdated). One audit event for the batch.
    """
    if not notes:
        return []
    created = ApplicantNote.objects.bulk_create(
        [
            ApplicantNote(
                applicant=applicant,
                category=entry["category"],
                body=entry["body"],
                noted_at=entry["noted_at"],
                author=entry["author"],
                source_lead_id=lead_id,
            )
            for entry in notes
        ]
    )
    for note, entry in zip(created, notes, strict=True):
        ApplicantNote.objects.filter(pk=note.pk).update(created_at=entry["created_at"])
        note.created_at = entry["created_at"]
    _record(
        action=ApplicantAuditAction.APPLICANT_NOTES_IMPORTED,
        actor=actor,
        applicant=applicant,
        summary=f"{len(created)} note(s) carried over from the converted lead.",
        metadata={"lead_id": str(lead_id), "count": len(created)},
        ip_address=ip_address,
    )
    return created


# ---------------------------------------------------------------------------
# Lead conversion — called by ``leads`` with plain values, never its models
# ---------------------------------------------------------------------------


def import_lead_qualification(
    *,
    actor: Any,
    applicant: Applicant,
    lead_id: Any,
    education: dict[str, Any],
    ip_address: str | None = None,
) -> ApplicantEducation:
    """Record a converted lead's highest qualification as the applicant's first education entry.

    Validated by the same rules as a hand-entered one, and appended (a freshly
    converted applicant has none). One audit event on the applicant's history.
    """
    _assert_educations_valid([education])
    record = ApplicantEducation.objects.create(
        applicant=applicant, source_lead_id=lead_id, **_normalized(education, _EDUCATION_TEXT)
    )
    _record(
        action=ApplicantAuditAction.APPLICANT_EDUCATION_CHANGED,
        actor=actor,
        applicant=applicant,
        summary="Highest qualification carried over from the converted lead.",
        metadata={"count": 1, "lead_id": str(lead_id)},
        ip_address=ip_address,
    )
    return record


def import_lead_certificates(
    *,
    actor: Any,
    applicant: Applicant,
    lead_id: Any,
    certificates: list[dict[str, Any]],
    ip_address: str | None = None,
) -> list[ApplicantLanguageTest]:
    """Copy a converted lead's language certificates onto the applicant, 1:1.

    The lead validated them with the same ``core`` rule, so this cannot fail on
    data the lead accepted — except a ``test_date`` that has meanwhile become
    valid, which only makes it more acceptable. Nothing is written for an empty list.
    """
    if not certificates:
        return []
    _assert_language_tests_valid(certificates)
    created = ApplicantLanguageTest.objects.bulk_create(
        [
            ApplicantLanguageTest(applicant=applicant, source_lead_id=lead_id, **_normalized(c, _LANGUAGE_TEST_TEXT))
            for c in certificates
        ]
    )
    _record(
        action=ApplicantAuditAction.APPLICANT_LANGUAGE_TESTS_CHANGED,
        actor=actor,
        applicant=applicant,
        summary=f"{len(created)} language test(s) carried over from the converted lead.",
        metadata={"count": len(created), "lead_id": str(lead_id)},
        ip_address=ip_address,
    )
    return created
