# FLOWS — Uploaded Files

**Owner app:** `uploaded_files`
**Updated:** 2026-07-24
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/uploaded_files.txt` to the callable endpoints in `backend/uploaded_files/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

> **One access rule shapes every screen below.** Admin and Lead Manager share the read, upload,
> replace, and download routes; **only an Admin** may verify, archive, or restore. And a file
> **inherits the visibility of the record it belongs to** — files owned by a `document` or a print
> snapshot are Admin-only in every respect, because `documents` and `document_history` are. For a
> Lead Manager those files do not appear in any list and every per-file route returns **404**, so a
> document attachments panel is an Admin-only screen.
>
> **Read this before wireframing anything file-related.** This app is not reached through the record
> it belongs to. There is no "attach" button backed by an `applicants` or `offers` endpoint, and no
> file field on any other module's payload. **Every file screen in Grandway — on an applicant, a
> journey, an offer, a document, or a snapshot — is this app's list endpoint with a filter.** The
> panels are embedded in other screens; the state behind them is one ledger.

---

## Flow: Attach a document to an applicant and get it approved

- **Actor:** Lead Manager (steps 1–3), Admin (steps 4–5)
- **Goal:** Get a passport scan onto the applicant's record and marked as trusted.
- **Entry point:** Applicant Detail → Files panel

**Steps:**

1. **Applicant Detail — Files panel** — the panel loads on open →
   `GET /api/v1/files/?applicant=<applicant_id>&is_archived=false` (`uploaded_files.file.list`)
   - **Requires state:** the applicant exists. Nothing else — an applicant with no files returns an
     empty array, which is a normal empty state, not an error.
   - **Side effects:** none
   - *Failure — `VALIDATION_ERROR`:* the applicant id in the URL is malformed. This is a routing bug
     in the client, not a user-facing state; log it rather than showing it.
2. **Applicant Detail — Files panel → Upload dialog** — pick a category, choose a file, submit →
   `POST /api/v1/files/` (`uploaded_files.file.upload`), `multipart/form-data`
   - **Requires state:** the applicant exists; the file is ≤ 10 MB and one of pdf/jpg/jpeg/png/webp/docx/xlsx.
   - **Side effects:** a file is written to platform storage; an audit event is recorded; the panel in
     step 1 must be refetched. The new file is **`pending`** — render the pending badge immediately,
     do not optimistically show it as accepted.
   - *Failure — `UPLOADED_FILES_FILE_TOO_LARGE`:* inline error on the file input, naming the 10 MB
     limit. Check size client-side first so the user does not wait for a 10 MB upload to be refused.
   - *Failure — `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED`:* inline error on the file input, listing the
     seven accepted extensions.
   - *Failure — `UPLOADED_FILES_FILE_CONTENT_MISMATCH`:* inline error — "this file is not really a
     PDF". Rare and confusing to users; word it as "the file appears to be damaged or renamed".
   - *Failure — `UPLOADED_FILES_OWNER_NOT_FOUND`:* the applicant was deleted or the id is stale.
     Blocking dialog, then reload the applicant.
3. **Applicant Detail — Files panel** — the file appears with a `pending` badge. **No further Lead
   Manager action exists.** Do not render a verify control for this actor; it returns 403.
4. **File Review queue** *(Admin only screen)* — the queue loads →
   `GET /api/v1/files/?verification_status=pending` (`uploaded_files.file.list`)
   - **Requires state:** Admin authority. A Lead Manager reaching this screen gets 403 on every row;
     hide the screen from them entirely rather than rendering it empty.
   - **Side effects:** none
5. **File Review queue → row action** — accept or refuse →
   `POST /api/v1/files/<file_id>/verify/` (`uploaded_files.file.verify`)
   - **Requires state:** Admin authority; the file exists and is not archived.
   - **Side effects:** `verification_status`, `reviewed_at`, and `reviewed_by_username` change; an
     audit event is recorded; both the queue and any open Files panel are stale.
   - *Failure — `UPLOADED_FILES_REJECTION_REASON_REQUIRED`:* the reason field is mandatory when
     refusing. Make it a required field in the reject dialog rather than discovering this at submit.
   - *Failure — `UPLOADED_FILES_FILE_ARCHIVED`:* the file was archived by someone else while the
     queue was open. Blocking dialog, then refetch the queue.
   - *Failure — `UPLOADED_FILES_ACTOR_FORBIDDEN`:* the actor is a Lead Manager. This should be
     unreachable if the screen is gated correctly — treat it as a client bug.

## Flow: Replace a rejected document with a better copy

- **Actor:** Lead Manager
- **Goal:** Supply a corrected scan without losing the record of what was refused.
- **Entry point:** Applicant Detail → Files panel → File Detail

**Steps:**

1. **File Detail** — open a file showing a `rejected` badge and its reason →
   `GET /api/v1/files/<file_id>/` (`uploaded_files.file.read`)
   - **Requires state:** the file exists.
   - **Side effects:** none
