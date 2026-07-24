# Iteration — 20260724_1639

## Document History

## 1. Module

- **Name:** Document History
- **Base path:** `/api/v1/document-history/`
- **Auth:** Bearer access JWT on every endpoint. Admin authority only — `lead_manager` and `superadmin` receive 403 on every route including reads.

## 2. Conventions

- **Response:** standard envelope — `success`, `message`, `data`, `meta`.
- **Error:** `success` is `false`; `error` carries `code`, `message`, and a `details` object that is always present (`{}` when there are no field-level errors).
- **Auth failures:** 401 with no token or an expired one. 403 `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` when the token is valid but the caller is not an Admin — on every route.
- **Pagination:** page-number based. `page` and `page_size`, default 20, max 100. `data` is the bare array of rows, not nested under `results`. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `next`/`previous` are absolute URLs or `null`.
- **IDs:** UUID strings. `version_number` is unique only within one document's chain and cannot address a snapshot.
- **Times:** `created_at` is ISO 8601 UTC, with a Bikram Sambat sibling `created_at_bs` on both resources. `updated_at` is not exposed on either.
- **HTTP status codes:** capture and reprint return **201**. Both `GET`s and recover return **200**. Domain-rule violations are 400, except the archived-document conflict which is 409. Missing path records are 404, authority failures 403, unrouted methods 405.
- **List/filter params:** snapshots accept `fiscal_year`. Timeline accepts `event_type` and `fiscal_year`. `fiscal_year` is a **Bikram Sambat** year pair — `2083/84`, not `2026/27`; a Gregorian-looking pair passes the format check, converts as if BS, and returns an empty list with no error. No search, no sort, no ordering parameter — ordering is fixed.
- **Query parameters:** a **recognised** parameter with an invalid value is rejected with 400; an **unrecognised** parameter is silently ignored; `page_size` above 100 is clamped. There is no multi-value syntax.
- **Empty text fields are `""`, never `null`.** No field on either resource is nullable.

## 3. Models

**Snapshot (list shape)** — `{ id, document, version_number, family:[enum], template_key, label, capture_note, captured_by_username, created_at, created_at_bs:json }`

- Retrieve and capture additionally return `content:json` and `render_context:json`. The list omits both.
- `family`, `template_key`, and `label` are frozen copies taken at capture, not live reads — a snapshot's `label` and its document's current `label` may legitimately differ.

**PrintEvent** — `{ id, snapshot, document, version_number, label, event_type:[enum], note, performed_by_username, created_at, created_at_bs:json }`

- `version_number` and `label` are read through from the referenced snapshot and describe the snapshot, not the event.
- Several events may name the same `snapshot`.
- Ordered by `-created_at` **plus `-id`**. `created_at` is not unique — a capture writes its snapshot and its event in one transaction — and without the tiebreaker a paginated timeline could show a row twice or skip it.

**Document** — returned by `POST /snapshots/<snapshot_id>/recover/`. The `documents` module's detail shape, not a snapshot; reproduced in this module's contract §4 so a consumer of only this module can type the response.

## 4. Enums

- `PrintEvent.event_type`: `capture` | `reprint` | `recovery`
- `Snapshot.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate` — **open, not closed.** The field is a plain string copied from `documents`; a family added there appears here with no change to this module and no version bump. Do not generate a closed union type from it.
- `Snapshot.template_key`: not an enum — a lowercase ASCII slug copied from the document.

## 5. Dependency order

- `Snapshot` needs a `Document` **(external module: `documents`)**. There is no standalone snapshot.
- `PrintEvent` needs a `Snapshot` — created automatically by capture, or by calling reprint or recover.
- `Document` needs an `Applicant` **(external module: `applicants`)** unless standalone. Nothing here cares which.

**Start here:** create or open a document through `documents`, save its body, then capture a snapshot.

## 6. Endpoints

### Snapshot — `/api/v1/document-history/`

**Use it when:** the Document History Timeline's version list, the Snapshot Detail screen, and the Compare Snapshots screen.

**Methods:**

- `GET /documents/<document_id>/snapshots/` — `document_history.snapshot.list`
- `POST /documents/<document_id>/snapshots/` — `document_history.snapshot.capture`
- `GET /snapshots/<snapshot_id>/` — `document_history.snapshot.read`

**Send (capture):**

- `render_context` — object, optional, defaults to `{}`
- `capture_note` — string, optional, max 2000 characters

