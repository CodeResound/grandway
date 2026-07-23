"""Domain exceptions for the leads app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.
"""


class LeadNotFoundError(Exception):
    """Raised when a lead does not exist or is outside the actor's scope.

    Deliberately conflates "does not exist" with "not yours" so a Lead Manager
    cannot probe for the existence of another Lead Manager's leads.
    """


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not act in this app at all.

    Superadmin is a platform authority and is excluded from consultancy
    operations (``concepts/authenticate.txt`` — "Authority structure").
    """


class InvalidStageTransitionError(Exception):
    """Raised when a stage change targets a stage the dropdown may not set.

    ``lost`` requires ``mark_lost`` (a reason is mandatory) and ``converted``
    requires the Admin conversion action.
    """


class StageNotEditableError(Exception):
    """Raised when changing the stage of a lead that is lost or converted.

    Such a lead must be reopened first.
    """


class LeadNotLostError(Exception):
    """Raised when reopening a lead that is neither lost nor converted."""


class LossReasonRequiredError(Exception):
    """Raised when marking a lead lost without a loss reason."""


class LossDetailRequiredError(Exception):
    """Raised when a loss reason marked ``requires_detail`` has no explanation."""


class SourceDetailRequiredError(Exception):
    """Raised when a lead source marked ``requires_detail`` has no description."""


class ReferenceNotFoundError(Exception):
    """Raised when a referenced lead source or loss reason does not exist."""


class ReferenceInactiveError(Exception):
    """Raised when a deactivated lead source or loss reason is selected."""


class ReferenceCodeTakenError(Exception):
    """Raised when creating a lead source or loss reason with a used code."""


class ContactNumberRequiredError(Exception):
    """Raised when a lead is created or updated with no contact number."""


class LeadAlreadyConvertedError(Exception):
    """Raised when converting a lead that already has an applicant.

    Guards the idempotency rule in ``concepts/leads.txt`` — "Conversion must be
    protected against repeated execution."
    """
