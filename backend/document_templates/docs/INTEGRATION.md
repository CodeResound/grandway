# Integration — Document Templates

**Owner app:** `document_templates`
**Version:** 1.2.0
**Status:** Active
**Created:** 2026-07-24

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-24 | AI (Claude) | Initial integration contract — 10 endpoints, two resources |
| 1.0.1 | 2026-07-24 | AI (Claude) | Defects found by the §19.5 consumer-comprehension test. **`DOCUMENT_TEMPLATES_STATUS_INVALID_TRANSITION` renamed to `..._STATUS_IMMUTABLE` for the `PATCH` guard** — no transition in this app is ever invalid, so the old name described a rule that does not exist. Documented that a rename re-derives `name`, that omitting `status` returns everything, the create-error precedence, a worked query-parameter error body, the real pagination cost of mirroring the catalogue, and four new gaps |
| 1.0.2 | 2026-07-24 | AI (Claude) | No endpoint or schema change. Corrected statements that `uploaded_files` does not exist — it shipped 2026-07-24. Same, for `signature_image_url` |
| 1.1.0 | 2026-07-25 | AI (Claude Opus 4.8) | **Breaking:** English-only names — dropped the `_np`/`_romanized` columns and renamed `_en` fields to bare (Signatory `name`/`title`). Taken in place on `/api/v1/`; see the iterations log 20260725_0037 |
| 1.2.0 | 2026-09-10 | AI (Claude Opus 5) | **Signature images are now uploadable.** New endpoint `POST /signatories/<id>/signature/` (§7), two new `Signatory` response fields (`signature_file`, `signature_source`), and a new `uploaded_files` dependency (§2). `signature_image_url` is retained and still honoured — additive, non-breaking. Retires the "no signature image storage" gap in §9 |

---

## 1. Module

- **Name:** Document Templates — the signatory library that certificate documents name, and the catalogue of template slugs the document picker offers. **This module stores what is *offered*, not what is *rendered*:** the templates themselves are frontend code, and nothing here describes how any document draws itself.
- **Base path:** `/api/v1/document-templates/`
- **Auth:** Bearer access JWT on every endpoint, obtained from `POST /api/v1/auth/login/`. **Admin authority only.** A `lead_manager` and a `superadmin` are both rejected with 403 on every route, reads included — identical to `documents` and `document_history`.
- **Status:** active

## 2. Requires

| Depends on | Kind | Why | What breaks without it |
|------------|------|-----|------------------------|
| `authenticate` | framework | Issues the access JWT and supplies `authority_type`, which is the whole access check here. | Every endpoint returns 401; any non-Admin gets 403 `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` everywhere. |
| `authenticate` | FK | `created_by` (`PROTECT`) on both models references a user account. | Neither resource could record who added it. |
| `documents` | constant + validator + service call | Three Python imports and **no database relation of any kind**: the `family` enum, the template-key slug validator, and the key/family agreement rule (a service function, called at request time). | Template creation could not validate a key at all, and this module's family vocabulary would drift from the one `documents` enforces. **Signatories are unaffected** — that half of the module has no `documents` dependency. |
| `audit` | service call | Every mutation appends one immutable event. This module stores no history of its own. | Records still save but leave no trace of who changed what. |
| `uploaded_files` | service call + FK | Signature images are stored in the file ledger, not here. `Signatory.signature_file` is a `PROTECT` foreign key into it, and the signature endpoint calls that module's `upload_file`/`replace_file`. | `POST /signatories/<id>/signature/` fails outright; `signature_file` is permanently `null` and `signature_source` never leaves `"url"`/`"none"`. Every other route in this module is unaffected. |

**This module holds exactly one database relation outside itself: `Signatory.signature_file` into `uploaded_files`.** There is still **no foreign key to `documents` in either direction**, and `documents` does not consult this catalogue — see §9, because that has a consequence you need to plan around.

