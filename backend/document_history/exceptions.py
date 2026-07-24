"""Domain exceptions for the document_history app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.

Two of these are re-raised from ``documents`` rather than raised here —
``recover_snapshot`` calls that app's ``update_document`` and lets its
``DocumentNotEditableError`` and ``ContentTooLargeError`` propagate. They are
translated in this app's views under this app's error codes, because a consumer
calling a ``/document-history/`` route should never receive a ``DOCUMENTS_*``
code from a route it did not call.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not access document history.

    In this app that is everyone except an Admin — Lead Managers and
    Superadmins alike, matching ``documents``. A snapshot holds the same bank
    balances and account numbers the working document does; freezing it does
    not make it less sensitive. See ``access.py``.
    """


class SnapshotImmutableError(Exception):
    """Raised when anything attempts to alter or remove a stored snapshot.

    ``concepts/document_history.txt`` — "Snapshots are append-only and never
    edited in place", "No editing of existing snapshots", "No deletion of
    historical snapshots". Enforced at the model layer so the Django admin, a
    management command, and a future service all hit the same wall.
    """


class RenderContextInvalidError(Exception):
    """Raised when ``render_context`` is not a JSON object.

    An array or scalar would break every consumer of the snapshot detail view,
    all of which expect a keyed shape.
    """


class RenderContextTooLargeError(Exception):
    """Raised when the serialized render context exceeds the cap.

    A bank statement's frozen per-row running balances grow with the
    transaction array; this is the only thing standing between one print and an
    unusable row.
    """
