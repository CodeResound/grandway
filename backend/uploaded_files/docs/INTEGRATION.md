# Integration — Uploaded Files

**Owner app:** `uploaded_files`
**Version:** 1.0.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 10 endpoints, one resource, the project's first file storage |
| 1.0.1 | 2026-07-24 | AI (Claude) | Defects found by the §19.5 consumer-comprehension test. **One was a real authorization leak and was fixed in code, not in prose:** a Lead Manager could list and download files owned by a `document` or a print snapshot, which `documents` and `document_history` hide from them entirely. Also **split `UPLOADED_FILES_FILE_EMPTY` out of `..._FILE_TOO_LARGE`** (one code for two opposite problems), **added `superseded_by_username`** (stored and never returned, so "who replaced this?" was unanswerable), corrected a nullable-field miscount and a false "every endpoint takes an id" claim, resolved the missing-owner error contradiction, stated the `details` rule for every custom code, and added seven gaps a client would have hit |

---

## 1. Module

- **Name:** Uploaded Files — the platform's file ledger. Every stored file in Grandway lives here: what it is, which record it belongs to, whether a reviewer accepted it, what it replaced, and whether it is still in active use. **This is the only module in the system where bytes are stored at all.**
- **Base path:** `/api/v1/files/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. **`admin` and `lead_manager` may list, read, edit, upload, replace, download, and read version chains. Only `admin` may verify, archive, or restore.** `superadmin` is rejected on every route.
- **One further restriction, and it is easy to miss:** a file whose owner is a `document` or a `snapshot` is **Admin-only in every respect** — a `lead_manager` cannot see it in a list, cannot read it, cannot download it, and cannot create one. A file inherits the visibility of the record it belongs to, and those two modules are Admin-only on every route including reads. See §3.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which is the whole access check here. | Every endpoint returns 401; a `superadmin` gets 403 everywhere and a `lead_manager` gets 403 on the three review/archival routes. |
| `authenticate` | FK | `uploaded_by` (`PROTECT`) plus three `SET_NULL` lifecycle actors reference user accounts. | No file could record who uploaded, reviewed, archived, or superseded it. |
| `applicants` | FK + service call | An applicant-owned file points at one, resolved through `applicants.selectors.get_applicant_by_id` on upload. | `POST` with `applicant=` returns 400 `UPLOADED_FILES_OWNER_NOT_FOUND` for any id that does not resolve; no applicant could hold a file. |
| `applicant_journeys` | FK + service call | Same, through `applicant_journeys.selectors.get_journey_by_id`. | No journey could hold a file. |
| `offers` | FK + service call | Same, through `offers.selectors.get_offer_by_id`. | No offer could hold its letter. |
| `documents` | FK + service call | Same, through `documents.selectors.get_document_by_id`. | No document could hold an attachment. |
| `document_history` | FK + service call | Same, through `document_history.selectors.get_snapshot_by_id`. | No print snapshot could hold a generated PDF. |
| `audit` | service call | Every write **and every download** appends one immutable event. This module stores no history of its own. | Records still save but leave no trace of who uploaded, reviewed, archived, or downloaded a file. |
| Local filesystem | infrastructure | `MEDIA_ROOT` is the byte store. **No URL maps to it in any environment** — reachable only through the download endpoint. | Uploads fail; existing rows return 404 `UPLOADED_FILES_FILE_BYTES_MISSING` on download. |

**Nothing outside this module references it.** No shipped app holds a foreign key to a file or calls into this app. That has one consequence you must plan around, and it is the single most important thing in this document:

> **There is no "attach" action on any other module's endpoints.** `applicants` has no photograph field, `offers` has no attachment field, `documents` has no attachment field, `document_history` has no generated-file field, and `clients.logo_url` / `document_templates.signature_image_url` are still plain URLs to hosts this API knows nothing about. To attach a passport to an applicant you `POST /api/v1/files/` with `applicant=<id>`; to show that applicant's files you `GET /api/v1/files/?applicant=<id>`. The relationship is one-way — a file knows its owner, an owner does not know its files.

## 3. Conventions

- **Access — two levels, and the split is the module's design, not an oversight.** `admin` and `lead_manager` may list, read, **edit**, upload, replace, download, and read version chains. **Only `admin`** may `verify`, `archive`, or `restore`. `superadmin` is refused everywhere. Render the review and archive controls only for an `admin`; a Lead Manager pressing them gets 403, not a validation error.
- **A third rule cuts across both: a file inherits the visibility of the record it belongs to.** Files owned by a `document` or a `snapshot` are **Admin-only**, because `documents` and `document_history` are Admin-only on every route including reads — without this, the file ledger would be a side door around another module's access rule. For a `lead_manager` such a file **does not appear in any list** and every per-file route returns **404, not 403**, deliberately: confirming it exists would leak exactly what those modules hide. Uploading against a `document` or `snapshot` owner returns **403** (there is nothing to conceal — the client named the owner itself).
- **Reads are otherwise not owner-scoped.** Any `admin` or `lead_manager` may read and download any file on any applicant, journey, or offer, regardless of who is assigned to it. Do not build a UI that assumes otherwise.
- **All three refusals share one code, `UPLOADED_FILES_ACTOR_FORBIDDEN`, and differ only in `message`.** Since you should not branch on `message`, **do not try to distinguish them from the response** — decide what to render from the authority you already hold. A 403 from this module means "this actor may not do this", and that is the whole contract.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint**, no delete action, and no way for any actor to remove a file or its bytes. Withdrawal from use is `POST /files/<id>/archive/`, which is reversible.
- **The bytes are never in a JSON response.** There is no `file` field, no URL, and no storage path in any payload. `GET /files/<id>/download/` is the only way to obtain a file's contents, and it requires the same authorization as everything else. Do not build `<img src>` or `<a href>` against anything in a file payload — there is no address to point at.
- **Request encoding:** `application/json`, **except** `POST /files/` and `POST /files/<id>/replace/`, which are `multipart/form-data`. Sending JSON to either returns 400.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to four fields to show the envelope**; a real upload returns the full `UploadedFile` shape defined in §4.

```json
{
  "success": true,
  "message": "File uploaded.",
  "data": {
    "id": "8f14e45f-ea22-4a7f-9f0a-1c2b3d4e5f60",
    "owner_type": "applicant",
    "category": "passport",
    "verification_status": "pending"
  },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract. Branch on the HTTP status and, for errors, on `error.code`.

- **The download response is the one exception to the envelope.** On success it is the raw file, not JSON, with `Content-Type` set to the stored type, `Content-Disposition: attachment; filename="<original_filename>"`, `X-Content-Type-Options: nosniff`, and `Cache-Control: private, no-store`. Every **failure** on that route still uses the standard error envelope.
- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.
- **The `details` rule for this module, stated once so you need no worked body per code:** every `UPLOADED_FILES_FILE_*` upload rejection keys its message under `file`; `UPLOADED_FILES_OWNER_NOT_FOUND` keys under the owner field that failed (`applicant`, `journey`, `offer`, `document`, or `snapshot`); `UPLOADED_FILES_FIELD_IMMUTABLE` keys under **each** refused field name; `UPLOADED_FILES_REJECTION_REASON_REQUIRED` and `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED` key under `reason`. **Every other code in this module returns `details: {}}`** — including all three 403s, all three 404s, `UPLOADED_FILES_ALREADY_SUPERSEDED`, `UPLOADED_FILES_FILE_ARCHIVED`, `UPLOADED_FILES_ALREADY_ARCHIVED`, and `UPLOADED_FILES_NOT_ARCHIVED`.

```json
{
  "success": false,
  "error": {
    "code": "UPLOADED_FILES_FILE_CONTENT_MISMATCH",
    "message": "The file's contents do not match its '.pdf' extension.",
    "details": { "file": ["The file's contents do not match its '.pdf' extension."] }
  },
  "meta": {}
}
```

  Field-level serializer failures use the project-wide `VALIDATION_ERROR` with the offending fields in `details`. The missing-owner case is keyed under the synthetic field `owner`, because the request could legitimately have carried any of five:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": {
      "owner": ["Supply exactly one of: applicant, journey, offer, document, snapshot. Received 0."]
    }
  },
  "meta": {}
}
```

  **Query-string failures use the same code and the same shape**, keyed by the parameter name — there is no separate envelope for them:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "category": ["\"visa\" is not a valid choice."] }
  },
  "meta": {}
}
```

