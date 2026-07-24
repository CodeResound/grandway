"""Domain exceptions for the offers app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not access offers.

    Superadmin is a platform authority excluded from consultancy operations.
    """


class ProgramReferenceRequiredError(Exception):
    """Raised when an offer names neither a catalogue program nor a manual one.

    An offer that cannot say which program was offered is not a record of
    anything.
    """


class CatalogueReferenceInvalidError(Exception):
    """Raised when the catalogue references do not belong together.

    A campus under a different institution, or a program under a different
    institution, means the client's pickers were not filtered — a UI bug rather
    than user error.
    """


class ReferenceImmutableError(Exception):
    """Raised when an edit targets the journey, catalogue link, or snapshot.

    The concept's central rule: an offer preserves what was true when the
    institution made the decision. Correcting a typo in the recorded program
    title would quietly rewrite history, so the whole reference block is fixed
    at creation.
    """


class AmountIncompleteError(Exception):
    """Raised when a money amount is recorded without its currency.

    A bare number is not a fee. Applies to tuition, scholarship, and deposit
    alike.
    """


class OfferNotIssuableError(Exception):
    """Raised when issuing an offer that is not a draft."""


class OfferNotDecidableError(Exception):
    """Raised when recording a decision on an already-terminal offer.

    Offers are never reopened. A changed institutional position is a new offer,
    which is what keeps the journey's decision trail readable.
    """


class DecisionReasonRequiredError(Exception):
    """Raised when rejecting or withdrawing an offer with no explanation."""


class DeferIntakeRequiredError(Exception):
    """Raised when deferring an offer without naming the target intake."""


class AcceptedOfferExistsError(Exception):
    """Raised when accepting a second offer on a journey that already has one.

    The one multiplicity rule this app enforces: a journey may collect any
    number of competing offers, but only one of them can be the one taken.
    """


class ConditionNoteRequiredError(Exception):
    """Raised when waiving a condition, or marking it not applicable, with no note."""
