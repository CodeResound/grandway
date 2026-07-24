# API — Uploaded Files

**Owner app:** `uploaded_files`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24
**Base prefix:** `/api/v1/files/`
**Auth:** Bearer access JWT (`authenticate.SessionBoundJWTAuthentication`) on every endpoint
**Throttle:** project defaults only — `UserRateThrottle` at 1000/hour. No endpoint here is public. **Two endpoints are worth watching and are deliberately not given a tighter scope yet:** `POST /files/` writes up to 10 MB to disk per call, and `GET /files/<id>/download/` streams it back. At 1000 requests/hour a single account could move ~10 GB. That is an accepted v1 limit — this is an internal staff system with a small, named user population and an audit event per download — and the mitigation is recorded as a known limitation rather than left implicit.
**Access level:** protected. Admin and Lead Manager for list, read, edit, upload, replace, and download; **Admin only** for verify, archive, and restore. **Files owned by a `document` or a print snapshot are Admin-only in every respect** — see the access model below.

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial API documentation — 10 endpoints on one resource, the project's first file storage |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint added or removed. **Closed an authorization leak found by the §19.5 consumer-comprehension review:** a Lead Manager could list and download files owned by a `document` or a print snapshot, which `documents` and `document_history` hide from them entirely. Split `UPLOADED_FILES_FILE_EMPTY` out of `..._FILE_TOO_LARGE`, and added `superseded_by_username` to the response |

---

## Access model (§9 interim inline pattern)

This app uses the interim inline access check in `uploaded_files/access.py`. There is no `permissions.py`.

| Check | Applies to | Allows | Denies |
|-------|-----------|--------|--------|
| `require_file_actor` | every endpoint | `admin`, `lead_manager` | `superadmin` → 403 `UPLOADED_FILES_ACTOR_FORBIDDEN` |
| `require_admin` | `verify`, `archive`, `restore` only | `admin` | `lead_manager` → 403 `UPLOADED_FILES_ACTOR_FORBIDDEN` |
| `require_owner_visibility` | every per-file route, and upload | any authority, for `applicant`/`journey`/`offer`-owned files | `lead_manager`, for a `document`- or `snapshot`-owned file → **404** `UPLOADED_FILES_FILE_NOT_FOUND` on a per-file route, **403** on upload |

Applied by two base classes — `FileScopedView` and `AdminFileScopedView` — so a new endpoint acquires one of the two authority rules by inheritance and cannot be added with neither. The visibility check lives in `FileScopedView.resolve`, so no per-file route can omit it either.

**A file inherits the visibility of the record it belongs to**, and this is the correction the §19.5 review forced. `documents` and `document_history` are Admin-only on every route including reads; without this rule, a Lead Manager who cannot open a bank statement could list and download the PDF attached to it, and neither module would know. The refusal is a **404, not a 403**, on read paths: confirming that such a file exists would leak exactly what those two modules hide. `ADMIN_ONLY_OWNER_TYPES` in `constants.py` holds the membership, and **it must be revisited in the same change as any decision to give Lead Managers document access.**

The list endpoint enforces it by **excluding** restricted rows from the queryset for a non-Admin (`selectors.get_visible_files`), never by refusing a row — a 403 on one row of a page would leak the same thing.

**This is the first app in the project to split the write population from the review population**, and the split is the point of the module:

- A **Lead Manager** sits with the applicant and receives the passport scan. Requiring an Admin to attach it would push a daily clerical act through an authority gate and get worked around.
- An **Admin** decides whether that file is *trusted* (`verify`) and whether it stays in active use (`archive`). If the uploader were also the reviewer, `verification_status` would record who uploaded a file rather than anyone's judgement — which is the one thing the field exists to avoid.

**Not owner-scoped, with the one exception above.** A Lead Manager may read any file on any applicant, journey, or offer — not only records assigned to them. Inherited from `applicants`, which made the same call for the same reason. This is the most sensitive data in the project, so the decision is argued in `docs/SECURITY.md` §2 rather than assumed.

**Authority is checked before existence** on every per-file route, so a caller who may not act cannot use 404-vs-403 to probe for valid ids. **Owner visibility is checked after existence and reported as 404**, for the opposite reason: a 403 there would confirm that a file exists on a record the caller is not allowed to know about.

**No `DELETE` method is exposed on any route, and there is no delete service.** Withdrawal from use is `POST .../archive/`, which is reversible and removes nothing. See `DATA_CONTRACT.md` "Soft Delete".

