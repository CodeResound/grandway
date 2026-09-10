"""Interim inline access checks for the uploaded_files app (§9).

**This is the first app in the project to split the write population from the
review population**, and the split is the whole point of the module.

Two rules:

* **Admin and Lead Manager may list, read, upload, replace, and download.**
  ``concepts/project_overview.txt`` — the Lead Manager "manages documents and
  files". They are the person who sits with the applicant and receives the
  passport scan; an app that made them ask an Admin to attach it would push a
  daily clerical act through an authority gate and get worked around.
* **Admin only may verify, reject, archive, and restore.** These are the four
  actions that decide whether a file is *trusted* or whether it leaves active
  use. Letting the uploader also be the reviewer would make
  ``verification_status`` a record of who uploaded it rather than of anyone's
  judgement, which is the one thing the field exists to avoid.

Superadmin is denied outright, matching ``applicants``, ``applicant_journeys``,
and ``offers``: it is a platform authority that manages Admin accounts and does
not participate in consultancy operations (``concepts/authenticate.txt``).

**Deliberately not owner-scoped.** A Lead Manager may read any file, not only
files on applicants assigned to them — inherited from ``applicants``, which made
the same call for the same reason: once a person enters the applicant lifecycle
several staff legitimately work on their file. This is the most sensitive data
in the project, so the decision is recorded rather than assumed, in
``docs/SECURITY.md`` §2.

Declared locally rather than imported from ``applicants.access``: §4 permits
importing another app's ``selectors.py`` and ``services.py``, and ``access.py``
is not on that list. An access rule silently inherited across a boundary is the
coupling that makes a later divergence invisible.

**A file inherits the visibility of the record it belongs to.** A file owned by a
``document``, a ``document_snapshot``, or a ``signatory`` is Admin-only, because
``documents``, ``document_history``, and ``document_templates`` are Admin-only on
every route, reads included. Without that rule this module would be a side door
around another module's access decision: a Lead Manager who cannot open a bank
statement could list and download the PDF attached to it, and neither module
would know. Found by the §19.5 consumer-comprehension review, not by design — the
flat "Admin + Lead Manager for reads" rule looked correct until someone asked
what a `document`-owned file was.

``signatory`` joined the rule when signature images became uploadable. Note that
it is **not** there because a signature is sensitive applicant data — it is not
applicant data at all. It is there because the owning app refuses a Lead Manager
outright, and because a signature image is the most forgeable artefact in the
system: it is what makes an issued certificate look authoritative, so read access
to the bytes is a larger ask than read access to the signatory row, not a
smaller one.

The rule is enforced in three places, because a file can be reached three ways:
per-file routes check the resolved file's owner, the upload route checks the
owner it is about to attach to, and the list selector excludes restricted rows
for a non-Admin so they never appear in a page at all.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from uploaded_files.constants import ADMIN_ONLY_OWNER_TYPES
from uploaded_files.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_file_actor(user: object) -> None:
    """Allow Admin and Lead Manager — list, read, upload, replace, download."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access uploaded files.")


def require_admin(user: object) -> None:
    """Allow Admin only — verify, reject, archive, restore.

    Checked *after* ``require_file_actor`` in every view that needs it, so a
    Superadmin gets the "may not access" message rather than the narrower
    "Admin authority is required", which would imply they are one step away from
    permission they will never have.
    """
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to review, archive, or restore a file.")


def require_owner_visibility(user: object, owner_type: str | None) -> None:
    """Refuse a non-Admin access to a file whose owning record is Admin-only.

    A file owned by a ``document``, a ``document_snapshot``, or a ``signatory``
    inherits those modules' Admin-only rule. Applied on read, download, update,
    and replace of an existing file, and on upload against such an owner.

    ``owner_type`` is ``None`` only for an unsaved instance, which no caller
    here holds; it is permitted rather than refused so this never becomes a
    confusing failure on a code path that cannot occur in a request.
    """
    if owner_type in ADMIN_ONLY_OWNER_TYPES and not is_admin(user):
        raise ActorNotPermittedError(
            "Admin authority is required for files belonging to a document, " "a print snapshot, or a signatory."
        )
