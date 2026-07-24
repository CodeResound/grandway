# Integration — Document History

**Owner app:** `document_history`
**Version:** 1.0.3
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 6 endpoints, two resources |
| 1.0.1 | 2026-07-24 | AI (Claude) | No endpoint change. Defects found by the §19.5 consumer-comprehension test: added success status codes, the recovery response shape, the 403 to every `Errors` list, the Bikram Sambat `fiscal_year` warning, corrected the query-parameter rule, and recorded three new gaps |
| 1.0.2 | 2026-07-24 | AI (Claude) | No endpoint change. Second §19.5 review round: declared the recovery `Document` field set complete, defined `is_editable`, disambiguated the `-id` tiebreaker, removed a stale claim that the 403 was absent from §7's error lists, and documented capture-note propagation, empty-body capture, nullable BS objects, response size, and the unenforced permission keys |
| 1.0.3 | 2026-07-24 | AI (Claude) | No endpoint change. Recorded that the signatory ids frozen into `render_context` now resolve against `document_templates` — while this module still validates nothing inside `render_context` — and that it gained no dependency on that module in either direction |

---

## 1. Module

- **Name:** Document History — the immutable print snapshots of a document, and the print events that produced them. The `documents` module owns the editable working record; this owns the frozen copies of it. **Nothing stored here is ever edited or deleted**, by any route, by the Django admin, or by any service.
- **Base path:** `/api/v1/document-history/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. **Admin authority only.** A `lead_manager` and a `superadmin` are both rejected with 403 on every route, reads included — identical to the `documents` module.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which is the whole access check here. | Every endpoint returns 401; any non-Admin gets 403 `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` everywhere. |
| `authenticate` | FK | `captured_by` and `performed_by` (both `PROTECT`) reference user accounts. | Snapshots could not record who captured or printed them. |
| `documents` | FK | Every snapshot and every print event points at exactly one `Document` (`PROTECT`). There is no standalone snapshot. | The module has nothing to snapshot. Every route is document- or snapshot-scoped; none is reachable without a document that already exists. |
| `documents` | service call | Two calls. `documents.selectors.get_document_by_id` resolves the document id in every document-scoped route. `documents.services.update_document` performs the **write** behind `snapshot.recover`. | Without the selector, every route 404s. Without the service, recovery is impossible — the snapshot could be read but never restored, and the module degrades to read-only history. |
| `audit` | service call | Every capture, reprint, and recovery appends one immutable event. This module stores no action history of its own. | Snapshots still save but leave no trace of who captured or printed them in the central log. The per-document timeline still works — it is this module's own table, not the audit log. |
| `applicants` | none | **No edge at all.** A snapshot reaches the applicant only through its document. | Nothing. |

**This module writes to exactly one thing outside itself, and only on one endpoint.** `POST /snapshots/<id>/recover/` writes `label` and `content` into the working `Document` through `documents.services.update_document`. Every other endpoint here is inert with respect to the rest of the system: capturing, listing, reading, and reprinting change nothing outside this module's own two tables. In particular, **capturing a snapshot does not change the document's `status`** — there is no `printed` status in `documents`, deliberately.

**One app this module deliberately does not contain, and which does not exist yet:**

| Missing app | What it would own | What you cannot do today |
|---|---|---|
| `uploaded_files` | File storage, verification, versioning | Attach or reference a generated PDF. **A snapshot has no file field at all** — see §9 |

**One app this module deliberately does not contain, and which now exists:** `document_templates`
(`/api/v1/document-templates/`) owns the signatory library whose ids you freeze into
`render_context.signatories`. This module holds **no dependency on it in either direction** — no
foreign key, no import, no call. It stores whatever `render_context` you send and does not resolve,
validate, or look inside it. What changed when that module shipped is that those ids now *resolve*
to something when a client looks them up; nothing about this module's behaviour changed at all.

## 3. Conventions

- **Access — Admin only, and this is unlike every module except `documents`.** `admin` may do everything; `lead_manager` and `superadmin` are refused on **every route including `GET`**. A document-history panel must be **hidden** for a Lead Manager, not rendered read-only or shown empty. The reasoning is argued in `documents`' `docs/SECURITY.md` §1 and applies to both modules; this one publishes no `SECURITY.md` of its own because it adds no security decision of its own.
- **Nothing is ever edited or deleted.** There is **no `PUT`, `PATCH`, or `DELETE` method on any endpoint**. A snapshot has no status, no lifecycle, and no retirement state — it exists, and it says what it said.
- **The backend copies the document body; it never accepts one.** A capture request has **no `content` field**. If you send one it is ignored. `content`, `family`, `template_key`, and `label` are all read off the committed document row inside the capture transaction.
- **Recovery does not rewrite history.** It writes the frozen body *forward* into the working document and leaves the snapshot untouched. It also does not create a new snapshot — your next capture does that.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to three fields to show the envelope**; a real capture returns the full `Snapshot` shape defined in §4.

```json
{
  "success": true,
  "message": "Snapshot captured.",
  "data": { "id": "7c1f9b20-3d44-4a8e-9f01-2b3c4d5e6f70", "version_number": 2, "label": "Vyas Statement" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE",
    "message": "This document is archived; restore it before recovering a snapshot into it.",
    "details": {}
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
    "details": { "event_type": ["\"printed\" is not a valid choice."] }
  },
  "meta": {}
}
```

- **Auth failures.** A valid token whose `authority_type` is not `admin` → 403 `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` on **every** route, including both `GET`s, with the body shown below. This code **replaces** the project-wide `PERMISSION_DENIED` rather than coexisting with it — a handler keyed only on the global code will never fire here. It is repeated at the head of every `Errors` list in §7 rather than left to this section, because a client that builds its error map by reading those lists would otherwise have no 403 branch at all. No token, an expired token, or a revoked session → 401 with the `authenticate` module's codes, which this contract does not enumerate — see §9.

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENT_HISTORY_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to access document history.",
    "details": {}
  },
  "meta": {}
}
```

