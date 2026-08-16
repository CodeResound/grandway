"""Domain exceptions for the reminders app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not access reminders.

    Superadmin is a platform authority excluded from consultancy operations,
    matching every other operational app.
    """


class OwnerNotResolvedError(Exception):
    """Raised when the owner reference is absent or ambiguous.

    A reminder with no owner is unreachable — no record panel would ever show
    it — and one with two owners has no answer to "whose follow-up is this".
    Both are the same defect from the caller's side: the request did not name
    exactly one record.
    """


class OwnerNotFoundError(Exception):
    """Raised when the named owner record does not exist.

    Carries ``owner_field`` so the view can put the message under the right
    key in ``error.details``.
    """

    def __init__(self, owner_field: str, message: str) -> None:
        super().__init__(message)
        self.owner_field = owner_field


class ReminderAlreadyClosedError(Exception):
    """Raised when acting on a completed or dismissed reminder.

    Terminal states are final — the concept replaces reopening with creating a
    new reminder, so a late update, complete, or dismiss is a conflict, not a
    correction.
    """
