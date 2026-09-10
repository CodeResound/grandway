# Session 20260910_1938 — Signatory signature image upload (branch `add_signatory_signature_upload_20260910_1829`)

## Document Templates

## 1. Module
- Name: Document Templates
- Base path: `/api/v1/document-templates/`
- Auth: unchanged — Bearer access JWT, Admin only on every route including reads

## 2. Conventions
- Response: unchanged — standard `success` / `message` / `data` / `meta` envelope
- Error: unchanged — `success: false` with `error.code`, `error.message`, `error.details`
- Auth failures: unchanged — 401 unauthenticated, 403 `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` for a Lead Manager or Superadmin
- Pagination: unchanged
- IDs: unchanged — UUID
- Times: unchanged — ISO 8601 UTC, no Bikram Sambat fields in this module
- List/search/filter/order params: unchanged
- **New:** one route in this module accepts `multipart/form-data` rather than JSON. A JSON body sent to it returns 415.

## 3. Models
- **Signatory** — `{ id, name, title, role, signature_image_url, signature_file?:object, signature_source:[enum], status:[enum], is_active, status_note, created_by_username, created_at, updated_at }`
  - Two fields added this session: `signature_file` and `signature_source`. Both read-only. Additive — no field was removed, renamed, or retyped.
  - `signature_file` is `null` when no uploaded signature is currently in force.
  - Migration `0003_signatory_signature_file` adds a nullable `PROTECT` FK to `uploaded_files.UploadedFile`, plus a help-text-only `AlterField` on `signature_image_url`.
- **SignatureFile** (nested inside `signature_file`) — `{ id, download_path, original_filename, content_type, size_bytes, version_number, uploaded_at }`
  - New this session. Six fields plus a derived path; a strict subset of the file ledger's own shape, declared locally so a change there is not a breaking change here.
  - `download_path` is a relative path to an authenticated route, not a public URL.

## 4. Enums
- `Signatory.signature_source: uploaded | url | none` — new this session. Server-computed; reports which signature a client should render.
- `Signatory.status: draft | active | inactive` — unchanged.

## 5. Dependency order
- A `Signatory` needs nothing.
- A signature upload needs a `Signatory` (any status).
- Rendering an uploaded signature needs `uploaded_files.file.download` `(external module)`.
- Removing a signature needs `uploaded_files.file.archive` `(external module)`.
- **Start here:** `POST /api/v1/document-templates/signatories/`, then upload a signature, then activate.

## 6. Endpoints

### Signatory — `/api/v1/document-templates/signatories/`
- **Use it when:** the Signatory Library screen, and populating the instructor/director selects on a certificate.
- **Methods:** unchanged this session
  - `GET /signatories/`
  - `POST /signatories/`
  - `GET /signatories/<signatory_id>/`
  - `PATCH /signatories/<signatory_id>/`
- **Send (create/update):** unchanged
- **Returns:** `Signatory` — now carrying `signature_file` and `signature_source`
- **Notes:**
  - The list carries `signature_file` too, at no extra query cost.
  - `PATCH` now rejects `signature_file` as well as `status` and `status_note`.
- **Errors:**
  - `DOCUMENT_TEMPLATES_SIGNATURE_FILE_IMMUTABLE` (400) — new; a `PATCH` carried `signature_file`

### Signatory signature — `/api/v1/document-templates/signatories/<signatory_id>/signature/`
- **Use it when:** the Signatory Library's upload-signature control, for a new signer or to replace a changed signature. **New this session.**
- **Methods:**
  - `POST /signatories/<signatory_id>/signature/` (`document_templates.signatory.upload_signature`)
- **Send:** `multipart/form-data`
  - `file` — required, exactly one part, PNG/JPG/JPEG/WEBP, max 10 MB
  - `notes` — optional text, stored against the file
- **Returns:** `Signatory` — **201**, not the file
- **Notes:**
  - Any status may receive a signature — `draft`, `active`, and `inactive` alike
  - A signature already in force is superseded; the old file is kept and readable through the file module's version chain
  - After the current signature is archived, a further upload starts a fresh chain at version 1
  - The stored file is always `category=signature_image` and `verification_status=pending`, and is excluded from the file verification queue
  - Removal is archiving the file through the file module; there is no removal endpoint here
  - Uploading through the file module directly with `signatory=<id>` stores a file that will never render
  - Exactly one file part; a second part fails during parsing as a 500