**Returns:** `Snapshot` from capture and retrieve; `list[Snapshot]` from the chain, without `content` or `render_context`.

**Notes:**

- `version_number` is allocated by the server as `max(existing) + 1` under a row lock on the parent document. Do not compute it client-side.
- `content`, `family`, `template_key`, and `label` are copied from the document. **There is no `content` field in the request**, and one sent is ignored.
- An archived document may be captured — a freeze changes nothing.
- Capture writes the snapshot and its `capture` print event in one transaction, and changes nothing outside this module. In particular the document's `status` and `updated_at` are untouched.
- Snapshots are immutable and permanent — no edit, no delete, at any level.

**Errors:**

- `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404) — no document with that id
- `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404) — no snapshot with that id
- `DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID` (400) — `render_context` is not a JSON object
- `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE` (400) — over 256 KiB serialized
- `VALIDATION_ERROR` (400) — `capture_note` too long, or a malformed `fiscal_year`

### Snapshot recovery — `/api/v1/document-history/snapshots/<snapshot_id>/recover/`

**Use it when:** the Recover Snapshot dialog, after staff confirm they want an older version back in the workspace.

**Methods:**

- `POST /snapshots/<snapshot_id>/recover/` — `document_history.snapshot.recover`

**Send:**

- `note` — string, optional, max 2000 characters