- **HTTP status codes.** `POST /documents/<document_id>/snapshots/` (capture) and `POST /snapshots/<snapshot_id>/reprint/` return **201**. Every other success — both `GET`s and `POST .../recover/` — returns **200**. Recovery is 200 rather than 201 because it creates no resource the caller addresses; the print event it writes is a side effect, and the body it returns is a `Document` that already existed. Domain-rule violations are **400**, except the archived-document conflict, which is **409**. Missing records named in the URL path are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Query parameter encoding — read this precisely, it is not "strict validation".** A **recognised** parameter with an invalid value is **rejected with 400**: `?event_type=printed` returns a validation error rather than an unfiltered result set. An **unrecognised** parameter is **silently ignored** — `?foo=1`, and in particular a cache-busting `?_=1721815262`, is accepted and has no effect. `page_size` above the 100 maximum is **clamped, not rejected**. There is no multi-value syntax: `?event_type=capture,reprint` is one invalid value, not two valid ones, and returns 400.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based. `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `count` is the **total across all pages**, not the number of rows in `data`. `next`/`previous` are absolute URLs (scheme + host) or `null`. Applied to both list endpoints (snapshots, timeline).
- **IDs:** UUID strings, unquoted and unmarked in the shapes below — a field with no type marker is a string. `version_number` is a small integer that is unique *within one document's chain* — it is **not** a global identifier and cannot be used to address a snapshot. Address snapshots by `id`.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. Snapshots are ordered by `-version_number`, which is unique within the one document a chain is always filtered to, so that list pages stably. Print events are ordered by `-created_at` **plus `-id` as a tiebreaker** — and `id` here is the same UUID this API returns on the row, not a hidden internal key, so you can reproduce the server's ordering exactly (descending `created_at`, then descending UUID string) when merging an optimistically-appended row into a fetched page. The tiebreaker exists because `created_at` is *not* unique: a capture writes its snapshot and its event in one transaction, and two events can share a timestamp. Without it a paginated timeline could show a row twice or skip it; with it, paging is stable.
- **Times.** `created_at` is ISO 8601 UTC and carries a Bikram Sambat sibling `created_at_bs` on **both** resources — an object shaped `{ year, month, day, month_name_en, month_name_np, display_en, display_np }`, never `null` (both models always have a creation time). Dates *inside* `content` or `render_context` are opaque frontend data and are never parsed, converted, or given a BS sibling. `updated_at` is not exposed on either resource: a row that can never be updated has nothing to report there.
- **Empty text fields are `""`, never `null`.** `capture_note` and `note` are `""` when not supplied. **No field on either resource is nullable.**

## 4. Models

**Snapshot (list shape)** — `{ id, document, version_number, family:[enum], template_key, label, capture_note, captured_by_username, created_at, created_at_bs:json }`

- **`content` and `render_context` are deliberately absent from the list.** A chain of twenty bank statements would otherwise carry twenty frozen transaction arrays to render a list of dates. Fetch the detail to get a body.
- `family`, `template_key`, and `label` are **frozen copies** taken at capture, not live reads. Renaming the document later does **not** change them — that is the point of the module. A snapshot's `label` and its document's current `label` may legitimately differ, and showing the snapshot's own is the correct behaviour.

**Snapshot (detail shape)** — the list shape plus `{ content:json, render_context:json }`

- Returned by retrieve **and** by capture. Only the list returns the shorter shape.
- **`content` is whatever the document held at capture time**, byte-for-byte. Its shape depends on `family` and `template_key`; the backend neither validates nor interprets it. Per-family shapes are reproduced in `documents`' `DATA_CONTRACT.md` §2.
- **`render_context` is whatever you sent.** The backend stores it verbatim and returns it verbatim; unknown keys are preserved. Nothing validates its shape.
- **`content` holds input fields; derived values belong in `render_context`.** Nothing enforces this, but it is the whole reason both exist — see §9.

**PrintEvent** — `{ id, snapshot, document, version_number, label, event_type:[enum], note, performed_by_username, created_at, created_at_bs:json }`

- `version_number` and `label` are **read through from the referenced snapshot**, so a timeline renders without one extra request per row. They describe the snapshot, not the event.
- A `capture` event and its snapshot are created in the same transaction and share a `created_at`.
- **A capture's event copies the snapshot's `capture_note` into its own `note`.** The two are the same text, so a timeline row and a Snapshot Detail screen show the same note rather than one appearing blank. `reprint` and `recovery` events carry whatever `note` was sent on their own request, which is unrelated to the snapshot's `capture_note`.
- **A `reprint` or `recovery` event has no snapshot of its own** — it points at an existing one. Several events may name the same `snapshot`.

### Worked examples

**Snapshot (detail shape) — a captured bank statement**

```json
{
  "id": "7c1f9b20-3d44-4a8e-9f01-2b3c4d5e6f70",
  "document": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "version_number": 2,
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
  "render_context": {
    "template_version": "2026.03",
    "locale": "en",
    "computed": {
      "statement_debit_total": 120000,
      "statement_credit_total": 500000,
      "statement_closing_balance": 630000,
      "amount_in_words": "Six Hundred Thirty Thousand Only"
    },
    "signatories": [
      { "id": "9f8e7d6c-5b4a-4392-8172-6f5e4d3c2b1a", "role": "director", "name": "Sunita Shrestha" }
    ]
  },
  "capture_note": "Printed for the visa file.",
  "captured_by_username": "adminuser",
  "created_at": "2026-07-24T09:41:02Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  }
}
```

**Note the split.** `content` carries **input fields only**, exactly as `documents` stores them. Every value the frontend calculated — the two totals, the closing balance, the amount in words — is under `render_context.computed`, where it is unambiguously a frozen presentation value rather than source data. Putting a computed total inside `content` would make the snapshot indistinguishable from a document whose source data genuinely contained one.

**Document — what a recovery returns**

`POST /snapshots/<id>/recover/` returns the `documents` module's **detail shape**, not a snapshot.
That shape is owned by the other module and defined there; it is reproduced here because a consumer
integrating only this module cannot otherwise type the response of its most consequential endpoint.
**The twenty fields below are the complete set — this response carries no others**, so a strict
decoder that rejects unknown properties will not trip on it. **If the two ever disagree, `documents`'
own contract §4 is authoritative.** Fields this recovery overwrote are marked.

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
  "content": { "statement_account_holder": "Ram Bahadur", "statement_opening_balance": 250000 },
  "status": "ready",
  "is_archived": false,
  "is_editable": true,
  "notes": "Chased the bank on 12 Shrawan.",
  "archive_reason": "",
  "archived_at": null,
  "archived_at_bs": null,
  "archived_by_username": null,
  "created_by_username": "adminuser",
  "created_at": "2026-07-20T04:11:23Z",
  "updated_at": "2026-07-24T12:03:11Z"
}
```

