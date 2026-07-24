# Integration — Documents

**Owner app:** `documents`
**Version:** 1.0.1
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 9 endpoints, one resource |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint change. `document_history` moved from "missing" to a documented consumer; print/recover gaps closed |

---

## 1. Module

- **Name:** Documents — the editable document working record. Identity, ownership, template association, status, and the entered source data staff type into the document workspace. **The backend is not the rendering engine**: it stores the source data verbatim and the frontend renders it and computes every display value.
- **Base path:** `/api/v1/documents/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. **Admin authority only.** A `lead_manager` and a `superadmin` are both rejected with 403 on every route, reads included.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which is the whole access check here. | Every endpoint returns 401; any non-Admin gets 403 `DOCUMENTS_ACTOR_FORBIDDEN` everywhere. |
| `authenticate` | FK | `created_by` (`PROTECT`) and `archived_by` (`SET_NULL`) reference user accounts. | Documents could not record who created or archived them. |
| `applicants` | FK + service call | An applicant-owned document points at one, resolved through `applicants.selectors.get_applicant_by_id` on create. | Only standalone documents could be created; `POST` returns 400 `DOCUMENTS_APPLICANT_NOT_FOUND` for any applicant id that does not resolve. |
| `audit` | service call | Every mutation appends one immutable event. This module stores no history of its own. | Documents still save but leave no trace of who changed what, and `GET /documents/<id>/history/` returns an empty list. |

**This module writes to nothing outside itself.** Creating, editing, or archiving a document does not touch the applicant's status or any other record.

**Two apps this module deliberately does not contain, and which do not exist yet:**

| Missing app | What it would own | What you cannot do today |
|---|---|---|
| `document_templates` | Template definitions, versions, signatory records + signature images | Fetch the signatory list, or validate `content.instructorId` / `content.directorId` |
| `uploaded_files` | File storage, verification, versioning | Attach a supporting file to a document, or store a generated PDF anywhere |

**One app this module deliberately does not contain, and which now exists:** `document_history`
(`/api/v1/document-history/`) owns immutable print snapshots and print events. It **consumes** this
module — it holds `PROTECT` foreign keys to `Document` and performs a recovery through this module's
own update service rather than writing directly — and this module depends on it for nothing.
Printing, print history,
reprinting, and recovering a previous body all live there; none of it is reachable from a
`/api/v1/documents/` route.

**Consequences for a client of *this* module:**

- **A document may be referenced by snapshots you cannot see from here.** No field on the `Document`
  resource reports whether it has ever been printed, or how many times. Ask `document_history`.
- **`POST /api/v1/document-history/snapshots/<id>/recover/` can change a document underneath you**,
  writing its `label` and `content`. It appears in this module's history endpoint as an ordinary
  `document_updated` event, indistinguishable from a manual edit except by its timing next to the
  recovery. Refetch after a recovery rather than trusting a cached copy.
- **`PROTECT` now runs both ways.** A document with print history cannot be deleted — which changes
  nothing today, since this module has no delete at all.

## 3. Conventions

- **Access — Admin only, and this is unlike every other module.** `admin` may do everything; `lead_manager` and `superadmin` are refused on **every route including `GET`**. Two other modules (`institutions`, `clients`) let a Lead Manager read but not write — **this one does not let them read.** A documents panel must be **hidden** for a Lead Manager, not rendered read-only or shown empty: an empty panel implies "this applicant has no documents", which is false.
- **The backend never touches the document body.** `content` is returned exactly as it was sent. It computes no running balances, no debit/credit totals, no closing balance, no interest or tax rows, and no amount-in-words. It also does not **strip** them if you send them — see §9.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint**. A document that is no longer current is archived with a mandatory reason and kept forever.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to three fields to show the envelope**; a real create returns the full `Document` shape defined in §4.

```json
{
  "success": true,
  "message": "Document created.",
  "data": { "id": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071", "label": "Vyas Statement", "status": "draft" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENTS_OWNERSHIP_IMMUTABLE",
    "message": "A document's owner, family, and template cannot be changed after creation.",
    "details": { "applicant": ["This field cannot be changed after creation."] }
  },
  "meta": {}
}
```

  Field-level serializer failures use the project-wide `VALIDATION_ERROR` with the offending fields in `details`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "template_key": ["Template key must be a lowercase ASCII slug: letters and digits in hyphen-separated segments, e.g. 'bank-vyas-statement'."] }
  },
  "meta": {}
}
```

