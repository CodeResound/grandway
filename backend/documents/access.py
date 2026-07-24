"""Interim inline access checks for the documents app (§9).

**Admin only — reads included.** This is the strictest access model in the
project, and the first where a Lead Manager is denied outright rather than
merely restricted to reads:

| App | Lead Manager reads | Lead Manager writes |
|-----|--------------------|---------------------|
| ``applicants``, ``applicant_journeys``, ``offers`` | yes | yes |
| ``institutions``, ``clients`` | yes | no |
| ``documents`` | **no** | **no** |

Documents hold the most sensitive material in Grandway. A single record may
carry a bank statement with an account number, balance, and full transaction
history; a passport-derived declaration; or family financial affidavits.
``concepts/project_overview.txt`` — "Privacy by default" — names exactly this
class of data, and its open question "Which sensitive fields or files should be
hidden from Lead Managers by default?" is answered here for this app: all of it.

**This deliberately departs from ``concepts/documents.txt``,** whose flow 1 says
"An Admin or Lead Manager opens an applicant record". The narrower rule was set
by the project owner after the concept was written and supersedes it (§36 —
concept files are a living draft, not a rulebook). The concept file carries a
correction note; ``docs/SECURITY.md`` §1 carries the reasoning.

Consequence for clients: the Applicant Detail documents panel must be **hidden**
for a Lead Manager, not rendered read-only, and a Lead Manager's applicant file
view is legitimately incomplete compared to an Admin's.
"""

from __future__ import annotations

from authenticate.constants import AuthorityType

from documents.exceptions import ActorNotPermittedError


def is_admin(user: object) -> bool:
    """True when the user acts with Admin authority in this app."""
    return getattr(user, "authority_type", None) == AuthorityType.ADMIN


def require_document_actor(user: object) -> None:
    """Allow Admin only — every read and every write.

    One helper rather than the reader/writer pair the other apps declare,
    because there is no split to express: the read population and the write
    population are the same set of one.
    """
    if not is_admin(user):
        raise ActorNotPermittedError("Admin authority is required to access documents.")