---

## Error codes

All codes live in `uploaded_files/constants.py` `ErrorCode`.

| Code | HTTP | Meaning |
|------|------|---------|
| `UPLOADED_FILES_ACTOR_FORBIDDEN` | 403 | The caller's authority may not perform this action |
| `UPLOADED_FILES_FILE_NOT_FOUND` | 404 | No file with the id in the URL path |
| `UPLOADED_FILES_OWNER_REQUIRED` | 400 | Zero or more than one owner reference supplied |
| `UPLOADED_FILES_OWNER_NOT_FOUND` | 400 | The named owner record does not exist. `details` names the field |
| `UPLOADED_FILES_FILE_MISSING` | 400 | Registered for completeness — see below |
| `UPLOADED_FILES_FILE_TOO_LARGE` | 400 | Over 10 MB (10 485 760 bytes) |
| `UPLOADED_FILES_FILE_EMPTY` | 400 | Zero bytes. A separate code, so a client never reports an empty file as oversized |
| `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED` | 400 | Extension outside the allowlist |
| `UPLOADED_FILES_FILE_CONTENT_MISMATCH` | 400 | The leading bytes disagree with the extension |
| `UPLOADED_FILES_FILE_BYTES_MISSING` | 404 | The row exists; the bytes are gone from the volume |
| `UPLOADED_FILES_ALREADY_SUPERSEDED` | 400 | Replacing a file that has already been replaced |
| `UPLOADED_FILES_FILE_ARCHIVED` | 400 | A write action against an archived file |
| `UPLOADED_FILES_ALREADY_ARCHIVED` | 400 | Archiving an archived file |
| `UPLOADED_FILES_NOT_ARCHIVED` | 400 | Restoring a file that is not archived |
| `UPLOADED_FILES_VERIFICATION_STATUS_INVALID` | 400 | Registered for completeness — see below |
| `UPLOADED_FILES_REJECTION_REASON_REQUIRED` | 400 | Rejecting without a reason |
| `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED` | 400 | Archiving without a reason |
| `UPLOADED_FILES_FIELD_IMMUTABLE` | 400 | A `PATCH` carried a field fixed at upload time |

Serializer-level failures return the project-wide `VALIDATION_ERROR` (400) with the offending fields in `error.details`.

**Three codes have no reachable HTTP path today, and all three are registered rather than omitted so the envelope is defined if a non-serializer caller is ever added.** Do not write client handling for any of them.

- `UPLOADED_FILES_FILE_MISSING` — the upload serializer declares `file` as a required `FileField`, so a request with no file part fails there as `VALIDATION_ERROR` with `file` in `details`.
- `UPLOADED_FILES_VERIFICATION_STATUS_INVALID` — `FileReviewSerializer.status` is a two-value `ChoiceField`, so anything outside `verified`/`rejected` (including `pending`) fails there as `VALIDATION_ERROR`.
- `UPLOADED_FILES_OWNER_REQUIRED` — `_OwnerMixin` counts the owner fields during request validation, so zero or two of them fails there as `VALIDATION_ERROR` with the message under `details.owner`. The code stays reachable from `services.resolve_owner` for a non-HTTP caller, which is why it exists.

**`UPLOADED_FILES_FILE_BYTES_MISSING` is not a client error.** It means the database and the storage volume have diverged — a row exists whose file is not on disk. It is reported as 404 so nothing about the path is leaked, and logged at `ERROR` with the file id so an operator can see it. No client retry will fix it.

---

## 1. Files

One resource, at `/api/v1/files/`. The per-record file panels are this list filtered — `?applicant=<id>`, `?journey=<id>`, and so on — not nested routes under the owning apps.

### 1.1 List files

`GET /api/v1/files/` — `uploaded_files.file.list` — Admin, Lead Manager

Paginated (`StandardPagination`, 20 per page, max 100). Response `data` is an array of the file shape in `DATA_CONTRACT.md §1`; `meta` carries the standard `count`/`page`/`page_size`/`next`/`previous`.

**Query parameters** — all optional, all validated. An unknown value for an enum parameter or a malformed UUID is a `VALIDATION_ERROR`, never silently ignored: a filter that quietly did nothing is how a screen ends up showing another applicant's files.