**The `uploaded_files` relationship runs both ways, and this is the only such pair in the project.** A file may be *owned by* a signatory (that module's sixth owner type), and a signatory *points at* the file that currently renders. The two answer different questions — which signatory these bytes belong to, versus which file renders — and the second cannot be derived from the first, because archived and superseded predecessors remain owned by the same signatory.

**Two modules reference this one without a foreign key, and neither validates the reference:**

| Referencing module | Where | What it stores |
|---|---|---|
| `documents` | `content.instructorId`, `content.directorId` on certificate templates | This module's `Signatory.id`, as an opaque string inside an unvalidated JSON body |
| `document_history` | `render_context.signatories[].id` on a print snapshot | The same, frozen at print time |

Both stored those ids against a table that did not exist until this module shipped. **What changed is that you now have a real list to pick from. What did not change is that nothing stops either module accepting an id that was never in that list** — see §9.

**One app this module deliberately does not contain:** `uploaded_files` (`/api/v1/files/`) owns file storage, and still does — this module never stores bytes itself, it delegates. **A signature is now a real upload**, made through this module's own endpoint (§7) and stored in the ledger owned by the signatory. The older `signature_image_url` link is retained and still honoured for signatories that have no uploaded file. See §3 for the precedence rule.

## 3. Conventions

- **Access — Admin only, and unlike the other two document modules this one holds almost no sensitive data.** `admin` may do everything; `lead_manager` and `superadmin` are refused on **every route including `GET`**. A signatory is a staff member's name and their signature image; a template is a slug and a label. **There is no applicant data in this module at all.** The Admin-only rule is inherited from the consumer — a Lead Manager cannot open a document workspace, so a signatory picker is a screen they can never reach. Hide these screens for them rather than rendering them read-only.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint**. A signatory or template that is no longer current is deactivated and kept, because documents reference a template by plain string and snapshots freeze signatory ids — neither protected by a foreign key.
- **A signature can arrive two ways, and `signature_source` tells you which one won.** Upload one with `POST /signatories/<id>/signature/` (§7) and it is stored in the file ledger; or set `signature_image_url`, a plain link this API stores verbatim, never fetches, and never validates. **An uploaded file always wins when both are present.** Do not re-derive that rule — read `signature_source`, which is `"uploaded"`, `"url"`, or `"none"`, and render exactly one branch. It is computed server-side because part of the rule is invisible to you: a file that has been archived or superseded stops counting, and you have no way to see that from the signatory payload.
- **`signature_file.download_path` is a `fetch` target, not an `<img src>`.** It is a relative path to an authenticated route that answers with `Content-Disposition: attachment`. Point an `<img>` at it and you get a 401 and a broken image. Fetch it with the bearer token, then `URL.createObjectURL` the blob. **Fetch each signature once per session and hold the object URL** — the route forbids caching (`Cache-Control: no-store`) and writes an audit event on every call, so re-fetching per render fills the audit log with noise.
- **Removing a signature is archiving its file**, through `POST /api/v1/files/<file_id>/archive/` on the file module. There is no remove endpoint here. After archiving, `signature_file` returns to `null` and `signature_source` falls back to `"url"` or `"none"`.
- **Response:** the standard project envelope — `success`, `message`, `data`, `meta`. Below, `data` is **abridged to three fields to show the envelope**; a real create returns the full `Signatory` shape defined in §4.

```json
{
  "success": true,
  "message": "Signatory created.",
  "data": { "id": "9f8e7d6c-5b4a-4392-8172-6f5e4d3c2b1a", "name": "Sunita Shrestha", "status": "draft" },
  "meta": {}
}
```

  **Do not assert on `message`.** It is a human-facing string, not part of the contract. Branch on the HTTP status and, for errors, on `error.code`.

- **Error:** `success` is `false` and `error` carries a stable `code`, a human `message`, and a `details` object that is always present — `{}` when there are no field-level errors.

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENT_TEMPLATES_KEY_IMMUTABLE",
    "message": "A template's key cannot be changed after creation.",
    "details": { "key": ["This field cannot be changed after creation."] }
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
    "details": { "status": ["\"enabled\" is not a valid choice."] }
  },
  "meta": {}
}
```

  Field-level serializer failures on a request **body** use the same code with the offending fields in `details`:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed.",
    "details": { "key": ["Template key must be a lowercase ASCII slug: letters and digits in hyphen-separated segments, e.g. 'bank-vyas-statement'."] }
  },
  "meta": {}
}
```

- **Auth failures.** A valid token whose `authority_type` is not `admin` → 403 `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` on **every** route, with the body below. This code **replaces** the project-wide `PERMISSION_DENIED` rather than coexisting with it — a handler keyed only on the global code will never fire here. It is repeated at the head of every `Errors` list in §7 rather than left to this section, because a client that builds its error map from those lists would otherwise have no 403 branch. No token, an expired token, or a revoked session → 401 with the `authenticate` module's codes, which this contract does not enumerate — see §9.

```json
{
  "success": false,
  "error": {
    "code": "DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN",
    "message": "Admin authority is required to access document templates.",
    "details": {}
  },
  "meta": {}
}
```