- **HTTP status codes:** `POST /documents/` returns **201**. Every other success — `GET`, `PATCH`, status, archive, restore — returns **200**. Domain-rule violations are **400**, except state conflicts (editing an archived document, archiving twice, restoring an active one), which are **409**. Missing records named in the URL path are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Auth failures:** 401 with no token, an expired token, or a revoked session. 403 `DOCUMENTS_ACTOR_FORBIDDEN` when the token is valid but the caller is not an Admin. Its body:

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENTS_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to access documents.",
    "details": {}
  },
  "meta": {}
}
```

  **This code replaces the project-wide `PERMISSION_DENIED`, it does not coexist with it.** You will not see `PERMISSION_DENIED` from `/api/v1/documents/`. It is omitted from the per-endpoint `Errors` lists in §7, since it applies identically to all nine.

- **Immutable fields are REJECTED on `PATCH`, not ignored.** `applicant`, `family`, and `template_key` return 400 `DOCUMENTS_OWNERSHIP_IMMUTABLE`; `status`, `archive_reason`, `archived_at`, and `archived_by` return 400 `DOCUMENTS_STATUS_IMMUTABLE`. Both list every offending field in `details`. **This differs from `institutions`**, which silently drops them — a read-modify-write-the-whole-object edit form carried across from that module will fail on every save. Send only the fields the user actually changed.
- **An archived document is frozen.** `PATCH` and the status action both return **409** `DOCUMENTS_DOCUMENT_NOT_EDITABLE` until it is restored. Archiving is not a soft-hide; it takes the record out of circulation.
- **A `PATCH` that changes nothing writes no audit event.** The response is still 200 with the unchanged record.
- **Query parameter encoding.** Invalid query parameters are **rejected with 400, not ignored** — `?family=banks` returns a validation error rather than an unfiltered result set. `standalone` is a boolean (`true`/`false`/`1`/`0`); omitting it returns both kinds. `page_size` above the 100 maximum is clamped.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based. `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs or `null`. Applied to all three list endpoints (documents, workspaces, history).
- **IDs:** UUID strings. `template_key` is a human-readable slug but is **not** an identifier you can address a record by.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. Documents are ordered by `-updated_at` (most recently touched first). Workspaces by `-last_updated`. History newest-first.
- **Times.** `created_at`, `updated_at`, and `archived_at` are ISO 8601 UTC. **Only `archived_at` carries a Bikram Sambat sibling**, `archived_at_bs` — an object or `null`, shaped `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`. Dates *inside* `content` are opaque frontend data and are never parsed, converted, or given a BS sibling.
- **Empty text fields are `""`, never `null`.** The nullable fields are `applicant`, `applicant_name`, `archived_at`, and `archived_by_username`.

## 4. Models

**Document (list shape)** — `{ id, applicant?, applicant_name?, is_standalone, family:[enum], template_key, label, status:[enum], is_archived, created_at, updated_at }`

- **`content` is deliberately absent from the list.** A page of twenty bank statements would otherwise carry a megabyte of transaction rows nothing renders. Fetch the detail to get a body.
- `applicant` and `applicant_name` are both `null` on a standalone document.

**Document (detail shape)** — the list shape plus `{ content:json, standalone_purpose, notes, is_editable, archive_reason, archived_at?, archived_at_bs?:json, archived_by_username?, created_by_username }`

