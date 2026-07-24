"""Domain exceptions for the documents app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not access documents.

    In this app that is everyone except an Admin — Lead Managers and
    Superadmins alike. See ``access.py``.
    """


class OwnerRequiredError(Exception):
    """Raised when a document names neither an applicant nor a standalone purpose.

    ``concepts/documents.txt``: "Standalone documents still need explicit
    ownership and purpose even when no applicant directly owns them."
    """


class OwnershipImmutableError(Exception):
    """Raised when an edit targets the applicant, family, or template key.

    A document's owner and template family are what it *is*. Changing either
    would silently turn one record into a different document while keeping its
    id, history, and any snapshot that referenced it.
    """


class StatusImmutableError(Exception):
    """Raised when an edit tries to set ``status`` directly.

    Status moves through the status, archive, and restore actions, each of
    which records who acted and — for archiving — why.
    """


class TemplateKeyInvalidError(Exception):
    """Raised when the template key is malformed or disagrees with the family.

    ``bank-vyas-statement`` under family ``lor`` is a client bug, not user
    error: the two are chosen together from one template picker.
    """


class ContentInvalidError(Exception):
    """Raised when ``content`` is not a JSON object.

    An array or scalar body would break every template, all of which expect a
    keyed shape.
    """


class ContentTooLargeError(Exception):
    """Raised when the serialized document body exceeds the cap.

    Bank statements carry an unbounded transaction array; this is the only
    thing standing between one document and an unusable row.
    """


class DocumentNotEditableError(Exception):
    """Raised when editing an archived document.

    An archived document is a historical record. It must be restored before it
    can change again, so that "this was archived and then edited" is always two
    visible events rather than a silent amendment.
    """


class InvalidStatusTransitionError(Exception):
    """Raised when the status action targets a status it may not set.

    ``archived`` is reachable only through the archive action, which demands a
    reason.
    """


class ArchiveReasonRequiredError(Exception):
    """Raised when archiving a document without saying why."""


class DocumentAlreadyArchivedError(Exception):
    """Raised when archiving a document that is already archived."""


class DocumentNotArchivedError(Exception):
    """Raised when restoring a document that is not archived."""