- **Auth failures.** A valid token whose authority may not perform the action → 403 `UPLOADED_FILES_ACTOR_FORBIDDEN` with the body below. This code **replaces** the project-wide `PERMISSION_DENIED` rather than coexisting with it — a handler keyed only on the global code will never fire here. It is repeated in every `Errors` list in §7 rather than left to this section, because a client building its error map from those lists would otherwise have no 403 branch. No token, an expired token, or a revoked session → 401 with the `authenticate` module's codes, which this contract does not enumerate — see §9.

```json
{
  "success": false,
  "error": {
    "code": "UPLOADED_FILES_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to review or archive a file.",
    "details": {}
  },
  "meta": {}
}
```

- **Authority is checked before existence.** A `lead_manager` calling `POST /files/<unknown-id>/verify/` gets 404, not 403 — the file is resolved first, then the authority. But a `superadmin` gets 403 on every route before anything is resolved. Do not infer a file's existence from either code.
- **HTTP status codes.** `POST /files/` and `POST /files/<id>/replace/` return **201** — both create a resource. Every other success returns **200**, including the three lifecycle actions, which create nothing and return the resource they changed. Domain-rule violations are **400**; **this module has no 409 at all.** A missing record named in the URL path is **404**, and so is a row whose bytes are missing from the volume. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Query parameter encoding.** A **recognised** parameter with an invalid value is **rejected with 400**: `?category=visa` returns a validation error rather than an unfiltered result set, and so does a malformed UUID in `?applicant=`. An **unrecognised** parameter is **silently ignored** — `?foo=1`, including a cache-busting `?_=1721815262`. `page_size` above the 100 maximum is **clamped, not rejected**. There is no multi-value syntax: `?category=passport,photograph` is one invalid value, not two valid ones, and returns 400.
- **Pagination:** page-number based. `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `count` is the **total across all pages**, not the rows in `data`. `next`/`previous` are absolute URLs (scheme + host) or `null`. Applied to `GET /files/` only — **the version-chain endpoint is not paginated** and returns its own `meta: { count }`.
- **IDs:** UUID strings, unquoted and unmarked in the shapes below — a field with no type marker is a string. **Every per-file route** takes the file's UUID `id` in its path; the list and upload routes take none. There is no lookup by filename or by checksum path; `?checksum=` on the list is the closest equivalent.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. The list is newest-created first. The version chain is **oldest first**, which is the opposite direction, deliberately: a chain is read as a history.
- **Times.** `created_at`, `updated_at`, `reviewed_at`, `archived_at`, and `superseded_at` are ISO 8601 UTC. **Three carry a Bikram Sambat sibling** (§39.4) — `created_at_bs`, `reviewed_at_bs`, `archived_at_bs` — each an object with `year`, `month`, `day`, `month_name_en`, `month_name_np`, `display_en`, `display_np`, or `null` while its Gregorian field is null. `updated_at` and `superseded_at` have **no** sibling. There is **no `?fiscal_year=` filter** on the list.
- **Empty text fields are `""`, never `null`.** The nullable fields are exactly those marked `?` in §4 — nine of them: `replaces`, `superseded_at`, `superseded_by_username`, `reviewed_at`, `reviewed_at_bs`, `reviewed_by_username`, `archived_at`, `archived_at_bs`, and `archived_by_username`. Every other field is always present and non-null.

## 4. Models

**UploadedFile** — `{ id, owner_type:[enum], owner_id, category:[enum], upload_source:[enum], original_filename, content_type, size_bytes:int, checksum_sha256, version_number:int, replaces?, is_current:bool, superseded_at?, superseded_by_username?, verification_status:[enum], is_verified:bool, rejection_reason, reviewed_at?, reviewed_at_bs?:json, reviewed_by_username?, is_archived:bool, archive_reason, archived_at?, archived_at_bs?:json, archived_by_username?, notes, uploaded_by_username, created_at, created_at_bs:json, updated_at }`

- **One shape for list, detail, upload, replace, and every lifecycle action.** There is no large column to withhold from a list — the bytes are not in the row — so a second shape would exist only to drift from this one.
- **There is no `file` field and there never will be.** No path, no URL. Use the download endpoint.
- `owner_type` names which of the five owner kinds this file belongs to; `owner_id` is that record's UUID. **Exactly one owner always, never zero and never two** — enforced by a database constraint, not only by validation.
- `is_current` (nothing has replaced this file) and `is_archived` (it is out of active use) are **independent**. A file can be archived and current, or superseded and not archived. Neither implies the other, and a UI that collapses them will misreport version chains.
- `replaces` is the id of the file this one superseded, or `null` for a v1.
- `checksum_sha256` is a lowercase hex SHA-256 of the bytes. **Duplicates are permitted** — two rows may share it.
- **`upload_source` is asserted by the caller, not verified.** Any client may send `system_generated`; nothing checks it. Treat it as a label the uploader chose, not as provenance. `uploaded_by_username` is the trustworthy field.
- **Actors are usernames, not ids.** `uploaded_by_username`, `reviewed_by_username`, `archived_by_username`, and `superseded_by_username` are strings with no user UUID beside them, so you cannot link to a profile or join safely on them. This matches every other module in the project — see §9.
- **A brand-new upload always looks like this:** `version_number: 1`, `replaces: null`, `is_current: true`, `superseded_at: null`, `superseded_by_username: null`, `verification_status: "pending"`, `is_verified: false`, and every review and archive field null-or-empty. The two worked examples below are mid-chain; this paragraph is the shape of the response you get from the endpoint you will call first.

### Worked examples

A verified passport scan, replacing an earlier upload:

```json
{
  "id": "8f14e45f-ea22-4a7f-9f0a-1c2b3d4e5f60",
  "owner_type": "applicant",
  "owner_id": "3c9a1b77-0d5e-4a2c-9b8f-77e1a4c6d210",
  "category": "passport",
  "upload_source": "staff_upload",
  "original_filename": "sita_passport_rescan.pdf",
  "content_type": "application/pdf",
  "size_bytes": 842118,
  "checksum_sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "version_number": 2,
  "replaces": "b21c0f9e-33aa-4c1d-8e77-5510aa9f3c41",
  "is_current": true,
  "superseded_at": null,
  "superseded_by_username": null,
  "verification_status": "verified",
  "is_verified": true,
  "rejection_reason": "",
  "reviewed_at": "2026-07-24T11:20:41Z",
  "reviewed_at_bs": {
    "year": 2083, "month": 4, "day": 9,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 9", "display_np": "२०८३ श्रावण ९"
  },
  "reviewed_by_username": "admin.rita",
  "is_archived": false,
  "archive_reason": "",
  "archived_at": null,
  "archived_at_bs": null,
  "archived_by_username": null,
  "notes": "Re-scanned at 300dpi; the first upload was unreadable on page 2.",
  "uploaded_by_username": "lm.bikash",
  "created_at": "2026-07-24T10:58:03Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 9,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 9", "display_np": "२०८३ श्रावण ९"
  },
  "updated_at": "2026-07-24T11:20:41Z"
}
```

Its predecessor, still readable and still downloadable:

```json
{
  "id": "b21c0f9e-33aa-4c1d-8e77-5510aa9f3c41",
  "owner_type": "applicant",
  "owner_id": "3c9a1b77-0d5e-4a2c-9b8f-77e1a4c6d210",
  "category": "passport",
  "upload_source": "staff_upload",
  "original_filename": "sita_passport.pdf",
  "content_type": "application/pdf",
  "size_bytes": 218440,
  "checksum_sha256": "4a44dc15364204a80fe80e9039455cc1608281820fe2b24f1e5233ade6af1dd5",
  "version_number": 1,
  "replaces": null,
  "is_current": false,
  "superseded_at": "2026-07-24T10:58:03Z",
  "superseded_by_username": "lm.bikash",
  "verification_status": "rejected",
  "is_verified": false,
  "rejection_reason": "Page 2 is unreadable.",
  "reviewed_at": "2026-07-24T09:41:12Z",
  "reviewed_at_bs": {
    "year": 2083, "month": 4, "day": 9,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 9", "display_np": "२०८३ श्रावण ९"
  },
  "reviewed_by_username": "admin.rita",
  "is_archived": false,
  "archive_reason": "",
  "archived_at": null,
  "archived_at_bs": null,
  "archived_by_username": null,
  "notes": "",
  "uploaded_by_username": "lm.bikash",
  "created_at": "2026-07-24T09:12:55Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 9,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 9", "display_np": "२०८३ श्रावण ९"
  },
  "updated_at": "2026-07-24T10:58:03Z"
}
```

## 5. Enums

- `UploadedFile.owner_type`: `applicant` | `journey` | `offer` | `document` | `snapshot`
- `UploadedFile.category`: `passport` | `photograph` | `academic_transcript` | `academic_certificate` | `test_score_report` | `offer_letter` | `financial` | `sponsorship` | `signature_image` | `generated_document` | `other`
- `UploadedFile.upload_source`: `staff_upload` | `system_generated`
- `UploadedFile.verification_status`: `pending` | `verified` | `rejected` — **but the verify action accepts only `verified` and `rejected`.** `pending` is a starting state, not a verdict, and cannot be set back.
- Accepted file extensions (not a response enum — an upload rule): `pdf` | `jpg` | `jpeg` | `png` | `webp` | `docx` | `xlsx`

## 6. Dependency order

- An `UploadedFile` needs exactly one of: an `Applicant`, an `ApplicantJourney`, an `Offer`, a `Document`, or a `DocumentSnapshot` (all **external modules**) — the record must already exist.
- An `ApplicantJourney` needs an `Applicant` (external module).
- An `Offer` needs an `ApplicantJourney` (external module).
- A `DocumentSnapshot` needs a `Document` (external module).
- A version-2 file needs the version-1 file it replaces.
- A verdict needs a file; an archive needs a file; a restore needs an archived file.

**Start here:** nothing in this module can be created first. Create the owning record in its own module, then `POST /api/v1/files/` against it.

## 7. Endpoints

### UploadedFile — `/api/v1/files/`

**Use it when:** rendering any per-record files panel (applicant, journey, offer, document, snapshot), the review queue, a global file search, or the file detail screen.

**Methods:**
- `GET /api/v1/files/` — list, paginated (`uploaded_files.file.list`)
- `POST /api/v1/files/` — upload, `multipart/form-data` (`uploaded_files.file.upload`)
- `GET /api/v1/files/<file_id>/` — retrieve (`uploaded_files.file.read`)
- `PATCH /api/v1/files/<file_id>/` — edit (`uploaded_files.file.update`)

**Send (upload — `multipart/form-data`):**
- exactly one of `applicant`, `journey`, `offer`, `document`, `snapshot` — the owning record's UUID
- `category` — required, one of the eleven values in §5
- `file` — required, the file part, ≤ 10 MB
- `upload_source` — optional, defaults to `staff_upload`
- `notes` — optional free text

**Send (edit — `application/json`):**
- `category` and/or `notes`. **Nothing else.** Any other field is refused by name with `UPLOADED_FILES_FIELD_IMMUTABLE`, not silently dropped

**Query parameters (list):**
- `applicant`, `journey`, `offer`, `document`, `snapshot` — UUID, narrows to that record's files
- `category`, `verification_status`, `upload_source` — enum values from §5
- `is_archived` — boolean. **Omitting it returns archived files too**; pass `false` for the active-only view
- `is_current` — boolean. `false` returns only superseded versions
- `checksum` — exact SHA-256 match, for finding duplicates
- `search` — substring of `original_filename` only

**Returns:** `UploadedFile` | `list[UploadedFile]`

**Requires state:**
- list, retrieve — nothing beyond authority. A `lead_manager` sees no `document`- or `snapshot`-owned rows at all
- upload — the owning record must already exist in its own module; a `lead_manager` may not name a `document` or a `snapshot`
- **edit — the file must exist and must NOT be archived.** An archived file returns `UPLOADED_FILES_FILE_ARCHIVED`; restore it first

**Side effects:**
- upload writes a file to the platform's storage and appends a `file_uploaded` event to the `audit` log
- edit appends a `file_updated` event, **unless nothing actually changed** — a no-op `PATCH` returns 200 and writes no event
- list and retrieve have no side effects

**Notes:**
- The stored filename is **not** the one you sent. `original_filename` keeps yours; the file on disk is a UUID. This is not configurable.
- `content_type` is derived from the extension after the leading bytes are checked against it. **The `Content-Type` you set on the multipart part is ignored.**
- Extension checking uses the **last** dot-segment, so `passport.pdf.exe` is an `exe` and is refused.
- Every new file is `pending`, including `system_generated` ones.
- **Duplicates are allowed.** Uploading the same bytes twice succeeds and produces two rows with the same `checksum_sha256`.
- `search` covers `original_filename` **only** — not `notes`, and there is no Devanagari/romanized search here as there is on other modules. A file named in Devanagari will not be found by a Roman-script query.
- A recognised filter with a bad value is a 400; an unrecognised parameter is ignored.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `superadmin` on any method; **or a `lead_manager` uploading against a `document` or `snapshot` owner.** Both authorities are otherwise permitted on all four methods, edit included
- `UPLOADED_FILES_FILE_NOT_FOUND` (404) — no file with that id, **or a `lead_manager` addressing a `document`- or `snapshot`-owned file**, which is reported as absent rather than forbidden
- `UPLOADED_FILES_OWNER_REQUIRED` (400) — zero or more than one owner supplied
- `UPLOADED_FILES_OWNER_NOT_FOUND` (400) — the named owner record does not exist; `details` names which field failed
- `UPLOADED_FILES_FILE_TOO_LARGE` (400) — over 10 MB. **10 MB means 10 485 760 bytes** (10 × 1024 × 1024)
- `UPLOADED_FILES_FILE_EMPTY` (400) — zero bytes. A separate code from the one above, so a UI never tells a user their empty file was too big
- `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED` (400) — extension outside the seven accepted
- `UPLOADED_FILES_FILE_CONTENT_MISMATCH` (400) — the bytes disagree with the extension
- `UPLOADED_FILES_FIELD_IMMUTABLE` (400) — a `PATCH` carried anything but `category`/`notes`
- `UPLOADED_FILES_FILE_ARCHIVED` (400) — a `PATCH` against an archived file; restore it first
- `VALIDATION_ERROR` (400) — missing `file`, unknown `category`, malformed UUID, bad query parameter

**Error precedence on upload**, so you know which one to expect when a request is wrong in more than one way: serializer validation (missing `file`, unknown `category`, malformed UUID, **wrong owner count**) → owner visibility for this authority → owner existence → size/empty → extension → content signature.

**On `replace`, the precedence is:** file exists → owner visibility → archived → already superseded → then the same four upload checks in the same order. Both `UPLOADED_FILES_FILE_ARCHIVED` and `UPLOADED_FILES_ALREADY_SUPERSEDED` can be true at once; you will be told about the archive first.

**A note on the missing-owner case, because it has two plausible codes and only one fires.** Sending zero or two owner fields is caught by request validation and returns **`VALIDATION_ERROR`** with the message under `details.owner`, exactly as shown in §3. `UPLOADED_FILES_OWNER_REQUIRED` is a registered code for the same condition that **no HTTP path can reach** — see §9. Handle `VALIDATION_ERROR`.

### File download — `GET /api/v1/files/<file_id>/download/`

**Use it when:** the user clicks a file to open or save it. This is the **only** way to obtain a file's contents.

**Methods:**
- `GET /api/v1/files/<file_id>/download/` (`uploaded_files.file.download`)

**Send:** none

**Returns:** the raw bytes — **not JSON, not the `UploadedFile` shape.** `Content-Type` is the stored type, `Content-Disposition` is `attachment; filename="<original_filename>"`, plus `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store`.

**Requires state:** the file must exist and its bytes must be present on the platform's storage.

**Side effects:** appends a `file_downloaded` event to the `audit` log, **before** the transfer begins — an aborted download is still recorded. This is the only read in the whole API that writes an audit event.

**Notes:**
- **Archived files and superseded files are both still downloadable.** Archival is a lifecycle state, not a deletion, and keeping old versions readable is the point of the version chain.
- The response is always an attachment, never inline. A browser will not render it in place; plan for a download rather than an embedded preview.
- There is no thumbnail, no preview, and **no documented `Content-Length`, `ETag`, `Last-Modified`, or `Accept-Ranges`** — assume a whole-file transfer with no resume and no reliable progress bar.
- A `lead_manager` downloading a `document`- or `snapshot`-owned file gets **404**, not 403.
- Requires the same bearer token as everything else — you cannot put this URL in an `<img src>` and expect it to load.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `superadmin`
- `UPLOADED_FILES_FILE_NOT_FOUND` (404) — no file with that id
- `UPLOADED_FILES_FILE_BYTES_MISSING` (404) — **the record exists and its bytes do not.** This is a platform fault, not a client one; no retry will fix it. Surface it as "this file could not be retrieved" and report it, rather than treating it as a missing record

### File versions — `GET /api/v1/files/<file_id>/versions/`

**Use it when:** rendering the replacement history on a file detail screen.

**Methods:**
- `GET /api/v1/files/<file_id>/versions/` (`uploaded_files.file.versions`)

**Send:** none

**Returns:** `list[UploadedFile]` — the whole chain containing this file, **oldest first**. `meta` carries `count` only.

**Requires state:** the file must exist.

**Side effects:** none

**Notes:**
- **Not paginated.** `page`/`page_size` are ignored.
- The chain reads identically from any member, so you may call it with a superseded id and still get the full history including what replaced it.
- A file that has never been replaced returns a chain of one — itself. That is a valid result, not an empty state.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `superadmin`
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)

### File replace — `POST /api/v1/files/<file_id>/replace/`

**Use it when:** the applicant supplies a better copy of a document already on file — a re-scan, a corrected version, a certified copy.

**Methods:**
- `POST /api/v1/files/<file_id>/replace/` — `multipart/form-data` (`uploaded_files.file.replace`)

**Send:**
- `file` — required, the new bytes, ≤ 10 MB, same rules as upload
- `notes` — optional free text for the **new** file

**Returns:** `UploadedFile` — **the successor**, a new record with a new id, not the file you addressed. 201.

**Requires state:** the addressed file must exist, must not be archived, and must not already have been replaced.

**Side effects:**
- creates a **second** file record and writes a second file to storage — the predecessor's bytes are kept, not overwritten
- sets `superseded_at`/`is_current: false` on the predecessor; nothing else about it changes
- appends a `file_replaced` event to the `audit` log

**Notes:**
- **The successor carries no owner or category of its own** — both are inherited. There is no way to move a file to another record through this endpoint, and no way to reclassify it; sending `applicant` or `category` here has no effect.
- **The successor is always `pending`, even when the predecessor was `verified`.** A replacement is a different artefact and must be reviewed again. Do not assume a verified file stays verified across a replace.
- A file may be replaced **once**. To supersede again, address the current version — `GET .../versions/` and take the last entry.
- The predecessor keeps its own verdict and rejection reason. A rejected v1 under a pending v2 is normal and expected.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `superadmin`; `lead_manager` **is** permitted here
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_ALREADY_SUPERSEDED` (400) — this file has already been replaced
- `UPLOADED_FILES_FILE_ARCHIVED` (400) — restore it first
- `UPLOADED_FILES_FILE_TOO_LARGE` (400)
- `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED` (400)
- `UPLOADED_FILES_FILE_CONTENT_MISMATCH` (400)
- `VALIDATION_ERROR` (400) — no `file` part