| Parameter | Type | Effect |
|---|---|---|
| `applicant`, `journey`, `offer`, `document`, `snapshot` | UUID | Narrow to files owned by that record |
| `category` | enum | One of the eleven `FileCategory` values |
| `verification_status` | enum | `pending` \| `verified` \| `rejected`. **`?verification_status=pending` is the review queue** |
| `upload_source` | enum | `staff_upload` \| `system_generated` |
| `is_archived` | boolean | Omitting it returns archived files **too** |
| `is_current` | boolean | `false` returns only superseded versions |
| `checksum` | string | Exact (case-insensitive) SHA-256 match — duplicate discovery |
| `search` | string | Substring of `original_filename` only |

**Query access pattern (§6).** The selector joins all five owner tables plus `replaces` and the four user columns in one `select_related`. Nine joins is unusual and is what keeps this endpoint at a fixed query count: the response reads `owner_type` off whichever foreign key is set, so a page of twenty mixed-owner files would otherwise fire twenty owner queries plus up to eighty user queries. Guarded by `tests/test_views.py::FileListQueryCountTests`, which asserts the count does not grow when the row count quadruples.

**`search` covers one field, and that is a real limitation.** Unlike every other searchable model in the project, a file has no `_np`/`_en`/`_romanized` triple — a filename is a byte-level artefact, not a canonical identity (§39.1). A file named in Devanagari will not be found by a Roman-script query. `notes` is deliberately not searched: it is operator free text that may carry applicant details, which should not be reachable by guessing.

**Error codes:** `UPLOADED_FILES_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.2 Upload a file

`POST /api/v1/files/` — `uploaded_files.file.upload` — Admin, Lead Manager — **`multipart/form-data`**

**Request** — exactly one owner field, plus:

| Field | Required | Notes |
|---|---|---|
| `applicant` \| `journey` \| `offer` \| `document` \| `snapshot` | exactly one | UUID of the owning record |
| `category` | yes | One of the eleven `FileCategory` values |
| `file` | yes | The file part. ≤ 10 MB |
| `upload_source` | no | Defaults to `staff_upload` |
| `notes` | no | Free text, Unicode-normalized on write |

Example: `curl -F applicant=<uuid> -F category=passport -F file=@passport.pdf`

**Response:** 201 with the file shape in `DATA_CONTRACT.md §1`.

**Validation rules**, applied in this order — a rejection at any step leaves **no row and no bytes**:

1. Exactly one owner supplied → else `VALIDATION_ERROR` with the message under `details.owner`. **Not `UPLOADED_FILES_OWNER_REQUIRED`** — request validation catches this first, so that code is unreachable over HTTP.
1b. The caller's authority may see that owner type → else 403 `UPLOADED_FILES_ACTOR_FORBIDDEN` (a Lead Manager naming a `document` or `snapshot`).
2. That owner exists → else `UPLOADED_FILES_OWNER_NOT_FOUND`, with the failing field named in `details`.
3. Size ≤ 10 MB (10 485 760 bytes) → else `UPLOADED_FILES_FILE_TOO_LARGE`; non-zero → else `UPLOADED_FILES_FILE_EMPTY`. Two codes for two opposite problems, so a client never reports an empty file as oversized.
4. Extension in `pdf, jpg, jpeg, png, webp, docx, xlsx` → else `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED`. The **last** dot-segment decides, so `passport.pdf.exe` is an `exe`.
5. Leading bytes agree with the extension → else `UPLOADED_FILES_FILE_CONTENT_MISMATCH`.

**Business rules:**

- The stored filename is a fresh UUID under `uploaded_files/<owner_type>/<YYYY>/<MM>/`. **The client's filename is never used on disk** — it survives in `original_filename` and is what comes back on download.
- `content_type` is derived from the validated extension. The client's declared `Content-Type` on the multipart part is ignored entirely.
- `checksum_sha256` is computed by streaming the file in 64 KB chunks. **Duplicates are recorded, not blocked** — the same scan legitimately supports two records.
- Every file starts `pending`, including `system_generated` ones.

**Error codes:** `UPLOADED_FILES_OWNER_REQUIRED`, `UPLOADED_FILES_OWNER_NOT_FOUND`, `UPLOADED_FILES_FILE_TOO_LARGE`, `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED`, `UPLOADED_FILES_FILE_CONTENT_MISMATCH`, `UPLOADED_FILES_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.3 Retrieve one file

`GET /api/v1/files/<file_id>/` — `uploaded_files.file.read` — Admin, Lead Manager

**Response:** 200 with the file shape in `DATA_CONTRACT.md §1`. Metadata only — **never the bytes and never the storage path.**

