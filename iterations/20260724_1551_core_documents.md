# Iteration — 2026-07-24 15:51 — core, documents

Session branch: `add_documents_app_20260724_1530`

---

## Documents

### 1. Module

- **Name:** Documents — the editable document working record. Ownership, template association, status, and the entered source data.
- **Base path:** `/api/v1/documents/`
- **Auth:** Bearer access JWT on every endpoint. **Admin authority only** — a `lead_manager` and a `superadmin` are both refused with 403 `DOCUMENTS_ACTOR_FORBIDDEN` on every route, reads included.

### 2. Conventions

- **Response:** `{ success, message, data, meta }`. The resource is always under `data`; `meta` is `{}` when there is nothing to report.
- **Error:** `{ success: false, error: { code, message, details }, meta }`. `details` is always present, `{}` when there are no field-level errors.
- **Auth failures:** 401 from the authentication framework with no, expired, or revoked token. 403 `DOCUMENTS_ACTOR_FORBIDDEN` when the token is valid but the caller is not an Admin. This code replaces the project-wide `PERMISSION_DENIED`, which is never returned from this module.
- **Pagination:** page-number based, `page` and `page_size` (default 20, max 100). `data` is the bare array of rows, not nested under `results`. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next` and `previous` are absolute URLs or `null`. Applied to all three list endpoints.
- **IDs:** UUID strings. `template_key` is a readable slug but is not an identifier a record can be addressed by.
- **Times:** `created_at`, `updated_at`, and `archived_at` are ISO 8601 UTC. **Only `archived_at` carries a Bikram Sambat sibling**, `archived_at_bs`, shaped `{ year, month, day, month_name_en, month_name_np, display_en, display_np }` or `null`. Dates inside `content` are opaque client data and are never parsed or converted.
- **List/search/filter params:** `applicant`, `standalone`, `status`, `family`, `template_key`, `search`, `fiscal_year`. Invalid values are rejected with 400, not ignored.
- **Ordering:** fixed and not client-controllable. Documents by `-updated_at`, workspaces by `-last_updated`, history newest-first.
- **Empty text fields are `""`, never `null`.** The nullable fields are `applicant`, `applicant_name`, `archived_at`, and `archived_by_username`.
- **`content` is stored and returned verbatim.** The backend computes, injects, normalizes, and strips nothing inside the document body.
- **`content` replaces wholesale on update, it does not merge.**
- **Immutable fields are rejected on `PATCH`, not silently dropped.**

### 3. Models

**Document (list shape)** — `{ id, applicant?, applicant_name?, is_standalone, family:[enum], template_key, label, status:[enum], is_archived, created_at, updated_at }`

- `content` is deliberately absent from the list; a page of bank statements would otherwise carry a megabyte of transaction rows nothing renders.
- `applicant` and `applicant_name` are both `null` on a standalone document.

**Document (detail shape)** — the list shape plus `{ content:json, standalone_purpose, notes, is_editable, archive_reason, archived_at?, archived_at_bs?:json, archived_by_username?, created_by_username }`

- Returned by retrieve, create, update, status, archive, and restore. Only the list returns the shorter shape.
- `content` shape depends on `family` and `template_key` and is neither validated nor interpreted by the backend.
- `archive_reason` is non-empty only when `status` is `archived`; restoring clears it.

**WorkspaceSummary** — `{ applicant_id, applicant_name, document_count, last_updated }`

- One row per applicant with live documents. Standalone documents are excluded, and archived documents are excluded from the count.
- `applicant_name` prefers the English name and falls back to the Devanagari one.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- `changes` maps field name to `{ from, to }`, both stringified; `{}` on creation events.
- A body change appears as `changes.content = { "from": "<changed>", "to": "<changed>" }` — the literal marker, never the body. A previous body cannot be recovered from the history.

### 4. Enums

- `Document.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`
- The 42 frontend slugs are **not** an enum — they live in `template_key` as a validated string
- `Document.status`: `draft` | `ready` | `archived`
- There is no `printed` status; nothing can set it until `document_history` exists
- There is no `submitted` status; the frontend's third value maps to `ready`
- `archived` is not reachable through the status action; it requires the archive endpoint and a reason
- `template_key`: **not** an enum — a lowercase ASCII slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, which must agree with `family` by prefix and, for the two bank families, by suffix
- `HistoryEvent.action`: `document_created` | `document_updated` | `document_status_changed` | `document_archived` | `document_restored`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai`. In practice only `admin` appears, since only Admins can write

### 5. Dependency order

- `Document` needs an `Applicant` **(external module: `applicants`)** — unless it is standalone, in which case it needs a `standalone_purpose` instead. Exactly one of the two.
- An `Applicant` needs nothing from this module.

**Start here:** for an applicant-owned document, obtain the applicant id, then `POST /api/v1/documents/`. A standalone document can be posted immediately with a purpose and no prerequisite record at all.

### 6. Endpoints

#### Document — `/api/v1/documents/`

**Use it when:** the Document List worklist, the Applicant Detail documents panel, the standalone documents list, the Document Workspace, and the New Document form.