- **HTTP status codes.** Three `POST`s return **201**: the two collection endpoints (create a signatory, register a template) and the signature upload. Every other success — all four `GET`s, both `PATCH`es, and both `POST .../status/` actions — returns **200**. The signature upload is 201 because it creates a file record, even though the body it returns is the signatory. A status action is 200 rather than 201 because it creates no resource; it returns the resource it changed. Domain-rule violations are **400** — **this module has no 409 at all**, because no operation here can conflict with another's state. Missing records named in the URL path are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Query parameter encoding.** A **recognised** parameter with an invalid value is **rejected with 400**: `?status=enabled` returns a validation error rather than an unfiltered result set. An **unrecognised** parameter is **silently ignored** — `?foo=1`, and in particular a cache-busting `?_=1721815262`, is accepted and has no effect. `page_size` above the 100 maximum is **clamped, not rejected**. There is no multi-value syntax: `?status=draft,active` is one invalid value, not two valid ones, and returns 400.
- **Request encoding:** `application/json`, **except** `POST /signatories/<id>/signature/`, which is `multipart/form-data`. **Sending JSON to it returns 415**, with no error code in the body — the parser rejects it before any handler runs.
- **Pagination:** page-number based, and the **default page size is 20** — so the 53-row template catalogue is three requests, not one. Pass `?page_size=100` to mirror it locally in a single call, and re-check that when the catalogue passes 100 rows, because the maximum clamps silently. `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `count` is the **total across all pages**, not the rows in `data`. `next`/`previous` are absolute URLs (scheme + host) or `null`. Applied to both list endpoints.
- **IDs:** UUID strings, unquoted and unmarked in the shapes below — a field with no type marker is a string. A template's `key` is a human-readable slug and is unique, but **it is not an address**: every endpoint here takes the UUID `id` in its path. There is no lookup-by-key endpoint — see §9.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. Signatories are ordered by `name` (alphabetical). Templates by `family`, then `display_order`, then `label`.
- **Times.** `created_at` and `updated_at` are ISO 8601 UTC. **Neither carries a Bikram Sambat sibling anywhere in this module** — unlike `documents` and `document_history`, which expose `archived_at_bs` and `created_at_bs`. §39.4 requires BS representation for *user-facing temporal data*; both timestamps here are system-internal bookkeeping on a reference library, and there is no business date on either resource. There is also **no `?fiscal_year=` filter** on either list, for the same reason.
- **Empty text fields are `""`, never `null`.** Every *text* field on both resources is non-null. **Exactly one field in this module is nullable: `Signatory.signature_file`**, an object, which is `null` when no uploaded signature is in force. `signature_source` is never null — it reports `"none"` instead. Nothing else on either resource can be `null`.

## 4. Models

**Signatory** — `{ id, name, title, role, signature_image_url, signature_file?:object, signature_source:[enum], status:[enum], is_active, status_note, created_by_username, created_at, updated_at }`

**SignatureFile** (the nested `signature_file` object) — `{ id, download_path, original_filename, content_type, size_bytes, version_number, uploaded_at }`

- **One shape for list and detail** — there is no large column to withhold from a list, so a second shape would exist only to drift from this one. The list carries `signature_file` too, at no extra query cost.
- **`is_active` is `status == "active"`.** A `draft` signatory is *not* active. This is the boolean to gate a picker on.
- **`role` is free text, not an enum** — see §5.
- **`signature_image_url` may be `""`.** A signatory can exist without a signature image, and one in `draft` usually does.
- **`signature_file` is `null` in three different situations** — never uploaded, uploaded then archived, uploaded then superseded through the file module directly — and you cannot tell them apart from this field. You do not need to: render from `signature_source`.
- **`size_bytes` is the stored byte count** and `version_number` counts replacements from 1. A signatory whose signature has been replaced twice shows `3`.
- **There is no field for the bytes themselves.** `download_path` is the only way to them, and it is authenticated — see §3.

**DocumentTemplate** — `{ id, key, family:[enum], label, description, display_order, status:[enum], is_active, status_note, created_by_username, created_at, updated_at }`

- **`key` is the string `documents` stores**, and the only field here that connects to anything outside this module. It is unique and immutable.
- **`label` is what you render to a user; `key` is a machine slug.** Never show the key.
- **`display_order` is per-family, not global.** Sort by `family`, then `display_order`, to reproduce the intended picker grouping. Two templates in different families routinely share a `display_order`.

### Worked examples

**Signatory — an active certificate signer**

```json
{
  "id": "9f8e7d6c-5b4a-4392-8172-6f5e4d3c2b1a",
  "name": "Sunita Shrestha",
  "title": "Director",
  "role": "director",
  "signature_image_url": "https://files.example/signatures/sunita.png",
  "signature_file": {
    "id": "3d2c1b0a-9f8e-4d7c-b6a5-948372615049",
    "download_path": "/api/v1/files/3d2c1b0a-9f8e-4d7c-b6a5-948372615049/download/",
    "original_filename": "sunita-signature.png",
    "content_type": "image/png",
    "size_bytes": 8241,
    "version_number": 2,
    "uploaded_at": "2026-09-10T11:04:22Z"
  },
  "signature_source": "uploaded",
  "status": "active",
  "is_active": true,
  "status_note": "Signature received.",
  "created_by_username": "adminuser",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T09:41:02Z"
}
```

**DocumentTemplate — a retired bank partner**

```json
{
  "id": "a1b2c3d4-5e6f-4708-9a1b-2c3d4e5f6071",
  "key": "bank-vyas-statement",
  "family": "bank_statement",
  "label": "Vyas Statement",
  "description": "",
  "display_order": 10,
  "status": "inactive",
  "is_active": false,
  "status_note": "Partner closed.",
  "created_by_username": "adminuser",
  "created_at": "2026-07-24T09:18:47Z",
  "updated_at": "2026-07-24T11:02:00Z"
}
```

**This row being `inactive` does not stop a document being created with `template_key: "bank-vyas-statement"`.** Nothing in `documents` reads this table. Enforcing the catalogue is your picker's job — see §9.

## 5. Enums

- `Signatory.status` / `DocumentTemplate.status`: `draft` | `active` | `inactive`
  - **`draft`** — created but not yet offered. Every record starts here; there is no way to create one `active`.
  - **`active`** — offered for new work. `is_active` is `true` only in this state.
  - **`inactive`** — retired. Still readable by id forever; simply not offered.
  - Any transition to any state is allowed, in any order, including `inactive` → `active`.
- `DocumentTemplate.family`: `student` | `woda` | `lor` | `moi` | `bank_statement` | `bank_certificate`
  - The same vocabulary as `documents.Document.family`, **imported from that module rather than redeclared**, so the two can never disagree. A family added there appears here with no change to this module and **no version bump** — do not generate a closed union type from this list; treat `family` as an open string with a fallback branch.
  - Bank documents are **two** families, not one, and their slugs share the `bank-` prefix while splitting on the `-statement` / `-certificate` suffix.
- `Signatory.role`: **not an enum.** Free text up to 100 characters. Observed values are `director` and `instructor` — the two slots the certificate templates fill — but nothing constrains it and nothing will reject a third. Do not build a closed dropdown from observed values.
- `DocumentTemplate.key`: **not an enum** — a lowercase ASCII slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, up to 100 characters, which must agree with `family` by prefix (`student-`, `woda-`, `lor-`, `moi-`, `bank-`) and, for the two bank families, by suffix.

## 6. Dependency order

- A `Signatory` needs **nothing**. It is the only resource in the whole document stack with no prerequisite record — you can create one against an empty database.
- A `DocumentTemplate` needs **nothing** either, though its `family` must be one of the six values `documents` defines.
- A `Document` **(external module: `documents`)** needs neither of them — it will accept any well-formed `template_key` and any string in `content.instructorId`, registered here or not.

**Start here:** `POST /api/v1/document-templates/signatories/`, then activate it. That is the shortest path to something the document workspace can actually use, because the signatory picker is the one screen in the document stack that is empty without this module.

## 7. Endpoints

### Signatory — `/api/v1/document-templates/signatories/`

**Use it when:** the Signatory Library management screen, and — the one call the frontend makes into this module — populating the **instructor/director selects** in the certificate document editor.

**Methods:**

- `GET /signatories/` — the library (`document_templates.signatory.list`)
- `POST /signatories/` — add a signer (`document_templates.signatory.create`)
- `GET /signatories/<signatory_id>/` — retrieve one (`document_templates.signatory.read`)
- `PATCH /signatories/<signatory_id>/` — correct one (`document_templates.signatory.update`)

**Send (create):**

- `name` — string, **required**, max 255.
- `title` — string, optional, max 255.
- `role` — string, optional, max 100.
- `signature_image_url` — URL, optional, max 500. The fallback signature; to upload a real image use the signature action below.

**Send (update):** any subset of the same fields. `name` is optional here. **`signature_file` is not accepted** — see the errors below.

**Returns:** `Signatory` from create — **201** — and from retrieve and update — **200**; `list[Signatory]` from the library — **200**.

**Requires state:** nothing. This resource has no prerequisites of any kind.

**Side effects:**

- Create and update each append one `audit` event. **Nothing outside this module changes** — in particular, no document or snapshot that already names a signatory is touched by editing them.
- **Renaming a signatory retroactively changes what every past document appears to say**, because `documents` stores only the id and resolves the name at render time. A snapshot is the exception: `document_history` froze the name at print time and still shows the old one. That divergence is intended — the snapshot records what was issued — but it will look like a bug if you do not expect it.
- Retrieve and list have **no** side effects.

**Notes:**

- **A new signatory is always `draft`.** There is no `status` field on create; activate it with the status action. A picker filtered to `?status=active` will not show a signatory you just created.
- **`status` is rejected on `PATCH`, not ignored** — 400 `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE`. Use the status action.
- **`signature_file` is rejected on `PATCH` too** — 400 `DOCUMENT_TEMPLATES_SIGNATURE_FILE_IMMUTABLE`. A signature is set by uploading bytes, never by naming a file id; the latter would let a caller point a signatory at any file on the platform.
- **Omitting `status` returns everything** — draft, active, and inactive alike. There is no implicit `active` default. That is what a management screen wants and the opposite of what a picker wants, so the picker must pass `?status=active` explicitly.
- **Query parameters:** `status`, `role` (exact, case-insensitive), `search`, `page`, `page_size`. `search` matches `name`; it does **not** match `title` or `role`. (Before v1.1.0 there were three name forms; there is one.)

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403) — the caller is not an Admin. Applies to every method in this block, `GET` included
- `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404) — no signatory with that id
- `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400) — a `PATCH` carried `status` or `status_note`
- `DOCUMENT_TEMPLATES_SIGNATURE_FILE_IMMUTABLE` (400) — a `PATCH` carried `signature_file`
- `VALIDATION_ERROR` (400) — missing `name`, a malformed `signature_image_url`, an over-long field, or an unrecognised `status` in the query string

### Signatory status — `POST /signatories/<signatory_id>/status/`

**Use it when:** activating a new signer once their signature image has been uploaded, or retiring one who has left.

**Methods:**

- `POST /signatories/<signatory_id>/status/` (`document_templates.signatory.change_status`)

**Send:**

- `status` — **required**, one of `draft` | `active` | `inactive`.
- `note` — string, optional, max 2000.

**Returns:** `Signatory` — **200**.

**Requires state:** the signatory must exist. **No status precondition** — any transition is allowed from any state, including reactivating a retired signer.

**Side effects:** appends one `audit` event and sets `status_note`. **Documents and snapshots that already name this signatory are completely unaffected** — deactivating removes them from the picker and nothing else.

**Notes:**

- **The note is optional on every transition**, unlike archiving a document in the `documents` module, which demands a reason. Deactivating here is reversible and loses nothing.
- Setting the status it already has, with no note, is a no-op and writes no event.

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403)
- `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404)
- `VALIDATION_ERROR` (400) — missing `status`, a status outside the enum, or a `note` over 2000 characters