- **`label` and `content` are the two fields the recovery wrote**, taken from the snapshot.
- **`status` and `notes` are not touched.** In this example the document was `ready` before the
  recovery and is still `ready`; the note was written after the print and survives it.
- `applicant`, `applicant_name`, `archived_at`, `archived_at_bs`, and `archived_by_username` are
  nullable — the only nullable fields in either module's payloads. `applicant` and `applicant_name`
  are both `null` on a standalone document.
- `status` is `draft` | `ready` | `archived`. A recovery cannot return `archived`: recovering into an
  archived document is a 409, so a 200 response always has `is_editable: true`.
- **`is_archived` is `status == "archived"`, and `is_editable` is its exact negation** — there is no
  third input. Use `is_editable` to enable or grey the Recover button *before* calling, rather than
  discovering the 409 afterwards; it is the same predicate the server checks.
- `updated_at` moves **only if the body actually changed**. A no-op recovery leaves it where it was —
  do not use it to detect success.
- **`archived_at_bs` is nullable here**, unlike the `created_at_bs` on this module's own two
  resources, which never is. If you write one shared decoder for the Bikram Sambat object, make it
  nullable — a non-nullable one works on every snapshot and print event and then throws the first
  time it meets an archived document.

**PrintEvent — a reprint**

```json
{
  "id": "3e4f5061-7283-4940-b5c6-d7e8f9012345",
  "snapshot": "7c1f9b20-3d44-4a8e-9f01-2b3c4d5e6f70",
  "document": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "version_number": 2,
  "label": "Vyas Statement",
  "event_type": "reprint",
  "note": "Second copy for the bank.",
  "performed_by_username": "adminuser",
  "created_at": "2026-07-24T11:15:30Z",
  "created_at_bs": {
    "year": 2083, "month": 4, "day": 8,
    "month_name_en": "Shrawan", "month_name_np": "श्रावण",
    "display_en": "2083 Shrawan 8", "display_np": "२०८३ श्रावण ८"
  }
}
```

