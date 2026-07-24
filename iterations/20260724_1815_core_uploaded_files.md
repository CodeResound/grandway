# Session 20260724_1815 — uploaded_files, core

## Uploaded Files

## 1. Module

- **Name:** Uploaded Files
- **Base path:** `/api/v1/files/`
- **Auth:** Bearer access JWT on every endpoint. `admin` and `lead_manager` may list, read, edit, upload, replace, download, and read version chains; **only `admin`** may verify, archive, or restore; `superadmin` is refused everywhere. A file owned by a `document` or a `snapshot` is Admin-only in every respect.

## 2. Conventions

- **Response:** `{ "success": true, "message": "...", "data": {...}, "meta": {...} }`
- **Error:** `{ "success": false, "error": { "code": "...", "message": "...", "details": {...} }, "meta": {...} }`. `details` is always present, `{}` when there are no field-level errors.
- **Auth failures:** 403 `UPLOADED_FILES_ACTOR_FORBIDDEN` with `details: {}` for a refused authority. 401 codes belong to `authenticate` and are not documented here. A `lead_manager` addressing a `document`- or `snapshot`-owned file gets **404**, not 403.
- **Pagination:** `page`, `page_size` (default 20, max 100, clamped not rejected). `data` is a bare array. `meta` carries `count`, `page`, `page_size`, `next`, `previous`. Applied to `GET /files/` only — the version-chain endpoint is unpaginated and returns `meta: { count }`.
- **IDs:** UUID strings.
- **Times:** ISO 8601 UTC. `created_at`, `reviewed_at`, and `archived_at` each carry a Bikram Sambat sibling (`*_bs`) object; `updated_at` and `superseded_at` do not.
- **List/search/filter params:** `applicant`, `journey`, `offer`, `document`, `snapshot`, `category`, `verification_status`, `upload_source`, `is_archived`, `is_current`, `checksum`, `search`. A recognised parameter with an invalid value is a 400; an unrecognised parameter is ignored. No sort control, no date-range filter.

## 3. Models

**UploadedFile** — `{ id, owner_type:[enum], owner_id, category:[enum], upload_source:[enum], original_filename, content_type, size_bytes:int, checksum_sha256, version_number:int, replaces?, is_current:bool, superseded_at?, superseded_by_username?, verification_status:[enum], is_verified:bool, rejection_reason, reviewed_at?, reviewed_at_bs?:json, reviewed_by_username?, is_archived:bool, archive_reason, archived_at?, archived_at_bs?:json, archived_by_username?, notes, uploaded_by_username, created_at, created_at_bs:json, updated_at }`

- Exactly one owner always — never zero, never two.
- There is no `file` field in any response. No path, no URL.
- `is_current` and `is_archived` are independent.
- `search` covers `original_filename` only.

## 4. Enums

- `UploadedFile.owner_type`: `applicant` | `journey` | `offer` | `document` | `snapshot`
- `UploadedFile.category`: `passport` | `photograph` | `academic_transcript` | `academic_certificate` | `test_score_report` | `offer_letter` | `financial` | `sponsorship` | `signature_image` | `generated_document` | `other`
- `UploadedFile.upload_source`: `staff_upload` | `system_generated`
- `UploadedFile.verification_status`: `pending` | `verified` | `rejected` — the verify action accepts only `verified` and `rejected`
- Accepted upload extensions: `pdf` | `jpg` | `jpeg` | `png` | `webp` | `docx` | `xlsx`

## 5. Dependency order

- `UploadedFile` needs exactly one of `Applicant`, `ApplicantJourney`, `Offer`, `Document`, or `DocumentSnapshot` (all external modules)
- `ApplicantJourney` needs `Applicant` (external module)
- `Offer` needs `ApplicantJourney` (external module)
- `DocumentSnapshot` needs `Document` (external module)
- A version-2 file needs the version-1 file it replaces
- A verdict, an archive, and a restore each need a file; a restore needs an archived one

**Start here:** the owning record, in its own module. Nothing in this module can be created first.

## 6. Endpoints

### UploadedFile — `/api/v1/files/`

**Use it when:** rendering any per-record files panel, the review queue, a global file search, or the file detail screen.