### Signatory signature — `POST /signatories/<signatory_id>/signature/`

**Use it when:** the Signatory Library's "upload signature" control, both for a new signer and for replacing a signature that has changed. This is the **only** way to attach signature bytes to a signatory.

**Methods:**

- `POST /signatories/<signatory_id>/signature/` (`document_templates.signatory.upload_signature`)

**Send:** `multipart/form-data`, **not JSON** — a JSON body is refused with **415** before any handler runs.

- `file` — **required**, exactly one part. PNG, JPG/JPEG, or WEBP only, max 10 MB. **Send exactly one file part**: the platform accepts at most one per request, and a second part fails during parsing as a **500**, not a validation error.
- `notes` — string, optional. Stored against the file, not the signatory.

**Returns:** `Signatory` — **201** — not the file. That is deliberate: the response is what a client re-renders the whole row from, and it carries `signature_source`, which the file shape alone could not tell you.

**Requires state:** the signatory must exist. **No other precondition.** Its status is irrelevant — a `draft`, `active`, or `inactive` signatory may all receive a signature, because a retired signer's certificates must stay reprintable. No prior signature is required, and an existing one does not need to be removed first.

**Side effects:**

- **A row is created in `uploaded_files`** owned by this signatory, categorised `signature_image`, verification status `pending`.
- **If a signature was already in force, it is superseded** — the new file is version *n+1* with the old one as its predecessor. The old bytes are kept and readable through `GET /api/v1/files/<old_id>/versions/`. Nothing is deleted.
- **`Signatory.signature_file` is re-pointed** and `signature_source` becomes `"uploaded"`.
- **Two `audit` events are written**, one in each module: the file ledger records that bytes arrived, this module records that the signatory's signature changed.
- **Documents and snapshots already naming this signatory are not touched** — but see the note below about what they will *render*.

