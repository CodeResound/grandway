"""Enums, error codes, and audit-action names for the clients app.

``ContactNumberLabel`` is not defined here — it is shared with ``leads`` and
``applicants`` and lives in ``core.constants`` (§2/§3). A client's phone numbers
are labelled from the same vocabulary a person's are, because the question
"which of these do I call" is the same question.
"""

from django.db import models


class ClientStatus(models.TextChoices):
    """Whether the consultancy currently works with this partner.

    **Two values, not three.** ``concepts/clients.txt`` asks whether a separate
    ``paused`` or ``archived`` distinction is needed; it is not, because in V1
    nothing branches on one. The only behaviour attached to status is whether
    the directory presents a partner as a current contact, and that is binary.
    The nuance a ``paused`` value would have carried — *why* the relationship
    is dormant — is carried better by the mandatory ``status_note``, which says
    it in words instead of encoding it in an enum nothing reads.

    This is the opposite call from ``institutions.AvailabilityStatus``, which
    genuinely needs four values because its program search filters on them.
    """

    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class ClientAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    CLIENT_CREATED = "client_created"
    CLIENT_UPDATED = "client_updated"
    CLIENT_RETIRED = "client_retired"
    CLIENT_RESTORED = "client_restored"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "clients"

#: ``audit.AuditEvent.entity_type`` value.
#:
#: Contact-number changes are recorded against the **client**, not the number,
#: because numbers are replaced wholesale through the client payload and have
#: no identity a reader would recognise on its own.
AUDIT_ENTITY_CLIENT = "client"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the clients app (§7)."""

    ACTOR_FORBIDDEN = "CLIENTS_ACTOR_FORBIDDEN"

    CLIENT_NOT_FOUND = "CLIENTS_CLIENT_NOT_FOUND"

    STATUS_NOTE_REQUIRED = "CLIENTS_STATUS_NOTE_REQUIRED"
    STATUS_IMMUTABLE = "CLIENTS_STATUS_IMMUTABLE"
    CLIENT_ALREADY_RETIRED = "CLIENTS_CLIENT_ALREADY_RETIRED"
    CLIENT_NOT_RETIRED = "CLIENTS_CLIENT_NOT_RETIRED"
    CONTACT_NUMBER_DUPLICATE = "CLIENTS_CONTACT_NUMBER_DUPLICATE"