### File review — `POST /api/v1/files/<file_id>/verify/`

**Use it when:** an Admin works the review queue (`GET /files/?verification_status=pending`) and accepts or refuses a document.

**Methods:**
- `POST /api/v1/files/<file_id>/verify/` (`uploaded_files.file.verify`)

**Send:**
- `status` — required, `verified` or `rejected`. **`pending` is rejected**
- `reason` — required when `status` is `rejected`, ignored otherwise

**Returns:** `UploadedFile`

**Requires state:** the file must exist and must not be archived. **`admin` authority.** A file may be in any verification state, including one already reviewed.

**Side effects:** sets `reviewed_at`/`reviewed_by_username`, appends a `file_reviewed` event to the `audit` log.

**Notes:**
- **A verdict may be revised.** There is no lock — an Admin who rejected the wrong file can verify it afterwards, and the audit log carries the sequence.
- Re-verifying a rejected file **clears `rejection_reason`**, so a stale refusal never sits under a current acceptance.
- **Verification gates nothing.** No endpoint in this API — or anywhere else in Grandway — refuses to proceed because a file is unverified. Treat it as a review record, not a precondition, and do not build a flow that expects the backend to block on it.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — **a `lead_manager` as well as a `superadmin`**
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_REJECTION_REASON_REQUIRED` (400) — rejecting with no reason
- `UPLOADED_FILES_FILE_ARCHIVED` (400)
- `VALIDATION_ERROR` (400) — `status` missing, or a value other than `verified`/`rejected`

### File archive — `POST /api/v1/files/<file_id>/archive/`

**Use it when:** a file is no longer part of active work but must remain on record — a superseded document, a wrong upload, a closed matter.

**Methods:**
- `POST /api/v1/files/<file_id>/archive/` (`uploaded_files.file.archive`)

**Send:**
- `reason` — **required**

**Returns:** `UploadedFile` with `is_archived: true`

**Requires state:** the file must exist and must not already be archived. **`admin` authority.**

**Side effects:** sets `archived_at`/`archived_by_username`/`archive_reason`, appends a `file_archived` event to the `audit` log.

**Notes:**
- **Nothing is deleted.** The bytes stay and the file is still downloadable.
- **The version chain is untouched.** An archived v1 is still v1 and still v2's predecessor.
- An archived file refuses `PATCH`, `replace`, and `verify` until it is restored.
- This is the closest thing to deletion the API offers. There is no harder option.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `lead_manager` or a `superadmin`
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_ALREADY_ARCHIVED` (400)
- `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED` (400)
- `VALIDATION_ERROR` (400) — `reason` missing or blank

