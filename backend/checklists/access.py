"""Interim inline access checks for the checklists app (§9).

The split here follows the shape of the work, not the shape of the data:

* **Only an Admin authors a template.** A template is a policy statement — "this
  is what Australia requires of every applicant we send" — and it propagates
  automatically to every future applicant bound for that country. One person
  editing it silently changes what dozens of files are measured against, which
  is authority, not clerical work.
* **Admin and Lead Manager both track.** Collecting a passport scan and ticking
  it off is the Lead Manager's daily job (``concepts/project_overview.txt`` — a
  Lead Manager "maintains checklists"). Routing every tick through an Admin
  would put an approval gate on clerical work, and gates on clerical work get
  worked around.

Superadmin is denied outright, matching ``applicants``, ``applicant_journeys``,
``offers``, and ``uploaded_files``: it is a platform authority that manages Admin
accounts and does not participate in consultancy operations
(``concepts/authenticate.txt``).

Declared locally rather than imported: §4 permits importing another app's
``selectors.py`` and ``services.py``, and ``access.py`` is not on that list. An
access rule silently inherited across a boundary is the coupling that makes a
later divergence invisible.

**Deliberately not owner-scoped.** A Lead Manager may read any checklist, not
only those on applicants assigned to them — inherited from ``applicants``, which
made the same call for the same reason: once a person enters the applicant
lifecycle, several staff legitimately work on their file.

**One thing this module does not gate, and it matters:** a checklist item may
cite an uploaded file as evidence. That reference is validated in
``services.py`` against the checklist's own journey and applicant, not here —
because the question is not "who is asking" but "does this file belong to this
applicant at all", and the answer is the same for an Admin.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from checklists.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def is_lead_manager(user: object) -> bool:
    """True when the user acts with Lead Manager authority."""
    return getattr(user, "authority_type", None) == AuthorityType.LEAD_MANAGER


def require_checklist_actor(user: object) -> None:
    """Allow Admin and Lead Manager — every read, and all checklist and item work."""
    if not (is_admin(user) or is_lead_manager(user)):
        raise ActorNotPermittedError("This authority may not access checklists.")


def require_admin(user: object) -> None:
    """Allow Admin only — authoring and editing templates.

    Checked *after* ``require_checklist_actor`` in every view that needs it, so a
    Superadmin gets the "may not access" message rather than the narrower "Admin
    authority is required", which would imply they are one step away from
    permission they will never have.
    """
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to author checklist templates.")
