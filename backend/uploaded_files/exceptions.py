"""Domain exceptions for the uploaded_files app.

Services and validators raise these; views translate each into the standard
error envelope (§7). Services never return HTTP responses.

Two groups, and the split matters. ``FileRejectedError`` and its subclasses are
raised *before* anything is written — a rejected upload leaves no row and no
bytes. Everything below it is raised against a record that already exists.
"""


class ActorNotPermittedError(Exception):
    """Raised when the caller's authority type may not perform this action.

    Covers two different refusals, deliberately with one exception: a Superadmin
    touching the app at all, and a Lead Manager attempting a review or archival
    action. Both are "this authority may not do this", and the message carries
    the distinction. See ``access.py``.
    """


class OwnerNotResolvedError(Exception):
    """Raised when the owner reference is absent, ambiguous, or unresolvable.

    A file with no owner is unreachable — nothing lists it and no screen shows
    it. A file with two owners has no answer to "whose archive rule applies".
    Both are the same defect from the caller's side: the request did not name
    exactly one record.
    """


class OwnerNotFoundError(Exception):
    """Raised when the named owner record does not exist.

    Carries ``owner_field`` so the view can put the message under the right key
    in ``error.details`` — a client that sent five possible owner fields needs to
    be told which one failed.
    """

    def __init__(self, owner_field: str, message: str) -> None:
        super().__init__(message)
        self.owner_field = owner_field


class FileRejectedError(Exception):
    """Base for every reason an upload is refused before it is stored."""


class FileTooLargeError(FileRejectedError):
    """Raised when the upload exceeds ``MAX_UPLOAD_BYTES``."""


class FileEmptyError(FileRejectedError):
    """Raised when the upload has no bytes at all.

    Separate from ``FileTooLargeError`` because the two are opposite problems and
    a client mapping one code to "your file is too big" would tell a user their
    empty file was oversized. A zero-byte file is also not merely invalid — it
    would put an unreviewable record in front of a reviewer.
    """


class FileTypeNotAllowedError(FileRejectedError):
    """Raised when the extension is outside the allowlist."""


class FileContentMismatchError(FileRejectedError):
    """Raised when the leading bytes disagree with the extension.

    The check the allowlist cannot make on its own: renaming an executable to
    ``.pdf`` passes an extension test and fails this one.
    """


class FileBytesMissingError(Exception):
    """Raised on download when the row exists but the file is gone from disk.

    Not a client error in any meaningful sense — it means the storage volume and
    the database have diverged. Surfaced as a 404 so nothing is leaked, and
    logged at ``ERROR`` so it is visible to an operator.
    """


class FileArchivedError(Exception):
    """Raised when a write action targets an archived file.

    An archived file must be restored first, so that "archived, then changed" is
    always two visible events rather than a silent amendment. Same rule
    ``documents`` applies to its own archived records.
    """


class AlreadyArchivedError(Exception):
    """Raised when archiving a file that is already archived."""


class NotArchivedError(Exception):
    """Raised when restoring a file that is not archived."""


class AlreadySupersededError(Exception):
    """Raised when replacing a file that has already been replaced.

    The version chain stays linear so "which file is current" always has exactly
    one answer. Also enforced by the ``OneToOne`` on ``replaces`` — this
    exception exists so the caller gets a sentence instead of an
    ``IntegrityError``.
    """


class InvalidVerificationStatusError(Exception):
    """Raised when the verify action targets a status it may not set.

    ``pending`` is a starting state, not a decision; there is no un-review
    action, because "this was reviewed and then un-reviewed" is a claim the
    audit log should make, not the record.
    """


class ReasonRequiredError(Exception):
    """Raised when a rejection or an archival arrives without its reason.

    The two actions that remove a file from ordinary use are the two that must
    explain themselves. ``concepts/project_overview.txt`` — "Any destructive
    action available to an Admin must be deliberate and auditable."
    """


class FieldImmutableError(Exception):
    """Raised when an update targets a field fixed at upload time.

    Everything about the bytes, the owner, and the version chain. Refused rather
    than dropped: a client that re-pointed a file at another applicant and got
    200 back would believe the move happened.
    """