### File restore — `POST /api/v1/files/<file_id>/restore/`

**Use it when:** a file was archived in error, or becomes relevant again.

**Methods:**
- `POST /api/v1/files/<file_id>/restore/` (`uploaded_files.file.restore`)

**Send:**
- `note` — optional. **No reason is required**, unlike archiving

**Returns:** `UploadedFile` with `is_archived: false`

**Requires state:** the file must exist and must currently be archived. **`admin` authority.**

**Side effects:** clears all three archive fields, appends a `file_restored` event to the `audit` log.

**Notes:**
- `archive_reason` is cleared to `""` and `archived_at`/`archived_by_username` to `null` — **the record keeps no trace of having been archived.** The history lives in the `audit` log, so do not expect to reconstruct "was this ever archived" from the file payload.
- **`note` does not appear in the response and is not stored on the record.** It is written into the audit event as its reason. Do not send anything through it that a user expects to read back.

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `lead_manager` or a `superadmin`
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_NOT_ARCHIVED` (400)

## 8. Flows

**Attach a passport to an applicant and get it approved**

1. The applicant already exists in the `applicants` module — you need its UUID.
2. `POST /api/v1/files/` with `applicant=<applicant_id>`, `category=passport`, `file=@passport.pdf` (multipart). → 201, file id `F1`, `verification_status: "pending"`.
   - 400 `UPLOADED_FILES_OWNER_NOT_FOUND` → the applicant id is wrong; `details.applicant` says so.
   - 400 `UPLOADED_FILES_FILE_CONTENT_MISMATCH` → the file is not really a PDF; ask for a real one.
3. An **Admin** opens the review queue: `GET /api/v1/files/?verification_status=pending`.
4. `POST /api/v1/files/F1/verify/` with `{"status": "verified"}`. → 200, `is_verified: true`.
   - 403 → the caller is a Lead Manager; only an Admin may do this.
5. The Applicant Detail files panel reads `GET /api/v1/files/?applicant=<applicant_id>&is_archived=false`.

**Reject a file and take a better copy**

1. `POST /api/v1/files/F1/verify/` with `{"status": "rejected", "reason": "Page 2 is unreadable."}` → 200.
   - 400 `UPLOADED_FILES_REJECTION_REASON_REQUIRED` → the reason is mandatory; do not send a rejection without one.
2. The applicant supplies a re-scan. `POST /api/v1/files/F1/replace/` with `file=@rescan.pdf` (multipart). → 201, **new** file id `F2`, `version_number: 2`, `replaces: F1`, `verification_status: "pending"`.
   - 400 `UPLOADED_FILES_ALREADY_SUPERSEDED` → `F1` was already replaced; call `GET /api/v1/files/F1/versions/` and address the last entry.
3. `POST /api/v1/files/F2/verify/` with `{"status": "verified"}` → 200. `F1` keeps its rejection; both remain readable.
4. `GET /api/v1/files/F2/versions/` → `[F1, F2]`, oldest first.

**Download a document**

1. `GET /api/v1/files/F2/` → metadata. There is no URL in it.
2. `GET /api/v1/files/F2/download/` with the bearer token → the raw bytes as an attachment named `rescan.pdf`.
   - 404 `UPLOADED_FILES_FILE_BYTES_MISSING` → a platform fault; the record exists but its bytes are gone. Do not retry; report it.
3. An audit event is recorded for the download whether or not the transfer completes.

**Retire a file without losing it**

1. `POST /api/v1/files/F1/archive/` with `{"reason": "Superseded by a certified copy."}` → 200, `is_archived: true`.
   - 403 → Admin authority only.
2. `F1` disappears from `?is_archived=false` views, and remains in unfiltered ones. It is **still downloadable** and still in `F2`'s version chain.
3. `PATCH /api/v1/files/F1/` now returns 400 `UPLOADED_FILES_FILE_ARCHIVED`.
4. `POST /api/v1/files/F1/restore/` → 200, all three archive fields cleared.

**Attach the letter an offer came from**

1. The offer already exists in the `offers` module — you need its UUID.
2. `POST /api/v1/files/` with `offer=<offer_id>`, `category=offer_letter`, `file=@offer.pdf`. → 201.
3. The Offer Detail supporting-files section reads `GET /api/v1/files/?offer=<offer_id>`.
   - Note that **the `offers` module itself knows nothing about this file.** Its endpoints return no file references; you must call this module separately.

## 9. Gaps

- **No other module links to a file.** `applicants` has no photograph field, `offers` has no attachment field, `documents` has no attachment field, `document_history` has no generated-file field. There is no "primary photo", no "the offer letter", and no way to mark one file as the canonical one for a record — only a list filtered by owner and category. If you need "the applicant's photograph", you must take the newest `category=photograph` file yourself and decide what to do when there are two.
- **`clients.logo_url` and `document_templates.signature_image_url` are still plain URLs** to hosts this API knows nothing about. Neither has been migrated to a file record, and neither module has an upload endpoint. A signature image is still a link that can rot with nothing reporting it.
- **Verification gates nothing, anywhere.** No endpoint in Grandway refuses an operation because a file is `pending` or `rejected`. If your product requires "the offer cannot be accepted until the passport is verified", that rule does not exist in the backend and must not be assumed.
- **A file belongs to exactly one record.** There is no way to attach one scan to both an applicant and a journey. Doing it means uploading twice, producing two rows with the same `checksum_sha256`.
- **`education` and `test_scores` are not owner types**, because those modules do not exist yet. A transcript or a test-score report currently attaches to the applicant. When those modules ship, existing files will **not** be re-pointed automatically.
- **No bulk upload.** One file per request; the server rejects a request carrying more than one file part.
- **No preview, thumbnail, page count, or text extraction.** The API knows a file's size, type, and checksum, and nothing about its contents.
- **No virus scanning.** The type check stops a renamed executable, not a malicious document.
- **No range requests / resumable download are documented.** Assume a whole-file transfer.
- **Auth failure bodies for 401 are not enumerated here** — no token, an expired token, and a revoked session all return the `authenticate` module's codes, which this contract does not restate. See that module's `INTEGRATION.md`.
- **Throttling is the project default** (1000 requests/hour per user), with no tighter scope on upload or download despite each moving up to 10 MB. A client that batch-uploads will hit the shared limit and receive the project-wide throttle response, which this contract does not document.
- **No `?fiscal_year=` filter and no date-range filter of any kind** on the list. You cannot ask for "files received this month" server-side.
- **No sort control.** The list is newest-first and the version chain is oldest-first, both fixed.
- **The audit trail is not readable through this module.** Every write and every download writes an event, but there is no endpoint here to read them; that lives in the `audit` module and is not cross-referenced by file id in this contract.
- **Three registered codes have no reachable HTTP path** — request validation catches each case first and returns `VALIDATION_ERROR`. Do not write handling for any of them: `UPLOADED_FILES_FILE_MISSING` (no file part), `UPLOADED_FILES_VERIFICATION_STATUS_INVALID` (a verdict outside `verified`/`rejected`), and `UPLOADED_FILES_OWNER_REQUIRED` (zero or two owner fields).
- **No owner rollup, and this is the biggest practical cost of the one-way relationship.** "Everything on file for this applicant" is not one call: files hang off the applicant, each of their journeys, each offer on each journey, and each document and snapshot. There is no `owner_type` filter, no multi-value filter syntax, and no rollup endpoint — you fan out one request per owner id and merge client-side. For most screens the per-record panel (`?applicant=<id>`) is what you actually want, and that is one call.
- **Nothing marks a primary file.** There is no "the photograph" or "the passport" — filtering by category can return several, and the newest-current-one convention is yours to implement, not a backend rule.
- **CORS and browser transport are not documented anywhere**, in this contract or the project one. This module's design forces two browser-specific things on a web client — a multipart upload with a bearer header, and fetching bytes as a blob to display them — and neither file states whether cross-origin requests are permitted, from which origins, or which response headers are exposed. Confirm with the backend before building either.
- **No idempotency key on upload.** Duplicates are explicitly allowed, so a 10 MB upload that times out after the server stored it produces a second row on retry, and the only way to notice is a `?checksum=` lookup afterwards. There is no request-level de-duplication.
- **No throttle documentation.** The project default (1000 requests/hour per user) applies with no tighter scope on upload or download despite each moving up to 10 MB. The 429 body and any `Retry-After` are not specified here.
- **Maximum lengths for `notes`, `reason`, and `original_filename` are not published**, nor are the exact message strings for any code. Do not build a client-side character counter against a guess.
- **The extension → `content_type` mapping is not published.** You know the seven accepted extensions and that `content_type` is derived from them, but not which string each produces — so a file-type icon keyed on `content_type` needs the values confirmed.