- Returned by retrieve, create, update, status, archive, **and** restore. Only the list returns the shorter shape.
- **`content` is whatever you stored.** Its shape depends on `family` and `template_key`; the backend neither validates nor interprets it. Per-family shapes are reproduced for reference in `DATA_CONTRACT.md` §2, and the authoritative version is the frontend's own contract.
- `archive_reason` is non-empty only when `status` is `archived`; restoring clears it.

**WorkspaceSummary** — `{ applicant_id, applicant_name, document_count, last_updated }`

- One row per applicant who has **live** documents. **Standalone documents are excluded** (no applicant to group under) and **archived documents are excluded from the count** — this table answers "whose files have live work on them". To list standalone documents use `GET /documents/?standalone=true`.
- `applicant_name` prefers the applicant's English name and falls back to the Devanagari one.

**HistoryEvent** — `{ id, action, actor_type:[enum], actor_label, summary, reason, changes:json, metadata:json, created_at, created_at_bs:json }`

- `changes` maps field name to `{ "from": "...", "to": "..." }`, both stringified. `{}` on creation events.
- **A body change appears as `changes.content = { "from": "<changed>", "to": "<changed>" }`** — the literal marker, never the body. The document body is never written to the audit log (§17); it may hold account numbers and transaction histories, and the audit log is a separate, widely-readable store. **You cannot recover a previous body from the history.**

### Worked examples

**Document (detail shape) — a bank statement**

```json
{
  "id": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "applicant": "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819",
  "applicant_name": "राम बहादुर",
  "is_standalone": false,
  "standalone_purpose": "",
  "family": "bank_statement",
  "template_key": "bank-vyas-statement",
  "label": "Vyas Statement",
  "content": {
    "statement_account_holder": "Ram Bahadur",
    "statement_account_no": "0123456789012",
    "statement_account_type": "Savings",
    "statement_opening_balance": 250000,
    "statement_interest": "5.5",
    "statement_tax": "5",
    "transactions": [
      { "date": "2026-04-01", "description": "Deposit", "credit": 500000 },
      { "date": "2026-05-12", "description": "Withdrawal", "debit": 120000 }
    ],
    "statement_spokesperson": "Sunita Shrestha"
  },
  "status": "draft",
  "is_archived": false,
  "is_editable": true,
  "notes": "",
  "archive_reason": "",
  "archived_at": null,
  "archived_at_bs": null,
  "archived_by_username": null,
  "created_by_username": "adminuser",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:18:47Z"
}
```

**Note what is absent and must stay absent:** no per-row `balance`, no `statement_debit_total`, no `statement_credit_total`, no closing balance, no interest or tax rows, no amount-in-words. Compute all of them at render.

**Document (detail shape) — a standalone document, archived**

```json
{
  "id": "b2c3d4e5-6f70-4819-a2b3-c4d5e6f70819",
  "applicant": null,
  "applicant_name": null,
  "is_standalone": true,
  "standalone_purpose": "Office authorisation letter commissioned by the director.",
  "family": "woda",
  "template_key": "woda-address",
  "label": "Address Declaration",
  "content": { "wodadoc_refno": "WD-2083-014", "applicant_name": "Ram Bahadur" },
  "status": "archived",
  "is_archived": true,
  "is_editable": false,
  "notes": "",
  "archive_reason": "Superseded by the 2083 revision.",
  "archived_at": "2026-07-24T10:02:00Z",
  "archived_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  },
  "archived_by_username": "adminuser",
  "created_by_username": "adminuser",
  "created_at": "2026-07-20T04:11:23Z",
  "updated_at": "2026-07-24T10:02:00Z"
}
```

## 5. Enums

- `Document.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`
  - **This is the backend's type vocabulary — not the 42 slugs.** The slug lives in `template_key` and is a validated string, not an enum, so a new bank partner needs no backend deploy.
  - Bank documents are **two** families, not one: a statement and a certificate have different content shapes and different screens.
