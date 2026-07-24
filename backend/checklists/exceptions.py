"""Domain exceptions for the checklists app.

Services raise these; views translate each into the standard error envelope
(§7). Services never return HTTP responses.

Two groups. Everything above ``ChecklistArchivedError`` is a refusal to *author*
something — a bad template, a duplicate default, a second copy of a checklist
that already exists. Everything below is a refusal to *move* a record that
already exists into a state it cannot legally reach.
"""

from __future__ import annotations


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not perform this action.

    Covers both refusals this app makes with one exception, the message carrying
    the distinction: a Superadmin touching the module at all, and a Lead Manager
    attempting to author a template. See ``access.py``.
    """


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------


class DefaultTemplateExistsError(Exception):
    """Raised when a country already has an active default template.

    Carries the conflicting template so the view can name it. Without that, an
    Admin is told "there is already a default" and left to search for it.
    """

    def __init__(self, existing: object, message: str) -> None:
        super().__init__(message)
        self.existing = existing


class DefaultRequiresCountryError(Exception):
    """Raised when a template is marked default without naming a country.

    A default exists to answer "which checklist does *this country* inherit".
    Without a country it answers nothing and can never be inherited by anyone.
    """


class TemplateNotActiveError(Exception):
    """Raised when a draft or inactive template is applied to a journey.

    A draft is half-written by definition; an inactive one was retired on
    purpose. Instantiating either would put a list in front of staff that
    nobody stands behind.
    """


class TemplateAlreadyAppliedError(Exception):
    """Raised when this journey already holds a live checklist from this template.

    Not an error the automation ever hits — the signal checks first and does
    nothing. It exists for the manual apply route, where a second copy would
    split one applicant's progress across two lists with no way to tell which is
    authoritative.
    """


class TemplateHasNoItemsError(Exception):
    """Raised when a template with no active items is applied.

    An empty checklist is worse than no checklist: it reads as "nothing is
    required of this applicant", which is never what an author meant.
    """


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class ChecklistArchivedError(Exception):
    """Raised when an archived checklist is edited. Restore it first."""


class ChecklistNotArchivedError(Exception):
    """Raised when restore is called on a checklist that is not archived."""


class InvalidTransitionError(Exception):
    """Raised when a lifecycle action does not apply from the current state.

    One exception for every such refusal rather than one per transition: the
    client's remedy is identical in each case — read the current ``status`` and
    choose a different action.
    """


class RequiredItemsPendingError(Exception):
    """Raised when completion is attempted while required work is unresolved.

    Carries the offending items so the view can list them. "Something is still
    pending" on a forty-item checklist is not an answer anyone can act on.
    """

    def __init__(self, items: list[object], message: str) -> None:
        super().__init__(message)
        self.items = items


class StatusNoteRequiredError(Exception):
    """Raised when a waived or blocked item carries no explanation.

    Both are judgements someone will be asked about months later — by the
    applicant, by an institution, or by whoever inherits the file.
    """


class ArchiveReasonRequiredError(Exception):
    """Raised when a checklist is archived with no reason given."""


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceNotAllowedError(Exception):
    """Raised when the attached file does not belong to this applicant.

    The one check that stops this module from becoming a way to cite somebody
    else's passport as proof — and, because a file owned by a document or a
    print snapshot is never owned by a journey or an applicant, the same check
    keeps a Lead Manager from reaching material the documents app holds
    Admin-only.
    """
