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


class ApplicantArchivedError(Exception):
    """Raised when writing to an archived applicant through a path that may not unarchive it.

    Moving out of ``archived`` is the Admin-only restore action; note writes
    wait until the applicant is restored.
    """


class ApplicantNotArchivedError(Exception):
    """Raised when restoring an applicant that is not archived."""


class NoteFutureDateError(Exception):
    """Raised when a note's ``noted_at`` is later than now (beyond clock skew)."""


class NoteBodyRequiredError(Exception):
    """Raised when a note body is blank once normalized."""


class NoteNotPermittedError(Exception):
    """Raised when someone other than the author or an Admin edits or deletes a note."""


class EducationInvalidError(Exception):
    """Raised when an education entry breaks a cross-field rule. ``fields`` maps ``educations[i].field`` to a message."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("One or more education entries are invalid.")
        self.fields = fields


class LanguageTestInvalidError(Exception):
    """Raised when a language-test entry breaks a rule. ``fields`` maps ``language_tests[i].field`` to a message."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("One or more language tests are invalid.")
        self.fields = fields


class AssigneeInvalidError(Exception):
    """Raised when the chosen assignee is not an active Admin or Lead Manager."""


class AssignmentNotPermittedError(Exception):
    """Raised when a Lead Manager assigns someone else, or takes an applicant someone else holds."""
