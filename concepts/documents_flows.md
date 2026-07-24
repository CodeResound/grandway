# FLOWS — Documents

**Owner app:** `documents`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/documents.txt` to the callable endpoints in `backend/documents/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **Five things govern every flow below.**
>
> 1. **Admin only — a Lead Manager cannot open any of these screens.** Not read-only, not empty:
>    **hidden**. This is the only module in Grandway a Lead Manager cannot see at all, and it
>    overrides the "Admin or Lead Manager" phrasing in `concepts/documents.txt` flow 1. An empty
>    documents panel would assert "this applicant has no documents", which is false and worse than
>    no panel.
> 2. **The frontend computes; the backend stores.** Send input fields only. Never send a running
>    balance, a debit/credit total, a closing balance, an interest or tax row, or an
>    amount-in-words — the backend stores whatever it is given and will hand a stale value back
>    forever.
> 3. **`content` replaces, it does not merge.** Every save sends the complete body. A partial
>    `content` payload silently discards every key it omits. This is the single most likely
>    integration mistake in this module.
> 4. **There is no delete, and no print.** The delete button becomes "Archive" (with a mandatory
>    reason). The print button has **no endpoint at all** — see the unbacked flow below.
> 5. **An archived document is frozen.** The workspace must go read-only; any save returns 409.

---

## Flow: Create and work on an applicant's document

- **Actor:** Admin
- **Goal:** Get from an applicant's file to a completed, ready document.
- **Entry point:** Applicant Detail → Documents panel

**Steps:**

1. **Applicant Detail → Documents panel** — load what exists →
   `GET /api/v1/documents/?applicant=<applicant_id>` (`documents.document.list`)
   - **Requires state:** the applicant being viewed.
   - **Side effects:** none.
   - **Hide this entire panel for a Lead Manager.** They receive 403 `DOCUMENTS_ACTOR_FORBIDDEN`.
   - Rows carry `label`, `family`, `template_key`, `status`, and `updated_at` — but **not `content`**.
     A worklist of twenty bank statements would otherwise carry a megabyte of transaction rows.
   - **Pass `status=draft` or `status=ready` for a live panel.** Omitting `status` includes archived
     documents by design.

2. **New Document Form** — choose a template and open the record →
   `POST /api/v1/documents/` (`documents.document.create`)
   - **Requires state:** an existing applicant. **Nothing about their status is checked** — a
     document may be created against a dormant or archived applicant.
   - **Side effects:** appends `document_created` to the audit log. Nothing outside this module
     changes.
   - **Send `family` and `template_key` together, from one picker.** They are cross-validated: a
     `bank-vyas-statement` slug under family `lor` is refused. Deriving the family from the slug
     client-side is the reliable way to keep them in step.
   - *Failure — `DOCUMENTS_TEMPLATE_KEY_INVALID`:* the two came from different pickers. A UI bug,
     not user error.
   - *Failure — `VALIDATION_ERROR` on `template_key`:* the slug is malformed — uppercase, spaces, or
     underscores. Slugs are lowercase ASCII with single hyphens.
   - **`content` is optional here** and defaults to `{}`. The workspace opens before anything is
     typed into it.

3. **Document Workspace** — load the body →
   `GET /api/v1/documents/<document_id>/` (`documents.document.read`)
   - **Requires state:** the document.
   - **Side effects:** none.
   - This is the **only** endpoint that returns `content`. Render the live preview from it.
   - **Render `label`, never `template_key`,** to the user — the slug is a machine key.