- `Document.status`: `draft` | `ready` | `archived`
  - **There is no `printed`, and there will not be one.** Print snapshots exist (`document_history`), but capturing one deliberately does not touch this field — "has been printed" is derivable from the version chain, and a second denormalized answer here could drift from it. Ask `GET /api/v1/document-history/documents/<document_id>/snapshots/` instead.
  - **There is no `submitted`** — the frontend's third value maps to `ready`. Nothing in Grandway submits a document anywhere.
  - `archived` is **not** reachable through the status action; it requires the archive endpoint and a reason.
- `template_key`: **not an enum** — a lowercase ASCII slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, up to 100 characters, which must agree with `family` by prefix (`student-`, `woda-`, `lor-`, `moi-`, `bank-`) and, for the two bank families, by suffix (`-statement`, `-certificate`).
- `HistoryEvent.action`: `document_created` | `document_updated` | `document_status_changed` | `document_archived` | `document_restored`
- `HistoryEvent.actor_type`: `superadmin` | `admin` | `lead_manager` | `system` | `ai` — the `audit` module's enum. In practice only `admin` appears here, since only Admins can write.

## 6. Dependency order

- `Document` needs an `Applicant` **(external module: `applicants`)** — *unless* it is standalone, in which case it needs a `standalone_purpose` instead. Exactly one of the two.
- An `Applicant` needs nothing from this module.

**Start here:** for an applicant-owned document, obtain the applicant id from `GET /api/v1/applicants/` (or the file you are already viewing), then `POST /api/v1/documents/`. For a standalone document you can post immediately with a `standalone_purpose` — no prerequisite record at all.

## 7. Endpoints

### Document — `/api/v1/documents/`

**Use it when:** the Document List worklist, the Applicant Detail documents panel (`?applicant=`), the standalone documents list (`?standalone=true`), the Document Workspace, and the New Document form.

**Methods:**
- `GET /api/v1/documents/` — list (permission: `documents.document.list`, risk: medium)
- `POST /api/v1/documents/` — create (permission: `documents.document.create`, risk: medium)
- `GET /api/v1/documents/<document_id>/` — retrieve (permission: `documents.document.read`, risk: **high**)
- `PATCH /api/v1/documents/<document_id>/` — update (permission: `documents.document.update`, risk: **high**)

**Send (create/update):**
- create: `family` (**required**), `template_key` (**required**), `label` (**required**); then **either** `applicant` (UUID) **or** `standalone_purpose`; plus optional `content`, `notes`
- update: any subset of `label`, `content`, `standalone_purpose`, `notes` — **and nothing else**

**Returns:** Document (detail shape) for create, retrieve, and update; list[Document (list shape)] for the list, paginated.

**Requires state:** for an applicant-owned document, an existing applicant. Nothing about the applicant's status is checked — a document may be created against a dormant or archived applicant.

**Side effects:** appends `document_created` / `document_updated` to the central audit log. **The body is redacted from the event** — see §4 `HistoryEvent`. Nothing outside this module changes.

**Notes:**
- **List filters:** `applicant` (UUID), `standalone` (bool), `status`, `family` (exact enums), `template_key` (exact string), `search` (partial match on `label` only), `fiscal_year` (`YYYY/YY`, on `created_at`), `page`, `page_size`.
- **`search` does not reach into `content`.** Searching for an account number returns nothing, deliberately — full-text search over personal financial data is a decision this module has not made.
- **Omitting `status` returns archived documents too.** Pass `status=draft` or `status=ready` for a live worklist.
- `content` defaults to `{}` — a workspace is opened before anything is typed into it.
- **`content` must be a JSON object** (not an array or scalar) and must serialize under **256 KiB**. A very long bank statement is the realistic way to hit that.
- **Immutable on update:** `applicant`, `family`, `template_key` → 400 `DOCUMENTS_OWNERSHIP_IMMUTABLE`; `status` and the archive fields → 400 `DOCUMENTS_STATUS_IMMUTABLE`.
- **An archived document returns 409 on `PATCH`.** Restore it first.
- There is no delete.