**Methods:**
- `GET /api/v1/files/` (`uploaded_files.file.list`)
- `POST /api/v1/files/` — `multipart/form-data` (`uploaded_files.file.upload`)
- `GET /api/v1/files/<file_id>/` (`uploaded_files.file.read`)
- `PATCH /api/v1/files/<file_id>/` (`uploaded_files.file.update`)

**Send (upload):**
- exactly one of `applicant`, `journey`, `offer`, `document`, `snapshot`
- `category` — required
- `file` — required, ≤ 10 MB
- `upload_source` — optional, defaults to `staff_upload`
- `notes` — optional

**Send (update):**
- `category` and/or `notes` only

**Returns:** `UploadedFile` | `list[UploadedFile]`

**Notes:**
- The stored filename is a fresh UUID; `original_filename` keeps the client's
- `content_type`, `size_bytes`, `checksum_sha256`, `version_number`, and every lifecycle field are set by the server
- Every new file is `pending`, `version_number` 1, `is_current` true
- Duplicates are permitted — two rows may share a checksum
- `upload_source` is caller-asserted and unverified
- Omitting `is_archived` returns archived files too

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `superadmin`, or a `lead_manager` uploading against a `document`/`snapshot`
- `UPLOADED_FILES_FILE_NOT_FOUND` (404) — no such file, or a `lead_manager` addressing a restricted one
- `UPLOADED_FILES_OWNER_NOT_FOUND` (400)
- `UPLOADED_FILES_FILE_TOO_LARGE` (400)
- `UPLOADED_FILES_FILE_EMPTY` (400)
- `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED` (400)
- `UPLOADED_FILES_FILE_CONTENT_MISMATCH` (400)
- `UPLOADED_FILES_FIELD_IMMUTABLE` (400)
- `UPLOADED_FILES_FILE_ARCHIVED` (400)
- `VALIDATION_ERROR` (400) — includes the zero-or-two-owner case, keyed under `details.owner`

### File download — `GET /api/v1/files/<file_id>/download/`

**Use it when:** the user opens or saves a file. The only way to obtain bytes.

**Methods:**
- `GET /api/v1/files/<file_id>/download/` (`uploaded_files.file.download`)

**Send:** none

**Returns:** the raw bytes, not JSON. `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`.

**Notes:**
- Archived and superseded files are both still downloadable
- Writes an audit event before the transfer starts — the only audited read in the API
- Needs the bearer token, so the URL cannot go in an `<img src>`
- No documented `Content-Length`, `ETag`, or range support

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403)
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_FILE_BYTES_MISSING` (404) — the row exists and its bytes do not; a platform fault

### File versions — `GET /api/v1/files/<file_id>/versions/`

**Use it when:** rendering replacement history on a file detail screen.

**Methods:**
- `GET /api/v1/files/<file_id>/versions/` (`uploaded_files.file.versions`)

**Send:** none

**Returns:** `list[UploadedFile]`, oldest first. `meta` carries `count` only.

**Notes:**
- Not paginated
- Reads identically from any member of the chain, including a superseded one
- A file never replaced returns a chain of one

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403)
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)

### File replace — `POST /api/v1/files/<file_id>/replace/`

**Use it when:** a better copy of a document already on file arrives.

**Methods:**
- `POST /api/v1/files/<file_id>/replace/` — `multipart/form-data` (`uploaded_files.file.replace`)

**Send:**
- `file` — required
- `notes` — optional, for the new file

**Returns:** `UploadedFile` — the successor, a new record with a new id. 201.

**Notes:**
- Owner and category are inherited; sending either has no effect
- The successor is always `pending`, even when the predecessor was `verified`
- The predecessor keeps its bytes, its verdict, and its reason
- A file may be replaced once

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403)
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_ALREADY_SUPERSEDED` (400)
- `UPLOADED_FILES_FILE_ARCHIVED` (400)
- `UPLOADED_FILES_FILE_TOO_LARGE` (400)
- `UPLOADED_FILES_FILE_EMPTY` (400)
- `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED` (400)
- `UPLOADED_FILES_FILE_CONTENT_MISMATCH` (400)
- `VALIDATION_ERROR` (400)