**Notes:**

- **Replacing a signature changes what past certificates render.** A snapshot freezes a signatory's name and role but **never the image**, so a reprint resolves the signature live. Replace a director's signature and every historical reprint shows the new one, beside the frozen old name. That divergence is a real consequence, not a bug — if a reprint must be byte-identical, freeze the image on your side at print time.
- **A second upload after the previous signature was archived starts a fresh chain at version 1**, rather than failing. Removal must not have to be undone before a replacement can be added.
- **The type rule here is stricter than the file module's.** That module accepts PDF, DOCX, and XLSX too; a signature must be an image. Both checks apply, narrower first.
- **The leading bytes must match the extension.** A PDF renamed `signature.png` is refused.
- **Every rejection carries a `DOCUMENT_TEMPLATES_*` code**, never an `UPLOADED_FILES_*` one, even though the file module raised it. You will never see another module's namespace on this route.
- **To remove a signature**, archive its file: `POST /api/v1/files/<file_id>/archive/` with a `reason`. There is no removal endpoint here.
- **Uploading through `POST /api/v1/files/` with `signatory=<id>` is possible but does not set the link** — the file will be owned by the signatory and will never render. Use this endpoint.

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403) — the caller is not an Admin
- `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404) — no signatory with that id. Checked *after* authority, so a refused caller cannot probe for ids
- `DOCUMENT_TEMPLATES_SIGNATURE_NOT_AN_IMAGE` (400) — not PNG/JPG/JPEG/WEBP
- `DOCUMENT_TEMPLATES_SIGNATURE_FILE_TOO_LARGE` (400) — over 10 MB
- `DOCUMENT_TEMPLATES_SIGNATURE_FILE_CONTENT_MISMATCH` (400) — the bytes contradict the extension
- `VALIDATION_ERROR` (400) — no `file` part, or an empty one
- *(no code)* **415** — a JSON body was sent to this multipart-only route
- *(no code)* **405** — any method other than `POST`

### DocumentTemplate — `/api/v1/document-templates/templates/`

**Use it when:** the Template Catalog management screen, and backing the **document type picker** in the New Document form so a retired bank partner stops being offered without a frontend deploy.

**Methods:**

- `GET /templates/` — the catalogue (`document_templates.template.list`)
- `POST /templates/` — register a slug (`document_templates.template.create`)
- `GET /templates/<template_id>/` — retrieve one (`document_templates.template.read`)
- `PATCH /templates/<template_id>/` — edit one (`document_templates.template.update`)

**Send (create):**

- `key` — string, **required**, max 100. A lowercase ASCII slug that must agree with `family`.
- `family` — **required**, one of the six values in §5.
- `label` — string, **required**, max 255.
- `description` — string, optional, max 5000.
- `display_order` — integer ≥ 0, optional, defaults to 0.

**Send (update):** any subset of `family`, `label`, `description`, `display_order`. **`key` is not accepted.**

**Returns:** `DocumentTemplate` from create — **201** — and from retrieve and update — **200**; `list[DocumentTemplate]` from the catalogue — **200**.

**Requires state:** nothing. No prerequisite record of any kind.

**Side effects:** create and update each append one `audit` event. **Nothing outside this module changes**, and in particular no existing document is affected by anything done here.

**Notes:**

- **`key` is immutable and is rejected on `PATCH`, not dropped** — 400 `DOCUMENT_TEMPLATES_KEY_IMMUTABLE`. Documents point at it as a plain string with no foreign key behind them.
- **Send `key` and `family` together, from one picker.** A `bank-vyas-statement` slug under family `lor` is refused. Deriving the family from the slug client-side is the reliable way to keep them in step.
- Changing `family` re-runs the agreement check against the existing `key`, so most family edits on an existing row will fail — which is intended.
- **A new template is always `draft`.** A picker filtered to `?status=active` will not show one you just registered.
- **Omitting `status` returns everything**, as on signatories. Pickers pass `?status=active`.
- **Query parameters:** `family`, `status`, `search`, `page`, `page_size`. `search` matches `label` and `key`.

**Errors** — and when a payload trips more than one, they fire in this order: serializer validation first, then uniqueness, then the family agreement rule. A malformed slug that is *also* a duplicate returns `VALIDATION_ERROR`; a well-formed duplicate that *also* mismatches its family returns `KEY_ALREADY_EXISTS`. Highlight the field named in `details` rather than guessing which rule the user broke.

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403)
- `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404) — no template with that id
- `DOCUMENT_TEMPLATES_KEY_ALREADY_EXISTS` (400) — that slug is already registered
- `DOCUMENT_TEMPLATES_KEY_IMMUTABLE` (400) — a `PATCH` carried `key`
- `DOCUMENT_TEMPLATES_TEMPLATE_KEY_INVALID` (400) — the slug and family disagree
- `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400) — a `PATCH` carried `status` or `status_note`
- `VALIDATION_ERROR` (400) — a malformed slug, a missing required field, or an unrecognised `family`/`status` in the query string

### DocumentTemplate status — `POST /templates/<template_id>/status/`

**Use it when:** publishing a newly registered slug to the picker, or retiring a bank partner.

**Methods:**

- `POST /templates/<template_id>/status/` (`document_templates.template.change_status`)

**Send:**

- `status` — **required**, one of `draft` | `active` | `inactive`.
- `note` — string, optional, max 2000.

**Returns:** `DocumentTemplate` — **200**.

**Requires state:** the template must exist. No status precondition.

**Side effects:** appends one `audit` event and sets `status_note`. **No existing document changes, and none can break** — `documents` does not consult this table, so retiring a row changes exactly one thing: whether your picker still offers it.

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403)
- `DOCUMENT_TEMPLATES_TEMPLATE_NOT_FOUND` (404)
- `VALIDATION_ERROR` (400) — missing `status`, a status outside the enum, or a `note` over 2000 characters

## 8. Flows

**Add a certificate signer**

1. `POST /api/v1/document-templates/signatories/` with `name`, `title`, and `role` → `Signatory`, `status: "draft"`, `signature_source: "none"`.
   - *Failure — `VALIDATION_ERROR` on `name`:* the name is required.
2. `POST /api/v1/document-templates/signatories/<id>/signature/` as `multipart/form-data` with one `file` part → `Signatory`, `signature_source: "uploaded"`, `signature_file.version_number: 1`.
   - *Failure — `DOCUMENT_TEMPLATES_SIGNATURE_NOT_AN_IMAGE`:* PNG, JPG/JPEG, or WEBP only.
   - *Failure — `DOCUMENT_TEMPLATES_SIGNATURE_FILE_TOO_LARGE`:* 10 MB cap.
   - *Alternative, no upload:* `PATCH` the signatory with `signature_image_url` instead → `signature_source: "url"`. You host the image; this API never fetches or validates it.
3. `POST /api/v1/document-templates/signatories/<id>/status/` with `{"status": "active"}` → now `is_active: true`.
4. `GET /api/v1/document-templates/signatories/?status=active` → the signer now appears in the picker.

**Render a signature into a certificate**

1. `GET /api/v1/document-templates/signatories/<id>/` → read `signature_source`.
2. Branch on it, and only on it: `"uploaded"` → step 3; `"url"` → render `signature_image_url` directly; `"none"` → render no signature.
3. `fetch(signature_file.download_path)` **with the bearer token**, then `URL.createObjectURL(blob)` and use that as the `<img src>`.
   - *Failure — 401:* you pointed an `<img>` straight at `download_path`. It is an authenticated route; fetch it instead.
   - *Failure — 404:* the file row exists but its bytes do not — a media volume restored older than the database. Report it; no client action fixes it.
4. **Cache the object URL for the session.** The route forbids browser caching and audits every read, so re-fetching per render floods the audit log and burns the shared 1000/hour request budget.

**Replace a signature that has changed**

1. `POST /api/v1/document-templates/signatories/<id>/signature/` with the new image → `version_number` increments; the previous file is superseded, not deleted.
2. `GET /api/v1/files/<old_file_id>/versions/` (module: `uploaded_files`) → the full chain, if you need to show history.
   - **Every historical reprint now renders the new signature**, because a snapshot freezes the signer's name but never the image.

**Remove a signature**

1. Read `signature_file.id` from the signatory.
2. `POST /api/v1/files/<file_id>/archive/` (module: `uploaded_files`) with a `reason` — **there is no removal endpoint in this module**.
3. `GET /api/v1/document-templates/signatories/<id>/` → `signature_file` is `null` and `signature_source` has fallen back to `"url"` or `"none"`.
   - The bytes are kept and the link still points at them; only the rendering stops.

**Fill the instructor/director selects on a certificate**

1. `GET /api/v1/document-templates/signatories/?status=active` → the options.
2. The user picks two; put their **`id`** values into `content.instructorId` and `content.directorId`.
3. `PATCH /api/v1/documents/<document_id>/` (module: `documents`) with the complete `content` → saved.
   - **Nothing validates those ids** — `documents` accepts any string. Sending a typo, a stale id, or an id of a `draft` signatory all succeed silently. Your picker is the only guard.
4. On print, `POST /api/v1/document-history/documents/<document_id>/snapshots/` (module: `document_history`) with the resolved signatory name and role frozen into `render_context.signatories` — so the snapshot survives the signer later being renamed or retired.

**Retire a bank partner from the picker**

1. `GET /api/v1/document-templates/templates/?family=bank_statement&status=active` → find the row.
2. `POST /api/v1/document-templates/templates/<id>/status/` with `{"status": "inactive", "note": "Partner closed."}`.
3. The row is now absent from `?status=active` and still retrievable by id.
   - **Every existing document using that slug is untouched and still fully editable**, because `documents` never reads this table. If you need those documents blocked, that is a client decision — this API will not make it for you.

**Build the New Document type picker**

1. `GET /api/v1/document-templates/templates/?status=active` → the catalogue, already grouped by `family` and ordered by `display_order`.
2. Group by `family`, render `label`, and send the row's `key` as `template_key` when creating the document.
3. Send the `family` from the same row — `documents` cross-validates the pair and will reject a mismatch.
   - **A slug absent from this catalogue is still accepted by `documents`.** The catalogue constrains your picker, not the API.

## 9. Gaps

- **`family` is an open enum and there is no endpoint that enumerates it.** §5 tells you not to generate a closed union, because a seventh family can appear with no version bump — but nothing here returns the current set, and `POST /templates/` validates `family` server-side while `GET /templates/?family=…` **rejects an unrecognised value with 400**. So a hardcoded list that lags behind the backend cannot register the new family, and one that leads breaks your own catalogue filter. There is no metadata endpoint anywhere in this project; adding a family is a backend deploy that silently invalidates your client's copy.
- **`role` is unconstrained free text.** Two values are in use (`director`, `instructor`) because that is what the certificate templates read, but any 100-character string is accepted. Do not build a closed dropdown from what you observe, and **do not filter the signatory picker by `role`** — a director may legitimately sign in the instructor slot.
- **No concurrency control anywhere.** No ETag, no `If-Match`, no `updated_at` precondition; the request bodies carry nothing that could express one. Two Admins editing the same signatory is last-write-wins and neither is told. Defensible for a small reference library, but it is your decision to make, so it is stated rather than left to be discovered.

- **This catalogue is advisory. `documents` does not enforce it, and that is the single most important thing to plan around.** `POST /api/v1/documents/` accepts any well-formed `template_key` that matches its family prefix, registered here or not, `active` or `inactive`. A typo that happens to match the prefix — `bank-vyass-statement` — is accepted by that module today and will still be accepted tomorrow. **If you want only catalogued templates used, your picker must be the only path to document creation** — there is no server-side guard, and none is planned in this module.
- **Signatory ids are still unvalidated everywhere they are used.** `documents` stores `content.instructorId` / `content.directorId` as opaque strings inside an unvalidated JSON body, and `document_history` freezes whatever it was given. Neither module checks that the id names a real signatory, or an active one. **A document can name a signatory that never existed**, exactly as before this module shipped — the difference is that a correct client now has a real list to pick from.
- **`created_by_username` is a username string, with no user id.** You cannot join a signatory or template to an `authenticate` user record, render an avatar, or survive a username change. Consistent with every other module in this project, but stated here because nothing else tells you.
- **No bulk reorder.** `display_order` is set one `PATCH` at a time, with no transaction across them — reordering a family of eleven bank templates is eleven independent writes that can half-apply.
- **No lookup-by-key endpoint.** Every route takes the UUID `id`. Holding a `documents.template_key` and wanting its label means listing the catalogue and matching client-side — cheap at 53 rows, but there is no `GET /templates/?key=...` and no `GET /templates/by-key/<key>/`.
- **No template *definition* of any kind.** No sections, no field hints, no signature slots, no layout, no preview, and no version chain. The templates are frontend code; this module knows only that a slug exists, what family it belongs to, and what to call it. `concepts/document_templates.txt` describes a Template Editor, a Template Detail / Version History screen, and a Template Preview — **none of the three has a backing endpoint**, deliberately, because nothing consumes that metadata and inventing a schema for it would guarantee drift from the templates that actually render.
- **~~No signature image storage.~~ Retired 2026-09-10.** This gap read: *"`signature_image_url` is a link to a host this API knows nothing about. No upload endpoint … a `Signatory` is not one of that module's owner types, so there is nowhere to attach a signature even by hand."* All of that is now false — `signatory` is the file module's sixth owner type and §7 has an upload endpoint. What remains true, and is why the gap is rewritten rather than deleted: **`signature_image_url` is still an unvalidated external link** for any signatory that has no uploaded file, with no reachability check and no CDN. If that link rots, the certificate shows a broken image and nothing here reports it. Uploading a real image is the fix, per signatory.
- **Signature bytes cost an authenticated round trip per render.** There is no public URL, no data URI, and no cacheable variant: `download_path` requires the bearer token, forbids browser caching, and writes an audit event on every read. A certificate naming two signers is two authenticated fetches per fresh render. Hold the object URLs for the session — see §8 — because nothing on the server side will do it for you.
- **A reprint that re-renders shows the *current* signature, not the one that was issued.** A snapshot freezes a signer's name and role and never the image, so replacing a signature rewrites the appearance of every past certificate that names that signer, while the frozen name beside it stays historical. **This applies to reprints that re-render from snapshot data.** If your client instead stored a generated PDF against the snapshot (the file module accepts a `snapshot` owner with `category=generated_document`), that PDF is unaffected and will keep showing the original signature — so the two reprint strategies diverge. Neither this module nor `document_history` chooses for you; see `document_history/docs/INTEGRATION.md`. If byte-identical reprints matter, store the rendered PDF or capture the image at print time.
- **No way to tell a never-uploaded signature from a removed one.** `signature_file: null` with `signature_source: "url"` could mean the signature was archived last week or that one was never uploaded. The distinction lives in the `audit` module and in the file module's own list filtered by `?signatory=<id>`, not in this payload.

**The `signature_source` rule, stated exhaustively.** §3 says part of it is invisible to you, which makes a partial list worse than none. It is `"uploaded"` when a linked file exists **and** is neither archived nor superseded; `"url"` when that fails and `signature_image_url` is non-empty; `"none"` otherwise. Exactly two conditions disqualify a linked file, and these are the consequences worth knowing:

- **Archiving the file** disqualifies it, and **restoring it re-qualifies it** — `POST /api/v1/files/<id>/restore/` puts `signature_source` back to `"uploaded"`. Remove is a real undo; the link is never broken, only its validity.
- **Superseding it through the file module directly** (`POST /api/v1/files/<id>/replace/`) disqualifies it permanently, because the successor is a new row the link does not follow. Do not replace a signature that way — use the signature endpoint.
- **Verification state is not consulted.** A signature `rejected` by a reviewer still renders as `"uploaded"`. That is deliberate — `verification_status` is a record of a human judgement, not a gate, and no endpoint in this project consults it — but it means a rejected signature keeps printing on certificates until someone archives it.
- **Missing bytes are not consulted either.** If the storage volume and the database diverge, `signature_source` still reads `"uploaded"` and the fetch 404s. Handle that at the fetch, not the branch.
- **`family` will grow without a version bump.** The six values come from `documents` and a seventh would appear here with no change to this module and no `/api/v2/`. Treat it as an open string.
- **No Bikram Sambat dates and no `?fiscal_year=` filter**, unlike `documents` and `document_history`. Both timestamps here are system bookkeeping on a reference library, not user-facing business dates.
- **401 bodies are not enumerated here.** This contract states *that* a missing, expired, or revoked-session token returns 401 with the `authenticate` module's codes, but not what those codes are — so distinguishing "refresh silently" from "redirect to login" requires that module's contract.
- **The permission keys in §7 are not enforced in the request path.** Every endpoint has one registered and no view consults it; access is decided solely by the `admin` authority check. Do not build a client-side permission gate off those keys expecting the server to agree.
- **The seeded catalogue may not match the real template set.** `seed_document_templates` loads 53 slugs transcribed from the frontend's own contract — whose heading says "42 slugs" and then lists 53. The discrepancy is unresolved. If 42 is correct, eleven seeded rows name templates the frontend cannot render, and a picker built from `?status=active` would offer them.
