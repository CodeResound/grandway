"""Domain exceptions for the authenticate app."""


class ImmutabilityError(Exception):
    """Raised when code attempts to delete or mutate an append-only record.

    ``AuthEvent`` is an append-only audit log; its QuerySet and instance
    ``delete()`` raise this. ``core/management/commands/reset_dev_data.py``
    detects the blocked bulk ``delete()`` and preserves such tables.
    """


class InvalidCredentialsError(Exception):
    """Raised when username/password authentication fails or the account is locked/blocked.

    Deliberately uniform across wrong-password, unknown-user, blocked, and locked
    so no enumeration or lockout signal leaks to the caller.
    """


class PasswordIncorrectError(Exception):
    """Raised when the current password supplied to a password change is wrong."""


class MfaRequiredError(Exception):
    """Raised when a correct password is given but a required TOTP code is missing."""


class MfaInvalidError(Exception):
    """Raised when a supplied TOTP code is wrong or expired."""


class MfaAlreadyEnrolledError(Exception):
    """Raised when enrolling MFA on an account that already has confirmed MFA."""


class MfaNotEnrolledError(Exception):
    """Raised when confirming/disabling MFA that was never enrolled."""


class MfaMandatoryError(Exception):
    """Raised when a superadmin attempts to disable mandatory MFA."""


class DeviceLimitError(Exception):
    """Raised when a login would exceed the per-user active-device cap."""


class InvalidRefreshTokenError(Exception):
    """Raised when a presented refresh credential is unknown, expired, or revoked."""


class RefreshTokenReuseError(Exception):
    """Raised when a retired (already-rotated) refresh token is presented.

    Signals that the whole session family should be revoked.
    """
