"""Domain exceptions for the notifications app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.

There are only two, and the reason there are so few is the shape of the app: a
client cannot create, edit, or delete a notification, so almost every refusal
this project's other apps make — bad input, illegal transition, missing
precondition — has no path to occur here. What is left is "you may not see
this" and "that has already been dealt with".
"""

from __future__ import annotations


class ActorNotPermittedError(Exception):
    """Raised when the caller may not touch this notification.

    Covers two refusals with one exception on purpose, because they must be
    indistinguishable to the caller: a Superadmin using the feed at all, and any
    user reaching for a notification addressed to somebody else. Splitting them
    would let a caller confirm that a given id exists on another person's feed —
    and a notification title names an applicant and the document they are
    missing.
    """


class AlreadyTerminalError(Exception):
    """Raised when dismissing an alert that is already dismissed or resolved.

    Deliberately not a silent success. Two clients open on the same feed, or one
    client holding a stale list, will otherwise show a notification the server
    considers closed — and the only way that client learns is if the server says
    so rather than returning 200 for a write it did not perform.
    """