## 5. Enums

- `PrintEvent.event_type`: `capture` | `reprint` | `recovery`
  - **`capture`** — the first and only event created alongside a new snapshot. One per snapshot, always.
  - **`reprint`** — a past snapshot printed again. No new snapshot.
  - **`recovery`** — a past snapshot's body restored into the working document. No new snapshot.
  - **The client cannot set this.** It is determined by which endpoint was called. There is no field for it in any request body.
- `Snapshot.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`
  - The same vocabulary as `documents.Document.family`, copied at capture. It is a plain `CharField` here, not a re-declared enum, so a value added by `documents` in future needs no change in this module.
- `Snapshot.template_key`: **not an enum** — a lowercase ASCII slug, copied from the document. `documents` validates its format on the way in; this module never re-checks it.

## 6. Dependency order

- A `Snapshot` needs a `Document` **(external module: `documents`)**. There is no standalone snapshot and no way to create one.
- A `PrintEvent` needs a `Snapshot` — created automatically by capture, or by calling reprint or recover on one that exists.
- A `Document` needs an `Applicant` **(external module: `applicants`)**, unless it is standalone. Nothing in this module cares which.
- Nothing in `documents` or `applicants` needs anything from this module.

**Start here:** create or open a document through `documents` (`POST /api/v1/documents/`), save its body, then `POST /api/v1/document-history/documents/<document_id>/snapshots/`. There is no route in this module you can call before a document exists.

## 7. Endpoints

### Snapshot — `/api/v1/document-history/`

**Use it when:** the Document History Timeline's version list, the Snapshot Detail screen, and the Compare Snapshots screen (which is two retrieves, diffed client-side).

**Methods:**

- `GET /documents/<document_id>/snapshots/` — the version chain (`document_history.snapshot.list`)
- `POST /documents/<document_id>/snapshots/` — capture (`document_history.snapshot.capture`)
- `GET /snapshots/<snapshot_id>/` — retrieve one in full (`document_history.snapshot.read`)