- **Errors:**
  - `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403) — not an Admin
  - `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404) — checked after authority
  - `DOCUMENT_TEMPLATES_SIGNATURE_NOT_AN_IMAGE` (400) — not PNG/JPG/JPEG/WEBP
  - `DOCUMENT_TEMPLATES_SIGNATURE_FILE_TOO_LARGE` (400) — over 10 MB
  - `DOCUMENT_TEMPLATES_SIGNATURE_FILE_CONTENT_MISMATCH` (400) — bytes contradict the extension
  - `VALIDATION_ERROR` (400) — no `file` part, or an empty one
  - 415 — a JSON body was sent
  - 405 — any method other than `POST`

No other endpoint in this module was added, changed, or retired.

## 7. Flows

**Add a signer with a real signature**
1. `POST /api/v1/document-templates/signatories/` → `Signatory`, `status: "draft"`, `signature_source: "none"`
2. `POST /api/v1/document-templates/signatories/<id>/signature/` as multipart → `signature_source: "uploaded"`, `version_number: 1`
   - Failure `DOCUMENT_TEMPLATES_SIGNATURE_NOT_AN_IMAGE` — images only
   - Failure `DOCUMENT_TEMPLATES_SIGNATURE_FILE_TOO_LARGE` — 10 MB cap
3. `POST /api/v1/document-templates/signatories/<id>/status/` with `active` → appears in the picker

**Render a signature**
1. Read `signature_source` from the signatory
2. `"uploaded"` → `fetch` `signature_file.download_path` with the bearer token, then build a blob URL
   - Failure 401 — an `<img src>` was pointed at the path instead of fetching it
   - Failure 404 — the row exists and the bytes do not
3. `"url"` → render `signature_image_url` directly; `"none"` → render nothing
4. Hold the blob URL for the session; the route forbids caching and audits every read

**Replace a signature**
1. `POST /api/v1/document-templates/signatories/<id>/signature/` with the new image → `version_number` increments, predecessor superseded
2. Every historical reprint now renders the new signature, because a snapshot freezes the signer's name but never the image

**Remove a signature**
1. Read `signature_file.id`
2. `POST /api/v1/files/<file_id>/archive/` with a `reason` — cross-app, no removal endpoint here
3. `signature_file` returns to `null` and `signature_source` falls back to `"url"` or `"none"`

## 8. Gaps
- No way to distinguish a never-uploaded signature from a removed one; both read as `signature_file: null`
- No thumbnail, dimension metadata, or server-side crop — whatever is uploaded is what prints
- A reprint renders the current signature, not the one that was issued; `render_context.signatories[]` has no file field to freeze one in
- `signature_image_url` remains an unvalidated external link, never fetched or reachability-checked
- Signature bytes cost an authenticated, uncached, audited round trip per fresh render

---

## Uploaded Files

## 1. Module
- Name: Uploaded Files
- Base path: `/api/v1/files/`
- Auth: unchanged — Bearer access JWT; Admin and Lead Manager for reads/uploads, Admin only for verify/archive/restore, Superadmin refused

## 2. Conventions
- Response: unchanged
- Error: unchanged
- Auth failures: unchanged
- Pagination: unchanged
- IDs: unchanged
- Times: unchanged
- List/search/filter/order params: **one new owner filter**, `?signatory=<uuid>`

## 3. Models
- **UploadedFile** — read shape unchanged. `owner_type` and `owner_id` are generic strings, so the sixth owner type required no field change.
  - `owner_type` may now be `signatory`.
  - Migration `0002_signatory_owner` adds a nullable `PROTECT` FK to `document_templates.Signatory` and widens the `uploaded_file_single_owner` check constraint from a five-way to a six-way disjunction.

## 4. Enums
- `UploadedFile.owner_type: applicant | journey | offer | document | snapshot | signatory` — `signatory` added this session.
- `UploadedFile.category` — unchanged. `signature_image` already existed and now has an owner that can use it.

## 5. Dependency order
- A file needs exactly one owner, which must already exist.
- A `signatory` owner needs `document_templates.signatory.create` `(external module)`.
- **Start here:** unchanged — create the owning record, then upload.