2. **File Detail → Replace dialog** — choose the new file, submit →
   `POST /api/v1/files/<file_id>/replace/` (`uploaded_files.file.replace`), `multipart/form-data`
   - **Requires state:** the file exists, is not archived, and has **not already been replaced**.
   - **Side effects:** a **new file record with a new id** is created — navigate to it, do not stay on
     the old one. The predecessor becomes `is_current: false` and keeps its bytes, its rejection, and
     its reason. The successor is **`pending`** even though this flow started from a rejection.
   - *Failure — `UPLOADED_FILES_ALREADY_SUPERSEDED`:* someone else already replaced it. Fetch the
     version chain (flow below) and offer the current version instead.
   - *Failure — the three upload failures:* identical treatment to the upload flow above.
3. **File Detail (successor)** — the new file shows `pending` and a "replaces" link to the old one.
4. **File Review queue** *(Admin)* — the successor is reviewed exactly as in the flow above →
   `POST /api/v1/files/<file_id>/verify/` (`uploaded_files.file.verify`)
   - **Side effects:** only the successor changes. The predecessor keeps its rejection permanently.

## Flow: Read a file's replacement history

- **Actor:** Admin or Lead Manager
- **Goal:** Understand which version is current and what came before it.
- **Entry point:** File Detail → Version history

**Steps:**

1. **File Detail → Version history** — the section loads →
   `GET /api/v1/files/<file_id>/versions/` (`uploaded_files.file.versions`)
   - **Requires state:** the file exists. It may be any member of the chain, including a superseded
     one — the response is the same either way.
   - **Side effects:** none
   - *Failure — `UPLOADED_FILES_FILE_NOT_FOUND`:* the id is stale. Return to the Files panel.
2. Render **oldest first** — this is the opposite order to the file list, deliberately, because a
   chain is read as a history. `meta.count` is the chain length; there is no pagination.
   A chain of one is normal, not an empty state.
3. **Version history → any row** — every version, current or not, offers download →
   `GET /api/v1/files/<file_id>/download/` (`uploaded_files.file.download`)

## Flow: Retrieve a file's contents

- **Actor:** Admin or Lead Manager
- **Goal:** Open or save the actual document.
- **Entry point:** any Files panel row, File Detail, or Version history row

**Steps:**

1. **Any file row — "Download"** — the user clicks →
   `GET /api/v1/files/<file_id>/download/` (`uploaded_files.file.download`)
   - **Requires state:** the file exists **and its bytes are present on the platform's storage**.
     Archived and superseded files are both still downloadable.
   - **Side effects:** **an audit event is recorded for every download**, before the transfer begins.
     This is the only read in the API that is audited; a user should not be surprised that opening a
     passport is logged.
   - *Failure — `UPLOADED_FILES_FILE_BYTES_MISSING`:* a platform fault, not a user error. Show "this
     file could not be retrieved" and offer a report path. **Do not retry** — nothing about it is
     transient.
2. The response is the raw file as an **attachment**, not JSON.
   - **This endpoint needs the bearer token, so the URL cannot go in an `<img src>` or a plain
     `<a href>`.** Fetch it with the auth header and hand the browser a blob.
   - There is **no inline preview and no thumbnail anywhere in this app.** A photograph or a
     signature image renders only if the client fetches the bytes and builds an object URL itself.

## Flow: Retire a file without losing it

- **Actor:** Admin
- **Goal:** Take a file out of active work while keeping it on record.
- **Entry point:** File Detail → Archive

**Steps:**

1. **File Detail → Archive dialog** — enter the reason, confirm →
   `POST /api/v1/files/<file_id>/archive/` (`uploaded_files.file.archive`)
   - **Requires state:** Admin authority; the file exists and is not already archived.
   - **Side effects:** the file drops out of every `?is_archived=false` panel. It stays downloadable
     and stays in its version chain. An audit event is recorded.
   - *Failure — `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED`:* make the reason a required field in the
     dialog. Archiving is the closest thing to deletion the API offers, and the reason is the record.
   - *Failure — `UPLOADED_FILES_ALREADY_ARCHIVED`:* stale state; refetch.
2. **Files panel** — the archived file is hidden by the default filter. Offer a "show archived"
   toggle that drops `is_archived` from the query — **omitting the parameter returns archived files
   too**; there is no `is_archived=true`-only convention to learn.
3. **File Detail (archived)** — `PATCH`, replace, and verify all now return
   `UPLOADED_FILES_FILE_ARCHIVED`. **Disable those controls rather than letting the user discover it.**
4. **File Detail → Restore** — reverse it →
   `POST /api/v1/files/<file_id>/restore/` (`uploaded_files.file.restore`)
   - **Requires state:** Admin authority; the file is archived.
   - **Side effects:** all three archive fields are cleared — **the payload keeps no trace that it was
     ever archived.** If a screen needs "was this archived before", it must come from the `audit`
     module, not from the file.
   - *Failure — `UPLOADED_FILES_NOT_ARCHIVED`:* stale state; refetch.

