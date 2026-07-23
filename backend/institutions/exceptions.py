"""Domain exceptions for the institutions app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not perform this action.

    Superadmin is a platform authority excluded from consultancy operations,
    and catalogue maintenance is Admin-only.
    """


class AvailabilityNoteRequiredError(Exception):
    """Raised when a record is made non-active without stating why.

    A record withdrawn from use with no recorded reason is exactly the drift
    the catalogue exists to prevent.
    """


class CampusInstitutionMismatchError(Exception):
    """Raised when a program's campus belongs to a different institution.

    Both foreign keys resolve individually, so nothing else catches this — it
    would silently place a program at a site that does not host it.
    """


class TuitionIncompleteError(Exception):
    """Raised when a tuition amount is recorded without a currency or fee period.

    An amount alone is unusable in counselling: "49824" is not a fee until it
    is known to be AUD, and per-year rather than per-program.
    """


class DuplicateCampusError(Exception):
    """Raised when an institution already has a campus of the same name."""


class DuplicateCodeError(Exception):
    """Raised when a country or field code is already taken."""