## 6. Endpoints

### UploadedFile — `/api/v1/files/`
- **Use it when:** unchanged.
- **Methods:** unchanged
- **Send (create):** one new optional owner field, `signatory`. Exactly one owner field is still required.
- **Returns:** `UploadedFile` — unchanged shape
- **Notes:**
  - `?signatory=<uuid>` narrows the list to one signatory's files
  - A file owned by a signatory is **Admin-only**: absent from a Lead Manager's list, 404 on every per-file route, 403 on upload
  - Signatory-owned files are **excluded from the verification queue** and the dashboard verification figures; they remain reviewable directly
  - Uploading with `signatory=<id>` here does **not** make the file render as that signatory's signature — use the owning module's signature endpoint
- **Errors:** unchanged. The "exactly one owner" message now names six fields rather than five.

No endpoint in this module was added, changed, or retired.

## 7. Flows
- No new flow. The existing upload, review, replace, archive, and restore flows all accept a `signatory` owner unchanged.
- One existing flow changed: the **file review queue** (`?verification_status=pending`) no longer surfaces signature images.

## 8. Gaps
- `education` and `test_scores` are still not owner types
- A signatory-owned file has no applicant, so it is absent from every applicant-scoped rollup and from country-narrowed dashboard counts

---

## Core

## 1. Module
- Name: Core
- Base path: `/api/v1/`
- Auth: unchanged this session

## 2. Conventions
- Response: unchanged
- Error: unchanged
- Auth failures: unchanged
- Pagination: unchanged
- IDs: unchanged
- Times: unchanged
- List/search/filter/order params: unchanged

## 3. Models
- No model changes in `core`. The policy registry gained one endpoint record.

## 4. Enums
- No changes.

## 5. Dependency order
- No changes.

## 6. Endpoints
- No endpoint in `core` was added, changed, or retired. The committed policy artifacts (`registry_export.json`, `openapi.json`) were regenerated to include `document_templates.signatory.upload_signature`, taking the registered endpoint count from 179 to 180.

## 7. Flows
- No changes this session.

## 8. Gaps
- No changes this session.

---

## Dashboards

## 1. Module
- Name: Dashboards
- Base path: `/api/v1/dashboards/`
- Auth: unchanged this session

## 2. Conventions
- Response: unchanged
- Error: unchanged
- Auth failures: unchanged
- Pagination: unchanged
- IDs: unchanged
- Times: unchanged
- List/search/filter/order params: unchanged

## 3. Models
- No model changes.

## 4. Enums
- No changes.

## 5. Dependency order
- No changes.

## 6. Endpoints
- No endpoint was added, changed, or retired. **Three figures changed value**, all sourced from `uploaded_files`: the `files_awaiting_verification` alert count, the `files_by_verification` breakdown, and the Today's Work file preview list. Signature images are excluded from all three, so a signature upload no longer raises the pending count or renders a file row with no applicant.

## 7. Flows
- No changes this session.

## 8. Gaps
- No changes this session.

---

## Search

## 1. Module
- Name: Search
- Base path: `/api/v1/search/`
- Auth: unchanged this session

## 2. Conventions
- Response: unchanged
- Error: unchanged
- Auth failures: unchanged
- Pagination: unchanged
- IDs: unchanged
- Times: unchanged
- List/search/filter/order params: unchanged

## 3. Models
- No model changes.

## 4. Enums
- No changes.

## 5. Dependency order
- No changes.

## 6. Endpoints
- No endpoint was added, changed, or retired. The `uploaded_file` bucket inherits the new Admin-only rule automatically, so a Lead Manager's search no longer returns signature files. A regression test was added for that path.

## 7. Flows
- No changes this session.

## 8. Gaps
- **Pre-existing, newly visible:** the `signatory`, `document`, and `document_template` buckets are not narrowed by authority, while the `uploaded_file` bucket is. A Lead Manager searching a signer's name therefore gets a populated `signatory` hit whose hand-off link returns 403, while that signatory's signature file is correctly hidden — an inconsistency inside one response body. Not introduced this session and deliberately not fixed here; recorded so it is not filed as a regression against this work.