### File review — `POST /api/v1/files/<file_id>/verify/`

**Use it when:** an Admin works the review queue and accepts or refuses a document.

**Methods:**
- `POST /api/v1/files/<file_id>/verify/` (`uploaded_files.file.verify`)

**Send:**
- `status` — required, `verified` or `rejected`
- `reason` — required when rejecting

**Returns:** `UploadedFile`

**Notes:**
- `pending` cannot be set
- A verdict may be revised; re-verifying clears a stale rejection reason
- Verification gates nothing anywhere in the platform
- Admin authority only

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403) — a `lead_manager` as well as a `superadmin`
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_REJECTION_REASON_REQUIRED` (400)
- `UPLOADED_FILES_FILE_ARCHIVED` (400)
- `VALIDATION_ERROR` (400)

### File archive — `POST /api/v1/files/<file_id>/archive/`

**Use it when:** a file leaves active work but must stay on record.

**Methods:**
- `POST /api/v1/files/<file_id>/archive/` (`uploaded_files.file.archive`)

**Send:**
- `reason` — required

**Returns:** `UploadedFile` with `is_archived: true`

**Notes:**
- Nothing is deleted; the bytes stay and the file is still downloadable
- The version chain is untouched
- An archived file refuses `PATCH`, `replace`, and `verify`
- Admin authority only

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403)
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_ALREADY_ARCHIVED` (400)
- `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED` (400)
- `VALIDATION_ERROR` (400)

### File restore — `POST /api/v1/files/<file_id>/restore/`

**Use it when:** a file was archived in error or becomes relevant again.

**Methods:**
- `POST /api/v1/files/<file_id>/restore/` (`uploaded_files.file.restore`)

**Send:**
- `note` — optional. No reason required

**Returns:** `UploadedFile` with `is_archived: false`

**Notes:**
- All three archive fields are cleared; the record keeps no trace of having been archived
- `note` is written to the audit event, not to the record, and is not readable back
- Admin authority only

**Errors:**
- `UPLOADED_FILES_ACTOR_FORBIDDEN` (403)
- `UPLOADED_FILES_FILE_NOT_FOUND` (404)
- `UPLOADED_FILES_NOT_ARCHIVED` (400)

## 7. Flows

**Attach a document to an applicant and get it approved**

1. The applicant exists in the `applicants` module — take its id.
2. `POST /api/v1/files/` with `applicant=<applicant_id>`, `category=passport`, `file=@passport.pdf` → 201, file `F1`, `verification_status: "pending"`.
   - 400 `UPLOADED_FILES_OWNER_NOT_FOUND` → the applicant id is wrong.
   - 400 `UPLOADED_FILES_FILE_CONTENT_MISMATCH` → the file is not really a PDF.
3. An Admin opens `GET /api/v1/files/?verification_status=pending`.
4. `POST /api/v1/files/F1/verify/` with `status=verified` → 200.
   - 403 → the caller is a Lead Manager.
5. The applicant's files panel reads `GET /api/v1/files/?applicant=<applicant_id>&is_archived=false`.

**Reject a file and take a better copy**

1. `POST /api/v1/files/F1/verify/` with `status=rejected`, `reason=...` → 200.
   - 400 `UPLOADED_FILES_REJECTION_REASON_REQUIRED` → the reason is mandatory.
2. `POST /api/v1/files/F1/replace/` with the new bytes → 201, new file `F2`, `version_number: 2`, `replaces: F1`, `pending`.
   - 400 `UPLOADED_FILES_ALREADY_SUPERSEDED` → call `GET /api/v1/files/F1/versions/` and address the last entry.
3. `POST /api/v1/files/F2/verify/` with `status=verified` → 200. `F1` keeps its rejection.
4. `GET /api/v1/files/F2/versions/` → `[F1, F2]`.

**Download a document**

1. `GET /api/v1/files/F2/` → metadata, containing no URL.
2. `GET /api/v1/files/F2/download/` with the bearer token → raw bytes as an attachment.
   - 404 `UPLOADED_FILES_FILE_BYTES_MISSING` → a platform fault; do not retry.
3. An audit event is recorded whether or not the transfer completes.