## Flow: Correct a misfiled document

- **Actor:** Admin or Lead Manager
- **Goal:** Fix a wrong category or add an explanatory note, without re-uploading.
- **Entry point:** File Detail → Edit

**Steps:**

1. **File Detail → Edit** — change the category, or add a note →
   `PATCH /api/v1/files/<file_id>/` (`uploaded_files.file.update`)
   - **Requires state:** the file exists and is not archived.
   - **Side effects:** an audit event is recorded — **unless nothing actually changed**, in which case
     the call still returns 200 and writes nothing.
   - *Failure — `UPLOADED_FILES_FIELD_IMMUTABLE`:* the form sent something other than `category` or
     `notes`. **Only build those two inputs.** A file cannot be moved to another record, renamed, or
     have its verification set through this endpoint; the response names each refused field.
   - *Failure — `UPLOADED_FILES_FILE_ARCHIVED`:* restore it first.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `uploaded_files.file.list` | `GET /api/v1/files/` | Attach a document; Retire a file | **Every** files panel in the product is this endpoint with a filter |
| `uploaded_files.file.upload` | `POST /api/v1/files/` | Attach a document | `multipart/form-data` |
| `uploaded_files.file.read` | `GET /api/v1/files/<file_id>/` | Replace a rejected document; Correct a misfiled document | |
| `uploaded_files.file.update` | `PATCH /api/v1/files/<file_id>/` | Correct a misfiled document | `category` and `notes` only |
| `uploaded_files.file.download` | `GET /api/v1/files/<file_id>/download/` | Retrieve a file's contents; Read a file's history | Returns bytes, not JSON. Audited |
| `uploaded_files.file.versions` | `GET /api/v1/files/<file_id>/versions/` | Read a file's replacement history | Oldest first, unpaginated |
| `uploaded_files.file.replace` | `POST /api/v1/files/<file_id>/replace/` | Replace a rejected document | Returns a **new** file id |
| `uploaded_files.file.verify` | `POST /api/v1/files/<file_id>/verify/` | Attach a document; Replace a rejected document | Admin only |
| `uploaded_files.file.archive` | `POST /api/v1/files/<file_id>/archive/` | Retire a file | Admin only |
| `uploaded_files.file.restore` | `POST /api/v1/files/<file_id>/restore/` | Retire a file | Admin only |

Every registered endpoint is used by at least one flow. There is no admin-only maintenance endpoint
here without a screen behind it.

## Cross-app dependencies

- **This app references (outbound):** `none`. No flow above calls another app's endpoint. Every flow
  begins from a record that already exists — an applicant, journey, offer, document, or snapshot —
  but reads and writes only this app's endpoints. **The owning record is a precondition, not a step.**
- **Referenced by other apps (inbound):** `none yet`. No other app's flow file calls a
  `uploaded_files.*` endpoint today, because no other module has a file-bearing screen wired up. The
  file panels described in `concepts/applicants_flows.md`, `concepts/offers_flows.md`,
  `concepts/documents_flows.md`, and `concepts/document_history_flows.md` as *missing* are now
  buildable — each of those files records the gap and points here.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file. **That ripple will matter soon:** the moment an applicant photograph or an offer
letter gets a first-class field in its own module, `uploaded_files.file.upload` will appear in that
module's flows.

## Open questions

- **Which screen owns the review queue?** `?verification_status=pending` is a global cross-applicant
  list. `concepts/uploaded_files.txt` names a "review queue" but not where it lives in the navigation.
- **How does a screen pick *the* photograph or *the* passport?** There is no primary-file concept.
  Filtering by category can return several files, and nothing marks one as canonical. Today the
  answer is "the newest current one", which is a client-side convention, not a backend rule.
- **Should a Lead Manager see files on applicants not assigned to them?** Today yes — reads are not
  owner-scoped. `concepts/project_overview.txt` leaves the underlying question open, and this app is
  where the answer bites hardest: an unscoped read here exposes a passport, not a name.
- **Is there a size or count limit per record?** No. An applicant may accumulate unlimited files and
  nothing warns anyone.
- **Who sees a document's attachments?** Only an Admin, today — a file owned by a `document` or a
  snapshot inherits that module's Admin-only rule. If Lead Managers are ever given document access,
  `ADMIN_ONLY_OWNER_TYPES` in the backend must change in the same session, or the attachments panel
  will stay invisible to them while the document itself becomes visible.
- **Where do generated PDFs come from?** The `generated_document` category and the `system_generated`
  source both exist, but `document_history` has no field pointing at a file and does not call this
  app. A client that generates a PDF may upload it against a snapshot; nothing in `document_history`
  will know it did.
- **No education or test-score owner type**, because those apps do not exist. Transcripts and score
  reports attach to the applicant for now, and will **not** be re-pointed automatically later.
