"""Business logic for the clients app.

Services receive already-validated data, own every rule that spans more than one
field, and return model instances — never HTTP responses.

Every mutation appends one event to the central audit log; that log *is* a
client's history. The concept asks that "if a detail changes, the previous value
should remain traceable through the normal audit history" — that is delivered by
recording a ``from``/``to`` pair for every changed field, not by versioning rows.

There is no delete service. Withdrawal from use is ``retire_client``, which sets
``status = inactive`` and records why.
"""

from __future__ import annotations

from typing import Any

from audit.constants import ActorType
from audit.services import record_event
from core.nepal.text import normalize_unicode, romanize_devanagari
from django.db import transaction
from django.utils import timezone

from clients.constants import (
    AUDIT_APP_LABEL,
    AUDIT_ENTITY_CLIENT,
    ClientAuditAction,
    ClientStatus,
)
from clients.exceptions import (
    ClientAlreadyRetiredError,
    ClientNotRetiredError,
    ContactNumberDuplicateError,
    StatusNoteRequiredError,
)
from clients.models import Client, ClientContactNumber

_ACTOR_TYPES = {ActorType.SUPERADMIN, ActorType.ADMIN, ActorType.LEAD_MANAGER}

#: The Devanagari-primary name fields and where each derives its search form.
#: Declared once so the organization name and the spokesperson name can never
#: drift into being handled differently.
_ROMANIZED_PAIRS: tuple[tuple[str, str], ...] = (
    ("name_np", "name_romanized"),
    ("spokesperson_name_np", "spokesperson_name_romanized"),
)


def _actor_type(actor: Any) -> str:
    authority = getattr(actor, "authority_type", None)
    return authority if authority in _ACTOR_TYPES else ActorType.SYSTEM