**Send (capture):**

- `render_context` — object, optional, defaults to `{}`. Everything the frontend computed or resolved at render time.
- `capture_note` — string, optional, max 2000 characters.

**Returns:** `Snapshot` (detail shape) from capture — **201** — and from retrieve — **200**; `list[Snapshot]` (list shape, no bodies) from the chain — **200**.

**Requires state:**

- The document named in the path must exist. An unknown id is a **404**, not an empty list.
- **The document does not need to be in any particular status.** An archived document may be captured — a freeze is a read.
- **The document body may be empty.** A document whose `content` is `{}` can be captured, and the snapshot faithfully records that it was empty. Nothing rejects it. If a blank capture is meaningless in your workflow, guard the button client-side — the API will not.
- **The document body must already be saved.** Capture reads the committed row; unsaved client-side edits are not in it.

**Side effects:**

- Capture writes **two rows in one transaction**: the snapshot, and its `capture` print event. It also appends one `audit` event (`snapshot_captured`).
- **Nothing outside this module changes.** In particular, the document's `status` and `updated_at` are untouched.
- The list and retrieve endpoints have **no** side effects.

**Notes:**

- `version_number` is allocated by the server as `max(existing) + 1`, under a row lock on the parent document, so concurrent captures never collide. **Do not compute it client-side.**
- `content`, `family`, `template_key`, and `label` are **copied from the document**. There is no request field for any of them, and a `content` key in the request body is ignored.
- **Query parameters** on the chain: `fiscal_year`, `page`, `page_size`.
- **`fiscal_year` is a Bikram Sambat year pair, and getting this wrong fails silently.** Send `?fiscal_year=2083/84`, **not** `2026/27`. A Gregorian-looking pair is accepted by the format check and converted as if it were BS, which puts the range in the 1960s and returns an empty list — no error, just nothing. Derive it from the `created_at_bs.year` a snapshot already returns. It filters on the **capture** date.
- Snapshots are **immutable and permanent**. There is no edit and no delete, at any level.
- **The 256 KiB `render_context` cap is measured server-side** as the UTF-8 byte length of the most compact JSON encoding of the parsed object — separators `,` and `:`, no whitespace, non-ASCII characters emitted as raw UTF-8 rather than `\uXXXX` escapes. To pre-check client-side, measure the same way; measuring your own pretty-printed or escape-encoded payload will overestimate, and Devanagari text is where the two diverge most (3 bytes raw vs 6 escaped per character).

**Errors:**

