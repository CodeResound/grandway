"""Model managers for the audit app."""

from __future__ import annotations

from django.db import models

from audit.exceptions import ImmutabilityError


class AuditEventQuerySet(models.QuerySet):
    """Append-only QuerySet: bulk deletion is blocked.

    ``reset_dev_data`` detects that ``delete`` differs from the base QuerySet's
    and preserves the table rather than clearing it.
    """

    def delete(self) -> None:  # type: ignore[override]
        raise ImmutabilityError("AuditEvent is append-only; bulk delete is not allowed.")
