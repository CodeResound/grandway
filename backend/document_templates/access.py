"""Interim inline access checks for the document_templates app (§9).

**Admin only — reads included.** The third app in the project to refuse a Lead
Manager outright, after ``documents`` and ``document_history``, and the one
where that rule is least obviously about the data.

Nothing here is sensitive. A signatory is a staff member's name and a link to
their signature image; a template is a slug and a label. There is **no applicant
data in this app at all** — it is the only module in the document stack that
holds none.

The rule is inherited from the consumer, not the content:
``concepts/document_templates.txt`` — "No Lead Manager maintenance access in V1
if the rest of the document stack is Admin-only, which is the current
direction." It is. A Lead Manager cannot open a document workspace, so the
signatory picker and the template list are screens they can never reach; giving
them read access would grant sight of a library they have no way to use.

**This is a judgement, not a data-classification.** If Lead Managers are ever
given document access, this app should follow in the same change rather than
being re-argued from scratch — which is why the reasoning is recorded here
rather than left implicit.

Declared locally rather than imported from ``documents.access``: §4 permits
importing another app's ``selectors.py`` and ``services.py``, and ``access.py``
is not on that list. An access rule silently inherited across a boundary is
exactly the coupling that makes a later divergence invisible — and this app's
rule rests on different reasoning from ``documents``', even though the two
currently agree.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from document_templates.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def require_template_actor(user: object) -> None:
    """Allow Admin only — every read and every write.

    One helper rather than the reader/writer pair ``institutions`` and
    ``clients`` declare, because there is no split to express: the read
    population and the write population are the same set of one.
    """
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to access document templates.")