4. **Document Workspace** — save →
   `PATCH /api/v1/documents/<document_id>/` (`documents.document.update`)
   - **Requires state:** the document must not be archived.
   - **Side effects:** appends `document_updated`. **The body is redacted from the event** — the
     history records that `content` changed, never what it said.
   - **Send the complete `content`.** It is replaced wholesale.
   - **Send only the fields the user changed at the top level.** Including `status`, `applicant`,
     `family`, or `template_key` fails the whole request — this module rejects immutable fields
     rather than dropping them, unlike `institutions`. Do not reuse a read-modify-write-the-whole-object
     form component from the catalogue screens.
   - *Failure — `DOCUMENTS_OWNERSHIP_IMMUTABLE` / `DOCUMENTS_STATUS_IMMUTABLE`:* strip those keys
     before submitting; `details` names each offending field.
   - *Failure — `DOCUMENTS_CONTENT_TOO_LARGE`:* the body exceeds 256 KiB. Realistically only a very
     long bank statement. Show it against the transactions table, not as a form-level error.
   - *Failure — `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409):* the document was archived, probably by
     someone else. Refetch and switch the workspace to read-only.
   - **A no-op save writes no history event.** A UI showing "saved, history updated" after an
     unchanged submit will be lying.

5. **Document Workspace** — mark it finished →
   `POST /api/v1/documents/<document_id>/status/` (`documents.document.change_status`)
   - **Requires state:** the document must not be archived.
   - **Side effects:** appends `document_status_changed`.
   - Accepts `draft` and `ready` **only**. Sending `archived` fails serializer validation — archiving
     is its own action because it demands a reason.

6. **Print** — **no endpoint exists.** See the unbacked flow below.

---

## Flow: Create a standalone document

- **Actor:** Admin
- **Goal:** Prepare an internal letter or form that belongs to no applicant.
- **Entry point:** Standalone Documents list

**Steps:**

1. **Standalone Documents list** →
   `GET /api/v1/documents/?standalone=true` (`documents.document.list`)
   - **Requires state:** nothing.
   - **Side effects:** none.
   - This is the only way to reach standalone documents as a set. **They are absent from
     `documents.document.list_workspaces`**, which groups by applicant.

2. **New Document Form** — create with a purpose instead of an owner →
   `POST /api/v1/documents/` (`documents.document.create`)
   - **Requires state:** nothing at all. This is the only creation path in the module with no
     prerequisite record.
   - **Side effects:** appends `document_created`.
   - **Send `standalone_purpose` and omit `applicant`.** The concept requires that a standalone
     document "must still say who owns or commissioned it", and the API enforces it: exactly one of
     the two must be present.
   - *Failure — `DOCUMENTS_OWNER_REQUIRED`:* neither was given. Make the purpose field mandatory on
     the standalone branch of the form.

3. **Work it forward** — identical to steps 3–5 of the applicant flow.
   - **One extra rule:** `standalone_purpose` cannot be cleared later. The ownership check re-runs on
     every save against the resulting record, so blanking it returns `DOCUMENTS_OWNER_REQUIRED`.

---

## Flow: Retire a document and bring it back

- **Actor:** Admin
- **Goal:** Take a superseded document out of circulation without losing it.
- **Entry point:** Document Workspace → Archive

**Steps:**

1. **Archive dialog** →
   `POST /api/v1/documents/<document_id>/archive/` (`documents.document.archive`)
   - **Requires state:** the document must not already be archived.
   - **Side effects:** appends `document_archived` with the reason; sets `status`, `archive_reason`,
     `archived_at`, `archived_by`. **The document stays in the list.**
   - **The reason input is mandatory** — enforce it before submit. Archived documents are kept
     forever, so why one is archived must be answerable from the record.
   - *Failure — `DOCUMENTS_ARCHIVE_REASON_REQUIRED`:* a whitespace-only reason reached the server.
   - *Failure — `DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED` (409):* refetch; someone else archived it.
   - **Label the button "Archive", not "Delete".** Say in the confirmation that the record is kept.

2. **Workspace goes read-only.** `is_editable` is now `false`. Every `PATCH` and status change
   returns 409 until step 3. A UI that leaves the form live will produce nothing but failed saves.

3. **Restore** →
   `POST /api/v1/documents/<document_id>/restore/` (`documents.document.restore`)
   - **Requires state:** the document must be archived.
   - **Side effects:** appends `document_restored`; clears the three archive fields.
   - **It returns to `draft`, never to `ready`** — even if it was `ready` when archived. Whoever
     archived it may have done so precisely because it was not ready.
   - *Failure — `DOCUMENTS_DOCUMENT_NOT_ARCHIVED` (409):* it was already active.

4. **History panel** — the archiving is still there →
   `GET /api/v1/documents/<document_id>/history/` (`documents.document.list_history`)
   - **Requires state:** the document.
   - **Side effects:** none.
   - `document_archived` and its reason survive the restore. **But a body change shows only a
     `<changed>` marker** — you cannot show a diff of what the document said, and you cannot offer
     "revert to previous version". Nothing stores it.

---

## Flow: The documents landing table

- **Actor:** Admin
- **Goal:** See whose files have live document work, without opening each applicant.
- **Entry point:** Documents (top-level nav)

**Steps:**

1. **Documents landing** →
   `GET /api/v1/documents/workspaces/` (`documents.document.list_workspaces`)
   - **Requires state:** nothing. Returns an empty array when no applicant has live documents.
   - **Side effects:** none.
   - One row per applicant: `applicant_id`, `applicant_name`, `document_count`, `last_updated`.
   - **Archived documents are excluded from the count**, and an applicant whose documents are *all*
     archived does not appear. The table answers "who has live work", not "who has documents".
   - **Standalone documents are absent entirely** — they need their own tab, fed by
     `?standalone=true`.
   - Note the **trailing slash**: `workspaces/` is a literal segment, not a document id.

2. **Row click** →
   `GET /api/v1/documents/?applicant=<applicant_id>` (`documents.document.list`)
   - Continues into the applicant flow above.

---

## Flow: Review and print — NOT DELIVERABLE

`concepts/documents.txt` flow 3 ends with "the system captures a print snapshot in the document
history app", and the Print Preview / History handoff screen exists in its wireframe notes.

**No endpoint in this project supports it.** There is no print-log endpoint, no snapshot storage, and
no way to record that a document was printed. That work belongs to `document_history`, which has **no
concept file** and therefore could not be built (CLAUDE.md §36 requires one first).

Two related gaps travel with it:

- **Signatory selection is unbacked.** Certificate templates read `content.instructorId` and
  `content.directorId`, which reference a Signature table owned by the unbuilt
  `document_templates`. There is no endpoint to populate those dropdowns, and the ids round-trip as
  **unvalidated opaque strings** — a document may name a signatory that never existed.
- **Supporting files are unbacked.** Flow 2's "attaches supporting files when needed" needs
  `uploaded_files`, which does not exist. Nothing can be attached to a document.

**Do not ship UI that implies any of this works** — no print button that only renders locally and
claims to have saved history, no signatory dropdown backed by hardcoded data, no file-attach control.
Each would need an API that is not there.

This is listed rather than omitted because a frontend author reading the concept file will look for
these endpoints and needs to know they are absent rather than conclude they missed them.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `documents.document.list` | `GET /api/v1/documents/` | Applicant document panel; Standalone list; Landing row click | Omits `content`. `?applicant=`, `?standalone=`, `?status=`, `?family=`, `?search=` |
| `documents.document.create` | `POST /api/v1/documents/` | Create applicant document; Create standalone | `family` + `template_key` cross-validated |
| `documents.document.list_workspaces` | `GET /api/v1/documents/workspaces/` | Documents landing table | Excludes standalone and archived |
| `documents.document.read` | `GET /api/v1/documents/<document_id>/` | Document Workspace | **The only endpoint returning `content`** |
| `documents.document.update` | `PATCH /api/v1/documents/<document_id>/` | Document Workspace save | `content` replaces wholesale; immutable fields rejected |
| `documents.document.change_status` | `POST /api/v1/documents/<document_id>/status/` | Mark ready | `draft` / `ready` only |
| `documents.document.archive` | `POST /api/v1/documents/<document_id>/archive/` | Retire | Reason mandatory. **This is the delete button** |
| `documents.document.restore` | `POST /api/v1/documents/<document_id>/restore/` | Retire → restore | Always returns to `draft` |
| `documents.document.list_history` | `GET /api/v1/documents/<document_id>/history/` | Retire (step 4); Workspace history panel | Body changes shown as a marker only |

**Screens from `concepts/documents.txt`, and whether they are backed:**

- **Document List** — backed. Filters for owner, status, type, and template family all exist;
  "template family" is `?family=`, and per-slug filtering is `?template_key=`.
- **Applicant Detail → Documents panel** — backed via `?applicant=`. **Admin-only; hide for Lead Managers.**
- **Standalone Documents list** — backed via `?standalone=true`.
- **Document Workspace** — backed for the header, source-data form, and save actions. **Its
  supporting-files section has no endpoint**, and its live preview is entirely client-side by design.
- **Print Preview / History handoff** — **not backed.** See the unbacked flow above.

## Cross-app dependencies

- **This app references (outbound):** `applicants.applicant.read` — a client resolves the applicant
  whose file it is working in before creating a document. The backend also holds a nullable FK and
  calls `applicants.selectors.get_applicant_by_id` on create; see
  `backend/documents/docs/INTEGRATION.md` §2.
- **Referenced by other apps (inbound):** none. No other app's flow file references a `documents.*`
  permission key.
- **Blocked on (not yet existing):** `document_history` (print snapshots), `document_templates`
  (templates and signatories), `uploaded_files` (supporting files). All three are named domains in
  `concepts/project_overview.txt`; the first two have no concept file.

**Note the access asymmetry with `applicants`.** An applicant is readable by any Admin or Lead
Manager, but their documents are Admin-only. A Lead Manager's applicant file view is legitimately
incomplete — that is the intent, not a bug to route around.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.