def _record(
    *,
    action: str,
    actor: Any,
    client: Client,
    summary: str = "",
    reason: str = "",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append one client audit event. Never pass secrets or full record dumps."""
    record_event(
        app_label=AUDIT_APP_LABEL,
        action=action,
        actor_type=_actor_type(actor),
        actor_id=str(actor.id) if getattr(actor, "id", None) else None,
        actor_label=getattr(actor, "username", "") or "",
        entity_type=AUDIT_ENTITY_CLIENT,
        entity_id=str(client.id),
        reason=reason,
        summary=summary,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=ip_address,
        source="api",
    )


def _diff(instance: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply ``fields`` to ``instance`` and return only what actually changed.

    Returning the empty dict when nothing moved is what keeps a no-op PATCH from
    writing a misleading "record updated" event into the history.
    """
    changes: dict[str, Any] = {}
    for name, value in fields.items():
        previous = getattr(instance, name)
        if previous != value:
            changes[name] = {"from": str(previous), "to": str(value)}
            setattr(instance, name, value)
    return changes


def _apply_name_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize each Devanagari name and derive its romanized form (§39.1/§39.3).

    Computed in the service layer — never in a model or signal — and only when
    the caller has not supplied one, so a hand-corrected transliteration
    ("Griha" over the generated "grha") survives a later edit.
    """
    for source, target in _ROMANIZED_PAIRS:
        if data.get(source):
            data[source] = normalize_unicode(data[source])
            if not data.get(target):
                data[target] = romanize_devanagari(data[source])
    return data


def _replace_contact_numbers(client: Client, numbers: list[dict[str, Any]]) -> None:
    """Replace a client's contact numbers wholesale.

    Replacement rather than per-row patching keeps the write predictable: the
    payload is the complete set the client should have afterwards. Same
    handling as ``applicants``.
    """
    seen: set[str] = set()
    for entry in numbers:
        number = entry.get("number", "")
        if number in seen:
            raise ContactNumberDuplicateError(f"The number {number} is listed more than once for this client.")
        seen.add(number)

    client.contact_numbers.all().delete()
    for entry in numbers:
        ClientContactNumber.objects.create(client=client, **entry)


# ---------------------------------------------------------------------------
# Creation and editing
# ---------------------------------------------------------------------------


@transaction.atomic
def create_client(
    *,
    actor: Any,
    data: dict[str, Any],
    contact_numbers: list[dict[str, Any]] | None = None,
    ip_address: str | None = None,
) -> Client:
    """Add a partner organization to the directory."""
    data = _apply_name_fields(dict(data))
    client = Client.objects.create(created_by=actor, status=ClientStatus.ACTIVE, **data)

    if contact_numbers:
        _replace_contact_numbers(client, contact_numbers)

    _record(
        action=ClientAuditAction.CLIENT_CREATED,
        actor=actor,
        client=client,
        summary=f"Client '{client.name_np}' added to the directory.",
        metadata={"contact_number_count": len(contact_numbers or [])},
        ip_address=ip_address,
    )
    return client


@transaction.atomic
def update_client(
    *,
    actor: Any,
    client: Client,
    fields: dict[str, Any],
    contact_numbers: list[dict[str, Any]] | None = None,
    ip_address: str | None = None,
) -> Client:
    """Correct a client's identity, contact details, or notes.

    ``status`` is deliberately not editable here — it moves only through
    ``retire_client`` and ``restore_client``, which record who did it and why.
    One field, one path.

    ``contact_numbers`` is replace-wholesale and is treated as a change in its
    own right: passing an empty list clears them, which is different from
    passing ``None`` (leave them alone).
    """
    fields = _apply_name_fields(dict(fields))
    changes = _diff(client, fields)

    if changes:
        client.save(update_fields=[*fields.keys(), "updated_at"])

    if contact_numbers is not None:
        _replace_contact_numbers(client, contact_numbers)
        changes["contact_numbers"] = {"from": "replaced", "to": f"{len(contact_numbers)} number(s)"}

    if changes:
        _record(
            action=ClientAuditAction.CLIENT_UPDATED,
            actor=actor,
            client=client,
            summary="Client details updated.",
            changes=changes,
            ip_address=ip_address,
        )
    return client


# ---------------------------------------------------------------------------
# Standing
# ---------------------------------------------------------------------------


@transaction.atomic
def retire_client(
    *,
    actor: Any,
    client: Client,
    reason: str,
    ip_address: str | None = None,
) -> Client:
    """Withdraw a partner from current use without deleting anything.

    The reason is mandatory. Inactive clients are kept forever, so "why is this
    one inactive" has to be answerable from the record rather than from someone
    remembering how the relationship ended.
    """
    if client.status == ClientStatus.INACTIVE:
        raise ClientAlreadyRetiredError("This client is already retired.")
    if not (reason or "").strip():
        raise StatusNoteRequiredError("Retiring a client requires a reason.")

    client.status = ClientStatus.INACTIVE
    client.status_note = normalize_unicode(reason)
    client.retired_at = timezone.now()
    client.retired_by = actor
    client.save(update_fields=["status", "status_note", "retired_at", "retired_by", "updated_at"])

    _record(
        action=ClientAuditAction.CLIENT_RETIRED,
        actor=actor,
        client=client,
        summary=f"Client '{client.name_np}' retired.",
        reason=reason,
        changes={"status": {"from": ClientStatus.ACTIVE, "to": ClientStatus.INACTIVE}},
        ip_address=ip_address,
    )
    return client


@transaction.atomic
def restore_client(
    *,
    actor: Any,
    client: Client,
    ip_address: str | None = None,
) -> Client:
    """Return a retired partner to current use.

    Clears the retirement state but not the history — the fact that the
    relationship once ended stays in the audit log, which is where someone
    asking "have we worked with them before?" will look.
    """
    if client.status != ClientStatus.INACTIVE:
        raise ClientNotRetiredError("Only a retired client can be restored.")

    client.status = ClientStatus.ACTIVE
    client.status_note = ""
    client.retired_at = None
    client.retired_by = None
    client.save(update_fields=["status", "status_note", "retired_at", "retired_by", "updated_at"])

    _record(
        action=ClientAuditAction.CLIENT_RESTORED,
        actor=actor,
        client=client,
        summary=f"Client '{client.name_np}' restored to active use.",
        changes={"status": {"from": ClientStatus.INACTIVE, "to": ClientStatus.ACTIVE}},
        ip_address=ip_address,
    )
    return client
