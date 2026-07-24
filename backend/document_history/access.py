"""Interim inline access checks for the document_history app (§9).

**Admin only — reads included.** Identical to ``documents``, and for the same
reason: a snapshot holds the same bank statement, the same account number, and
the same transaction history the working document does. Freezing a body does
not make it less sensitive, so the app that stores the frozen copies cannot be
more open than the app that stores the original.

``concepts/document_history.txt`` — Constraints: "No Lead Manager access if the
project keeps document data restricted to Admins only, which is the current
direction of the documents app." It does, so this is that.

**Declared here rather than imported from ``documents.access``.** §4 permits
importing another app's ``selectors.py`` and ``services.py``; ``access.py`` is
not on that list, and an access rule silently inherited across a boundary is
exactly the kind of coupling that makes a later divergence invisible. This is
the call ``documents.validators`` already made about ``institutions``.

Consequence for clients: every document-history screen must be **hidden** for a
Lead Manager, not rendered read-only — the same rule as the documents workspace.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from document_history.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def require_document_history_actor(user: object) -> None:
    """Allow Admin only — every read and every write.

    One helper rather than a reader/writer pair, because there is no split to
    express: the read population and the write population are the same set of
    one.
    """
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to access document history.")
