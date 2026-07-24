# Security — Documents

**Owner app:** `documents`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial security notes — Admin-only access, audit redaction of the document body |

---

## 1. Access: Admin only, reads included

| Action | `admin` | `lead_manager` | `superadmin` |
|--------|---------|----------------|--------------|
| `GET` (list, workspaces, detail, history) | allowed | **denied** | **denied** |
| `POST` / `PATCH` (create, update, status, archive, restore) | allowed | **denied** | **denied** |

Implemented in `documents/access.py` as the single helper `require_document_actor`, applied by the
`DocumentActorView` base class that every view in the app inherits. Denial is 403
`DOCUMENTS_ACTOR_FORBIDDEN` in every case.

**This is the strictest access model in the project, and the first where a Lead Manager is refused a
read.** Set against the others:

| App | Lead Manager reads | Lead Manager writes |
|-----|--------------------|---------------------|
| `applicants`, `applicant_journeys`, `offers` | yes | yes |
| `institutions`, `clients` | yes | no |
| **`documents`** | **no** | **no** |

**Why.** Documents hold the most sensitive material in Grandway. A single record may carry a bank
statement with an account number, an opening balance, and a full transaction history; a
passport-derived declaration; or a family financial affidavit. `concepts/project_overview.txt` —
"Privacy by default" — names exactly this class of data, and lists "Which sensitive fields or files
should be hidden from Lead Managers by default?" as an open project question. For this app the
project owner has answered it: all of it.

**This overrides the concept file, deliberately.** `concepts/documents.txt` flow 1 says "An Admin or
Lead Manager opens an applicant record or a standalone document workspace". The narrower rule was set
by the project owner after the concept was written and supersedes it (§36 — concept files are a
living draft, not a rulebook). The concept file carries a correction note in the same commit.

**Consequences a client must handle.**

- The Applicant Detail documents panel must be **hidden** for a Lead Manager, not rendered read-only
  or shown empty. An empty panel implies "this applicant has no documents", which is a different and
  false statement.
- A Lead Manager's view of an applicant file is legitimately incomplete compared to an Admin's. That
  is the intent, not a bug to route around.
- There is no partial access, no metadata-only tier, and no "can see that a document exists but not
  its contents" mode. The list endpoint is refused along with everything else, because knowing
  *which* applicants have bank statements on file is itself disclosure.

**Consequence for 404s.** A 404 from this app always means the record genuinely does not exist —
never "exists but is out of your scope", as it can in `leads`. Nothing is hidden from an Admin.

**Interim pattern, not the permissions app.** These are inline `authority_type` checks per §9. No
view in this app — or any app — calls a `check_permission()` engine; the `permission_key` values in
`registry.py` are metadata, not enforcement. Every endpoint here is registered at `medium` or `high`
risk, deliberately higher than the equivalents in other apps, so that whoever eventually wires
enforcement into the request path inherits the judgement rather than having to re-derive it.

## 2. The document body never reaches the audit log

Every mutation appends one `audit.AuditEvent` whose `changes` map records each changed field's
previous and new value — **except `content`, which is replaced by the literal marker `<changed>`**.

This is not a nicety. The audit log is a separate app with its own read endpoints, available to every
Admin and Superadmin. A change map carrying the old and new document body would copy an applicant's
account number and transaction history into a second, longer-lived, more widely readable store — and
§17 forbids logging that class of data outright. The history records *that* the body changed and who
changed it, never what it said.

Implemented in `services._diff_for_audit`, which is written out in full rather than copied from the
other apps' `_diff` precisely so the redaction is visible at the point it happens. Covered by
`tests/test_services.py::ContentNeverReachesTheAuditLogTests`, which asserts that a real account
number appears nowhere in `changes`, `metadata`, or `summary` across the whole audit table.

**Corollary: a document's history cannot be used to reconstruct a previous body.** There is no field
history and no versioning here. Recovering what a document said before an edit is what
`document_history` print snapshots are for, and that app does not exist. Editing a document today
loses its previous contents irrecoverably.

## 3. Search and admin are scoped away from the body

- **`?search=` matches `label` only.** `selectors.search_documents` deliberately does not reach into
  `content`. Full-text search over personal financial data is a feature that needs its own decision,
  not an accident of a search box.
- **Django admin registers `content` read-only** and does not expose it to `search_fields`. An admin
  edit would also bypass the service layer, which is what appends the audit event — a change made
  there would alter the record and leave no trace of who did it.

## 4. Nothing is deleted

There is **no `DELETE` method on any endpoint**, and no delete service. Withdrawal is
`POST .../archive/` with a mandatory reason. Four layers:

1. **No route.** `urls.py` maps only `GET`, `POST`, and `PATCH`.
2. **No service.** A test scans the service module for any `delete_*` or `remove_*` callable and
   fails if one appears, so a future session has to remove the test deliberately rather than slip
   past review.
3. **An archived document is frozen.** Update and status change both return 409 until it is
   restored, so an archived record cannot be quietly amended.
4. **Database `PROTECT`** on `applicant` and `created_by`: an applicant who has documents on file
   cannot be deleted, and neither can the account that created one.

## 5. What is deliberately not protected

- **`content` is not validated, sanitized, or escaped.** It is stored as received and returned as
  stored. A client that posts script content into a text field will get it back verbatim, and the
  frontend is responsible for escaping on render. The backend cannot sanitize what it does not
  parse — and parsing 42 open shapes is exactly what this app refuses to do.
- **Signature references are unverified.** `content.instructorId` / `content.directorId` point at a
  table that does not exist yet; a document may name a signatory that never did.
- **A client-supplied derived value is stored, not rejected.** Posting `statement_debit_total` gets
  it persisted. It must not be trusted — the authoritative figure is always the one the frontend
  computes from the inputs at render time.
- **No rate limiting beyond project defaults**, and no per-document size accounting beyond the 256 KiB
  cap on a single body.
