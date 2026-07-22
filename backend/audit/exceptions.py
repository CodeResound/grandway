"""Domain exceptions for the audit app."""


class ImmutabilityError(Exception):
    """Raised when code attempts to delete or mutate an append-only audit record.

    ``core/management/commands/reset_dev_data.py`` detects the blocked bulk
    ``delete()`` and preserves the table.
    """
