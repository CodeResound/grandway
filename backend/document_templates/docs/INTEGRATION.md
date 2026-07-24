# Integration — Document Templates

**Owner app:** `document_templates`
**Version:** 1.1.0
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

**This module writes to nothing outside itself, and nothing outside it writes here.** There is **no foreign key to `documents` in either direction**, and `documents` does not consult this catalogue — see §9, because that has a consequence you need to plan around.

**Two modules reference this one without a foreign key, and neither validates the reference:**

| Referencing module | Where | What it stores |
|---|---|---|
| `documents` | `content.instructorId`, `content.directorId` on certificate templates | This module's `Signatory.id`, as an opaque string inside an unvalidated JSON body |
| `document_history` | `render_context.signatories[].id` on a print snapshot | The same, frozen at print time |

Both stored those ids against a table that did not exist until this module shipped. **What changed is that you now have a real list to pick from. What did not change is that nothing stops either module accepting an id that was never in that list** — see §9.

**One app this module deliberately does not contain, and which now exists:** `uploaded_files` (`/api/v1/files/`) owns file storage. **A signature is still a link, not an upload** — this module was not migrated to it, and a `Signatory` is not one of that module's five owner types, so a signature image cannot be attached there today either. See §3 and §9.

## 3. Conventions

- **Access — Admin only, and unlike the other two document modules this one holds no sensitive data.** `admin` may do everything; `lead_manager` and `superadmin` are refused on **every route including `GET`**. A signatory is a staff member's name and a link to their signature image; a template is a slug and a label. **There is no applicant data in this module at all.** The Admin-only rule is inherited from the consumer — a Lead Manager cannot open a document workspace, so a signatory picker is a screen they can never reach. Hide these screens for them rather than rendering them read-only.
- **Nothing is ever deleted.** There is **no `DELETE` method on any endpoint**. A signatory or template that is no longer current is deactivated and kept, because documents reference a template by plain string and snapshots freeze signatory ids — neither protected by a foreign key.
- **The signature image is a URL you host, not a file you upload.** `signature_image_url` is a plain link. This API stores and returns it verbatim, never fetches it, never validates that it resolves, and has no upload endpoint. If the link rots, every certificate rendered from that signatory shows a broken image and nothing here will tell you.
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

- **HTTP status codes.** Both `POST` collection endpoints (create a signatory, register a template) return **201**. Every other success — all four `GET`s, both `PATCH`es, and both `POST .../status/` actions — returns **200**. A status action is 200 rather than 201 because it creates no resource; it returns the resource it changed. Domain-rule violations are **400** — **this module has no 409 at all**, because no operation here can conflict with another's state. Missing records named in the URL path are **404**. Authority failures are **403**. An unrouted method is **405** with the project-wide `METHOD_NOT_ALLOWED` code, still inside the standard envelope.
- **Query parameter encoding.** A **recognised** parameter with an invalid value is **rejected with 400**: `?status=enabled` returns a validation error rather than an unfiltered result set. An **unrecognised** parameter is **silently ignored** — `?foo=1`, and in particular a cache-busting `?_=1721815262`, is accepted and has no effect. `page_size` above the 100 maximum is **clamped, not rejected**. There is no multi-value syntax: `?status=draft,active` is one invalid value, not two valid ones, and returns 400.
- **Request encoding:** `application/json`.
- **Pagination:** page-number based, and the **default page size is 20** — so the 53-row template catalogue is three requests, not one. Pass `?page_size=100` to mirror it locally in a single call, and re-check that when the catalogue passes 100 rows, because the maximum clamps silently. `page` and `page_size` (default 20, max 100). `data` is the **bare array of rows — not nested under a `results` key**. `meta` carries `count`, `page`, `page_size`, `next`, `previous`; `count` is the **total across all pages**, not the rows in `data`. `next`/`previous` are absolute URLs (scheme + host) or `null`. Applied to both list endpoints.
- **IDs:** UUID strings, unquoted and unmarked in the shapes below — a field with no type marker is a string. A template's `key` is a human-readable slug and is unique, but **it is not an address**: every endpoint here takes the UUID `id` in its path. There is no lookup-by-key endpoint — see §9.
- **Ordering** is fixed and **not client-controllable** — there is no `sort` or `ordering` parameter. Signatories are ordered by `name` (alphabetical). Templates by `family`, then `display_order`, then `label`.
- **Times.** `created_at` and `updated_at` are ISO 8601 UTC. **Neither carries a Bikram Sambat sibling anywhere in this module** — unlike `documents` and `document_history`, which expose `archived_at_bs` and `created_at_bs`. §39.4 requires BS representation for *user-facing temporal data*; both timestamps here are system-internal bookkeeping on a reference library, and there is no business date on either resource. There is also **no `?fiscal_year=` filter** on either list, for the same reason.
- **Empty text fields are `""`, never `null`.** **No field on either resource is nullable.**

## 4. Models

**Signatory** — `{ id, name, title, role, signature_image_url, status:[enum], is_active, status_note, created_by_username, created_at, updated_at }`

