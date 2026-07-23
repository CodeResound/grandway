"""Domain exceptions for the applicants app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class ApplicantNotFoundError(Exception):
    """Raised when an applicant does not exist."""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not perform the action.

    Superadmin is a platform authority excluded from consultancy operations;
    creating an applicant is additionally Admin-only.
    """


class ContactNumberRequiredError(Exception):
    """Raised when an applicant is left with no contact number."""


class PassportExpiryInvalidError(Exception):
    """Raised when a passport's expiry date is not after its issue date."""
