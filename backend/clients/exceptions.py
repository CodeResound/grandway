"""Domain exceptions for the clients app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not perform the action.

    Covers two distinct refusals, distinguished by the message: a Lead Manager
    attempting a write, and a Superadmin attempting anything.
    """


class StatusNoteRequiredError(Exception):
    """Raised when retiring a client without saying why.

    The directory keeps inactive partners forever, so "why is this one
    inactive" has to be answerable from the record rather than from someone's
    memory of the relationship.
    """


class ClientAlreadyRetiredError(Exception):
    """Raised when retiring a client that is already inactive."""


class ClientNotRetiredError(Exception):
    """Raised when restoring a client that is already active."""


class ContactNumberDuplicateError(Exception):
    """Raised when one client is given the same number twice."""