**Methods:**
- `GET /api/v1/documents/` — `documents.document.list`
- `POST /api/v1/documents/` — `documents.document.create`
- `GET /api/v1/documents/<document_id>/` — `documents.document.read`
- `PATCH /api/v1/documents/<document_id>/` — `documents.document.update`

**Send (create/update):**
- create: `family` required, `template_key` required, `label` required; then either `applicant` or `standalone_purpose`; plus optional `content` and `notes`
- update: any subset of `label`, `content`, `standalone_purpose`, `notes` — and nothing else

**Returns:** Document (detail shape) for create, retrieve, and update; list[Document (list shape)] for the list.

**Notes:**
- `search` matches `label` only and does not reach into the document body.
- Omitting `status` returns archived documents too.
- `content` defaults to `{}`, must be a JSON object, and must serialize under 256 KiB.
- `applicant`, `family`, and `template_key` are immutable after creation and are rejected on update.
- `status` and the archive fields are rejected on update; standing moves through its own actions.
- An archived document returns 409 on update.
- `content` is replaced wholesale — a partial body discards every key it omits.
- There is no delete.

**Errors:**
- `DOCUMENTS_APPLICANT_NOT_FOUND` (400) — no applicant with that id, on create
- `DOCUMENTS_OWNER_REQUIRED` (400) — neither an applicant nor a standalone purpose was given
- `DOCUMENTS_TEMPLATE_KEY_INVALID` (400) — the slug does not agree with the family
- `DOCUMENTS_CONTENT_INVALID` (400) — the body is not a JSON object
- `DOCUMENTS_CONTENT_TOO_LARGE` (400) — the body exceeds 256 KiB
- `DOCUMENTS_OWNERSHIP_IMMUTABLE` (400) — a PATCH carried the applicant, family, or template key
- `DOCUMENTS_STATUS_IMMUTABLE` (400) — a PATCH carried a standing field
- `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409) — the document is archived
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

#### Document workspaces — `/api/v1/documents/workspaces/`

**Use it when:** the Documents landing table — applicants with live document work.

**Methods:**
- `GET /api/v1/documents/workspaces/` — `documents.document.list_workspaces`

**Send:** nothing beyond pagination.

**Returns:** list[WorkspaceSummary], ordered by most recent edit.

**Notes:**
- Standalone documents are excluded; list them with `?standalone=true`.
- Archived documents are excluded from the count, and an applicant whose documents are all archived does not appear.
- Note the trailing slash; `workspaces/` is a literal path segment, not a document id.

**Errors:** none beyond the global authority failure.

#### Document: status — `/api/v1/documents/<document_id>/status/`

**Use it when:** the workspace's mark-ready control, and moving a document back to draft.

**Methods:**
- `POST /api/v1/documents/<document_id>/status/` — `documents.document.change_status`

**Send:** `status` — `draft` or `ready` only.

**Returns:** Document (detail shape).

**Notes:**
- `archived` is refused at the serializer; archiving requires its own endpoint and a reason.
- Re-sending the current status is a no-op returning 200 and writing no event.
- The document must not be archived.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409)
- `DOCUMENTS_STATUS_INVALID_TRANSITION` (400)
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

#### Document: archive — `/api/v1/documents/<document_id>/archive/`

**Use it when:** retiring a superseded document. This is what a delete button becomes.

**Methods:**
- `POST /api/v1/documents/<document_id>/archive/` — `documents.document.archive`

**Send:** `reason`, required and non-empty.

**Returns:** Document (detail shape) with `status` now `archived`, `is_editable` false, and `archived_at` / `archived_by_username` stamped.

**Notes:**
- Only an active document may be archived.
- The reason is mandatory; archived documents are kept forever.
- The document remains in unfiltered list results — archiving is not hiding.
- After archiving the document is frozen: update and status change both return 409.

**Errors:**
- `DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED` (409)
- `DOCUMENTS_ARCHIVE_REASON_REQUIRED` (400)
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

#### Document: restore — `/api/v1/documents/<document_id>/restore/`

**Use it when:** bringing an archived document back for correction.

**Methods:**
- `POST /api/v1/documents/<document_id>/restore/` — `documents.document.restore`

**Send:** nothing.

**Returns:** Document (detail shape) with `status` back to `draft` and the three archive fields cleared.

**Notes:**
- Only an archived document may be restored.
- It always returns to `draft`, never to `ready`, even if it was `ready` when archived.
- Clearing the archive fields does not erase the archiving from history.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_ARCHIVED` (409)
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

#### Document: history — `/api/v1/documents/<document_id>/history/`

**Use it when:** the history panel on the Document Workspace.

**Methods:**
- `GET /api/v1/documents/<document_id>/history/` — `documents.document.list_history`

**Send:** nothing.

**Returns:** list[HistoryEvent], newest first, paginated.

**Notes:**
- Never empty for an existing document; creation always writes one event.
- A body change is recorded as a marker, not as content. A previous body cannot be reconstructed from this endpoint.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### 7. Flows

**Create and work on an applicant's document**

