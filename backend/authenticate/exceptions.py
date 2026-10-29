"""Domain exceptions for the authenticate app."""

from authenticate.constants import RefreshRejectReason


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


class NotManageableError(Exception):
    """Raised when a target account does not exist or is outside the actor's authority.

    Deliberately conflates "not found" and "not manageable" so an actor cannot
    enumerate accounts they have no authority over.
    """


class HierarchyViolationError(Exception):
    """Raised when an actor acts on a peer/superior, or on themselves where disallowed."""


class InvalidAuthorityError(Exception):
    """Raised when creating an account with an authority the actor may not create."""


class UsernameTakenError(Exception):
    """Raised when creating an account with an already-used username."""


class SessionNotFoundError(Exception):
    """Raised when a referenced session does not exist or is not in scope."""


class DeviceLimitError(Exception):
    """Raised when a login would exceed the per-user active-device cap."""


class InvalidRefreshTokenError(Exception):
    """Raised when a presented refresh credential is unknown, expired, or revoked.

    ``reason`` is a ``RefreshRejectReason`` or the revoked session's
    ``SessionRevocationReason``; it is returned to the client as
    ``error.details.reason`` and recorded on the ``refresh_rejected`` event.
    """

    def __init__(self, reason: str = RefreshRejectReason.NOT_FOUND) -> None:
        super().__init__(reason)
        self.reason = reason


class RefreshTokenReuseError(Exception):
    """Raised when a retired (already-rotated) refresh token is presented.

    Signals that the whole session family should be revoked.
    """


class ClipboardLimitError(Exception):
    """Raised when an account already holds the maximum number of clipboard entries."""


class ClipboardCategoryLimitError(Exception):
    """Raised when an account already holds the maximum number of clipboard categories."""


class ClipboardCategoryNameTakenError(Exception):
    """Raised when an account already has a clipboard category of that name (any case)."""


class ClipboardCategoryInvalidError(Exception):
    """Raised when an entry names a category that is not one of the caller's own."""