**Returns:** the updated `Document` (the `documents` module's detail shape), not the snapshot.

**Notes:**

- Requires the target document **not** be archived. The only endpoint in this module with a state precondition, and the only one that can return 409.
- Restores `label` and `content` only. `notes`, `status`, `applicant`, `family`, and `template_key` are not restored.
- Writes into the working document through the `documents` module's own update service — the only write outside this module.
- Writes a `recovery` print event and appends two audit events, one per module.
- The snapshot is not altered and no new snapshot is created.
- A no-op recovery is not an error: the document is unchanged and no `document_updated` event is written, but the print event and `snapshot_recovered` still are.

**Errors:**

- `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404) — no snapshot with that id
- `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` (409) — the document is archived, not the snapshot
- `DOCUMENT_HISTORY_CONTENT_TOO_LARGE` (400) — the frozen body no longer fits the working record's cap
- `VALIDATION_ERROR` (400) — `note` too long

### PrintEvent — `/api/v1/document-history/`

**Use it when:** the Document History Timeline — the chronological list that distinguishes an original issue from a reprint.

**Methods:**

- `GET /documents/<document_id>/timeline/` — `document_history.print_event.list`
- `POST /snapshots/<snapshot_id>/reprint/` — `document_history.print_event.reprint`

**Send (reprint):**

- `note` — string, optional, max 2000 characters

**Returns:** `PrintEvent` from reprint; `list[PrintEvent]` from the timeline.

**Notes:**

- `event_type` is set by the endpoint called, never by the client. There is no field for it in any request body.
- A reprint writes one event and no new snapshot, and changes nothing in `documents`. The version chain does not grow.
- A snapshot of an archived document may be reprinted — reprinting writes nothing to the document.
- A document that has never been printed returns an empty list; an unknown document id is a 404.
- The timeline is per-document only. There is no cross-document print log.

**Errors:**

- `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404) — no document with that id
- `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404) — no snapshot with that id
- `VALIDATION_ERROR` (400) — unrecognised `event_type`, malformed `fiscal_year`, or `note` too long

## 7. Flows

**Capture a print snapshot**

1. `GET /api/v1/documents/<document_id>/` — load the body (module: `documents`).
2. `PATCH /api/v1/documents/<document_id>/` — save pending edits. Capture reads the committed row, so an unsaved workspace freezes the old body.
3. Render client-side, computing every derived value.
4. `POST /api/v1/document-history/documents/<document_id>/snapshots/` with those values under `render_context` → `Snapshot` with `version_number` = *n*.
   - Failure `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE`: trim per-row derived values.
   - Failure `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND`: the document id is wrong.

**Review a document's history**

1. `GET /api/v1/document-history/documents/<document_id>/timeline/` → every capture, reprint, and recovery with `event_type`, `version_number`, actor, and time.
2. `GET /api/v1/document-history/snapshots/<snapshot_id>/` → the full frozen record for Snapshot Detail.
   - Render the snapshot's own `label` and `render_context`, not the document's current values.
3. `GET /api/v1/document-history/documents/<document_id>/timeline/?event_type=capture` → originals only.
   - Failure `VALIDATION_ERROR`: only `capture`, `reprint`, and `recovery` are accepted; an unrecognised value is rejected, not ignored.

**Compare two versions**

1. `GET /api/v1/document-history/documents/<document_id>/snapshots/` → the chain.
2. `GET /api/v1/document-history/snapshots/<id_a>/` and `GET /api/v1/document-history/snapshots/<id_b>/` — two separate calls.
3. Diff client-side. There is no compare endpoint.

**Recover a prior version**

1. `GET /api/v1/document-history/snapshots/<snapshot_id>/` → show what will be restored.
2. `POST /api/v1/document-history/snapshots/<snapshot_id>/recover/` → the updated `Document`.
   - Failure `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` (409): the document is archived. Call `POST /api/v1/documents/<document_id>/restore/` (module: `documents`) and retry.
3. Re-render the workspace from the returned document.
4. Optionally capture again to freeze the recovered state as version *n+1*.

**Reprint an earlier issue**

1. `GET /api/v1/document-history/snapshots/<snapshot_id>/` → the frozen body and context.
2. Render from the snapshot's own data, not the live document.
3. `POST /api/v1/document-history/snapshots/<snapshot_id>/reprint/` → the event. The chain does not grow.

## 8. Gaps

- A "has been printed" badge on a documents list costs one extra request per row. No field on the `Document` resource reports snapshot existence or count, both list endpoints require a document id, and there is no batch, `__in`, or aggregate query. A 50-row list is 50 extra calls against a shared 1000/hour budget.
- The actor is exposed only as a username string. `captured_by_username` and `performed_by_username` are backed by `PROTECT` FKs, but neither id is returned — so a timeline row cannot be deep-linked to a user, and renaming a user retroactively changes what past snapshots appear to say. Consistent with every other module in the project, and the sharpest gap on a module whose purpose is proving who issued what.
- `Snapshot.family` will grow without a version bump — treat it as an open string with a fallback branch.
- No generated-file storage or reference of any kind. A snapshot has no file field, no PDF URL, and no attachment; `uploaded_files` does not exist.
- No compare endpoint. Comparing two versions is two retrieves and a client-side diff.
- No cross-document view. Both list endpoints require a document id — no "everything printed this month", no filter by family, actor, or date across documents.
- `render_context` is completely unvalidated beyond being a JSON object under 256 KiB. There is no schema, no version gate, and no migration if the client's shape changes.
- Nothing enforces that computed values go in `render_context` rather than `content`. A stale derived value frozen inside `content` is possible and unflagged.
- Signatory ids inside `render_context` reference the unbuilt `document_templates` and resolve to nothing.
- Capturing does not mark the document as printed. `documents` has no `printed` status and none is set; there is no snapshot count or flag on the document resource.
- No `updated_at` on either resource.
- `DOCUMENT_HISTORY_SNAPSHOT_IMMUTABLE` is a registered error code with no reachable HTTP path — there is no update or delete endpoint to raise it.
- No throttle beyond the project default (`UserRateThrottle`, 1000/hour), though a capture writes up to 512 KiB per call.

---

## Documents

## 1. Module

- **Name:** Documents
- **Base path:** `/api/v1/documents/`
- **Auth:** Bearer access JWT on every endpoint. Admin authority only.

## 2. Conventions

No change this session.

## 3. Models

No change this session. No field was added, removed, or renamed on `Document`.

## 4. Enums

No change this session. `Document.status` remains `draft` | `ready` | `archived` — **`printed` was considered and deliberately not added** now that `document_history` exists, because "has been printed" is derivable from the snapshot chain and a second denormalized answer here could drift from it.

## 5. Dependency order

Unchanged outbound. One inbound edge is new: `document_history` holds `PROTECT` foreign keys to `Document` and writes to it through this module's update service during a recovery. `documents` depends on `document_history` for nothing.

## 6. Endpoints

**No endpoint was added, changed, or retired in this module this session.** All nine remain exactly as registered, with the same paths, methods, permission keys, request shapes, response shapes, and error codes.

Two behavioural notes for a client, arising from the new module rather than from any change here:

- `POST /api/v1/document-history/snapshots/<snapshot_id>/recover/` can change a document's `label` and `content` without a `/api/v1/documents/` call being made. It surfaces in `GET /api/v1/documents/<document_id>/history/` as an ordinary `document_updated` event, indistinguishable from a manual edit except by its timing. Refetch after a recovery rather than trusting a cached copy.
- A document with print history cannot be deleted (`PROTECT`), which changes nothing today since this module has no delete at all.

## 7. Flows

**Prepare and print an applicant's document** — the previously unbacked print step now resolves.

1. `GET /api/v1/documents/?applicant=<applicant_id>` → the applicant's documents.
2. `POST /api/v1/documents/` with `family`, `template_key`, `label` → the working record.
3. `GET /api/v1/documents/<document_id>/` → the workspace body.
4. `PATCH /api/v1/documents/<document_id>/` → save. **Required before printing** — capture reads the committed row.
5. `POST /api/v1/document-history/documents/<document_id>/snapshots/` (module: `document_history`) → the frozen version.
   - Failure `DOCUMENTS_DOCUMENT_NOT_EDITABLE` at step 4: the document is archived; restore it first.

## 8. Gaps

- **Closed this session:** "no print snapshot and no print log" and "a previous body cannot be recovered" are no longer accurate as written. Both are now served by `document_history`.
- **Narrowed, not closed:** a previous body is recoverable **only if somebody captured a snapshot of it**. Editing a document that was never printed still loses its previous contents irrecoverably — `document_history` is a print log, not an autosave.
- **Unchanged:** no signatory list and unvalidated signature references (`document_templates` unbuilt); no supporting files (`uploaded_files` unbuilt); no template registry; a client-supplied derived value is stored rather than stripped; `content` is replaced wholesale on `PATCH`; `?search=` matches `label` only; no bulk operations.
- **Sharper now that printing works:** a generated PDF has nowhere to live. A snapshot records what was issued, but the file itself cannot be stored or referenced anywhere in the project.

---

## Core

## 1. Module

- **Name:** Core — project infrastructure and the API root.
- **Base path:** `/api/v1/` and the unversioned `/health/`, `/ready/`, `/admin/`.
- **Auth:** unchanged.

## 2. Conventions

One correction, not an addition. The project-level access table gained a **`Superadmin`** column, and it reads `no` on every row: **no business app in this project grants a superadmin anything.** Every app's access check is an exact authority match against `admin` or `lead_manager`, so a superadmin token is refused with the owning app's 403 code on every business route, reads included — not only on the Admin-only apps. This was always true and was never stated; a §19.5 comprehension test found that a reader given only the documentation would build navigation showing an Admin's panels to a superadmin and get a 403 on every call.

## 3. Models

No change this session. `core` owns no business tables; `core.policy_engine` gained six endpoint registrations but no schema change.

## 4. Enums

No change this session.

## 5. Dependency order

No change this session.

## 6. Endpoints

**No `core` endpoint was added, changed, or retired this session.** `core.api_urls` gained one route include mounting `document_history` at `/api/v1/document-history/`; the six endpoints behind it belong to that module and are listed in its block above.

Six new registrations were synced into the Core Policy Engine, and the committed registry and OpenAPI artifacts were regenerated to match:

- `document_history.snapshot.list` — `list`, `medium`
- `document_history.snapshot.capture` — `create`, `medium`
- `document_history.snapshot.read` — `read`, `high`
- `document_history.print_event.list` — `list`, `medium`
- `document_history.print_event.reprint` — `custom`, `medium`
- `document_history.snapshot.recover` — `custom`, `high`

All six sit under the existing `document_management` permission category, shared with `documents`. `document_history.snapshot.recover` carries a cross-app strict `requires` edge to `documents.document.update` — the only such edge in the registry — so a grant of recovery without document-edit authority is refused at grant time.

## 7. Flows

No `core` flow changed. The project-level dependency graph gained one node and one edge; the app inventory gained one row.

## 8. Gaps

- **Narrowed:** the project-level contract previously recorded three unbuilt document-adjacent domains. Two remain — `document_templates` and `uploaded_files` — and neither has a concept file.
- **Closed:** the access table no longer omits superadmin. It previously had only Lead Manager columns, which left a reader to infer that a superadmin inherits Admin's access. It does not.
- **Unchanged:** no host is published in the documentation set; the first account requires shell access (`bootstrap_superadmin`); rate-limit state is not exposed in response headers.
- **Note for consumers:** two unrelated mechanisms now share the word "snapshot". `offers` snapshots institution and program *names* into columns on the offer row; `document_history` snapshots a whole document body into its own table. Different mechanism, different module, no shared shape or endpoint.