**Errors:**
- `DOCUMENTS_APPLICANT_NOT_FOUND` (400) — no applicant with that id, on create
- `DOCUMENTS_OWNER_REQUIRED` (400) — neither an applicant nor a standalone purpose was given, or a standalone document's purpose was cleared
- `DOCUMENTS_TEMPLATE_KEY_INVALID` (400) — the slug does not agree with the family
- `DOCUMENTS_CONTENT_INVALID` (400) — the body is not a JSON object
- `DOCUMENTS_CONTENT_TOO_LARGE` (400) — the body exceeds 256 KiB
- `DOCUMENTS_OWNERSHIP_IMMUTABLE` (400) — a `PATCH` carried the applicant, family, or template key
- `DOCUMENTS_STATUS_IMMUTABLE` (400) — a `PATCH` carried a standing field
- `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409) — the document is archived
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document workspaces — `/api/v1/documents/workspaces/`

**Use it when:** the Documents landing table — applicants who have live document work, one row each.

**Methods:**
- `GET /api/v1/documents/workspaces/` — (permission: `documents.document.list_workspaces`, risk: medium)

**Send:** nothing beyond `page` / `page_size`.

**Returns:** list[WorkspaceSummary], ordered by most recent edit, paginated.

**Requires state:** nothing. Returns an empty array when no applicant has live documents.

**Side effects:** none.

**Notes:**
- **Standalone documents are excluded** — they have no applicant to group under. List them with `GET /documents/?standalone=true`.
- **Archived documents are excluded from `document_count`**, and an applicant whose documents are all archived does not appear at all.
- `last_updated` is the maximum `updated_at` across that applicant's live documents.
- Note the **trailing slash**, and that this is a literal path segment — it is not a document id.

**Errors:** none beyond the global authority failure.

### Document: status — `/api/v1/documents/<document_id>/status/`

**Use it when:** the workspace's "mark ready" control, and moving a document back to draft.

**Methods:**
- `POST /api/v1/documents/<document_id>/status/` — (permission: `documents.document.change_status`, risk: medium)

**Send:** `status` — **`draft` or `ready` only**.

**Returns:** Document (detail shape).

**Requires state:** the document must not be archived.

**Side effects:** appends `document_status_changed`.

**Notes:**
- **`archived` is not accepted here** and fails serializer validation with `VALIDATION_ERROR` on the `status` field. Archiving requires its own endpoint and a reason, so a document is never retired without one.
- Re-sending the current status is a no-op: 200, no event.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_EDITABLE` (409) — the document is archived
- `DOCUMENTS_STATUS_INVALID_TRANSITION` (400) — reserved for a status outside the selectable set that passes serializer validation
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document: archive — `/api/v1/documents/<document_id>/archive/`

**Use it when:** the workspace's "retire" action. **This is what a delete button becomes.**

**Methods:**
- `POST /api/v1/documents/<document_id>/archive/` — (permission: `documents.document.archive`, risk: high)

**Send:** `reason` (**required**, non-empty).

**Returns:** Document (detail shape), with `status: "archived"`, `is_editable: false`, and `archived_at` / `archived_by_username` stamped.

**Requires state:** the document must not already be archived.

**Side effects:** appends `document_archived` with the reason attached. **The document remains in the directory and in unfiltered list results** — archiving is not hiding.

**Notes:**
- **The reason is mandatory.** Archived documents are kept forever, so "why is this one archived" must be answerable from the record.
- **After archiving, the document is frozen** — `PATCH` and the status action both return 409. Label it clearly; a UI that leaves the workspace editable will produce failed saves.

**Errors:**
- `DOCUMENTS_DOCUMENT_ALREADY_ARCHIVED` (409)
- `DOCUMENTS_ARCHIVE_REASON_REQUIRED` (400) — reason missing or whitespace-only
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document: restore — `/api/v1/documents/<document_id>/restore/`

**Use it when:** bringing an archived document back for correction.

**Methods:**
- `POST /api/v1/documents/<document_id>/restore/` — (permission: `documents.document.restore`, risk: high)

**Send:** nothing.