- **One shape for list and detail** — there is no large column to withhold from a list, so a second shape would exist only to drift from this one.
- **`is_active` is `status == "active"`.** A `draft` signatory is *not* active. This is the boolean to gate a picker on.
- **`role` is free text, not an enum** — see §5.
- **`signature_image_url` may be `""`.** A signatory can exist without a signature image, and one in `draft` usually does.

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
- `name` — string, optional, max 255.
- `name` — string, optional. Derived from `name` when omitted; a supplied value is kept.
- `title`, `title` — string, optional, max 255.
- `role` — string, optional, max 100.
- `signature_image_url` — URL, optional, max 500.

**Send (update):** any subset of the same fields. `name` is optional here.

**Returns:** `Signatory` from create — **201** — and from retrieve and update — **200**; `list[Signatory]` from the library — **200**.

**Requires state:** nothing. This resource has no prerequisites of any kind.

**Side effects:**

- Create and update each append one `audit` event. **Nothing outside this module changes** — in particular, no document or snapshot that already names a signatory is touched by editing them.
- **Renaming a signatory retroactively changes what every past document appears to say**, because `documents` stores only the id and resolves the name at render time. A snapshot is the exception: `document_history` froze the name at print time and still shows the old one. That divergence is intended — the snapshot records what was issued — but it will look like a bug if you do not expect it.
- Retrieve and list have **no** side effects.

**Notes:**

- **A new signatory is always `draft`.** There is no `status` field on create; activate it with the status action. A picker filtered to `?status=active` will not show a signatory you just created.
- **`status` is rejected on `PATCH`, not ignored** — 400 `DOCUMENT_TEMPLATES_STATUS_INVALID_TRANSITION`. Use the status action.
- **Omitting `status` returns everything** — draft, active, and inactive alike. There is no implicit `active` default. That is what a management screen wants and the opposite of what a picker wants, so the picker must pass `?status=active` explicitly.
- **Query parameters:** `status`, `role` (exact, case-insensitive), `search`, `page`, `page_size`. `search` matches all three name forms; it does **not** match `title` or `role`.

**Errors:**

- `DOCUMENT_TEMPLATES_ACTOR_FORBIDDEN` (403) — the caller is not an Admin. Applies to every method in this block, `GET` included
- `DOCUMENT_TEMPLATES_SIGNATORY_NOT_FOUND` (404) — no signatory with that id
- `DOCUMENT_TEMPLATES_STATUS_IMMUTABLE` (400) — a `PATCH` carried `status` or `status_note`
- `VALIDATION_ERROR` (400) — missing `name`, a malformed `signature_image_url`, an over-long field, or an unrecognised `status` in the query string

### Signatory status — `POST /signatories/<signatory_id>/status/`

**Use it when:** activating a new signer once their signature image is in place, or retiring one who has left.

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

1. `POST /api/v1/document-templates/signatories/` with `name`, `name`, `title`, `role`, and `signature_image_url` → `Signatory`, `status: "draft"`.
   - *Failure — `VALIDATION_ERROR` on `name`:* the name is required.
   - *Failure — `VALIDATION_ERROR` on `signature_image_url`:* it must be a well-formed URL. Host the image yourself first — there is no upload endpoint.
2. `POST /api/v1/document-templates/signatories/<id>/status/` with `{"status": "active"}` → now `is_active: true`.
3. `GET /api/v1/document-templates/signatories/?status=active` → the signer now appears in the picker.

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
- **No signature image storage.** `signature_image_url` is a link to a host this API knows nothing about. No upload endpoint, no size or type validation, no reachability check, no CDN. **`uploaded_files` shipped on 2026-07-24 and this field was deliberately not migrated to it** — repointing it would change a shipped response shape, and a `Signatory` is not one of that module's owner types, so there is nowhere to attach a signature even by hand. If the link rots, every certificate rendered from that signatory shows a broken image and nothing here will report it.
- **`role` is unconstrained free text.** Two values are in use (`director`, `instructor`) because that is what the certificate templates read, but any 100-character string is accepted. Do not build a closed dropdown from what you observe; do not assume a signatory's `role` matches the slot you are filling.
- **`family` will grow without a version bump.** The six values come from `documents` and a seventh would appear here with no change to this module and no `/api/v2/`. Treat it as an open string.
- **No Bikram Sambat dates and no `?fiscal_year=` filter**, unlike `documents` and `document_history`. Both timestamps here are system bookkeeping on a reference library, not user-facing business dates.
- **401 bodies are not enumerated here.** This contract states *that* a missing, expired, or revoked-session token returns 401 with the `authenticate` module's codes, but not what those codes are — so distinguishing "refresh silently" from "redirect to login" requires that module's contract.
- **The permission keys in §7 are not enforced in the request path.** Every endpoint has one registered and no view consults it; access is decided solely by the `admin` authority check. Do not build a client-side permission gate off those keys expecting the server to agree.
- **The seeded catalogue may not match the real template set.** `seed_document_templates` loads 53 slugs transcribed from the frontend's own contract — whose heading says "42 slugs" and then lists 53. The discrepancy is unresolved. If 42 is correct, eleven seeded rows name templates the frontend cannot render, and a picker built from `?status=active` would offer them.