**Retire a file without losing it**

1. `POST /api/v1/files/F1/archive/` with `reason=...` → 200, `is_archived: true`.
   - 403 → Admin authority only.
2. `F1` leaves `?is_archived=false` views, stays downloadable, stays in `F2`'s chain.
3. `PATCH /api/v1/files/F1/` → 400 `UPLOADED_FILES_FILE_ARCHIVED`.
4. `POST /api/v1/files/F1/restore/` → 200, all three archive fields cleared.

**Attach the letter an offer came from**

1. The offer exists in the `offers` module — take its id.
2. `POST /api/v1/files/` with `offer=<offer_id>`, `category=offer_letter` → 201.
3. The Offer Detail supporting-files section reads `GET /api/v1/files/?offer=<offer_id>`.
   - The `offers` module returns no file references; this is always a second call.

## 8. Gaps

- No module returns a file reference. `applicants` has no photograph field, `offers` no attachment field, `documents` no attachment field, `document_history` no generated-file field. Every files panel is a second call joined client-side.
- Nothing marks a primary file. Filtering by category can return several; choosing among them is a client convention.
- No owner rollup. "Every file for this applicant" spans the applicant, each journey, each offer, each document, and each snapshot — one request per owner id. No `owner_type` filter, no multi-value filter syntax.
- `clients.logo_url` and `document_templates.signature_image_url` were deliberately not migrated, and neither `Client` nor `Signatory` is an accepted owner type.
- Verification gates nothing anywhere in the platform.
- A file belongs to exactly one record. Attaching one scan to two records means uploading twice.
- `education` and `test_scores` are not owner types; those modules do not exist. Existing files will not be re-pointed when they ship.
- No bulk upload; one file per request.
- No preview, thumbnail, page count, or text extraction. No virus scanning.
- No documented `Content-Length`, `ETag`, or range support on download.
- No upload idempotency key. A timed-out upload that succeeded produces a duplicate on retry.
- CORS and browser transport are undocumented project-wide, and this module forces multipart upload and blob-based display on a web client.
- Maximum lengths for `notes`, `reason`, and `original_filename` are not published, nor is the extension → `content_type` mapping.
- 401 bodies belong to `authenticate` and are not restated here. Throttling is the project default with no tighter scope on upload or download; the 429 body is unspecified.
- `UPLOADED_FILES_FILE_MISSING`, `UPLOADED_FILES_VERIFICATION_STATUS_INVALID`, and `UPLOADED_FILES_OWNER_REQUIRED` are registered codes with no reachable HTTP path.

## Core

## 1. Module

- **Name:** Core — project-level infrastructure and the consumer entry point.
- **Base path:** n/a
- **Auth:** unchanged.

## 2. Conventions

No change. The response envelope, error shape, pagination, id type, and timestamp format are all as previously documented.

## 3. Models

No model was added or changed in `core` this session.

## 4. Enums

No enum was added or changed in `core` this session.

## 5. Dependency order

- `uploaded_files` needs `applicants`, `applicant_journeys`, `offers`, `documents`, and `document_history` (all external modules) — a file belongs to exactly one of them.

**Start here:** unchanged — `authenticate`, for a token.

## 6. Endpoints

No endpoint was added, changed, or retired in `core` this session. Settings gained `MEDIA_ROOT`, `FILE_UPLOAD_PERMISSIONS`, `FILE_UPLOAD_DIRECTORY_PERMISSIONS`, and `DATA_UPLOAD_MAX_NUMBER_FILES`; `api_urls.py` gained the `files/` include; none of that is client-visible beyond the new module's own routes.

## 7. Flows

No `core` flow changed. The project-level entry point (`core/docs/INTEGRATION.md`) gained `uploaded_files` in its app inventory and dependency graph, and a fourth access shape in its gaps section.

## 8. Gaps

- The access-model table in `core/docs/INTEGRATION.md` now lists four shapes rather than three. `uploaded_files` is the only module that additionally scopes by the owning record.
- No module points at a file. Reverse references are additive and each needs its own session.
- Nothing serves `MEDIA_ROOT`, in any environment. There is no URL for a stored file other than the download endpoint.