**Returns:** Document (detail shape), with `status: "draft"` and the three archive fields cleared.

**Requires state:** the document must be archived.

**Side effects:** appends `document_restored`. **Clearing the archive fields does not erase the archiving from history** — `document_archived` and its reason stay in the history endpoint.

**Notes:**
- **Restore always returns to `draft`, never to `ready`**, even if the document was `ready` when archived. Whoever archived it may have done so precisely because it was not ready, and a restore should not re-assert a judgement nobody made.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_ARCHIVED` (409)
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

### Document: history — `/api/v1/documents/<document_id>/history/`

**Use it when:** the history panel on the Document Workspace.

**Methods:**
- `GET /api/v1/documents/<document_id>/history/` — (permission: `documents.document.list_history`, risk: medium)

**Send:** nothing.

**Returns:** list[HistoryEvent], newest first, paginated.

**Requires state:** the document must exist.

**Side effects:** none.

**Notes:**
- Never empty for an existing document — creation always writes one event.
- **A body change is recorded as a marker, not as content.** This endpoint tells you *that* the document changed and who changed it, never what it said. **You cannot reconstruct a previous body from it** — that is what `document_history` print snapshots are for, and only for edits somebody captured a snapshot of.

**Errors:**
- `DOCUMENTS_DOCUMENT_NOT_FOUND` (404)

## 8. Flows

**Create and work on an applicant's document** *(Admin)*

1. `GET /api/v1/documents/?applicant=<applicant_id>` — the Applicant Detail documents panel.
2. `POST /api/v1/documents/` with `applicant`, `family`, `template_key`, and `label`. → document id, `status: "draft"`, `content: {}`.
   - A `family` and `template_key` from different pickers → 400 `DOCUMENTS_TEMPLATE_KEY_INVALID`.
   - No applicant and no purpose → 400 `DOCUMENTS_OWNER_REQUIRED`.
3. `GET /api/v1/documents/<id>/` — the workspace loads the body.
4. `PATCH /api/v1/documents/<id>/` with `content` on each save. **Send the complete body**; it is replaced wholesale, not merged.
   - Send only the input fields. Do not send computed balances, totals, or amounts-in-words — the backend stores whatever it is given, and a stored derived value will be stale the moment the inputs change.
5. `POST /api/v1/documents/<id>/status/` with `ready` when the document is finished.
6. **Print** — save first, then `POST /api/v1/document-history/documents/<document_id>/snapshots/` (module: `document_history`). Capture reads the *committed* row, so an unsaved workspace is not what gets frozen.

**Create a standalone document** *(Admin)*

1. `POST /api/v1/documents/` with `standalone_purpose` and **no** `applicant`. → `is_standalone: true`.
2. Work it exactly as above.
3. Find it again with `GET /api/v1/documents/?standalone=true` — it will **not** appear in `GET /documents/workspaces/`, which groups by applicant.

**Retire a document and bring it back** *(Admin)*

1. `POST /api/v1/documents/<id>/archive/` with a reason. → `status: "archived"`, `is_editable: false`.
   - No reason → 400 `DOCUMENTS_ARCHIVE_REASON_REQUIRED`. Make the reason input mandatory before submit.
2. **The workspace must go read-only now.** Any `PATCH` returns 409 `DOCUMENTS_DOCUMENT_NOT_EDITABLE`.
3. The document still appears in `GET /api/v1/documents/` with no `status` filter, and in `?status=archived`.
4. `POST /api/v1/documents/<id>/restore/` → back to `draft` and editable.
5. `GET /api/v1/documents/<id>/history/` still shows `document_archived` with the original reason.

**Build the documents landing table** *(Admin)*

1. `GET /api/v1/documents/workspaces/` → one row per applicant with live documents: id, name, count, last edit.
2. Clicking a row → `GET /api/v1/documents/?applicant=<applicant_id>` for that applicant's documents.
3. Standalone documents need their own tab — they are absent from step 1 by design.

## 9. Gaps

### Blocking — features the concept describes that have no endpoints

- **No signatory list, and signature references are unvalidated.** `content.instructorId` / `content.directorId` on certificate templates point at a Signature table owned by the unbuilt `document_templates`. They round-trip as opaque strings; a document may name a signatory that never existed.
- **No supporting files.** `uploaded_files` does not exist, so nothing can be attached to a document.
- **No template registry.** `template_key` is format-checked and family-checked but not checked against a list of real templates. A typo that happens to match the family prefix — `bank-vyass-statement` — is accepted.

### Behavioural — things that will surprise a client

- **A client-supplied derived value is stored, not stripped.** Posting `statement_debit_total` gets it persisted and returned. The backend cannot strip it without knowing all 42 shapes, and stripping would break "preserve any extra keys". **Never read a derived value back from the API as truth** — recompute from the inputs.
- **`content` is replaced wholesale on `PATCH`, not merged.** Sending `{"content": {"a": 1}}` on a document whose body had ten keys leaves it with one. Send the complete body.
- **A previous body is recoverable only if somebody printed it.** This module has no field history, no versioning, and its audit log redacts the body. `document_history` snapshots are the only record of a previous body — so editing a document that was never printed still loses its previous contents irrecoverably. It is a print log, not an autosave.
- **`content` is not sanitized or escaped.** It is returned exactly as stored; escaping on render is the frontend's responsibility.
- **`?search=` matches `label` only** — not the body, not the applicant's name, not `template_key`.
- **No cascade from applicants.** `applicant` is `PROTECT`: an applicant with documents cannot be deleted, and no document is ever removed as a side effect of anything.
- **No bulk operations.** No bulk create, bulk archive, or bulk export.

### Frontend contract reconciliation

The uploaded `frontend_api-used.md` and `frontend_data-contract.md` describe a **different backend** — a different project, different auth, and a different response envelope. Every row below is a real difference the client must adapt to.

| The frontend docs assume | Grandway actually |
|---|---|
| `POST /api/auth/login/` with `{ email, password }` | `POST /api/v1/auth/login/` with `{ username, password, device_id }` |
| `{ data, meta: { total, page, pageSize } }` | `{ success, message, data, meta: { count, page, page_size, next, previous } }` |
| `GET /api/auth/users/me/` | `GET /api/v1/auth/me/` |
| `studentId` on a document | `applicant` (UUID) |
| `GET /students/:studentId/documents` | `GET /api/v1/documents/?applicant=<id>` |
| `GET /students/:studentId/full` | `GET /api/v1/applicants/<id>/` — exists, but **without** `summary`, `skills`, `experience`, IELTS scores, or education history: `education` and `test_scores` are not built |
| `DELETE /documents/:id` → 204, and cascade-delete of print logs | **No delete exists.** `POST /api/v1/documents/<id>/archive/` with a reason |
| Deleting a student removes their documents | **Never.** `applicant` is `PROTECT` |
| `type: "bank-vyas-statement"` (one field) | `family: "bank_statement"` **and** `template_key: "bank-vyas-statement"` (two fields, cross-validated) |
| `status: draft \| submitted \| archived` | `draft \| ready \| archived` — `submitted` becomes `ready` |
| `GET /documents/workspaces` | `GET /api/v1/documents/workspaces/` — note the trailing slash |
| `DocumentWorkspaceSummary.studentId` / `.studentName` | `applicant_id` / `applicant_name` |
| `GET /documents/:id/print-logs`, `POST` the same | Built, in a **different module and at a different path**: `GET /api/v1/document-history/documents/<document_id>/timeline/` and `POST /api/v1/document-history/documents/<document_id>/snapshots/` |
| `GET /signatures?active=true` | **Not built** — needs `document_templates` |
| Any authenticated user reaches these screens | **Admin only.** A Lead Manager gets 403 on every route, reads included |

**What the frontend gets right and must keep:** `content` carries input fields only; derived values are computed at render and never persisted. That is exactly this backend's contract, and the one thing in the uploaded docs that needed no reconciliation at all.
