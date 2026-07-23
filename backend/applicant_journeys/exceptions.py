"""Domain exceptions for the applicant_journeys app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class JourneyNotFoundError(Exception):
    """Raised when a journey does not exist."""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not access journeys.

    Superadmin is a platform authority excluded from consultancy operations.
    """


class InvalidStageTransitionError(Exception):
    """Raised when a stage change targets a stage the dropdown may not set.

    ``closed`` and ``completed`` need the close action with an outcome, and
    ``deferred`` needs the defer action with a target intake.
    """


class StageNotEditableError(Exception):
    """Raised when changing the stage of a completed, closed, or deferred journey.

    Such a journey must be reopened first.
    """


class JourneyNotTerminalError(Exception):
    """Raised when reopening a journey that is already active."""


class OutcomeRequiredError(Exception):
    """Raised when closing a journey without an outcome."""


class OutcomeDetailRequiredError(Exception):
    """Raised when closing with the ``other`` outcome and no explanation."""


class DeferIntakeRequiredError(Exception):
    """Raised when deferring a journey without naming the target intake."""