1. `GET /api/v1/documents/?applicant=<applicant_id>` for the Applicant Detail panel. Hide the panel entirely for a Lead Manager.
2. `POST /api/v1/documents/` with `applicant`, `family`, `template_key`, and `label`. Returns the document at `status: draft` with `content: {}`.
   - A family and slug from different pickers → 400 `DOCUMENTS_TEMPLATE_KEY_INVALID`.
3. `GET /api/v1/documents/<id>/` — the only endpoint that returns the body.
4. `PATCH /api/v1/documents/<id>/` with the complete `content` on each save. Send input fields only; never a computed balance, total, or amount-in-words.
   - Including `status` or `template_key` → 400; strip them before submitting.
5. `POST /api/v1/documents/<id>/status/` with `ready` when finished.
6. Printing is not available — it needs `document_history`, which is not built.

**Create a standalone document**

1. `POST /api/v1/documents/` with `standalone_purpose` and no `applicant`. Returns `is_standalone: true`.
   - Neither given → 400 `DOCUMENTS_OWNER_REQUIRED`.
2. Work it exactly as an applicant-owned document.
3. Find it with `?standalone=true`; it will not appear in the workspaces landing table.

**Retire a document and bring it back**

1. `POST /api/v1/documents/<id>/archive/` with a reason. Returns `status: archived`, `is_editable: false`.
   - No reason → 400 `DOCUMENTS_ARCHIVE_REASON_REQUIRED`.
2. The workspace must go read-only; every save now returns 409.
3. The document still appears in the unfiltered list and under `?status=archived`.
4. `POST /api/v1/documents/<id>/restore/` returns it to `draft` and editable.
5. `GET /api/v1/documents/<id>/history/` still shows the archiving and its reason.

**Build the documents landing table**

1. `GET /api/v1/documents/workspaces/` for one row per applicant with live work.
2. A row click leads to `GET /api/v1/documents/?applicant=<applicant_id>`.
3. Standalone documents need a separate tab; they are absent from step 1 by design.

### 8. Gaps

- **No print snapshot and no print log.** The concept's flow 3 ends by capturing an immutable snapshot; that belongs to `document_history`, which has no concept file and no code.
- **No signatory list, and signature references are unvalidated.** `content.instructorId` and `content.directorId` point at a Signature table owned by the unbuilt `document_templates`; they round-trip as opaque strings.
- **No supporting files.** `uploaded_files` does not exist, so nothing can be attached to a document.
- **No template registry.** `template_key` is format-checked and family-checked but not checked against real templates; a typo matching the family prefix is accepted.
- **A client-supplied derived value is stored, not stripped.** The backend cannot strip it without knowing all 42 shapes. Never read a derived value back as truth.
- **`content` replaces wholesale on update, not merged.** A partial body discards every key it omits.
- **A previous body cannot be recovered.** No field history, no versioning, and the audit log redacts the body. Editing loses the previous contents irrecoverably.
- **`content` is not sanitized or escaped.** Escaping on render is the client's responsibility.
- **`search` matches labels only** — not the body, not the applicant's name, not `template_key`.
- **No cascade from applicants.** An applicant with documents cannot be deleted.
- **No bulk create, archive, or export.**
- **The uploaded frontend reference docs describe a different backend.** Path, envelope, field-name, and verb differences are tabulated in `backend/documents/docs/INTEGRATION.md` §9.

---

## Core

### 1. Module

- **Name:** Core — global infrastructure. Not a business app.
- **Base path:** none of its own beyond `/health/`, `/ready/`, and the `/api/v1/` mount.
- **Auth:** unchanged.

### 2. Conventions

No changes this session. The project-wide envelope, pagination, error-code naming, and money-as-string rules are unchanged.

### 3. Models

No changes this session. `core/models.py` still contains only the abstract `BaseModel`.

### 4. Enums

No changes this session.

### 5. Dependency order

Unchanged. `core` depends on no business app; every app depends on it.

### 6. Endpoints

**No endpoint was added, changed, or retired in `core` this session.** `core/api_urls.py` gained one include line mounting `documents` at `/api/v1/documents/`; the routes it exposes belong to `documents` and are documented under that app above.

### 7. Flows

No core-owned flow exists. `concepts/project_flows.md` gained a dependency-graph entry for `documents` and three gaps recording why no end-to-end journey passes through it.

### 8. Gaps

- Permission-key-based authorization is still not enforced in the request path. All nine `documents` endpoints carry a registered `permission_key` at `medium` or `high` risk — deliberately higher than equivalents elsewhere — and no view consults one.
- **A third distinct access model now exists.** Shared (`applicants`, `applicant_journeys`, `offers`), read-shared with Admin-only writes (`institutions`, `clients`), and **Admin-only including reads (`documents`)**. No global rule can be assumed; `core/docs/INTEGRATION.md` §10 carries the table.
- Immutable-field handling on `PATCH` differs across four apps now: `institutions` silently ignores, while `offers`, `clients`, and `documents` reject. A shared edit-form component carried between them will fail on every save.
- Three named document domains remain unbuilt — `document_history`, `document_templates`, `uploaded_files` — and the first two have no concept file, which is what prevented them being built alongside `documents`.