**Error codes:** `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`.

### 1.4 Edit a file

`PATCH /api/v1/files/<file_id>/` — `uploaded_files.file.update` — Admin, Lead Manager

**Request:** `category` and/or `notes`. Nothing else.

**Business rules:**

- **Every other field is refused, not dropped** → `UPLOADED_FILES_FIELD_IMMUTABLE`, with each offending field named in `details`. A client that re-pointed a file at another applicant and got 200 back would believe the move happened.
- A `PATCH` against an archived file is refused → `UPLOADED_FILES_FILE_ARCHIVED`. Restore first, so "archived, then changed" is always two visible events.
- A no-op `PATCH` writes no audit event.

**Error codes:** `UPLOADED_FILES_FIELD_IMMUTABLE`, `UPLOADED_FILES_FILE_ARCHIVED`, `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.5 Download a file

`GET /api/v1/files/<file_id>/download/` — `uploaded_files.file.download` — Admin, Lead Manager

**The only endpoint in this project that does not return the standard JSON envelope on success**, and the only read anywhere that writes an audit event. Both follow from what it is: this is where an applicant's passport actually leaves the system. Registered at `critical` risk — the only endpoint in Grandway at that level.

**Response:** 200, the raw bytes, with:

- `Content-Type` — the stored, validated type
- `Content-Disposition: attachment; filename="<original_filename>"` — **always `attachment`, never `inline`**, so a crafted file cannot execute in the API's own origin
- `X-Content-Type-Options: nosniff`
- `Cache-Control: private, no-store`

Every failure on this route still uses the standard error envelope.

**Business rules:**

- An **archived file is still downloadable.** Archival is a lifecycle state, not a tombstone.
- A **superseded file is still downloadable.** That is the point of keeping the chain.
- One `file_downloaded` audit event is written per call, **before** the stream starts, so a client that aborts mid-transfer still leaves the record that it asked.

**Error codes:** `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_FILE_BYTES_MISSING`, `UPLOADED_FILES_ACTOR_FORBIDDEN`.

### 1.6 List a file's versions

`GET /api/v1/files/<file_id>/versions/` — `uploaded_files.file.versions` — Admin, Lead Manager

**Response:** 200, `data` is the whole replacement chain **oldest first**, `meta.count` is its length. **Unpaginated** — a chain is short by construction, and paging it would let a caller request a slice of something only meaningful whole.

**Business rules:** the chain reads identically from any member of it, so a client holding a superseded id can still ask what replaced it.

**Query access pattern (§6).** `selectors.get_version_chain` walks backwards through `replaces` to the original, then forwards through the `replaced_by` reverse of the same `OneToOne`. It is one query per link, deliberately: a chain has no set-based form, and it is bounded by the `OneToOne` that makes forking impossible. A cycle guard is present as a backstop against corrupted data — an infinite loop inside a request is a worse failure than a short answer.

**Error codes:** `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`.

### 1.7 Replace a file

`POST /api/v1/files/<file_id>/replace/` — `uploaded_files.file.replace` — Admin, Lead Manager — **`multipart/form-data`**

**Request:** `file` (required), `notes` (optional). **No owner and no category** — both are inherited. Accepting either would let a replacement quietly move a file to another applicant, which is exactly what `UPLOADED_FILES_FIELD_IMMUTABLE` prevents on the ordinary update path.

**Response:** 201 with the **successor's** shape, at `version_number = previous + 1` with `replaces` set to the predecessor's id.

**Business rules:**

- **Nothing is overwritten.** The predecessor keeps its bytes, its verdict, its notes, and its place in the chain; only `superseded_at`/`superseded_by` are set on it.
- The successor **starts `pending`** even if the predecessor was `verified`. A re-scan is a different artefact; carrying the verdict across would mark a file nobody looked at as reviewed.
- A file may be replaced **once** → `UPLOADED_FILES_ALREADY_SUPERSEDED`. The chain stays linear, so "which file is current" always has exactly one answer.
- The same five upload validation rules as §1.2 apply.

**Error codes:** `UPLOADED_FILES_ALREADY_SUPERSEDED`, `UPLOADED_FILES_FILE_ARCHIVED`, `UPLOADED_FILES_FILE_TOO_LARGE`, `UPLOADED_FILES_FILE_TYPE_NOT_ALLOWED`, `UPLOADED_FILES_FILE_CONTENT_MISMATCH`, `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.8 Review a file

