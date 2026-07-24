"""Domain exceptions for the document_templates app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.

``TemplateKeyInvalidError`` is deliberately **not** declared here — the
family/slug agreement rule is imported wholesale from ``documents.services``,
and so is the exception it raises. Declaring a second exception for the same
rule would let the two apps disagree about what a valid key is, which is the
exact drift §4 exists to prevent.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not access this app.

    Everyone except an Admin — Lead Managers and Superadmins alike, matching
    ``documents`` and ``document_history``. See ``access.py``.
    """


class TemplateKeyAlreadyExistsError(Exception):
    """Raised when a template key is already registered.

    The key is the catalogue's identity and the string every document stores.
    Two rows claiming ``bank-vyas-statement`` would make "which template is
    this document using" unanswerable.
    """


class TemplateKeyImmutableError(Exception):
    """Raised when an edit targets a template's key.

    Documents point at the key as a plain string with no foreign key behind it,
    so renaming one here would silently orphan every document that used it —
    with nothing in the database to notice.
    """


class InvalidStatusTransitionError(Exception):
    """Raised when the status action targets a status outside the enum."""