- `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403) — the caller is not an Admin. Applies to **every** method in this block, `GET` included
- `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404) — no document with that id
- `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404) — no snapshot with that id
- `DOCUMENT_HISTORY_RENDER_CONTEXT_INVALID` (400) — `render_context` is not a JSON object
- `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE` (400) — over 256 KiB serialized
- `VALIDATION_ERROR` (400) — `capture_note` too long, or a malformed `fiscal_year`

### Snapshot recovery — `POST /snapshots/<snapshot_id>/recover/`

**Use it when:** the Recover Snapshot dialog — staff have chosen an older version and confirmed they want it back in the workspace.

**Methods:**

- `POST /snapshots/<snapshot_id>/recover/` (`document_history.snapshot.recover`)

**Send:**

- `note` — string, optional, max 2000 characters. Why the recovery was performed.

**Returns:** **200** with the updated **`Document`** — the `documents` module's detail shape, **not** the snapshot. That shape is reproduced in §4 under `Document — what a recovery returns`, so you can type this response without reading the other module's contract. Drop it straight into the workspace; no follow-up fetch is needed.

**Requires state:**

- The snapshot must exist.
- **The target document must not be archived.** This is the one endpoint in the module with a state precondition, and the only one that can return 409.

**Side effects:**

- Writes `label` and `content` into the working document — **this module's only write outside itself**, and one of only two cross-app writes in the whole project (the other is lead conversion, in `leads`).
- Writes a `recovery` print event.
- Appends **two** audit events, one per module: `documents.document_updated` (with the body redacted to a `<changed>` marker) and `document_history.snapshot_recovered`.
- **The snapshot is not altered, and no new snapshot is created.** Capture again if you want the recovered state frozen.

**Notes:**

- **Only `label` and `content` are recovered.** `notes`, `status`, `applicant`, `family`, and `template_key` are not. A note written after the print survives the recovery; a document that was `ready` stays `ready`.
- **A no-op recovery is not an error.** If the body already matches, the document is unchanged and no `document_updated` event is written — but the print event and `snapshot_recovered` still are, because the action happened. Do not treat an unchanged `updated_at` as a failure.
- **There is no concurrency control on this endpoint, and no way for you to add one.** No ETag, no `If-Match`, no version or `updated_at` precondition — the request body carries nothing but an optional note. Two Admins recovering different snapshots into one document is last-write-wins, and neither is told. The database row is locked for the duration of the write, so you cannot get a torn or interleaved body — but you can absolutely get someone else's. The response is the authoritative post-recovery document: re-render from it rather than from what you had, and expect that it may not be what you asked for.

**Errors:**

- `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403) — the caller is not an Admin
- `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404) — no snapshot with that id
- `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE` (409) — **the document is archived**, not the snapshot. Restore it via `POST /api/v1/documents/<id>/restore/` and retry
- `DOCUMENT_HISTORY_CONTENT_TOO_LARGE` (400) — the frozen body no longer fits the working record's 256 KiB cap. **Unreachable today** — it can only fire if that cap is lowered in a future release. Listed because it is a stable published code, not because you should expect it; handling it is optional
- `VALIDATION_ERROR` (400) — `note` too long

### PrintEvent — `/api/v1/document-history/`

**Use it when:** the Document History Timeline — the chronological list of everything that happened to this document's history, and the screen that distinguishes an original issue from a reprint.

**Methods:**

- `GET /documents/<document_id>/timeline/` — the timeline (`document_history.print_event.list`)
- `POST /snapshots/<snapshot_id>/reprint/` — record a reprint (`document_history.print_event.reprint`)

**Send (reprint):**

- `note` — string, optional, max 2000 characters.

**Returns:** `PrintEvent` from reprint — **201**; `list[PrintEvent]` from the timeline — **200**.

**Requires state:**

- Timeline: the document named in the path must exist. An unknown id is a 404. A document that has never been printed returns an **empty list**, which is a different and correct answer.
- Reprint: the snapshot must exist. **No status precondition** — a snapshot of an archived document may be reprinted, because reprinting writes nothing to the document.

**Side effects:**

- Reprint writes **one print event and no new snapshot**, plus one `audit` event (`snapshot_reprinted`). Nothing outside this module changes.
- The timeline has no side effects.

**Notes:**

- **`event_type` is set by the endpoint you call, never by you.** There is no field for it in any request body.
- A reprint does **not** grow the version chain. If the chain is static while the timeline grows, reprints are working correctly.
- The timeline is **per-document only**. There is no cross-document print log — see §9.
- **Query parameters** on the timeline: `event_type` (`capture` | `reprint` | `recovery`, one value only — no comma list), `fiscal_year` (Bikram Sambat `YYYY/YY`, e.g. `2083/84` — see the warning in the Snapshot block), `page`, `page_size`. **There is no filter by snapshot, by actor, or by date range.** To show "every event affecting version 2" you must page the whole timeline and filter client-side.

**Errors:**

- `DOCUMENT_HISTORY_ACTOR_FORBIDDEN` (403) — the caller is not an Admin. Applies to both methods in this block
- `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND` (404) — no document with that id
- `DOCUMENT_HISTORY_SNAPSHOT_NOT_FOUND` (404) — no snapshot with that id
- `VALIDATION_ERROR` (400) — unrecognised `event_type`, malformed `fiscal_year`, or `note` too long

## 8. Flows

**Capture a print snapshot**

1. Open the document — `GET /api/v1/documents/<document_id>/` (module: `documents`) → gives `content`, `label`, `family`, `template_key`.
2. **Save any pending edits first** — `PATCH /api/v1/documents/<document_id>/`. Capture reads the committed row, not your local state.
3. Render the document client-side, computing every derived value (totals, closing balance, amount in words).
4. `POST /api/v1/document-history/documents/<document_id>/snapshots/` with `render_context` carrying those computed values, the template version, and the resolved signatories → `Snapshot` with `version_number` = *n*.
   - *Failure — 404 `DOCUMENT_HISTORY_DOCUMENT_NOT_FOUND`:* the document id is wrong or the document was never created.
   - *Failure — 400 `DOCUMENT_HISTORY_RENDER_CONTEXT_TOO_LARGE`:* the computed context exceeds 256 KiB. Realistically only a very long bank statement; trim per-row derived values before sending.
   - *Failure — 403:* the user is not an Admin. This whole feature must be hidden from them, not merely error out.

**Review a document's history**

1. `GET /api/v1/document-history/documents/<document_id>/timeline/` → the ordered list of every capture, reprint, and recovery, each with `event_type`, `version_number`, actor, and time.
2. Click a row → `GET /api/v1/document-history/snapshots/<snapshot_id>/` → the full frozen record for the Snapshot Detail screen.
   - Render the snapshot's own `label` and `render_context.computed`, **not** the document's current values. Showing live values here would defeat the module.
3. Optionally narrow to originals only — `GET .../timeline/?event_type=capture`.

**Compare two versions**

1. `GET /api/v1/document-history/documents/<document_id>/snapshots/` → the chain, with version numbers and dates.
2. `GET /api/v1/document-history/snapshots/<id_a>/` and `GET /api/v1/document-history/snapshots/<id_b>/` — **two separate calls.**
3. Diff `content` and `render_context.computed` client-side. **There is no compare endpoint** — see §9.

**Recover a prior version**

1. `GET /api/v1/document-history/snapshots/<snapshot_id>/` → show the user what they are about to restore.
2. Confirm in the Recover Snapshot dialog.
3. `POST /api/v1/document-history/snapshots/<snapshot_id>/recover/` → returns the updated `Document`.
   - *Failure — 409 `DOCUMENT_HISTORY_DOCUMENT_NOT_EDITABLE`:* the document is archived. Offer `POST /api/v1/documents/<id>/restore/` (module: `documents`) and retry.
4. Re-render the workspace from the returned document.
5. The old snapshot is still there, unchanged, and still in the chain. Capture again to freeze the recovered state as version *n+1*.

**Reprint an earlier issue**

1. `GET /api/v1/document-history/snapshots/<snapshot_id>/` → the frozen `content` and `render_context`.
2. Render output from **the snapshot's own data**, not from the live document.
3. `POST /api/v1/document-history/snapshots/<snapshot_id>/reprint/` → records the event.
   - The version chain does not grow. This is correct.

## 9. Gaps

- **A "has this been printed?" badge on a documents list costs one extra request per row, and there is no way around it.** No field on the `Document` resource reports snapshot existence or count, and **both list endpoints here require a document id** — there is no cross-document query of any kind. A 50-row Documents list with a printed indicator is 50 additional calls, against a shared 1000/hour budget with no separate throttle for this module. There is no batch endpoint, no `?document_id__in=`, and no aggregate. `GET /api/v1/audit/events/?app=document_history` is the nearest substitute and returns audit events with a different shape, from a different module. **Design the screen around this or do not build the badge** — this is a structural constraint, not an oversight to route around.
- **The actor is exposed only as a username string.** `captured_by_username` and `performed_by_username` are backed by `PROTECT` foreign keys to user accounts, but **neither id is returned**. You cannot deep-link a timeline row to a user, join to a directory, or render an avatar without a name lookup. Worse for an append-only history: a username is mutable, so renaming a user retroactively changes what every one of their past snapshots appears to say, and there is nothing to anchor the true actor to. This matches the convention in `documents` and every other module in the project — it is consistent, not accidental — but on a module whose entire purpose is proving what was issued and by whom, it is the sharpest gap in this contract.
- **`Snapshot.family` will grow without a version bump.** §5 lists six values, but the field is a plain string copied from `documents`, and a family added there appears here with no change to this module and no `/api/v2/`. **Do not generate a closed union type from §5.** Treat `family` as an open string with a fallback branch; the six values are what exists today, not a guarantee.
- **No generated-file storage or reference of any kind.** A snapshot has no file field, no PDF URL, and no attachment. `uploaded_files` does not exist, so any reference stored today would be an unresolvable string. The snapshot *is* the record; if you generate a PDF client-side you must store it yourself, and nothing in this API will know about it. `concepts/document_history.txt` names "Generated file reference" as a core entity — it is deliberately deferred, not overlooked.
- **No compare endpoint.** The concept file's "Compare Snapshots" screen is backed by two retrieves and a client-side diff. The backend does not compute, return, or store a diff between two versions.
- **No cross-document view.** Both list endpoints require a document id. You cannot ask "everything printed this month", "every snapshot of family `bank_statement`", or "everything user X printed". The `audit` module's event list (`GET /api/v1/audit/events/?app=document_history`) is the nearest available substitute and returns audit events, not snapshots.
- **`render_context` is completely unvalidated.** The backend checks only that it is a JSON object under 256 KiB. It does not know what a template version is, cannot tell a real signatory id from a typo, and will return whatever you stored forever. **If your client stops sending a computed value, older snapshots keep theirs and newer ones simply lack it** — with no error and no migration. Version your own `render_context` shape; `template_version` is the conventional place, but nothing enforces it.
- **Nothing stops a computed value being placed in `content` instead of `render_context`.** `content` is copied wholesale from the document, and `documents` does not strip derived values either. A snapshot whose `content` carries a stale `statement_closing_balance` is possible and the API will not flag it. Treat `content` as inputs and `render_context.computed` as outputs by convention — it is not enforced anywhere.
- **Signatory ids inside `render_context` are resolvable but still unvalidated.** They name records in `document_templates`, which now exists — `GET /api/v1/document-templates/signatories/<id>/` will resolve one, and a retired signatory stays retrievable forever precisely so old snapshots keep working. But **this module validates nothing inside `render_context`**: it stores whatever you send. A snapshot may still name a signatory that never existed. **Freeze the signatory's name and role alongside the id**, as the §4 worked example does — an id alone leaves a snapshot dependent on a lookup that may return a since-renamed record, which defeats the point of freezing it.
- **Capturing does not mark the document as printed.** `documents.Document.status` has no `printed` value and this module does not set one. To show "has been printed" you must call the snapshot list (or timeline) yourself; there is no count or flag on the document resource.
- **No `updated_at` on either resource.** Both models carry one internally, but neither is exposed, because a row that can never be updated has nothing to report there. Use `created_at`. (The `Document` returned by a recovery *does* carry one — it belongs to the other module.)
- **401 bodies are not enumerated here.** This contract states *that* a missing, expired, or revoked-session token returns 401 with the `authenticate` module's codes, but not what those codes are — so you cannot distinguish "refresh the token silently" from "redirect to login" without reading that module's contract. That is a real dependency this file does not remove.
- **No route-deprecation signal has ever been exercised.** The project promises a `Deprecation: <date>` header before any endpoint is removed. Nothing here is deprecated, so that mechanism is untested. Note that this module's "nothing is ever deleted" guarantee is about **rows**, not routes — it says nothing about the stability of these six paths.
- **`SnapshotImmutableError` has an error code (`DOCUMENT_HISTORY_SNAPSHOT_IMMUTABLE`) but no reachable HTTP path.** There is no update or delete endpoint that could raise it. It exists so the envelope is already defined if one is ever added. **Do not write client handling for it.**
- **No throttle beyond the project default** (`UserRateThrottle`, 1000/hour). A capture writes up to 512 KiB per call and is not separately rate-limited.
- **Snapshot retrieve is the heaviest read in the project and nothing bounds it below ~512 KiB.** A frozen body can be 256 KiB and its render context another 256 KiB, both returned in full with no field-selection parameter, no partial fetch, and no documented compression. The Compare Snapshots screen is two of these concurrently. Budget for it on a slow connection; the list endpoints exist precisely so you do not pay this to render a chain.
- **This contract cannot tell you the caller's `authority_type`, which is what every access rule here turns on.** Both this file and the project-level contract instruct you to *hide* these screens from a non-Admin rather than let them 403 — but neither states where a client reads the caller's authority from a login response. That is `authenticate`'s contract, and building the navigation gating these files demand requires reading it.
- **The permission keys in §7 are not enforced in the request path.** Every endpoint has one registered, and no view consults it — access is decided solely by the `admin` authority check. Do not build a client-side permission gate off those keys expecting the server to agree with it; today the server's only question is whether you are an Admin.