`POST /api/v1/files/<file_id>/verify/` — `uploaded_files.file.verify` — **Admin only**

**Request:** `status` (`verified` | `rejected`) and `reason` (required when rejecting).

**Response:** 200 with the file shape.

**Business rules:**

- `pending` **cannot be set.** It is a starting state, not a verdict, and there is no un-review action — "this was reviewed and then un-reviewed" is a claim the audit log should make, not the record.
- Rejecting requires a reason → `UPLOADED_FILES_REJECTION_REASON_REQUIRED`. Verifying does not: a rejection is the verdict someone has to answer for later.
- Re-verifying a rejected file **clears the stale rejection reason**, so an old refusal never sits under a current acceptance.
- A verdict may be revised. There is no lock, deliberately — a reviewer who rejects the wrong file must be able to correct it, and the audit log carries the sequence.
- **Verification gates nothing.** No endpoint anywhere in Grandway refuses to proceed because a file is unverified. The state is recorded for human review, not enforced.

**Error codes:** `UPLOADED_FILES_REJECTION_REASON_REQUIRED`, `UPLOADED_FILES_FILE_ARCHIVED`, `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.9 Archive a file

`POST /api/v1/files/<file_id>/archive/` — `uploaded_files.file.archive` — **Admin only**

**Request:** `reason` (required).

**Response:** 200 with the file shape, `is_archived: true`.

**Business rules:**

- The reason is mandatory → `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED`. Archived files are kept forever, so "why is this one archived" must be answerable from the record.
- **Nothing is deleted.** The bytes stay on disk and the file stays downloadable.
- **The version chain is untouched.** An archived v1 is still v1 and still v2's predecessor: `is_archived` and `is_current` are independent axes.
- Archiving an archived file → `UPLOADED_FILES_ALREADY_ARCHIVED`.

**Error codes:** `UPLOADED_FILES_ARCHIVE_REASON_REQUIRED`, `UPLOADED_FILES_ALREADY_ARCHIVED`, `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`, `VALIDATION_ERROR`.

### 1.10 Restore a file

`POST /api/v1/files/<file_id>/restore/` — `uploaded_files.file.restore` — **Admin only**

**Request:** `note` (optional). No reason is required, unlike archiving — demanding an explanation for undoing something discourages correcting a mistake.

**Response:** 200 with the file shape, `is_archived: false` and `archive_reason` cleared.

**Business rules:** all three archive columns are cleared, so the record carries no trace of having been archived. The audit log carries that — denormalized fields are *current state*, the append-only log is *history*.

**Error codes:** `UPLOADED_FILES_NOT_ARCHIVED`, `UPLOADED_FILES_FILE_NOT_FOUND`, `UPLOADED_FILES_ACTOR_FORBIDDEN`.

---

## AI debugging notes

- **"The response has no `file` field."** Correct and intentional. `file` is the only model field in this project that is never serialized under any circumstances — returning a storage path would leak the layout of `MEDIA_ROOT` and imply a fetchable URL that does not exist. Use `GET /files/<id>/download/`.
- **"A direct URL to the media directory 404s."** Also correct. `MEDIA_URL` is unset and nothing serves `MEDIA_ROOT` statically. The download endpoint is the only path from the volume to a client.
- **"The upload succeeded but the filename on disk is not mine."** By design (§14 filename rule). `original_filename` holds yours.
- **"`PATCH` returned 400 for a field I sent."** Only `category` and `notes` are editable. Everything else about a stored file is fixed; the response names the fields it refused.
- **"A Lead Manager gets 403 on `/verify/` but 200 on `/replace/`."** That is the access split — see the access model table above, not a bug.
- **"A Lead Manager gets 404 on a file that plainly exists."** Check its owner. A `document`- or `snapshot`-owned file is invisible to that authority by design, and reported as absent rather than forbidden so the refusal leaks nothing. An Admin sees it.
- **"`?is_archived` was omitted and archived files came back."** By design. The selector hides nothing a caller did not ask it to hide; pass `?is_archived=false` for the active-only view.
- **"A file is `is_current: false` but not archived, or archived but `is_current: true`."** Two independent axes: superseded means "something replaced it", archived means "it is out of active use". Neither implies the other.
- **404 `UPLOADED_FILES_FILE_BYTES_MISSING` is an infrastructure fault, not a client one** — the row exists and the file is gone from the volume. Check the `MEDIA_ROOT` mount; the log carries the file id.
